"""Checks the real repository baseline; pending Git bindings remain failures."""
from pathlib import Path

from strixnova.project_engineering_baseline import BASELINE_SCHEMA, ProjectEngineeringBaseline

PROJECT_ROOT = Path(__file__).parents[2]


def test_repository_baseline_contains_only_adoption_and_review_facts() -> None:
    baseline = ProjectEngineeringBaseline(PROJECT_ROOT).load(
        required=True,
        allow_candidate_refs=True,
    )

    assert baseline is not None
    assert baseline["schema_version"] == BASELINE_SCHEMA
    assert set(baseline) == {
        "schema_version",
        "baseline_id",
        "project",
        "authority_refs",
        "current_architecture_stage_id",
        "code_version",
        "review_state",
        "_manifest_path",
        "_observed_commit",
        "semantic_content_machine_proven",
    }
    assert set(baseline["authority_refs"]) == {
        "product_definition",
        "domain_model",
        "target_architecture",
        "engineering_policy",
        "implementation_alignment",
    }
    alignment_status = baseline["authority_refs"]["implementation_alignment"][
        "status"
    ]
    assert (
        alignment_status["revision_status"],
        alignment_status["adoption_status"],
    ) in {
        ("draft", "current"),
        ("draft", "under_review"),
        ("ready_for_confirmation", "under_review"),
        ("confirmed", "current"),
    }
    assert baseline["review_state"]["required"] is (
        (
            alignment_status["revision_status"],
            alignment_status["adoption_status"],
        )
        != ("confirmed", "current")
    )
    assert baseline["semantic_content_machine_proven"] is False
