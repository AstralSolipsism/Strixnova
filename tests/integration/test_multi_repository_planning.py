from copy import deepcopy
import json
from pathlib import Path
import sys

from click.testing import CliRunner
import pytest
import yaml

from strixnova.application_coordinator import ApplicationCoordinator, ApplicationCoordinatorError
from strixnova.cli import main
from strixnova.engineering_governance import EngineeringGovernanceError, compile_engineering_plan
from strixnova.host_adapter import HostAdapterError, LocalHostAdapter
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_context import ProjectContextResolver
from strixnova.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from tests.support.governance_assessment import assessment_fixture, bind_assessment_to_work_item, direction_fixture, refresh_single_slice, semantic_review_fixture
from tests.support.project_baseline import portable_project_baseline, TEST_DOMAIN_MODEL_ID, TEST_CONTEXT_FACT_ID
from tests.support.project_configuration import configuration_document
from tests.support.project_context import BACKEND, FRONTEND, PROJECT, git, repository, tree_bytes
from strixnova.work_item_repositories import planned_repository_deliveries


def planning_project(root: Path) -> dict:
    entry, front, back = root / "entry", root / "front", root / "back"
    entry.mkdir()
    front.mkdir()
    assessment = assessment_fixture(front)
    baseline = portable_project_baseline(front, baseline_id="multi repository planning", artifacts=[])
    repository(back)
    for source in (front / "docs").rglob("*"):
        if source.is_file():
            target = back / source.relative_to(front)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    (back / "src.py").write_text("def value():\n    return 2\n", encoding="utf-8")
    (back / "backend_only.py").write_text("BACKEND = True\n", encoding="utf-8")
    git(back, "add", ".")
    git(back, "commit", "-m", "backend authorities and code")
    back_commit = git(back, "rev-parse", "HEAD")
    for kind in ("product_definition", "domain_model", "target_architecture"):
        baseline["authority_refs"][kind].update(repository_id=BACKEND, ref=back_commit)
    baseline_path = front / "docs/engineering/baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    config = configuration_document(integration_ref="main")
    config["repositories"] += [
        {"repository_id": BACKEND, "owner_project_id": PROJECT, "purpose": "后端与权威材料"},
        {"repository_id": "REPO-4444444444444444", "owner_project_id": PROJECT, "purpose": "本次无需绑定的成员"},
    ]
    (front / "strixnova-project.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (front / baseline["authority_refs"]["product_definition"]["path"]).write_text("wrong repository\n", encoding="utf-8")
    git(front, "add", ".")
    git(front, "commit", "-m", "project declaration and frontend")
    front_commit = git(front, "rev-parse", "HEAD")
    bindings = {
        "schema_version": "strixnova.project-bindings.v1", "project_id": PROJECT,
        "configuration": {"repository_id": FRONTEND}, "management_root": "state",
        "repositories": [
            {"repository_id": FRONTEND, "path": "../front"},
            {"repository_id": BACKEND, "path": "../back"},
        ],
    }
    assessment["investigation_ref"] = front_commit
    assessment["repository_scope"] = {"project_id": PROJECT, "repositories": [
        {"repository_id": FRONTEND, "role": "modify", "investigation_ref": front_commit, "target_ref": "main"},
        {"repository_id": BACKEND, "role": "modify", "investigation_ref": back_commit, "target_ref": "main"},
    ]}
    assessment["source_references"] = [
        {**deepcopy(assessment["source_references"][0]), "repository_id": identifier,
         "reference_id": f"SRC-00{index}", "observed_ref": commit}
        for index, (identifier, commit) in enumerate(((FRONTEND, front_commit), (BACKEND, back_commit)), 1)
    ]
    assessment["operations"] = [
        {**deepcopy(assessment["operations"][0]), "repository_id": identifier, "evidence_refs": [f"SRC-00{index}"]}
        for index, identifier in enumerate((FRONTEND, BACKEND), 1)
    ]
    command = deepcopy(assessment["verification_commands"][0])
    command["argv"][0] = sys.executable
    assessment["verification_commands"] = [{**deepcopy(command), "repository_id": identifier} for identifier in (FRONTEND, BACKEND)]
    assessment["delivery_plan"]["repository_order"] = [BACKEND, FRONTEND]
    refresh_single_slice(assessment)
    return dict(entry=entry, front=front, back=back, bindings=bindings, assessment=assessment,
                front_commit=front_commit, back_commit=back_commit)


def plan_alignment_refresh(project):
    baseline = yaml.safe_load((project['front'] / 'docs/engineering/baseline.yaml').read_text(encoding='utf-8'))
    reference = baseline['authority_refs']['implementation_alignment']
    model = yaml.safe_load((project['front'] / reference['path']).read_text(encoding='utf-8'))
    paths = [reference['path'], *model['artifact_paths'].values(), 'docs/engineering/baseline.yaml']
    assessment = project['assessment']
    for index, path in enumerate(paths):
        source_id = f'SRC-META-{index}'
        assessment['source_references'].append({'reference_id': source_id, 'repository_id': FRONTEND, 'path': path, 'observed_ref': project['front_commit'], 'epistemic_status': 'observed'})
        assessment['operations'].append({
            'repository_id': FRONTEND, 'action': 'modify', 'path': path,
            'reason': 'Refresh the repository-qualified implementation evidence for the jointly changed sources.',
            'evidence_refs': [source_id], 'implements': ['design_decisions[0]'],
            **({'long_lived_artifact': {'artifact_id': reference['alignment_model_id'], 'artifact_type': 'domain_alignment'}} if index == 0 else {}),
        })
    assessment['authority_change_set'] = {
        'schema_version': 'strixnova.authority-change-set.v1', 'change_set_id': 'AUTHCHANGE-7777777777777777',
        'work_item_id': assessment['direction_ref']['work_item_id'],
        'base_authorities': [{'authority_kind': 'implementation_alignment', 'artifact_id': reference['alignment_model_id'], 'revision_id': reference['revision_id'], 'path': reference['path'], 'status': 'confirmed', 'observed_commit': project['front_commit']}],
        'candidate_authorities': [{'authority_kind': 'implementation_alignment', 'artifact_id': reference['alignment_model_id'], 'revision_id': 'ALIGNREV-7777777777777777', 'path': reference['path'], 'status': 'draft', 'supersedes_revision_id': reference['revision_id'], 'adoption_effect': 'not_adopted'}],
        'changes': [{'change_id': 'AUTHOP-001', 'authority_kind': 'implementation_alignment', 'operation': 'modify', 'target_ref': reference['alignment_model_id'], 'summary': 'Review source ownership and exact observations for both repositories.', 'evidence_refs': ['SRC-META-0']}],
        'downstream_dispositions': [], 'semantic_content_machine_proven': False,
    }
    for kind, identity_field in (('product_definition', 'product_id'), ('domain_model', 'model_id'), ('target_architecture', 'architecture_id')):
        upstream = baseline['authority_refs'][kind]
        assessment['authority_change_set']['base_authorities'].append({'authority_kind': kind, 'artifact_id': upstream[identity_field], 'revision_id': upstream['revision_id'], 'path': upstream['path'], 'status': 'confirmed', 'observed_commit': upstream.get('ref') or project['front_commit']})
    assessment['semantic_review'] = semantic_review_fixture('SRC-META-0', 'authority_change_set')
    refresh_single_slice(assessment)
    return model



def compile_candidate(project: dict, assessment: dict) -> dict:
    context = ProjectContextResolver(project["entry"]).configured(bindings=project["bindings"], observed_ref=project["front_commit"])
    checker = ProjectAuthorityConsistency(project["entry"], shared_context=context)
    governance = checker.engineering_governance_context()
    return compile_engineering_plan(
        assessment, project_dir=project["entry"],
        candidate_context=checker.engineering_candidate_context(assessment),
        direction=direction_fixture(), direction_version=3, work_item_id="WI-TEST-001",
        profile=governance["profile"], known_baseline_refs=set(governance["baseline_refs"]),
        domain_model_id=governance["domain_model_id"], known_domain_fact_locations=governance["domain_fact_locations"],
        known_authority_artifacts=governance["authority_artifacts"],
    )


def commit_frontend_change(project: dict, message: str) -> None:
    git(project["front"], "add", ".")
    git(project["front"], "commit", "-m", message)
    commit = git(project["front"], "rev-parse", "HEAD")
    project["front_commit"] = commit
    project["assessment"]["investigation_ref"] = commit
    project["assessment"]["repository_scope"]["repositories"][0]["investigation_ref"] = commit
    for reference in project["assessment"]["source_references"]:
        if reference["repository_id"] == FRONTEND:
            reference["observed_ref"] = commit


def accept(adapter: LocalHostAdapter, item: dict, kind: str) -> dict:
    challenge = adapter.current_action(item["work_item_id"])["confirmation_challenge"]
    return adapter.confirm(
        item["work_item_id"], kind, candidate_fingerprint=challenge["candidate_fingerprint"],
        user_confirmation="接受这份完整候选。",
        agent_decision={"decision": "accept", "reason": "固定场景中负责人已接受所展示的完整候选。"},
        expected_version=item["version"],
    )


def plan_item(project: dict) -> tuple[LocalHostAdapter, dict]:
    adapter = LocalHostAdapter(project["entry"], project_bindings=project["bindings"])
    item = adapter.coordinator.intake(title="前后端共同结果", raw_request="同一目标包含前端和后端，整体接受后交付。")
    context = adapter.next_step(item["work_item_id"], record_refs=["project.direction_context"])["records"]["project.direction_context"]
    direction = direction_fixture()
    direction["decision_context"] = {
        "context_ref": context["context_ref"],
        "capability_refs": [context["capability_catalog"][0]["capability_ref"]],
        "guardrail_dispositions": [
            {"decision_ref": guardrail["decision_ref"], "disposition": "applies", "reason": "本场景继续遵守现行护栏。"}
            for guardrail in context["guardrails"]
        ], "assumptions": [],
    }
    item = adapter.submit_direction(item["work_item_id"], {"direction": direction, "ready_for_confirmation": True}, expected_version=item["version"])
    item = accept(adapter, item, "direction")
    # Public submission now rejects omitted alignment obligations before a
    # plan reaches its owner. Reuse the existing complete fixture, retaining
    # actual source operations and the independent multi-repository assertions.
    operations = project["assessment"]["operations"]
    if (any(op.get("path") == "src.py" and op.get("repository_id") == FRONTEND for op in operations)
        and not any((op.get("long_lived_artifact") or {}).get("artifact_type") == "domain_alignment" for op in operations)):
        project['alignment_before'] = plan_alignment_refresh(project)
    assessment = deepcopy(project["assessment"])
    bind_assessment_to_work_item(assessment, item)
    project["assessment"] = assessment
    item = adapter.submit_engineering_assessment(item["work_item_id"], assessment, expected_version=item["version"])
    return adapter, item


def test_one_plan_distinguishes_equal_paths_and_commands_in_two_repositories(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    before = tree_bytes(tmp_path)
    plan = compile_candidate(project, project["assessment"])
    assert [entry["repository_id"] for entry in plan["operations"]] == [FRONTEND, BACKEND]
    assert len(plan["verification_commands"]) == 2
    assert plan["implementation_slices"][0]["repository_ids"] == [FRONTEND, BACKEND]
    assert plan["delivery_plan"]["repository_order"] == [BACKEND, FRONTEND]
    assert tree_bytes(tmp_path) == before


def test_verification_input_repositories_are_explicit_and_cannot_omit_the_execution_source(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    assessment = project['assessment']
    assessment['verification_commands'][0]['input_repository_ids'] = [FRONTEND, BACKEND]
    plan = compile_candidate(project, assessment)
    assert plan['verification_commands'][0]['input_repository_ids'] == [FRONTEND, BACKEND]
    assert 'input_repository_ids' not in plan['verification_commands'][1]
    assessment['verification_commands'][0]['input_repository_ids'] = [BACKEND]
    with pytest.raises(EngineeringGovernanceError, match='execution repository'):
        compile_candidate(project, assessment)


@pytest.mark.parametrize("fault", ["missing_id", "wrong_repository", "duplicate_operation", "invalid_order", "readonly_write", "invalid_collection"])
def test_invalid_repository_plans_do_not_create_management_state(tmp_path: Path, fault: str) -> None:
    project = planning_project(tmp_path)
    assessment = project["assessment"]
    if fault == "missing_id":
        assessment["operations"][0].pop("repository_id")
    elif fault == "wrong_repository":
        assessment["operations"][0]["path"] = "backend_only.py"
    elif fault == "duplicate_operation":
        assessment["operations"][1]["repository_id"] = FRONTEND
    elif fault == "invalid_order":
        assessment["delivery_plan"]["repository_order"] = [FRONTEND, FRONTEND]
    elif fault == "readonly_write":
        assessment["repository_scope"]["repositories"][1].update(role="read", target_ref=None)
    else:
        assessment["operations"] = None
    before = tree_bytes(tmp_path)
    with pytest.raises(EngineeringGovernanceError):
        compile_candidate(project, assessment)
    assert tree_bytes(tmp_path) == before


def test_separated_entry_keeps_one_item_and_one_plan_confirmation_then_offers_preparation(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    repositories_before = {key: tree_bytes(project[key]) for key in ("front", "back")}
    adapter, item = plan_item(project)
    assert item["data"]["project_id"] == PROJECT
    assert [row["repository_id"] for row in item["data"]["repository_deliveries"]] == [BACKEND, FRONTEND]
    assert (project["entry"] / "state/.strixnova/authority.sqlite3").is_file()
    assert not (project["front"] / ".strixnova").exists()
    assert not (project["back"] / ".strixnova").exists()
    item = accept(adapter, item, "engineering_plan")
    action = adapter.current_action(item["work_item_id"])
    assert action["action_type"] == "begin_implementation"
    assert action['repository_id'] == BACKEND
    record = adapter.next_step(item["work_item_id"], record_refs=["repository_deliveries"])["records"]["repository_deliveries"]
    assert record["execution_facts_included"] is True
    assert record["overall_result_confirmation"] is None
    assert action["input_contract_ref"] == 'input.contract:begin_implementation'
    with pytest.raises(ApplicationCoordinatorError):
        adapter.coordinator.delivery(item["work_item_id"], {'repository_id': FRONTEND}, expected_version=item["version"])
    assert adapter.coordinator.authority.get(item["work_item_id"])["version"] == item["version"]
    assert all(tree_bytes(project[key]) == value for key, value in repositories_before.items())


@pytest.mark.parametrize("role", ["read", "modify"])
def test_external_repository_is_a_dependency_without_delivery_ownership(tmp_path: Path, role: str) -> None:
    project = planning_project(tmp_path)
    external_id = "REPO-5555555555555555"
    external = tmp_path / "external"
    repository(external)
    (external / "library.py").write_text("LIBRARY = 1\n", encoding="utf-8")
    git(external, "add", ".")
    git(external, "commit", "-m", "external version")
    commit = git(external, "rev-parse", "HEAD")
    config_path = project["front"] / "strixnova-project.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    config["external_repositories"] = [{"repository_id": external_id, "owner_project_id": "PROJECT-AAAAAAAAAAAAAAAA", "purpose": "外部只读依赖"}]
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    commit_frontend_change(project, "declare external dependency")
    project["bindings"]["repositories"].append({"repository_id": external_id, "path": "../external"})
    assessment = project["assessment"]
    assessment["repository_scope"]["repositories"].append({
        "repository_id": external_id, "role": role, "investigation_ref": commit,
        "target_ref": None if role == "read" else "main",
    })
    assessment["source_references"].append({
        "reference_id": "SRC-LIB", "repository_id": external_id, "path": "library.py",
        "observed_ref": commit, "epistemic_status": "observed",
    })
    before = tree_bytes(tmp_path)
    if role == "modify":
        with pytest.raises(EngineeringGovernanceError, match="外部依赖"):
            compile_candidate(project, assessment)
    else:
        plan = compile_candidate(project, assessment)
        assert len(plan["repository_scope"]["repositories"]) == 3
        assert {entry["repository_id"] for entry in planned_repository_deliveries(plan)} == {FRONTEND, BACKEND}
    assert tree_bytes(tmp_path) == before


def test_policy_relative_program_is_resolved_in_its_command_repository(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    allowed = project["front"] / "tools/check.cmd"
    allowed.parent.mkdir()
    allowed.write_text("@exit /b 0\n", encoding="utf-8")
    policy_path = project["front"] / "docs/engineering/policy.yaml"
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["verification_command_policy"]["allowed_programs"] = [{
        "program": str(allowed), "purpose": "仅授权前端此脚本", "argument_policy": "exact_plan_only",
    }]
    policy_path.write_text(yaml.safe_dump(policy), encoding="utf-8")
    commit_frontend_change(project, "bind exact frontend tool")
    assessment = project["assessment"]
    for command in assessment["verification_commands"]:
        command["argv"] = ["tools/check.cmd"]
    with pytest.raises(EngineeringGovernanceError, match="VC-002"):
        compile_candidate(project, assessment)
    assessment["verification_commands"] = assessment["verification_commands"][:1]
    refresh_single_slice(assessment)
    assert len(compile_candidate(project, assessment)["verification_commands"]) == 1


def test_domain_fact_location_includes_its_authority_repository(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    assessment = project["assessment"]
    assessment["domain_fact_changes"] = [{
        "repository_id": FRONTEND, "disposition": "retain",
        "target_ref": {"schema_version": "strixnova.domain-fact-reference.v1", "authority_kind": "project_domain_model",
                       "model_id": TEST_DOMAIN_MODEL_ID, "fact_id": TEST_CONTEXT_FACT_ID, "observed_commit": project["back_commit"]},
        "source_path": "docs/domain/sources/core.yaml", "reason": "保留当前事实", "evidence_refs": ["SRC-002"], "lineage": [],
    }]
    with pytest.raises(EngineeringGovernanceError, match="领域权威仓库"):
        compile_candidate(project, assessment)
    assessment["domain_fact_changes"][0]["repository_id"] = BACKEND
    assert compile_candidate(project, assessment)["actual_result_requirements"]["domain_fact_changes"]


def test_replanning_changes_responsibilities_and_rejects_the_previous_confirmation(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    adapter, item = plan_item(project)
    old_challenge = adapter.current_action(item["work_item_id"])["confirmation_challenge"]
    item = accept(adapter, item, "engineering_plan")
    item = adapter.request_replan(item["work_item_id"], {"schema_version": "strixnova.replan-request.v1", "reasons": ["后端仅作为验证依赖。"]}, expected_version=item["version"])
    assessment = deepcopy(project["assessment"])
    assessment["assessment_revision"] = 2
    assessment["repository_scope"]["repositories"][1].update(role="read", target_ref=None)
    assessment["operations"] = [operation for operation in assessment["operations"] if operation["repository_id"] == FRONTEND]
    assessment["delivery_plan"]["repository_order"] = [FRONTEND]
    refresh_single_slice(assessment)
    item = adapter.submit_engineering_assessment(item["work_item_id"], assessment, expected_version=item["version"])
    assert [row["repository_id"] for row in item["data"]["repository_deliveries"]] == [FRONTEND]
    with pytest.raises(HostAdapterError):
        adapter.confirm(item["work_item_id"], "engineering_plan", candidate_fingerprint=old_challenge["candidate_fingerprint"],
                        user_confirmation="接受之前的候选。", agent_decision={"decision": "accept", "reason": "旧候选"}, expected_version=item["version"])
    cancelled = adapter.coordinator.cancel(item["work_item_id"], {"reason": "停止后续建设"}, expected_version=item["version"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["data"]["actual_result_confirmation"] is None
    events = adapter.coordinator.authority.history(item["work_item_id"])
    assert sum(event["event_type"] == "confirm_direction" for event in events) == 1
    assert sum(event["event_type"] == "submit_engineering_assessment" for event in events) == 2


def test_one_selected_repository_uses_the_same_preparation_contract(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    assessment = project["assessment"]
    assessment["repository_scope"]["repositories"] = assessment["repository_scope"]["repositories"][:1]
    assessment["operations"] = assessment["operations"][:1]
    assessment["source_references"] = assessment["source_references"][:1]
    assessment["verification_commands"] = assessment["verification_commands"][:1]
    assessment["delivery_plan"]["repository_order"] = [FRONTEND]
    refresh_single_slice(assessment)
    adapter, item = plan_item(project)
    item = accept(adapter, item, "engineering_plan")
    assert adapter.current_action(item["work_item_id"])["action_type"] == "begin_implementation"
    assert adapter.coordinator.project_current_action(item)["input_contract_ref"] == 'input.contract:begin_implementation'
    with pytest.raises(ApplicationCoordinatorError):
        adapter.coordinator.delivery(item["work_item_id"], {'repository_id': BACKEND}, expected_version=item["version"])


def test_public_cli_intake_uses_explicit_management_root(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    path = project["entry"] / "bindings.json"
    path.write_text(json.dumps(project["bindings"]), encoding="utf-8")
    result = CliRunner().invoke(main, ["--project-bindings", str(path), "intake", "--project-dir", str(project["entry"]),
                                     "--input", json.dumps({"title": "跨仓库事项", "request": "共同结果"})])
    assert result.exit_code == 0, result.output
    work_item_id = json.loads(result.output)["next"]["work_item_id"]
    assert WorkflowAuthority(project["entry"] / "state").get(work_item_id)["data"]["project_id"] == PROJECT


def test_management_store_rejects_a_second_project_identity(tmp_path: Path) -> None:
    project = planning_project(tmp_path)
    adapter, item = plan_item(project)
    with pytest.raises(WorkflowAuthorityError) as caught:
        WorkflowAuthority(project["entry"] / "state", project_id="PROJECT-AAAAAAAAAAAAAAAA").create(title="另一项目", raw_request="不能混入")
    assert getattr(caught.value, "code", None) == "authority_project_mismatch"
    assert adapter.coordinator.authority.get(item["work_item_id"])["version"] == item["version"]
