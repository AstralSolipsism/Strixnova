from copy import deepcopy
import pytest

from strixnova.prepared_input import (
    PreparedInputError, assemble, check_context, evidence_catalog,
    prepare, result_requirements, schema_issues,
)
from strixnova.public_input_contract import input_contract_for
from strixnova.actual_result import validate_actual_result
from strixnova.host_adapter import HostAdapterError, LocalHostAdapter
from strixnova.workflow_authority import WorkflowAuthority
from tests.unit.test_host_adapter import _stable_direction


def _result_context():
    target = {"schema_version": "strixnova.domain-fact-reference.v1", "authority_kind": "project_domain_model",
              "model_id": "MODEL-1111111111111111", "fact_id": "FACT-1111111111111111", "observed_commit": "a" * 40}
    assessment = {"domain_fact_changes": [{"target_ref": target, "disposition": "introduce"}],
                  "method_applications": []}
    plan = {"applicable_rules": [{"rule_id": "RULE-1"}], "operations": [], "verification_targets": []}
    current = {"work_item_id": "WI-1", "version": 7, "data": {"engineering": {"assessment": assessment, "plan": plan}},
               "current_action": {"action_type": "present_actual_result", "intent": "delivery",
                                  "input_kind": "actual_result", "input_contract_ref": "input.contract:present_actual_result"}}
    coverage = {"verification_status": "passed", "latest_receipt_ids": {}}
    template = result_requirements(current, coverage, "review-subject:" + "a" * 64)
    return prepare(current, input_contract_for(current["current_action"]), project="fixture", result=template), current, coverage


def _answers():
    return {"fields": {"effect_summary": "Implemented", "delivered_outcomes": ["Explicit result"], "deviations": [], "limitations": []},
            "answers": {
                "fact:FACT-1111111111111111": {"outcome": "realized", "evidence_refs": [{"kind": "delivered_outcomes", "key": 0}], "limitations": []},
                "rule:RULE-1": {"status": "satisfied", "evidence_refs": [{"kind": "delivered_outcomes", "key": 0}], "gaps": [], "remediation_actions": [], "limitations": []}}}


def test_result_preparation_assembles_fixed_identity_and_requires_semantic_answers():
    context, current, coverage = _result_context()
    payload = assemble(context, {})
    assert "outcome" not in payload["domain_fact_change_results"][0]
    assert "status" not in payload["governance_rule_results"][0]
    assert len(schema_issues(context, payload)) >= 5
    payload = assemble(context, _answers())
    assert schema_issues(context, payload) == []
    # Real result validator is the reference, not an imitation in the adapter.
    result = validate_actual_result(payload, coverage,
        planned_domain_fact_changes=current["data"]["engineering"]["assessment"]["domain_fact_changes"],
        planned_governance_rules=current["data"]["engineering"]["plan"]["applicable_rules"],
        planned_verification_targets=[])
    assert result["domain_fact_change_results"][0]["target_ref"] == context["template"]["domain_fact_change_results"][0]["target_ref"]
    assert result["semantic_content_machine_proven"] is False


def test_evidence_catalog_keeps_stage_and_version_and_reports_all_bad_refs():
    context, _, _ = _result_context()
    entry = evidence_catalog(context, _answers()["fields"])[0]
    assert entry["ref"] == "delivered_outcomes[0]"
    assert entry["owner"] == {"work_item_id": "WI-1", "work_item_version": 7}
    value = _answers()
    value["answers"]["fact:FACT-1111111111111111"]["evidence_refs"] = ["direction", "SRC-1"]
    with pytest.raises(PreparedInputError) as caught:
        assemble(context, value)
    assert len(caught.value.details) == 2


def test_groups_are_explicit_cannot_override_metadata_or_fill_missing_items():
    context, _, _ = _result_context()
    with pytest.raises(PreparedInputError, match="fixed"):
        assemble(context, {"answers": {"fact:FACT-1111111111111111": {"target_ref": {}}}})
    grouped = {"fields": _answers()["fields"], "groups": [{"items": ["fact:FACT-1111111111111111"], "values": _answers()["answers"]["fact:FACT-1111111111111111"]}]}
    result = assemble(context, grouped)
    assert result["domain_fact_change_results"][0]["outcome"] == "realized"
    assert "status" not in result["governance_rule_results"][0]
    grouped["groups"][0]["items"].append("fact:FACT-1111111111111111")
    with pytest.raises(PreparedInputError):
        assemble(context, grouped)


def test_context_is_immutable_and_cannot_be_refreshed_at_submission():
    context, _, _ = _result_context()
    changed = deepcopy(context)
    changed["binding"]["work_item_version"] += 1
    with pytest.raises(PreparedInputError) as caught:
        check_context(context, changed)
    assert caught.value.code == "prepared_input_stale"


def test_adapter_preparation_is_read_only_and_confirmation_uses_exact_raw_message(tmp_path):
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="Example", raw_request="Example request")
    identifier = item["work_item_id"]
    authority.transition(identifier, "submit_direction", {"direction": _stable_direction(goal="Goal", scope=["Scope"], acceptance=["Evidence"]), "ready_for_confirmation": True}, expected_version=item["version"])
    adapter = LocalHostAdapter(tmp_path)
    context = adapter.prepare_input(identifier)
    version = authority.get(identifier)["version"]
    blank = adapter.preview_input(context, {})
    assert not blank["ok"]
    assert authority.get(identifier)["version"] == version
    raw = "  Confirm this scope.\r\nOnly this scope.\r\n"
    reply = {"fields": {"agent_decision": {"decision": "accept", "reason": "Explicit fixture interpretation"}}}
    assert adapter.preview_input(context, reply, user_message=raw)["ok"]
    applied = adapter.apply_input(context, reply, user_message=raw)
    assert applied["next"]["work_item_version"] == version + 1
    assert authority.get(identifier)["data"]["direction_confirmation"]["user_confirmation"] == raw
    with pytest.raises(HostAdapterError) as caught:
        adapter.apply_input(context, reply, user_message=raw)
    assert caught.value.code == "prepared_input_stale"


def test_revisions_keep_the_selected_base_and_require_explicit_keep_rest():
    from strixnova.prepared_input import revise_prepared
    context = {"revision_bases": {"assessment": {"assessment_id": "EA-1", "assessment_revision": 2,
               "direction_ref": {"work_item_id": "WI-1", "direction_version": 3}, "unchanged": ["preserve"], "owner_view": {"summary": "before"}}},
               "revision_direction_ref": {"work_item_id": "WI-1", "direction_version": 8}}
    edit = {"kind": "assessment", "keep_rest": True, "changes": [{"op": "replace", "path": "/owner_view/summary", "value": "after"}]}
    result = revise_prepared(context, edit)
    assert result["unchanged"] == ["preserve"]
    assert result["assessment_id"] == "EA-1" and result["assessment_revision"] == 3
    assert result["direction_ref"]["direction_version"] == 8
    assert context["revision_bases"]["assessment"]["owner_view"]["summary"] == "before"
    edit["keep_rest"] = False
    with pytest.raises(PreparedInputError):
        revise_prepared(context, edit)
    edit["keep_rest"] = True
    edit["changes"][0]["path"] = "/assessment_revision"
    with pytest.raises(PreparedInputError) as caught:
        revise_prepared(context, edit)
    assert caught.value.code == "prepared_binding_override"


def test_selected_material_is_complete_without_cursor_assembly_and_detects_drift(tmp_path, monkeypatch):
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="A", raw_request="long request " * 2000)
    adapter = LocalHostAdapter(tmp_path)
    material = adapter.read_materials(item["work_item_id"], record_refs=["request"])
    assert material["reading"]["complete"]
    assert material["records"]["request"]["raw_request"] == item["data"]["raw_request"]
    original = adapter.next_step
    count = 0
    def changed(*args, **kwargs):
        nonlocal count
        count += 1
        value = original(*args, **kwargs)
        if count == 2:
            value["records"]["request"]["raw_request"] = "concurrent edit"
        return value
    monkeypatch.setattr(adapter, "next_step", changed)
    with pytest.raises(HostAdapterError) as caught:
        adapter.read_materials(item["work_item_id"], record_refs=["request"])
    assert caught.value.code == "record_read_source_changed"


def test_inspection_does_not_hide_large_child_values():
    from strixnova.prepared_input import inspect_material
    import json
    document = {"small": "read", "large": {"body": "x" * 900}}
    value = inspect_material(document, "", 512)
    assert not value["complete"]
    assert value["unexpanded"] == ["/large"]
    assert len(json.dumps(value, indent=2).encode()) <= 512
    assert inspect_material(document, "/large/body", 2000)["value"] == "x" * 900


def test_batch_authority_registration_stops_before_review_and_reports_partial_failure(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    from strixnova.application_coordinator import ApplicationCoordinatorError
    adapter = object.__new__(LocalHostAdapter)
    calls = []
    context = {"binding": {"work_item_id": "WI-1", "work_item_version": 7,
               "action": {"action_type": "author_project_authority_candidate", "authority_kind": "product_definition"}}}
    def candidate(identifier, kind, *, expected_version):
        calls.append((kind, expected_version))
        if kind == "domain_model":
            raise ApplicationCoordinatorError("candidate_not_ready", "Missing candidate")
        return {"presented_at_work_item_version": 8, "current_action": {"action_type": "author_project_authority_candidate", "authority_kind": "domain_model"}}
    adapter.coordinator = SimpleNamespace(read_operation=nullcontext, project_authority_candidate=candidate)
    monkeypatch.setattr(adapter, "_check_prepared_input", lambda value: None)
    monkeypatch.setattr(adapter, "next_step", lambda identifier: {"work_item_version": 8})
    report = adapter.present_authorities(context, ["product_definition", "domain_model", "target_architecture"])
    assert not report["ok"] and report["stopped"]["code"] == "candidate_not_ready"
    assert len(report["presented"]) == 1
    assert calls == [("product_definition", 7), ("domain_model", 8)]
    context["binding"]["action"] = {"action_type": "review_project_authority_candidates"}
    calls.clear()
    report = adapter.present_authorities(context, ["product_definition"])
    assert report["stopped"]["code"] == "authority_batch_boundary" and not calls


def test_snapshot_observations_leave_uncaptured_scope_and_retest_undecided():
    from strixnova.project_content_snapshot import compose_content_snapshot, content_fingerprint, snapshot_observations
    def snapshot(paths):
        return compose_content_snapshot("PLAN-1", [{"repository_id": None, "paths": paths, "content_sha256": content_fingerprint(paths)}])
    a = {"path": "a.py", "state": "file", "sha256": "a" * 64}
    b = {"path": "b.py", "state": "file", "sha256": "b" * 64}
    original = snapshot([a, b])
    observed = snapshot([{**a, "sha256": "c" * 64}, b, {**b, "path": "new.py"}])
    facts = snapshot_observations(original, observed)
    assert facts["changed"] == ["_:a.py"] and facts["unchanged"] == ["_:b.py"]
    assert facts["uncaptured"] == ["_:new.py"] and "needs_retest" not in facts
    assert facts["outside_captured_scope"] == "unknown"
    changed_again = snapshot([{**a, "sha256": "d" * 64}, b, {**b, "path": "new.py"}])
    later = snapshot_observations(original, changed_again)
    assert facts["changed"] == later["changed"]
    assert facts["observed_content_sha256"] != later["observed_content_sha256"]
    assert not snapshot_observations(None, observed)["comparison_available"]
    assert snapshot_observations(original, None)["unchanged"] == []


def test_case_preflight_reports_root_and_exact_node_mismatches_together(tmp_path):
    import hashlib
    from strixnova.test_case_evidence import REPORT_SCHEMA, adapter_path, preflight_case_report
    from tests.support.behavior_examples import case_config
    config = case_config(["test_behavior.py::test_other_remains"])
    report = {"schema_version": REPORT_SCHEMA, "run_id": "collection-1", "adapter": "pytest",
              "adapter_sha256": hashlib.sha256(adapter_path().read_bytes()).hexdigest(), "framework_version": "8.0", "python_version": "3.12",
              "test_root": str(tmp_path.parent), "collection_complete": True, "session_finished": True, "exit_status": 0,
              "collected_test_ids": ["test_behavior.py::TestScope::test_other_remains"], "deselected_test_ids": [], "collection_errors": [], "results": []}
    before = deepcopy(config)
    result = preflight_case_report(report, config=config, execution_root=tmp_path)
    assert not result["ok"] and len(result["issues"]) == 2
    assert result["unmatched"][0]["status"] == "not_collected"
    assert result["execution_performed"] is False and config == before
    report["test_root"] = str(tmp_path)
    config["bindings"][0]["test_ids"] = list(report["collected_test_ids"])
    assert preflight_case_report(report, config=config, execution_root=tmp_path)["ok"]


def test_prepared_cli_keeps_identity_in_file_and_refuses_stale_context(tmp_path):
    import json
    from click.testing import CliRunner
    from strixnova.cli import main
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="Example", raw_request="Example request")
    identifier = item["work_item_id"]
    authority.transition(identifier, "submit_direction", {"direction": _stable_direction(goal="Goal", scope=["Scope"], acceptance=["Evidence"]), "ready_for_confirmation": True}, expected_version=item["version"])
    runner = CliRunner()
    context = tmp_path / "prepared.json"
    source = tmp_path / "message.txt"
    source.write_bytes("Confirm only this scope.\r\n".encode())
    response = runner.invoke(main, ["action", "prepare", "--project-dir", str(tmp_path), "--work-item-id", identifier, "--output", str(context)])
    assert response.exit_code == 0, response.output
    reply = json.dumps({"fields": {"agent_decision": {"decision": "accept", "reason": "Explicit fixture decision"}}})
    args = ["action", "apply", "--project-dir", str(tmp_path), "--context", str(context), "--input", reply, "--user-message-file", str(source)]
    response = runner.invoke(main, args)
    assert response.exit_code == 0, response.output
    response = runner.invoke(main, args)
    assert response.exit_code == 1
    assert json.loads(response.output)["error"]["code"] == "prepared_input_stale"


def test_slice_binding_is_derived_from_the_existing_action_reference():
    action = {"action_type": "complete_implementation_slice", "intent": "submit", "input_kind": "implementation_slice_completion",
              "input_contract_ref": "input.contract:complete_implementation_slice", "record_refs": ["engineering.plan.implementation_slice:SLICE-1"]}
    context = prepare({"work_item_id": "WI-1", "version": 4, "current_action": action, "data": {}}, input_contract_for(action), project="fixture")
    assert assemble(context, {"fields": {"completion_summary": "Explicit review done"}})["slice_id"] == "SLICE-1"


def test_preflight_combines_independent_reference_and_missing_field_errors(monkeypatch):
    from contextlib import nullcontext
    from types import SimpleNamespace
    context, _, _ = _result_context()
    adapter = object.__new__(LocalHostAdapter)
    adapter.coordinator = SimpleNamespace(read_operation=nullcontext)
    monkeypatch.setattr(adapter, "_check_prepared_input", lambda _: None)
    result = adapter.preview_input(context, {"answers": {"fact:FACT-1111111111111111": {"evidence_refs": ["direction", "SRC-1"]}}})
    assert not result["ok"]
    assert sum(issue["code"] == "unknown_result_evidence" for issue in result["issues"]) == 2
    assert any(issue["code"] == "schema_required" for issue in result["issues"])


def test_alignment_cli_carries_preparation_binding_without_model_copy(tmp_path):
    import json
    import yaml
    from click.testing import CliRunner
    from strixnova.cli import main
    from tests.unit.test_implementation_alignment_preparation import _complete_project, _persist_current_authority, ALIGNMENT_PREPARATION_REQUEST_SCHEMA
    current, baseline = _complete_project(tmp_path)
    current = _persist_current_authority(tmp_path, current)
    alignment = yaml.safe_load((tmp_path / baseline["authority_refs"]["implementation_alignment"]["path"]).read_text(encoding="utf-8"))
    request = {"schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA, "alignment_revision_id": "ALIGNREV-ABCDABCDABCDABCD",
               "supersedes_revision_id": alignment["revision"]["revision_id"]}
    runner = CliRunner()
    output = tmp_path / "alignment-context.json"
    result = runner.invoke(main, ["alignment", "prepare", "--project-dir", str(tmp_path), "--work-item-id", current["work_item_id"],
        "--version", str(current["version"]), "--input", json.dumps(request), "--output", str(output)])
    assert result.exit_code == 0, result.output
    saved = json.loads(output.read_text(encoding="utf-8"))
    inspect_args = ["alignment", "inspect", "--project-dir", str(tmp_path), "--prepared", str(output)]
    result = runner.invoke(main, inspect_args)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["alignment"]["preparation_ref"] == saved["preparation_ref"]
    material = tmp_path / ".strixnova" / "artifacts" / "agent-inputs" / "alignment-material.json"
    result = runner.invoke(main, [*inspect_args, "--limit", "10", "--output", str(material)])
    assert result.exit_code == 0, result.output
    assembled = json.loads(material.read_text(encoding="utf-8"))
    assert assembled["reading"]["complete"]
    assert len(assembled["items"]) == assembled["reading"]["item_count"]
    assert assembled["preparation_ref"] == saved["preparation_ref"]
    result = runner.invoke(main, [*inspect_args, "--version", str(current["version"])])
    assert result.exit_code != 0


def test_exploration_result_uses_the_existing_result_validator_route(tmp_path, monkeypatch):
    from strixnova.application_coordinator import ApplicationCoordinator
    coordinator = ApplicationCoordinator(tmp_path)
    created = coordinator.authority.create(title="Explore", raw_request="Inspect current state")
    identifier, version = created["work_item_id"], created["version"]
    current = {**created, "status": "exploring", "current_action": {"action_type": "investigate_and_report"}}
    monkeypatch.setattr(coordinator, "_current_for_effect", lambda *a, **kw: current)
    monkeypatch.setattr(coordinator, "_require_current_work_item_direction_context", lambda *a: None)
    calls = []
    monkeypatch.setattr(coordinator, "present_actual_result", lambda *a, **kw: calls.append((a, kw)) or (current, {"checked": True}))
    value = {"effect_summary": "Explicit result"}
    report = coordinator.delivery(identifier, value, expected_version=version)
    assert report["steps"] == ["actual_result_presented"]
    assert calls == [((identifier, value), {"expected_version": version})]


def test_checklist_pending_fields_exclude_generated_nested_rows():
    context, current, coverage = _result_context()
    current["data"]["engineering"]["assessment"]["method_applications"] = [{"method_id": "METHOD-1", "decision": "applied", "planned_uses": [{"use_id": "USE-1"}]}]
    context = prepare(current, context["contract"], project="fixture", result=result_requirements(current, coverage, "review-subject:" + "a" * 64))
    method = next(row for row in context["checklist"] if row["id"] == "method:METHOD-1")
    assert method["pending_fields"] == ["deviations"]
    use = next(row for row in context["checklist"] if row["id"] == "use:METHOD-1/USE-1")
    assert set(use["pending_fields"]) == {"status", "outcome", "evidence_refs"}


def test_malformed_result_lists_reach_preflight_as_schema_errors():
    context, _, _ = _result_context()
    payload = assemble(context, {"fields": {"delivered_outcomes": None, "limitations": False}})
    errors = schema_issues(context, payload)
    assert any(error["path"] == ["delivered_outcomes"] for error in errors)
    assert any(error["path"] == ["limitations"] for error in errors)



def test_protocol_constants_are_filled_without_deciding_readiness(tmp_path):
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="Example", raw_request="Example request")
    context = LocalHostAdapter(tmp_path).prepare_input(item["work_item_id"])
    direction = _stable_direction(goal="Goal", scope=["Scope"], acceptance=["Evidence"])
    del direction["schema_version"]
    value = assemble(context, {"fields": {"direction": direction}})
    assert value["direction"]["schema_version"] == "strixnova.direction-decision.v1"
    assert "ready_for_confirmation" not in value
    assert any(error["code"] == "schema_required" for error in schema_issues(context, value))
