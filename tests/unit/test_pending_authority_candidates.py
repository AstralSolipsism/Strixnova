from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import subprocess

import pytest
import yaml

from strixnova.project_authority_consistency import (
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
)
from strixnova.project_authority_decision import (
    project_authority_candidate,
    project_authority_review_bundle,
)
from tests.support.project_baseline import portable_project_baseline
from tests.support.project_configuration import configure_repository


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _git(project: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _pending(project: Path, kind: str) -> tuple[str, dict, dict]:
    baseline = portable_project_baseline(
        project, baseline_id="pending", artifacts=[]
    )
    baseline_path = project / "docs/engineering/baseline.yaml"
    _write(baseline_path, baseline)
    configure_repository(project, integration_ref="main")
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "adopted authorities")
    commit = _git(project, "rev-parse", "HEAD")
    reference = baseline["authority_refs"][kind]
    path = project / reference["path"]
    authority = yaml.safe_load(path.read_text(encoding="utf-8"))
    old_revision = deepcopy(authority["revision"])
    new_revision = old_revision["revision_id"].split("-", 1)[0] + "-EEEEEEEEEEEEEEEE"
    status = (
        "draft" if kind == "implementation_alignment" else "ready_for_confirmation"
    )
    authority["revision"] = {
        "revision_id": new_revision,
        "status": status,
        "supersedes_revision_id": old_revision["revision_id"],
        "confirmed_by_owner_id": None,
        "confirmed_on": None,
    }
    _write(path, authority)
    if kind == "implementation_alignment":
        for relative in authority["artifact_paths"].values():
            child_path = project / relative
            child = yaml.safe_load(child_path.read_text(encoding="utf-8"))
            child["alignment_revision_id"] = new_revision
            _write(child_path, child)
    reference["revision_id"] = new_revision
    reference["status"] = {
        "revision_status": status,
        "adoption_status": "under_review",
    }
    baseline["review_state"] = {
        "required": True,
        "reasons": ["Successor candidate requires review and owner acceptance."],
        "affected_authority_kinds": [kind],
    }
    _write(baseline_path, baseline)
    return commit, baseline, old_revision


@pytest.mark.parametrize("kind", ["implementation_alignment", "engineering_policy"])
def test_explicit_candidate_read_keeps_pending_successor_separate_from_adoption(
    tmp_path: Path,
    kind: str,
) -> None:
    commit, baseline, old_revision = _pending(tmp_path, kind)
    before = {
        p.relative_to(tmp_path): p.read_bytes()
        for p in (tmp_path / "docs").rglob("*.yaml")
    }

    result = ProjectAuthorityConsistency(tmp_path).load_working_tree_candidate_for(
        commit
    )

    assert result["structurally_consistent"] is True
    assert result["changed_authority_kinds"] == [kind]
    assert result["baseline"]["authority_refs"][kind] == (
        baseline["authority_refs"][kind]
    )
    assert result["review_state"]["required"] is True
    assert result["ready_for_stage_completion"] is False
    assert result["semantic_content_machine_proven"] is False
    adopted = ProjectAuthorityConsistency(tmp_path, observed_ref=commit).load()
    adopted_reference = adopted["baseline"]["authority_refs"][kind]
    assert adopted_reference["revision_id"] == old_revision["revision_id"]
    assert adopted_reference["status"]["adoption_status"] == "current"
    assert all((tmp_path / p).read_bytes() == raw for p, raw in before.items())


def test_complete_review_bundle_can_read_a_pending_successor_in_an_adopted_project(
    tmp_path: Path,
) -> None:
    commit, baseline, _old_revision = _pending(tmp_path, "engineering_policy")
    reference = baseline["authority_refs"]["engineering_policy"]
    item = {
        "work_item_id": "WI-20260906-11111111",
        "version": 7,
        "status": "implementing",
        "data": {
            "engineering": {
                "plan_confirmation": {
                    "accepted": True,
                    "candidate_fingerprint": "sha256:" + "1" * 64,
                },
                "plan": {
                    "plan_id": "PLAN-EA-1111111111111111-R1",
                    "investigation_ref": commit,
                    "assessment_ref": {
                        "assessment_id": "EA-1111111111111111",
                        "assessment_revision": 1,
                    },
                    "operations": [
                        {
                            "action": "modify",
                            "path": reference["path"],
                            "long_lived_artifact": {
                                "artifact_id": reference["policy_id"],
                                "artifact_type": "quality_policy",
                            },
                        }
                    ],
                },
            },
        },
    }
    candidate = project_authority_candidate(tmp_path, item, "engineering_policy")

    bundle = project_authority_review_bundle(
        tmp_path,
        item,
        [{"authority_kind": "engineering_policy", "candidate": candidate}],
    )

    assert len(bundle["candidates"]) == 5
    policy = next(
        value
        for value in bundle["candidates"]
        if value["authority_kind"] == "engineering_policy"
    )
    assert policy["revision_id"] == reference["revision_id"]
    assert bundle["semantic_content_machine_proven"] is False
    after = yaml.safe_load(
        (tmp_path / reference["path"]).read_text(encoding="utf-8")
    )
    assert after["revision"]["status"] == "ready_for_confirmation"


@pytest.mark.parametrize(
    "invalid_binding",
    ["adopted_reference", "same_revision", "wrong_predecessor", "confirmed_successor"],
)
def test_pending_status_does_not_waive_exact_successor_binding(
    tmp_path: Path,
    invalid_binding: str,
) -> None:
    commit, baseline, old_revision = _pending(tmp_path, "implementation_alignment")
    reference = baseline["authority_refs"]["implementation_alignment"]
    path = tmp_path / reference["path"]
    authority = yaml.safe_load(path.read_text(encoding="utf-8"))
    if invalid_binding == "adopted_reference":
        reference["revision_id"] = old_revision["revision_id"]
        reference["status"]["revision_status"] = "confirmed"
    elif invalid_binding == "same_revision":
        authority["revision"]["revision_id"] = old_revision["revision_id"]
        reference["revision_id"] = old_revision["revision_id"]
        for relative in authority["artifact_paths"].values():
            child_path = tmp_path / relative
            child = yaml.safe_load(child_path.read_text(encoding="utf-8"))
            child["alignment_revision_id"] = old_revision["revision_id"]
            _write(child_path, child)
    elif invalid_binding == "wrong_predecessor":
        authority["revision"]["supersedes_revision_id"] = "ALIGNREV-FFFFFFFFFFFFFFFF"
    else:
        authority["revision"].update(
            status="confirmed",
            confirmed_by_owner_id=old_revision["confirmed_by_owner_id"],
            confirmed_on=old_revision["confirmed_on"],
        )
        reference["status"]["revision_status"] = "confirmed"
    _write(path, authority)
    _write(tmp_path / "docs/engineering/baseline.yaml", baseline)

    with pytest.raises(ProjectAuthorityConsistencyError) as caught:
        ProjectAuthorityConsistency(tmp_path).load_working_tree_candidate_for(commit)

    assert any(
        "采用状态" in issue or "复用现行修订身份" in issue or "精确承接" in issue
        for issue in caught.value.issues
    )
