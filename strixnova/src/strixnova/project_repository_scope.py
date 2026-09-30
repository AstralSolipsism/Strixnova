"""Bind one planned repository scope without creating workflow or Git state."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from strixnova.git_project_reader import GitProjectReader
from strixnova.project_context import ProjectContext, ProjectContextError


def _fail(message: str) -> None:
    raise ProjectContextError("repository_scope_invalid", message)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} 必须是非空文本")
    return value.strip()


def select_repository(
    value: Mapping[str, Any], scope: Mapping[str, Any], *, modification: bool = False,
) -> str | None:
    """Resolve a shorthand only when its eligible scope is unambiguous."""

    entries = list(scope["repositories"])
    if modification:
        entries = [entry for entry in entries if entry["role"] == "modify"]
        if not entries:
            _fail("本次范围没有可修改仓库，不能计划文件操作")
    identifier = value.get("repository_id")
    if "repository_id" not in value:
        if len(entries) != 1:
            _fail("存在多个仓库时必须明确 repository_id")
        identifier = entries[0]["repository_id"]
    if not any(entry["repository_id"] == identifier for entry in entries):
        _fail("repository_id 不属于本次允许的修改或读取范围")
    return identifier


def qualify_candidate(
    candidate: Mapping[str, Any], scope: Mapping[str, Any],
) -> dict[str, Any]:
    """Add explicit repository identities to the same current input contract."""

    result = deepcopy(dict(candidate))
    result["repository_scope"] = deepcopy(dict(scope))
    for field, modification in (
        ("operations", True), ("source_references", False),
        ("verification_commands", False), ("domain_fact_changes", True),
        ("external_observation_provider_plans", False),
    ):
        entries = result.get(field, [])
        if not isinstance(entries, list):
            continue
        for item in entries:
            if isinstance(item, dict):
                writes = modification and not (field == "domain_fact_changes" and item.get("disposition") == "retain")
                item["repository_id"] = select_repository(item, scope, modification=writes)
    adr_plans = result.get("adr_plans", [])
    for item in adr_plans if isinstance(adr_plans, list) else []:
        if isinstance(item, dict) and item.get("disposition") in {"create", "update"}:
            item["repository_id"] = select_repository(item, scope, modification=True)
    return result


@dataclass(frozen=True)
class PreparedRepositoryScope:
    scope: dict[str, Any]
    requests: dict[str | None, str]
    readers: dict[str | None, GitProjectReader]
    configuration_reader: GitProjectReader

    def facts(self) -> dict[str, Any]:
        return {
            "scope": deepcopy(self.scope),
            "requests": [
                {"repository_id": key, "requested_ref": value}
                for key, value in self.requests.items()
            ],
            "repository_roots": [
                {"repository_id": key, "path": str(reader.project)}
                for key, reader in self.readers.items()
            ],
        }


def prepare_repository_scope(
    project: Path, candidate: Mapping[str, Any], context: ProjectContext | None,
) -> PreparedRepositoryScope:
    """Resolve declared IDs and refs; all project and content reads stay explicit."""

    change_context = candidate.get("change_context")
    formal = isinstance(change_context, Mapping) and change_context.get("formal_implementation") is True
    investigation = _text(candidate.get("investigation_ref"), "investigation_ref")
    configuration = context.configuration if context is not None else None
    configuration_source = context.configuration_reader if context is not None else None
    carrier = (configuration or {}).get("repository_id")
    project_id = context.project_id if context is not None else None
    carrier_root = configuration_source.project if configuration_source is not None else project
    if context is not None:
        selected = context.repository(carrier, for_modification=True)
        configuration_reader = GitProjectReader.for_repository(
            selected.scope, observed_ref=None if investigation == "working_tree" else investigation,
        )
    else:
        configuration_reader = GitProjectReader(
            carrier_root, observed_ref=None if investigation == "working_tree" else investigation,
        )
    raw = candidate.get("repository_scope")
    if raw is None:
        if context is not None and len([item for item in context.repositories if item.membership == "member"]) != 1:
            _fail("多仓库工程评估必须明确 repository_scope")
        raw = {"project_id": project_id, "repositories": [{
            "repository_id": carrier, "role": "modify" if formal else "read",
            "investigation_ref": investigation,
            "target_ref": (configuration or {}).get("default_integration_ref") if formal else None,
        }]}
    if not isinstance(raw, Mapping) or set(raw) - {"project_id", "repositories"}:
        _fail("repository_scope 只能声明 project_id 和 repositories")
    if raw.get("project_id", project_id) != project_id:
        _fail("repository_scope.project_id 与当前项目声明不一致")
    entries = raw.get("repositories")
    if not isinstance(entries, list) or not entries:
        _fail("repository_scope.repositories 必须是非空数组")
    normalized, requests, readers = [], {}, {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or set(entry) - {"repository_id", "role", "investigation_ref", "target_ref"}:
            _fail(f"repository_scope.repositories[{index}] 字段无效")
        if not {"repository_id", "role", "investigation_ref"} <= set(entry):
            _fail("每个仓库范围必须声明身份、角色及调查版本")
        identifier = entry["repository_id"]
        if not isinstance(identifier, (str, type(None))) or identifier in requests:
            _fail("仓库身份无效或重复")
        role = entry["role"]
        if not isinstance(role, str) or role not in {"modify", "read"} or (not formal and role == "modify"):
            _fail("仓库角色必须是 modify/read；非交付调查只能读取")
        reference = _text(entry["investigation_ref"], "repository.investigation_ref")
        target = entry.get("target_ref")
        if target is not None:
            target = _text(target, "repository.target_ref")
        if role == "read" and target is not None:
            _fail("只读依赖不能声明交付目标")
        if len(entries) > 1 and role == "modify" and target is None:
            _fail("多仓库修改范围必须逐项声明本地 target_ref")
        if context is None:
            if identifier is not None or len(entries) != 1:
                _fail("没有项目声明时不能编造仓库身份或建立多仓库范围")
            reader = GitProjectReader(project, observed_ref=None if reference == "working_tree" else reference)
        else:
            selected = context.repository(identifier, for_modification=role == "modify")
            reader = GitProjectReader.for_repository(
                selected.scope, observed_ref=None if reference == "working_tree" else reference,
            )
        if formal and investigation != "working_tree" and reader.observed_commit is None:
            _fail("正式方案的每个仓库必须绑定不可变调查提交")
        if target is not None:
            # An explicit target must exist; its current value is not substituted
            # for the investigation snapshot.
            reader.resolve_commit(target if target.startswith("refs/heads/") else "refs/heads/" + target)
        normalized.append({
            "repository_id": identifier, "role": role,
            "investigation_ref": reader.observed_commit or "working_tree", "target_ref": target,
        })
        requests[identifier], readers[identifier] = reference, reader
    scope = {"project_id": project_id, "repositories": normalized}
    return PreparedRepositoryScope(scope, requests, readers, configuration_reader)


def scope_for_candidate(
    candidate: Mapping[str, Any], prepared: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify a candidate still matches prepared scope facts before compiling."""

    scope = deepcopy(prepared["scope"])
    requested = {entry["repository_id"]: entry["requested_ref"] for entry in prepared["requests"]}
    raw = candidate.get("repository_scope")
    if raw is not None:
        if not isinstance(raw, Mapping) or set(raw) - {"project_id", "repositories"}:
            _fail("repository_scope 与可信读取范围不一致")
        if raw.get("project_id", scope["project_id"]) != scope["project_id"]:
            _fail("项目身份与可信读取范围不一致")
        rows = raw.get("repositories")
        if not isinstance(rows, list) or len(rows) != len(scope["repositories"]):
            _fail("仓库范围与可信读取范围不一致")
        for actual, expected in zip(rows, scope["repositories"], strict=True):
            if not isinstance(actual, Mapping) or set(actual) - set(expected):
                _fail("仓库范围字段与可信读取范围不一致")
            for field in ("repository_id", "role", "target_ref"):
                if actual.get(field) != expected[field]:
                    _fail("仓库身份、角色或目标与可信读取范围不一致")
            if actual.get("investigation_ref") not in {expected["investigation_ref"], requested[expected["repository_id"]]}:
                _fail("仓库调查版本与可信读取范围不一致")
    return scope


def repository_key(value: Mapping[str, Any], path: str) -> tuple[str | None, str]:
    return value.get("repository_id"), path
