from __future__ import annotations

from tests.support.project_configuration import configure_repository
from tests.support.project_baseline import portable_project_baseline
from tests.support.project_context import git

from pathlib import Path

import pytest
import yaml

from strixnova.project_engineering_baseline import (
    BASELINE_SCHEMA,
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)


PROJECT_ROOT = Path(__file__).parents[2]


def _fixture_value(project: Path) -> dict:
    """Use an independently committed input, never the live repository draft."""
    configure_repository(project)
    git(project, "commit", "--allow-empty", "-m", "isolated baseline origin")
    value = portable_project_baseline(project, baseline_id="baseline-contract-fixture", artifacts=[])
    value["code_version"]["repositories"][0].update(
        base_commit=git(project, "rev-parse", "HEAD"), worktree_state="dirty",
    )
    return value


def _write_project(tmp_path: Path, value: dict) -> None:
    path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)




def test_baseline_does_not_load_or_validate_downstream_authority_bodies(
    tmp_path: Path,
) -> None:
    value = _fixture_value(tmp_path)
    for reference in value["authority_refs"].values():
        reference["path"] = "missing/" + reference["path"]
    _write_project(tmp_path, value)

    baseline = ProjectEngineeringBaseline(tmp_path).load(
        required=True,
        allow_candidate_refs=True,
    )

    assert baseline is not None
    assert all(
        reference["path"].startswith("missing/")
        for reference in baseline["authority_refs"].values()
    )


def test_baseline_rejects_unsupported_contract(tmp_path: Path) -> None:
    old_value = {
        "schema_version": "strixnova.project-engineering-baseline.v999",
        "baseline_id": "old",
        "project": {},
        "engineering_methods": [],
        "long_lived_models": {},
        "policies": {},
        "governance": {},
        "artifacts": [],
    }

    with pytest.raises(ProjectEngineeringBaselineError) as caught:
        ProjectEngineeringBaseline(tmp_path).validate(old_value)

    assert any("当前仓库限定合同" in issue for issue in caught.value.issues)


def test_baseline_schema_error_explains_type_in_chinese(tmp_path: Path) -> None:
    value = _fixture_value(tmp_path)
    value["project"]["owner_id"] = 7

    with pytest.raises(ProjectEngineeringBaselineError) as caught:
        ProjectEngineeringBaseline(tmp_path).validate(value)

    assert any(
        "owner_id" in issue and "值类型必须是文本" in issue
        for issue in caught.value.issues
    )


def test_current_authority_must_bind_a_confirmed_revision(tmp_path: Path) -> None:
    value = _fixture_value(tmp_path)
    value["authority_refs"]["domain_model"]["status"][
        "revision_status"
    ] = "draft"
    _write_project(tmp_path, value)

    with pytest.raises(ProjectEngineeringBaselineError) as caught:
        ProjectEngineeringBaseline(tmp_path).load(required=True)

    assert any("必须精确采用已确认的当前上游权威" in issue for issue in caught.value.issues)


def test_non_candidate_baseline_rejects_unadopted_upstream_authority(
    tmp_path: Path,
) -> None:
    value = _fixture_value(tmp_path)
    value["authority_refs"]["domain_model"]["status"] = {
        "revision_status": "draft",
        "adoption_status": "not_adopted",
    }
    _write_project(tmp_path, value)

    with pytest.raises(ProjectEngineeringBaselineError) as caught:
        ProjectEngineeringBaseline(tmp_path).load(required=True)

    assert any("必须精确采用已确认的当前上游权威" in issue for issue in caught.value.issues)


def test_candidate_baseline_can_expose_upstream_authority_under_review(
    tmp_path: Path,
) -> None:
    value = _fixture_value(tmp_path)
    value["authority_refs"]["product_definition"]["status"] = {
        "revision_status": "ready_for_confirmation",
        "adoption_status": "under_review",
    }
    _write_project(tmp_path, value)

    candidate = ProjectEngineeringBaseline(tmp_path).load(
        required=True,
        allow_candidate_refs=True,
    )

    assert candidate is not None
    assert candidate["authority_refs"]["product_definition"]["status"] == {
        "revision_status": "ready_for_confirmation",
        "adoption_status": "under_review",
    }


def test_alignment_under_review_requires_visible_review_state(
    tmp_path: Path,
) -> None:
    value = _fixture_value(tmp_path)
    value["authority_refs"]["implementation_alignment"]["status"] = {
        "revision_status": "ready_for_confirmation",
        "adoption_status": "under_review",
    }
    value["review_state"] = {
        "required": False,
        "reasons": [],
        "affected_authority_kinds": [],
    }
    _write_project(tmp_path, value)

    with pytest.raises(ProjectEngineeringBaselineError) as caught:
        ProjectEngineeringBaseline(tmp_path).load(required=True)

    assert any("需要复核" in issue for issue in caught.value.issues)


def test_select_exposes_only_narrow_baseline_sections(tmp_path: Path) -> None:
    value = _fixture_value(tmp_path)
    for reference in value["authority_refs"].values():
        reference["status"] = {
            "revision_status": "confirmed",
            "adoption_status": "current",
        }
    value["review_state"] = {
        "required": False,
        "reasons": [],
        "affected_authority_kinds": [],
    }
    _write_project(tmp_path, value)
    reader = ProjectEngineeringBaseline(tmp_path)

    selected = reader.select(["authority_refs", "review_state"])

    assert set(selected["sections"]) == {"authority_refs", "review_state"}
    with pytest.raises(ProjectEngineeringBaselineError):
        reader.select(["policies"])
