"""Native local Git lifecycle for one WorkItem."""

from __future__ import annotations

from pathlib import Path
import os
import re
import shutil
from typing import Any

from strixnova.git_project_reader import (
    GitProjectReaderError,
    repository_path_from_git,
    repository_relative_path,
)
from strixnova.process_supervisor import (
    ProcessExecutionError,
    ProcessLimits,
    ProcessPolicy,
    ProcessResult,
    run_process,
)


GIT_WORK_AREA_SCHEMA = "strixnova.git-work-area.v1"
_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")


class GitWorkspaceError(RuntimeError):
    """A local Git precondition or operation failed."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _git_paths(output: bytes, field: str) -> list[str]:
    """Decode Git path output through the shared repository-path contract."""

    try:
        return [
            repository_path_from_git(value, field)
            for value in output.split(b"\0")
            if value
        ]
    except GitProjectReaderError as error:
        raise GitWorkspaceError(
            error.code,
            str(error),
            details=error.details,
        ) from error


def _valid_ref(value: str, field: str) -> str:
    ref = str(value or "").strip()
    if (
        not _REF.fullmatch(ref)
        or ".." in ref
        or ref.endswith("/")
        or "//" in ref
        or ref.startswith("-")
    ):
        raise GitWorkspaceError("invalid_ref", f"{field} 不是安全的本地 Git ref")
    return ref


def _work_ref(work_item_id: str) -> str:
    identifier = str(work_item_id or "").strip()
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", identifier).strip("-")
    if not safe:
        raise GitWorkspaceError("invalid_work_item_id", "WorkItem ID 无法生成分支名")
    return f"strixnova/{safe}"


class GitWorkspace:
    """Deep module for local branch, worktree, merge, and cleanup behavior."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self._verified_commits: set[str] = set()
        if not self.project.is_dir():
            raise GitWorkspaceError(
                "project_missing",
                f"项目目录不存在：{self.project}",
            )
        self.git = shutil.which("git")
        if not self.git:
            raise GitWorkspaceError("git_missing", "未检测到 Git")
        top = self._run(["rev-parse", "--show-toplevel"], allow_failure=True)
        if top.exit_code != 0:
            raise GitWorkspaceError(
                "git_required",
                "正式实施要求本地 Git 仓库",
            )
        reported = Path(top.stdout_text().strip()).resolve()
        if reported != self.project:
            raise GitWorkspaceError(
                "project_root_mismatch",
                "Git 项目根与 Strixnova 项目目录不一致",
                details={
                    "requested": str(self.project),
                    "git_root": str(reported),
                },
            )

    def ensure_local_excludes(self, patterns: Sequence[str]) -> None:
        """Keep Strixnova runtime files out of Git without editing project files."""

        normalized: list[str] = []
        for pattern in patterns:
            if (
                not isinstance(pattern, str)
                or not pattern.strip()
                or "\n" in pattern
                or "\r" in pattern
            ):
                raise GitWorkspaceError(
                    "invalid_local_exclude",
                    "Git local exclude 必须是非空单行字符串",
                )
            cleaned = pattern.strip()
            if cleaned not in normalized:
                normalized.append(cleaned)

        common_raw = self._text(["rev-parse", "--git-common-dir"])
        common_dir = Path(common_raw)
        if not common_dir.is_absolute():
            common_dir = self.project / common_dir
        common_dir = common_dir.resolve()
        exclude_raw = self._text(["rev-parse", "--git-path", "info/exclude"])
        reported_exclude_path = Path(exclude_raw)
        if not reported_exclude_path.is_absolute():
            reported_exclude_path = self.project / reported_exclude_path
        if reported_exclude_path.exists() and reported_exclude_path.is_symlink():
            raise GitWorkspaceError(
                "unsafe_local_exclude_path",
                "Git local exclude 不得是符号链接",
            )
        exclude_path = reported_exclude_path.resolve()
        expected_path = (common_dir / "info" / "exclude").resolve()
        if exclude_path != expected_path:
            raise GitWorkspaceError(
                "unsafe_local_exclude_path",
                "Git local exclude 路径不属于当前仓库",
                details={"reported": str(exclude_path)},
            )
        existing = (
            exclude_path.read_text(encoding="utf-8")
            if exclude_path.exists()
            else ""
        )
        entries = {
            line.strip()
            for line in existing.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        missing = [pattern for pattern in normalized if pattern not in entries]
        if not missing:
            return
        prefix = existing
        if prefix and not prefix.endswith(("\n", "\r")):
            prefix += "\n"
        exclude_path.parent.mkdir(parents=True, exist_ok=True)
        exclude_path.write_text(
            prefix + "\n".join(missing) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    @staticmethod
    def local_excludes_present(
        project_dir: str | Path,
        patterns: Sequence[str],
    ) -> bool:
        """Cheaply check an ordinary repository before invoking Git to repair it."""

        project = Path(project_dir).expanduser().resolve()
        dot_git = project / ".git"
        if not dot_git.exists():
            return True
        if not dot_git.is_dir():
            # Linked worktrees and unusual Git layouts use Git's canonical
            # path resolution in ensure_local_excludes.
            return False
        exclude_path = dot_git / "info" / "exclude"
        if exclude_path.exists() and exclude_path.is_symlink():
            return False
        if not exclude_path.is_file():
            return False
        existing = exclude_path.read_text(encoding="utf-8")
        entries = {
            line.strip()
            for line in existing.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        return all(
            isinstance(pattern, str) and pattern.strip() in entries
            for pattern in patterns
        )

    def inspect(self, target_ref: str) -> dict[str, Any]:
        target = _valid_ref(target_ref, "target_ref")
        self._require_local_branch(target)
        return {
            "schema_version": "strixnova.git-inspection.v1",
            "repository": str(self.project),
            "target_ref": target,
            "target_commit": self._text(["rev-parse", target]),
            "current_branch": self._current_branch(self.project),
            "current_commit": self._text(["rev-parse", "HEAD"]),
            "status": self._status(self.project),
            "remote_operations_in_scope": False,
        }

    def create_work_area(
        self,
        *,
        work_item_id: str,
        target_ref: str,
        worktree_path: str | Path | None = None,
        merge_strategy: str = "no_ff",
        expected_target_commit: str | None = None,
        plan_only: bool = False,
    ) -> dict[str, Any]:
        target = _valid_ref(target_ref, "target_ref")
        if merge_strategy not in {"no_ff", "ff_only"}:
            raise GitWorkspaceError(
                "unsupported_merge_strategy",
                "本地合入策略必须是 no_ff 或 ff_only",
            )
        self._require_local_branch(target)
        status = self._status(self.project)
        current_branch = self._current_branch(self.project)
        if status["dirty"] and current_branch == target:
            raise GitWorkspaceError(
                "existing_work_unresolved",
                "当前项目已有未归属改动；请先由用户决定归属，不会自动 stash",
                details=status["entries"],
            )
        branch = _work_ref(work_item_id)
        if self._local_branch_exists(branch):
            raise GitWorkspaceError(
                "work_ref_exists",
                f"WorkItem 分支已经存在：{branch}",
            )
        base_commit = self._text(["rev-parse", target])
        if (
            expected_target_commit is not None
            and base_commit != expected_target_commit
        ):
            raise GitWorkspaceError(
                "target_changed_before_work_area_creation",
                "目标分支在建立工作区副作用边界发生变化，必须重新评估",
                details={
                    "expected_target_commit": expected_target_commit,
                    "current_target_commit": base_commit,
                },
            )
        if worktree_path is None:
            if current_branch != target:
                raise GitWorkspaceError(
                    "linked_worktree_required",
                    (
                        f"主工作树当前是 {current_branch or '<detached>'}；"
                        "并行事项必须明确提供独立 worktree 路径"
                    ),
                )
            if not plan_only:
                self._run(["switch", "-c", branch, base_commit])
            return {
                "schema_version": GIT_WORK_AREA_SCHEMA,
                "repository": str(self.project),
                "work_item_id": work_item_id,
                "target_ref": target,
                "base_commit": base_commit,
                "work_ref": branch,
                "worktree_path": str(self.project),
                "worktree_mode": "in_place",
                "created_by_strixnova": True,
                "merge_strategy": merge_strategy,
            }
        worktree = Path(worktree_path).expanduser().resolve()
        if worktree == self.project or self.project in worktree.parents:
            raise GitWorkspaceError(
                "worktree_inside_repository",
                "WorkItem worktree 必须位于主仓库之外",
            )
        if worktree.exists():
            raise GitWorkspaceError(
                "worktree_path_exists",
                f"WorkItem worktree 路径已经存在：{worktree}",
            )
        if not plan_only:
            worktree.parent.mkdir(parents=True, exist_ok=True)
            self._run(["branch", branch, base_commit])
            self._run(["worktree", "add", str(worktree), branch])
        return {
            "schema_version": GIT_WORK_AREA_SCHEMA,
            "repository": str(self.project),
            "work_item_id": work_item_id,
            "target_ref": target,
            "base_commit": base_commit,
            "work_ref": branch,
            "worktree_path": str(worktree),
            "worktree_mode": "linked",
            "created_by_strixnova": True,
            "merge_strategy": merge_strategy,
        }

    def materialize_work_area(self, work_area: dict[str, Any]) -> dict[str, Any]:
        """Finish an already recorded creation intent from native Git facts."""
        area = self._binding(work_area)
        branch = area["work_ref"]
        worktree = Path(area["worktree_path"])
        if self._local_branch_exists(branch):
            if not self.is_ancestor(area["base_commit"], self.resolve_commit(branch)):
                raise GitWorkspaceError("work_area_recovery_conflict", "工作分支不再承接已记录的建立基点")
            if area["worktree_mode"] == "linked":
                if self._registered_worktree(worktree, branch):
                    self.require_work_area_binding(area)
                    return area
                if worktree.exists() or self.resolve_commit(branch) != area["base_commit"]:
                    raise GitWorkspaceError("work_area_recovery_conflict", "未登记工作区或分支已经变化，不能猜测建立意图")
                worktree.parent.mkdir(parents=True, exist_ok=True)
                self._run(["worktree", "add", str(worktree), branch])
            elif self._current_branch(self.project) != branch:
                if self._current_branch(self.project) != area["target_ref"] or self._status(self.project)["dirty"] or self.resolve_commit(branch) != area["base_commit"]:
                    raise GitWorkspaceError("work_area_recovery_conflict", "原地工作区已变化，不能继续切换分支")
                self._run(["switch", branch])
            self.require_work_area_binding(area)
            return area
        created = self.create_work_area(
            work_item_id=area["work_item_id"], target_ref=area["target_ref"],
            worktree_path=worktree if area["worktree_mode"] == "linked" else None,
            merge_strategy=area["merge_strategy"], expected_target_commit=area["base_commit"],
        )
        return {**created, **({"target_advance": area["target_advance"]} if "target_advance" in area else {})}

    def inspect_work_area(
        self,
        work_area: dict[str, Any],
    ) -> dict[str, Any]:
        binding = self._binding(work_area)
        worktree = Path(binding["worktree_path"]).resolve()
        if binding["worktree_mode"] == "linked" and not self._registered_worktree(
            worktree, binding["work_ref"]
        ):
            raise GitWorkspaceError(
                "worktree_not_registered",
                "WorkItem worktree 不在当前 Git 登记中",
            )
        return {
            "schema_version": "strixnova.git-work-area-status.v1",
            "work_ref": binding["work_ref"],
            "worktree_path": str(worktree),
            "current_branch": self._current_branch(worktree),
            "current_commit": self._text(["rev-parse", "HEAD"], cwd=worktree),
            "status": self._status(worktree),
            "result_commits": (
                self.result_commits(binding, require_clean=False)
                if binding["worktree_mode"] == "linked"
                or self._current_branch(self.project) == binding["work_ref"]
                else self._commit_list(binding)
            ),
        }

    def require_work_area_binding(
        self,
        work_area: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-prove the recorded branch/worktree binding before any file read."""

        binding = self._binding(work_area)
        worktree = Path(binding["worktree_path"]).resolve()
        if binding["worktree_mode"] == "linked":
            self._require_worktree_binding(worktree, binding["work_ref"])
        elif self._current_branch(self.project) != binding["work_ref"]:
            raise GitWorkspaceError(
                "worktree_binding_changed",
                "主工作树已经离开 WorkItem 分支",
            )
        return dict(binding)

    def changed_paths(self, work_area: dict[str, Any]) -> list[str]:
        """Derive current WorkItem paths from Git without persisting a ledger."""

        binding = self._binding(work_area)
        worktree = Path(binding["worktree_path"]).resolve()
        if binding["worktree_mode"] == "linked":
            self._require_worktree_binding(worktree, binding["work_ref"])
        elif self._current_branch(self.project) != binding["work_ref"]:
            raise GitWorkspaceError(
                "worktree_binding_changed",
                "主工作树已经离开 WorkItem 分支",
            )
        tracked = self._run(
            [
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-only",
                "-z",
                binding["base_commit"],
                "--",
            ],
            cwd=worktree,
        )
        untracked = self._run(
            [
                "-c",
                "core.quotepath=false",
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ],
            cwd=worktree,
        )
        return sorted(
            {
                value
                for output in (tracked.stdout, untracked.stdout)
                for value in _git_paths(output, "Git 工作区变化路径")
            }
        )

    def changed_worktree_paths_from(self, older_ref: str) -> list[str]:
        """Derive the main worktree delta from one immutable commit."""

        older = self.resolve_commit(older_ref)
        tracked = self._run(
            [
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-only",
                "-z",
                older,
                "--",
            ]
        )
        untracked = self._run(
            [
                "-c",
                "core.quotepath=false",
                "ls-files",
                "--others",
                "--exclude-standard",
                "-z",
            ]
        )
        return sorted(
            {
                value
                for output in (tracked.stdout, untracked.stdout)
                for value in _git_paths(output, "Git 工作树变化路径")
            }
        )

    def result_commits(
        self,
        work_area: dict[str, Any],
        *,
        require_clean: bool = True,
    ) -> list[str]:
        binding = self._binding(work_area)
        worktree = Path(binding["worktree_path"]).resolve()
        if binding["worktree_mode"] == "linked":
            self._require_worktree_binding(worktree, binding["work_ref"])
        elif self._current_branch(self.project) != binding["work_ref"]:
            raise GitWorkspaceError(
                "worktree_binding_changed",
                "主工作树已经离开 WorkItem 分支",
            )
        if require_clean:
            status = self._status(worktree)
            if status["dirty"]:
                raise GitWorkspaceError(
                    "uncommitted_result",
                    "用户确认后仍有未提交文件，Agent 必须显式暂存并形成原子提交",
                    details=status["entries"],
                )
        return self._commit_list(binding)

    def branch_result_commits(
        self,
        work_area: dict[str, Any],
    ) -> list[str]:
        """Read the current immutable commit series of the recorded work branch."""

        binding = self._binding(work_area)
        self._require_local_branch(str(binding["work_ref"]))
        return self._commit_list(binding)

    def _commit_list(self, binding: dict[str, Any]) -> list[str]:
        ancestor = self._run(
            [
                "merge-base",
                "--is-ancestor",
                binding["base_commit"],
                binding["work_ref"],
            ],
            allow_failure=True,
        )
        if ancestor.exit_code != 0:
            raise GitWorkspaceError(
                "base_commit_not_ancestor",
                "WorkItem 分支不再基于记录的 base_commit",
            )
        output = self._text(
            [
                "rev-list",
                "--reverse",
                f"{binding['base_commit']}..{binding['work_ref']}",
            ]
        )
        return [line for line in output.splitlines() if line]

    def integrate(
        self,
        work_area: dict[str, Any],
        *,
        merge_strategy: str | None = None,
        expected_result_commits: list[str] | None = None,
        expected_target_commit: str | None = None,
        prepare_only: bool = False,
    ) -> dict[str, Any]:
        binding = self._binding(work_area)
        strategy = merge_strategy or str(binding.get("merge_strategy") or "no_ff")
        if strategy not in {"no_ff", "ff_only"}:
            raise GitWorkspaceError(
                "unsupported_merge_strategy",
                "程序只执行 no_ff 或 ff_only；rebase 和 squash 由项目另行管理",
            )
        current_branch = self._current_branch(self.project)
        commits = (
            self._commit_list(binding)
            if binding["worktree_mode"] == "in_place"
            and current_branch == binding["target_ref"]
            else self.result_commits(binding, require_clean=True)
        )
        if (
            expected_result_commits is not None
            and commits != expected_result_commits
        ):
            raise GitWorkspaceError(
                "result_commits_changed_before_integration",
                "已记录的结果提交在合入副作用边界发生变化",
                details={
                    "recorded_result_commits": expected_result_commits,
                    "current_result_commits": commits,
                },
            )
        if (
            binding["worktree_mode"] == "in_place"
            and current_branch == binding["work_ref"]
        ):
            self._run(["switch", binding["target_ref"]])
            current_branch = binding["target_ref"]
        if current_branch != binding["target_ref"]:
            raise GitWorkspaceError(
                "target_not_checked_out",
                (
                    f"主工作树当前是 {current_branch or '<detached>'}，"
                    f"必须由用户回到 {binding['target_ref']}"
                ),
            )
        if not commits:
            raise GitWorkspaceError(
                "result_commits_missing",
                "WorkItem 没有用户确认后形成的结果提交",
            )
        result_tip = commits[-1]
        if self._run(
            [
                "merge-base",
                "--is-ancestor",
                result_tip,
                binding["target_ref"],
            ],
            allow_failure=True,
        ).exit_code == 0:
            return self.integration_result(
                binding,
                expected_result_commits=commits,
                expected_target_commit=expected_target_commit,
            )
        current_target_commit = self._text(
            ["rev-parse", binding["target_ref"]]
        )
        if (
            expected_target_commit is not None
            and current_target_commit != expected_target_commit
        ):
            raise GitWorkspaceError(
                "target_changed_before_integration",
                "目标分支在合入副作用边界发生变化，必须重新评估",
                details={
                    "expected_target_commit": expected_target_commit,
                    "current_target_commit": current_target_commit,
                },
            )
        if self._merge_in_progress(self.project):
            merge_head = self._text(["rev-parse", "MERGE_HEAD"])
            if merge_head != result_tip:
                raise GitWorkspaceError(
                    "target_merge_in_progress",
                    "本地目标工作树正在处理其他 Git merge",
                )
            pending = {
                "schema_version": "strixnova.git-integration.v1",
                "outcome": (
                    "conflict"
                    if self._has_unmerged_entries(self.project)
                    else "prepared"
                ),
                "target_ref": binding["target_ref"],
                "work_ref": binding["work_ref"],
                "result_commits": commits,
                "conflict_entries": self._status(self.project)["entries"],
            }
            if pending["outcome"] == "prepared" and not prepare_only:
                return self.commit_prepared_integration(
                    binding,
                    expected_result_commits=commits,
                    expected_target_commit=expected_target_commit,
                )
            return pending
        target_status = self._status(self.project)
        if target_status["dirty"]:
            raise GitWorkspaceError(
                "target_worktree_dirty",
                "本地目标分支存在未归属改动，不能自动合入",
                details=target_status["entries"],
            )
        if strategy == "ff_only":
            if self._run(
                [
                    "merge-base",
                    "--is-ancestor",
                    current_target_commit,
                    result_tip,
                ],
                allow_failure=True,
            ).exit_code != 0:
                raise GitWorkspaceError(
                    "ff_only_not_possible",
                    "目标分支与结果提交已经分叉，不能仅快进合入",
                )
            arguments = ["merge", "--ff-only", result_tip]
        else:
            arguments = [
                "merge",
                "--no-ff",
                "--no-commit",
                result_tip,
            ]
        result = self._run(arguments, allow_failure=True)
        if result.exit_code != 0:
            merge_head = self._run(
                ["rev-parse", "-q", "--verify", "MERGE_HEAD"],
                allow_failure=True,
            )
            if merge_head.exit_code == 0:
                return {
                    "schema_version": "strixnova.git-integration.v1",
                    "outcome": "conflict",
                    "target_ref": binding["target_ref"],
                    "work_ref": binding["work_ref"],
                    "result_commits": commits,
                    "conflict_entries": self._status(self.project)["entries"],
                }
            raise GitWorkspaceError(
                "merge_failed",
                "本地 Git 合入失败",
                details=result.stderr_text().strip(),
            )
        if strategy == "no_ff":
            prepared = {
                "schema_version": "strixnova.git-integration.v1",
                "outcome": "prepared",
                "target_ref": binding["target_ref"],
                "work_ref": binding["work_ref"],
                "result_commits": commits,
                "conflict_entries": [],
            }
            if prepare_only:
                return prepared
            return self.commit_prepared_integration(
                binding,
                expected_result_commits=commits,
                expected_target_commit=expected_target_commit,
            )
        return self.integration_result(
            binding,
            expected_result_commits=commits,
            expected_target_commit=expected_target_commit,
        )

    def commit_prepared_integration(
        self,
        work_area: dict[str, Any],
        *,
        expected_result_commits: list[str],
        expected_target_commit: str | None,
    ) -> dict[str, Any]:
        """Commit one already validated native no-ff merge."""

        binding = self._binding(work_area)
        if self._current_branch(self.project) != binding["target_ref"]:
            raise GitWorkspaceError(
                "target_not_checked_out",
                "主工作树不在 WorkItem 的 target_ref",
            )
        if not self._merge_in_progress(self.project):
            return self.integration_result(
                binding,
                expected_result_commits=expected_result_commits,
                expected_target_commit=expected_target_commit,
            )
        merge_head = self._text(["rev-parse", "MERGE_HEAD"])
        if merge_head != expected_result_commits[-1]:
            raise GitWorkspaceError(
                "target_merge_in_progress",
                "本地目标工作树正在处理其他 Git merge",
            )
        if self._has_unmerged_entries(self.project):
            raise GitWorkspaceError(
                "integration_conflict_unresolved",
                "本地目标工作树仍有未解决的 Git 冲突",
            )
        current_target_commit = self._text(["rev-parse", "HEAD"])
        if (
            expected_target_commit is not None
            and current_target_commit != expected_target_commit
        ):
            raise GitWorkspaceError(
                "target_changed_before_integration",
                "目标分支在合入提交形成前发生变化，必须重新评估",
            )
        committed = self._run(
            ["commit", "--no-edit"],
            allow_failure=True,
        )
        if committed.exit_code != 0:
            raise GitWorkspaceError(
                "merge_commit_failed",
                "本地 Git 合入候选已经验证，但 merge commit 形成失败",
                details=committed.stderr_text().strip(),
            )
        return self.integration_result(
            binding,
            expected_result_commits=expected_result_commits,
            expected_target_commit=expected_target_commit,
        )

    def abort_prepared_integration(
        self,
        work_area: dict[str, Any],
        *,
        expected_result_tip: str,
        expected_target_commit: str | None,
    ) -> None:
        """Abort only the exact merge prepared by this WorkItem."""

        binding = self._binding(work_area)
        if not self._merge_in_progress(self.project):
            return
        merge_head = self._text(["rev-parse", "MERGE_HEAD"])
        if merge_head != expected_result_tip:
            raise GitWorkspaceError(
                "target_merge_in_progress",
                "不能中止不属于当前 WorkItem 的 Git merge",
            )
        aborted = self._run(["merge", "--abort"], allow_failure=True)
        if aborted.exit_code != 0:
            raise GitWorkspaceError(
                "merge_abort_failed",
                "无法安全恢复尚未提交的本地合入候选",
                details=aborted.stderr_text().strip(),
            )
        if expected_target_commit is not None and self._text(
            ["rev-parse", "HEAD"]
        ) != expected_target_commit:
            raise GitWorkspaceError(
                "merge_abort_target_changed",
                "中止合入候选后目标提交不再等于副作用前记录",
            )

    def integration_result(
        self,
        work_area: dict[str, Any],
        *,
        expected_result_commits: list[str] | None = None,
        expected_target_commit: str | None = None,
    ) -> dict[str, Any]:
        binding = self._binding(work_area)
        if self._current_branch(self.project) != binding["target_ref"]:
            raise GitWorkspaceError(
                "target_not_checked_out",
                "主工作树不在 WorkItem 的 target_ref",
            )
        result_commits = (
            list(expected_result_commits)
            if expected_result_commits is not None
            else self._commit_list(binding)
        )
        if not result_commits:
            raise GitWorkspaceError(
                "result_commits_missing",
                "WorkItem 没有可复核的结果提交",
            )
        if self._run(
            [
                "merge-base",
                "--is-ancestor",
                result_commits[-1],
                binding["target_ref"],
            ],
            allow_failure=True,
        ).exit_code != 0:
            raise GitWorkspaceError(
                "integration_not_complete",
                "WorkItem 分支尚未合入本地目标分支",
            )
        target_tip = self._text(["rev-parse", binding["target_ref"]])
        integrated_commit = target_tip
        if expected_target_commit is not None:
            candidates = self._text(
                [
                    "rev-list",
                    "--first-parent",
                    "--reverse",
                    f"{expected_target_commit}..{target_tip}",
                ]
            ).splitlines()
            result_tip = result_commits[-1]
            exact = next(
                (
                    candidate
                    for candidate in candidates
                    if candidate == result_tip
                    or result_tip
                    in self._text(
                        ["rev-list", "--parents", "-n", "1", candidate]
                    ).split()[2:]
                ),
                None,
            )
            if exact is not None:
                integrated_commit = exact
        parent_line = self._text(
            ["rev-list", "--parents", "-n", "1", integrated_commit]
        ).split()
        if expected_target_commit is not None:
            exact_fast_forward = (
                integrated_commit == result_commits[-1]
                and self._run(
                    [
                        "merge-base",
                        "--is-ancestor",
                        expected_target_commit,
                        integrated_commit,
                    ],
                    allow_failure=True,
                ).exit_code
                == 0
            )
            exact_merge = (
                len(parent_line) >= 3
                and parent_line[1] == expected_target_commit
                and result_commits[-1] in parent_line[2:]
            )
            if not exact_fast_forward and not exact_merge:
                raise GitWorkspaceError(
                    "integration_recovery_target_changed",
                    "无法把目标分支当前提交识别为本事项的精确合入结果",
                    details={
                        "expected_target_commit": expected_target_commit,
                        "current_target_commit": target_tip,
                        "expected_result_tip": result_commits[-1],
                    },
                )
            contribution_base_commit = expected_target_commit
        else:
            contribution_base_commit = (
                parent_line[1]
                if len(parent_line) >= 3
                else str(binding["base_commit"])
            )
        return {
            "schema_version": "strixnova.git-integration.v1",
            "outcome": "integrated",
            "target_ref": binding["target_ref"],
            "work_ref": binding["work_ref"],
            "result_commits": result_commits,
            "integrated_commit": integrated_commit,
            "contribution_base_commit": contribution_base_commit,
        }

    def cleanup(self, work_area: dict[str, Any]) -> dict[str, Any]:
        binding = self._binding(work_area)
        if binding.get("created_by_strixnova") is not True:
            raise GitWorkspaceError(
                "branch_not_owned",
                "不会删除非 Strixnova 创建的分支",
            )
        if not str(binding["work_ref"]).startswith("strixnova/"):
            raise GitWorkspaceError(
                "branch_not_owned",
                "WorkItem 分支不属于 Strixnova 命名空间",
            )
        worktree = Path(binding["worktree_path"]).resolve()
        branch_exists = self._local_branch_exists(binding["work_ref"])
        registered = (
            self._registered_worktree(worktree, binding["work_ref"])
            if binding["worktree_mode"] == "linked"
            else False
        )
        if not branch_exists:
            if registered or (
                binding["worktree_mode"] == "linked" and worktree.exists()
            ):
                raise GitWorkspaceError(
                    "cleanup_state_inconsistent",
                    "WorkItem 分支已不存在，但并行 worktree 仍然存在",
                )
            return {
                "schema_version": "strixnova.git-cleanup.v1",
                "safe": True,
                "removed_worktree": (
                    str(worktree)
                    if binding["worktree_mode"] == "linked"
                    else None
                ),
                "removed_work_ref": binding["work_ref"],
            }
        if binding["worktree_mode"] == "linked" and not registered:
            if worktree.exists():
                raise GitWorkspaceError(
                    "worktree_not_registered",
                    "并行 worktree 不在 Git 登记中，且路径仍然存在",
                )
            self.integration_result(binding)
            self._run(["branch", "-d", binding["work_ref"]])
            return {
                "schema_version": "strixnova.git-cleanup.v1",
                "safe": True,
                "removed_worktree": str(worktree),
                "removed_work_ref": binding["work_ref"],
            }
        status = self._status(worktree)
        if status["dirty"]:
            raise GitWorkspaceError(
                "worktree_dirty",
                "WorkItem worktree 仍有未提交文件，不能清理",
                details=status["entries"],
            )
        if (
            binding["worktree_mode"] == "in_place"
            and self._current_branch(self.project) == binding["work_ref"]
        ):
            if self._run(
                [
                    "merge-base",
                    "--is-ancestor",
                    binding["work_ref"],
                    binding["target_ref"],
                ],
                allow_failure=True,
            ).exit_code != 0:
                raise GitWorkspaceError(
                    "integration_not_complete",
                    "WorkItem 分支尚未合入本地目标分支",
                )
            self._run(["switch", binding["target_ref"]])
        self.integration_result(binding)
        removed_worktree: str | None = None
        if binding["worktree_mode"] == "linked":
            self._run(["worktree", "remove", str(worktree)])
            removed_worktree = str(worktree)
        self._run(["branch", "-d", binding["work_ref"]])
        return {
            "schema_version": "strixnova.git-cleanup.v1",
            "safe": True,
            "removed_worktree": removed_worktree,
            "removed_work_ref": binding["work_ref"],
        }

    def rollback_empty_work_area(
        self,
        work_area: dict[str, Any],
    ) -> dict[str, Any]:
        """Undo a just-created work area only while it contains no work."""

        binding = self._binding(work_area)
        if (
            binding.get("created_by_strixnova") is not True
            or not str(binding["work_ref"]).startswith("strixnova/")
        ):
            raise GitWorkspaceError(
                "branch_not_owned",
                "不会回滚非 Strixnova 创建的分支",
            )
        worktree = Path(binding["worktree_path"]).resolve()
        if binding["worktree_mode"] == "linked" and not self._registered_worktree(
            worktree, binding["work_ref"]
        ):
            if worktree.exists():
                raise GitWorkspaceError("worktree_not_registered", "待回滚位置存在未登记目录，不能删除")
            if self._local_branch_exists(binding["work_ref"]):
                if self.resolve_commit(binding["work_ref"]) != binding["base_commit"]:
                    raise GitWorkspaceError("work_area_not_empty", "未完成建立的工作分支已经有新内容，不能自动删除")
                self._run(["branch", "-D", binding["work_ref"]])
            return {"schema_version": "strixnova.git-work-area-rollback.v1", "safe": True, "rolled_back": True, "removed_worktree": None, "removed_work_ref": binding["work_ref"]}
        status = self._status(worktree)
        commits = self.result_commits(binding, require_clean=False)
        if status["dirty"] or commits:
            raise GitWorkspaceError(
                "work_area_not_empty",
                "WorkItem 已经产生改动，不能作为初始化回滚删除",
                details={"status": status, "commits": commits},
            )
        removed_worktree: str | None = None
        if binding["worktree_mode"] == "linked":
            self._run(["worktree", "remove", str(worktree)])
            removed_worktree = str(worktree)
        else:
            self._run(["switch", binding["target_ref"]])
        self._run(["branch", "-D", binding["work_ref"]])
        return {
            "schema_version": "strixnova.git-work-area-rollback.v1",
            "safe": True,
            "rolled_back": True,
            "removed_worktree": removed_worktree,
            "removed_work_ref": binding["work_ref"],
        }

    def cancellation_state(
        self,
        work_area: dict[str, Any],
    ) -> dict[str, Any]:
        binding = self._binding(work_area)
        worktree = Path(binding["worktree_path"]).resolve()
        if binding["worktree_mode"] == "linked" and not self._registered_worktree(worktree, binding["work_ref"]):
            if worktree.exists():
                raise GitWorkspaceError("worktree_not_registered", "待取消位置存在未登记目录，不能推断其归属")
            commits = self._commit_list(binding) if self._local_branch_exists(binding["work_ref"]) else []
            return {"schema_version": "strixnova.git-cancellation-state.v1", "dirty": False, "entries": [], "result_commits": commits, "unmerged_commits": commits, "already_integrated": False, "requires_user_decision": bool(commits), "worktree_missing": True}
        status = self._status(worktree)
        current_branch = self._current_branch(self.project)
        commits = (
            self._commit_list(binding)
            if binding["worktree_mode"] == "in_place"
            and current_branch == binding["target_ref"]
            else self.result_commits(binding, require_clean=False)
        )
        integrated = (
            self._run(
                [
                    "merge-base",
                    "--is-ancestor",
                    binding["work_ref"],
                    binding["target_ref"],
                ],
                allow_failure=True,
            ).exit_code
            == 0
        )
        unmerged_commits = [] if integrated else commits
        return {
            "schema_version": "strixnova.git-cancellation-state.v1",
            "dirty": status["dirty"],
            "entries": status["entries"],
            "result_commits": commits,
            "unmerged_commits": unmerged_commits,
            "already_integrated": integrated,
            "requires_user_decision": bool(
                status["dirty"] or unmerged_commits
            ),
        }

    def discard_cancelled_work(
        self,
        work_area: dict[str, Any],
        *,
        destructive_confirmed: bool,
    ) -> dict[str, Any]:
        binding = self._binding(work_area)
        if not destructive_confirmed:
            raise GitWorkspaceError(
                "destructive_confirmation_required",
                "丢弃未合入工作必须有明确用户确认",
            )
        if (
            binding.get("created_by_strixnova") is not True
            or not str(binding["work_ref"]).startswith("strixnova/")
        ):
            raise GitWorkspaceError(
                "branch_not_owned",
                "不会丢弃非 Strixnova 创建的分支",
            )
        if self._merge_in_progress(self.project):
            raise GitWorkspaceError(
                "target_merge_in_progress",
                "本地目标分支仍处于 Git merge 中；请先由 Agent 原生解决或中止冲突",
            )
        worktree = Path(binding["worktree_path"]).resolve()
        branch_exists = self._local_branch_exists(binding["work_ref"])
        if binding["worktree_mode"] == "linked":
            registered = self._registered_worktree(
                worktree,
                binding["work_ref"],
            )
            if registered:
                self._run(["worktree", "remove", "--force", str(worktree)])
            elif worktree.exists():
                raise GitWorkspaceError(
                    "worktree_not_registered",
                    "待丢弃 worktree 不在 Git 登记中，且路径仍然存在",
                )
        elif binding["worktree_mode"] == "in_place":
            current_branch = self._current_branch(self.project)
            if not branch_exists and current_branch == binding["target_ref"]:
                return {
                    "schema_version": "strixnova.git-cancel-discard.v1",
                    "discarded": True,
                    "removed_worktree": None,
                    "removed_work_ref": binding["work_ref"],
                }
            if current_branch == binding["work_ref"]:
                self._run(["reset", "--hard", binding["base_commit"]])
                self._run(["clean", "-fd"])
                self._run(["switch", binding["target_ref"]])
            elif current_branch != binding["target_ref"]:
                raise GitWorkspaceError(
                    "worktree_binding_changed",
                    "主工作树已经离开待丢弃的 WorkItem 分支",
                )
        if self._local_branch_exists(binding["work_ref"]):
            self._run(["branch", "-D", binding["work_ref"]])
        return {
            "schema_version": "strixnova.git-cancel-discard.v1",
            "discarded": True,
            "removed_worktree": (
                str(worktree) if binding["worktree_mode"] == "linked" else None
            ),
            "removed_work_ref": binding["work_ref"],
        }

    def artifact_commits(
        self,
        relative_path: str,
        *,
        ref: str = "HEAD",
    ) -> dict[str, Any]:
        raw = self._repository_path(relative_path)
        commit = self.resolve_commit(ref)
        result = self._run(
            ["log", "--format=%H", "--follow", commit, "--", raw],
            allow_failure=True,
        )
        commits = [
            line.strip()
            for line in result.stdout_text().splitlines()
            if line.strip()
        ]
        return {
            "path": raw,
            "introduced_commit": commits[-1] if commits else None,
            "updated_commit": commits[0] if commits else None,
        }

    def resolve_commit(self, ref: str) -> str:
        """Resolve a caller-selected Git ref to the immutable observed commit."""

        selected = _valid_ref(ref, "observed_ref")
        if (
            re.fullmatch(r"[0-9a-f]{40,64}", selected)
            and selected in self._verified_commits
        ):
            return selected
        result = self._run(
            ["rev-parse", "--verify", f"{selected}^{{commit}}"],
            allow_failure=True,
        )
        commit = result.stdout_text().strip()
        if result.exit_code != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", commit):
            raise GitWorkspaceError(
                "observed_ref_missing",
                f"Git ref 不存在或不是提交：{selected}",
            )
        # Only immutable object identities are memoized. Branches and other
        # moving refs are deliberately resolved on every call.
        self._verified_commits.add(commit)
        return commit

    def path_exists_at(self, ref: str, relative_path: str) -> bool:
        """Return whether one ordinary repository file exists at a Git commit."""

        commit = self.resolve_commit(ref)
        path = self._repository_path(relative_path)
        return (
            self._run(
                ["cat-file", "-e", f"{commit}:{path}"],
                allow_failure=True,
            ).exit_code
            == 0
        )

    def read_file_at(self, ref: str, relative_path: str) -> bytes:
        """Read one file from Git without materializing a parallel snapshot."""

        commit = self.resolve_commit(ref)
        path = self._repository_path(relative_path)
        result = self._run(
            ["show", f"{commit}:{path}"],
            allow_failure=True,
        )
        if result.exit_code != 0:
            raise GitWorkspaceError(
                "git_path_missing",
                f"{path} 在 Git 提交 {commit} 中不存在",
            )
        return result.stdout

    def tracked_paths_at(
        self,
        ref: str,
        *,
        prefix: str | None = None,
    ) -> list[str]:
        """Return Git-tracked paths at one immutable commit.

        This is a native Git projection used by long-lived engineering models.
        It does not persist a second project file inventory.
        """

        commit = self.resolve_commit(ref)
        arguments = [
            "-c",
            "core.quotepath=false",
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            commit,
        ]
        if prefix is not None:
            arguments.extend(["--", self._repository_path(prefix)])
        result = self._run(arguments)
        return sorted(_git_paths(result.stdout, "Git 跟踪路径"))

    def changed_paths_between(
        self,
        older_ref: str,
        newer_ref: str,
    ) -> list[str]:
        """Derive changed paths between two commits without storing a ledger."""

        older = self.resolve_commit(older_ref)
        newer = self.resolve_commit(newer_ref)
        result = self._run(
            [
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-only",
                "-z",
                older,
                newer,
                "--",
            ]
        )
        return sorted(_git_paths(result.stdout, "Git 变化路径"))

    def is_ancestor(self, ancestor_ref: str, descendant_ref: str) -> bool:
        """Ask Git whether one selected commit is adopted by another."""

        ancestor = self.resolve_commit(ancestor_ref)
        descendant = self.resolve_commit(descendant_ref)
        return (
            self._run(
                ["merge-base", "--is-ancestor", ancestor, descendant],
                allow_failure=True,
            ).exit_code
            == 0
        )

    @staticmethod
    def _repository_path(relative_path: str) -> str:
        try:
            return repository_relative_path(relative_path, "Git 文件路径")
        except GitProjectReaderError as error:
            raise GitWorkspaceError(
                "invalid_artifact_path",
                "Git 文件路径必须是仓库内普通相对路径",
            ) from error

    def _binding(self, value: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(value, dict) or value.get(
            "schema_version"
        ) != GIT_WORK_AREA_SCHEMA:
            raise GitWorkspaceError(
                "invalid_work_area",
                "Git work area 格式无效",
            )
        if Path(str(value.get("repository") or "")).resolve() != self.project:
            raise GitWorkspaceError(
                "repository_mismatch",
                "Git work area 指向其他仓库",
            )
        _valid_ref(str(value.get("target_ref") or ""), "target_ref")
        _valid_ref(str(value.get("work_ref") or ""), "work_ref")
        mode = str(value.get("worktree_mode") or "")
        if mode not in {"in_place", "linked"}:
            raise GitWorkspaceError(
                "invalid_work_area",
                "Git work area 缺少有效 worktree_mode",
            )
        worktree = Path(str(value.get("worktree_path") or "")).resolve()
        if mode == "in_place" and worktree != self.project:
            raise GitWorkspaceError(
                "invalid_work_area",
                "in_place 工作区必须是项目主工作树",
            )
        if mode == "linked" and (
            worktree == self.project or self.project in worktree.parents
        ):
            raise GitWorkspaceError(
                "invalid_work_area",
                "linked 工作区必须位于项目仓库之外",
            )
        base_commit = str(value.get("base_commit") or "")
        if not re.fullmatch(r"[0-9a-f]{40,64}", base_commit):
            raise GitWorkspaceError(
                "invalid_base_commit",
                "base_commit 无效",
            )
        return dict(value)

    def _require_local_branch(self, branch: str) -> None:
        if not self._local_branch_exists(branch):
            raise GitWorkspaceError(
                "target_ref_missing",
                f"本地目标分支不存在：{branch}",
            )

    def _local_branch_exists(self, branch: str) -> bool:
        return (
            self._run(
                ["show-ref", "--verify", "--quiet", f"refs/heads/{branch}"],
                allow_failure=True,
            ).exit_code
            == 0
        )

    def _current_branch(self, cwd: Path) -> str | None:
        result = self._run(
            ["symbolic-ref", "--short", "-q", "HEAD"],
            cwd=cwd,
            allow_failure=True,
        )
        return result.stdout_text().strip() or None

    def _status(self, cwd: Path) -> dict[str, Any]:
        result = self._run(
            [
                "-c",
                "core.quotepath=false",
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            cwd=cwd,
        )
        records = [
            item.decode("utf-8", errors="replace")
            for item in result.stdout.split(b"\0")
            if item
        ]
        return {"dirty": bool(records), "entries": records}

    def _registered_worktree(self, path: Path, branch: str) -> bool:
        result = self._run(["worktree", "list", "--porcelain"])
        current_path: Path | None = None
        for line in result.stdout_text().splitlines():
            if line.startswith("worktree "):
                current_path = Path(line.removeprefix("worktree ")).resolve()
            elif line == f"branch refs/heads/{branch}" and current_path == path:
                return True
        return False

    def _require_worktree_binding(self, path: Path, branch: str) -> None:
        if not self._registered_worktree(path, branch):
            raise GitWorkspaceError(
                "worktree_binding_changed",
                "WorkItem worktree 不再绑定记录的 work_ref",
            )
        current = self._current_branch(path)
        if current != branch:
            raise GitWorkspaceError(
                "worktree_branch_mismatch",
                f"WorkItem worktree 当前是 {current or '<detached>'}，不是 {branch}",
            )

    def _merge_in_progress(self, cwd: Path) -> bool:
        return (
            self._run(
                ["rev-parse", "-q", "--verify", "MERGE_HEAD"],
                cwd=cwd,
                allow_failure=True,
            ).exit_code
            == 0
        )

    def _has_unmerged_entries(self, cwd: Path) -> bool:
        return any(
            len(entry) >= 2
            and ("U" in entry[:2] or entry[:2] in {"AA", "DD"})
            for entry in self._status(cwd)["entries"]
        )

    def _text(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
    ) -> str:
        return self._run(arguments, cwd=cwd).stdout_text().strip()

    def _run(
        self,
        arguments: list[str],
        *,
        cwd: Path | None = None,
        allow_failure: bool = False,
    ) -> ProcessResult:
        working_directory = (cwd or self.project).resolve()
        environment = dict(os.environ)
        environment.update(
            {
                "GIT_CONFIG_COUNT": "3",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": self.project.as_posix(),
                "GIT_CONFIG_KEY_1": "safe.directory",
                "GIT_CONFIG_VALUE_1": working_directory.as_posix(),
                "GIT_CONFIG_KEY_2": "core.fsmonitor",
                "GIT_CONFIG_VALUE_2": "false",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        try:
            command = [str(self.git), *arguments]
            result = run_process(
                command,
                cwd=working_directory,
                policy=ProcessPolicy.exact(
                    "strixnova.git-workspace.v1",
                    "local_git_delivery",
                    command,
                ),
                env=environment,
                limits=ProcessLimits(
                    timeout_seconds=60,
                    cleanup_timeout_seconds=10,
                    max_output_bytes=16 * 1024 * 1024,
                ),
            )
        except ProcessExecutionError as error:
            raise GitWorkspaceError(
                error.reason,
                str(error),
                details=(
                    error.partial_result.stderr_text()
                    if error.partial_result is not None
                    else None
                ),
            ) from error
        if result.exit_code != 0 and not allow_failure:
            raise GitWorkspaceError(
                "git_command_failed",
                "本地 Git 命令失败",
                details={
                    "arguments": arguments,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr_text().strip(),
                },
            )
        return result


__all__ = [
    "GIT_WORK_AREA_SCHEMA",
    "GitWorkspace",
    "GitWorkspaceError",
]
