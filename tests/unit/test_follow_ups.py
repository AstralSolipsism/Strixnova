from copy import deepcopy
import json
from pathlib import Path

from click.testing import CliRunner
import pytest

from strixnova.actual_result import validate_actual_result
from strixnova.cli import main
from strixnova.host_adapter import LocalHostAdapter
from strixnova.follow_ups import FollowUpError, declared_refs, project_records, validate_items, validate_results
from strixnova.work_item_read_model import WorkItemReadModel
from strixnova.workflow_authority import InvalidTransition, WorkflowAuthority, WorkflowAuthorityError
from tests.support.governance_assessment import direction_fixture


def item(identifier="FOLLOWUP-1111111111111111", *, accepted=False):
    return {"follow_up_id": identifier, "limitation_refs": ["limitations[0]"], "disposition": "accepted_limitation" if accepted else "deferred", "reason": "Explicit owner-selected scope", "responsible_party": None if accepted else "project maintainer", "due_on": None if accepted else "2020-01-01", "review_condition": None if accepted else "Review before the next capacity increase", "completion_criteria": None if accepted else "Measure the stated capacity and record the result"}


def confirm(authority, current, *, accepted=True):
    action = authority.get(current["work_item_id"])["current_action"]
    return authority.transition(current["work_item_id"], action["action_type"], {"candidate_fingerprint": action["confirmation_challenge"]["candidate_fingerprint"], "user_confirmation": "Proceed" if accepted else "Please revise", "agent_decision": {"decision": "accept" if accepted else "request_changes", "reason": "Explicit synthetic owner decision"}}, expected_version=current["version"])


def start(authority, refs=(), *, related_to=None):
    current = authority.create(title="Owned deferred-work fixture", raw_request="Investigate the stated issue")
    direction = direction_fixture()
    if refs or related_to:
        direction["work_item_relations"] = [{"target_work_item_id": refs[0]["work_item_id"] if refs else related_to, "relation_type": "follows_up", "reason": "Resolve the carried finding", **({"follow_up_refs": list(refs)} if refs else {})}]
    current = authority.transition(current["work_item_id"], "submit_direction", {"direction": direction, "ready_for_confirmation": True, "blockers": []}, expected_version=current["version"])
    current = confirm(authority, current)
    current = authority.transition(current["work_item_id"], "submit_engineering_assessment", {"assessment": {"assessment_id": "EA-test", "assessment_revision": 1, "verification_commands": []}, "plan": {"plan_id": "PLAN-test", "change_context": {"formal_implementation": False}, "verification_commands": [], "verification_targets": []}}, expected_version=current["version"])
    return confirm(authority, current)


def present(authority, current, *, new_items=(), resolutions=()):
    value = {"schema_version": "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64, "effect_summary": "Recorded observed evidence and the remaining limit", "delivered_outcomes": ["Explicit fixture observation"], "deviations": [], "limitations": ["Capacity has not yet been measured"], "verification_receipt_ids": [], "long_lived_refs": [], "method_application_results": [], "governance_rule_results": [], "follow_up_items": list(new_items), "follow_up_results": list(resolutions), "semantic_content_machine_proven": False}
    value = validate_actual_result(value, {"verification_status": "not_required", "latest_receipt_ids": {}}, planned_verification_targets=[], planned_follow_up_refs=declared_refs(current["data"]["direction"]))
    return authority.transition(current["work_item_id"], "present_actual_result", {"actual_result": value}, expected_version=current["version"])


def resolution(record, outcome="resolved"):
    return {"follow_up_ref": record["follow_up_ref"], "expected_version": record["version"], "outcome": outcome, "rationale": "Review explicitly addresses the original limit", "evidence_refs": ["delivered_outcomes[0]"], "limitation_refs": [] if outcome == "resolved" else ["limitations[0]"]}


def test_only_accepted_results_publish_obligations_and_cli_query_is_read_only(tmp_path: Path):
    authority = WorkflowAuthority(tmp_path)
    current = present(authority, start(authority), new_items=[item()])
    assert WorkItemReadModel(tmp_path).follow_ups()["items"] == []
    current = confirm(authority, current)
    assert current["status"] == "completed"
    before = authority.revision()
    response = CliRunner().invoke(main, ["status", "--project-dir", str(tmp_path), "--follow-ups"])
    assert response.exit_code == 0, response.output
    record = json.loads(response.output)["follow_ups"]["items"][0]
    assert record["state"] == "open"
    assert record["date_attention"] == "due"
    assert record["condition_requires_agent_review"] is True
    assert authority.revision() == before
    fresh = authority.create(title="Read follow-ups", raw_request="Inspect pending work")
    view = LocalHostAdapter(tmp_path).next_step(fresh["work_item_id"], record_refs=["project.follow_ups"])
    assert view["records"]["project.follow_ups"]["total"] == 1


def test_related_completion_alone_does_not_resolve_and_exact_accepted_outcome_does(tmp_path: Path):
    authority = WorkflowAuthority(tmp_path)
    parent = confirm(authority, present(authority, start(authority), new_items=[item()]))
    reader = WorkItemReadModel(tmp_path)
    record = reader.follow_ups()["items"][0]
    parent_history = authority.history(parent["work_item_id"])
    generic_child = confirm(authority, present(authority, start(authority, related_to=parent["work_item_id"])))
    assert generic_child["status"] == "completed"
    assert reader.follow_ups()["total"] == 1
    child = start(authority, [record["follow_up_ref"]])
    with pytest.raises(FollowUpError) as missing:
        validate_results([], expected_refs=[record["follow_up_ref"]], known_evidence=set(), limitations=[])
    assert missing.value.code == "follow_up_results_missing"
    child = present(authority, child, resolutions=[resolution(record)])
    assert reader.follow_ups()["total"] == 1
    child = confirm(authority, child)
    assert child["status"] == "completed"
    assert reader.follow_ups()["total"] == 0
    assert reader.follow_ups(include_closed=True)["items"][0]["state"] == "resolved"
    assert authority.history(parent["work_item_id"]) == parent_history


def test_concurrent_resolution_is_rechecked_inside_confirmation_transaction(tmp_path: Path):
    authority = WorkflowAuthority(tmp_path)
    confirm(authority, present(authority, start(authority), new_items=[item()]))
    reader = WorkItemReadModel(tmp_path)
    original = reader.follow_ups()["items"][0]
    first, second = start(authority, [original["follow_up_ref"]]), start(authority, [original["follow_up_ref"]])
    first = present(authority, first, resolutions=[resolution(original, "partially_resolved")])
    second = present(authority, second, resolutions=[resolution(original)])
    confirm(authority, first)
    before = authority.get(second["work_item_id"])
    with pytest.raises(InvalidTransition) as caught:
        confirm(authority, second)
    assert caught.value.code == "follow_up_conflict"
    assert authority.get(second["work_item_id"]) == before
    assert reader.follow_ups()["items"][0]["latest_resolution"]["outcome"] == "partially_resolved"


def test_accepting_a_limitation_finishes_followup_without_creating_a_task(tmp_path: Path):
    authority = WorkflowAuthority(tmp_path)
    confirm(authority, present(authority, start(authority), new_items=[item(accepted=True)]))
    reader = WorkItemReadModel(tmp_path)
    assert len(authority.list()) == 1
    assert reader.follow_ups()["total"] == 0
    assert reader.follow_ups(include_closed=True)["items"][0]["state"] == "accepted_limitation"


def test_rejected_origin_and_cancelled_assignee_do_not_change_accepted_obligations(tmp_path: Path):
    authority = WorkflowAuthority(tmp_path)
    candidate = present(authority, start(authority), new_items=[item()])
    rejected = confirm(authority, candidate, accepted=False)
    reader = WorkItemReadModel(tmp_path)
    assert reader.follow_ups()["total"] == 0
    parent = confirm(authority, present(authority, rejected, new_items=[item()]))
    ref = reader.follow_ups()["items"][0]["follow_up_ref"]
    child = start(authority, [ref])
    authority.transition(child["work_item_id"], "cancel_work_item", {"reason": "Stop this investigation", "has_unmerged_work": False}, expected_version=child["version"])
    assert reader.follow_ups()["items"][0]["state"] == "open"
    wrong = {**ref, "result_version": ref["result_version"] + 1}
    with pytest.raises(InvalidTransition) as caught:
        start(authority, [wrong])
    assert caught.value.code == "follow_up_not_open"
    assert authority.get(parent["work_item_id"])["status"] == "completed"


def test_empty_query_does_not_initialize_and_pagination_detects_changes(tmp_path: Path):
    reader = WorkItemReadModel(tmp_path)
    assert reader.follow_ups()["total"] == 0
    assert not (tmp_path / ".strixnova").exists()
    authority = WorkflowAuthority(tmp_path)
    for _ in range(2):
        confirm(authority, present(authority, start(authority), new_items=[item()]))
    first = reader.follow_ups(limit=1)
    assert first["next_cursor"]
    assert reader.follow_ups(limit=1, cursor=first["next_cursor"])["items"][0]["follow_up_ref"] != first["items"][0]["follow_up_ref"]
    authority.create(title="Change snapshot", raw_request="Read only")
    with pytest.raises(WorkflowAuthorityError) as caught:
        reader.follow_ups(limit=1, cursor=first["next_cursor"])
    assert caught.value.code == "follow_up_cursor_stale"


def test_cursor_cannot_cross_projects_with_the_same_event_revision(tmp_path: Path):
    projects = [tmp_path / name for name in ("one", "two")]
    for project in projects:
        project.mkdir()
        authority = WorkflowAuthority(project)
        for _ in range(2):
            confirm(authority, present(authority, start(authority), new_items=[item()]))
    first = WorkItemReadModel(projects[0]).follow_ups(limit=1)
    other = WorkItemReadModel(projects[1])
    assert other.follow_ups(limit=1)["revision"] == first["revision"]
    with pytest.raises(WorkflowAuthorityError) as caught:
        other.follow_ups(limit=1, cursor=first["next_cursor"])
    assert caught.value.code == "follow_up_cursor_stale"


@pytest.mark.parametrize("field", ["responsible_party", "completion_criteria", "due_on", "limitation_refs"])
def test_deferred_items_require_an_owner_trigger_and_exact_source(field):
    value = deepcopy(item())
    if field == "limitation_refs": value[field] = ["limitations[9]"]
    elif field == "due_on": value[field], value["review_condition"] = None, None
    else: value[field] = None
    with pytest.raises(FollowUpError): validate_items([value], ["Existing limit"])


def test_unknown_result_contract_cannot_establish_promises():
    records = [
        {"sequence": 1, "version": 6, "work_item_id": "WI-old", "facts": {"candidate": {"kind": "actual_result", "fingerprint": "original", "value": {"schema_version": "strixnova.actual-result.v999", "limitations": ["Maybe follow up later"], "follow_up_items": [item()]}}}},
        {"sequence": 2, "version": 7, "work_item_id": "WI-old", "facts": {"decision": {"kind": "actual_result", "accepted": True, "candidate_fingerprint": "original"}}},
    ]
    assert project_records(records) == {}


@pytest.mark.parametrize("schema", ["strixnova.actual-result.v1"])
def test_recorded_follow_up_promises_keep_their_original_result_contract(schema):
    records = [
        {"sequence": 1, "version": 6, "work_item_id": "WI-history", "facts": {"candidate": {"kind": "actual_result", "fingerprint": "original", "value": {"schema_version": schema, "limitations": ["Capacity limit"], "follow_up_items": [item()]}}}},
        {"sequence": 2, "version": 7, "work_item_id": "WI-history", "facts": {"decision": {"kind": "actual_result", "accepted": True, "candidate_fingerprint": "original"}}},
    ]
    assert len(project_records(records)) == 1
