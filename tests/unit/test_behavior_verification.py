from copy import deepcopy

import pytest

from strixnova.behavior_examples import example_catalog
from strixnova.engineering_governance import EngineeringGovernanceError, compile_engineering_plan
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_engineering_policy import load_base_governance_profile
from strixnova.verification_targets import VerificationTargetError, assess_targets, compile_targets, validate_reviews
from tests.support.behavior_examples import EXAMPLE_REF, PARENT_REF, case_config, direction
from tests.support.governance_assessment import assessment_fixture


def test_plan_derives_example_targets_and_keeps_report_configuration_bound(tmp_path):
    value = direction()
    value["constraints"] = [{"constraint_id": "DIRCON-2222222222222222", "statement": "Use the project interpreter"}]
    assessment = assessment_fixture(tmp_path)
    assessment["verification_commands"][0]["case_report"] = case_config(["test_behavior.py::test_other_remains"], bound=False)
    plan = compile_engineering_plan(
        assessment, project_dir=tmp_path,
        candidate_context=ProjectAuthorityConsistency(tmp_path).engineering_candidate_context(assessment),
        work_item_id=assessment["direction_ref"]["work_item_id"], direction=value,
        direction_version=assessment["direction_ref"]["direction_version"],
        profile=load_base_governance_profile(),
    )
    command = plan["verification_commands"][0]
    assert EXAMPLE_REF in command["covers"]
    assert command["case_report"]["example_fingerprints"][EXAMPLE_REF] == plan["behavior_examples"][EXAMPLE_REF]["example_sha256"]
    targets = {item["target_ref"]: item for item in plan["verification_targets"]}
    assert targets[PARENT_REF]["method"] == "examples"
    assert targets[EXAMPLE_REF]["case_bindings"] == [{"command_id": command["command_id"], "test_ids": ["test_behavior.py::test_other_remains"]}]
    assert "behavior_examples" not in assessment


def test_claiming_command_coverage_cannot_replace_a_case_binding(tmp_path):
    value = direction()
    value["constraints"] = [{"constraint_id": "DIRCON-2222222222222222", "statement": "Use the project interpreter"}]
    assessment = assessment_fixture(tmp_path)
    assessment["verification_commands"][0]["covers"].append(EXAMPLE_REF)
    with pytest.raises(EngineeringGovernanceError, match="逐用例"):
        compile_engineering_plan(
            assessment, project_dir=tmp_path,
            candidate_context=ProjectAuthorityConsistency(tmp_path).engineering_candidate_context(assessment),
            work_item_id=assessment["direction_ref"]["work_item_id"], direction=value,
            direction_version=assessment["direction_ref"]["direction_version"],
            profile=load_base_governance_profile(),
        )


def target_fixture():
    value = direction()
    other = deepcopy(value["acceptance"][0]["behavior"]["examples"][0])
    other["example_id"] = "DIREX-5555555555555555"
    other["title"] = "Repeated withdrawal does not change the result"
    value["acceptance"][0]["behavior"]["examples"].append(other)
    examples = example_catalog(value)
    refs = list(examples)
    commands = [{
        "command_id": "VC-001", "covers": [PARENT_REF, *refs],
        "case_report": {"bindings": [{"example_ref": ref, "test_ids": [f"test_behavior.py::test_{index}"]} for index, ref in enumerate(refs)]},
    }]
    targets = compile_targets(commands, [], examples=examples)
    coverage = {
        "results": {"VC-001": "passed"}, "latest_receipt_ids": {"VC-001": "VR-ONE"},
        "case_evidence_by_command": {"VC-001": {
            "status": "recorded", "freshness": "current", "report_ref": "recorded-report",
            "example_results": [{
                "example_ref": ref, "example_sha256": examples[ref]["example_sha256"],
                "status": "passed" if index == 0 else "with_gaps",
                "tests": [{"test_id": f"test_behavior.py::test_{index}", "status": "passed" if index == 0 else "skipped"}],
            } for index, ref in enumerate(refs)],
        }},
    }
    reviews = [{"target_ref": ref, "outcome": "supported", "rationale": "The assertions compare independent expected outcomes.", "evidence_refs": ["VR-ONE"]} for ref in refs]
    return targets, coverage, reviews


def test_parent_acceptance_cannot_hide_a_skipped_example():
    targets, coverage, reviews = target_fixture()
    with pytest.raises(VerificationTargetError, match="保留限制"):
        assess_targets(targets, reviews, coverage=coverage, known_evidence={"VR-ONE"}, limitations=[])
    _, result = assess_targets(targets, reviews, coverage=coverage, known_evidence={"VR-ONE"}, limitations=["The repeated-withdrawal example was skipped."])
    rows = {item["target_ref"]: item for item in result["items"]}
    assert rows[PARENT_REF]["status"] == "example_evidence_incomplete"
    assert rows[EXAMPLE_REF]["status"] == "case_evidence_passed"
    assert result["status"] == "with_gaps"
    assert result["semantic_content_machine_proven"] is False


def test_running_a_case_does_not_complete_the_agent_assertion_review():
    targets, coverage, reviews = target_fixture()
    with pytest.raises(VerificationTargetError) as caught:
        assess_targets(targets, [], coverage=coverage, known_evidence={"VR-ONE"}, limitations=[])
    assert caught.value.code == "verification_target_results_missing"
    _, result = assess_targets(targets, [{**review, "outcome": "not_supported"} for review in reviews], coverage=coverage, known_evidence={"VR-ONE"}, limitations=["The assertion review found a missing effect check."])
    assert result["status"] == "with_gaps"


def test_new_example_must_have_its_own_arrangement():
    with pytest.raises(VerificationTargetError) as caught:
        validate_reviews([], targets={EXAMPLE_REF}, commands=[{"covers": [PARENT_REF]}], known_evidence=set())
    assert caught.value.code == "verification_targets_uncovered"
