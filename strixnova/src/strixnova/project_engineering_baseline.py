"""Narrow project baseline containing only exact authority adoption facts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from importlib.resources import files
import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
    repository_relative_path,
)
from strixnova.schema_error_reporting import schema_error_message
from strixnova.project_context import (
    DEFAULT_BASELINE_PATH,
    PROJECT_CONFIG_SCHEMA,
    ProjectContext,
    ProjectContextError,
    ProjectContextResolver,
    read_project_configuration,
)


BASELINE_SCHEMA = "strixnova.project-engineering-baseline.v1"
AUTHORITY_KINDS = (
    "product_definition",
    "domain_model",
    "target_architecture",
    "engineering_policy",
    "implementation_alignment",
)
UPSTREAM_AUTHORITY_KINDS = AUTHORITY_KINDS[:-1]
_IDENTITY_FIELD_BY_KIND = {
    "product_definition": "product_id",
    "domain_model": "model_id",
    "target_architecture": "architecture_id",
    "engineering_policy": "policy_id",
    "implementation_alignment": "alignment_model_id",
}


class ProjectEngineeringBaselineError(ValueError):
    """The project configuration or narrow baseline is invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目工程基线无效")


def _schema_issues(value: Mapping[str, Any]) -> list[str]:
    resource = files("strixnova.resources").joinpath(
        "project-engineering-baseline-v1.schema.json"
    )
    schema = json.loads(resource.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    result: list[str] = []
    for error in errors:
        path = ".".join(str(item) for item in error.absolute_path)
        location = f" {path}" if path else ""
        result.append(
            "项目工程基线"
            f"{location} 不符合当前结构合同："
            + schema_error_message(error)
        )
    return result


class ProjectEngineeringBaseline:
    """Deep interface for project identity and exact authority references only."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
        shared_context: ProjectContext | None = None,
    ) -> None:
        try:
            if shared_context is not None and observed_ref is not None:
                raise ProjectContextError("project_context_scope_conflict", "已绑定项目上下文不能另选配置版本")
            if shared_reader is not None:
                project_reader_for_scope(project_dir, observed_ref=observed_ref, shared_reader=shared_reader)
            self.context = shared_context or ProjectContextResolver(project_dir).configured(
                observed_ref=(shared_reader.observed_commit if shared_reader is not None else observed_ref),
            )
            if self.context is None:
                self.reader = project_reader_for_scope(
                    project_dir, observed_ref=observed_ref, shared_reader=shared_reader,
                )
                self._configuration = read_project_configuration(self.reader)
                self._baseline_path = DEFAULT_BASELINE_PATH
            else:
                assert self.context.configuration is not None
                assert self.context.configuration_reader is not None
                self._configuration = deepcopy(self.context.configuration)
                reference = self._configuration["engineering_baseline"]
                selected = self.context.authority_reader(
                    reference, parent_reader=self.context.configuration_reader,
                )
                if shared_reader is not None:
                    if (shared_reader.project != selected.project
                            or shared_reader.observed_commit != selected.observed_commit):
                        raise ProjectContextError("project_context_scope_conflict", "共享读取器不属于选定基线范围")
                    member = self.context.repository(reference["repository_id"])
                    assert member.scope is not None
                    self.reader = shared_reader.bind_repository(member.scope)
                else:
                    self.reader = selected
                self._baseline_path = reference["path"]
        except (GitProjectReaderError, ProjectContextError) as error:
            failure = ProjectEngineeringBaselineError(getattr(error, "issues", [str(error)]))
            failure.code = error.code
            raise failure from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit

    def project_configuration(self) -> dict[str, Any]:
        return deepcopy(self._configuration)

    @property
    def configuration_commit(self) -> str | None:
        if self.context is not None and self.context.configuration_reader is not None:
            return self.context.configuration_reader.observed_commit
        return self.observed_commit

    @property
    def scope_key(self) -> str:
        scope = {
            "configuration_commit": self.configuration_commit,
            "configuration_path": self.context.configuration_path if self.context else "strixnova-project.yaml",
            "baseline_root": str(self.project), "baseline_commit": self.observed_commit,
            "baseline_path": self._baseline_path,
            "declaration": self.context.declaration_sha256 if self.context else None,
            "bindings": self.context.bindings_sha256 if self.context else None,
        }
        return hashlib.sha256(json.dumps(scope, sort_keys=True).encode("utf-8")).hexdigest()

    def locate(self) -> Path:
        return self.project.joinpath(*self._baseline_path.split("/"))

    def project_config_exists(self) -> bool:
        return self._configuration["_configuration_explicit"]

    def engineering_baseline_exists(self) -> bool:
        relative = self.locate().relative_to(self.project).as_posix()
        return self.reader.exists(relative)

    def load(
        self,
        *,
        required: bool = False,
        allow_candidate_refs: bool = False,
    ) -> dict[str, Any] | None:
        relative = self.locate().relative_to(self.project).as_posix()
        if not self.reader.exists(relative):
            if required:
                raise ProjectEngineeringBaselineError(
                    [f"项目工程基线不存在：{relative}"]
                )
            return None
        if self.context is None:
            raise ProjectEngineeringBaselineError(["读取项目基线需要明确项目配置及仓库身份"])
        try:
            value = self.reader.load_yaml(relative, "项目工程基线")
        except GitProjectReaderError as error:
            raise ProjectEngineeringBaselineError([str(error)]) from error
        if not isinstance(value, Mapping):
            raise ProjectEngineeringBaselineError(["项目工程基线必须是对象"])
        return self.validate(
            value,
            manifest_path=relative,
            allow_candidate_refs=allow_candidate_refs,
        )

    def observe_code_version(self) -> dict[str, Any]:
        """Return current code identity without exposing the reader boundary."""

        try:
            commit = self.observed_commit or self.reader.resolve_commit("HEAD")
            worktree_state = (
                "clean"
                if self.observed_commit is not None
                else (
                    "dirty" if self.reader.worktree_dirty() else "clean"
                )
            )
        except GitProjectReaderError as error:
            raise ProjectEngineeringBaselineError([str(error)]) from error
        return {
            "schema_version": "strixnova.observed-code-version.v1",
            "base_commit": commit,
            "worktree_state": worktree_state,
            "immutable_observation": self.observed_commit is not None,
        }

    def resolve_code_ref(self, reference: str) -> str:
        """Resolve one project version reference through the stable baseline seam."""

        if not isinstance(reference, str) or not reference.strip():
            raise ProjectEngineeringBaselineError(
                ["代码版本引用必须是非空字符串"]
            )
        try:
            source = self.context.configuration_reader if self.context is not None else self.reader
            assert source is not None
            return source.resolve_commit(reference.strip())
        except GitProjectReaderError as error:
            raise ProjectEngineeringBaselineError([str(error)]) from error

    def validate(
        self,
        value: Mapping[str, Any],
        *,
        manifest_path: str | None = None,
        allow_candidate_refs: bool = False,
    ) -> dict[str, Any]:
        if value.get("schema_version") != BASELINE_SCHEMA:
            raise ProjectEngineeringBaselineError(
                ["项目工程基线必须使用当前仓库限定合同"]
            )
        issues = _schema_issues(value)
        components = value.get("code_version", {}).get("repositories", [])
        identifiers = [entry.get("repository_id") for entry in components if isinstance(entry, Mapping)]
        if len(identifiers) != len(set(identifiers)):
            issues.append("代码观察组合不能重复引用同一仓库")
        if self.context is not None:
            declared = {entry.repository_id for entry in self.context.repositories}
            if set(identifiers) - declared:
                issues.append("代码观察组合引用了未声明仓库")
        authority_refs = value.get("authority_refs")
        normalized_paths: list[tuple[str, str]] = []
        if isinstance(authority_refs, Mapping):
            for kind in AUTHORITY_KINDS:
                reference = authority_refs.get(kind)
                if not isinstance(reference, Mapping):
                    continue
                try:
                    normalized_paths.append((str(reference.get("repository_id") or ""),
                        repository_relative_path(
                            reference.get("path"),
                            f"authority_refs.{kind}.path",
                        )
                    ))
                except GitProjectReaderError as error:
                    issues.append(str(error))
                if self.context is not None and not any(
                    item.repository_id == reference.get("repository_id") and item.membership == "member"
                    for item in self.context.repositories
                ):
                    issues.append(f"authority_refs.{kind} 必须引用本项目声明的成员仓库")
                status = reference.get("status")
                if not isinstance(status, Mapping):
                    continue
                revision_status = status.get("revision_status")
                adoption_status = status.get("adoption_status")
                if not allow_candidate_refs and kind in UPSTREAM_AUTHORITY_KINDS:
                    if (
                        revision_status != "confirmed"
                        or adoption_status != "current"
                    ):
                        issues.append(
                            f"authority_refs.{kind} 必须精确采用已确认的当前上游权威"
                        )
                elif (
                    not allow_candidate_refs
                    and adoption_status == "current"
                    and revision_status != "confirmed"
                ):
                    issues.append(
                        f"authority_refs.{kind} 只有已确认修订才能成为当前采用权威"
                    )
                if (
                    adoption_status == "under_review"
                    and kind != "implementation_alignment"
                    and not allow_candidate_refs
                ):
                    issues.append(
                        f"authority_refs.{kind} 不得以待复核状态替代当前上游权威"
                    )
        if len(normalized_paths) != len(set(normalized_paths)):
            issues.append("不同长期权威不得共享同一仓库中的同一文件路径")
        project = value.get("project")
        if isinstance(project, Mapping) and isinstance(authority_refs, Mapping):
            owner_id = project.get("owner_id")
            product = authority_refs.get("product_definition")
            if (
                not allow_candidate_refs
                and isinstance(product, Mapping)
                and product.get("status", {}).get("adoption_status")
                != "current"
            ):
                issues.append("项目必须恰有一个当前采用的已确认产品定义")
            if not isinstance(owner_id, str):
                issues.append("项目负责人身份无效")
            if self.context is not None and project.get("project_id") != self.context.project_id:
                issues.append("项目基线与项目配置身份不一致")
        review = value.get("review_state")
        if isinstance(review, Mapping):
            required = review.get("required")
            alignment = (
                authority_refs.get("implementation_alignment")
                if isinstance(authority_refs, Mapping)
                else None
            )
            alignment_under_review = (
                isinstance(alignment, Mapping)
                and alignment.get("status", {}).get("adoption_status")
                == "under_review"
            )
            if alignment_under_review and required is not True:
                issues.append("实现对齐处于待复核状态时基线必须标记需要复核")
        if issues:
            raise ProjectEngineeringBaselineError(issues)
        normalized = deepcopy(dict(value))
        normalized["_manifest_path"] = manifest_path
        normalized["_observed_commit"] = self.observed_commit
        normalized["semantic_content_machine_proven"] = False
        return normalized

    def select(self, section_names: Sequence[str]) -> dict[str, Any]:
        baseline = self.load(required=True)
        assert baseline is not None
        allowed = {
            "project",
            "authority_refs",
            "current_architecture_stage_id",
            "code_version",
            "review_state",
        }
        requested = [str(name) for name in section_names]
        unknown = sorted(set(requested) - allowed)
        if unknown:
            raise ProjectEngineeringBaselineError(
                ["未知项目工程基线章节：" + ", ".join(unknown)]
            )
        return {
            "schema_version": baseline["schema_version"],
            "baseline_id": baseline["baseline_id"],
            "sections": {
                name: deepcopy(baseline[name]) for name in requested
            },
            "observed_commit": self.observed_commit,
        }


__all__ = [
    "AUTHORITY_KINDS",
    "UPSTREAM_AUTHORITY_KINDS",
    "BASELINE_SCHEMA",
    "DEFAULT_BASELINE_PATH",
    "PROJECT_CONFIG_SCHEMA",
    "ProjectEngineeringBaseline",
    "ProjectEngineeringBaselineError",
]
