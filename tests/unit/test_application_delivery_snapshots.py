from __future__ import annotations

from tests.support.project_context import FRONTEND

from tests.support.project_configuration import configure_repository

from pathlib import Path
import subprocess

import pytest
import yaml

import strixnova.application_coordinator as application_coordinator_module
from strixnova.application_coordinator import ApplicationCoordinator
from strixnova.git_workspace import GitWorkspace
from strixnova.implementation_candidate_evidence import (
    ImplementationCandidateEvidence,
)
from strixnova.verification_runner import VerificationRunnerError
from tests.support.project_baseline import (
    adopt_portable_ddd,
    portable_project_baseline,
)


def test_conflict_can_have_no_applicable_retest_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = {
        "schema_version": "strixnova.implementation-candidate-snapshot.v1",
        "plan_id": "PLAN-CONFLICT",
        "comparison_base_commit": "a" * 40,
        "paths": [
            {
                "path": "shared.txt",
                "state": "file",
                "sha256": "b" * 64,
            }
        ],
        "changed_paths": ["shared.txt"],
        "semantic_content_machine_proven": False,
    }
    current = {
        "work_item_id": "WI-CONFLICT",
        "version": 9,
        "status": "integration_conflict",
        "current_action": {"action_type": "resolve_git_conflict"},
        "data": {
            "engineering": {
                "assessment": {"investigation_ref": "a" * 40},
                "plan": {
                    "plan_id": "PLAN-CONFLICT",
                    "verification_commands": [{"command_id": "VC-001"}],
                },
            },
            "actual_result": {"implementation_candidate_snapshot": snapshot},
        },
    }
    coordinator = ApplicationCoordinator(tmp_path)
    recorded: dict = {}
    monkeypatch.setattr(coordinator.authority, "get", lambda _identifier: current)

    def record_transition(
        _identifier: str,
        action: str,
        value: dict,
        *,
        expected_version: int,
    ) -> dict:
        recorded.update(
            action=action,
            value=value,
            expected_version=expected_version,
        )
        return current

    monkeypatch.setattr(coordinator.authority, "transition", record_transition)
    monkeypatch.setattr(
        coordinator,
        "_conflict_candidate_snapshot",
        lambda _current: snapshot,
    )

    class ConsistencyProbe:
        def __init__(self, _project: Path) -> None:
            pass

        def verify_working_tree_candidate_snapshot(
            self,
            _actual_result: dict,
            *,
            investigation_ref: str,
        ) -> dict:
            assert investigation_ref == "a" * 40
            return {"verified": True}

    monkeypatch.setattr(
        application_coordinator_module,
        "ProjectAuthorityConsistency",
        ConsistencyProbe,
    )

    result = coordinator.submit_current_action_input(
        "WI-CONFLICT",
        {
            "user_visible_result_changed": False,
            "confirmed_direction_or_plan_changed": False,
            "reason": "冲突只涉及文档拼接，没有方案内命令适用。",
            "retest_command_ids": [],
        },
        expected_version=9,
    )

    assert result == current
    assert recorded["action"] == "record_conflict_resolution"
    assert recorded["value"]["retest_command_ids"] == []
    assert recorded["value"]["implementation_candidate_snapshot"] == snapshot


def _git(project: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8", errors="replace").strip()


def _current(project: Path) -> tuple[dict, dict, dict]:
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    (project / "base.txt").write_text("base\n", encoding="utf-8")
    _git(project, "add", "base.txt")
    _git(project, "commit", "-m", "base")
    base_commit = _git(project, "rev-parse", "HEAD")
    work_ref = "strixnova/WI-SNAPSHOT"
    _git(project, "switch", "-c", work_ref)
    operation = {
        "action": "create",
        "path": "feature.py",
        "reason": "形成可交付行为。",
        "evidence_refs": [
            "direction.acceptance:DIRACC-3333333333333333"
        ],
        "implements": [
            "direction.acceptance:DIRACC-3333333333333333"
        ],
    }
    slice_value = {
        "slice_id": "SLICE-001",
        "operation_refs": ["operations[0]"],
        "continued_operation_refs": [],
        "depends_on": [],
        "verification_command_ids": [],
    }
    plan = {
        "plan_id": "PLAN-EA-SNAPSHOT0000001-R1",
        "operations": [operation],
        "implementation_slices": [slice_value],
        "verification_commands": [],
    }
    current = {
        "work_item_id": "WI-SNAPSHOT",
        "version": 7,
        "status": "implementing",
        "data": {
            "engineering": {"plan": plan},
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "repository": str(project),
                "work_item_id": "WI-SNAPSHOT",
                "target_ref": "main",
                "base_commit": base_commit,
                "worktree_path": str(project),
                "work_ref": work_ref,
                "worktree_mode": "in_place",
                "created_by_strixnova": True,
                "merge_strategy": "no_ff",
            },
            "verifications": [],
            "implementation_slice_completions": [],
        },
    }
    return current, plan, slice_value


def _authority_repo(project: Path) -> tuple[str, str, str]:
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    (project / "src.py").write_text(
        "def value():\n    return 1\n",
        encoding="utf-8",
    )
    baseline = portable_project_baseline(
        project,
        baseline_id="target-advance-projection",
        artifacts=[],
    )
    identities = adopt_portable_ddd(project, baseline)
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(project, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(project, "add", ".")
    _git(project, "commit", "-m", "adopt authorities")
    base = _git(project, "rev-parse", "HEAD")

    alignment_path = project / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    alignment["code_snapshot"]["repositories"][0]["base_commit"] = base
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(project, "add", str(alignment_path.relative_to(project)))
    _git(project, "commit", "-m", "refresh implementation evidence")
    alignment_only = _git(project, "rev-parse", "HEAD")

    product_path = project / identities["product_path"]
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    product["purpose"] = "同一修订被原地改写的产品正文。"
    product_path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(project, "add", str(product_path.relative_to(project)))
    _git(project, "commit", "-m", "pollute product authority")
    product_changed = _git(project, "rev-parse", "HEAD")
    return base, alignment_only, product_changed


def test_target_advance_projection_blocks_upstream_authority_pollution_only(
    tmp_path: Path,
) -> None:
    base, alignment_only, product_changed = _authority_repo(tmp_path)

    base_projection = ApplicationCoordinator._authority_ref_projection(
        tmp_path,
        base,
    )
    alignment_projection = ApplicationCoordinator._authority_ref_projection(
        tmp_path,
        alignment_only,
    )
    product_projection = ApplicationCoordinator._authority_ref_projection(
        tmp_path,
        product_changed,
    )

    assert "implementation_alignment" in base_projection["baseline"][
        "authority_refs"
    ]
    assert base_projection["implementation_alignment"]["revision"][
        "revision_id"
    ]
    assert alignment_projection == base_projection
    assert product_projection != alignment_projection


def test_slice_completion_rejects_an_omitted_planned_file_operation(
    tmp_path: Path,
) -> None:
    current, plan, slice_value = _current(tmp_path)
    evidence = ImplementationCandidateEvidence(tmp_path)

    with pytest.raises(VerificationRunnerError) as captured:
        evidence.require_operations_realized(
            current,
            plan,
            slice_value,
        )

    assert captured.value.code == "implementation_slice_operations_unrealized"
    assert captured.value.details["unrealized_operation_refs"] == [
        "operations[0]"
    ]


def test_actual_result_snapshot_rejects_file_swap_before_commit(
    tmp_path: Path,
) -> None:
    current, plan, slice_value = _current(tmp_path)
    evidence = ImplementationCandidateEvidence(tmp_path)
    feature = tmp_path / "feature.py"
    feature.write_text("VALUE = 1\n", encoding="utf-8")
    operation_results = (
        evidence.require_operations_realized(
            current,
            plan,
            slice_value,
        )
    )
    completion = {
        "schema_version": "strixnova.implementation-slice-completion.v1",
        "slice_id": "SLICE-001",
        "completion_summary": "计划文件已形成。",
        "evidence_kind": "explicit_no_command",
        "source_receipt_ids": [],
        "operation_results": operation_results,
        "owned_path_snapshot": evidence.path_snapshot(
            ["feature.py"],
        ),
        "semantic_content_machine_proven": False,
    }
    current["data"]["implementation_slice_completions"] = [completion]
    snapshot = evidence.candidate_snapshot(current)
    assert snapshot is not None
    current["data"]["actual_result"] = {
        "implementation_candidate_snapshot": snapshot
    }

    evidence.require_candidate_snapshot(current)
    feature.write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(VerificationRunnerError) as captured:
        evidence.require_candidate_snapshot(current)

    assert captured.value.code == "accepted_implementation_candidate_changed"
    assert captured.value.details["changed_paths"] == ["feature.py"]


def test_actual_result_snapshot_rejects_an_added_unplanned_file(
    tmp_path: Path,
) -> None:
    current, plan, slice_value = _current(tmp_path)
    feature = tmp_path / "feature.py"
    feature.write_text("VALUE = 1\n", encoding="utf-8")
    completion = {
        "schema_version": "strixnova.implementation-slice-completion.v1",
        "slice_id": "SLICE-001",
        "completion_summary": "计划文件已形成。",
        "evidence_kind": "explicit_no_command",
        "source_receipt_ids": [],
        "operation_results": (
            ApplicationCoordinator._require_slice_operations_realized(
                current,
                plan,
                slice_value,
                project_dir=tmp_path,
            )
        ),
        "owned_path_snapshot": ApplicationCoordinator._slice_path_snapshot(
            tmp_path,
            ["feature.py"],
        ),
        "semantic_content_machine_proven": False,
    }
    current["data"]["implementation_slice_completions"] = [completion]
    snapshot = ApplicationCoordinator._implementation_candidate_snapshot(
        current,
        project_dir=tmp_path,
    )
    assert snapshot is not None
    assert snapshot["changed_paths"] == ["feature.py"]
    current["data"]["actual_result"] = {
        "implementation_candidate_snapshot": snapshot
    }

    (tmp_path / "smuggled.txt").write_text("not accepted\n", encoding="utf-8")

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._require_implementation_candidate_snapshot(
            current,
            project_dir=tmp_path,
        )

    assert captured.value.code == "accepted_implementation_path_set_changed"
    assert captured.value.details == {
        "missing_paths": [],
        "unexpected_paths": ["smuggled.txt"],
        "observed_ref": "working_tree",
    }


def test_prepared_in_place_merge_uses_the_target_tip_as_comparison_base(
    tmp_path: Path,
) -> None:
    current, plan, slice_value = _current(tmp_path)
    feature = tmp_path / "feature.py"
    feature.write_text("VALUE = 1\n", encoding="utf-8")
    completion = {
        "schema_version": "strixnova.implementation-slice-completion.v1",
        "slice_id": "SLICE-001",
        "completion_summary": "计划文件已形成。",
        "evidence_kind": "explicit_no_command",
        "source_receipt_ids": [],
        "operation_results": (
            ApplicationCoordinator._require_slice_operations_realized(
                current,
                plan,
                slice_value,
                project_dir=tmp_path,
            )
        ),
        "owned_path_snapshot": ApplicationCoordinator._slice_path_snapshot(
            tmp_path,
            ["feature.py"],
        ),
        "semantic_content_machine_proven": False,
    }
    current["data"]["implementation_slice_completions"] = [completion]
    snapshot = ApplicationCoordinator._implementation_candidate_snapshot(
        current,
        project_dir=tmp_path,
    )
    assert snapshot is not None
    current["data"]["actual_result"] = {
        "implementation_candidate_snapshot": snapshot
    }
    _git(tmp_path, "add", "feature.py")
    _git(tmp_path, "commit", "-m", "result")
    area = current["data"]["git"]
    commits = GitWorkspace(tmp_path).result_commits(area)

    prepared = GitWorkspace(tmp_path).integrate(
        area,
        expected_result_commits=commits,
        expected_target_commit=area["base_commit"],
        prepare_only=True,
    )
    assert prepared["outcome"] == "prepared"

    ApplicationCoordinator._require_implementation_candidate_snapshot(
        current,
        project_dir=tmp_path,
        comparison_base_ref=area["base_commit"],
    )
    GitWorkspace(tmp_path).abort_prepared_integration(
        area,
        expected_result_tip=commits[-1],
        expected_target_commit=area["base_commit"],
    )


def test_immutable_result_commit_must_equal_the_presented_file_snapshot(
    tmp_path: Path,
) -> None:
    current, plan, slice_value = _current(tmp_path)
    feature = tmp_path / "feature.py"
    feature.write_text("VALUE = 1\n", encoding="utf-8")
    completion = {
        "schema_version": "strixnova.implementation-slice-completion.v1",
        "slice_id": "SLICE-001",
        "completion_summary": "计划文件已形成。",
        "evidence_kind": "explicit_no_command",
        "source_receipt_ids": [],
        "operation_results": (
            ApplicationCoordinator._require_slice_operations_realized(
                current,
                plan,
                slice_value,
                project_dir=tmp_path,
            )
        ),
        "owned_path_snapshot": ApplicationCoordinator._slice_path_snapshot(
            tmp_path,
            ["feature.py"],
        ),
        "semantic_content_machine_proven": False,
    }
    current["data"]["implementation_slice_completions"] = [completion]
    snapshot = ApplicationCoordinator._implementation_candidate_snapshot(
        current,
        project_dir=tmp_path,
    )
    assert snapshot is not None
    current["data"]["actual_result"] = {
        "implementation_candidate_snapshot": snapshot
    }
    _git(tmp_path, "add", "feature.py")
    _git(tmp_path, "commit", "-m", "result")
    result_commit = _git(tmp_path, "rev-parse", "HEAD")

    ApplicationCoordinator._require_implementation_candidate_snapshot(
        current,
        project_dir=tmp_path,
        observed_ref=result_commit,
    )

    feature.write_text("VALUE = 2\n", encoding="utf-8")
    _git(tmp_path, "add", "feature.py")
    _git(tmp_path, "commit", "-m", "swap")
    swapped_commit = _git(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._require_implementation_candidate_snapshot(
            current,
            project_dir=tmp_path,
            observed_ref=swapped_commit,
        )

    assert captured.value.code == "accepted_implementation_candidate_changed"

    _git(tmp_path, "reset", "--hard", result_commit)
    (tmp_path / "smuggled.txt").write_text("not accepted\n", encoding="utf-8")
    _git(tmp_path, "add", "smuggled.txt")
    _git(tmp_path, "commit", "-m", "smuggle")
    smuggled_commit = _git(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._require_implementation_candidate_snapshot(
            current,
            project_dir=tmp_path,
            observed_ref=smuggled_commit,
        )

    assert captured.value.code == "accepted_implementation_path_set_changed"
    assert captured.value.details["unexpected_paths"] == ["smuggled.txt"]


def test_terminal_failure_does_not_require_a_future_long_lived_artifact(
    tmp_path: Path,
) -> None:
    current, _, _ = _current(tmp_path)
    current["data"]["engineering"]["assessment"] = {
        "change_context": {"change_kind": "modify_existing"},
        "adr_plans": [],
    }
    operations = [
        {
            "action": "create",
            "path": "attempt.txt",
            "reason": "记录已经执行的失败尝试。",
            "evidence_refs": [
                "direction.acceptance:DIRACC-3333333333333333"
            ],
            "implements": [
                "direction.acceptance:DIRACC-3333333333333333"
            ],
        },
        {
            "action": "create",
            "path": "docs/future-runbook.md",
            "reason": "后续切片原计划形成运行手册。",
            "evidence_refs": [
                "direction.acceptance:DIRACC-3333333333333333"
            ],
            "implements": [
                "direction.acceptance:DIRACC-3333333333333333"
            ],
            "long_lived_artifact": {
                "artifact_id": "RUNBOOK-FUTURE",
                "artifact_type": "runbook",
            },
        },
    ]
    current["data"]["engineering"]["plan"] = {
        "plan_id": "PLAN-EA-SNAPSHOT0000001-R1",
        "operations": operations,
        "implementation_slices": [
            {
                "slice_id": "SLICE-001",
                "operation_refs": ["operations[0]"],
                "continued_operation_refs": [],
                "depends_on": [],
                "verification_command_ids": ["VC-001"],
            },
            {
                "slice_id": "SLICE-002",
                "operation_refs": ["operations[1]"],
                "continued_operation_refs": [],
                "depends_on": ["SLICE-001"],
                "verification_command_ids": [],
            },
        ],
    }
    current["data"]["verifications"] = [
        {
            "receipt_id": "VR-001",
            "command_id": "VC-001",
            "result": "failed",
            "code_change_assessment": {
                "changed_after": False,
                "needs_retest": False,
            },
        }
    ]
    (tmp_path / "attempt.txt").write_text("attempted\n", encoding="utf-8")

    ApplicationCoordinator._validate_long_lived_trace(
        current,
        {"long_lived_refs": []},
        project_dir=tmp_path,
    )
