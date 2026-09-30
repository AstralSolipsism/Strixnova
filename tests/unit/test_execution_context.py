from copy import deepcopy
from pathlib import Path

import pytest

from strixnova.current_action import current_action_for
from strixnova.project_authority_progress import project_authority_plan_ref
from strixnova.work_item_read_model import WorkItemReadModel
from tests.support.project_context import FRONTEND
from tests.support.project_baseline import TEST_MODULE_ID
from tests.support.review_context import read_yaml, review_project


def recorded_item():
    return {
        "work_item_id": "WI-example", "version": 7, "status": "implementing",
        "data": {
            "direction": {
                "schema_version": "strixnova.direction-decision.v1",
                "goal": "Expose recorded evidence",
                "scope": [{"requirement_id": "DIRREQ-1111111111111111", "statement": "Read exact evidence"}],
                "constraints": [{"constraint_id": "DIRCON-1111111111111111", "statement": "Read-only means no writes"}],
                "acceptance": [{"acceptance_id": "DIRACC-1111111111111111", "statement": "Return original content", "requirement_refs": ["DIRREQ-1111111111111111"]}],
                "non_goals": ["Do not judge meaning"],
            },
            "direction_confirmation": {"accepted": True, "direction_version": 2},
            "engineering": {
                "assessment": {
                    "assessment_id": "EA-example", "assessment_revision": 1,
                    "design_decisions": [{"decision": "The program returns original evidence"}],
                    "unknowns_and_limitations": ["External behavior not observed"],
                },
                "plan": {
                    "plan_id": "PLAN-example", "change_context": {"formal_implementation": True, "change_kind": "modify_existing"},
                    "assessment_ref": {"work_item_id": "WI-example", "assessment_id": "EA-example", "assessment_revision": 1},
                    "operations": [{"action": "modify", "path": "src.py", "repository_id": FRONTEND}],
                    "implementation_slices": [{
                        "slice_id": "SLICE-001", "purpose": "Return original content",
                        "operation_refs": ["operations[0]"], "depends_on": [],
                        "verification_command_ids": [], "completion_criteria": ["Evidence unchanged"],
                        "implements": ["direction.acceptance:DIRACC-1111111111111111"],
                    }],
                    "verification_commands": [],
                    "semantic_review": {"review_id": "SEMREVIEW-example", "findings": [
                        {"finding_id": "F-1", "status": "open", "statement": "Review the actual input"},
                        {"finding_id": "F-2", "status": "resolved", "statement": "Old issue"},
                        {"finding_id": "F-3", "status": "accepted_risk", "statement": "Unmeasured latency"},
                    ]},
                },
            },
            "verifications": [], "implementation_slice_completions": [],
        },
    }


def test_execution_material_preserves_source_text_and_unresolved_findings(tmp_path):
    item = recorded_item()
    original = deepcopy(item)
    context = WorkItemReadModel(tmp_path).execution_context(item)
    assert context["direction"] == item["data"]["direction"]
    assert [row["finding"]["finding_id"] for row in context["open_findings"]] == ["F-1", "F-3"]
    assert context["assessment_material"]["records"]["design_decisions"] == item["data"]["engineering"]["assessment"]["design_decisions"]
    context["direction"]["constraints"][0]["statement"] = "changed by reader"
    assert item == original
    assert not context["writes_performed"]
    assert not list(tmp_path.iterdir())


def test_another_assessment_revision_is_not_presented_as_the_plan_basis(tmp_path):
    item = recorded_item()
    item["data"]["engineering"]["assessment"]["assessment_revision"] = 2
    context = WorkItemReadModel(tmp_path).execution_context(item)
    assert context["assessment_material"] is None
    assert "execution_assessment_not_bound" in {gap["code"] for gap in context["gaps"]}
    assert context["direction"]["goal"] == "Expose recorded evidence"


def test_recorded_plan_change_changes_the_execution_source_identity(tmp_path):
    item = recorded_item()
    reader = WorkItemReadModel(tmp_path)
    before = reader.execution_context(item)
    item["data"]["engineering"]["plan"]["operations"][0]["path"] = "other.py"
    after = reader.execution_context(item)
    assert before["source"]["plan_sha256"] != after["source"]["plan_sha256"]
    assert after["resolved_operations"][0]["operation"]["path"] == "other.py"


@pytest.mark.parametrize("status", ["implementation_ready", "implementing", "replanning_required"])
def test_current_action_exposes_execution_material_for_start_resume_and_replan(status):
    item = recorded_item()
    item["status"] = status
    action = current_action_for(item)
    assert "engineering.execution_context" in action["record_refs"]


def test_execution_material_includes_recorded_project_rules_for_owned_code(tmp_path: Path):
    basis = review_project(tmp_path)
    before = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and '.git' not in p.parts}
    item = recorded_item()
    item["data"]["engineering"]["plan"]["investigation_ref"] = basis
    context = WorkItemReadModel(tmp_path).execution_context(item)
    rules = context["project_rules"]
    assert rules["architecture"]["selected_module_ids"] == [TEST_MODULE_ID]
    assert rules["engineering_policy"]["policy_statements"] == read_yaml(tmp_path, "docs/engineering/policy.yaml")["policy_statements"]
    assert rules["domain_facts"]["facts"]
    assert rules["sources"]["target_architecture"]["files"]
    after = {p.relative_to(tmp_path).as_posix(): p.read_bytes() for p in tmp_path.rglob('*') if p.is_file() and '.git' not in p.parts}
    assert after == before


def test_unassigned_code_keeps_global_rules_and_an_explicit_investigation_gap(tmp_path: Path):
    basis = review_project(tmp_path)
    item = recorded_item()
    item["data"]["engineering"]["plan"]["investigation_ref"] = basis
    item["data"]["engineering"]["plan"]["operations"][0]["path"] = "new-file.py"
    rules = WorkItemReadModel(tmp_path).execution_context(item)["project_rules"]
    assert rules["engineering_policy"]["policy_statements"]
    assert rules["product_guardrails"]["constraints"]
    assert rules["architecture"]["selected_module_ids"] == []
    assert "source_ownership_unknown" in {gap["code"] for gap in rules["gaps"]}


def test_execution_context_exposes_exact_extended_rules_and_their_sources(tmp_path):
    from tests.support.review_context import project_with_extended_policy
    basis, rule = project_with_extended_policy(tmp_path)
    item = recorded_item()
    item["data"]["engineering"]["plan"]["investigation_ref"] = basis
    material = WorkItemReadModel(tmp_path).execution_context(item)["project_rules"]
    policy = material["engineering_policy"]
    assert next(row for row in policy["rules"] if row["rule_id"] == rule["rule_id"]) == rule
    assert any(row["source_id"] == "SOURCE-LAYOUT" for row in policy["rule_sources"])
    assert any(row["path"] == "docs/conventions.md" for row in material["sources"]["engineering_policy"]["files"])
    assert material["semantic_content_machine_proven"] is False


@pytest.mark.parametrize("same_plan", [True, False])
def test_final_authority_review_findings_follow_the_plan_into_execution(tmp_path, same_plan):
    item = recorded_item()
    item["data"]["engineering"]["plan_confirmation"] = {"accepted": True, "candidate_fingerprint": "sha256:" + "a" * 64}
    plan_ref = project_authority_plan_ref(item)
    if not same_plan:
        plan_ref["plan_content_sha256"] = "b" * 64
    item["data"]["project_authority_reviews"] = [{
        "plan_ref": plan_ref,
        "semantic_review": {"review_id": "SEMREVIEW-final", "findings": [
            {"finding_id": "F-final", "status": "accepted_risk", "statement": "Keep the actual recovery gap visible"},
        ]},
    }]
    context = WorkItemReadModel(tmp_path).execution_context(item)
    identities = {(row["review_id"], row["finding"]["finding_id"]) for row in context["open_findings"]}
    assert (("SEMREVIEW-final", "F-final") in identities) is same_plan


def test_same_path_in_another_repository_does_not_inherit_module_ownership(tmp_path):
    basis = review_project(tmp_path)
    item = recorded_item()
    plan = item["data"]["engineering"]["plan"]
    plan["investigation_ref"] = basis
    plan["operations"][0]["repository_id"] = "REPO-9999999999999999"
    rules = WorkItemReadModel(tmp_path).execution_context(item)["project_rules"]
    assert rules["architecture"]["selected_module_ids"] == []
    gap = next(row for row in rules["gaps"] if row["code"] == "source_ownership_unknown")
    assert gap["repository_id"] == "REPO-9999999999999999"
    assert gap["path"] == "src.py"
