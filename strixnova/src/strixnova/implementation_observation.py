"""Language-neutral, evidence-preserving implementation observation.

The public seam is intentionally small: callers submit exact source scopes and
receive one normalized snapshot.  Language adapters are internal details.  No
adapter decides architecture meaning, and no observation failure is represented
as an empty successful graph.
"""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath
import posixpath
import re
import shutil
import tomllib
from typing import Any
import xml.etree.ElementTree as ET

from jsonschema import Draft202012Validator

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
    repository_relative_path,
    repository_scope_root,
)
from strixnova.process_supervisor import (
    ProcessExecutionError,
    ProcessLimits,
    ProcessPolicy,
    run_process,
)


IMPLEMENTATION_OBSERVATION_SCHEMA = "strixnova.implementation-observation.v1"
IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA = (
    "strixnova.implementation-observation-provider.v1"
)

_LANGUAGE_ALIASES = {
    "c#": "csharp",
    "cs": "csharp",
    "c++": "cpp",
    "golang": "go",
    "javascript": "typescript",
    "js": "typescript",
    "py": "python",
    "rs": "rust",
    "ts": "typescript",
}
_STATUS_PRIORITY = {"complete": 0, "partial": 1, "unavailable": 2, "failed": 3}
_SOURCE_EXTENSIONS = {
    "python": frozenset({".py"}),
    "rust": frozenset({".rs"}),
    "go": frozenset({".go"}),
    "typescript": frozenset(
        {".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"}
    ),
    "csharp": frozenset({".cs"}),
    "cpp": frozenset({".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx"}),
}


class ImplementationObservationError(ValueError):
    """The observation plan is invalid or cannot be read safely."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "实现观察无效")


@dataclass(frozen=True)
class ExternalProviderMaterial:
    """One owner-confirmed provider file identity."""

    role: str
    path: str
    sha256: str
    command_argument_index: int | None

    def __post_init__(self) -> None:
        issues: list[str] = []
        if self.role not in {
            "executable",
            "entry_script",
            "config",
            "supporting_file",
        }:
            issues.append("外部观察提供者材料 role 无效")
        if not isinstance(self.path, str) or not self.path.strip():
            issues.append("外部观察提供者材料 path 必须是非空字符串")
        if not isinstance(self.sha256, str) or re.fullmatch(
            r"[0-9a-f]{64}", self.sha256
        ) is None:
            issues.append("外部观察提供者材料 sha256 无效")
        if self.command_argument_index is not None and (
            type(self.command_argument_index) is not int
            or self.command_argument_index < 0
        ):
            issues.append("外部观察提供者材料 command_argument_index 无效")
        if issues:
            raise ImplementationObservationError(issues)


@dataclass(frozen=True)
class ExternalObservationProvider:
    """One caller-authorized provider for one exact scope and language.

    The provider receives a JSON request on stdin and must emit exactly one
    ``strixnova.implementation-observation-provider.v1`` JSON object on stdout.
    Strixnova validates and normalizes that object; the provider never gains
    architecture or domain authority.
    """

    scope_id: str
    language_id: str
    provider_id: str
    provider_version: str
    command: tuple[str, ...]
    materials: tuple[ExternalProviderMaterial, ...]
    source_globs: tuple[str, ...]
    process_policy: ProcessPolicy
    limits: ProcessLimits = field(default_factory=ProcessLimits)

    def __post_init__(self) -> None:
        issues: list[str] = []
        if re.fullmatch(r"OBSCOPE-[0-9A-F]{16}", self.scope_id) is None:
            issues.append("外部观察提供者 scope_id 无效")
        try:
            normalized_language = _normalized_language(self.language_id)
        except ImplementationObservationError as error:
            issues.extend(error.issues)
        else:
            object.__setattr__(self, "language_id", normalized_language)
        for label, value in (
            ("provider_id", self.provider_id),
            ("provider_version", self.provider_version),
        ):
            if not isinstance(value, str) or not value.strip():
                issues.append(f"外部观察提供者 {label} 必须是非空字符串")
        if not self.command or any(
            not isinstance(item, str) or not item for item in self.command
        ):
            issues.append("外部观察提供者 command 必须是非空 argv")
        if not self.materials or any(
            not isinstance(item, ExternalProviderMaterial)
            for item in self.materials
        ):
            issues.append("外部观察提供者 materials 必须是非空材料绑定")
        else:
            bound_indices: set[int] = set()
            executable_count = 0
            for material in self.materials:
                index = material.command_argument_index
                if index is not None:
                    if index >= len(self.command):
                        issues.append("外部观察提供者材料绑定了未知 command 参数")
                    elif index in bound_indices:
                        issues.append("外部观察提供者材料重复绑定 command 参数")
                    bound_indices.add(index)
                if material.role in {"executable", "entry_script"} and index is None:
                    issues.append("可执行文件或入口脚本必须绑定 command 参数")
                if material.role == "executable":
                    executable_count += 1
                    if index != 0:
                        issues.append("外部观察提供者可执行文件必须绑定 command[0]")
            if executable_count != 1:
                issues.append("外部观察提供者必须唯一绑定 command[0] 可执行文件")
        if not self.source_globs or any(
            not isinstance(item, str)
            or not item.strip()
            or PurePosixPath(item).is_absolute()
            or ".." in PurePosixPath(item).parts
            or "\\" in item
            for item in self.source_globs
        ):
            issues.append("外部观察提供者 source_globs 必须是安全的非空相对 glob")
        if not isinstance(self.process_policy, ProcessPolicy):
            issues.append("外部观察提供者必须携带 ProcessPolicy")
        if not isinstance(self.limits, ProcessLimits):
            issues.append("外部观察提供者 limits 必须是 ProcessLimits")
        if issues:
            raise ImplementationObservationError(issues)


def external_observation_providers_from_plans(
    provider_plans: Sequence[Mapping[str, Any]],
) -> tuple[ExternalObservationProvider, ...]:
    """Build restricted providers from already-governed plan records.

    Process-policy construction belongs to the observation Adapter.  Callers
    provide only the exact, confirmed plan records and never construct process
    supervision objects themselves.
    """

    if not isinstance(provider_plans, Sequence) or isinstance(
        provider_plans, (str, bytes)
    ):
        raise ImplementationObservationError(
            ["外部观察 provider 计划必须是数组"]
        )
    providers: list[ExternalObservationProvider] = []
    issues: list[str] = []
    for index, raw in enumerate(provider_plans):
        label = f"external_observation_provider_plans[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{label} 必须是对象")
            continue
        policy = raw.get("process_policy")
        limits = raw.get("limits")
        if not isinstance(policy, Mapping) or not isinstance(limits, Mapping):
            issues.append(f"{label} 缺少 process_policy 或 limits")
            continue
        command = tuple(str(item) for item in raw.get("command") or [])
        raw_materials = raw.get("materials")
        if not isinstance(raw_materials, Sequence) or isinstance(
            raw_materials, (str, bytes)
        ):
            issues.append(f"{label}.materials 必须是数组")
            raw_materials = []
        try:
            providers.append(
                ExternalObservationProvider(
                    scope_id=str(raw.get("scope_id") or ""),
                    language_id=str(raw.get("language_id") or ""),
                    provider_id=str(raw.get("provider_id") or ""),
                    provider_version=str(raw.get("provider_version") or ""),
                    command=command,
                    materials=tuple(
                        ExternalProviderMaterial(
                            role=str(item.get("role") or ""),
                            path=str(item.get("path") or ""),
                            sha256=str(item.get("sha256") or ""),
                            command_argument_index=item.get(
                                "command_argument_index"
                            ),
                        )
                        for item in raw_materials
                        if isinstance(item, Mapping)
                    ),
                    source_globs=tuple(
                        str(item) for item in raw.get("source_globs") or []
                    ),
                    process_policy=ProcessPolicy.exact(
                        str(policy.get("policy_id") or ""),
                        str(policy.get("purpose") or ""),
                        command,
                        forbidden_program_names=tuple(
                            str(item)
                            for item in policy.get("forbidden_program_names") or []
                        ),
                    ),
                    limits=ProcessLimits(
                        timeout_seconds=float(limits["timeout_seconds"]),
                        cleanup_timeout_seconds=float(
                            limits["cleanup_timeout_seconds"]
                        ),
                        max_input_bytes=int(limits["max_input_bytes"]),
                        max_output_bytes=int(limits["max_output_bytes"]),
                    ),
                )
            )
        except (ImplementationObservationError, KeyError, TypeError, ValueError) as error:
            if isinstance(error, ImplementationObservationError):
                issues.extend(f"{label}: {issue}" for issue in error.issues)
            else:
                issues.append(f"{label} 不能形成受限 provider")
    if issues:
        raise ImplementationObservationError(issues)
    return tuple(providers)


def _external_provider_schema() -> dict[str, Any]:
    resource = files("strixnova.resources").joinpath(
        "implementation-observation-provider-v1.schema.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _external_provider_schema_issues(payload: Any) -> list[str]:
    errors = sorted(
        Draft202012Validator(_external_provider_schema()).iter_errors(payload),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    issues: list[str] = []
    for error in errors:
        path = ".".join(str(item) for item in error.absolute_path)
        location = f".{path}" if path else ""
        issues.append(f"外部提供者输出{location} 不符合版本化结构合同：{error.message}")
    return issues


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _identity(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:16].upper()}"


def _normalized_language(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ImplementationObservationError(["观察语言必须是非空字符串"])
    selected = value.strip().casefold()
    return _LANGUAGE_ALIASES.get(selected, selected)


def _relative_to_root(path: str, root: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    return candidate.relative_to(PurePosixPath(root))


def _observation_bytes(reader: GitProjectReader, path: str) -> bytes:
    """Use future Git blob bytes when a repository exists, raw bytes otherwise."""

    try:
        return reader.read_canonical_bytes(path, "实现观察源码")
    except GitProjectReaderError as error:
        if error.code != "git_repository_required":
            raise
        return reader.read_bytes(path, "实现观察源码")


def _is_excluded(path: str, root: str, exclusions: Sequence[str]) -> bool:
    relative = _relative_to_root(path, root)
    return any(relative.match(pattern) for pattern in exclusions)


def _normalize_scopes(raw_scopes: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    issues: list[str] = []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    if not isinstance(raw_scopes, Sequence) or isinstance(raw_scopes, (str, bytes)):
        raise ImplementationObservationError(["实现观察范围必须是数组"])
    if not raw_scopes:
        raise ImplementationObservationError(["至少需要一个实现观察范围"])
    for index, raw in enumerate(raw_scopes):
        if not isinstance(raw, Mapping):
            issues.append(f"observation_scopes[{index}] 必须是对象")
            continue
        scope_id = raw.get("scope_id")
        if not isinstance(scope_id, str) or re.fullmatch(
            r"OBSCOPE-[0-9A-F]{16}", scope_id
        ) is None:
            issues.append(
                f"observation_scopes[{index}].scope_id 必须匹配 OBSCOPE-加十六位大写十六进制"
            )
            continue
        if scope_id in seen:
            issues.append(f"实现观察范围身份重复：{scope_id}")
            continue
        seen.add(scope_id)
        try:
            root = repository_scope_root(
                raw.get("root"),
                f"observation_scopes[{index}].root",
            )
        except GitProjectReaderError as error:
            issues.append(str(error))
            continue
        raw_languages = raw.get("languages")
        if not isinstance(raw_languages, list) or not raw_languages:
            issues.append(f"observation_scopes[{index}].languages 必须是非空数组")
            continue
        try:
            languages = sorted({_normalized_language(item) for item in raw_languages})
        except ImplementationObservationError as error:
            issues.extend(error.issues)
            continue
        relation_kinds = raw.get("required_relation_kinds")
        if not isinstance(relation_kinds, list) or not relation_kinds or not all(
            isinstance(item, str) and item.strip() for item in relation_kinds
        ):
            issues.append(
                f"observation_scopes[{index}].required_relation_kinds 必须是非空字符串数组"
            )
            continue
        configurations = raw.get("configurations", ["default"])
        if not isinstance(configurations, list) or not configurations or not all(
            isinstance(item, str) and item.strip() for item in configurations
        ):
            issues.append(
                f"observation_scopes[{index}].configurations 必须是非空字符串数组"
            )
            continue
        exclusions = raw.get("exclusions", [])
        if not isinstance(exclusions, list) or not all(
            isinstance(item, str)
            and item.strip()
            and not PurePosixPath(item).is_absolute()
            and ".." not in PurePosixPath(item).parts
            and "\\" not in item
            for item in exclusions
        ):
            issues.append(
                f"observation_scopes[{index}].exclusions 必须是安全的仓库相对 glob 数组"
            )
            continue
        options = raw.get("provider_options", {})
        if not isinstance(options, Mapping):
            issues.append(
                f"observation_scopes[{index}].provider_options 必须是对象"
            )
            continue
        normalized.append(
            {
                "scope_id": scope_id,
                "root": root,
                "languages": languages,
                "required_relation_kinds": sorted(
                    {str(item).strip() for item in relation_kinds}
                ),
                "configurations": sorted(
                    {str(item).strip() for item in configurations}
                ),
                "exclusions": sorted({str(item).strip() for item in exclusions}),
                "provider_options": dict(options),
            }
        )
    if issues:
        raise ImplementationObservationError(issues)
    return sorted(normalized, key=lambda item: item["scope_id"])


def _normalize_external_providers(
    providers: Sequence[ExternalObservationProvider],
) -> dict[tuple[str, str], ExternalObservationProvider]:
    if not isinstance(providers, Sequence) or isinstance(providers, (str, bytes)):
        raise ImplementationObservationError(["外部观察提供者必须是数组"])
    normalized: dict[tuple[str, str], ExternalObservationProvider] = {}
    issues: list[str] = []
    for index, provider in enumerate(providers):
        if not isinstance(provider, ExternalObservationProvider):
            issues.append(f"external_providers[{index}] 类型无效")
            continue
        key = (provider.scope_id, provider.language_id)
        if key in normalized:
            issues.append(
                "外部观察提供者重复："
                f"{provider.scope_id}/{provider.language_id}"
            )
            continue
        try:
            provider.process_policy.validate(provider.command)
        except ProcessExecutionError as error:
            issues.append(
                "外部观察提供者命令未被其 ProcessPolicy 精确允许："
                f"{provider.scope_id}/{provider.language_id}/{error.reason}"
            )
            continue
        normalized[key] = provider
    if issues:
        raise ImplementationObservationError(issues)
    return normalized


def _path_in_scope(path: str, root: str, field: str) -> str:
    try:
        normalized = repository_relative_path(path, field)
        PurePosixPath(normalized).relative_to(PurePosixPath(root))
    except (GitProjectReaderError, ValueError) as error:
        raise ImplementationObservationError(
            [f"{field} 必须位于观察范围 {root} 内"]
        ) from error
    return normalized


class _ProviderMaterialVerificationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _resolved_provider_material_path(project: Path, raw_path: str) -> Path:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        return candidate.resolve()
    try:
        relative = repository_relative_path(raw_path, "provider material path")
    except GitProjectReaderError as error:
        raise _ProviderMaterialVerificationError(
            "provider_material_path_invalid",
            str(error),
        ) from error
    resolved = project.joinpath(*PurePosixPath(relative).parts).resolve()
    if not resolved.is_relative_to(project):
        raise _ProviderMaterialVerificationError(
            "provider_material_path_invalid",
            f"外部观察提供者材料越出项目：{raw_path}",
        )
    return resolved


def _resolved_command_argument(
    project: Path,
    command: Sequence[str],
    index: int,
) -> Path:
    token = command[index]
    if index == 0 and not Path(token).is_absolute() and not any(
        separator in token for separator in ("/", "\\")
    ):
        discovered = shutil.which(token)
        if discovered is None:
            raise _ProviderMaterialVerificationError(
                "provider_material_missing",
                f"外部观察提供者可执行文件不可解析：{token}",
            )
        return Path(discovered).resolve()
    candidate = Path(token)
    return (
        candidate.resolve()
        if candidate.is_absolute()
        else (project / candidate).resolve()
    )


def _verify_provider_materials(
    project: Path,
    provider: ExternalObservationProvider,
) -> list[dict[str, Any]]:
    receipts: list[dict[str, Any]] = []
    for material in provider.materials:
        resolved = _resolved_provider_material_path(project, material.path)
        if not resolved.is_file() or resolved.is_symlink():
            raise _ProviderMaterialVerificationError(
                "provider_material_missing",
                f"外部观察提供者材料不存在或不是普通文件：{material.path}",
            )
        if material.command_argument_index is not None:
            command_path = _resolved_command_argument(
                project,
                provider.command,
                material.command_argument_index,
            )
            if command_path != resolved:
                raise _ProviderMaterialVerificationError(
                    "provider_material_command_mismatch",
                    (
                        "外部观察提供者材料路径没有绑定已确认的 command 参数："
                        f"{material.path}"
                    ),
                )
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        if digest != material.sha256:
            raise _ProviderMaterialVerificationError(
                "provider_material_changed",
                f"外部观察提供者材料在方案确认后发生变化：{material.path}",
            )
        receipts.append(
            {
                "role": material.role,
                "path": material.path,
                "sha256": digest,
                "command_argument_index": material.command_argument_index,
            }
        )
    return receipts


def _external_provider_failure(
    scope: Mapping[str, Any],
    provider: ExternalObservationProvider,
    *,
    status: str,
    execution_mode: str,
    code: str,
    message: str,
    expected_source_count: int,
    request_sha256: str | None = None,
    material_receipts: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    coverage = {
        "scope_id": scope["scope_id"],
        "language_id": provider.language_id,
        "provider_id": provider.provider_id,
        "provider_version": provider.provider_version,
        "status": status,
        "execution_mode": execution_mode,
        "configurations": list(scope["configurations"]),
        "required_relation_kinds": list(scope["required_relation_kinds"]),
        "supported_relation_kinds": [],
        "observed_relation_kinds": [],
        "source_file_count": expected_source_count,
        "relation_count": 0,
        "limitations": [],
        "gaps": [
            {
                "code": code,
                "message": message,
                "paths": [scope["root"]],
                "relation_kind": None,
            }
        ],
    }
    receipt = {
        "scope_id": scope["scope_id"],
        "language_id": provider.language_id,
        "provider_id": provider.provider_id,
        "provider_version": provider.provider_version,
        "execution_mode": execution_mode,
        "status": status,
        "result_sha256": _canonical_hash(coverage),
        "policy_id": provider.process_policy.policy_id,
        "command_sha256": _canonical_hash(list(provider.command)),
        "material_receipts": [dict(item) for item in material_receipts],
    }
    if request_sha256 is not None:
        receipt["request_sha256"] = request_sha256
    return {
        "nodes": [],
        "relations": [],
        "coverage": coverage,
        "observed_paths": {},
        "receipt": receipt,
    }


def _external_source_paths(
    scope: Mapping[str, Any],
    scope_paths: Sequence[str],
    provider: ExternalObservationProvider,
) -> list[str]:
    root = str(scope["root"])
    return sorted(
        path
        for path in scope_paths
        if any(
            _relative_to_root(path, root).match(pattern)
            for pattern in provider.source_globs
        )
    )


def _observe_external_provider(
    reader: GitProjectReader,
    scope: Mapping[str, Any],
    scope_paths: Sequence[str],
    provider: ExternalObservationProvider,
    *,
    execution_authorized: bool,
) -> dict[str, Any]:
    expected_paths = _external_source_paths(scope, scope_paths, provider)
    if not execution_authorized:
        return _external_provider_failure(
            scope,
            provider,
            status="unavailable",
            execution_mode="not_run",
            code="provider_execution_not_authorized",
            message="外部实现观察提供者没有取得本次调用的明确执行授权",
            expected_source_count=len(expected_paths),
        )
    if reader.observed_commit is not None:
        return _external_provider_failure(
            scope,
            provider,
            status="unavailable",
            execution_mode="not_run",
            code="provider_immutable_snapshot_unavailable",
            message="外部提供者不能针对未物化的不可变 Git 快照执行",
            expected_source_count=len(expected_paths),
        )

    try:
        material_receipts = _verify_provider_materials(reader.project, provider)
    except _ProviderMaterialVerificationError as error:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="not_run",
            code=error.code,
            message=str(error),
            expected_source_count=len(expected_paths),
        )

    request = {
        "schema_version": "strixnova.implementation-observation-provider-request.v1",
        "requested_output_schema_version": IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA,
        "scope": dict(scope),
        "language_id": provider.language_id,
        "provider_id": provider.provider_id,
        "provider_version": provider.provider_version,
        "scope_paths": list(scope_paths),
        "expected_source_paths": expected_paths,
    }
    try:
        request_bytes = json.dumps(
            request,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="authorized_tool",
            code="provider_request_invalid",
            message=(
                "外部实现观察提供者请求无法序列化："
                f"{type(error).__name__}"
            ),
            expected_source_count=len(expected_paths),
        )
    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
    if len(request_bytes) > provider.limits.max_input_bytes:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="authorized_tool",
            code="provider_request_input_limit",
            message=(
                "外部实现观察提供者请求超过明确输入上限："
                f"{len(request_bytes)} > {provider.limits.max_input_bytes}"
            ),
            expected_source_count=len(expected_paths),
            request_sha256=request_sha256,
            material_receipts=material_receipts,
        )
    try:
        process_result = run_process(
            provider.command,
            cwd=reader.project,
            policy=provider.process_policy,
            limits=provider.limits,
            stdin_bytes=request_bytes,
        )
    except ProcessExecutionError as error:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="authorized_tool",
            code=f"provider_process_{error.reason}",
            message=f"外部实现观察提供者执行失败：{error.reason}",
            expected_source_count=len(expected_paths),
            request_sha256=request_sha256,
            material_receipts=material_receipts,
        )
    if process_result.exit_code != 0:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="authorized_tool",
            code="provider_process_nonzero_exit",
            message=(
                "外部实现观察提供者返回非零退出码："
                f"{process_result.exit_code}"
            ),
            expected_source_count=len(expected_paths),
            request_sha256=request_sha256,
            material_receipts=material_receipts,
        )
    try:
        payload = json.loads(process_result.stdout.decode("utf-8", errors="strict"))
    except (UnicodeError, json.JSONDecodeError) as error:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="authorized_tool",
            code="provider_output_invalid_json",
            message=f"外部实现观察提供者输出不是有效 UTF-8 JSON：{type(error).__name__}",
            expected_source_count=len(expected_paths),
            request_sha256=request_sha256,
            material_receipts=material_receipts,
        )
    try:
        normalized = _normalize_external_provider_output(
            reader,
            scope,
            scope_paths,
            expected_paths,
            provider,
            payload,
        )
    except ImplementationObservationError as error:
        return _external_provider_failure(
            scope,
            provider,
            status="failed",
            execution_mode="authorized_tool",
            code="provider_output_contract_invalid",
            message="外部实现观察提供者输出不符合合同：" + "；".join(error.issues),
            expected_source_count=len(expected_paths),
            request_sha256=request_sha256,
            material_receipts=material_receipts,
        )
    normalized["receipt"] = {
        "scope_id": scope["scope_id"],
        "language_id": provider.language_id,
        "provider_id": provider.provider_id,
        "provider_version": provider.provider_version,
        "execution_mode": "authorized_tool",
        "status": normalized["coverage"]["status"],
        "result_sha256": _canonical_hash(
            {
                "nodes": normalized["nodes"],
                "relations": normalized["relations"],
                "coverage": normalized["coverage"],
                "observed_paths": normalized["observed_paths"],
            }
        ),
        "policy_id": provider.process_policy.policy_id,
        "command_sha256": _canonical_hash(list(provider.command)),
        "request_sha256": request_sha256,
        "material_receipts": material_receipts,
    }
    return normalized


class _ObservationBuilder:
    def __init__(
        self,
        reader: GitProjectReader,
        scope: Mapping[str, Any],
        language_id: str,
        provider_id: str,
        supported_relation_kinds: Sequence[str],
    ) -> None:
        self.reader = reader
        self.scope = dict(scope)
        self.language_id = language_id
        self.provider_id = provider_id
        self.supported_relation_kinds = tuple(sorted(supported_relation_kinds))
        self.nodes: dict[str, dict[str, Any]] = {}
        self.relations: dict[str, dict[str, Any]] = {}
        self.gaps: list[dict[str, Any]] = []
        self.limitations: set[str] = set()
        self.observed_paths: dict[str, str] = {}
        self.failed = False

    def read_text(self, path: str) -> str | None:
        try:
            content = _observation_bytes(self.reader, path)
            self.observed_paths[path] = hashlib.sha256(content).hexdigest()
            return content.decode("utf-8")
        except (GitProjectReaderError, UnicodeError) as error:
            self.add_gap(
                "source_unreadable",
                f"无法安全读取实现文件：{path}：{error}",
                paths=[path],
                fatal=True,
            )
            return None

    def add_node(
        self,
        *,
        node_kind: str,
        path: str | None,
        external_name: str | None = None,
        display_name: str | None = None,
        identity_key: str | None = None,
    ) -> str:
        identity_value = (
            identity_key
            if identity_key is not None
            else path if path is not None else f"external:{external_name}"
        )
        node_id = _identity(
            "IMPLNODE",
            self.scope["scope_id"],
            self.language_id,
            self.provider_id,
            node_kind,
            identity_value,
        )
        self.nodes[node_id] = {
            "node_id": node_id,
            "scope_id": self.scope["scope_id"],
            "language_id": self.language_id,
            "node_kind": node_kind,
            "path": path,
            "external_name": external_name,
            "display_name": display_name or path or external_name,
        }
        return node_id

    def source_node(self, path: str) -> str:
        return self.add_node(node_kind="source_file", path=path)

    def add_relation(
        self,
        *,
        source_node_id: str,
        target_node_id: str,
        relation_kind: str,
        observed_name: str,
        resolution_status: str,
        evidence_path: str,
        line: int | None = None,
        conditions: Sequence[str] = (),
    ) -> None:
        relation_id = _identity(
            "IMPLREL",
            self.scope["scope_id"],
            self.provider_id,
            source_node_id,
            target_node_id,
            relation_kind,
            observed_name,
            resolution_status,
            *sorted(conditions),
        )
        location = {"path": evidence_path, "line": line}
        existing = self.relations.get(relation_id)
        if existing is not None:
            if location not in existing["evidence_locations"]:
                existing["evidence_locations"].append(location)
                existing["evidence_locations"].sort(
                    key=lambda item: (item["path"], item["line"] or 0)
                )
            return
        self.relations[relation_id] = {
            "relation_id": relation_id,
            "scope_id": self.scope["scope_id"],
            "provider_id": self.provider_id,
            "source_node_id": source_node_id,
            "target_node_id": target_node_id,
            "relation_kind": relation_kind,
            "observed_name": observed_name,
            "resolution_status": resolution_status,
            "conditions": sorted(set(conditions)),
            "evidence_locations": [location],
        }

    def add_gap(
        self,
        code: str,
        message: str,
        *,
        paths: Sequence[str] = (),
        relation_kind: str | None = None,
        fatal: bool = False,
    ) -> None:
        gap = {
            "code": code,
            "message": message,
            "paths": sorted(set(paths)),
            "relation_kind": relation_kind,
        }
        if gap not in self.gaps:
            self.gaps.append(gap)
        self.failed = self.failed or fatal

    def result(self, source_file_count: int) -> dict[str, Any]:
        requested = set(self.scope["required_relation_kinds"])
        unsupported = sorted(requested - set(self.supported_relation_kinds))
        for relation_kind in unsupported:
            self.add_gap(
                "relation_kind_unsupported",
                f"{self.provider_id} 不支持必需关系种类：{relation_kind}",
                relation_kind=relation_kind,
            )
        if source_file_count == 0:
            self.add_gap(
                "no_source_files",
                f"观察范围内没有找到 {self.language_id} 源文件，不能据此证明没有实现关系",
            )
        if self.failed:
            status = "failed"
        elif unsupported or self.gaps or self.limitations or source_file_count == 0:
            status = "partial"
        else:
            status = "complete"
        return {
            "nodes": sorted(self.nodes.values(), key=lambda item: item["node_id"]),
            "relations": sorted(
                self.relations.values(), key=lambda item: item["relation_id"]
            ),
            "coverage": {
                "scope_id": self.scope["scope_id"],
                "language_id": self.language_id,
                "provider_id": self.provider_id,
                "provider_version": "1",
                "status": status,
                "execution_mode": "builtin_static",
                "configurations": list(self.scope["configurations"]),
                "required_relation_kinds": list(
                    self.scope["required_relation_kinds"]
                ),
                "supported_relation_kinds": list(self.supported_relation_kinds),
                "observed_relation_kinds": sorted(
                    {item["relation_kind"] for item in self.relations.values()}
                ),
                "source_file_count": source_file_count,
                "relation_count": len(self.relations),
                "limitations": sorted(self.limitations),
                "gaps": sorted(
                    self.gaps,
                    key=lambda item: (
                        item["code"], item["message"], item["paths"]
                    ),
                ),
            },
            "observed_paths": dict(sorted(self.observed_paths.items())),
        }


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item.strip() for item in value
    ):
        raise ImplementationObservationError(
            [f"外部提供者输出 {field_name} 必须是字符串数组"]
        )
    return sorted({item.strip() for item in value})


def _normalize_external_provider_output(
    reader: GitProjectReader,
    scope: Mapping[str, Any],
    scope_paths: Sequence[str],
    expected_source_paths: Sequence[str],
    provider: ExternalObservationProvider,
    payload: Any,
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ImplementationObservationError(["外部提供者输出根必须是对象"])
    schema_issues = _external_provider_schema_issues(payload)
    if schema_issues:
        raise ImplementationObservationError(schema_issues)
    required_keys = {
        "schema_version",
        "scope_id",
        "language_id",
        "provider_id",
        "provider_version",
        "status",
        "supported_relation_kinds",
        "nodes",
        "relations",
        "observed_paths",
        "limitations",
        "gaps",
    }
    unknown = sorted(set(payload) - required_keys)
    missing = sorted(required_keys - set(payload))
    issues = [f"外部提供者输出缺少字段：{item}" for item in missing]
    issues.extend(f"外部提供者输出存在未知字段：{item}" for item in unknown)
    expected_identity = {
        "schema_version": IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA,
        "scope_id": scope["scope_id"],
        "language_id": provider.language_id,
        "provider_id": provider.provider_id,
        "provider_version": provider.provider_version,
    }
    for field_name, expected in expected_identity.items():
        if payload.get(field_name) != expected:
            issues.append(f"外部提供者输出 {field_name} 与请求身份不一致")
    if payload.get("status") not in {"complete", "partial", "failed"}:
        issues.append("外部提供者输出 status 无效")
    if issues:
        raise ImplementationObservationError(issues)

    supported = _string_list(
        payload["supported_relation_kinds"],
        "supported_relation_kinds",
    )
    limitations = _string_list(payload["limitations"], "limitations")
    raw_nodes = payload["nodes"]
    raw_relations = payload["relations"]
    raw_hashes = payload["observed_paths"]
    raw_gaps = payload["gaps"]
    if not isinstance(raw_nodes, list):
        raise ImplementationObservationError(["外部提供者输出 nodes 必须是数组"])
    if not isinstance(raw_relations, list):
        raise ImplementationObservationError(["外部提供者输出 relations 必须是数组"])
    if not isinstance(raw_hashes, Mapping):
        raise ImplementationObservationError(
            ["外部提供者输出 observed_paths 必须是对象"]
        )
    if not isinstance(raw_gaps, list):
        raise ImplementationObservationError(["外部提供者输出 gaps 必须是数组"])

    scope_path_set = set(scope_paths)
    expected_path_set = set(expected_source_paths)
    observed_hashes: dict[str, str] = {}
    for raw_path, raw_hash in raw_hashes.items():
        if not isinstance(raw_path, str) or not isinstance(raw_hash, str):
            raise ImplementationObservationError(
                ["外部提供者 observed_paths 的键和值必须是字符串"]
            )
        path = _path_in_scope(raw_path, str(scope["root"]), "observed_paths 路径")
        if path not in expected_path_set:
            raise ImplementationObservationError(
                [f"外部提供者观察了未声明为源码的路径：{path}"]
            )
        if re.fullmatch(r"[0-9a-f]{64}", raw_hash) is None:
            raise ImplementationObservationError(
                [f"外部提供者源码哈希无效：{path}"]
            )
        actual_content = reader.read_bytes(path, "外部提供者观察源码")
        actual_hash = hashlib.sha256(actual_content).hexdigest()
        if raw_hash != actual_hash:
            raise ImplementationObservationError(
                [f"外部提供者源码哈希与精确快照不一致：{path}"]
            )
        canonical_content = _observation_bytes(reader, path)
        observed_hashes[path] = hashlib.sha256(canonical_content).hexdigest()
    if set(observed_hashes) != expected_path_set:
        missing_paths = sorted(expected_path_set - set(observed_hashes))
        extra_paths = sorted(set(observed_hashes) - expected_path_set)
        details = [
            *(f"外部提供者没有覆盖声明源码：{path}" for path in missing_paths),
            *(f"外部提供者覆盖了范围外源码：{path}" for path in extra_paths),
        ]
        raise ImplementationObservationError(details)

    builder = _ObservationBuilder(
        reader,
        scope,
        provider.language_id,
        provider.provider_id,
        supported,
    )
    builder.limitations.update(limitations)
    builder.observed_paths.update(observed_hashes)
    node_ids: dict[str, str] = {}
    internal_node_keys: set[str] = set()
    source_node_paths: set[str] = set()
    for index, raw_node in enumerate(raw_nodes):
        if not isinstance(raw_node, Mapping):
            raise ImplementationObservationError(
                [f"外部提供者 nodes[{index}] 必须是对象"]
            )
        allowed = {"node_key", "node_kind", "path", "external_name", "display_name"}
        if set(raw_node) != allowed:
            raise ImplementationObservationError(
                [f"外部提供者 nodes[{index}] 字段不完整或含未知字段"]
            )
        node_key = raw_node["node_key"]
        node_kind = raw_node["node_kind"]
        path = raw_node["path"]
        external_name = raw_node["external_name"]
        display_name = raw_node["display_name"]
        if not isinstance(node_key, str) or not node_key.strip():
            raise ImplementationObservationError(
                [f"外部提供者 nodes[{index}].node_key 无效"]
            )
        if node_key in node_ids:
            raise ImplementationObservationError(
                [f"外部提供者节点键重复：{node_key}"]
            )
        if not isinstance(node_kind, str) or not node_kind.strip():
            raise ImplementationObservationError(
                [f"外部提供者 nodes[{index}].node_kind 无效"]
            )
        if display_name is not None and (
            not isinstance(display_name, str) or not display_name.strip()
        ):
            raise ImplementationObservationError(
                [f"外部提供者 nodes[{index}].display_name 无效"]
            )
        if path is None:
            if not isinstance(external_name, str) or not external_name.strip():
                raise ImplementationObservationError(
                    [f"外部提供者 nodes[{index}] 外部节点缺少 external_name"]
                )
            normalized_path = None
        else:
            if not isinstance(path, str) or external_name is not None:
                raise ImplementationObservationError(
                    [f"外部提供者 nodes[{index}] 内部节点身份无效"]
                )
            normalized_path = _path_in_scope(
                path,
                str(scope["root"]),
                f"nodes[{index}].path",
            )
            if normalized_path not in scope_path_set:
                raise ImplementationObservationError(
                    [f"外部提供者节点路径不属于精确范围：{normalized_path}"]
                )
            if node_kind == "source_file":
                source_node_paths.add(normalized_path)
            internal_node_keys.add(node_key)
        node_ids[node_key] = builder.add_node(
            node_kind=node_kind.strip(),
            path=normalized_path,
            external_name=(external_name.strip() if isinstance(external_name, str) else None),
            display_name=(display_name.strip() if isinstance(display_name, str) else None),
            identity_key=node_key,
        )
    if source_node_paths != expected_path_set:
        raise ImplementationObservationError(
            ["外部提供者 source_file 节点必须与声明源码范围完全一致"]
        )

    resolution_statuses = {
        "resolved_internal",
        "external",
        "unresolved",
        "ambiguous",
    }
    for index, raw_relation in enumerate(raw_relations):
        if not isinstance(raw_relation, Mapping):
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}] 必须是对象"]
            )
        allowed = {
            "source_node_key",
            "target_node_key",
            "relation_kind",
            "observed_name",
            "resolution_status",
            "conditions",
            "evidence_locations",
        }
        if set(raw_relation) != allowed:
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}] 字段不完整或含未知字段"]
            )
        source_key = raw_relation["source_node_key"]
        target_key = raw_relation["target_node_key"]
        if source_key not in node_ids or target_key not in node_ids:
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}] 引用了未知节点"]
            )
        if source_key not in internal_node_keys:
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}] 的来源必须是范围内实现节点"]
            )
        relation_kind = raw_relation["relation_kind"]
        observed_name = raw_relation["observed_name"]
        resolution_status = raw_relation["resolution_status"]
        if not isinstance(relation_kind, str) or not relation_kind.strip():
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}].relation_kind 无效"]
            )
        if relation_kind.strip() not in supported:
            raise ImplementationObservationError(
                [
                    "外部提供者关系种类没有包含在 supported_relation_kinds："
                    f"{relation_kind.strip()}"
                ]
            )
        if not isinstance(observed_name, str) or not observed_name.strip():
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}].observed_name 无效"]
            )
        if resolution_status not in resolution_statuses:
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}].resolution_status 无效"]
            )
        conditions = _string_list(
            raw_relation["conditions"],
            f"relations[{index}].conditions",
        )
        locations = raw_relation["evidence_locations"]
        if not isinstance(locations, list) or not locations:
            raise ImplementationObservationError(
                [f"外部提供者 relations[{index}].evidence_locations 必须非空"]
            )
        for location_index, location in enumerate(locations):
            if not isinstance(location, Mapping) or set(location) != {"path", "line"}:
                raise ImplementationObservationError(
                    [
                        "外部提供者关系证据位置字段无效："
                        f"relations[{index}].evidence_locations[{location_index}]"
                    ]
                )
            evidence_path = location["path"]
            if not isinstance(evidence_path, str):
                raise ImplementationObservationError(
                    [f"外部提供者 relations[{index}] 证据路径无效"]
                )
            normalized_evidence_path = _path_in_scope(
                evidence_path,
                str(scope["root"]),
                f"relations[{index}].evidence_locations[{location_index}].path",
            )
            if normalized_evidence_path not in scope_path_set:
                raise ImplementationObservationError(
                    [f"外部提供者关系证据路径不属于精确范围：{normalized_evidence_path}"]
                )
            line = location["line"]
            if line is not None and (not isinstance(line, int) or line < 1):
                raise ImplementationObservationError(
                    [f"外部提供者 relations[{index}] 证据行号无效"]
                )
            builder.add_relation(
                source_node_id=node_ids[source_key],
                target_node_id=node_ids[target_key],
                relation_kind=relation_kind.strip(),
                observed_name=observed_name.strip(),
                resolution_status=str(resolution_status),
                evidence_path=normalized_evidence_path,
                line=line,
                conditions=conditions,
            )
        if resolution_status in {"unresolved", "ambiguous"}:
            builder.add_gap(
                "provider_relation_not_resolved",
                "外部提供者报告了未解析或歧义关系",
                relation_kind=relation_kind.strip(),
            )

    for index, raw_gap in enumerate(raw_gaps):
        if not isinstance(raw_gap, Mapping) or set(raw_gap) != {
            "code",
            "message",
            "paths",
            "relation_kind",
        }:
            raise ImplementationObservationError(
                [f"外部提供者 gaps[{index}] 字段无效"]
            )
        code = raw_gap["code"]
        message = raw_gap["message"]
        if not isinstance(code, str) or not code.strip():
            raise ImplementationObservationError(
                [f"外部提供者 gaps[{index}].code 无效"]
            )
        if not isinstance(message, str) or not message.strip():
            raise ImplementationObservationError(
                [f"外部提供者 gaps[{index}].message 无效"]
            )
        paths = _string_list(raw_gap["paths"], f"gaps[{index}].paths")
        normalized_paths = [
            _path_in_scope(path, str(scope["root"]), f"gaps[{index}].paths")
            for path in paths
        ]
        relation_kind = raw_gap["relation_kind"]
        if relation_kind is not None and (
            not isinstance(relation_kind, str) or not relation_kind.strip()
        ):
            raise ImplementationObservationError(
                [f"外部提供者 gaps[{index}].relation_kind 无效"]
            )
        builder.add_gap(
            code.strip(),
            message.strip(),
            paths=normalized_paths,
            relation_kind=(relation_kind.strip() if isinstance(relation_kind, str) else None),
            fatal=payload["status"] == "failed",
        )
    if payload["status"] == "partial" and not builder.gaps and not builder.limitations:
        builder.add_gap(
            "provider_reported_partial",
            "外部提供者报告部分覆盖但没有提供更具体的缺口",
        )
    if payload["status"] == "failed":
        builder.failed = True
    result = builder.result(len(expected_source_paths))
    result["coverage"]["provider_version"] = provider.provider_version
    result["coverage"]["execution_mode"] = "authorized_tool"
    return result


class _PythonAdapter:
    language_id = "python"
    provider_id = "strixnova.python-static.v1"
    relation_kinds = ("source_import",)

    @staticmethod
    def _module_name(package_name: str, relative_path: PurePosixPath) -> str:
        parts = list(relative_path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        suffix = ".".join(parts)
        return ".".join(part for part in (package_name, suffix) if part)

    @staticmethod
    def _absolute_import(
        node: ast.ImportFrom,
        *,
        source_module: str,
        source_is_package: bool,
    ) -> str:
        if node.level == 0:
            return node.module or ""
        package_parts = source_module.split(".")
        if not source_is_package:
            package_parts.pop()
        remove_count = node.level - 1
        if remove_count:
            package_parts = package_parts[:-remove_count]
        if node.module:
            package_parts.extend(node.module.split("."))
        return ".".join(package_parts)

    @staticmethod
    def _resolve(imported: str, modules: Mapping[str, str]) -> str | None:
        candidate = imported
        while candidate:
            if candidate in modules:
                return modules[candidate]
            candidate = candidate.rpartition(".")[0]
        return None

    def observe(
        self,
        reader: GitProjectReader,
        scope: Mapping[str, Any],
        paths: Sequence[str],
    ) -> dict[str, Any]:
        builder = _ObservationBuilder(
            reader, scope, self.language_id, self.provider_id, self.relation_kinds
        )
        root = scope["root"]
        prefix = root.rstrip("/") + "/"
        source_paths = sorted(
            path for path in paths if PurePosixPath(path).suffix == ".py"
        )
        package_name = str(
            scope["provider_options"].get(
                "python_package_name", PurePosixPath(root).name
            )
        ).strip()
        if not package_name and root != ".":
            builder.add_gap(
                "python_package_name_missing",
                "Python 观察需要非空软件包名称",
                fatal=True,
            )
            return builder.result(len(source_paths))
        relative = {
            path: (
                PurePosixPath(PurePosixPath(path).name)
                if path == root
                else PurePosixPath(path.removeprefix(prefix))
            )
            for path in source_paths
        }
        nested_package_roots = sorted(
            {
                f"{root}/{item.parts[0]}"
                for item in relative.values()
                if len(item.parts) > 1 and item.name == "__init__.py"
            }
        )
        if (
            root != "."
            and f"{root}/__init__.py" not in source_paths
            and nested_package_roots
            and package_name == PurePosixPath(root).name
            and scope["provider_options"].get("python_namespace_package") is not True
        ):
            builder.add_gap(
                "python_source_container_ambiguous",
                f"{root} 是源码容器而不是单一可导入软件包根；候选根："
                + "、".join(nested_package_roots),
                paths=nested_package_roots,
                relation_kind="source_import",
                fatal=True,
            )
            return builder.result(len(source_paths))
        modules = {
            self._module_name(package_name, rel): path
            for path, rel in relative.items()
        }
        for path in source_paths:
            builder.source_node(path)
        for source_path in source_paths:
            text = builder.read_text(source_path)
            if text is None:
                continue
            source_module = self._module_name(package_name, relative[source_path])
            try:
                tree = ast.parse(text, filename=source_path)
            except SyntaxError as error:
                builder.add_gap(
                    "python_syntax_error",
                    f"Python AST 无法解析：{source_path}:{error.lineno or 0}",
                    paths=[source_path],
                    relation_kind="source_import",
                    fatal=True,
                )
                continue
            for node in ast.walk(tree):
                imported_names: Sequence[str]
                if isinstance(node, ast.Import):
                    imported_names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    base_import = self._absolute_import(
                        node,
                        source_module=source_module,
                        source_is_package=relative[source_path].name
                        == "__init__.py",
                    )
                    imported_names = []
                    for alias in node.names:
                        qualified_alias = (
                            f"{base_import}.{alias.name}"
                            if base_import and alias.name != "*"
                            else base_import
                        )
                        # ``from . import child`` imports the child module when
                        # it exists.  Treating only the package __init__ as the
                        # target hides a real file-to-file dependency.
                        imported_names.append(
                            qualified_alias
                            if qualified_alias in modules
                            else base_import
                        )
                    imported_names = list(dict.fromkeys(imported_names))
                elif isinstance(node, ast.Call) and (
                    isinstance(node.func, ast.Name)
                    and node.func.id in {"__import__", "import_module"}
                    or isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module"
                ):
                    builder.add_gap(
                        "python_dynamic_import",
                        f"动态导入需要人工或运行时补充观察：{source_path}:{node.lineno}",
                        paths=[source_path],
                        relation_kind="source_import",
                    )
                    continue
                else:
                    continue
                for imported_name in imported_names:
                    if not imported_name:
                        continue
                    target_path = self._resolve(imported_name, modules)
                    source_id = builder.source_node(source_path)
                    if target_path is not None and target_path != source_path:
                        target_id = builder.source_node(target_path)
                        resolution = "resolved_internal"
                    elif imported_name == source_module:
                        continue
                    else:
                        target_id = builder.add_node(
                            node_kind="external_package",
                            path=None,
                            external_name=imported_name.split(".")[0],
                        )
                        resolution = "external"
                    builder.add_relation(
                        source_node_id=source_id,
                        target_node_id=target_id,
                        relation_kind="source_import",
                        observed_name=imported_name,
                        resolution_status=resolution,
                        evidence_path=source_path,
                        line=getattr(node, "lineno", None),
                    )
        return builder.result(len(source_paths))


class _RustAdapter:
    language_id = "rust"
    provider_id = "strixnova.rust-static.v1"
    relation_kinds = ("module_reference", "package_dependency")

    @staticmethod
    def _module_for(path: str, root: str) -> str:
        relative = _relative_to_root(path, root)
        parts = list(relative.with_suffix("").parts)
        if "src" in parts:
            parts = parts[parts.index("src") + 1 :]
        if parts and parts[-1] in {"lib", "main", "mod"}:
            parts.pop()
        return "crate" + ("::" + "::".join(parts) if parts else "")

    @staticmethod
    def _resolve_module(name: str, modules: Mapping[str, str]) -> str | None:
        candidate = name
        while candidate:
            if candidate in modules:
                return modules[candidate]
            candidate = candidate.rpartition("::")[0]
        return None

    def observe(self, reader, scope, paths):
        builder = _ObservationBuilder(
            reader, scope, self.language_id, self.provider_id, self.relation_kinds
        )
        root = scope["root"]
        source_paths = sorted(path for path in paths if path.endswith(".rs"))
        modules = {self._module_for(path, root): path for path in source_paths}
        for path in source_paths:
            builder.source_node(path)
        for source_path in source_paths:
            text = builder.read_text(source_path)
            if text is None:
                continue
            source_module = self._module_for(source_path, root)
            if re.search(r"\b(?:cfg|cfg_attr)!?\s*[\[(]", text):
                builder.limitations.add(
                    "检测到条件编译；未执行配置解析时只能证明声明源码中的保守关系。"
                )
            if re.search(r"\binclude(?:_str|_bytes)?!\s*\(", text):
                builder.add_gap(
                    "rust_include_macro",
                    f"Rust include 宏需要补充展开观察：{source_path}",
                    paths=[source_path],
                    relation_kind="module_reference",
                )
            for match in re.finditer(r"(?m)^\s*mod\s+([A-Za-z_][A-Za-z0-9_]*)\s*;", text):
                name = match.group(1)
                base = PurePosixPath(source_path).parent
                candidates = [
                    (base / f"{name}.rs").as_posix(),
                    (base / name / "mod.rs").as_posix(),
                ]
                target_path = next((item for item in candidates if item in source_paths), None)
                source_id = builder.source_node(source_path)
                if target_path is None:
                    target_id = builder.add_node(
                        node_kind="unresolved_symbol",
                        path=None,
                        external_name=name,
                    )
                    resolution = "unresolved"
                    builder.add_gap(
                        "rust_module_unresolved",
                        f"无法解析 Rust 模块：{source_path} -> {name}",
                        paths=[source_path],
                        relation_kind="module_reference",
                    )
                else:
                    target_id = builder.source_node(target_path)
                    resolution = "resolved_internal"
                builder.add_relation(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    relation_kind="module_reference",
                    observed_name=name,
                    resolution_status=resolution,
                    evidence_path=source_path,
                    line=text.count("\n", 0, match.start()) + 1,
                )
            for match in re.finditer(
                r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?use\s+([^;]+);", text
            ):
                raw_name = match.group(1).strip().split(" as ", 1)[0]
                raw_name = raw_name.split("::{", 1)[0].rstrip(":")
                if raw_name.startswith("crate::"):
                    canonical = raw_name
                elif raw_name.startswith("self::"):
                    canonical = source_module + "::" + raw_name.removeprefix("self::")
                elif raw_name.startswith("super::"):
                    parent = source_module.rpartition("::")[0] or "crate"
                    canonical = parent + "::" + raw_name.removeprefix("super::")
                else:
                    canonical = raw_name
                target_path = self._resolve_module(canonical, modules)
                source_id = builder.source_node(source_path)
                if target_path is not None and target_path != source_path:
                    target_id = builder.source_node(target_path)
                    resolution = "resolved_internal"
                else:
                    target_id = builder.add_node(
                        node_kind="external_package",
                        path=None,
                        external_name=canonical.split("::")[0],
                    )
                    resolution = "external" if not canonical.startswith("crate") else "unresolved"
                    if resolution == "unresolved":
                        builder.add_gap(
                            "rust_use_unresolved",
                            f"无法解析 Rust use：{source_path} -> {raw_name}",
                            paths=[source_path],
                            relation_kind="module_reference",
                        )
                builder.add_relation(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    relation_kind="module_reference",
                    observed_name=raw_name,
                    resolution_status=resolution,
                    evidence_path=source_path,
                    line=text.count("\n", 0, match.start()) + 1,
                )
        for manifest in sorted(path for path in paths if path.endswith("Cargo.toml")):
            text = builder.read_text(manifest)
            if text is None:
                continue
            project_id = builder.add_node(node_kind="project", path=manifest)
            try:
                document = tomllib.loads(text)
            except tomllib.TOMLDecodeError as error:
                builder.add_gap(
                    "cargo_manifest_invalid",
                    f"Cargo.toml 无法解析：{manifest}：{error}",
                    paths=[manifest],
                    relation_kind="package_dependency",
                    fatal=True,
                )
                continue
            dependency_tables = ["dependencies", "dev-dependencies", "build-dependencies"]
            for table_name in dependency_tables:
                table = document.get(table_name, {})
                if not isinstance(table, Mapping):
                    continue
                for dependency, spec in sorted(table.items()):
                    conditions = [table_name]
                    target_path = None
                    if isinstance(spec, Mapping) and isinstance(spec.get("path"), str):
                        candidate = (
                            PurePosixPath(manifest).parent / spec["path"] / "Cargo.toml"
                        )
                        normalized = candidate.as_posix()
                        if normalized in paths:
                            target_path = normalized
                    if target_path:
                        target_id = builder.add_node(node_kind="project", path=target_path)
                        resolution = "resolved_internal"
                    else:
                        target_id = builder.add_node(
                            node_kind="external_package",
                            path=None,
                            external_name=str(dependency),
                        )
                        resolution = "external"
                    builder.add_relation(
                        source_node_id=project_id,
                        target_node_id=target_id,
                        relation_kind="package_dependency",
                        observed_name=str(dependency),
                        resolution_status=resolution,
                        evidence_path=manifest,
                        conditions=conditions,
                    )
            if "workspace" in document:
                builder.limitations.add(
                    "Cargo workspace、feature 和 target 条件需要按明确配置补充解析观察。"
                )
        if any(PurePosixPath(path).name == "build.rs" for path in source_paths):
            builder.limitations.add(
                "检测到 build.rs；内置只读观察不会执行构建脚本。"
            )
        return builder.result(len(source_paths))


class _GoAdapter:
    language_id = "go"
    provider_id = "strixnova.go-static.v1"
    relation_kinds = ("package_import", "module_dependency")

    @staticmethod
    def _manifest_entries(
        text: str,
    ) -> tuple[set[str], dict[str, str]]:
        requirements: set[str] = set()
        replacements: dict[str, str] = {}
        block: str | None = None
        for raw_line in text.splitlines():
            line = raw_line.split("//", 1)[0].strip()
            if not line:
                continue
            if line == ")":
                block = None
                continue
            if line in {"require (", "replace ("}:
                block = line.split()[0]
                continue
            directive = block
            value = line
            if directive is None:
                head, separator, tail = line.partition(" ")
                if head not in {"require", "replace"} or not separator:
                    continue
                directive = head
                value = tail.strip()
            if directive == "require":
                dependency = value.split()[0] if value.split() else ""
                if dependency:
                    requirements.add(dependency)
                continue
            left, separator, right = value.partition("=>")
            if separator:
                source = left.split()[0] if left.split() else ""
                target = right.split()[0] if right.split() else ""
                if source and target:
                    replacements[source] = target
        return requirements, replacements

    @staticmethod
    def _join_repository_path(base: PurePosixPath, value: str) -> str | None:
        normalized = posixpath.normpath((base / value).as_posix())
        try:
            return repository_relative_path(normalized, "Go 本地模块路径")
        except GitProjectReaderError:
            return None

    @staticmethod
    def _module_for_source(
        source_path: str,
        modules: Sequence[Mapping[str, str]],
    ) -> Mapping[str, str] | None:
        source = PurePosixPath(source_path)
        candidates = [
            item
            for item in modules
            if source.parent == PurePosixPath(item["root"])
            or PurePosixPath(item["root"]) in source.parents
        ]
        return max(
            candidates,
            key=lambda item: len(PurePosixPath(item["root"]).parts),
            default=None,
        )

    def observe(self, reader, scope, paths):
        builder = _ObservationBuilder(
            reader, scope, self.language_id, self.provider_id, self.relation_kinds
        )
        source_paths = sorted(path for path in paths if path.endswith(".go"))
        go_mods = sorted(path for path in paths if PurePosixPath(path).name == "go.mod")
        modules: list[dict[str, str]] = []
        manifests: dict[str, tuple[set[str], dict[str, str]]] = {}
        for manifest in go_mods:
            text = builder.read_text(manifest)
            if text is None:
                continue
            match = re.search(r"(?m)^\s*module\s+(\S+)", text)
            if match is None:
                builder.add_gap(
                    "go_module_name_missing",
                    f"go.mod 缺少 module 声明：{manifest}",
                    paths=[manifest],
                    relation_kind="module_dependency",
                    fatal=True,
                )
                continue
            module_name = match.group(1)
            modules.append(
                {
                    "name": module_name,
                    "root": PurePosixPath(manifest).parent.as_posix(),
                    "manifest": manifest,
                }
            )
            manifests[manifest] = self._manifest_entries(text)

        modules_by_name = {item["name"]: item for item in modules}
        if len(modules_by_name) != len(modules):
            builder.add_gap(
                "go_module_name_ambiguous",
                "观察范围内存在重复 Go module 身份",
                paths=go_mods,
                relation_kind="module_dependency",
                fatal=True,
            )
        if source_paths and not modules:
            builder.add_gap(
                "go_module_manifest_missing",
                "Go 源码范围缺少可解析的 go.mod，不能可靠区分内部包与外部包",
                paths=[scope["root"]],
                relation_kind="package_import",
            )

        path_set = set(paths)
        for manifest, (dependencies, replacements) in sorted(manifests.items()):
            project_id = builder.add_node(node_kind="project", path=manifest)
            for dependency in sorted(dependencies):
                internal = modules_by_name.get(dependency)
                replacement = replacements.get(dependency)
                unresolved_local = False
                if replacement and replacement.startswith((".", "/")):
                    candidate_root = self._join_repository_path(
                        PurePosixPath(manifest).parent,
                        replacement,
                    )
                    candidate_manifest = (
                        f"{candidate_root}/go.mod" if candidate_root else None
                    )
                    internal = next(
                        (
                            item
                            for item in modules
                            if item["manifest"] == candidate_manifest
                        ),
                        None,
                    )
                    unresolved_local = internal is None
                if internal is not None:
                    target_id = builder.add_node(
                        node_kind="project",
                        path=internal["manifest"],
                    )
                    resolution = "resolved_internal"
                elif unresolved_local:
                    target_id = builder.add_node(
                        node_kind="unresolved_project",
                        path=None,
                        external_name=replacement,
                    )
                    resolution = "unresolved"
                    builder.add_gap(
                        "go_local_replace_unresolved",
                        f"无法解析 Go 本地 replace：{manifest} -> {replacement}",
                        paths=[manifest],
                        relation_kind="module_dependency",
                    )
                else:
                    target_id = builder.add_node(
                        node_kind="external_package",
                        path=None,
                        external_name=replacement or dependency,
                    )
                    resolution = "external"
                builder.add_relation(
                    source_node_id=project_id,
                    target_node_id=target_id,
                    relation_kind="module_dependency",
                    observed_name=dependency,
                    resolution_status=resolution,
                    evidence_path=manifest,
                    conditions=(
                        [f"replace:{replacement}"] if replacement else []
                    ),
                )

        for workspace in sorted(
            path for path in paths if PurePosixPath(path).name == "go.work"
        ):
            text = builder.read_text(workspace)
            if text is None:
                continue
            use_values: list[str] = []
            use_values.extend(
                match.group(1)
                for match in re.finditer(r"(?m)^\s*use\s+(\S+)", text)
                if match.group(1) != "("
            )
            for block_match in re.finditer(r"(?ms)^\s*use\s*\((.*?)\)", text):
                use_values.extend(
                    line.split("//", 1)[0].strip().split()[0]
                    for line in block_match.group(1).splitlines()
                    if line.split("//", 1)[0].strip()
                )
            for value in use_values:
                root = self._join_repository_path(
                    PurePosixPath(workspace).parent,
                    value,
                )
                manifest = f"{root}/go.mod" if root else None
                if manifest not in path_set:
                    builder.add_gap(
                        "go_workspace_module_unresolved",
                        f"go.work 引用了范围内无法解析的模块：{workspace} -> {value}",
                        paths=[workspace],
                        relation_kind="module_dependency",
                    )

        package_nodes: dict[str, str] = {}
        for path in source_paths:
            builder.source_node(path)
            directory = PurePosixPath(path).parent.as_posix()
            package_nodes[directory] = builder.add_node(
                node_kind="package", path=directory, display_name=directory
            )
        for source_path in source_paths:
            text = builder.read_text(source_path)
            if text is None:
                continue
            conditions: list[str] = []
            if re.search(r"(?m)^\s*//go:build\s+", text):
                conditions.append("go_build_constraint")
                builder.limitations.add(
                    "检测到 Go build tags；需要按目标平台和标签补充配置观察。"
                )
            filename = PurePosixPath(source_path).stem
            filename_parts = filename.split("_")
            if len(filename_parts) > 1 and filename_parts[-1] in {
                "aix", "android", "darwin", "dragonfly", "freebsd", "illumos",
                "ios", "js", "linux", "netbsd", "openbsd", "plan9", "solaris",
                "wasip1", "windows", "386", "amd64", "arm", "arm64", "loong64",
                "mips", "mips64", "mips64le", "mipsle", "ppc64", "ppc64le",
                "riscv64", "s390x", "wasm",
            }:
                conditions.append(f"go_filename_constraint:{filename_parts[-1]}")
                builder.limitations.add(
                    "检测到按平台命名的 Go 源文件；需要按目标平台补充配置观察。"
                )
            imports: list[tuple[str, int]] = []
            for match in re.finditer(r"(?m)^\s*import\s+(?:[._A-Za-z][\w.]*\s+)?\"([^\"]+)\"", text):
                imports.append((match.group(1), text.count("\n", 0, match.start()) + 1))
            for block_match in re.finditer(r"(?ms)^\s*import\s*\((.*?)\)", text):
                block = block_match.group(1)
                for item in re.finditer(r"(?m)^\s*(?:[._A-Za-z][\w.]*\s+)?\"([^\"]+)\"", block):
                    line = text.count("\n", 0, block_match.start() + item.start()) + 1
                    imports.append((item.group(1), line))
            for imported, line in imports:
                source_id = builder.source_node(source_path)
                target_directory = None
                matching_module = next(
                    (
                        item
                        for item in sorted(
                            modules,
                            key=lambda value: len(value["name"]),
                            reverse=True,
                        )
                        if imported == item["name"]
                        or imported.startswith(item["name"] + "/")
                    ),
                    None,
                )
                if matching_module is not None:
                    suffix = imported.removeprefix(
                        matching_module["name"]
                    ).lstrip("/")
                    root_dir = PurePosixPath(matching_module["root"])
                    candidate = (
                        (root_dir / suffix).as_posix()
                        if suffix
                        else root_dir.as_posix()
                    )
                    if candidate in package_nodes:
                        target_directory = candidate
                if target_directory is not None:
                    target_id = package_nodes[target_directory]
                    resolution = "resolved_internal"
                elif matching_module is not None:
                    target_id = builder.add_node(
                        node_kind="unresolved_package",
                        path=None,
                        external_name=imported,
                    )
                    resolution = "unresolved"
                    builder.add_gap(
                        "go_internal_package_unresolved",
                        f"无法解析 Go 内部包：{source_path} -> {imported}",
                        paths=[source_path],
                        relation_kind="package_import",
                    )
                else:
                    target_id = builder.add_node(
                        node_kind="external_package",
                        path=None,
                        external_name=imported,
                    )
                    resolution = "external"
                builder.add_relation(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    relation_kind="package_import",
                    observed_name=imported,
                    resolution_status=resolution,
                    evidence_path=source_path,
                    line=line,
                    conditions=conditions,
                )
            if modules and self._module_for_source(source_path, modules) is None:
                builder.add_gap(
                    "go_source_module_unresolved",
                    f"Go 源文件不属于观察范围内任何 module：{source_path}",
                    paths=[source_path],
                    relation_kind="package_import",
                )
        return builder.result(len(source_paths))


def _strip_json_comments(value: str) -> str:
    without_blocks = re.sub(r"/\*.*?\*/", "", value, flags=re.DOTALL)
    without_lines = re.sub(r"(?m)(?<!:)//.*$", "", without_blocks)
    return re.sub(r",\s*([}\]])", r"\1", without_lines)


class _TypeScriptAdapter:
    language_id = "typescript"
    provider_id = "strixnova.typescript-static.v1"
    relation_kinds = ("source_import", "project_reference", "package_dependency")

    @staticmethod
    def _resolve_relative(source: str, imported: str, paths: set[str]) -> str | None:
        base = PurePosixPath(source).parent / imported
        candidates = [base.as_posix()]
        for suffix in (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs"):
            candidates.append(base.with_suffix(suffix).as_posix())
        for suffix in (".ts", ".tsx", ".js", ".jsx"):
            candidates.append((base / f"index{suffix}").as_posix())
        return next((candidate for candidate in candidates if candidate in paths), None)

    @staticmethod
    def _package_name(imported: str) -> str:
        if imported.startswith("@"):
            return "/".join(imported.split("/")[:2])
        return imported.split("/", 1)[0]

    @staticmethod
    def _resolve_package_subpath(
        package_root: str,
        subpath: str,
        paths: set[str],
    ) -> str | None:
        raw_base = PurePosixPath(package_root) / subpath
        normalized = posixpath.normpath(raw_base.as_posix())
        if normalized == ".." or normalized.startswith("../"):
            return None
        base = PurePosixPath(normalized)
        candidates = [base.as_posix()]
        suffixes = (".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs")
        if base.suffix:
            candidates.extend(
                base.with_suffix(suffix).as_posix() for suffix in suffixes
            )
        else:
            candidates.extend(
                base.with_suffix(suffix).as_posix() for suffix in suffixes
            )
        candidates.extend(
            (base / f"index{suffix}").as_posix() for suffix in suffixes
        )
        return next((candidate for candidate in candidates if candidate in paths), None)

    def observe(self, reader, scope, paths):
        builder = _ObservationBuilder(
            reader, scope, self.language_id, self.provider_id, self.relation_kinds
        )
        source_paths = sorted(
            path for path in paths if PurePosixPath(path).suffix in _SOURCE_EXTENSIONS["typescript"]
        )
        path_set = set(source_paths)
        manifest_paths = sorted(
            path for path in paths if PurePosixPath(path).name == "package.json"
        )
        package_documents: dict[str, Mapping[str, Any]] = {}
        packages_by_name: dict[str, dict[str, str]] = {}
        for manifest in manifest_paths:
            text = builder.read_text(manifest)
            if text is None:
                continue
            try:
                document = json.loads(text)
            except json.JSONDecodeError as error:
                builder.add_gap(
                    "package_json_invalid",
                    f"package.json 无法解析：{manifest}：{error}",
                    paths=[manifest],
                    relation_kind="package_dependency",
                    fatal=True,
                )
                continue
            if not isinstance(document, Mapping):
                builder.add_gap(
                    "package_json_invalid",
                    f"package.json 顶层必须是对象：{manifest}",
                    paths=[manifest],
                    relation_kind="package_dependency",
                    fatal=True,
                )
                continue
            package_documents[manifest] = document
            name = document.get("name")
            if isinstance(name, str) and name.strip():
                if name in packages_by_name:
                    builder.add_gap(
                        "typescript_package_name_ambiguous",
                        f"观察范围内存在重复 package 名称：{name}",
                        paths=[packages_by_name[name]["manifest"], manifest],
                        relation_kind="package_dependency",
                        fatal=True,
                    )
                else:
                    packages_by_name[name] = {
                        "manifest": manifest,
                        "root": PurePosixPath(manifest).parent.as_posix(),
                    }
        for path in source_paths:
            builder.source_node(path)
        patterns = (
            re.compile(r"(?m)\b(?:import|export)\s+(?:[^;\n]*?\s+from\s+)?[\"']([^\"']+)[\"']"),
            re.compile(r"(?m)\brequire\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
            re.compile(r"(?m)\bimport\s*\(\s*[\"']([^\"']+)[\"']\s*\)"),
        )
        for source_path in source_paths:
            text = builder.read_text(source_path)
            if text is None:
                continue
            matched_spans: set[tuple[int, int]] = set()
            for pattern in patterns:
                for match in pattern.finditer(text):
                    if match.span() in matched_spans:
                        continue
                    matched_spans.add(match.span())
                    imported = match.group(1)
                    source_id = builder.source_node(source_path)
                    target_path = (
                        self._resolve_relative(source_path, imported, path_set)
                        if imported.startswith(".")
                        else None
                    )
                    if target_path is not None:
                        target_id = builder.source_node(target_path)
                        resolution = "resolved_internal"
                    elif imported.startswith("."):
                        target_id = builder.add_node(
                            node_kind="unresolved_symbol",
                            path=None,
                            external_name=imported,
                        )
                        resolution = "unresolved"
                        builder.add_gap(
                            "typescript_relative_import_unresolved",
                            f"无法解析 TypeScript 相对导入：{source_path} -> {imported}",
                            paths=[source_path],
                            relation_kind="source_import",
                        )
                    elif not imported.startswith(".") and (
                        package := packages_by_name.get(
                            self._package_name(imported)
                        )
                    ) is not None:
                        package_name = self._package_name(imported)
                        subpath = imported.removeprefix(package_name).lstrip("/")
                        if subpath:
                            target_path = self._resolve_package_subpath(
                                package["root"],
                                subpath,
                                path_set,
                            )
                        if target_path is not None:
                            target_id = builder.source_node(target_path)
                            resolution = "resolved_internal"
                        elif not subpath:
                            target_id = builder.add_node(
                                node_kind="package",
                                path=package["root"],
                                display_name=package_name,
                            )
                            resolution = "resolved_internal"
                        else:
                            target_id = builder.add_node(
                                node_kind="unresolved_package",
                                path=None,
                                external_name=imported,
                            )
                            resolution = "unresolved"
                            builder.add_gap(
                                "typescript_workspace_subpath_unresolved",
                                "无法解析 TypeScript 工作区包子路径："
                                f"{source_path} -> {imported}",
                                paths=[source_path],
                                relation_kind="source_import",
                            )
                    else:
                        target_id = builder.add_node(
                            node_kind="external_package",
                            path=None,
                            external_name=self._package_name(imported),
                        )
                        resolution = "external"
                    builder.add_relation(
                        source_node_id=source_id,
                        target_node_id=target_id,
                        relation_kind="source_import",
                        observed_name=imported,
                        resolution_status=resolution,
                        evidence_path=source_path,
                        line=text.count("\n", 0, match.start()) + 1,
                    )
            if re.search(r"\b(?:import|require)\s*\(\s*(?![\"'])", text):
                builder.add_gap(
                    "typescript_dynamic_import",
                    f"检测到非字面量动态导入：{source_path}",
                    paths=[source_path],
                    relation_kind="source_import",
                )
        for manifest in manifest_paths:
            document = package_documents.get(manifest)
            if document is None:
                continue
            project_id = builder.add_node(node_kind="project", path=manifest)
            for table_name in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                table = document.get(table_name, {})
                if not isinstance(table, Mapping):
                    continue
                for dependency in sorted(table):
                    internal_package = packages_by_name.get(str(dependency))
                    if internal_package is not None:
                        target_id = builder.add_node(
                            node_kind="project",
                            path=internal_package["manifest"],
                        )
                        resolution = "resolved_internal"
                    else:
                        target_id = builder.add_node(
                            node_kind="external_package",
                            path=None,
                            external_name=str(dependency),
                        )
                        resolution = "external"
                    builder.add_relation(
                        source_node_id=project_id,
                        target_node_id=target_id,
                        relation_kind="package_dependency",
                        observed_name=str(dependency),
                        resolution_status=resolution,
                        evidence_path=manifest,
                        conditions=[table_name],
                    )
        for config in sorted(path for path in paths if PurePosixPath(path).name.startswith("tsconfig") and path.endswith(".json")):
            text = builder.read_text(config)
            if text is None:
                continue
            project_id = builder.add_node(node_kind="project", path=config)
            try:
                document = json.loads(_strip_json_comments(text))
            except json.JSONDecodeError as error:
                builder.add_gap(
                    "tsconfig_invalid",
                    f"tsconfig 无法静态解析：{config}：{error}",
                    paths=[config],
                    relation_kind="project_reference",
                    fatal=True,
                )
                continue
            compiler_options = document.get("compilerOptions", {})
            if isinstance(compiler_options, Mapping) and compiler_options.get("paths"):
                builder.limitations.add(
                    "检测到 TypeScript paths 映射；未运行编译器解析时非相对导入保持外部观察。"
                )
            for reference in document.get("references", []) or []:
                if not isinstance(reference, Mapping) or not isinstance(reference.get("path"), str):
                    continue
                base = PurePosixPath(config).parent / reference["path"]
                candidates = [base.as_posix(), (base / "tsconfig.json").as_posix()]
                target_path = next((candidate for candidate in candidates if candidate in paths), None)
                if target_path:
                    target_id = builder.add_node(node_kind="project", path=target_path)
                    resolution = "resolved_internal"
                else:
                    target_id = builder.add_node(
                        node_kind="unresolved_project",
                        path=None,
                        external_name=reference["path"],
                    )
                    resolution = "unresolved"
                    builder.add_gap(
                        "typescript_project_reference_unresolved",
                        f"无法解析 TypeScript 项目引用：{config} -> {reference['path']}",
                        paths=[config],
                        relation_kind="project_reference",
                    )
                builder.add_relation(
                    source_node_id=project_id,
                    target_node_id=target_id,
                    relation_kind="project_reference",
                    observed_name=reference["path"],
                    resolution_status=resolution,
                    evidence_path=config,
                )
        return builder.result(len(source_paths))


class _CSharpAdapter:
    language_id = "csharp"
    provider_id = "strixnova.csharp-static.v1"
    relation_kinds = ("namespace_reference", "project_reference", "package_dependency")

    def observe(self, reader, scope, paths):
        builder = _ObservationBuilder(
            reader, scope, self.language_id, self.provider_id, self.relation_kinds
        )
        source_paths = sorted(path for path in paths if path.endswith(".cs"))
        project_paths = set(path for path in paths if path.endswith(".csproj"))
        for path in source_paths:
            builder.source_node(path)
        for source_path in source_paths:
            text = builder.read_text(source_path)
            if text is None:
                continue
            for match in re.finditer(
                r"(?m)^\s*(?:global\s+)?using\s+(?:static\s+)?(?:[A-Za-z_][\w]*\s*=\s*)?([A-Za-z_][\w.]*)\s*;",
                text,
            ):
                namespace = match.group(1)
                target_id = builder.add_node(
                    node_kind="external_namespace", path=None, external_name=namespace
                )
                builder.add_relation(
                    source_node_id=builder.source_node(source_path),
                    target_node_id=target_id,
                    relation_kind="namespace_reference",
                    observed_name=namespace,
                    resolution_status="external",
                    evidence_path=source_path,
                    line=text.count("\n", 0, match.start()) + 1,
                )
        for project in sorted(project_paths):
            text = builder.read_text(project)
            if text is None:
                continue
            project_id = builder.add_node(node_kind="project", path=project)
            try:
                root = ET.fromstring(text)
            except ET.ParseError as error:
                builder.add_gap(
                    "csproj_invalid",
                    f"C# 项目文件无法解析：{project}：{error}",
                    paths=[project],
                    relation_kind="project_reference",
                    fatal=True,
                )
                continue
            if any(element.get("Condition") for element in root.iter()):
                builder.limitations.add(
                    "检测到 MSBuild Condition；内置静态观察不会求值具体配置。"
                )
            for element in root.iter():
                tag = element.tag.rsplit("}", 1)[-1]
                if tag == "ProjectReference" and element.get("Include"):
                    observed = element.get("Include", "").replace("\\", "/")
                    candidate = (PurePosixPath(project).parent / observed).as_posix()
                    if candidate in project_paths:
                        target_id = builder.add_node(node_kind="project", path=candidate)
                        resolution = "resolved_internal"
                    else:
                        target_id = builder.add_node(
                            node_kind="unresolved_project", path=None, external_name=observed
                        )
                        resolution = "unresolved"
                        builder.add_gap(
                            "csharp_project_reference_unresolved",
                            f"无法解析 C# 项目引用：{project} -> {observed}",
                            paths=[project],
                            relation_kind="project_reference",
                        )
                    builder.add_relation(
                        source_node_id=project_id,
                        target_node_id=target_id,
                        relation_kind="project_reference",
                        observed_name=observed,
                        resolution_status=resolution,
                        evidence_path=project,
                        conditions=[element.get("Condition")]
                        if element.get("Condition")
                        else [],
                    )
                elif tag == "PackageReference" and element.get("Include"):
                    package = element.get("Include", "")
                    target_id = builder.add_node(
                        node_kind="external_package", path=None, external_name=package
                    )
                    builder.add_relation(
                        source_node_id=project_id,
                        target_node_id=target_id,
                        relation_kind="package_dependency",
                        observed_name=package,
                        resolution_status="external",
                        evidence_path=project,
                    )
        builder.limitations.add(
            "using 指令只证明命名空间引用；类型绑定、生成源码和条件项目图需要 Roslyn/MSBuild 授权观察。"
        )
        return builder.result(len(source_paths))


class _CppAdapter:
    language_id = "cpp"
    provider_id = "strixnova.cpp-static.v1"
    relation_kinds = ("source_include", "build_target_dependency")

    def observe(self, reader, scope, paths):
        builder = _ObservationBuilder(
            reader, scope, self.language_id, self.provider_id, self.relation_kinds
        )
        source_paths = sorted(
            path for path in paths if PurePosixPath(path).suffix in _SOURCE_EXTENSIONS["cpp"]
        )
        path_set = set(source_paths)
        for path in source_paths:
            builder.source_node(path)
        for source_path in source_paths:
            text = builder.read_text(source_path)
            if text is None:
                continue
            conditions: list[str] = []
            if re.search(r"(?m)^\s*#\s*(?:if|ifdef|ifndef|elif)\b", text):
                conditions.append("preprocessor_condition")
                builder.limitations.add(
                    "检测到预处理条件；未运行编译器时只能证明声明源码中的保守 include 关系。"
                )
            for match in re.finditer(r"(?m)^\s*#\s*include\s*([<\"])([^>\"]+)[>\"]", text):
                delimiter, imported = match.groups()
                source_id = builder.source_node(source_path)
                target_path = None
                if delimiter == '"':
                    candidates = [
                        (PurePosixPath(source_path).parent / imported).as_posix(),
                        (PurePosixPath(scope["root"]) / imported).as_posix(),
                    ]
                    target_path = next((candidate for candidate in candidates if candidate in path_set), None)
                if target_path:
                    target_id = builder.source_node(target_path)
                    resolution = "resolved_internal"
                elif delimiter == '"':
                    target_id = builder.add_node(
                        node_kind="unresolved_header", path=None, external_name=imported
                    )
                    resolution = "unresolved"
                    builder.add_gap(
                        "cpp_include_unresolved",
                        f"无法在声明范围解析 C/C++ include：{source_path} -> {imported}",
                        paths=[source_path],
                        relation_kind="source_include",
                    )
                else:
                    target_id = builder.add_node(
                        node_kind="external_header", path=None, external_name=imported
                    )
                    resolution = "external"
                builder.add_relation(
                    source_node_id=source_id,
                    target_node_id=target_id,
                    relation_kind="source_include",
                    observed_name=imported,
                    resolution_status=resolution,
                    evidence_path=source_path,
                    line=text.count("\n", 0, match.start()) + 1,
                    conditions=conditions,
                )
            if re.search(r"(?m)^\s*#\s*include\s+(?![<\"])", text):
                builder.add_gap(
                    "cpp_macro_include",
                    f"检测到宏形式 include：{source_path}",
                    paths=[source_path],
                    relation_kind="source_include",
                )
        cmake_paths = sorted(
            path for path in paths if PurePosixPath(path).name == "CMakeLists.txt"
        )
        declared_targets: dict[str, str] = {}
        cmake_texts: dict[str, str] = {}
        for cmake in cmake_paths:
            text = builder.read_text(cmake)
            if text is None:
                continue
            cmake_texts[cmake] = re.sub(r"(?m)#.*$", "", text)
            for match in re.finditer(
                r"(?is)\b(?:add_library|add_executable)\s*\(\s*([^\s)]+)",
                cmake_texts[cmake],
            ):
                target = match.group(1)
                declared_targets[target] = builder.add_node(
                    node_kind="build_target",
                    path=cmake,
                    display_name=target,
                    identity_key=f"{cmake}#target:{target}",
                )
        for cmake, text in cmake_texts.items():
            for match in re.finditer(
                r"(?is)\btarget_link_libraries\s*\(\s*([^\s)]+)\s+(.*?)\)",
                text,
            ):
                source_target = match.group(1)
                source_id = declared_targets.get(source_target) or builder.add_node(
                    node_kind="unresolved_build_target",
                    path=None,
                    external_name=source_target,
                )
                tokens = re.findall(r"[^\s;]+", match.group(2))
                for dependency in tokens:
                    if dependency.upper() in {"PUBLIC", "PRIVATE", "INTERFACE", "DEBUG", "OPTIMIZED", "GENERAL"}:
                        continue
                    if dependency.startswith("$"):
                        builder.add_gap(
                            "cmake_generator_expression",
                            f"CMake 生成器表达式需要配置解析：{cmake} -> {dependency}",
                            paths=[cmake],
                            relation_kind="build_target_dependency",
                        )
                        target_id = builder.add_node(
                            node_kind="unresolved_build_target",
                            path=None,
                            external_name=dependency,
                        )
                        resolution = "unresolved"
                    elif dependency in declared_targets:
                        target_id = declared_targets[dependency]
                        resolution = "resolved_internal"
                    else:
                        target_id = builder.add_node(
                            node_kind="external_library",
                            path=None,
                            external_name=dependency,
                        )
                        resolution = "external"
                    builder.add_relation(
                        source_node_id=source_id,
                        target_node_id=target_id,
                        relation_kind="build_target_dependency",
                        observed_name=dependency,
                        resolution_status=resolution,
                        evidence_path=cmake,
                        line=text.count("\n", 0, match.start()) + 1,
                    )
        builder.limitations.add(
            "内置 C/C++ 观察不执行预处理器或构建系统；完整目标图需要按平台、工具链和配置授权解析。"
        )
        return builder.result(len(source_paths))


_ADAPTERS = {
    adapter.language_id: adapter
    for adapter in (
        _PythonAdapter(),
        _RustAdapter(),
        _GoAdapter(),
        _TypeScriptAdapter(),
        _CSharpAdapter(),
        _CppAdapter(),
    )
}


def implementation_observation_capabilities() -> dict[str, Any]:
    """Return declared built-in capabilities without claiming project coverage."""

    return {
        "schema_version": "strixnova.implementation-observation-capabilities.v1",
        "provider_contract_version": IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA,
        "languages": [
            {
                "language_id": language_id,
                "provider_id": adapter.provider_id,
                "provider_version": "1",
                "execution_mode": "builtin_static",
                "relation_kinds": sorted(adapter.relation_kinds),
                "complete_project_semantics_without_configuration": False,
            }
            for language_id, adapter in sorted(_ADAPTERS.items())
        ],
        "semantic_content_machine_proven": False,
    }


def observe_implementation(
    project_dir: str | Path,
    observation_scopes: Sequence[Mapping[str, Any]],
    *,
    observed_ref: str | None = None,
    shared_reader: GitProjectReader | None = None,
    external_providers: Sequence[ExternalObservationProvider] = (),
    external_execution_authorized: bool = False,
) -> dict[str, Any]:
    """Observe one exact implementation snapshot through the public seam."""

    scopes = _normalize_scopes(observation_scopes)
    providers = _normalize_external_providers(external_providers)
    planned_keys = {
        (scope["scope_id"], language_id)
        for scope in scopes
        for language_id in scope["languages"]
    }
    unused_provider_keys = sorted(set(providers) - planned_keys)
    if unused_provider_keys:
        raise ImplementationObservationError(
            [
                "外部观察提供者不属于本次观察计划："
                + ", ".join(f"{scope_id}/{language}" for scope_id, language in unused_provider_keys)
            ]
        )
    try:
        reader = project_reader_for_scope(
            project_dir,
            observed_ref=observed_ref,
            shared_reader=shared_reader,
        )
    except GitProjectReaderError as error:
        raise ImplementationObservationError([str(error)]) from error
    nodes: dict[str, dict[str, Any]] = {}
    relations: dict[str, dict[str, Any]] = {}
    coverage: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    observed_paths: dict[str, str] = {}
    for scope in scopes:
        try:
            root_exists = reader.path_scope_exists(scope["root"])
            scope_paths = (
                [
                    path
                    for path in reader.tracked_paths(scope["root"])
                    if not _is_excluded(
                        path,
                        scope["root"],
                        scope["exclusions"],
                    )
                ]
                if root_exists
                else []
            )
        except GitProjectReaderError as error:
            root_exists = False
            scope_paths = []
            root_error = str(error)
        else:
            root_error = f"实现观察范围不存在：{scope['root']}"
        for language_id in scope["languages"]:
            external_provider = providers.get((scope["scope_id"], language_id))
            if external_provider is not None:
                if not root_exists:
                    provider_result = _external_provider_failure(
                        scope,
                        external_provider,
                        status="failed",
                        execution_mode="not_run",
                        code="observation_scope_unavailable",
                        message=root_error,
                        expected_source_count=0,
                    )
                else:
                    provider_result = _observe_external_provider(
                        reader,
                        scope,
                        scope_paths,
                        external_provider,
                        execution_authorized=external_execution_authorized,
                    )
                for node in provider_result["nodes"]:
                    nodes[node["node_id"]] = node
                for relation in provider_result["relations"]:
                    relations[relation["relation_id"]] = relation
                coverage.append(provider_result["coverage"])
                observed_paths.update(provider_result["observed_paths"])
                receipts.append(provider_result["receipt"])
                continue
            adapter = _ADAPTERS.get(language_id)
            if adapter is None:
                item = {
                    "scope_id": scope["scope_id"],
                    "language_id": language_id,
                    "provider_id": None,
                    "provider_version": None,
                    "status": "unavailable",
                    "execution_mode": "not_run",
                    "configurations": list(scope["configurations"]),
                    "required_relation_kinds": list(
                        scope["required_relation_kinds"]
                    ),
                    "supported_relation_kinds": [],
                    "observed_relation_kinds": [],
                    "source_file_count": 0,
                    "relation_count": 0,
                    "limitations": [],
                    "gaps": [
                        {
                            "code": "language_provider_unavailable",
                            "message": f"没有声明 {language_id} 的实现观察提供者",
                            "paths": [scope["root"]],
                            "relation_kind": None,
                        }
                    ],
                }
                coverage.append(item)
                receipts.append(
                    {
                        "scope_id": scope["scope_id"],
                        "language_id": language_id,
                        "provider_id": None,
                        "provider_version": None,
                        "execution_mode": "not_run",
                        "status": "unavailable",
                        "result_sha256": _canonical_hash(item),
                    }
                )
                continue
            if not root_exists:
                item = {
                    "scope_id": scope["scope_id"],
                    "language_id": language_id,
                    "provider_id": adapter.provider_id,
                    "provider_version": "1",
                    "status": "failed",
                    "execution_mode": "builtin_static",
                    "configurations": list(scope["configurations"]),
                    "required_relation_kinds": list(
                        scope["required_relation_kinds"]
                    ),
                    "supported_relation_kinds": sorted(adapter.relation_kinds),
                    "observed_relation_kinds": [],
                    "source_file_count": 0,
                    "relation_count": 0,
                    "limitations": [],
                    "gaps": [
                        {
                            "code": "observation_scope_unavailable",
                            "message": root_error,
                            "paths": [scope["root"]],
                            "relation_kind": None,
                        }
                    ],
                }
                coverage.append(item)
                receipts.append(
                    {
                        "scope_id": scope["scope_id"],
                        "language_id": language_id,
                        "provider_id": adapter.provider_id,
                        "provider_version": "1",
                        "execution_mode": "builtin_static",
                        "status": "failed",
                        "result_sha256": _canonical_hash(item),
                    }
                )
                continue
            provider_result = adapter.observe(reader, scope, scope_paths)
            for node in provider_result["nodes"]:
                nodes[node["node_id"]] = node
            for relation in provider_result["relations"]:
                relations[relation["relation_id"]] = relation
            coverage.append(provider_result["coverage"])
            observed_paths.update(provider_result["observed_paths"])
            receipts.append(
                {
                    "scope_id": scope["scope_id"],
                    "language_id": language_id,
                    "provider_id": adapter.provider_id,
                    "provider_version": "1",
                    "execution_mode": "builtin_static",
                    "status": provider_result["coverage"]["status"],
                    "result_sha256": _canonical_hash(
                        {
                            "nodes": provider_result["nodes"],
                            "relations": provider_result["relations"],
                            "coverage": provider_result["coverage"],
                            "observed_paths": provider_result["observed_paths"],
                        }
                    ),
                }
            )
    coverage.sort(key=lambda item: (item["scope_id"], item["language_id"]))
    receipts.sort(key=lambda item: (item["scope_id"], item["language_id"]))
    overall_status = max(
        (item["status"] for item in coverage),
        key=_STATUS_PRIORITY.__getitem__,
    )
    source_manifest_sha256 = _canonical_hash(observed_paths)
    observed_revision = reader.observed_commit or "working_tree"
    snapshot_content = {
        "scopes": scopes,
        "nodes": sorted(nodes.values(), key=lambda item: item["node_id"]),
        "relations": sorted(
            relations.values(), key=lambda item: item["relation_id"]
        ),
        "coverage": coverage,
        "provider_receipts": receipts,
        "observed_paths": dict(sorted(observed_paths.items())),
        "source_manifest_sha256": source_manifest_sha256,
    }
    return {
        "schema_version": IMPLEMENTATION_OBSERVATION_SCHEMA,
        "observed_revision": observed_revision,
        **snapshot_content,
        "overall_coverage_status": overall_status,
        "observation_snapshot_sha256": _canonical_hash(snapshot_content),
        "semantic_content_machine_proven": False,
    }


def observe_project_implementation(
    repository_readers: Mapping[str | None, GitProjectReader],
    observation_scopes: Sequence[Mapping[str, Any]],
    *,
    external_providers: Sequence[ExternalObservationProvider] = (),
    external_execution_authorized: bool = False,
) -> dict[str, Any]:
    """Combine repository observations, retaining each native provider receipt.

    No dependency across repositories is inferred merely from equal file names.
    Every current project uses this composition, including a one-member project.
    """
    from strixnova.project_content_snapshot import repository_path_key

    identifiers = [scope.get("scope_id") for scope in observation_scopes]
    if len(set(identifiers)) != len(identifiers):
        raise ImplementationObservationError(["Project observation scope identities must be unique"])
    grouped: dict[str | None, list[dict[str, Any]]] = {}
    for scope in observation_scopes:
        identifier = scope.get("repository_id")
        if "repository_id" not in scope and len(repository_readers) == 1:
            identifier = next(iter(repository_readers))
        if identifier not in repository_readers:
            raise ImplementationObservationError([f"Observation repository is not explicitly available: {identifier}"])
        grouped.setdefault(identifier, []).append(dict(scope))
    components = []
    nodes, relations, coverage, receipts, scopes = [], [], [], [], []
    paths = {}
    for identifier, selected_scopes in sorted(grouped.items(), key=lambda item: str(item[0])):
        reader = repository_readers[identifier]
        if reader.repository_id is not None and reader.repository_id != identifier:
            raise ImplementationObservationError(["Observation reader repository identity does not match its selected scope"])
        scope_ids = {scope["scope_id"] for scope in selected_scopes}
        native = observe_implementation(
            reader.project, selected_scopes, shared_reader=reader,
            external_providers=[provider for provider in external_providers if provider.scope_id in scope_ids],
            external_execution_authorized=external_execution_authorized,
        )
        components.append({"repository_id": identifier, "observation": native})
        nodes.extend({**entry, "repository_id": identifier} for entry in native["nodes"])
        relations.extend({**entry, "repository_id": identifier} for entry in native["relations"])
        coverage.extend({**entry, "repository_id": identifier} for entry in native["coverage"])
        receipts.extend({**entry, "repository_id": identifier} for entry in native["provider_receipts"])
        scopes.extend({**entry, "repository_id": identifier} for entry in native["scopes"])
        paths.update({repository_path_key(identifier, path): digest for path, digest in native["observed_paths"].items()})
    content = {
        "scopes": scopes, "nodes": nodes, "relations": relations,
        "coverage": coverage, "provider_receipts": receipts,
        "observed_paths": paths, "source_manifest_sha256": _canonical_hash(paths),
        "repository_observations": components,
    }
    return {
        "schema_version": "strixnova.project-implementation-observation.v1", **content,
        "overall_coverage_status": max((entry["status"] for entry in coverage), key=_STATUS_PRIORITY.__getitem__, default="unavailable"),
        "observation_snapshot_sha256": _canonical_hash({key: value for key, value in content.items() if key != "repository_observations"}),
        "semantic_content_machine_proven": False,
    }


__all__ = [
    "ExternalObservationProvider",
    "ExternalProviderMaterial",
    "IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA",
    "IMPLEMENTATION_OBSERVATION_SCHEMA",
    "ImplementationObservationError",
    "external_observation_providers_from_plans",
    "implementation_observation_capabilities",
    "observe_implementation",
    "observe_project_implementation",
]
