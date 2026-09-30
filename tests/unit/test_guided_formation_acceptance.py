from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from scripts.check_guided_formation_acceptance import (
    GuidedFormationAcceptanceError,
    check_catalog,
)
from scripts.skill_bundle_manifest import directory_manifest


PROJECT_ROOT = Path(__file__).parents[2]
EXPECTED_CASE_IDS = {
    "GF-GUIDANCE-AUTHORITY-DECISION",
    "GF-GUIDANCE-ALIGNMENT-DRAFT",
    "GF-GUIDANCE-VERIFICATION-RESUME",
    "GF-COMM-AUTONOMOUS-PROGRESS",
    "GF-COMM-RESUME-QUESTION",
    "GF-COMM-COMPLETE-DECISION",
    "GF-COMM-UNKNOWN-FAILURE",
    "GF-COMM-DETAIL-AND-CLOSURE",
    "GF-CLEAR-BOUNDED",
    "GF-VAGUE-DESIRE",
    "GF-CONCRETE-INCOMPLETE",
    "GF-ONE-HIGH-RISK",
    "GF-MULTIPLE-RESULTS",
    "GF-CROSS-UNIT-ARCHITECTURE",
    "GF-UPSTREAM-CORRECTION",
    "GF-PACE-SAME-CONTRACT",
    "GF-PD-SOLUTION-PROBLEM-ROLES",
    "GF-PD-OPTION-EXPANSION",
    "GF-PD-ASSUMPTION-REJECTION",
    "GF-PD-CURRENT-EVIDENCE",
    "GF-PD-TIMELY-STOP",
    "GF-PD-NONBUILD-OUTCOME",
    "GF-PD-AUTHORITY-CORRECTION",
    "GF-CONFIRM-DIRECTION-EXPLANATION",
    "GF-CONFIRM-PLAN-EXPLANATION",
    "GF-CONFIRM-RESULT-EXPLANATION",
    "GF-CONFIRM-REEXPLAIN-SAME-CANDIDATE",
    "GF-CONFIRM-HIDE-INTERNAL-FIELDS",
    "GF-PRD-FORMATION",
    "GF-PRD-READING",
    "GF-PRD-CORRECTION",
    "GF-PRD-REVIEW",
    "GF-SPEC-READING",
    "GF-SPEC-UPDATE",
    "GF-DOMAIN-READING",
    "GF-DOMAIN-LANGUAGE-CORRECTION",
    "GF-CODE-REVIEW-SCOPE",
    "GF-CODE-REVIEW-CORRECTION",
    "GF-TEST-FEEDBACK",
    "GF-TEST-BOUNDARY-STABILITY",
    "GF-METHODS-SMALL-CHANGE",
    "GF-METHODS-FEATURE-CHAIN",
    "GF-UX-FORMATION",
    "GF-UX-REVIEW-CORRECTION",
    "GF-UX-SKIP",
    "GF-BEHAVIOR-CONTRACT-RISKS",
    "GF-ALIGNMENT-FINALIZATION-ORDER",
    "GF-MULTI-RESULT-OVERVIEW",
    "GF-HISTORY-INDEPENDENT",
    "GF-UPGRADE-UNCLOSED-EXECUTION",
}
CONTRACT_CASE_IDS = {"GF-CONCRETE-INCOMPLETE", "GF-PACE-SAME-CONTRACT"}


def test_guided_formation_catalog_is_complete_and_explicit_about_proof() -> None:
    result = check_catalog()

    assert result["status"] == "valid"
    assert result["case_count"] == len(EXPECTED_CASE_IDS)
    assert {item["case_id"] for item in result["cases"]} == EXPECTED_CASE_IDS
    assert result["counts_by_verification_kind"] == {
        "agent_response": len(EXPECTED_CASE_IDS - CONTRACT_CASE_IDS),
        "contract_structure": len(CONTRACT_CASE_IDS),
    }
    assert {
        item["case_id"] for item in result["cases"]
        if item["verification_kind"] == "contract_structure"
    } == CONTRACT_CASE_IDS
    assert (
        result["current_evidence_count"]
        + result["stale_evidence_count"]
        + result["pending_evidence_count"]
        + result["unassessed_evidence_count"]
        == len(EXPECTED_CASE_IDS)
    )
    assert result["semantic_content_machine_proven"] is False


def test_catalog_marks_only_changed_dependencies_stale(tmp_path: Path) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("entry\n", encoding="utf-8")
    (skill_root / "unrelated.md").write_text("other\n", encoding="utf-8")
    evidence = tmp_path / "evidence.md"
    evidence.write_text("CASE-LOCATOR\n", encoding="utf-8")
    dependency_hash = directory_manifest(
        skill_root,
        relative_paths=["SKILL.md"],
    )["sha256"]
    catalog = {
        "schema_version": "strixnova.guided-formation-acceptance-catalog.v1",
        "skill_source_root": "skill",
        "semantic_content_machine_proven": False,
        "cases": [
            {'case_id': 'GF-FIXTURE-CASE', 'title': 'fixture', 'verification_kind': 'contract_structure', 'expected_behavior': 'expected', 'must_avoid': 'forbidden', 'dependency_paths': ['SKILL.md'], 'evidence': {'result': 'passed', 'path': 'evidence.md', 'locator': 'CASE-LOCATOR', 'dependency_manifest_sha256': dependency_hash, 'full_skill_bundle_manifest_sha256': None, 'binding_basis': 'fixture'}, 'execution_dependencies': None}
        ],
    }
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    initial = check_catalog(tmp_path, catalog_path="catalog.yaml")
    assert initial["skill_current_count"] == 1
    assert initial["unassessed_evidence_count"] == 1
    assert initial["acceptance_complete"] is False
    (skill_root / "unrelated.md").write_text("changed\n", encoding="utf-8")
    assert check_catalog(tmp_path, catalog_path="catalog.yaml")["skill_current_count"] == 1
    (skill_root / "SKILL.md").write_text("changed\n", encoding="utf-8")
    result = check_catalog(tmp_path, catalog_path="catalog.yaml")
    assert result["acceptance_complete"] is False
    assert result["stale_evidence_count"] == 1


def test_catalog_can_declare_pending_agent_evidence_without_fabricating_it(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("entry\n", encoding="utf-8")
    catalog = {
        "schema_version": "strixnova.guided-formation-acceptance-catalog.v1",
        "skill_source_root": "skill",
        "semantic_content_machine_proven": False,
        "cases": [
            {'case_id': 'GF-PENDING-AGENT', 'title': 'pending fixture', 'verification_kind': 'agent_response', 'expected_behavior': 'expected', 'must_avoid': 'forbidden', 'dependency_paths': ['SKILL.md'], 'evidence': {'result': 'pending', 'path': None, 'locator': None, 'dependency_manifest_sha256': None, 'full_skill_bundle_manifest_sha256': None, 'binding_basis': '等待全新无历史 Agent 验收。'}, 'execution_dependencies': None}
        ],
    }
    catalog_path = tmp_path / "catalog.yaml"
    catalog_path.write_text(
        yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = check_catalog(tmp_path, catalog_path="catalog.yaml")

    assert result["pending_evidence_count"] == 1
    assert result["current_evidence_count"] == 0
    assert result["stale_evidence_count"] == 0
    assert result["acceptance_complete"] is False

    catalog["cases"][0]["evidence"]["path"] = "invented.md"
    catalog_path.write_text(
        yaml.safe_dump(catalog, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    with pytest.raises(GuidedFormationAcceptanceError, match="不得伪造"):
        check_catalog(tmp_path, catalog_path="catalog.yaml")
