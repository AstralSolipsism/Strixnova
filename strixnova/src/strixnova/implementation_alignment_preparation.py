"""Prepare observations and write implementation-alignment candidates.

The Module keeps observation, semantic decision binding, content-addressed
preparation artifacts, and recoverable candidate writes behind one Interface.
It never assigns product, domain, architecture, or owner meaning by itself.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any, Mapping, Sequence

import yaml

from strixnova.git_project_reader import (
    GitProjectReader, repository_relative_path, repository_scope_root,
)
from strixnova.project_content_snapshot import repository_path_key, split_repository_path_key
from strixnova.implementation_observation import observe_project_implementation, external_observation_providers_from_plans
from strixnova.project_domain_model import ProjectDomainModel
from strixnova.project_architecture_description import ProjectArchitectureDescription
from strixnova.engineering_change_planning import focused_slice
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.implementation_alignment_artifacts import (
    AlignmentArtifactError,
    ImplementationAlignmentArtifactStore,
)
from strixnova.project_implementation_alignment import (
    IMPLEMENTATION_OBSERVATION_SCHEMA,
    ProjectImplementationAlignment,
    ProjectImplementationAlignmentError,
    normalized_observed_relations,
)
from strixnova.recoverable_document_transaction import (
    DocumentTransactionError,
    recover_document_transactions,
    replace_documents,
)


PASSING_REFRESH_CLASSIFICATIONS = frozenset(
    {
        "internal_same_module",
        "allowed_direct",
        "allowed_read_only",
        "external_observed",
    }
)


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} 必须包含对象")
    return value


def _render(value: Mapping[str, Any]) -> bytes:
    return yaml.safe_dump(
        dict(value),
        allow_unicode=True,
        sort_keys=False,
    ).encode("utf-8")


def _atomic_dump_many(
    documents: Sequence[tuple[Path, Mapping[str, Any]]],
    *,
    validate_replaced: Callable[[], None] | None = None,
    transaction_root: Path | None = None,
    recovery_root: Path | None = None,
    allowed_targets: Sequence[Path] | None = None,
) -> None:
    """Replace a related YAML set through a crash-recoverable transaction."""

    replace_documents(
        [(target, _render(value)) for target, value in documents],
        validate_replaced=validate_replaced,
        transaction_root=transaction_root,
        recovery_root=recovery_root,
        allowed_targets=allowed_targets,
    )


def _scope_contains_path(scope: Mapping[str, Any], path: str) -> bool:
    root = PurePosixPath(str(scope["root"]))
    candidate = PurePosixPath(path)
    if candidate != root and root not in candidate.parents:
        return False
    relative = candidate.relative_to(root)
    return any(
        relative.as_posix() == str(pattern)
        or relative.match(str(pattern))
        for pattern in scope["included_path_patterns"]
    )


def _unique_governed_scope(
    scopes: Sequence[Mapping[str, Any]],
    path: str,
) -> Mapping[str, Any]:
    identifier, relative = split_repository_path_key(path) if any("repository_id" in scope for scope in scopes) else (None, path)
    matches = [scope for scope in scopes if ("repository_id" not in scope or scope["repository_id"] == identifier) and _scope_contains_path(scope, relative)]
    if len(matches) != 1:
        identities = [
            str(scope.get("scope_id") or f"index:{index}")
            for index, scope in enumerate(matches)
        ]
        raise ValueError(
            "每个受管源码文件必须且只能属于一个 governed_source_scope："
            f"{path} 匹配 {identities or '无作用域'}"
        )
    return matches[0]


def _governed_hashes(
    project: Path,
    scopes: Sequence[Mapping[str, Any]],
    repository_readers: Mapping[str | None, GitProjectReader] | None = None,
) -> dict[str, str]:
    if repository_readers is not None:
        hashes = {}
        for identifier in dict.fromkeys(scope.get("repository_id") for scope in scopes):
            if identifier not in repository_readers:
                raise ValueError(f"Required observation repository is unavailable: {identifier}")
            selected = [{key: value for key, value in scope.items() if key != "repository_id"} for scope in scopes if scope.get("repository_id") == identifier]
            reader = repository_readers[identifier]
            paths = set()
            for scope in selected:
                paths.update(path for path in reader.tracked_paths(scope["root"]) if _scope_contains_path(scope, path) and "__pycache__" not in PurePosixPath(path).parts)
            for path in paths:
                _unique_governed_scope(selected, path)
            hashes.update({repository_path_key(identifier, path): hashlib.sha256(content).hexdigest() for path, content in reader.iter_canonical_files(sorted(paths), "Scoped implementation source")})
        return hashes
    reader = GitProjectReader(project)
    paths: set[str] = set()
    for index, scope in enumerate(scopes):
        root = repository_scope_root(
            scope.get("root"),
            f"governed_source_scopes[{index}].root",
        )
        patterns = scope.get("included_path_patterns")
        if not isinstance(patterns, list) or not patterns:
            raise ValueError(
                f"governed_source_scopes[{index}].included_path_patterns 必须非空"
            )
        paths.update(
            path
            for path in reader.tracked_paths(root)
            if _scope_contains_path(scope, path)
            and "__pycache__" not in PurePosixPath(path).parts
        )
    ordered_paths = sorted(paths)
    for path in ordered_paths:
        _unique_governed_scope(scopes, path)
    reader.prefetch(ordered_paths)
    return {
        path: hashlib.sha256(
            reader.read_canonical_bytes(path, "受管实现文件")
        ).hexdigest()
        for path in ordered_paths
    }


def _manifest(hashes: Mapping[str, str]) -> str:
    content = "".join(
        f"{path}:{digest}\n" for path, digest in sorted(hashes.items())
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _target_file_bindings(
    project: Path,
    relative_paths: Sequence[str],
) -> dict[str, dict[str, Any]]:
    """Bind the exact current bytes or absence of every candidate target."""

    root = project.resolve()
    bindings: dict[str, dict[str, Any]] = {}
    for index, raw_path in enumerate(sorted(set(relative_paths))):
        try:
            relative = repository_relative_path(
                raw_path,
                f"candidate_target_paths[{index}]",
            )
        except ValueError as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_candidate_path_invalid",
                str(error),
            ) from error
        target = root.joinpath(*PurePosixPath(relative).parts)
        resolved = target.resolve(strict=False)
        if not resolved.is_relative_to(root) or target.is_symlink():
            raise ImplementationAlignmentPreparationError(
                "alignment_candidate_path_invalid",
                f"实现对齐候选路径必须是项目内普通文件：{relative}",
            )
        if target.exists() and not target.is_file():
            raise ImplementationAlignmentPreparationError(
                "alignment_candidate_path_invalid",
                f"实现对齐候选路径不是普通文件：{relative}",
            )
        content = target.read_bytes() if target.exists() else None
        bindings[relative] = {
            "exists": content is not None,
            "sha256": (
                hashlib.sha256(content).hexdigest()
                if content is not None
                else None
            ),
        }
    return bindings


def _target_location_bindings(locations: Mapping[str, str]) -> dict[str, dict[str, Any]]:
    result = {}
    for key, location in sorted(locations.items()):
        path = Path(location)
        result[key] = _target_file_bindings(path.parent, [path.name])[path.name]
    return result


def _ownership(
    project: Path,
    current: Mapping[str, Any],
    repository_readers: Mapping[str | None, GitProjectReader] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    records = current.get("records")
    scopes = current.get("governed_source_scopes")
    if not isinstance(records, list) or not isinstance(scopes, list):
        raise ValueError("受管源码归属底账结构无效")
    existing = {_source_key(item): item for item in records}
    if len(existing) != len(records):
        raise ValueError("受管源码归属底账存在重复路径，必须由 Agent（智能代理）纠正")
    hashes = _governed_hashes(project, scopes, repository_readers)
    missing_records = sorted(set(hashes) - set(existing))
    stale_records = sorted(set(existing) - set(hashes))
    if missing_records or stale_records:
        raise ValueError(
            "受管源码集合变化必须先由 Agent（智能代理）形成语义归属；"
            f"缺少={missing_records}，多余={stale_records}"
        )
    return (
        [
            {**existing[path], "sha256": hashes[path]}
            for path in sorted(hashes)
        ],
        hashes,
    )


def _source_key(record: Mapping[str, Any]) -> str:
    return repository_path_key(record.get("repository_id"), record["path"]) if "repository_id" in record else record["path"]


def _dependency_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(item["scope_id"]),
        str(item["provider_id"]),
        str(item["source_node_id"]),
        str(item["target_node_id"]),
        str(item["relation_kind"]),
        str(item["resolution_status"]),
        tuple(str(value) for value in item.get("conditions", [])),
    )


def _endpoint_module(
    relation: Mapping[str, Any],
    endpoint: str,
    owners: Mapping[str, Mapping[str, Any]],
) -> str | None:
    path = relation.get(f"{endpoint}_path")
    if not isinstance(path, str):
        return None
    exact = owners.get(path)
    if exact is not None:
        return str(exact["target_module_id"])
    if relation.get(f"{endpoint}_node_kind") != "package":
        return None
    root = PurePosixPath(path)
    direct_modules = {
        str(item["target_module_id"])
        for owned_path, item in owners.items()
        if PurePosixPath(owned_path).parent == root
    }
    if len(direct_modules) == 1:
        return next(iter(direct_modules))
    descendant_modules = {
        str(item["target_module_id"])
        for owned_path, item in owners.items()
        if root in PurePosixPath(owned_path).parents
    }
    if len(descendant_modules) == 1:
        return next(iter(descendant_modules))
    return None


def _default_dependency_rationale(classification: str) -> str:
    return {
        "external_observed": (
            "观察提供者将目标识别为项目外部依赖；该记录不伪造内部模块归属。"
        ),
        "internal_same_module": "两个实现节点属于同一目标模块。",
        "allowed_direct": "实际直接依赖符合目标架构声明的稳定关系。",
        "allowed_read_only": "实际依赖符合目标架构声明的只读投影关系。",
    }.get(classification, "观察关系按目标架构和端点归属确定性分类。")


def _dependencies(
    ownership: Sequence[Mapping[str, Any]],
    architecture: Mapping[str, Any],
    current: Mapping[str, Any],
    observation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    owners = {
        item["path"]: item
        for item in ownership
        if item["disposition"] == "owned"
    }
    relationships = {
        (item["from_module_id"], item["to_module_id"]): item
        for item in architecture["relationships"]
    }
    classification_for_mode = {
        "direct": "allowed_direct",
        "read_only_projection": "allowed_read_only",
        "through_module": "requires_mediator_but_direct",
        "forbidden": "forbidden",
    }
    current_records = current.get("records")
    if not isinstance(current_records, list):
        raise ValueError("实际实现关系底账结构无效")
    existing: dict[tuple[Any, ...], Mapping[str, Any]] = {}
    for item in current_records:
        if not item.get("source_node_id") or not item.get("target_node_id"):
            raise ValueError("实际实现关系必须使用当前节点身份合同")
        key = _dependency_key(item)
        if key in existing:
            raise ValueError(
                "实际实现关系底账存在重复节点边，必须由 Agent（智能代理）纠正"
            )
        existing[key] = item

    observed = normalized_observed_relations(observation)
    observed_keys = {_dependency_key(item) for item in observed}
    stale = [
        item
        for key, item in existing.items()
        if key not in observed_keys
    ]
    stale_with_semantics = [
        item
        for item in stale
        if item.get("deviation_ids")
        or item.get("classification")
        not in PASSING_REFRESH_CLASSIFICATIONS
    ]
    if stale_with_semantics:
        raise ValueError(
            "已消失的实现关系仍携带偏离或非通过分类，必须先由 Agent（智能代理）复核："
            + ", ".join(
                f"{item.get('source_path')} -> "
                f"{item.get('target_path') or item.get('target_external_name')}"
                for item in stale_with_semantics
            )
        )

    failures: list[str] = []
    records: list[dict[str, Any]] = []
    for item in sorted(observed, key=_dependency_key):
        if "repository_id" in item:
            owners = {record["path"]: record for record in ownership if record["disposition"] == "owned" and record.get("repository_id") == item["repository_id"]}
        key = _dependency_key(item)
        previous = existing.get(key)
        source_module = _endpoint_module(item, "source", owners)
        if source_module is None:
            failures.append(
                "实现关系来源节点没有唯一 owned 模块归属："
                f"{item['source_path'] or item['source_external_name']} -> "
                f"{item['target_path'] or item['target_external_name']}"
            )
            continue
        resolution = item["resolution_status"]
        target_module: str | None = None
        relationship = None
        if resolution == "external":
            classification = "external_observed"
        elif resolution == "unresolved":
            classification = "unresolved_observation"
        elif resolution == "ambiguous":
            classification = "ambiguous_observation"
        else:
            target_module = _endpoint_module(item, "target", owners)
            if target_module is None:
                failures.append(
                    "内部实现关系目标节点没有唯一 owned 模块归属："
                    f"{item['source_path'] or item['source_external_name']} -> "
                    f"{item['target_path'] or item['target_external_name']}"
                )
                continue
            if source_module == target_module:
                classification = "internal_same_module"
            else:
                relationship = relationships.get((source_module, target_module))
                classification = (
                    classification_for_mode[relationship["mode"]]
                    if relationship is not None
                    else "undeclared"
                )
        projection = {
            "source_module_id": source_module,
            "target_module_id": target_module,
            "classification": classification,
            "target_relationship_id": (
                relationship["relationship_id"]
                if relationship is not None
                else None
            ),
        }
        if previous is not None:
            changed = [
                field
                for field, value in projection.items()
                if previous.get(field) != value
            ]
            if changed:
                failures.append(
                    "实现关系的归属或架构分类变化，必须重新判断："
                    f"{item['source_path']} -> "
                    f"{item['target_path'] or item['target_external_name']} "
                    f"({','.join(changed)})"
                )
                continue
            deviation_ids = list(previous.get("deviation_ids", []))
            rationale = str(previous.get("rationale") or "").strip()
        else:
            deviation_ids = []
            rationale = _default_dependency_rationale(classification)
        if classification not in PASSING_REFRESH_CLASSIFICATIONS and not deviation_ids:
            failures.append(
                "非通过实现关系必须先由 Agent（智能代理）形成偏离处置："
                f"{classification}: "
                f"{item['source_path'] or item['source_external_name']} -> "
                f"{item['target_path'] or item['target_external_name']}"
            )
            continue
        records.append(
            {
                **item,
                **projection,
                "deviation_ids": deviation_ids,
                "rationale": rationale,
            }
        )
    if failures:
        raise ValueError("实际实现关系仍未收敛：\n" + "\n".join(failures))
    return records


def _responsibilities(
    architecture: Mapping[str, Any],
    current: Mapping[str, Any],
) -> list[dict[str, Any]]:
    expected = {
        *(str(item["module_id"]) for item in architecture["modules"]),
        *(
            str(item["relationship_id"])
            for item in architecture["relationships"]
        ),
        *(str(item["constraint_id"]) for item in architecture["constraints"]),
    }
    existing = {str(item["target_id"]): item for item in current["records"]}
    missing = sorted(expected - set(existing))
    extra = sorted(set(existing) - expected)
    if missing or extra:
        raise ValueError(
            "目标责任记录必须由 Agent（智能代理）按当前架构逐项形成；"
            f"缺少={missing}，多余={extra}"
        )
    return [existing[target_id] for target_id in sorted(expected)]


ALIGNMENT_PREPARATION_PACKET_SCHEMA = (
    "strixnova.implementation-alignment-preparation-packet.v1"
)
ALIGNMENT_PREPARATION_REQUEST_SCHEMA = (
    "strixnova.implementation-alignment-preparation-request.v1"
)
ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA = (
    "strixnova.implementation-alignment-candidate-decisions.v1"
)
ALIGNMENT_INSPECTION_RESULT_SCHEMA = (
    "strixnova.implementation-alignment-inspection-result.v1"
)
ALIGNMENT_INSPECTION_MAX_ITEMS = 200
PREVIOUS_RECORD_REF_SCHEMA = (
    "strixnova.implementation-alignment-previous-record-ref.v1"
)


class ImplementationAlignmentPreparationError(ValueError):
    """One preparation, capture, or candidate write was rejected safely."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ImplementationAlignmentPreparationError(
            "alignment_preparation_not_serializable",
            "实现对齐准备包包含不能稳定序列化的内容",
        ) from error


def _content_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _decision_ref(kind: str, value: Any) -> str:
    digest = _content_sha256({"kind": kind, "facts": value})
    return "ALIGNDECISION-" + digest[:16].upper()


class ImplementationAlignmentPreparation:
    """Deep Module for installed alignment preparation and candidate writes."""

    _ARTIFACT_ROOT = PurePosixPath(
        ".strixnova/artifacts/implementation-alignment"
    )

    @classmethod
    def _transaction_root(cls, implementation_root: Path) -> Path:
        return implementation_root.joinpath(
            *cls._ARTIFACT_ROOT.parts,
            "transactions",
        )

    @classmethod
    def _recover_transactions(cls, implementation_root: Path, allowed_targets: Sequence[Path] | None = None) -> None:
        try:
            recover_document_transactions(
                cls._transaction_root(implementation_root),
                implementation_root,
                allowed_targets=allowed_targets,
            )
        except DocumentTransactionError as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_transaction_recovery_failed",
                "上一次实现对齐写入没有完成且不能安全自动恢复",
                details=error.details or [str(error)],
            ) from error

    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        if not self.project.is_dir():
            raise ImplementationAlignmentPreparationError(
                "project_directory_missing",
                f"项目目录不存在：{self.project}",
            )

    @staticmethod
    def _work_item_plan(current: Mapping[str, Any]) -> Mapping[str, Any]:
        data = current.get("data")
        engineering = data.get("engineering") if isinstance(data, Mapping) else None
        plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
        confirmation = (
            engineering.get("plan_confirmation")
            if isinstance(engineering, Mapping)
            else None
        )
        if not isinstance(plan, Mapping) or not isinstance(confirmation, Mapping):
            raise ImplementationAlignmentPreparationError(
                "alignment_plan_missing",
                "实现对齐入口需要当前已确认工程方案",
            )
        if confirmation.get("accepted") is not True:
            raise ImplementationAlignmentPreparationError(
                "alignment_plan_not_confirmed",
                "实现对齐入口不能执行尚未由项目负责人接受的工程方案",
            )
        return plan

    @staticmethod
    def _operation_path(operation: Mapping[str, Any]) -> str:
        return str(
            operation.get("to_path")
            if operation.get("action") == "move"
            else operation.get("path")
            or ""
        ).replace("\\", "/").strip()

    def _binding(self, current: Mapping[str, Any]) -> dict[str, Any]:
        if current.get("status") != "implementing":
            raise ImplementationAlignmentPreparationError(
                "alignment_current_action_mismatch",
                "实现对齐入口只服务当前 implementing 实施切片",
                details={"status": current.get("status")},
            )
        work_item_id = str(current.get("work_item_id") or "").strip()
        version = current.get("version")
        if not work_item_id or type(version) is not int or version < 1:
            raise ImplementationAlignmentPreparationError(
                "alignment_work_item_invalid",
                "实现对齐入口缺少有效 WorkItem 身份和版本",
            )
        plan = self._work_item_plan(current)
        data = current.get("data")
        assert isinstance(data, Mapping)
        focused = focused_slice(
            plan,
            list(data.get("verifications") or []),
            list(data.get("implementation_slice_completions") or []),
        )
        if not isinstance(focused, Mapping):
            raise ImplementationAlignmentPreparationError(
                "alignment_slice_missing",
                "当前方案没有可执行的实现对齐切片",
            )
        references = list(
            dict.fromkeys(
                [
                    *(focused.get("operation_refs") or []),
                    *(focused.get("continued_operation_refs") or []),
                ]
            )
        )
        operations = list(plan.get("operations") or [])
        selected_operations: list[tuple[str, Mapping[str, Any]]] = []
        for reference in references:
            text = str(reference)
            index_text = (
                text[len("operations[") : -1]
                if text.startswith("operations[") and text.endswith("]")
                else ""
            )
            if not index_text.isdigit() or int(index_text) >= len(operations):
                raise ImplementationAlignmentPreparationError(
                    "alignment_operation_ref_invalid",
                    f"当前实施切片引用未知计划操作：{text}",
                )
            operation = operations[int(index_text)]
            if not isinstance(operation, Mapping):
                raise ImplementationAlignmentPreparationError(
                    "alignment_operation_invalid",
                    f"当前实施切片计划操作结构无效：{text}",
                )
            selected_operations.append((text, operation))
        alignment_roots = [
            (reference, operation)
            for reference, operation in selected_operations
            if isinstance(operation.get("long_lived_artifact"), Mapping)
            and operation["long_lived_artifact"].get("artifact_type")
            == "domain_alignment"
        ]
        if len(alignment_roots) != 1:
            raise ImplementationAlignmentPreparationError(
                "alignment_operation_not_current",
                "当前实施切片必须唯一拥有或延续实现对齐根操作",
                details={"candidate_count": len(alignment_roots)},
            )
        _alignment_ref, alignment_operation = alignment_roots[0]
        alignment_path = self._operation_path(alignment_operation)
        artifact = alignment_operation["long_lived_artifact"]
        git = data.get("git")
        worktree_path = (
            (git.get("repository") if git.get("conflict_resolution") else git.get("worktree_path")) if isinstance(git, Mapping) else None
        )
        implementation_root = (
            Path(str(worktree_path)).expanduser().resolve()
            if isinstance(worktree_path, str) and worktree_path.strip()
            else self.project
        )
        if not implementation_root.is_dir():
            raise ImplementationAlignmentPreparationError(
                "alignment_worktree_missing",
                f"实现工作树不存在：{implementation_root}",
            )
        allowed_paths = sorted(
            {
                path
                for _reference, operation in selected_operations
                for path in (
                    str(operation.get("path") or "").replace("\\", "/").strip(),
                    str(operation.get("to_path") or "").replace("\\", "/").strip(),
                )
                if path
            }
        )
        repository_roots = {}
        for entry in data.get("repository_deliveries") or []:
            area = entry.get("git") or {}
            root = area.get("repository") if area.get("conflict_resolution") or (area.get("integration") or {}).get("integrated_commit") else area.get("worktree_path")
            if root:
                repository_roots[entry["repository_id"]] = str(root)
        repository_roots.setdefault(alignment_operation.get("repository_id"), str(implementation_root))
        allowed_targets = sorted({str(Path(repository_roots.get(operation.get("repository_id"), str(implementation_root))) / path) for _reference, operation in selected_operations for path in (str(operation.get("path") or ""), str(operation.get("to_path") or "")) if path})
        return {
            "work_item_id": work_item_id,
            "repository_id": alignment_operation.get("repository_id"),
            "work_item_version": version,
            "plan_id": str(plan.get("plan_id") or ""),
            "plan_content_sha256": _content_sha256(plan),
            "slice_id": str(focused.get("slice_id") or ""),
            "alignment_model_id": str(artifact.get("artifact_id") or ""),
            "alignment_path": alignment_path,
            "allowed_paths": allowed_paths,
            "allowed_targets": allowed_targets,
            "implementation_root": str(implementation_root),
        }

    @staticmethod
    def _architecture(project: Path, model: Mapping[str, Any]) -> dict[str, Any]:
        paths = model.get("artifact_paths")
        if not isinstance(paths, Mapping):
            raise ImplementationAlignmentPreparationError(
                "target_architecture_invalid",
                "目标架构缺少从属产物路径",
            )
        try:
            return {
                "modules": _load(project / str(paths["modules"]))["modules"],
                "relationships": _load(project / str(paths["relationships"]))[
                    "relationships"
                ],
                "constraints": _load(project / str(paths["constraints"]))[
                    "constraints"
                ],
            }
        except (KeyError, OSError, ValueError) as error:
            raise ImplementationAlignmentPreparationError(
                "target_architecture_invalid",
                "目标架构从属产物不能用于实现对齐准备",
            ) from error

    @staticmethod
    def _initial_documents(
        request: Mapping[str, Any],
        *,
        binding: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "schema_version",
            "alignment_revision_id",
            "supersedes_revision_id",
            "observation_scopes",
            "governed_source_scopes",
            "artifact_paths",
        }
        if set(request) != required or request.get("schema_version") != (
            ALIGNMENT_PREPARATION_REQUEST_SCHEMA
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_request_invalid",
                "首次实现对齐准备请求字段或版本无效",
            )
        revision_id = str(request.get("alignment_revision_id") or "")
        supersedes_revision_id = request.get("supersedes_revision_id")
        if re.fullmatch(r"ALIGNREV-[0-9A-F]{16}", revision_id) is None or (
            supersedes_revision_id is not None
            and re.fullmatch(
                r"ALIGNREV-[0-9A-F]{16}",
                str(supersedes_revision_id),
            )
            is None
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_request_invalid",
                "实现对齐准备请求包含无效修订身份",
            )
        artifact_paths = request.get("artifact_paths")
        if not isinstance(artifact_paths, Mapping) or set(artifact_paths) != {
            "source_ownership",
            "actual_dependencies",
            "target_responsibilities",
            "deviations",
        }:
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_request_invalid",
                "首次实现对齐准备必须给出四份从属产物的精确路径",
            )
        return {
            "model": {
                "schema_version": "strixnova.project-implementation-alignment.v1",
                "alignment_model_id": binding["alignment_model_id"],
                "revision": {
                    "revision_id": revision_id,
                    "status": "draft",
                    "supersedes_revision_id": request.get(
                        "supersedes_revision_id"
                    ),
                    "confirmed_by_owner_id": None,
                    "confirmed_on": None,
                },
                "observation_scopes": deepcopy(
                    request.get("observation_scopes")
                ),
                "artifact_paths": {
                    str(key): str(value) for key, value in artifact_paths.items()
                },
                "unresolved_items": [],
            },
            "source": {
                "schema_version": "strixnova.implementation-source-ownership.v1",
                "alignment_model_id": binding["alignment_model_id"],
                "alignment_revision_id": str(
                    request.get("alignment_revision_id") or ""
                ),
                "governed_source_scopes": deepcopy(
                    request.get("governed_source_scopes")
                ),
                "records": [],
            },
            "dependencies": {
                "schema_version": "strixnova.implementation-actual-dependencies.v1",
                "alignment_model_id": binding["alignment_model_id"],
                "alignment_revision_id": str(
                    request.get("alignment_revision_id") or ""
                ),
                "observation_contract_version": IMPLEMENTATION_OBSERVATION_SCHEMA,
                "records": [],
            },
            "responsibilities": {
                "schema_version": "strixnova.implementation-target-responsibilities.v1",
                "alignment_model_id": binding["alignment_model_id"],
                "alignment_revision_id": str(
                    request.get("alignment_revision_id") or ""
                ),
                "records": [],
            },
            "deviations": {
                "schema_version": "strixnova.implementation-deviations.v1",
                "alignment_model_id": binding["alignment_model_id"],
                "alignment_revision_id": str(
                    request.get("alignment_revision_id") or ""
                ),
                "deviations": [],
            },
        }

    def _documents(
        self,
        binding: Mapping[str, Any],
        request: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        project = Path(str(binding["implementation_root"]))
        model_path = project / str(binding["alignment_path"])
        if model_path.is_file():
            model = _load(model_path)
            paths = model.get("artifact_paths")
            if not isinstance(paths, Mapping):
                raise ImplementationAlignmentPreparationError(
                    "alignment_candidate_invalid",
                    "现有实现对齐根文件缺少从属产物路径",
                )
            try:
                documents = {
                    "model": model,
                    "source": _load(project / str(paths["source_ownership"])),
                    "dependencies": _load(
                        project / str(paths["actual_dependencies"])
                    ),
                    "responsibilities": _load(
                        project / str(paths["target_responsibilities"])
                    ),
                    "deviations": _load(project / str(paths["deviations"])),
                }
            except (KeyError, OSError, ValueError) as error:
                raise ImplementationAlignmentPreparationError(
                    "alignment_candidate_invalid",
                    "现有实现对齐从属产物不完整或不可读",
                ) from error
            previous_revision = documents["model"].get("revision")
            if request is None:
                if (
                    isinstance(previous_revision, Mapping)
                    and previous_revision.get("status") == "draft"
                ):
                    return documents
                raise ImplementationAlignmentPreparationError(
                    "alignment_revision_request_required",
                    "现行实现对齐不是 draft；prepare 需要一个只含新修订身份的请求",
                )
            revision_fields = {
                "schema_version",
                "alignment_revision_id",
                "supersedes_revision_id",
            }
            scope_fields = {"observation_scopes", "governed_source_scopes"}
            if set(request) not in (revision_fields, revision_fields | scope_fields) or request.get("schema_version") != (
                ALIGNMENT_PREPARATION_REQUEST_SCHEMA
            ):
                raise ImplementationAlignmentPreparationError(
                    "alignment_preparation_request_invalid",
                    "现有实现对齐的新修订请求只能包含新修订身份和 supersedes",
                )
            requested_revision_id = str(
                request.get("alignment_revision_id") or ""
            )
            if (
                not isinstance(previous_revision, Mapping)
                or re.fullmatch(
                    r"ALIGNREV-[0-9A-F]{16}", requested_revision_id
                )
                is None
                or requested_revision_id
                == previous_revision.get("revision_id")
                or request.get("supersedes_revision_id")
                != previous_revision.get("revision_id")
            ):
                raise ImplementationAlignmentPreparationError(
                    "alignment_revision_lineage_invalid",
                    "现有实现对齐的新草稿必须使用新修订身份并精确 supersede 当前修订",
                )
            revision = {
                "revision_id": requested_revision_id,
                "status": "draft",
                "supersedes_revision_id": request["supersedes_revision_id"],
                "confirmed_by_owner_id": None,
                "confirmed_on": None,
            }
            documents["model"] = deepcopy(documents["model"])
            documents["model"]["revision"] = revision
            documents["model"]["unresolved_items"] = []
            if scope_fields <= set(request):
                documents["model"]["observation_scopes"] = deepcopy(request["observation_scopes"])
                documents["source"]["governed_source_scopes"] = deepcopy(request["governed_source_scopes"])
            for name in (
                "source",
                "dependencies",
                "responsibilities",
                "deviations",
            ):
                documents[name] = deepcopy(documents[name])
                documents[name]["alignment_revision_id"] = revision[
                    "revision_id"
                ]
            return documents
        if request is None:
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_request_required",
                "首次建立实现对齐时必须提供最小观察范围和四份从属产物路径",
            )
        return self._initial_documents(request, binding=binding)

    @staticmethod
    def _previous_record_key(
        ledger: str,
        record: Mapping[str, Any],
    ) -> Any:
        if ledger == "source":
            return {"path": str(record.get("path") or ""), **({"repository_id": record["repository_id"]} if "repository_id" in record else {})}
        if ledger == "dependencies":
            return {"dependency_key": _dependency_key(record)}
        if ledger == "responsibilities":
            return {"target_id": str(record.get("target_id") or "")}
        raise ImplementationAlignmentPreparationError(
            "alignment_preparation_invalid",
            f"实现对齐准备包引用未知旧记录底账：{ledger}",
        )

    @classmethod
    def _previous_record_ref(
        cls,
        ledger: str,
        record: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        if record is None:
            return None
        return {
            "schema_version": PREVIOUS_RECORD_REF_SCHEMA,
            "ledger": ledger,
            "record_key_sha256": _content_sha256(
                cls._previous_record_key(ledger, record)
            ),
            "content_sha256": _content_sha256(record),
        }

    @classmethod
    def _resolve_previous_record(
        cls,
        documents: Mapping[str, Any],
        reference: Any,
    ) -> dict[str, Any] | None:
        if reference is None:
            return None
        if not isinstance(reference, Mapping) or set(reference) != {
            "schema_version",
            "ledger",
            "record_key_sha256",
            "content_sha256",
        }:
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包旧记录引用结构无效",
            )
        ledger = str(reference.get("ledger") or "")
        key_digest = str(reference.get("record_key_sha256") or "")
        content_digest = str(reference.get("content_sha256") or "")
        if (
            reference.get("schema_version") != PREVIOUS_RECORD_REF_SCHEMA
            or ledger not in {"source", "dependencies", "responsibilities"}
            or any(
                len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
                for digest in (key_digest, content_digest)
            )
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包旧记录引用身份无效",
            )
        container = documents.get(ledger)
        records = container.get("records") if isinstance(container, Mapping) else None
        if not isinstance(records, list):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                f"实现对齐准备包缺少 {ledger} 旧记录底账",
            )
        matches = [
            record
            for record in records
            if isinstance(record, Mapping)
            and _content_sha256(cls._previous_record_key(ledger, record))
            == key_digest
        ]
        if len(matches) != 1 or _content_sha256(matches[0]) != content_digest:
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                f"实现对齐准备包 {ledger} 旧记录引用不能唯一还原",
            )
        return deepcopy(dict(matches[0]))

    @classmethod
    def _expanded_decision_catalog(
        cls,
        documents: Mapping[str, Any],
        catalog: Any,
    ) -> list[dict[str, Any]]:
        if not isinstance(catalog, list) or any(
            not isinstance(item, Mapping) for item in catalog
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包缺少决定目录",
            )
        expanded: list[dict[str, Any]] = []
        for raw in catalog:
            item = deepcopy(dict(raw))
            facts = item.get("facts")
            if not isinstance(facts, Mapping) or "previous_record_ref" not in facts:
                raise ImplementationAlignmentPreparationError(
                    "alignment_preparation_invalid",
                    "实现对齐准备包决定缺少冻结旧记录引用",
                )
            expanded_facts = deepcopy(dict(facts))
            reference = expanded_facts.pop("previous_record_ref")
            expanded_facts["previous"] = cls._resolve_previous_record(
                documents,
                reference,
            )
            item["facts"] = expanded_facts
            expanded.append(item)
        return expanded

    @classmethod
    def _required_decisions(
        cls,
        documents: Mapping[str, Any],
        observation: Mapping[str, Any],
        hashes: Mapping[str, str],
        architecture: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        required: list[dict[str, Any]] = []
        source = documents["source"]
        existing_sources = {
            _source_key(item): item
            for item in source.get("records") or []
            if isinstance(item, Mapping)
        }
        scopes = list(source.get("governed_source_scopes") or [])
        for path, digest in sorted(hashes.items()):
            scope = _unique_governed_scope(
                [item for item in scopes if isinstance(item, Mapping)],
                path,
            )
            scope_id = str(scope.get("scope_id") or "")
            if not scope_id:
                raise ValueError(f"受管源码作用域缺少 scope_id：{path}")
            existing = existing_sources.get(path)
            facts = {
                "scope_id": scope_id,
                "path": split_repository_path_key(path)[1] if "repository_id" in scope else path,
                **({"repository_id": scope["repository_id"]} if "repository_id" in scope else {}),
                "sha256": digest,
                "previous_record_ref": cls._previous_record_ref(
                    "source",
                    existing if isinstance(existing, Mapping) else None,
                ),
            }
            required.append(
                {
                    "decision_ref": _decision_ref("source", facts),
                    "kind": "source_record",
                    "required": existing is None,
                    "facts": facts,
                    "required_value_fields": [
                        "language_id",
                        "node_kind",
                        "disposition",
                        "target_module_id",
                        "implementation_stage_id",
                        "current_status",
                        "deviation_ids",
                        "rationale",
                    ],
                }
            )
        for path, existing in sorted(existing_sources.items()):
            if path in hashes:
                continue
            facts = {
                "path": str(existing["path"]),
                **({"repository_id": existing["repository_id"]} if "repository_id" in existing else {}),
                "previous_record_ref": cls._previous_record_ref(
                    "source",
                    existing,
                ),
            }
            required.append(
                {
                    "decision_ref": _decision_ref("remove-source", facts),
                    "kind": "remove_source_record",
                    "required": True,
                    "facts": facts,
                    "required_value_fields": ["accepted", "rationale"],
                }
            )

        observed = normalized_observed_relations(observation)
        existing_dependencies = {
            _dependency_key(item): item
            for item in documents["dependencies"].get("records") or []
            if isinstance(item, Mapping)
            and "source_node_id" in item
            and "target_node_id" in item
        }
        observed_keys = {_dependency_key(item) for item in observed}
        for relation in sorted(observed, key=_dependency_key):
            key = _dependency_key(relation)
            existing = existing_dependencies.get(key)
            facts = {
                **deepcopy(dict(relation)),
                "previous_record_ref": cls._previous_record_ref(
                    "dependencies",
                    existing if isinstance(existing, Mapping) else None,
                ),
            }
            required.append(
                {
                    "decision_ref": _decision_ref("dependency", facts),
                    "kind": "dependency_record",
                    "required": existing is None,
                    "facts": facts,
                    "required_value_fields": [
                        "source_module_id",
                        "target_module_id",
                        "classification",
                        "target_relationship_id",
                        "deviation_ids",
                        "rationale",
                    ],
                }
            )
        for key, existing in sorted(
            existing_dependencies.items(), key=lambda item: item[0]
        ):
            if key in observed_keys:
                continue
            facts = {
                "previous_record_ref": cls._previous_record_ref(
                    "dependencies",
                    existing,
                )
            }
            required.append(
                {
                    "decision_ref": _decision_ref(
                        "remove-dependency", facts
                    ),
                    "kind": "remove_dependency_record",
                    "required": True,
                    "facts": facts,
                    "required_value_fields": ["accepted", "rationale"],
                }
            )

        expected_targets = {
            *(str(item["module_id"]) for item in architecture["modules"]),
            *(
                str(item["relationship_id"])
                for item in architecture["relationships"]
            ),
            *(str(item["constraint_id"]) for item in architecture["constraints"]),
        }
        existing_responsibilities = {
            str(item.get("target_id") or ""): item
            for item in documents["responsibilities"].get("records") or []
            if isinstance(item, Mapping)
        }
        for target_id in sorted(expected_targets):
            existing = existing_responsibilities.get(target_id)
            facts = {
                "target_id": target_id,
                "previous_record_ref": cls._previous_record_ref(
                    "responsibilities",
                    existing if isinstance(existing, Mapping) else None,
                ),
            }
            required.append(
                {
                    "decision_ref": _decision_ref("responsibility", facts),
                    "kind": "responsibility_record",
                    "required": existing is None,
                    "facts": facts,
                    "required_value_fields": [
                        "target_kind",
                        "status",
                        "satisfied",
                        "missing",
                        "evidence",
                        "deviation_ids",
                        "resolution_plan",
                    ],
                }
            )
        for target_id in sorted(set(existing_responsibilities) - expected_targets):
            facts = {
                "target_id": target_id,
                "previous_record_ref": cls._previous_record_ref(
                    "responsibilities",
                    existing_responsibilities[target_id],
                ),
            }
            required.append(
                {
                    "decision_ref": _decision_ref(
                        "remove-responsibility", facts
                    ),
                    "kind": "remove_responsibility_record",
                    "required": True,
                    "facts": facts,
                    "required_value_fields": ["accepted", "rationale"],
                }
            )
        return required

    def _store_json(self, kind: str, value: Mapping[str, Any]) -> dict[str, str]:
        try:
            return ImplementationAlignmentArtifactStore(
                self.project
            ).store_packet(kind, value)
        except AlignmentArtifactError as error:
            raise ImplementationAlignmentPreparationError(
                error.code,
                str(error),
                details=error.details,
            ) from error

    def _load_preparation(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        try:
            return ImplementationAlignmentArtifactStore(
                self.project
            ).load_packet(
                reference,
                expected_kind="preparations",
                expected_schema=ALIGNMENT_PREPARATION_PACKET_SCHEMA,
            )
        except AlignmentArtifactError as error:
            raise ImplementationAlignmentPreparationError(
                error.code,
                str(error),
                details=error.details,
            ) from error

    @classmethod
    def _inspection_items(
        cls,
        packet: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        """Project one preparation into a storage-independent review stream."""

        raw_decisions = packet.get("decision_catalog")
        documents = packet.get("documents")
        architecture = packet.get("architecture")
        observation = packet.get("observation")
        if (
            not isinstance(raw_decisions, list)
            or any(not isinstance(item, Mapping) for item in raw_decisions)
            or not isinstance(documents, Mapping)
            or not isinstance(architecture, Mapping)
            or not isinstance(observation, Mapping)
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包缺少可检查的逻辑事实",
            )
        decisions = cls._expanded_decision_catalog(documents, raw_decisions)

        def item(record_kind: str, value: Any) -> dict[str, Any]:
            return {
                "record_kind": record_kind,
                "value": deepcopy(value),
            }

        binding = packet.get("binding")
        if not isinstance(binding, Mapping):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包缺少工作绑定",
            )
        summary_binding_fields = (
            "work_item_id",
            "work_item_version",
            "plan_id",
            "plan_content_sha256",
            "slice_id",
            "alignment_model_id",
            "alignment_path",
        )
        values: list[dict[str, Any]] = [
            item(
                "preparation_summary",
                {
                    "binding": {
                        field: deepcopy(binding[field])
                        for field in summary_binding_fields
                        if field in binding
                    },
                    "observed_on": packet.get("observed_on"),
                    "observation_coverage_status": observation.get(
                        "overall_coverage_status"
                    ),
                    "required_decision_count": sum(
                        entry.get("required") is True for entry in decisions
                    ),
                    "optional_decision_count": sum(
                        entry.get("required") is False for entry in decisions
                    ),
                    "external_provider_plan_ids": deepcopy(
                        packet.get("external_provider_plan_ids") or []
                    ),
                    "capture_ref": deepcopy(packet.get("capture_ref")),
                    "semantic_content_machine_proven": False,
                },
            )
        ]

        baseline = packet.get("baseline")
        if isinstance(baseline, Mapping):
            baseline_fields = (
                "schema_version",
                "baseline_id",
                "project",
                "authority_refs",
                "current_architecture_stage_id",
                "code_version",
                "review_state",
            )
            values.append(
                item(
                    "engineering_baseline_context",
                    {
                        field: deepcopy(baseline[field])
                        for field in baseline_fields
                        if field in baseline
                    },
                )
            )
        for record_kind, field in (
            ("domain_model_context", "domain_model"),
            ("architecture_model_context", "architecture_model"),
        ):
            value = packet.get(field)
            if isinstance(value, Mapping):
                values.append(item(record_kind, value))

        for record_kind, field in (
            ("architecture_module", "modules"),
            ("architecture_relationship", "relationships"),
            ("architecture_constraint", "constraints"),
        ):
            for value in architecture.get(field) or []:
                if isinstance(value, Mapping):
                    values.append(item(record_kind, value))

        model = documents.get("model")
        if isinstance(model, Mapping):
            model_fields = (
                "schema_version",
                "alignment_model_id",
                "revision",
                "domain_model_ref",
                "architecture_ref",
                "code_snapshot",
                "observation_scopes",
                "artifact_paths",
                "unresolved_items",
            )
            values.append(
                item(
                    "existing_alignment_context",
                    {
                        field: deepcopy(model[field])
                        for field in model_fields
                        if field in model
                    },
                )
            )
        source = documents.get("source")
        if isinstance(source, Mapping):
            for value in source.get("governed_source_scopes") or []:
                if isinstance(value, Mapping):
                    values.append(item("governed_source_scope", value))
        deviations = documents.get("deviations")
        if isinstance(deviations, Mapping):
            for value in deviations.get("deviations") or []:
                if isinstance(value, Mapping):
                    values.append(item("existing_deviation", value))

        for value in observation.get("coverage") or []:
            if isinstance(value, Mapping):
                values.append(item("observation_coverage", value))
        for value in observation.get("provider_receipts") or []:
            if isinstance(value, Mapping):
                values.append(item("observation_provider_receipt", value))
        values.extend(item("semantic_decision", value) for value in decisions)
        return values

    @staticmethod
    def _inspection_cursor(content_sha256: str, offset: int) -> str:
        signature = hashlib.sha256(
            (
                "strixnova:implementation-alignment-inspection:v1:"
                f"{content_sha256}:{offset}"
            ).encode("utf-8")
        ).hexdigest()[:16].upper()
        return f"ALIGNCURSOR-{offset}-{signature}"

    @classmethod
    def _inspection_offset(
        cls,
        content_sha256: str,
        cursor: str | None,
    ) -> int:
        if cursor is None:
            return 0
        matched = re.fullmatch(r"ALIGNCURSOR-([0-9]+)-([0-9A-F]{16})", cursor)
        if matched is None:
            raise ImplementationAlignmentPreparationError(
                "alignment_inspection_cursor_invalid",
                "实现对齐检查游标无效",
            )
        offset = int(matched.group(1))
        if cls._inspection_cursor(content_sha256, offset) != cursor:
            raise ImplementationAlignmentPreparationError(
                "alignment_inspection_cursor_invalid",
                "实现对齐检查游标不属于当前准备包",
            )
        return offset

    def inspect(
        self,
        current: Mapping[str, Any],
        preparation_ref: Mapping[str, Any],
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return a bounded logical review page without exposing artifact layout."""

        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or limit < 1
            or limit > ALIGNMENT_INSPECTION_MAX_ITEMS
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_inspection_limit_invalid",
                "实现对齐检查每页条目数必须在 1 到 200 之间",
            )
        binding = self._binding(current)
        packet = self._load_preparation(preparation_ref)
        self._assert_current_binding(packet, binding)
        content_sha256 = str(preparation_ref.get("content_sha256") or "")
        offset = self._inspection_offset(content_sha256, cursor)
        items = self._inspection_items(packet)
        if offset > len(items):
            raise ImplementationAlignmentPreparationError(
                "alignment_inspection_cursor_invalid",
                "实现对齐检查游标超过当前逻辑记录范围",
            )
        page = items[offset : offset + limit]
        next_offset = offset + len(page)
        next_cursor = (
            self._inspection_cursor(content_sha256, next_offset)
            if next_offset < len(items)
            else None
        )
        return {
            "schema_version": ALIGNMENT_INSPECTION_RESULT_SCHEMA,
            "preparation_ref": deepcopy(dict(preparation_ref)),
            "item_count": len(items),
            "returned_count": len(page),
            "items": page,
            "next_cursor": next_cursor,
            "semantic_content_machine_proven": False,
        }

    def garbage_collect_artifacts(
        self,
        *,
        apply: bool,
        expected_orphan_set_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Maintain only unreachable cache components; never remove authorities."""

        try:
            return ImplementationAlignmentArtifactStore(
                self.project
            ).garbage_collect_orphan_components(
                apply=apply,
                expected_orphan_set_sha256=expected_orphan_set_sha256,
            )
        except AlignmentArtifactError as error:
            raise ImplementationAlignmentPreparationError(
                error.code,
                str(error),
                details=error.details,
            ) from error

    @staticmethod
    def _assert_current_binding(
        packet: Mapping[str, Any],
        binding: Mapping[str, Any],
    ) -> None:
        recorded = packet.get("binding")
        if not isinstance(recorded, Mapping) or any(
            recorded.get(field) != binding.get(field)
            for field in (
                "work_item_id",
                "work_item_version",
                "plan_id",
                "plan_content_sha256",
                "slice_id",
                "alignment_model_id",
                "alignment_path",
                "allowed_paths",
                "implementation_root",
            )
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_stale",
                "WorkItem、工程方案、实施切片或工作树已变化；请重新 prepare",
            )

    @staticmethod
    def _assert_target_file_bindings(
        packet: Mapping[str, Any],
        project: Path,
    ) -> None:
        recorded = packet.get("target_file_bindings")
        if not isinstance(recorded, Mapping) or any(
            not isinstance(value, Mapping) for value in recorded.values()
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包缺少六文件内容绑定",
            )
        current = _target_location_bindings(packet["target_file_locations"]) if "target_file_locations" in packet else _target_file_bindings(project, list(recorded))
        if current != recorded:
            changed = sorted(
                path
                for path in set(recorded) | set(current)
                if recorded.get(path) != current.get(path)
            )
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_stale",
                "实现对齐候选目标文件在 prepare 后已变化；不会覆盖后续编辑",
                details=changed,
            )

    @staticmethod
    def _repository_inputs(current: Mapping[str, Any], baseline_reader: ProjectEngineeringBaseline) -> dict[str | None, GitProjectReader]:
        context = baseline_reader.context
        if context is None:
            return {baseline_reader.reader.repository_id: baseline_reader.reader}
        plan = current["data"]["engineering"]["plan"]
        selected_refs = {entry["repository_id"]: entry for entry in (plan.get("repository_scope") or {}).get("repositories", [])}
        readers = {}
        for repository in context.repositories:
            if repository.scope is None or repository.availability != "available":
                continue
            selection = selected_refs.get(repository.repository_id, {})
            version = selection.get("investigation_ref") if selection.get("role") == "read" else (context.content_versions or {}).get(repository.repository_id)
            readers[repository.repository_id] = GitProjectReader.for_repository(repository.scope, observed_ref=version)
        return readers

    @staticmethod
    def _qualify_documents(documents: Mapping[str, Any], default_repository: str | None) -> dict[str, Any]:
        qualified = deepcopy(dict(documents))
        for records in (qualified["model"]["observation_scopes"], qualified["source"]["governed_source_scopes"], qualified["source"]["records"], qualified["dependencies"]["records"]):
            for record in records:
                record.setdefault("repository_id", default_repository)
        return qualified

    def prepare(
        self,
        current: Mapping[str, Any],
        request: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        binding = self._binding(current)
        implementation_root = Path(str(binding["implementation_root"]))
        self._recover_transactions(implementation_root, [Path(path) for path in binding["allowed_targets"]])
        documents = self._documents(binding, request)
        model = documents["model"]
        if model.get("alignment_model_id") != binding["alignment_model_id"]:
            raise ImplementationAlignmentPreparationError(
                "alignment_identity_mismatch",
                "实现对齐根文件身份与已确认工程方案不一致",
            )
        artifact_paths = model.get("artifact_paths")
        if not isinstance(artifact_paths, Mapping):
            raise ImplementationAlignmentPreparationError(
                "alignment_candidate_invalid",
                "实现对齐根文件缺少从属产物路径",
            )
        try:
            baseline_reader = ProjectEngineeringBaseline(implementation_root)
            baseline = baseline_reader.load(required=True, allow_candidate_refs=True)
            assert baseline is not None
            baseline_path = baseline_reader.locate().relative_to(baseline_reader.project).as_posix()
            baseline_root = baseline_reader.project
        except ProjectEngineeringBaselineError as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_baseline_invalid",
                "实现对齐准备需要可读的项目工程基线",
                details=error.issues,
            ) from error
        locations = {repository_path_key(binding.get("repository_id"), str(path)): str(implementation_root / str(path)) for path in [binding["alignment_path"], *artifact_paths.values()]}
        locations[repository_path_key(baseline_reader.reader.repository_id, baseline_path)] = str(baseline_root / baseline_path)
        unplanned = sorted(set(locations.values()) - set(binding["allowed_targets"]))
        if unplanned:
            raise ImplementationAlignmentPreparationError(
                "alignment_candidate_paths_unplanned",
                "当前实施切片没有覆盖实现对齐候选的全部恢复性写入路径",
                details=unplanned,
            )
        target_file_bindings = _target_location_bindings(locations)
        alignment_ref = baseline["authority_refs"]["implementation_alignment"]
        if (
            alignment_ref.get("path") != binding["alignment_path"]
            or alignment_ref.get("alignment_model_id")
            != binding["alignment_model_id"]
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_baseline_binding_mismatch",
                "项目工程基线没有绑定工程方案中的同一实现对齐",
            )
        domain_ref = baseline["authority_refs"]["domain_model"]
        architecture_ref = baseline["authority_refs"]["target_architecture"]
        context = baseline_reader.context
        domain_source = context.authority_reader(domain_ref, parent_reader=baseline_reader.reader) if context is not None else baseline_reader.reader
        architecture_source = context.authority_reader(architecture_ref, parent_reader=baseline_reader.reader) if context is not None else baseline_reader.reader
        domain_model = domain_source.load_yaml(str(domain_ref["path"]), "Domain authority for observation")
        architecture_model = architecture_source.load_yaml(str(architecture_ref["path"]), "Architecture authority for observation")
        architecture = ProjectArchitectureDescription(architecture_source.project, str(architecture_ref["path"]), shared_reader=architecture_source).load()
        documents = self._qualify_documents(documents, alignment_ref.get("repository_id"))
        model = documents["model"]
        repository_readers = self._repository_inputs(current, baseline_reader)
        source = documents["source"]
        try:
            hashes = _governed_hashes(
                implementation_root,
                list(source.get("governed_source_scopes") or []),
                repository_readers,
            )
        except ValueError as error:
            code = (
                "alignment_governed_scope_ambiguous"
                if "必须且只能属于一个" in str(error)
                else "alignment_governed_scope_invalid"
            )
            raise ImplementationAlignmentPreparationError(
                code,
                str(error),
            ) from error
        plan = self._work_item_plan(current)
        provider_plans = plan.get("external_observation_provider_plans") or []
        try:
            observation = observe_project_implementation(repository_readers, list(model.get("observation_scopes") or []), external_providers=external_observation_providers_from_plans(provider_plans), external_execution_authorized=False)
        except Exception as error:
            if isinstance(error, ImplementationAlignmentPreparationError):
                raise
            raise ImplementationAlignmentPreparationError(
                "alignment_observation_failed",
                "实现观察准备失败",
                details=getattr(error, "issues", [str(error)]),
            ) from error
        packet = {
            "schema_version": ALIGNMENT_PREPARATION_PACKET_SCHEMA,
            "binding": binding,
            "observed_on": date.today().isoformat(),
            "baseline_path": baseline_path,
            "baseline_root": str(baseline_root),
            "target_file_locations": locations,
            "target_file_bindings": target_file_bindings,
            "baseline": deepcopy(baseline),
            "domain_model": deepcopy(domain_model),
            "architecture_model": deepcopy(architecture_model),
            "architecture": deepcopy(architecture),
            "documents": deepcopy(documents),
            "governed_hashes": hashes,
            "repository_content_refs": [{"repository_id": identifier, "base_commit": reader.observed_commit or reader.resolve_commit("HEAD"), "worktree_state": "clean" if reader.observed_commit is not None else "dirty" if reader.worktree_dirty() else "clean"} for identifier, reader in sorted(repository_readers.items(), key=lambda item: str(item[0])) if identifier in {scope["repository_id"] for scope in model["observation_scopes"]}],
            "observation": observation,
            "external_provider_plan_ids": [
                str(item.get("provider_plan_id") or "")
                for item in plan.get("external_observation_provider_plans") or []
                if isinstance(item, Mapping)
            ],
            "capture_ref": None,
            "semantic_content_machine_proven": False,
        }
        packet["decision_catalog"] = self._required_decisions(
            documents,
            observation,
            hashes,
            architecture,
        )
        reference = self._store_json("preparations", packet)
        coverage = str(observation["overall_coverage_status"])
        return {
            "schema_version": "strixnova.implementation-alignment-prepare-result.v1",
            "preparation_ref": reference,
            "required_decision_count": sum(
                item.get("required") is True
                for item in packet["decision_catalog"]
            ),
            "optional_decision_count": sum(
                item.get("required") is False
                for item in packet["decision_catalog"]
            ),
            "observation_coverage_status": coverage,
            "external_capture_available": bool(provider_plans),
            "external_capture_required": bool(provider_plans)
            and coverage != "complete",
            "draft_candidate_write_available": True,
            "semantic_content_machine_proven": False,
        }

    def capture_external(
        self,
        current: Mapping[str, Any],
        preparation_ref: Mapping[str, Any],
        *,
        authorize_external: bool,
    ) -> dict[str, Any]:
        if authorize_external is not True:
            raise ImplementationAlignmentPreparationError(
                "external_observation_not_authorized",
                "执行外部观察必须为本次调用显式提供 --authorize-external",
            )
        binding = self._binding(current)
        implementation_root = Path(str(binding["implementation_root"]))
        self._recover_transactions(implementation_root, [Path(path) for path in binding["allowed_targets"]])
        packet = self._load_preparation(preparation_ref)
        self._assert_current_binding(packet, binding)
        self._assert_target_file_bindings(
            packet,
            implementation_root,
        )
        plan = self._work_item_plan(current)
        provider_plans = plan.get("external_observation_provider_plans") or []
        if not provider_plans:
            raise ImplementationAlignmentPreparationError(
                "external_observation_not_planned",
                "当前已确认工程方案没有外部观察 provider 计划",
            )
        try:
            observation = observe_project_implementation(
                self._repository_inputs(current, ProjectEngineeringBaseline(implementation_root)),
                list(packet["documents"]["model"]["observation_scopes"]),
                external_providers=external_observation_providers_from_plans(provider_plans),
                external_execution_authorized=True,
            )
        except Exception as error:
            raise ImplementationAlignmentPreparationError(
                "external_observation_failed",
                "外部观察没有形成可验证结果",
                details=getattr(error, "issues", [str(error)]),
            ) from error
        capture = {
            "schema_version": "strixnova.implementation-alignment-capture.v1",
            "binding": binding,
            "observation": observation,
            "provider_plan_ids": list(packet["external_provider_plan_ids"]),
            "semantic_content_machine_proven": False,
        }
        capture_ref = self._store_json("captures", capture)
        updated_packet = deepcopy(packet)
        updated_packet["observation"] = observation
        updated_packet["capture_ref"] = capture_ref
        updated_packet["decision_catalog"] = self._required_decisions(
            updated_packet["documents"],
            observation,
            updated_packet["governed_hashes"],
            updated_packet["architecture"],
        )
        updated_ref = self._store_json("preparations", updated_packet)
        return {
            "schema_version": "strixnova.implementation-alignment-capture-result.v1",
            "preparation_ref": updated_ref,
            "capture_ref": capture_ref,
            "required_decision_count": sum(
                item.get("required") is True
                for item in updated_packet["decision_catalog"]
            ),
            "optional_decision_count": sum(
                item.get("required") is False
                for item in updated_packet["decision_catalog"]
            ),
            "observation_coverage_status": observation[
                "overall_coverage_status"
            ],
            "draft_candidate_write_available": True,
            "semantic_content_machine_proven": False,
        }

    @staticmethod
    def _decision_values(
        catalog: Sequence[Mapping[str, Any]],
        payload: Mapping[str, Any],
    ) -> tuple[dict[str, Mapping[str, Any]], dict[str, Mapping[str, Any]]]:
        if payload.get("schema_version") != ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA:
            raise ImplementationAlignmentPreparationError(
                "alignment_decisions_invalid",
                "实现对齐候选决定必须使用公开第一版合同",
            )
        raw_decisions = payload.get("decisions")
        if not isinstance(raw_decisions, list):
            raise ImplementationAlignmentPreparationError(
                "alignment_decisions_invalid",
                "实现对齐候选 decisions 必须是数组",
            )
        catalog_by_ref = {
            str(item.get("decision_ref") or ""): item for item in catalog
        }
        if len(catalog_by_ref) != len(catalog):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包决定引用重复",
            )
        decisions: dict[str, Mapping[str, Any]] = {}
        for index, raw in enumerate(raw_decisions):
            if not isinstance(raw, Mapping) or set(raw) != {
                "decision_ref",
                "value",
            }:
                raise ImplementationAlignmentPreparationError(
                    "alignment_decisions_invalid",
                    f"decisions[{index}] 字段不完整或包含未知字段",
                )
            reference = str(raw.get("decision_ref") or "")
            value = raw.get("value")
            if reference not in catalog_by_ref:
                raise ImplementationAlignmentPreparationError(
                    "alignment_decision_ref_unknown",
                    f"实现对齐候选引用了准备包中不存在的决定：{reference}",
                )
            if reference in decisions:
                raise ImplementationAlignmentPreparationError(
                    "alignment_decision_ref_duplicate",
                    f"实现对齐候选决定重复：{reference}",
                )
            if not isinstance(value, Mapping):
                raise ImplementationAlignmentPreparationError(
                    "alignment_decisions_invalid",
                    f"决定 {reference} 的 value 必须是对象",
                )
            expected_fields = set(
                catalog_by_ref[reference].get("required_value_fields") or []
            )
            if set(value) != expected_fields:
                raise ImplementationAlignmentPreparationError(
                    "alignment_decision_fields_invalid",
                    f"决定 {reference} 的字段必须精确匹配准备包合同",
                    details={
                        "expected": sorted(expected_fields),
                        "actual": sorted(str(key) for key in value),
                    },
                )
            decisions[reference] = value
        missing = sorted(
            reference
            for reference, item in catalog_by_ref.items()
            if item.get("required") is True and reference not in decisions
        )
        if missing:
            raise ImplementationAlignmentPreparationError(
                "alignment_decisions_incomplete",
                "实现对齐候选缺少准备包要求的语义决定",
                details=missing,
            )
        for reference, item in catalog_by_ref.items():
            if not str(item.get("kind") or "").startswith("remove_"):
                continue
            value = decisions.get(reference)
            if value is not None and (
                value.get("accepted") is not True
                or not isinstance(value.get("rationale"), str)
                or not str(value["rationale"]).strip()
            ):
                raise ImplementationAlignmentPreparationError(
                    "alignment_removal_not_acknowledged",
                    f"移除语义记录必须由 Agent 明确接受并说明理由：{reference}",
                )
        return decisions, catalog_by_ref

    @staticmethod
    def _persistable(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            str(key): deepcopy(item)
            for key, item in value.items()
            if not str(key).startswith("_")
            and key != "semantic_content_machine_proven"
        }

    def write_candidate(
        self,
        current: Mapping[str, Any],
        payload: Mapping[str, Any],
        *,
        current_binding_check: Callable[[], Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping) or set(payload) != {
            "schema_version",
            "preparation_ref",
            "decisions",
            "deviations",
            "unresolved_items",
        }:
            raise ImplementationAlignmentPreparationError(
                "alignment_decisions_invalid",
                "实现对齐候选输入字段不完整或包含未知字段",
            )
        binding = self._binding(current)
        implementation_root = Path(str(binding["implementation_root"]))
        self._recover_transactions(implementation_root, [Path(path) for path in binding["allowed_targets"]])
        preparation_ref = payload.get("preparation_ref")
        if not isinstance(preparation_ref, Mapping):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_ref_invalid",
                "实现对齐候选缺少准备引用",
            )
        packet = self._load_preparation(preparation_ref)
        self._assert_current_binding(packet, binding)
        self._assert_target_file_bindings(
            packet,
            implementation_root,
        )
        documents = packet.get("documents")
        if not isinstance(documents, Mapping):
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_invalid",
                "实现对齐准备包缺少现有底账",
            )
        catalog = self._expanded_decision_catalog(
            documents,
            packet.get("decision_catalog"),
        )
        decisions, catalog_by_ref = self._decision_values(catalog, payload)
        raw_deviations = payload.get("deviations")
        unresolved_items = payload.get("unresolved_items")
        if not isinstance(raw_deviations, list) or not isinstance(
            unresolved_items, list
        ):
            raise ImplementationAlignmentPreparationError(
                "alignment_decisions_invalid",
                "deviations 和 unresolved_items 必须是数组",
            )

        project = implementation_root
        hashes = {
            str(path): str(digest)
            for path, digest in packet["governed_hashes"].items()
        }
        observation = packet["observation"]
        architecture = packet["architecture"]

        source_records: list[dict[str, Any]] = []
        for reference, item in catalog_by_ref.items():
            if item.get("kind") != "source_record":
                continue
            facts = item["facts"]
            value = decisions.get(reference)
            previous = facts.get("previous")
            semantic = value if value is not None else previous
            if not isinstance(semantic, Mapping):
                raise ImplementationAlignmentPreparationError(
                    "alignment_decisions_incomplete",
                    f"源码记录缺少语义决定：{reference}",
                )
            source_records.append(
                {
                    "scope_id": str(facts["scope_id"]),
                    "path": str(facts["path"]),
                    "sha256": str(facts["sha256"]),
                    "repository_id": facts["repository_id"],
                    **{
                        field: deepcopy(semantic.get(field))
                        for field in item["required_value_fields"]
                    },
                }
            )
        source_current = {
            "governed_source_scopes": deepcopy(
                documents["source"]["governed_source_scopes"]
            ),
            "records": source_records,
        }
        try:
            repository_readers = self._repository_inputs(current, ProjectEngineeringBaseline(project))
            source_records, governed_hashes = _ownership(project, source_current, repository_readers)
        except ValueError as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_source_decisions_invalid",
                str(error),
            ) from error
        if governed_hashes != hashes:
            raise ImplementationAlignmentPreparationError(
                "alignment_preparation_stale",
                "受管源码字节或文件集合已变化；请重新 prepare",
            )

        dependency_records: list[dict[str, Any]] = []
        for reference, item in catalog_by_ref.items():
            if item.get("kind") != "dependency_record":
                continue
            facts = item["facts"]
            value = decisions.get(reference)
            previous = facts.get("previous")
            semantic = value if value is not None else previous
            if not isinstance(semantic, Mapping):
                raise ImplementationAlignmentPreparationError(
                    "alignment_decisions_incomplete",
                    f"依赖记录缺少语义决定：{reference}",
                )
            dependency_records.append(
                {
                    **{
                        str(key): deepcopy(value)
                        for key, value in facts.items()
                        if key != "previous"
                    },
                    **{
                        field: deepcopy(semantic.get(field))
                        for field in item["required_value_fields"]
                    },
                }
            )
        try:
            dependencies = _dependencies(
                source_records,
                architecture,
                {"records": dependency_records},
                observation,
            )
        except ValueError as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_dependency_decisions_invalid",
                str(error),
            ) from error

        responsibility_records: list[dict[str, Any]] = []
        for reference, item in catalog_by_ref.items():
            if item.get("kind") != "responsibility_record":
                continue
            facts = item["facts"]
            value = decisions.get(reference)
            previous = facts.get("previous")
            semantic = value if value is not None else previous
            if not isinstance(semantic, Mapping):
                raise ImplementationAlignmentPreparationError(
                    "alignment_decisions_incomplete",
                    f"目标责任缺少语义决定：{reference}",
                )
            responsibility_records.append(
                {
                    "target_id": str(facts["target_id"]),
                    **{
                        field: deepcopy(semantic.get(field))
                        for field in item["required_value_fields"]
                    },
                }
            )
        try:
            responsibilities = _responsibilities(
                architecture,
                {"records": responsibility_records},
            )
        except ValueError as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_responsibility_decisions_invalid",
                str(error),
            ) from error

        model = deepcopy(documents["model"])
        revision = model.get("revision")
        if not isinstance(revision, Mapping) or revision.get("status") != "draft":
            raise ImplementationAlignmentPreparationError(
                "alignment_revision_not_draft",
                "write-candidate 只能写入具有新修订身份的 draft 实现对齐",
            )
        revision_id = str(revision.get("revision_id") or "")
        domain_model = packet["domain_model"]
        architecture_model = packet["architecture_model"]
        model["domain_model_ref"] = {
            "model_id": domain_model["model_id"],
            "revision_id": domain_model["revision"]["revision_id"],
        }
        model["architecture_ref"] = {
            "architecture_id": architecture_model["architecture_id"],
            "revision_id": architecture_model["revision"]["revision_id"],
        }
        model["code_snapshot"] = {
            "repositories": deepcopy(packet["repository_content_refs"]),
            "governed_source_manifest_sha256": _manifest(governed_hashes),
            "observed_on": str(packet["observed_on"]),
        }
        model["observation_coverage"] = {
            "contract_version": observation["schema_version"],
            "overall_status": observation["overall_coverage_status"],
            "source_manifest_sha256": observation["source_manifest_sha256"],
            "observation_snapshot_sha256": observation[
                "observation_snapshot_sha256"
            ],
            "observed_paths": deepcopy(observation["observed_paths"]),
            "records": deepcopy(observation["coverage"]),
            "provider_receipts": deepcopy(observation["provider_receipts"]),
        }
        model["unresolved_items"] = deepcopy(unresolved_items)
        model.pop("semantic_content_machine_proven", None)

        model_id = str(model["alignment_model_id"])
        source_document = {
            "schema_version": "strixnova.implementation-source-ownership.v1",
            "alignment_model_id": model_id,
            "alignment_revision_id": revision_id,
            "governed_source_scopes": deepcopy(
                documents["source"]["governed_source_scopes"]
            ),
            "records": source_records,
        }
        dependencies_document = {
            "schema_version": "strixnova.implementation-actual-dependencies.v1",
            "alignment_model_id": model_id,
            "alignment_revision_id": revision_id,
            "observation_contract_version": observation["schema_version"],
            "records": dependencies,
        }
        responsibilities_document = {
            "schema_version": "strixnova.implementation-target-responsibilities.v1",
            "alignment_model_id": model_id,
            "alignment_revision_id": revision_id,
            "records": responsibilities,
        }
        deviations_document = {
            "schema_version": "strixnova.implementation-deviations.v1",
            "alignment_model_id": model_id,
            "alignment_revision_id": revision_id,
            "deviations": deepcopy(raw_deviations),
        }

        baseline = self._persistable(packet["baseline"])
        baseline["schema_version"] = "strixnova.project-engineering-baseline.v1"
        alignment_ref = baseline["authority_refs"]["implementation_alignment"]
        alignment_ref["revision_id"] = revision_id
        alignment_ref["status"] = {
            "revision_status": "draft",
            "adoption_status": "under_review",
        }
        baseline["code_version"] = {
            "repositories": deepcopy(packet["repository_content_refs"]),
        }
        reason = (
            "实现对齐候选已绑定当前代码观察；语义仍需 Agent 复核并由实际结果确认。"
        )
        baseline["review_state"] = {
            "required": True,
            "reasons": list(
                dict.fromkeys(
                    [
                        *(baseline.get("review_state", {}).get("reasons") or []),
                        reason,
                    ]
                )
            ),
            "affected_authority_kinds": sorted(
                {
                    *(
                        baseline.get("review_state", {}).get(
                            "affected_authority_kinds"
                        )
                        or []
                    ),
                    "implementation_alignment",
                    "code_version",
                }
            ),
        }

        paths = model["artifact_paths"]
        documents_to_write = [
            (project / str(binding["alignment_path"]), model),
            (project / str(paths["source_ownership"]), source_document),
            (project / str(paths["actual_dependencies"]), dependencies_document),
            (
                project / str(paths["target_responsibilities"]),
                responsibilities_document,
            ),
            (project / str(paths["deviations"]), deviations_document),
            (Path(packet.get("baseline_root", str(project))) / str(packet["baseline_path"]), baseline),
        ]

        # Recheck immediately before the transaction so a valid edit made
        # after prepare is rejected instead of being replaced by packet bytes.
        self._assert_target_file_bindings(packet, project)

        def validate_replaced() -> None:
            ProjectEngineeringBaseline(project).load(
                required=True,
                allow_candidate_refs=True,
            )
            baseline_reader = ProjectEngineeringBaseline(project)
            context = baseline_reader.context
            domain_ref = baseline["authority_refs"]["domain_model"]
            architecture_ref = baseline["authority_refs"]["target_architecture"]
            domain_source = context.authority_reader(domain_ref, parent_reader=baseline_reader.reader) if context is not None else baseline_reader.reader
            architecture_source = context.authority_reader(architecture_ref, parent_reader=baseline_reader.reader) if context is not None else baseline_reader.reader
            ProjectImplementationAlignment(
                project,
                str(binding["alignment_path"]),
                domain_model_path=str(
                    baseline["authority_refs"]["domain_model"]["path"]
                ),
                architecture_description_path=str(
                    baseline["authority_refs"]["target_architecture"]["path"]
                ),
                domain_reader=ProjectDomainModel(domain_source.project, domain_ref["path"], shared_reader=domain_source),
                architecture_reader=ProjectArchitectureDescription(architecture_source.project, architecture_ref["path"], shared_reader=architecture_source),
                repository_readers=repository_readers,
            ).load()
            if current_binding_check is not None:
                latest = current_binding_check()
                self._assert_current_binding(packet, self._binding(latest))

        try:
            _atomic_dump_many(
                documents_to_write,
                validate_replaced=validate_replaced,
                transaction_root=self._transaction_root(project),
                recovery_root=project,
                allowed_targets=[Path(path) for path in packet["target_file_locations"].values()],
            )
        except ImplementationAlignmentPreparationError:
            raise
        except (
            OSError,
            ValueError,
            DocumentTransactionError,
            ProjectImplementationAlignmentError,
        ) as error:
            raise ImplementationAlignmentPreparationError(
                "alignment_candidate_write_failed",
                "实现对齐候选没有通过恢复性写入和完整结构复核",
                details=getattr(error, "issues", [str(error)]),
            ) from error
        output_hashes = {
            target.relative_to(project).as_posix(): hashlib.sha256(
                target.read_bytes()
            ).hexdigest()
            for target, _value in documents_to_write
        }
        complete_alignment = bool(
            observation["overall_coverage_status"] == "complete"
            and not unresolved_items
            and not raw_deviations
            and all(
                record.get("disposition") != "owned"
                or record.get("current_status") == "aligned"
                for record in source_records
            )
            and all(
                record.get("classification")
                in PASSING_REFRESH_CLASSIFICATIONS
                for record in dependencies
            )
            and all(
                record.get("status") == "implemented"
                for record in responsibilities
            )
        )
        return {
            "schema_version": "strixnova.implementation-alignment-candidate-result.v1",
            "candidate_valid": True,
            "complete_alignment": complete_alignment,
            "alignment_model_id": model_id,
            "alignment_revision_id": revision_id,
            "candidate_status": "draft",
            "written_paths": sorted(output_hashes),
            "content_sha256_by_path": output_hashes,
            "observation_coverage_status": observation[
                "overall_coverage_status"
            ],
            "semantic_content_machine_proven": False,
        }
