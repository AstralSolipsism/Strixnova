from pathlib import Path
from collections import Counter
import yaml

from strixnova.project_authority_consistency import AUTHORITY_CONSISTENCY_SCHEMA, ProjectAuthorityConsistency
from strixnova.project_engineering_assurance import ProjectEngineeringAssurance

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_repository_authorities_form_one_exact_chain_without_semantic_claim() -> None:
    result = ProjectAuthorityConsistency(
        PROJECT_ROOT
    ).load_working_tree_candidate(None)

    assert result["schema_version"] == AUTHORITY_CONSISTENCY_SCHEMA
    assert result["structurally_consistent"] is True
    assert result["product_definition"]["product_id"] == (
        result["domain_catalog"]["product_definition_ref"]["product_id"]
    )
    alignment_status = result["implementation_alignment"]["revision"]["status"]
    assert alignment_status in {
        "draft",
        "ready_for_confirmation",
        "confirmed",
    }
    assert result["ready_for_stage_completion"] is not result["review_state"]["required"]
    if alignment_status != "confirmed":
        assert result["review_state"]["required"] is True
    if result["ready_for_stage_completion"]:
        assert not result["review_state"]["reasons"]
        assert not result["implementation_alignment"]["unresolved_items"]
    assert result["semantic_content_machine_proven"] is False


def test_repository_assurance_binds_current_authorities_without_certifying_them(
) -> None:
    baseline = yaml.safe_load(
        (
            PROJECT_ROOT / "docs" / "engineering" / "baseline.yaml"
        ).read_text(encoding="utf-8")
    )
    assurance = yaml.safe_load(
        (
            PROJECT_ROOT / "docs" / "engineering" / "assurance" / "model.yaml"
        ).read_text(encoding="utf-8")
    )
    expected_refs = {
        kind: {
            field: reference[field]
            for field in reference
            if field != "status"
        }
        for kind, reference in baseline["authority_refs"].items()
    }
    consistency = ProjectAuthorityConsistency(PROJECT_ROOT)
    # This repository's HEAD also contains unadopted drafts. Inspect the
    # current candidate directly without treating that commit as adoption.
    consistency.load_working_tree_candidate(None)
    matrix = ProjectEngineeringAssurance(
        PROJECT_ROOT,
        shared_consistency=consistency,
    ).matrix()

    assert matrix["assurance_id"] == assurance["assurance_id"]
    assert matrix["assurance_revision_id"] == assurance["assurance_revision_id"]
    # Loading the matrix validates every rule, exact upstream binding and
    # evidence byte digest for drafts too; status counts are not a pass quota.
    assert matrix["by_status"] == dict(Counter(
        item["status"] for item in assurance["rule_assessments"]
    ))
    assert matrix["authority_refs"] == expected_refs
    assert matrix["external_assurance"]["status"] == "not_claimed"
    assert matrix["semantic_content_machine_proven"] is False
    assert matrix["external_assurance_machine_proven"] is False
    assert matrix["projection_is_project_authority"] is False
