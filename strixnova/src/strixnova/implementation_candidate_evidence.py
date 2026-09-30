"""Deterministic implementation evidence behind the application boundary.

This module compares planned file operations and immutable Git bytes.  It
does not decide whether an implementation, risk, or result is semantically
correct; ApplicationCoordinator remains the only public use-case entry.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
from pathlib import Path
from typing import Any

from strixnova.engineering_change_planning import (
    focused_slice,
    implementation_slice_reportability,
)
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.git_workspace import GitWorkspace
from strixnova.project_context import ProjectContextResolver
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.verification_runner import VerificationRunnerError
from strixnova.workflow_authority import WorkflowAuthorityError


IMPLEMENTATION_CANDIDATE_SNAPSHOT_SCHEMA = (
    "strixnova.implementation-candidate-snapshot.v1"
)


class ImplementationCandidateEvidence:
    """Own slice realization and accepted-delivery byte comparisons."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).resolve()

    @staticmethod
    def _work_area(current: Mapping[str, Any]) -> dict[str, Any]:
        data = current.get("data")
        value = data.get("git") if isinstance(data, Mapping) else None
        if not isinstance(value, Mapping) or value.get("schema_version") != (
            "strixnova.git-work-area.v1"
        ):
            raise WorkflowAuthorityError(
                "git_work_area_missing",
                "当前 WorkItem 没有有效的 Git 工作区记录",
            )
        return dict(value)

    @staticmethod
    def operation_refs(slice_value: Mapping[str, Any]) -> list[str]:
        return list(
            dict.fromkeys(
                [
                    *(slice_value.get("operation_refs") or []),
                    *(slice_value.get("continued_operation_refs") or []),
                ]
            )
        )

    @classmethod
    def operation_paths(
        cls,
        plan: Mapping[str, Any],
        slice_value: Mapping[str, Any],
        *, repository_id: Any = ...,
    ) -> list[str]:
        operations = list(plan.get("operations") or [])
        paths: set[str] = set()
        for reference in cls.operation_refs(slice_value):
            text = str(reference)
            if not text.startswith("operations[") or not text.endswith("]"):
                continue
            index_text = text[len("operations[") : -1]
            if not index_text.isdigit() or int(index_text) >= len(operations):
                continue
            operation = operations[int(index_text)]
            if not isinstance(operation, Mapping):
                continue
            if repository_id is not ... and operation.get("repository_id") != repository_id:
                continue
            for field in ("path", "to_path"):
                path = str(operation.get(field) or "").replace("\\", "/").strip()
                if path:
                    paths.add(path)
        return sorted(paths)

    def operation_realization(
        self,
        current: Mapping[str, Any],
        plan: Mapping[str, Any],
        slice_value: Mapping[str, Any],
        *,
        observed_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        operations = list(plan.get("operations") or [])
        work_area = self._work_area(current)
        base_commit = str(work_area.get("base_commit") or "")
        selected_scope = next((entry for entry in (plan.get("repository_scope") or {}).get("repositories", []) if entry["repository_id"] == current["data"].get("selected_repository_id")), {})
        if selected_scope.get("investigation_ref") not in {None, "working_tree"}:
            base_commit = selected_scope["investigation_ref"]
        try:
            base_reader = GitProjectReader(self.project, observed_ref=base_commit)
            current_reader = GitProjectReader(
                self.project,
                observed_ref=observed_ref,
            )
        except GitProjectReaderError as error:
            raise VerificationRunnerError(
                "implementation_operation_evidence_invalid",
                "无法读取实施切片的调查基点或当前工作树",
                details=[str(error)],
            ) from error
        results: list[dict[str, Any]] = []
        for reference in self.operation_refs(slice_value):
            text = str(reference)
            index_text = (
                text[len("operations[") : -1]
                if text.startswith("operations[") and text.endswith("]")
                else ""
            )
            if not index_text.isdigit() or int(index_text) >= len(operations):
                continue
            operation = operations[int(index_text)]
            if not isinstance(operation, Mapping):
                continue
            if "repository_id" in operation and operation["repository_id"] != current["data"].get("selected_repository_id"):
                continue
            action = str(operation.get("action") or "")
            path = str(operation.get("path") or "").replace("\\", "/")
            to_path = str(operation.get("to_path") or "").replace("\\", "/")
            base_exists = base_reader.exists(path)
            current_exists = current_reader.exists(path)
            realized = False
            if action == "create":
                realized = not base_exists and current_exists
            elif action == "delete":
                realized = base_exists and not current_exists
            elif action == "move":
                realized = (
                    base_exists
                    and not current_exists
                    and bool(to_path)
                    and current_reader.exists(to_path)
                )
            elif action == "modify" and base_exists and current_exists:
                try:
                    realized = base_reader.read_canonical_bytes(
                        path,
                        "实施前文件",
                    ) != current_reader.read_canonical_bytes(
                        path,
                        "实施后文件",
                    )
                except GitProjectReaderError as error:
                    raise VerificationRunnerError(
                        "implementation_operation_evidence_invalid",
                        "无法比较实施操作前后的规范文件字节",
                        details={"operation_ref": text, "error": str(error)},
                    ) from error
            results.append(
                {
                    "operation_ref": text,
                    **({"repository_id": operation["repository_id"]} if "repository_id" in operation else {}),
                    "action": action,
                    "path": path,
                    "to_path": to_path or None,
                    "realized": realized,
                }
            )
        return results

    def require_operations_realized(
        self,
        current: Mapping[str, Any],
        plan: Mapping[str, Any],
        slice_value: Mapping[str, Any],
        *,
        observed_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        results = self.operation_realization(
            current,
            plan,
            slice_value,
            observed_ref=observed_ref,
        )
        unrealized = [
            result["operation_ref"]
            for result in results
            if result["realized"] is not True
        ]
        if unrealized:
            raise VerificationRunnerError(
                "implementation_slice_operations_unrealized",
                "实施切片不能用摘要或验证回执冒充未形成的计划文件操作",
                details={
                    "slice_id": slice_value.get("slice_id"),
                    "unrealized_operation_refs": unrealized,
                    "operation_results": results,
                },
            )
        return results

    def path_snapshot(
        self,
        paths: Sequence[str],
        *,
        observed_ref: str | None = None,
    ) -> list[dict[str, str]]:
        reader = GitProjectReader(self.project, observed_ref=observed_ref)
        snapshot: list[dict[str, str]] = []
        existing = [path for path in sorted(set(paths)) if reader.exists(path)]
        try:
            contents = dict(reader.iter_canonical_files(existing, "实施切片完成证据"))
        except GitProjectReaderError as error:
            raise VerificationRunnerError("implementation_slice_snapshot_invalid", "无法形成实施切片文件的稳定完成证据", details=[str(error)]) from error
        for path in sorted(set(paths)):
            if path not in contents:
                snapshot.append({"path": path, "state": "absent", "sha256": ""})
                continue
            content = contents[path]
            snapshot.append(
                {
                    "path": path,
                    "state": "file",
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
        return snapshot

    def require_completed_slice_snapshots(
        self,
        current: Mapping[str, Any],
        *,
        observed_ref: str | None = None,
        exclude_paths: Sequence[str] = (),
    ) -> None:
        data = current.get("data")
        engineering = data.get("engineering") if isinstance(data, Mapping) else None
        plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
        completions = (
            data.get("implementation_slice_completions")
            if isinstance(data, Mapping)
            else []
        )
        if (
            not isinstance(plan, Mapping)
            or not isinstance(completions, list)
            or not completions
        ):
            return
        receipts = data.get("verifications") if isinstance(data, Mapping) else []
        current_slice = focused_slice(
            plan,
            receipts if isinstance(receipts, list) else [],
            completions,
        )
        active_paths = (
            set(self.operation_paths(plan, current_slice, repository_id=current["data"].get("selected_repository_id")))
            if isinstance(current_slice, Mapping)
            else set()
        )
        if observed_ref is not None:
            active_paths = set()
        excluded = {
            str(path).replace("\\", "/")
            for path in exclude_paths
            if str(path).strip()
        }
        try:
            baseline = ProjectEngineeringBaseline(self.project).locate()
            baseline_path = baseline.relative_to(self.project).as_posix() if baseline.is_relative_to(self.project) else ""
        except ProjectEngineeringBaselineError:
            baseline_path = ""
        if baseline_path:
            excluded.add(baseline_path)
        expected_by_path: dict[str, dict[str, str]] = {}
        slices_by_id = {
            str(value.get("slice_id") or ""): value
            for value in plan.get("implementation_slices") or []
            if isinstance(value, Mapping)
        }
        for completion in completions:
            if not isinstance(completion, Mapping):
                continue
            slice_id = str(completion.get("slice_id") or "")
            slice_value = slices_by_id.get(slice_id)
            if not isinstance(slice_value, Mapping):
                raise VerificationRunnerError(
                    "implementation_slice_snapshot_invalid",
                    "实施切片完成证据引用了当前方案中不存在的切片",
                    details={"slice_id": slice_id},
                )
            realized = self.require_operations_realized(
                current,
                plan,
                slice_value,
                observed_ref=observed_ref,
            )
            expected_results = [value for value in completion.get("operation_results") or [] if "repository_id" not in value or value["repository_id"] == current["data"].get("selected_repository_id")]
            if expected_results != realized:
                raise VerificationRunnerError(
                    "implementation_slice_operation_evidence_stale",
                    "实施切片完成记录与当前计划操作的真实结果不一致",
                    details={"slice_id": slice_id},
                )
            raw_snapshot = completion.get("owned_path_snapshot")
            if not isinstance(raw_snapshot, list):
                raise VerificationRunnerError(
                    "implementation_slice_snapshot_missing",
                    "已完成实施切片缺少不可变文件快照；必须重新规划并重新形成证据",
                    details={"slice_id": completion.get("slice_id")},
                )
            for entry in raw_snapshot:
                if "repository_id" in entry and entry["repository_id"] != current["data"].get("selected_repository_id"):
                    continue
                if isinstance(entry, Mapping) and str(entry.get("path") or ""):
                    expected_by_path[str(entry["path"])] = {
                        "path": str(entry["path"]),
                        "state": str(entry.get("state") or ""),
                        "sha256": str(entry.get("sha256") or ""),
                    }
        protected_paths = sorted(set(expected_by_path) - active_paths - excluded)
        actual = {
            entry["path"]: entry
            for entry in self.path_snapshot(
                protected_paths,
                observed_ref=observed_ref,
            )
        }
        changed = [
            path
            for path in protected_paths
            if actual.get(path) != expected_by_path[path]
        ]
        if changed:
            raise VerificationRunnerError(
                "implementation_slice_evidence_stale",
                "后续工作改写了已完成切片且未声明延续所有权；旧验证或完成证据已经失效",
                details={
                    "changed_paths": changed,
                    "current_slice_id": (
                        current_slice.get("slice_id")
                        if isinstance(current_slice, Mapping)
                        else None
                    ),
                },
            )

    def candidate_snapshot(
        self,
        current: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Bind one actual result to the exact final slice-controlled files."""

        data = current.get("data")
        engineering = data.get("engineering") if isinstance(data, Mapping) else None
        plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
        if not isinstance(plan, Mapping) or not plan.get("implementation_slices"):
            return None
        receipts = data.get("verifications") if isinstance(data, Mapping) else []
        completions = (
            data.get("implementation_slice_completions")
            if isinstance(data, Mapping)
            else []
        )
        reportability = implementation_slice_reportability(
            plan,
            receipts if isinstance(receipts, list) else [],
            completions if isinstance(completions, list) else [],
        )
        if not reportability.get("reportable"):
            raise VerificationRunnerError(
                "implementation_slices_incomplete",
                "尚不能形成实施结果文件快照",
            )
        not_executed = set(reportability.get("not_executed_slice_ids") or [])
        included_slices = [
            value
            for value in plan.get("implementation_slices") or []
            if isinstance(value, Mapping)
            and str(value.get("slice_id") or "") not in not_executed
        ]
        paths = sorted(
            {
                path
                for slice_value in included_slices
                for path in self.operation_paths(plan, slice_value, repository_id=current["data"].get("selected_repository_id"))
            }
        )
        work_area = self._work_area(current)
        workspace = GitWorkspace(str(work_area["repository"]))
        comparison_base_commit = str(work_area.get("base_commit") or "")
        if work_area.get("conflict_resolution") or (work_area.get("integration") or {}).get("outcome") == "conflict":
            comparison_base_commit = workspace.resolve_commit("HEAD")
            changed_paths = workspace.changed_worktree_paths_from(
                comparison_base_commit
            )
        else:
            changed_paths = workspace.changed_paths(dict(work_area))
        return {
            "schema_version": IMPLEMENTATION_CANDIDATE_SNAPSHOT_SCHEMA,
            "repository_id": current["data"].get("selected_repository_id"),
            "plan_id": str(plan.get("plan_id") or ""),
            "base_commit": str(work_area.get("base_commit") or ""),
            "comparison_base_commit": comparison_base_commit,
            "included_slice_ids": [
                str(value["slice_id"]) for value in included_slices
            ],
            "terminal_slice_id": reportability.get("terminal_slice_id"),
            "not_executed_slice_ids": sorted(not_executed),
            "changed_paths": changed_paths,
            "paths": self.path_snapshot(paths),
            "semantic_content_machine_proven": False,
        }

    def conflict_candidate_snapshot(
        self,
        current: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Bind an unchanged conflict resolution to the accepted delivery."""

        data = current.get("data")
        actual_result = data.get("actual_result") if isinstance(data, Mapping) else None
        accepted_snapshot = (
            actual_result.get("implementation_candidate_snapshot")
            if isinstance(actual_result, Mapping)
            else None
        )
        if isinstance(accepted_snapshot, Mapping) and accepted_snapshot.get("schema_version") == "strixnova.project-implementation-snapshot.v1":
            accepted_snapshot = next((entry for entry in accepted_snapshot["repositories"] if entry["repository_id"] == current["data"].get("selected_repository_id")), None)
        if not isinstance(accepted_snapshot, Mapping) or not isinstance(
            accepted_snapshot.get("paths"), list
        ):
            return None
        git = data.get("git") if isinstance(data, Mapping) else None
        resolution = (
            git.get("conflict_resolution") if isinstance(git, Mapping) else None
        )
        integration = git.get("integration") if isinstance(git, Mapping) else None
        conflict_entries = (
            resolution.get("conflict_entries")
            if isinstance(resolution, Mapping)
            else integration.get("conflict_entries")
            if isinstance(integration, Mapping)
            else []
        )
        conflict_paths = {
            str(entry)[3:].replace("\\", "/")
            for entry in conflict_entries or []
            if len(str(entry)) >= 4
            and ("U" in str(entry)[:2] or str(entry)[:2] in {"AA", "DD"})
        }
        accepted_by_path = {
            str(entry.get("path") or ""): dict(entry)
            for entry in accepted_snapshot["paths"]
            if isinstance(entry, Mapping)
            and str(entry.get("path") or "").strip()
        }
        unexpected_conflicts = sorted(conflict_paths - set(accepted_by_path))
        if unexpected_conflicts:
            raise VerificationRunnerError(
                "conflict_path_unplanned",
                "原生合入冲突包含负责人未确认的交付路径；必须重新规划",
                details=unexpected_conflicts,
            )
        non_conflict_paths = sorted(set(accepted_by_path) - conflict_paths)
        current_non_conflict = {
            entry["path"]: entry
            for entry in self.path_snapshot(non_conflict_paths)
        }
        changed_non_conflict = sorted(
            path
            for path in non_conflict_paths
            if current_non_conflict.get(path) != accepted_by_path[path]
        )
        if changed_non_conflict:
            raise VerificationRunnerError(
                "non_conflict_delivery_path_changed",
                "冲突解决改写了未发生原生冲突的已确认交付文件；不能扩大复测快照范围",
                details=changed_non_conflict,
            )
        replacement = {
            entry["path"]: entry
            for entry in self.path_snapshot(sorted(conflict_paths))
        }
        workspace = GitWorkspace(self.project)
        comparison_base_commit = workspace.resolve_commit("HEAD")
        actual_conflict_paths = set(
            workspace.changed_worktree_paths_from(comparison_base_commit)
        )
        expected_conflict_paths = {
            str(path).replace("\\", "/")
            for path in accepted_snapshot.get("changed_paths") or []
            if str(path).strip()
        }
        unexpected_paths = sorted(actual_conflict_paths - expected_conflict_paths)
        missing_paths = sorted(expected_conflict_paths - actual_conflict_paths)
        current_missing = {
            entry["path"]: entry for entry in self.path_snapshot(missing_paths)
        }
        unproven_missing = sorted(
            path
            for path in missing_paths
            if current_missing.get(path) != accepted_by_path.get(path)
        )
        if unexpected_paths or unproven_missing:
            raise VerificationRunnerError(
                "conflict_delivery_path_set_changed",
                "冲突解决后的本事项路径集合包含夹带，或缺失路径无法证明已同内容收敛",
                details={
                    "expected_paths": sorted(expected_conflict_paths),
                    "actual_paths": sorted(actual_conflict_paths),
                    "unexpected_paths": unexpected_paths,
                    "unproven_missing_paths": unproven_missing,
                },
            )
        conflict_snapshot = deepcopy(dict(accepted_snapshot))
        conflict_snapshot["paths"] = [
            replacement.get(path, accepted_by_path[path])
            for path in sorted(accepted_by_path)
        ]
        conflict_snapshot["comparison_base_commit"] = comparison_base_commit
        conflict_snapshot["changed_paths"] = sorted(expected_conflict_paths)
        return conflict_snapshot

    def require_candidate_snapshot(
        self,
        current: Mapping[str, Any],
        *,
        observed_ref: str | None = None,
        comparison_base_ref: str | None = None,
        exclude_paths: Sequence[str] = (),
        use_conflict_resolution: bool = False,
    ) -> None:
        """Reject any file swap after the owner saw the actual result."""

        data = current.get("data")
        actual_result = data.get("actual_result") if isinstance(data, Mapping) else None
        engineering = data.get("engineering") if isinstance(data, Mapping) else None
        plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
        if not isinstance(plan, Mapping) or not plan.get("implementation_slices"):
            return
        if use_conflict_resolution:
            git = data.get("git") if isinstance(data, Mapping) else None
            resolution = (
                git.get("conflict_resolution")
                if isinstance(git, Mapping)
                else None
            )
            snapshot = (
                resolution.get("implementation_candidate_snapshot")
                if isinstance(resolution, Mapping)
                else None
            )
        else:
            snapshot = (
                actual_result.get("implementation_candidate_snapshot")
                if isinstance(actual_result, Mapping)
                else None
            )
        if isinstance(snapshot, Mapping) and snapshot.get("schema_version") == "strixnova.project-implementation-snapshot.v1":
            snapshot = next((entry for entry in snapshot["repositories"] if entry["repository_id"] == current["data"].get("selected_repository_id")), None)
        if (
            not isinstance(snapshot, Mapping)
            or snapshot.get("schema_version")
            != IMPLEMENTATION_CANDIDATE_SNAPSHOT_SCHEMA
            or (snapshot.get("plan_id") != plan.get("plan_id") and snapshot != (data.get("git") or {}).get("integrated_content_snapshot"))
            or snapshot.get("semantic_content_machine_proven") is not False
            or not isinstance(snapshot.get("paths"), list)
            or not isinstance(snapshot.get("changed_paths"), list)
        ):
            raise VerificationRunnerError(
                "implementation_candidate_snapshot_missing",
                (
                    "冲突解决复测没有绑定当前目标工作树的完整实施文件快照"
                    if use_conflict_resolution
                    else "实际结果没有绑定当前方案的完整实施文件快照"
                ),
            )
        excluded = {
            str(path).replace("\\", "/")
            for path in exclude_paths
            if str(path).strip()
        }
        work_area = self._work_area(current)
        workspace = GitWorkspace(str(work_area["repository"]))
        base_commit = str(
            comparison_base_ref
            or snapshot.get("comparison_base_commit")
            or snapshot.get("base_commit")
            or ""
        )
        if observed_ref is None and (comparison_base_ref is not None or work_area.get("conflict_resolution")):
            actual_changed_paths = set(
                workspace.changed_worktree_paths_from(base_commit)
            )
        elif observed_ref is None:
            actual_changed_paths = set(workspace.changed_paths(dict(work_area)))
        else:
            actual_changed_paths = set(
                workspace.changed_paths_between(base_commit, observed_ref)
            )
        expected_changed_paths = {
            str(path).replace("\\", "/")
            for path in snapshot["changed_paths"]
            if str(path).strip()
        }
        missing_paths = sorted(
            (expected_changed_paths - excluded)
            - (actual_changed_paths - excluded)
        )
        unexpected_paths = sorted(
            (actual_changed_paths - excluded)
            - (expected_changed_paths - excluded)
        )
        converged_integration = comparison_base_ref is not None
        if unexpected_paths or (missing_paths and not converged_integration):
            raise VerificationRunnerError(
                "accepted_implementation_path_set_changed",
                "负责人确认后的完整交付路径集合发生了增删；不能夹带或遗漏文件",
                details={
                    "missing_paths": missing_paths,
                    "unexpected_paths": unexpected_paths,
                    "observed_ref": observed_ref or "working_tree",
                },
            )
        expected = {
            str(entry.get("path") or ""): dict(entry)
            for entry in snapshot["paths"]
            if isinstance(entry, Mapping)
            and str(entry.get("path") or "") not in excluded
        }
        actual = {
            entry["path"]: entry
            for entry in self.path_snapshot(
                sorted(expected),
                observed_ref=observed_ref,
            )
        }
        changed = sorted(
            path for path in expected if actual.get(path) != expected[path]
        )
        if changed:
            raise VerificationRunnerError(
                "accepted_implementation_candidate_changed",
                "负责人看到的实际结果文件在确认、提交或合入阶段发生了变化",
                details={
                    "changed_paths": changed,
                    "observed_ref": observed_ref or "working_tree",
                },
            )
        unproven_missing = sorted(path for path in missing_paths if path not in expected)
        if unproven_missing:
            raise VerificationRunnerError(
                "accepted_implementation_path_set_changed",
                "合入贡献中缺少的路径没有最终内容快照，不能证明为同内容收敛",
                details={
                    "missing_paths": unproven_missing,
                    "observed_ref": observed_ref,
                },
            )

    @staticmethod
    def mechanical_authority_paths(current: Mapping[str, Any]) -> list[str]:
        """Return only paths whose metadata was mechanically adopted."""

        data = current.get("data")
        adoption = data.get("authority_adoption") if isinstance(data, Mapping) else None
        if not isinstance(adoption, Mapping):
            return []
        identifier = data.get("selected_repository_id")
        if identifier is None:
            area = data.get("git") or {}
            recorded_root = area.get("repository")
            candidate_root = area.get("worktree_path") or recorded_root
            if candidate_root and not Path(candidate_root).is_dir():
                candidate_root = recorded_root
            if recorded_root and candidate_root:
                context = ProjectContextResolver(candidate_root).configured(use_execution_bindings=False)
                if context is not None:
                    native = GitProjectReader(recorded_root)
                    matches = [repository.repository_id for repository in context.repositories
                               if repository.membership == "member" and repository.scope is not None
                               and native.repository_scope(repository.repository_id).git_common_dir == repository.scope.git_common_dir]
                    if len(matches) == 1:
                        identifier = matches[0]
        paths = {str(adoption.get("baseline_path") or "").replace("\\", "/")} if adoption.get("baseline_repository_id") == identifier or "baseline_repository_id" not in adoption else set()
        paths.update(
            str(update.get("path") or "").replace("\\", "/")
            for update in adoption.get("authority_updates") or []
            if isinstance(update, Mapping) and ("repository_id" not in update or update["repository_id"] == identifier)
        )
        actual_result = data.get("actual_result")
        if isinstance(actual_result, Mapping):
            alignment_repository = (actual_result.get("authority_candidate_snapshot") or {}).get("authority_repositories", {}).get("implementation_alignment")
            paths.update(
                str(reference.get("path") or "").replace("\\", "/")
                for reference in actual_result.get("long_lived_refs") or []
                if isinstance(reference, Mapping)
                and reference.get("artifact_type") == "domain_alignment"
                and (alignment_repository == identifier or "authority_repositories" not in (actual_result.get("authority_candidate_snapshot") or {}))
            )
        return sorted(path for path in paths if path)


__all__ = [
    "IMPLEMENTATION_CANDIDATE_SNAPSHOT_SCHEMA",
    "ImplementationCandidateEvidence",
]
