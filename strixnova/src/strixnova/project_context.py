"""Read project configuration and resolve supplied repository contexts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from dataclasses import dataclass, field, replace
from importlib.resources import files
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    RepositoryReadScope,
    repository_relative_path,
)
from strixnova.schema_error_reporting import schema_error_message


PROJECT_CONFIG_SCHEMA = "strixnova.project-config.v1"
DEFAULT_BASELINE_PATH = "docs/engineering/baseline.yaml"
_OPERATION_CONTEXT: ContextVar[dict[str, Any] | None] = ContextVar("strixnova_project_context_operation", default=None)


class ProjectContextError(ValueError):
    """A supplied declaration, binding or requested scope cannot be used."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class ProjectConfigurationError(ProjectContextError):
    """The selected version of the project configuration cannot be used."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__(
            "project_configuration_invalid",
            "；".join(self.issues) or "项目配置无效",
            details=self.issues,
        )


def read_project_configuration(
    reader: GitProjectReader, path: str = "strixnova-project.yaml",
) -> dict[str, Any]:
    """Read only the locator from the caller's already selected content scope.

    This does not load the baseline, infer repository membership, or adopt a
    configuration. Both existence and content use the same reader, including
    when that reader is pinned to a historical commit.
    """

    path = repository_relative_path(path, "configuration.path")
    if not reader.exists(path):
        return {
            "schema_version": PROJECT_CONFIG_SCHEMA,
            "engineering_baseline": None,
            "default_integration_ref": None,
            "_configuration_explicit": False,
        }
    try:
        value = reader.load_yaml(path, "项目配置")
    except GitProjectReaderError as error:
        raise ProjectConfigurationError([str(error)]) from error
    if not isinstance(value, Mapping):
        raise ProjectConfigurationError(["strixnova-project.yaml 必须是对象"])
    if value.get("schema_version") != PROJECT_CONFIG_SCHEMA:
        raise ProjectConfigurationError([
            "项目配置必须使用 " + PROJECT_CONFIG_SCHEMA
            + "；配置必须声明明确的项目和仓库身份"
        ])
    schema = json.loads(files("strixnova.resources").joinpath(
        "project-config-v1.schema.json"
    ).read_text(encoding="utf-8"))
    issues = [
        ".".join(str(part) for part in error.absolute_path) + "：" + schema_error_message(error)
        for error in Draft202012Validator(schema).iter_errors(value)
    ]
    if issues:
        raise ProjectConfigurationError(issues)
    normalized = deepcopy(dict(value))
    try:
        normalized["engineering_baseline"]["path"] = repository_relative_path(
            value["engineering_baseline"]["path"], "engineering_baseline.path"
        )
    except GitProjectReaderError as error:
        issues.append(str(error))
    raw_ref = value.get("default_integration_ref")
    if raw_ref is not None and (not isinstance(raw_ref, str) or not raw_ref.strip()):
        issues.append("default_integration_ref 必须为空值或非空字符串")
    if issues:
        raise ProjectConfigurationError(issues)
    normalized["default_integration_ref"] = raw_ref.strip() if isinstance(raw_ref, str) else None
    normalized["_configuration_explicit"] = True
    return normalized


def project_context_contract(action: str) -> dict[str, Any]:
    if action in {"configuration", "bindings"}:
        name = "project-config-v1.schema.json" if action == "configuration" else "project-bindings-v1.schema.json"
        return json.loads(files("strixnova.resources").joinpath(name).read_text(encoding="utf-8"))
    if action not in {"inspect", "read"}:
        raise ProjectContextError("project_context_action_invalid", "上下文查询种类无效")
    schema = json.loads(
        files("strixnova.resources").joinpath("project-context-v1.schema.json").read_text(encoding="utf-8")
    )
    return {
        "$schema": schema["$schema"],
        "$id": f"strixnova.project-context-{action}.v1",
        "$ref": f"#/$defs/{action}_request",
        "$defs": schema["$defs"],
    }


def _validated_request(action: str, value: Mapping[str, Any]) -> dict[str, Any]:
    errors = sorted(
        Draft202012Validator(project_context_contract(action)).iter_errors(value),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        details = [
            {"path": ".".join(str(part) for part in error.absolute_path),
             "reason": schema_error_message(error)}
            for error in errors
        ]
        raise ProjectContextError(
            "project_context_input_invalid", "项目上下文输入不符合合同", details=details
        )
    return deepcopy(dict(value))


def _text(value: str, label: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ProjectContextError("project_context_input_invalid", f"{label} 不能为空白")
    return cleaned


def _ordinary_binding(entry: Path, value: str, label: str) -> Path:
    selected = Path(_text(value, label)).expanduser()
    if not selected.is_absolute():
        selected = entry / selected
    try:
        # Check lexical ancestors before collapsing .., so a link cannot be hidden.
        absolute = selected.absolute()
        for part in (absolute, *absolute.parents):
            if part.is_symlink() or part.is_junction():
                raise ProjectContextError(
                    "project_binding_link_forbidden", f"{label} 不得经过符号链接或联接点"
                )
        return Path(os.path.abspath(selected)).resolve()
    except (OSError, RuntimeError, ValueError) as error:
        if isinstance(error, ProjectContextError):
            raise
        raise ProjectContextError(
            "project_binding_path_invalid", f"无法解析 {label}"
        ) from error


def _digest(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class RepositoryContext:
    repository_id: str
    owner_project_id: str
    purpose: str
    membership: str
    availability: str
    checkout_path: Path | None = None
    scope: RepositoryReadScope | None = None
    issue_code: str | None = None

    def view(self) -> dict[str, Any]:
        return {
            "repository_id": self.repository_id,
            "owner_project_id": self.owner_project_id,
            "purpose": self.purpose,
            "membership": self.membership,
            "availability": self.availability,
            "checkout_path": str(self.checkout_path) if self.checkout_path is not None else None,
            "git_common_dir": str(self.scope.git_common_dir) if self.scope is not None else None,
            "issue_code": self.issue_code,
        }


@dataclass(frozen=True, slots=True)
class ProjectContext:
    project_id: str
    entry_root: Path
    management_root: Path
    declaration_sha256: str
    bindings_sha256: str
    repositories: tuple[RepositoryContext, ...]
    configuration: dict[str, Any] | None = None
    configuration_reader: GitProjectReader | None = None
    configuration_path: str = "strixnova-project.yaml"
    content_versions: dict[str, str | None] | None = field(default=None, compare=False, repr=False)
    _readers: dict[tuple[str, str | None], GitProjectReader] = field(
        default_factory=dict, compare=False, repr=False,
    )

    def repository(self, repository_id: str, *, for_modification: bool = False) -> RepositoryContext:
        selected = next((item for item in self.repositories if item.repository_id == repository_id), None)
        if selected is None:
            raise ProjectContextError(
                "project_repository_unknown", "项目声明中不存在该仓库",
                details={"repository_id": repository_id},
            )
        if for_modification and selected.membership != "member":
            raise ProjectContextError(
                "repository_not_owned_by_project", "外部依赖不属于本项目的修改范围",
                details={"repository_id": repository_id},
            )
        if selected.availability != "available":
            raise ProjectContextError(
                selected.issue_code or "repository_unavailable", "所需仓库当前不可用",
                details={"repository_id": repository_id, "availability": selected.availability},
            )
        return selected

    def bind_reference(self, reference: Mapping[str, Any]) -> GitProjectReader:
        selected = self.repository(str(reference.get("repository_id") or ""))
        repository_relative_path(reference.get("path"), "reference.path")
        ref = reference.get("ref")
        if ref is not None:
            if not isinstance(ref, str) or not ref.strip():
                raise ProjectContextError("project_context_input_invalid", "reference.ref 必须为空或非空文本")
            ref = ref.strip()
        assert selected.scope is not None
        return GitProjectReader.for_repository(selected.scope, observed_ref=ref)

    def authority_reader(
        self, reference: Mapping[str, Any], *, parent_reader: GitProjectReader,
    ) -> GitProjectReader:
        """Bind a member authority, inheriting only its own repository version."""

        identifier = str(reference.get("repository_id") or "")
        selected = self.repository(identifier, for_modification=True)
        repository_relative_path(reference.get("path"), "authority.path")
        ref = reference.get("ref")
        explicit_component = self.content_versions is not None and identifier in self.content_versions
        if ref is None and explicit_component:
            ref = self.content_versions[identifier]
        if identifier == parent_reader.repository_id and (
            ref is None or ref == parent_reader.observed_commit
        ):
            return parent_reader
        if ref is None and parent_reader.observed_commit is not None and not explicit_component:
            raise ProjectContextError(
                "cross_repository_commit_required",
                "不可变权威引用跨入另一仓库时必须给出精确提交",
                details={"repository_id": identifier, "path": reference["path"]},
            )
        key = (identifier, ref)
        if key not in self._readers:
            assert selected.scope is not None
            self._readers[key] = GitProjectReader.for_repository(selected.scope, observed_ref=ref)
        return self._readers[key]

    def view(self) -> dict[str, Any]:
        return {
            "schema_version": "strixnova.project-context-view.v1",
            "scope": "supplied_declaration",
            "project_id": self.project_id,
            "entry_root": str(self.entry_root),
            "management_root": str(self.management_root),
            "declaration_sha256": self.declaration_sha256,
            "bindings_sha256": self.bindings_sha256,
            "repositories": [item.view() for item in self.repositories],
            "declaration_adopted": False,
            "writes_performed": False,
            "limitations": [
                "身份与归属来自本次明确声明，本地 Git 核对不证明全机唯一性或用户授权。",
                "本接口只解析和读取，不采用声明或写入事项；正式事项和方案使用配置上下文入口。",
            ],
        }


class ProjectContextResolver:
    """Resolve one supplied declaration through the existing read-only Git seam."""

    def __init__(self, entry_dir: str | Path) -> None:
        self.entry = _ordinary_binding(Path.cwd(), str(entry_dir), "项目入口")
        if not self.entry.is_dir():
            raise ProjectContextError("project_entry_missing", "项目入口目录不存在")

    def resolve(self, request: Mapping[str, Any], *, action: str = "inspect") -> ProjectContext:
        payload = _validated_request(action, request)
        return self._resolve(payload)

    def configured(
        self, *, bindings: Mapping[str, Any] | None = None,
        observed_ref: str | None = None,
        use_execution_bindings: bool = True,
    ) -> ProjectContext | None:
        """Load the unique versioned locator using only explicitly bound paths."""

        operation = _OPERATION_CONTEXT.get()
        if operation is None:
            return self._configured(bindings=bindings, observed_ref=observed_ref)
        execution_bindings = operation.get("execution_bindings", {}).get(str(self.entry))
        inferred_history = bool(use_execution_bindings and bindings is None and execution_bindings is not None and observed_ref is not None)
        if use_execution_bindings and bindings is None and execution_bindings is not None:
            bindings = execution_bindings
        if bindings is None and self.entry == operation["entry"]:
            bindings = operation["bindings"]
        key = (str(self.entry), _digest(bindings), observed_ref, use_execution_bindings, inferred_history)
        if key not in operation["contexts"]:
            versions = operation.get("execution_versions", {}).get(str(self.entry)) if use_execution_bindings and observed_ref is None else None
            configuration_ref = versions.get(bindings["configuration"]["repository_id"]) if versions is not None and bindings is not None else observed_ref
            context = self._configured(bindings=bindings, observed_ref=configuration_ref, allow_unconfigured_history=inferred_history)
            operation["contexts"][key] = replace(context, content_versions=versions, _readers={}) if context is not None and versions is not None else context
        return operation["contexts"][key]

    def management_binding(self, bindings: Mapping[str, Any]) -> Path:
        """Validate the explicit state location without reading damaged content."""
        value = _validated_request("bindings", bindings)
        return _ordinary_binding(self.entry, value.get("management_root", "."), "管理数据位置")

    @contextmanager
    def operation(self, bindings: Mapping[str, Any] | None = None):
        """Share selected locators within one request, without loading state."""

        if _OPERATION_CONTEXT.get() is not None:
            yield
            return
        token = _OPERATION_CONTEXT.set({"entry": self.entry, "bindings": deepcopy(bindings), "contexts": {}})
        try:
            yield
        finally:
            _OPERATION_CONTEXT.reset(token)

    @contextmanager
    def execution_readers(self, context: ProjectContext | None, work_areas: Sequence[Mapping[str, Any]], *, observed_versions: Mapping[str, str | None] | None = None):
        """Carry explicit repository bindings into this operation's worktrees.

        Each recorded area must share the already selected repository identity.
        Only these exact directories become aliases; no common ancestor is used.
        """
        operation = _OPERATION_CONTEXT.get()
        if context is None or operation is None or not context.configuration:
            yield
            return
        resolved_areas = []
        resolved_versions = dict(observed_versions or {})
        for entry in work_areas:
            if entry.get("repository_id") is None:
                area = entry.get("git") or {}
                recorded_root = area.get("repository")
                candidates = [repository for repository in context.repositories
                              if recorded_root and repository.checkout_path == Path(recorded_root).resolve()]
                if len(candidates) != 1:
                    raise ProjectContextError("repository_worktree_identity_mismatch", "原未绑定工作区无法对应当前明确仓库")
                identity = candidates[0].repository_id
                if None in resolved_versions:
                    resolved_versions[identity] = resolved_versions.pop(None)
                entry = {**entry, "repository_id": identity}
            resolved_areas.append(entry)
        work_areas = resolved_areas
        observed_versions = resolved_versions or None
        roots = {entry.repository_id: str(entry.checkout_path) for entry in context.repositories if entry.checkout_path is not None and entry.availability == "available"}
        aliases = list(roots.values())
        versions = {entry["repository_id"]: None for entry in work_areas}
        versions.update(observed_versions or {})
        for entry in work_areas:
            area = entry.get("git") or {}
            integrated = (area.get("integration") or {}).get("integrated_commit")
            if integrated and entry["repository_id"] not in (observed_versions or {}):
                versions[entry["repository_id"]] = integrated
            if observed_versions is not None and entry["repository_id"] in observed_versions:
                aliases.append(roots[entry["repository_id"]])
            path = area.get("worktree_path")
            if not path or (area.get("cleanup") or {}).get("safe") is True:
                continue
            root = Path(path)
            # A missing worktree may be a cleanup whose writeback was interrupted.
            # Recovery must remain possible, without making it a readable alias.
            if not root.is_dir():
                continue
            repository = context.repository(entry["repository_id"], for_modification=True)
            scope = GitProjectReader(root).repository_scope(entry["repository_id"])
            if repository.scope is None or scope.git_common_dir != repository.scope.git_common_dir:
                raise ProjectContextError("repository_worktree_identity_mismatch", "记录的工作区不属于当前绑定仓库")
            if entry["repository_id"] not in (observed_versions or {}):
                roots[entry["repository_id"]] = str(root)
            aliases.append(str(root.resolve()))
        bindings = {
            "schema_version": "strixnova.project-bindings.v1", "project_id": context.project_id,
            "configuration": {"repository_id": context.configuration["repository_id"], "path": context.configuration_path},
            "management_root": str(context.management_root),
            "repositories": [{"repository_id": identifier, "path": path} for identifier, path in roots.items()],
        }
        replacement = {**operation, "contexts": {}, "execution_bindings": {**operation.get("execution_bindings", {}), **{alias: bindings for alias in aliases}}, "execution_versions": {**operation.get("execution_versions", {}), **{alias: versions for alias in aliases}}}
        token = _OPERATION_CONTEXT.set(replacement)
        try:
            yield
        finally:
            _OPERATION_CONTEXT.reset(token)

    def _configured(
        self, *, bindings: Mapping[str, Any] | None = None,
        observed_ref: str | None = None,
        allow_unconfigured_history: bool = False,
    ) -> ProjectContext | None:

        path = "strixnova-project.yaml"
        if bindings is None:
            root = self.entry
            requested_id = None
        else:
            schema = json.loads(files("strixnova.resources").joinpath(
                "project-bindings-v1.schema.json"
            ).read_text(encoding="utf-8"))
            errors = list(Draft202012Validator(schema).iter_errors(bindings))
            if errors:
                raise ProjectConfigurationError([schema_error_message(error) for error in errors])
            bindings = deepcopy(dict(bindings))
            requested_id = bindings["configuration"]["repository_id"]
            candidates = [item for item in bindings["repositories"] if item["repository_id"] == requested_id]
            if len(candidates) != 1:
                raise ProjectContextError("configuration_binding_required", "项目配置仓库需要唯一明确的本机绑定")
            root = _ordinary_binding(self.entry, candidates[0]["path"], "配置仓库")
            path = repository_relative_path(bindings["configuration"].get("path", path), "configuration.path")
        reader = GitProjectReader(root, observed_ref=observed_ref)
        configuration = read_project_configuration(reader, path)
        # Execution aliases locate today's candidate. They do not assert that
        # the default declaration already existed in this same repository's
        # investigation commit. Explicit caller bindings remain strict.
        optional_history = allow_unconfigured_history and root == self.entry and path == "strixnova-project.yaml"
        if not configuration["_configuration_explicit"]:
            if bindings is not None and not optional_history:
                raise ProjectContextError("project_configuration_missing", "明确绑定的项目配置不存在")
            return None
        identifier = configuration["repository_id"]
        if requested_id is not None and requested_id != identifier:
            raise ProjectContextError("configuration_repository_mismatch", "项目配置所属仓库与本机绑定不一致")
        if bindings is None:
            locations = {
                "project_id": configuration["project_id"],
                "management_root": ".",
                "repositories": [{"repository_id": identifier, "path": str(root)}],
            }
        else:
            locations = {key: deepcopy(bindings[key]) for key in ("project_id", "repositories")}
            locations["management_root"] = bindings.get("management_root", ".")
        scope = reader.bind_repository_identity(identifier)
        request = {
            "schema_version": "strixnova.project-context-inspect.v1",
            "declaration": {key: deepcopy(configuration[key]) for key in (
                "project_id", "repositories", "external_repositories"
            ) if key in configuration},
            "bindings": locations,
        }
        context = self._resolve(_validated_request("inspect", request), known_scopes={identifier: scope})
        configured_repository = context.repository(identifier, for_modification=True)
        baseline_repository = configuration["engineering_baseline"]["repository_id"]
        if not any(item.repository_id == baseline_repository and item.membership == "member" for item in context.repositories):
            raise ProjectContextError("baseline_repository_not_owned", "工程基线必须属于本项目已声明的成员仓库")
        assert configured_repository.scope is not None
        bound = reader
        if read_project_configuration(bound, path) != configuration:
            raise ProjectContextError("project_configuration_changed", "项目配置在本次解析期间发生变化")
        return replace(context, configuration=configuration, configuration_reader=bound, configuration_path=path)

    def _resolve(
        self, payload: dict[str, Any], *, known_scopes: Mapping[str, RepositoryReadScope] | None = None,
    ) -> ProjectContext:
        declaration, bindings = payload["declaration"], payload["bindings"]
        project_id = declaration["project_id"]
        if bindings["project_id"] != project_id:
            raise ProjectContextError("project_binding_identity_mismatch", "本机绑定与项目声明身份不一致")
        entries: dict[str, tuple[dict[str, Any], str]] = {}
        for field, membership in (("repositories", "member"), ("external_repositories", "external_dependency")):
            for item in declaration.get(field, []):
                identifier = item["repository_id"]
                if identifier in entries:
                    raise ProjectContextError("project_repository_duplicate", "项目声明重复使用仓库身份")
                if (membership == "member") != (item["owner_project_id"] == project_id):
                    raise ProjectContextError("repository_owner_mismatch", "仓库归属与成员或外部依赖声明不一致")
                item["purpose"] = _text(item["purpose"], "仓库用途")
                entries[identifier] = (item, membership)
        paths: dict[str, str] = {}
        for binding in bindings["repositories"]:
            identifier = binding["repository_id"]
            if identifier not in entries:
                raise ProjectContextError("project_binding_repository_unknown", "本机绑定引用未声明仓库")
            if identifier in paths:
                raise ProjectContextError("project_binding_duplicate", "一个仓库存在重复本机绑定")
            paths[identifier] = _text(binding["path"], "仓库路径")
        management = _ordinary_binding(self.entry, bindings.get("management_root", "."), "管理数据位置")
        if management.exists() and not management.is_dir():
            raise ProjectContextError("project_management_root_invalid", "管理数据位置必须是目录")
        resolved: list[RepositoryContext] = []
        for identifier, (item, membership) in entries.items():
            common = {
                "repository_id": identifier, "owner_project_id": item["owner_project_id"],
                "purpose": item["purpose"], "membership": membership,
            }
            if identifier not in paths:
                resolved.append(RepositoryContext(**common, availability="not_bound", issue_code="repository_not_bound"))
                continue
            selected_path = None
            try:
                selected_path = _ordinary_binding(self.entry, paths[identifier], "仓库路径")
                if not selected_path.exists():
                    resolved.append(RepositoryContext(**common, availability="missing", checkout_path=selected_path,
                                                      issue_code="repository_checkout_missing"))
                    continue
                if not selected_path.is_dir():
                    raise ProjectContextError(
                        "repository_binding_not_directory", "仓库本机绑定必须是目录"
                    )
                scope = (known_scopes or {}).get(identifier)
                if scope is None:
                    scope = GitProjectReader(selected_path).repository_scope(identifier)
                elif scope.project_dir != selected_path:
                    raise ProjectContextError("project_binding_identity_mismatch", "已选配置读取范围与本机绑定不一致")
                resolved.append(RepositoryContext(**common, availability="available", checkout_path=selected_path, scope=scope))
            except (ProjectContextError, GitProjectReaderError) as error:
                resolved.append(RepositoryContext(**common, availability="invalid", checkout_path=selected_path,
                                                  issue_code=error.code))
        common_dirs: dict[str, list[int]] = {}
        for index, item in enumerate(resolved):
            if item.scope is not None:
                key = os.path.normcase(str(item.scope.git_common_dir))
                common_dirs.setdefault(key, []).append(index)
        for indexes in common_dirs.values():
            if len(indexes) > 1:
                for index in indexes:
                    resolved[index] = replace(resolved[index], availability="conflict", issue_code="repository_binding_conflict")
        binding_snapshot = {
            "project_id": project_id,
            "entry_root": str(self.entry),
            "management_root": str(management),
            "repositories": [
                {
                    "repository_id": item.repository_id,
                    "checkout_path": str(item.checkout_path) if item.checkout_path is not None else None,
                    "git_common_dir": str(item.scope.git_common_dir) if item.scope is not None else None,
                    "availability": item.availability,
                    "issue_code": item.issue_code,
                }
                for item in resolved
            ],
        }
        return ProjectContext(
            project_id, self.entry, management, _digest(declaration),
            _digest(binding_snapshot), tuple(resolved),
        )

    def read(self, request: Mapping[str, Any]) -> dict[str, Any]:
        payload = _validated_request("read", request)
        context = self._resolve(payload)
        reference = payload["reference"]
        reader = context.bind_reference(reference)
        result = reader.content_window(
            reference["path"], offset=payload.get("offset", 0), limit=payload.get("limit", 65536),
            expected_sha256=payload.get("expected_sha256"),
        )
        return {
            **result,
            "project_id": context.project_id,
            "declaration_sha256": context.declaration_sha256,
            "bindings_sha256": context.bindings_sha256,
            "declaration_adopted": False,
        }


__all__ = [
    "DEFAULT_BASELINE_PATH", "PROJECT_CONFIG_SCHEMA", "ProjectConfigurationError",
    "ProjectContext", "ProjectContextError", "ProjectContextResolver",
    "RepositoryContext", "project_context_contract", "read_project_configuration",
]
