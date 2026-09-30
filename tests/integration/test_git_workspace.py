from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

from strixnova.git_workspace import GitWorkspace, GitWorkspaceError


def _git(repo: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


@pytest.fixture
def git_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    (project / "shared.txt").write_text("base\n", encoding="utf-8")
    _git(project, "add", "shared.txt")
    _git(project, "commit", "-m", "initial")
    _git(project, "branch", "-M", "main")
    return project


def _linked_area(
    workspace: GitWorkspace,
    project: Path,
    work_item_id: str,
) -> dict:
    return workspace.create_work_area(
        work_item_id=work_item_id,
        target_ref="main",
        worktree_path=project.parent / f"{work_item_id}-worktree",
    )


def test_single_work_item_uses_a_local_branch_without_forcing_a_new_worktree(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    base = _git(git_project, "rev-parse", "main")

    area = workspace.create_work_area(
        work_item_id="WI-LOCAL-001",
        target_ref="main",
    )

    assert area["base_commit"] == base
    assert area["work_ref"] == "strixnova/WI-LOCAL-001"
    assert area["worktree_mode"] == "in_place"
    assert Path(area["worktree_path"]) == git_project
    assert workspace.inspect("main")["remote_operations_in_scope"] is False
    status = workspace.inspect_work_area(area)
    assert status["current_branch"] == area["work_ref"]
    assert status["status"]["dirty"] is False
    assert status["result_commits"] == []

    workspace.discard_cancelled_work(area, destructive_confirmed=True)
    assert _git(git_project, "branch", "--show-current") == "main"


def test_existing_uncommitted_work_is_never_stashed_or_adopted(
    git_project: Path,
) -> None:
    (git_project / "unowned.txt").write_text("user work\n", encoding="utf-8")
    workspace = GitWorkspace(git_project)

    with pytest.raises(GitWorkspaceError) as caught:
        workspace.create_work_area(
            work_item_id="WI-DIRTY",
            target_ref="main",
        )

    assert caught.value.code == "existing_work_unresolved"
    assert not _git(git_project, "branch", "--list", "strixnova/WI-DIRTY")
    assert (git_project / "unowned.txt").read_text(encoding="utf-8") == (
        "user work\n"
    )


def test_linked_worktree_path_must_stay_outside_the_repository(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    requested = git_project / "nested-worktree"

    with pytest.raises(GitWorkspaceError) as captured:
        workspace.create_work_area(
            work_item_id="WI-INSIDE",
            target_ref="main",
            worktree_path=requested,
        )

    assert captured.value.code == "worktree_inside_repository"
    assert not requested.exists()
    assert not _git(git_project, "branch", "--list", "strixnova/WI-INSIDE")


def test_linked_worktree_never_overwrites_an_existing_external_path(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    requested = git_project.parent / "existing-worktree"
    requested.mkdir()
    marker = requested / "keep.txt"
    marker.write_text("user content\n", encoding="utf-8")

    with pytest.raises(GitWorkspaceError) as captured:
        workspace.create_work_area(
            work_item_id="WI-EXISTS",
            target_ref="main",
            worktree_path=requested,
        )

    assert captured.value.code == "worktree_path_exists"
    assert marker.read_text(encoding="utf-8") == "user content\n"
    assert not _git(git_project, "branch", "--list", "strixnova/WI-EXISTS")


def test_confirmed_result_requires_clean_commits_then_merges_and_cleans_up(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = workspace.create_work_area(
        work_item_id="WI-MERGE",
        target_ref="main",
    )
    worktree = Path(area["worktree_path"])
    (worktree / "feature.txt").write_text("implemented\n", encoding="utf-8")

    with pytest.raises(GitWorkspaceError) as caught:
        workspace.result_commits(area)
    assert caught.value.code == "uncommitted_result"

    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "feat: implement confirmed result")
    result_commit = _git(worktree, "rev-parse", "HEAD")
    assert workspace.result_commits(area) == [result_commit]

    integration = workspace.integrate(area)
    assert integration["outcome"] == "integrated"
    assert integration["result_commits"] == [result_commit]
    assert (git_project / "feature.txt").read_text(encoding="utf-8") == (
        "implemented\n"
    )

    cleanup = workspace.cleanup(area)
    assert cleanup["safe"] is True
    assert cleanup["removed_worktree"] is None
    assert worktree.exists()
    assert _git(git_project, "branch", "--show-current") == "main"
    assert not _git(git_project, "branch", "--list", area["work_ref"])


def test_integration_uses_the_recorded_commits_and_target_tip(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-EXACT-INTEGRATION")
    worktree = Path(area["worktree_path"])
    (worktree / "feature.txt").write_text("accepted\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "accepted result")
    recorded = workspace.result_commits(area)
    target_before = _git(git_project, "rev-parse", "main")

    (worktree / "extra.txt").write_text("not accepted\n", encoding="utf-8")
    _git(worktree, "add", "extra.txt")
    _git(worktree, "commit", "-m", "unaccepted addition")

    with pytest.raises(GitWorkspaceError) as caught:
        workspace.integrate(
            area,
            expected_result_commits=recorded,
            expected_target_commit=target_before,
        )

    assert caught.value.code == "result_commits_changed_before_integration"
    assert _git(git_project, "rev-parse", "main") == target_before


def test_integration_recovers_the_exact_already_completed_merge(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-INTEGRATION-RECOVERY")
    worktree = Path(area["worktree_path"])
    (worktree / "feature.txt").write_text("accepted\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "accepted result")
    recorded = workspace.result_commits(area)
    target_before = _git(git_project, "rev-parse", "main")

    first = workspace.integrate(
        area,
        expected_result_commits=recorded,
        expected_target_commit=target_before,
    )
    recovered = workspace.integrate(
        area,
        expected_result_commits=recorded,
        expected_target_commit=target_before,
    )

    assert recovered == first


def test_no_ff_integration_is_validated_before_its_merge_commit(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-PREPARED-INTEGRATION")
    worktree = Path(area["worktree_path"])
    (worktree / "feature.txt").write_text("accepted\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "accepted result")
    commits = workspace.result_commits(area)
    target_before = _git(git_project, "rev-parse", "main")

    prepared = workspace.integrate(
        area,
        expected_result_commits=commits,
        expected_target_commit=target_before,
        prepare_only=True,
    )

    assert prepared["outcome"] == "prepared"
    assert _git(git_project, "rev-parse", "HEAD") == target_before
    assert _git(git_project, "rev-parse", "MERGE_HEAD") == commits[-1]
    assert (git_project / "feature.txt").read_text(encoding="utf-8") == (
        "accepted\n"
    )

    integrated = workspace.commit_prepared_integration(
        area,
        expected_result_commits=commits,
        expected_target_commit=target_before,
    )
    assert integrated["outcome"] == "integrated"
    assert _git(git_project, "rev-parse", "HEAD") != target_before


def test_prepared_integration_can_be_aborted_without_moving_target(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-ABORT-PREPARED")
    worktree = Path(area["worktree_path"])
    (worktree / "feature.txt").write_text("accepted\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "accepted result")
    commits = workspace.result_commits(area)
    target_before = _git(git_project, "rev-parse", "main")
    assert workspace.integrate(
        area,
        expected_result_commits=commits,
        expected_target_commit=target_before,
        prepare_only=True,
    )["outcome"] == "prepared"

    workspace.abort_prepared_integration(
        area,
        expected_result_tip=commits[-1],
        expected_target_commit=target_before,
    )

    assert _git(git_project, "rev-parse", "HEAD") == target_before
    assert not (git_project / "feature.txt").exists()
    assert subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=git_project,
        capture_output=True,
        check=False,
    ).returncode != 0


def test_ff_only_divergence_is_rejected_before_any_merge_side_effect(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-FF-DIVERGED")
    worktree = Path(area["worktree_path"])
    (worktree / "feature.txt").write_text("accepted\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "accepted result")
    commits = workspace.result_commits(area)
    (git_project / "target.txt").write_text("advanced\n", encoding="utf-8")
    _git(git_project, "add", "target.txt")
    _git(git_project, "commit", "-m", "advance target")
    target_before = _git(git_project, "rev-parse", "main")

    with pytest.raises(GitWorkspaceError) as caught:
        workspace.integrate(
            area,
            merge_strategy="ff_only",
            expected_result_commits=commits,
            expected_target_commit=target_before,
            prepare_only=True,
        )

    assert caught.value.code == "ff_only_not_possible"
    assert _git(git_project, "rev-parse", "main") == target_before
    assert subprocess.run(
        ["git", "rev-parse", "-q", "--verify", "MERGE_HEAD"],
        cwd=git_project,
        capture_output=True,
        check=False,
    ).returncode != 0


def test_native_merge_conflict_is_reported_and_never_semantically_resolved(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-CONFLICT")
    worktree = Path(area["worktree_path"])
    (worktree / "shared.txt").write_text("work item\n", encoding="utf-8")
    _git(worktree, "add", "shared.txt")
    _git(worktree, "commit", "-m", "change from work item")

    (git_project / "shared.txt").write_text("target branch\n", encoding="utf-8")
    _git(git_project, "add", "shared.txt")
    _git(git_project, "commit", "-m", "change from target")

    result = workspace.integrate(area)

    assert result["outcome"] == "conflict"
    assert any(entry[:2] == "UU" for entry in result["conflict_entries"])
    assert _git(git_project, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    assert worktree.exists()
    assert _git(git_project, "branch", "--list", area["work_ref"])

    _git(git_project, "merge", "--abort")
    workspace.discard_cancelled_work(area, destructive_confirmed=True)
    assert (git_project / "shared.txt").read_text(encoding="utf-8") == (
        "target branch\n"
    )


def test_agent_can_finish_native_conflict_after_reverification(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-CONFLICT-FINISH")
    worktree = Path(area["worktree_path"])
    (worktree / "shared.txt").write_text("work item\n", encoding="utf-8")
    _git(worktree, "add", "shared.txt")
    _git(worktree, "commit", "-m", "change from work item")
    (git_project / "shared.txt").write_text("target\n", encoding="utf-8")
    _git(git_project, "add", "shared.txt")
    _git(git_project, "commit", "-m", "change from target")
    assert workspace.integrate(area)["outcome"] == "conflict"

    (git_project / "shared.txt").write_text(
        "target plus confirmed work item\n",
        encoding="utf-8",
    )
    _git(git_project, "add", "shared.txt")
    with pytest.raises(GitWorkspaceError) as caught:
        workspace.integration_result(area)
    assert caught.value.code == "integration_not_complete"

    _git(git_project, "commit", "--no-edit")
    integration = workspace.integration_result(area)
    assert integration["outcome"] == "integrated"
    assert (git_project / "shared.txt").read_text(encoding="utf-8") == (
        "target plus confirmed work item\n"
    )
    assert workspace.cleanup(area)["safe"] is True


def test_result_commits_refuse_a_rebound_or_detached_worktree(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-BINDING")
    worktree = Path(area["worktree_path"])
    _git(worktree, "checkout", "--detach")

    with pytest.raises(GitWorkspaceError) as caught:
        workspace.result_commits(area)
    assert caught.value.code == "worktree_binding_changed"

    _git(worktree, "checkout", area["work_ref"])
    workspace.discard_cancelled_work(area, destructive_confirmed=True)


def test_cancellation_requires_user_choice_before_destructive_discard(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-CANCEL")
    worktree = Path(area["worktree_path"])
    (worktree / "draft.txt").write_text("unfinished\n", encoding="utf-8")

    state = workspace.cancellation_state(area)
    assert state["requires_user_decision"] is True
    assert state["dirty"] is True
    with pytest.raises(GitWorkspaceError) as caught:
        workspace.discard_cancelled_work(
            area,
            destructive_confirmed=False,
        )
    assert caught.value.code == "destructive_confirmation_required"
    assert worktree.exists()

    discarded = workspace.discard_cancelled_work(
        area,
        destructive_confirmed=True,
    )
    assert discarded["discarded"] is True
    assert not worktree.exists()


def test_long_lived_artifacts_use_git_history_not_a_parallel_ledger(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    introduced = _git(git_project, "rev-parse", "HEAD")
    (git_project / "shared.txt").write_text("updated\n", encoding="utf-8")
    _git(git_project, "add", "shared.txt")
    _git(git_project, "commit", "-m", "update artifact")
    updated = _git(git_project, "rev-parse", "HEAD")

    history = workspace.artifact_commits("shared.txt")

    assert history == {
        "path": "shared.txt",
        "introduced_commit": introduced,
        "updated_commit": updated,
    }
    with pytest.raises(GitWorkspaceError) as caught:
        workspace.artifact_commits("../outside.md")
    assert caught.value.code == "invalid_artifact_path"
    with pytest.raises(GitWorkspaceError) as internal:
        workspace.artifact_commits(".git/config")
    assert internal.value.code == "invalid_artifact_path"


def test_changed_paths_are_derived_from_git_for_tracked_and_untracked_work(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = workspace.create_work_area(
        work_item_id="WI-CHANGED-PATHS",
        target_ref="main",
    )
    (git_project / "shared.txt").write_text("changed\n", encoding="utf-8")
    (git_project / "new.txt").write_text("new\n", encoding="utf-8")

    assert workspace.changed_paths(area) == ["new.txt", "shared.txt"]

    workspace.discard_cancelled_work(area, destructive_confirmed=True)


def test_resolve_commit_keeps_moving_refs_fresh_while_reusing_commit_ids(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    initial = workspace.resolve_commit("main")

    (git_project / "later.txt").write_text("later\n", encoding="utf-8")
    _git(git_project, "add", "later.txt")
    _git(git_project, "commit", "-m", "advance main")

    advanced = workspace.resolve_commit("main")

    assert advanced != initial
    assert workspace.resolve_commit(initial) == initial


def test_just_created_empty_work_area_can_be_compensated(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = workspace.create_work_area(
        work_item_id="WI-ROLLBACK",
        target_ref="main",
    )
    worktree = Path(area["worktree_path"])

    result = workspace.rollback_empty_work_area(area)

    assert result["rolled_back"] is True
    assert worktree.exists()
    assert result["removed_worktree"] is None
    assert _git(git_project, "branch", "--show-current") == "main"
    assert not _git(git_project, "branch", "--list", area["work_ref"])


def test_two_non_intersecting_work_items_merge_from_independent_worktrees(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    first = _linked_area(workspace, git_project, "WI-PARALLEL-A")
    second = _linked_area(workspace, git_project, "WI-PARALLEL-B")
    first_tree = Path(first["worktree_path"])
    second_tree = Path(second["worktree_path"])
    (first_tree / "a.txt").write_text("a\n", encoding="utf-8")
    (second_tree / "b.txt").write_text("b\n", encoding="utf-8")
    _git(first_tree, "add", "a.txt")
    _git(first_tree, "commit", "-m", "feat: add a")
    _git(second_tree, "add", "b.txt")
    _git(second_tree, "commit", "-m", "feat: add b")

    assert workspace.integrate(first)["outcome"] == "integrated"
    workspace.cleanup(first)
    assert workspace.integrate(second)["outcome"] == "integrated"
    workspace.cleanup(second)

    assert (git_project / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert (git_project / "b.txt").read_text(encoding="utf-8") == "b\n"


def test_destructive_cancel_refuses_while_native_merge_is_in_progress(
    git_project: Path,
) -> None:
    workspace = GitWorkspace(git_project)
    area = _linked_area(workspace, git_project, "WI-CANCEL-CONFLICT")
    worktree = Path(area["worktree_path"])
    (worktree / "shared.txt").write_text("work item\n", encoding="utf-8")
    _git(worktree, "add", "shared.txt")
    _git(worktree, "commit", "-m", "change from work item")
    (git_project / "shared.txt").write_text("target\n", encoding="utf-8")
    _git(git_project, "add", "shared.txt")
    _git(git_project, "commit", "-m", "change from target")
    assert workspace.integrate(area)["outcome"] == "conflict"

    with pytest.raises(GitWorkspaceError) as caught:
        workspace.discard_cancelled_work(area, destructive_confirmed=True)
    assert caught.value.code == "target_merge_in_progress"
    assert worktree.exists()

    _git(git_project, "merge", "--abort")
    workspace.discard_cancelled_work(area, destructive_confirmed=True)
