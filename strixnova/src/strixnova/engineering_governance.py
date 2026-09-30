"""Coding-agent-authored semantics with deterministic governance checks."""

from __future__ import annotations
from strixnova.verification_dependencies import normalize_dependency_checks

from strixnova.project_context import ProjectContextError
from strixnova.project_repository_scope import qualify_candidate, scope_for_candidate, repository_key

from collections.abc import Mapping, Sequence
from copy import deepcopy
import math
import json
from pathlib import Path, PurePosixPath
import re
from typing import Any

from strixnova.behavior_examples import BehaviorExampleError, example_catalog, example_parents
from strixnova.test_case_evidence import TestCaseEvidenceError, merge_configs, normalize_config
from strixnova.engineering_change_planning import (
    ChangePlanningError,
    compile_implementation_slices,
    validate_change_planning,
)
from strixnova.verification_targets import VerificationTargetError, compile_targets, validate_reviews


# The governance contract mirrors the packaged schema and the execution
# supervisor's independent safety ceiling. Keeping the values local avoids a
# domain-to-infrastructure dependency; contract tests bind all three surfaces.
_MAX_PROVIDER_INPUT_BYTES = 64 * 1024 * 1024
_MAX_PROVIDER_OUTPUT_BYTES = 256 * 1024 * 1024

ASSESSMENT_SCHEMA = "strixnova.engineering-assessment.v1"
PLAN_SCHEMA = "strixnova.engineering-plan.v1"
DIRECTION_SCHEMA = "strixnova.direction-decision.v1"
VERIFICATION_POLICY_DECISION_SCHEMA = (
    "strixnova.verification-policy-decision.v1"
)
_DEFAULT_FORBIDDEN_AGENT_PROGRAM_NAMES = (
    "aider",
    "claude",
    "codex",
    "cursor",
    "gemini",
    "opencode",
    "windsurf",
)
_OPAQUE_COMMAND_WRAPPER_NAMES = frozenset(
    {
        "bash",
        "cmd",
        "env",
        "fish",
        "powershell",
        "pwsh",
        "sh",
        "wsl",
        "zsh",
    }
)
RUN_KINDS = frozenset(
    {
        "targeted_test",
        "integration_test",
        "acceptance_test",
        "typecheck",
        "build",
        "lint",
        "manual_check",
        "full_regression",
    }
)

IMPACT_DIMENSIONS = (
    "user_behavior",
    "product_scope",
    "domain",
    "architecture",
    "interface",
    "data",
    "security_privacy",
    "quality_performance",
    "operations_deployment",
    "compatibility_migration",
    "testing",
    "documentation_support",
)

INFORMATION_KINDS = (
    "requirement",
    "acceptance",
    "constraint",
    "impact",
    "risk",
    "option",
    "design",
    "operation",
    "verification",
    "delivery",
    "adr_candidate",
    "unknown",
)

BANDS = ("A0", "A1", "A2", "A3", "A4")
ARTIFACT_TYPES = frozenset(
    {
        "adr",
        "architecture",
        "domain_model",
        "domain_alignment",
        "interface",
        "data_policy",
        "quality_policy",
        "test_policy",
        "security_policy",
        "release_policy",
        "operations_policy",
        "maintenance_policy",
        "glossary",
        "product_governance",
        "engineering_assurance",
    }
)
_CORE_AUTHORITY_KIND_BY_ARTIFACT_TYPE = {
    "product_governance": "product_definition",
    "domain_model": "domain_model",
    "architecture": "target_architecture",
    "quality_policy": "engineering_policy",
    "domain_alignment": "implementation_alignment",
}
_CORE_AUTHORITY_ID_PATTERNS = {
    "product_definition": re.compile(r"^PRODUCT-[0-9A-F]{16}$"),
    "domain_model": re.compile(r"^MODEL-[0-9A-F]{16}$"),
    "target_architecture": re.compile(r"^ARCH-[0-9A-F]{16}$"),
    "engineering_policy": re.compile(r"^POLICY-[0-9A-F]{16}$"),
    "implementation_alignment": re.compile(r"^ALIGNMODEL-[0-9A-F]{16}$"),
}
_BAND_INDEX = {band: index for index, band in enumerate(BANDS)}
_FORBIDDEN_REPOSITORY_ROOTS = frozenset({".git", ".strixnova"})
_OBSERVATION_LANGUAGE_ALIASES = {
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
_DIRECTION_ITEM_SPECS = (
    (
        "scope",
        "requirement_id",
        "direction.requirement",
        re.compile(r"^DIRREQ-[0-9A-F]{16}$"),
    ),
    (
        "constraints",
        "constraint_id",
        "direction.constraint",
        re.compile(r"^DIRCON-[0-9A-F]{16}$"),
    ),
    (
        "acceptance",
        "acceptance_id",
        "direction.acceptance",
        re.compile(r"^DIRACC-[0-9A-F]{16}$"),
    ),
)


class EngineeringGovernanceError(ValueError):
    """An assessment, profile, policy result, or trace is invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "工程治理输入无效")


def _direction_target_refs(
    direction: Mapping[str, Any],
    issues: list[str],
) -> dict[str, set[str]]:
    refs = {
        "requirements": set(),
        "constraints": set(),
        "acceptance": set(),
    }
    if direction.get("schema_version") != DIRECTION_SCHEMA:
        issues.append(f"current_direction.schema_version 必须是 {DIRECTION_SCHEMA}")
    result_keys = ("requirements", "constraints", "acceptance")
    for result_key, (field, identifier_field, prefix, pattern) in zip(
        result_keys,
        _DIRECTION_ITEM_SPECS,
        strict=True,
    ):
        values = direction.get(field)
        if not isinstance(values, list):
            issues.append(f"current_direction.{field} 必须是方向条目数组")
            continue
        for index, value in enumerate(values):
            path = f"current_direction.{field}[{index}].{identifier_field}"
            if not isinstance(value, Mapping):
                issues.append(f"current_direction.{field}[{index}] 必须是对象")
                continue
            identifier = value.get(identifier_field)
            if not isinstance(identifier, str) or pattern.fullmatch(identifier) is None:
                issues.append(f"{path} 格式无效")
                continue
            reference = f"{prefix}:{identifier}"
            if reference in refs[result_key]:
                issues.append(f"current_direction.{field} 身份重复：{identifier}")
                continue
            refs[result_key].add(reference)
    return refs


def _unsafe_repository_path(path: PurePosixPath, raw: str) -> bool:
    return (
        not raw
        or path.is_absolute()
        or path.as_posix() == "."
        or ".." in path.parts
        or ":" in raw
        or bool(path.parts and path.parts[0].casefold() in _FORBIDDEN_REPOSITORY_ROOTS)
    )


def _text(
    value: Any,
    path: str,
    issues: list[str],
) -> str:
    if not isinstance(value, str):
        issues.append(f"{path} 必须是字符串")
        return ""
    normalized = value.strip()
    if not normalized:
        issues.append(f"{path} 不能为空")
        return ""
    return normalized


def _list(
    value: Any,
    path: str,
    issues: list[str],
) -> list[Any]:
    if not isinstance(value, list):
        issues.append(f"{path} 必须是数组")
        return []
    return value


def _enum(
    value: Any,
    path: str,
    allowed: Sequence[str] | set[str] | frozenset[str],
    issues: list[str],
) -> str:
    normalized = _text(value, path, issues)
    vocabulary = frozenset(allowed)
    if normalized and normalized not in vocabulary:
        issues.append(
            f"{path} 必须是 " + "、".join(sorted(vocabulary)) + " 之一"
        )
        return ""
    return normalized


def _boolean(value: Any, path: str, issues: list[str]) -> bool:
    if type(value) is not bool:
        issues.append(f"{path} 必须是布尔值")
        return False
    return value


def _integer(
    value: Any,
    path: str,
    issues: list[str],
    *,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    if type(value) is not int:
        issues.append(f"{path} 必须是整数")
        return 0
    if minimum is not None and value < minimum:
        issues.append(f"{path} 必须大于或等于 {minimum}")
        return 0
    if maximum is not None and value > maximum:
        issues.append(f"{path} 必须小于或等于 {maximum}")
        return 0
    return value


def _number(
    value: Any,
    path: str,
    issues: list[str],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        issues.append(f"{path} 必须是数字")
        return 0
    if isinstance(value, float) and not math.isfinite(value):
        issues.append(f"{path} 必须是有限数字")
        return 0
    if minimum is not None and (
        value <= minimum if exclusive_minimum else value < minimum
    ):
        qualifier = "大于" if exclusive_minimum else "大于或等于"
        issues.append(f"{path} 必须{qualifier} {minimum:g}")
        return 0
    if maximum is not None and value > maximum:
        issues.append(f"{path} 必须小于或等于 {maximum:g}")
        return 0
    return value


def _string_list(
    value: Any,
    path: str,
    issues: list[str],
    *,
    required: bool = False,
    unique: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        issues.append(f"{path} 必须是数组")
        return []
    normalized = [
        _text(item, f"{path}[{index}]", issues)
        for index, item in enumerate(value)
    ]
    if required and not normalized:
        issues.append(f"{path} 不能为空")
    if unique and len(set(normalized)) != len(normalized):
        issues.append(f"{path} 不能包含重复值")
    return normalized


def _check_fields(
    value: Mapping[str, Any],
    *,
    required: set[str],
    optional: set[str] = frozenset(),
    path: str,
    issues: list[str],
) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required - optional)
    if missing:
        issues.append(f"{path} 缺少字段：" + ", ".join(missing))
    if extra:
        issues.append(f"{path} 包含未知字段：" + ", ".join(extra))


def _source_reference(
    value: Any,
    index: int,
    code_facts: Mapping[str, Any],
    issues: list[str],
) -> dict[str, Any] | None:
    path_label = f"source_references[{index}]"
    if not isinstance(value, Mapping):
        issues.append(f"{path_label} 必须是对象")
        return None
    _check_fields(
        value,
        required={
            "reference_id",
            "path",
            "observed_ref",
            "epistemic_status",
        },
        optional={"line_start", "line_end", "repository_id"},
        path=path_label,
        issues=issues,
    )
    reference_id = _text(
        value.get("reference_id"),
        f"{path_label}.reference_id",
        issues,
    )
    raw_path = _text(value.get("path"), f"{path_label}.path", issues)
    epistemic_status = _enum(
        value.get("epistemic_status"),
        f"{path_label}.epistemic_status",
        {"observed", "inferred", "unknown"},
        issues,
    )
    observed_ref = _text(
        value.get("observed_ref"),
        f"{path_label}.observed_ref",
        issues,
    )
    resolved_observed_ref = observed_ref
    normalized_path = ""
    if raw_path:
        candidate = PurePosixPath(raw_path.replace("\\", "/"))
        if _unsafe_repository_path(candidate, raw_path):
            issues.append(f"{path_label}.path 必须是仓库内相对路径")
        else:
            normalized_path = candidate.as_posix()
    line_count: int | None = None
    prepared_sources = code_facts.get("source_references")
    prepared = (
        prepared_sources[index]
        if isinstance(prepared_sources, list)
        and index < len(prepared_sources)
        and isinstance(prepared_sources[index], Mapping)
        else None
    )
    if prepared is None:
        issues.append(f"{path_label} 缺少可信代码事实")
    else:
        current_ref = value.get("observed_ref")
        if prepared.get("repository_id") != value.get("repository_id") or prepared.get("requested_path") != value.get("path") or current_ref not in {
            prepared.get("requested_ref"),
            prepared.get("resolved_ref"),
        }:
            issues.append(f"{path_label} 与可信代码事实不匹配")
        prepared_issues = prepared.get("issues")
        if isinstance(prepared_issues, list):
            issues.extend(
                f"{path_label}: {item}" for item in prepared_issues
            )
        prepared_path = prepared.get("normalized_path")
        if normalized_path and prepared_path != normalized_path:
            issues.append(f"{path_label}.path 与可信代码事实不一致")
        resolved = prepared.get("resolved_ref")
        if isinstance(resolved, str) and resolved:
            resolved_observed_ref = resolved
        if normalized_path and prepared.get("exists") is not True:
            issues.append(f"{path_label}.path 不存在：{normalized_path}")
        prepared_line_count = prepared.get("line_count")
        if isinstance(prepared_line_count, int):
            line_count = prepared_line_count
    line_start = value.get("line_start")
    line_end = value.get("line_end")
    if (line_start is None) != (line_end is None):
        issues.append(f"{path_label} 的 line_start 和 line_end 必须同时存在")
    elif line_start is not None:
        if (
            type(line_start) is not int
            or type(line_end) is not int
            or line_start < 1
            or line_end < line_start
        ):
            issues.append(f"{path_label} 的行范围无效")
        elif line_count is not None:
            if line_end > max(line_count, 1):
                issues.append(f"{path_label}.line_end 超出文件范围")
    return {
        "reference_id": reference_id,
        "repository_id": value.get("repository_id"),
        "path": normalized_path,
        "line_start": line_start,
        "line_end": line_end,
        "observed_ref": resolved_observed_ref,
        "epistemic_status": epistemic_status,
    }


def _repository_path(value: Any, path: str, issues: list[str]) -> str:
    raw = _text(value, path, issues)
    if not raw:
        return ""
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if _unsafe_repository_path(candidate, raw):
        issues.append(f"{path} 必须是仓库内相对路径")
        return ""
    return candidate.as_posix()


def _external_observation_provider_plans(
    value: Any,
    issues: list[str],
) -> list[dict[str, Any]]:
    """Normalize exact provider execution plans without granting execution."""

    plans = _list(
        value,
        "external_observation_provider_plans",
        issues,
    )
    normalized: list[dict[str, Any]] = []
    identities: set[str] = set()
    scope_languages: set[tuple[str, str]] = set()
    required = {
        "provider_plan_id",
        "scope_id",
        "language_id",
        "provider_id",
        "provider_version",
        "command",
        "materials",
        "source_globs",
        "process_policy",
        "limits",
    }
    for index, raw in enumerate(plans):
        path = f"external_observation_provider_plans[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(raw, required=required, optional={"repository_id"}, path=path, issues=issues)
        plan_id = _text(raw.get("provider_plan_id"), f"{path}.provider_plan_id", issues)
        if plan_id and re.fullmatch(r"OBSPROVPLAN-[0-9A-F]{16}", plan_id) is None:
            issues.append(f"{path}.provider_plan_id 必须匹配 OBSPROVPLAN-加十六位大写十六进制")
        if plan_id in identities:
            issues.append(f"外部观察提供者计划身份重复：{plan_id}")
        identities.add(plan_id)
        scope_id = _text(raw.get("scope_id"), f"{path}.scope_id", issues)
        if scope_id and re.fullmatch(r"OBSCOPE-[0-9A-F]{16}", scope_id) is None:
            issues.append(f"{path}.scope_id 必须匹配 OBSCOPE-加十六位大写十六进制")
        language = _text(raw.get("language_id"), f"{path}.language_id", issues).casefold()
        language = _OBSERVATION_LANGUAGE_ALIASES.get(language, language)
        if language and re.fullmatch(r"[a-z0-9][a-z0-9+.#_-]*", language) is None:
            issues.append(f"{path}.language_id 无效")
        scope_language = (raw.get("repository_id"), scope_id, language)
        if scope_language in scope_languages:
            issues.append(f"外部观察提供者计划重复：{scope_id}/{language}")
        scope_languages.add(scope_language)

        command = raw.get("command")
        if (
            not isinstance(command, list)
            or not command
            or any(not isinstance(item, str) or not item for item in command)
        ):
            issues.append(f"{path}.command 必须是非空 argv")
            command = []
        source_globs = raw.get("source_globs")
        if not isinstance(source_globs, list) or not source_globs:
            issues.append(f"{path}.source_globs 必须是非空数组")
            source_globs = []
        normalized_globs: list[str] = []
        for glob_index, item in enumerate(source_globs):
            glob_path = f"{path}.source_globs[{glob_index}]"
            if not isinstance(item, str) or not item.strip():
                issues.append(f"{glob_path} 必须是非空字符串")
                continue
            candidate = PurePosixPath(item)
            if candidate.is_absolute() or ".." in candidate.parts or "\\" in item:
                issues.append(f"{glob_path} 必须是安全的仓库相对 glob")
                continue
            normalized_globs.append(item.strip())

        policy = raw.get("process_policy")
        if not isinstance(policy, Mapping):
            issues.append(f"{path}.process_policy 必须是对象")
            policy = {}
        _check_fields(
            policy,
            required={"policy_id", "purpose", "forbidden_program_names"},
            path=f"{path}.process_policy",
            issues=issues,
        )
        policy_id = _text(
            policy.get("policy_id"),
            f"{path}.process_policy.policy_id",
            issues,
        )
        if policy_id and re.fullmatch(r"PROCESSPOLICY-[0-9A-F]{16}", policy_id) is None:
            issues.append(f"{path}.process_policy.policy_id 必须匹配 PROCESSPOLICY-加十六位大写十六进制")
        forbidden = _string_list(
            policy.get("forbidden_program_names"),
            f"{path}.process_policy.forbidden_program_names",
            issues,
            unique=True,
        )
        forbidden_identities = {
            identity
            for name in [*_DEFAULT_FORBIDDEN_AGENT_PROGRAM_NAMES, *forbidden]
            for identity in _program_identities(name)
        }
        if any(
            _program_identities(token) & forbidden_identities
            for token in command
        ):
            issues.append(f"{path}.command 不得直接或通过参数启动智能编码代理程序")
        command_identities = _program_identities(command[0]) if command else set()
        if command_identities & _OPAQUE_COMMAND_WRAPPER_NAMES:
            issues.append(f"{path}.command 不得使用不透明 shell 或命令包装器")
        inline_eval_flags = {"-c", "-e", "--eval", "--execute"}
        if command_identities & {"node", "perl", "python", "python3", "ruby"} and any(
            token.casefold() in inline_eval_flags for token in command[1:]
        ):
            issues.append(f"{path}.command 不得通过语言运行时执行内联代码")

        raw_materials = raw.get("materials")
        if not isinstance(raw_materials, list) or not raw_materials:
            issues.append(f"{path}.materials 必须是非空数组")
            raw_materials = []
        materials: list[dict[str, Any]] = []
        material_paths: set[str] = set()
        material_indices: set[int] = set()
        executable_bindings = 0
        for material_index, material in enumerate(raw_materials):
            material_path = f"{path}.materials[{material_index}]"
            if not isinstance(material, Mapping):
                issues.append(f"{material_path} 必须是对象")
                continue
            _check_fields(
                material,
                required={
                    "role",
                    "path",
                    "sha256",
                    "command_argument_index",
                },
                path=material_path,
                issues=issues,
            )
            role = _text(material.get("role"), f"{material_path}.role", issues)
            if role not in {
                "executable",
                "entry_script",
                "config",
                "supporting_file",
            }:
                issues.append(f"{material_path}.role 无效")
            raw_path = _text(
                material.get("path"),
                f"{material_path}.path",
                issues,
            ).replace("\\", "/")
            is_absolute = bool(
                raw_path.startswith("/")
                or re.match(r"^[A-Za-z]:/", raw_path)
            )
            if not is_absolute:
                raw_path = _repository_path(
                    raw_path,
                    f"{material_path}.path",
                    issues,
                )
            if raw_path in material_paths:
                issues.append(f"外部观察提供者材料路径重复：{raw_path}")
            material_paths.add(raw_path)
            digest = _text(
                material.get("sha256"),
                f"{material_path}.sha256",
                issues,
            )
            if digest and re.fullmatch(r"[0-9a-f]{64}", digest) is None:
                issues.append(f"{material_path}.sha256 必须是 64 位小写 SHA-256")
            argument_index = material.get("command_argument_index")
            if argument_index is not None:
                if type(argument_index) is not int or not (
                    0 <= argument_index < len(command)
                ):
                    issues.append(
                        f"{material_path}.command_argument_index 必须指向 command 参数"
                    )
                    argument_index = None
                elif argument_index in material_indices:
                    issues.append(
                        f"外部观察提供者材料重复绑定 command[{argument_index}]"
                    )
                else:
                    material_indices.add(argument_index)
            if role in {"executable", "entry_script"} and argument_index is None:
                issues.append(f"{material_path}.{role} 必须绑定一个 command 参数")
            if role == "executable":
                executable_bindings += 1
                if argument_index != 0:
                    issues.append(f"{material_path}.executable 必须绑定 command[0]")
            materials.append(
                {
                    "role": role,
                    "path": raw_path,
                    "sha256": digest,
                    "command_argument_index": argument_index,
                }
            )
        if executable_bindings != 1:
            issues.append(f"{path}.materials 必须唯一绑定 command[0] 可执行文件")

        limits = raw.get("limits")
        if not isinstance(limits, Mapping):
            issues.append(f"{path}.limits 必须是对象")
            limits = {}
        _check_fields(
            limits,
            required={
                "timeout_seconds",
                "cleanup_timeout_seconds",
                "max_input_bytes",
                "max_output_bytes",
            },
            path=f"{path}.limits",
            issues=issues,
        )
        timeout = _number(
            limits.get("timeout_seconds"),
            f"{path}.limits.timeout_seconds",
            issues,
            minimum=0,
            maximum=3600,
            exclusive_minimum=True,
        )
        cleanup_timeout = _number(
            limits.get("cleanup_timeout_seconds"),
            f"{path}.limits.cleanup_timeout_seconds",
            issues,
            minimum=0,
            maximum=300,
            exclusive_minimum=True,
        )
        max_input = _integer(
            limits.get("max_input_bytes"),
            f"{path}.limits.max_input_bytes",
            issues,
            minimum=1,
            maximum=_MAX_PROVIDER_INPUT_BYTES,
        )
        max_output = _integer(
            limits.get("max_output_bytes"),
            f"{path}.limits.max_output_bytes",
            issues,
            minimum=1,
            maximum=_MAX_PROVIDER_OUTPUT_BYTES,
        )
        normalized.append(
            {
                "provider_plan_id": plan_id,
                "repository_id": raw.get("repository_id"),
                "scope_id": scope_id,
                "language_id": language,
                "provider_id": _text(raw.get("provider_id"), f"{path}.provider_id", issues),
                "provider_version": _text(raw.get("provider_version"), f"{path}.provider_version", issues),
                "command": list(command),
                "materials": materials,
                "source_globs": sorted(set(normalized_globs)),
                "process_policy": {
                    "policy_id": policy_id,
                    "purpose": _text(policy.get("purpose"), f"{path}.process_policy.purpose", issues),
                    "forbidden_program_names": sorted(set(forbidden)),
                },
                "limits": {
                    "timeout_seconds": timeout,
                    "cleanup_timeout_seconds": cleanup_timeout,
                    "max_input_bytes": max_input,
                    "max_output_bytes": max_output,
                },
            }
        )
    return normalized


def _prepared_domain_fact_reference(
    value: Any,
    path: str,
    candidate_context: Mapping[str, Any],
    issues: list[str],
) -> dict[str, str] | None:
    references = candidate_context.get("domain_fact_references")
    prepared = references.get(path) if isinstance(references, Mapping) else None
    if not isinstance(prepared, Mapping):
        issues.append(f"{path} 缺少可信领域引用事实")
        return None
    if prepared.get("raw") != value:
        issues.append(f"{path} 与可信领域引用事实不匹配")
        return None
    prepared_issues = prepared.get("issues")
    if isinstance(prepared_issues, list) and prepared_issues:
        issues.extend(f"{path}: {item}" for item in prepared_issues)
        return None
    normalized = prepared.get("normalized")
    if not isinstance(normalized, Mapping):
        issues.append(f"{path} 没有有效的规范领域引用")
        return None
    return {str(key): str(item) for key, item in normalized.items()}


def _evidence_refs(
    value: Any,
    path: str,
    issues: list[str],
    known_refs: set[str],
) -> list[str]:
    refs = _list(value, path, issues)
    if not refs:
        issues.append(f"{path} 不能为空")
    normalized: list[str] = []
    for raw in refs:
        if not isinstance(raw, str):
            issues.append(f"{path} 只能包含字符串")
            continue
        ref = raw.strip()
        if not ref:
            issues.append(f"{path} 包含空值")
        elif ref not in known_refs:
            issues.append(f"{path} 引用了未知来源：{ref}")
        else:
            normalized.append(ref)
    return list(dict.fromkeys(normalized))


def _field_refs(field: str, values: Sequence[Any]) -> set[str]:
    return {f"{field}[{index}]" for index in range(len(values))}


def _impact_by_dimension(
    impact_scope: Mapping[str, Any],
) -> dict[str, dict[str, Any]]:
    """Project compact coding-agent input without adding meaning."""

    projected: dict[str, dict[str, Any]] = {}
    for status in ("affected", "unknown"):
        for item in impact_scope.get(status) or []:
            if isinstance(item, Mapping):
                projected[str(item.get("dimension") or "")] = {
                    "status": status,
                    "reason": item.get("reason"),
                    "evidence_refs": list(item.get("evidence_refs") or []),
                }
    for dimension in impact_scope.get("unaffected") or []:
        projected[str(dimension)] = {
            "status": "unaffected",
            "reason": None,
            "evidence_refs": [],
        }
    return projected


def _impact_trace_refs(impact_scope: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for status in ("affected", "unknown", "unaffected"):
        refs.extend(
            f"impact_scope.{status}[{index}]"
            for index, _ in enumerate(impact_scope.get(status) or [])
        )
    return refs


_METHOD_STAGES = frozenset(
    {
        "requirements",
        "domain_analysis",
        "design",
        "implementation",
        "verification",
        "delivery",
    }
)
_METHOD_DECISIONS = frozenset({"applied", "considered_not_applied"})
_METHOD_ADOPTION_STATUSES = frozenset(
    {"adopted", "conditional", "not_adopted", "not_assessed"}
)
_DOMAIN_FACT_DISPOSITIONS = frozenset({"retain", "add", "update", "retire"})


def _validate_domain_fact_changes(
    raw_value: Any,
    *,
    candidate_context: Mapping[str, Any],
    known_refs: set[str],
    known_domain_model_id: str | None,
    known_domain_fact_ids: set[str],
    known_domain_fact_paths: Mapping[str, str],
    investigation_commit: str | None,
    operations: Sequence[Mapping[str, Any]],
    domain_model_path: str | None,
    issues: list[str],
    domain_repository_id: str | None = None,
) -> list[dict[str, Any]]:
    """Validate project-authority Fact changes independently of methods."""

    raw_lineage_relations = candidate_context.get("domain_lineage_relations")
    lineage_relations = (
        frozenset(str(item) for item in raw_lineage_relations)
        if isinstance(raw_lineage_relations, list)
        else frozenset()
    )
    normalized: list[dict[str, Any]] = []
    seen_fact_changes: set[str] = set()
    for change_index, change in enumerate(
        _list(raw_value, "domain_fact_changes", issues)
    ):
        change_path = f"domain_fact_changes[{change_index}]"
        if not isinstance(change, Mapping):
            issues.append(f"{change_path} 必须是对象")
            continue
        _check_fields(
            change,
            required={
                "disposition",
                "target_ref",
                "source_path",
                "reason",
                "evidence_refs",
                "lineage",
            },
            optional={"repository_id"},
            path=change_path,
            issues=issues,
        )
        disposition = _enum(
            change.get("disposition"),
            f"{change_path}.disposition",
            _DOMAIN_FACT_DISPOSITIONS,
            issues,
        )
        target_ref = _prepared_domain_fact_reference(
            change.get("target_ref"),
            f"{change_path}.target_ref",
            candidate_context,
            issues,
        )
        if target_ref is None:
            target_ref = {
                "schema_version": "strixnova.domain-fact-reference.v1",
                "authority_kind": "project_domain_model",
                "model_id": "",
                "fact_id": "",
                "observed_commit": "",
            }
        fact_id = target_ref["fact_id"]
        if change.get("repository_id") != domain_repository_id:
            issues.append(f"{change_path}.repository_id 与领域权威仓库不一致")
        source_path = _repository_path(
            change.get("source_path"),
            f"{change_path}.source_path",
            issues,
        )
        if fact_id in seen_fact_changes:
            issues.append(f"domain_fact_changes 重复声明：{fact_id}")
        seen_fact_changes.add(fact_id)
        if (
            known_domain_model_id is not None
            and target_ref["model_id"] != known_domain_model_id
        ):
            issues.append(f"{change_path}.target_ref 指向其他领域模型")
        if (
            investigation_commit is not None
            and target_ref["observed_commit"] != investigation_commit
        ):
            issues.append(f"{change_path}.target_ref 未绑定 investigation_ref")
        if disposition == "add" and fact_id in known_domain_fact_ids:
            issues.append(f"{change_path} 把既有领域 Fact 错误声明为 add")
        if disposition != "add" and fact_id not in known_domain_fact_ids:
            issues.append(f"{change_path} 引用了不存在的当前领域 Fact")
        known_source_path = known_domain_fact_paths.get(fact_id)
        if (
            disposition in {"retain", "retire"}
            and known_source_path is not None
            and source_path != known_source_path
        ):
            issues.append(
                f"{change_path}.source_path 与当前 Fact 规范正文位置不一致"
            )
        lineage: list[dict[str, str]] = []
        for lineage_index, relation in enumerate(
            _list(change.get("lineage"), f"{change_path}.lineage", issues)
        ):
            lineage_path = f"{change_path}.lineage[{lineage_index}]"
            if not isinstance(relation, Mapping):
                issues.append(f"{lineage_path} 必须是对象")
                continue
            _check_fields(
                relation,
                required={"relation", "target_fact_id"},
                path=lineage_path,
                issues=issues,
            )
            relation_name = _enum(
                relation.get("relation"),
                f"{lineage_path}.relation",
                lineage_relations,
                issues,
            )
            target_fact_id = _text(
                relation.get("target_fact_id"),
                f"{lineage_path}.target_fact_id",
                issues,
            )
            identity = (relation_name, target_fact_id)
            if identity in {(item["relation"], item["target_fact_id"]) for item in lineage}:
                issues.append(f"{lineage_path} 重复")
            if target_fact_id == fact_id:
                issues.append(f"{lineage_path} 不得指向自身")
            lineage.append(
                {"relation": relation_name, "target_fact_id": target_fact_id}
            )
        if disposition != "retire" and lineage:
            issues.append(f"{change_path}.lineage 只适用于 retire")
        split_targets = [
            value for value in lineage if value["relation"] == "split_into"
        ]
        if split_targets and len(split_targets) < 2:
            issues.append(f"{change_path}.split_into 至少需要两个后继 Fact")
        normalized.append(
            {
                "disposition": disposition,
                "repository_id": change.get("repository_id"),
                "target_ref": target_ref,
                "source_path": source_path,
                "reason": _text(change.get("reason"), f"{change_path}.reason", issues),
                "evidence_refs": _evidence_refs(
                    change.get("evidence_refs"),
                    f"{change_path}.evidence_refs",
                    issues,
                    known_refs,
                ),
                "lineage": lineage,
            }
        )

    declared_fact_ids = known_domain_fact_ids | {
        change["target_ref"]["fact_id"]
        for change in normalized
        if change["disposition"] == "add"
    }
    operation_targets = {
        repository_key(operation, str(
            operation.get("to_path")
            if operation.get("action") == "move"
            else operation.get("path")
        )): str(operation.get("action") or "")
        for operation in operations
    }
    for change_index, change in enumerate(normalized):
        for lineage in change["lineage"]:
            if lineage["target_fact_id"] not in declared_fact_ids:
                issues.append(
                    f"domain_fact_changes[{change_index}].lineage "
                    "指向未知当前或同候选新增 Fact"
                )
        disposition = change["disposition"]
        if disposition != "retain":
            action = operation_targets.get(repository_key(change, change["source_path"]))
            allowed_actions = {
                "add": {"create", "modify"},
                "update": {"modify", "move"},
                "retire": {"modify", "delete"},
            }[disposition]
            if action not in allowed_actions:
                issues.append(
                    f"domain_fact_changes[{change_index}].source_path "
                    "缺少一致的计划文件操作"
                )
    if any(change["disposition"] == "retire" for change in normalized) and (
        not domain_model_path
        or operation_targets.get((domain_repository_id, domain_model_path)) not in {"modify", "move"}
    ):
        issues.append("domain_fact_changes 退役 Fact 时必须计划更新领域模型 tombstone")
    return normalized


def _validate_domain_fact_authority_change_alignment(
    domain_fact_changes: Sequence[Mapping[str, Any]],
    authority_change_set: Mapping[str, Any] | None,
    issues: list[str],
) -> None:
    """Keep the domain Fact ledger and authority change set on one identity map."""

    if not isinstance(authority_change_set, Mapping):
        return
    expected_operation = {
        "add": "add",
        "update": "modify",
        "retire": "retire",
    }
    fact_changes = {
        str(change.get("target_ref", {}).get("fact_id") or ""): str(
            change.get("disposition") or ""
        )
        for change in domain_fact_changes
        if isinstance(change.get("target_ref"), Mapping)
        and change.get("disposition") != "retain"
    }
    authority_changes: dict[str, list[str]] = {}
    raw_changes = authority_change_set.get("changes")
    if isinstance(raw_changes, list):
        for change in raw_changes:
            if not isinstance(change, Mapping):
                continue
            target_ref = str(change.get("target_ref") or "")
            if (
                change.get("authority_kind") == "domain_model"
                and target_ref.startswith("FACT-")
            ):
                authority_changes.setdefault(target_ref, []).append(
                    str(change.get("operation") or "")
                )

    for fact_id, disposition in sorted(fact_changes.items()):
        operations = authority_changes.get(fact_id, [])
        required = expected_operation.get(disposition)
        if operations != [required]:
            issues.append(
                "domain_fact_changes 与 authority_change_set 对同一领域 Fact "
                f"的身份或动作不一致：{fact_id} 需要 {required}，实际为 {operations}"
            )
    for fact_id in sorted(set(authority_changes) - set(fact_changes)):
        issues.append(
            "authority_change_set 声明了 domain_fact_changes 未登记的领域 Fact "
            f"变化：{fact_id}"
        )


def _validate_method_applications(
    raw_value: Any,
    *,
    candidate_context: Mapping[str, Any],
    change_kind: str,
    impact_scope: Mapping[str, Any],
    profile: Mapping[str, Any],
    known_refs: set[str],
    known_baseline_refs: set[str],
    known_domain_model_id: str | None,
    known_domain_fact_ids: set[str],
    domain_fact_changes: Sequence[Mapping[str, Any]],
    investigation_commit: str | None,
    target_refs: set[str],
    operations: Sequence[Mapping[str, Any]],
    baseline_path: str | None,
    domain_model_path: str | None,
    alignment_path: str | None,
    issues: list[str],
    baseline_repository_id: str | None = None,
    alignment_repository_id: str | None = None,
) -> list[dict[str, Any]]:
    """Validate explicit coding-agent choices without inventing semantics."""

    methods = {
        method["method_id"]: method
        for method in profile.get("engineering_methods", [])
        if isinstance(method, Mapping) and isinstance(method.get("method_id"), str)
    }
    adoptions = {
        adoption["method_id"]: adoption
        for adoption in profile.get("project_method_adoptions", [])
        if isinstance(adoption, Mapping)
        and isinstance(adoption.get("method_id"), str)
    }
    impact = _impact_by_dimension(impact_scope)
    relevant_dimensions = {
        dimension
        for dimension, detail in impact.items()
        if detail.get("status") in {"affected", "unknown"}
    }
    raw_items = _list(raw_value, "method_applications", issues)
    normalized: list[dict[str, Any]] = []
    seen_methods: set[str] = set()
    seen_uses: set[str] = set()
    for index, item in enumerate(raw_items):
        path = f"method_applications[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            item,
            required={
                "method_id",
                "decision",
                "purpose",
                "evidence_refs",
                "baseline_refs",
                "domain_fact_refs",
                "planned_uses",
            },
            optional={"adoption_change"},
            path=path,
            issues=issues,
        )
        method_id = _text(item.get("method_id"), f"{path}.method_id", issues)
        if method_id in seen_methods:
            issues.append(f"工程方法重复：{method_id}")
        seen_methods.add(method_id)
        method = methods.get(method_id)
        if method is None:
            issues.append(f"{path}.method_id 引用未知工程方法：{method_id}")
            method = {
                "techniques": [],
                "project_adoption_requires": [],
                "consider_when": [],
            }
        decision = _enum(
            item.get("decision"),
            f"{path}.decision",
            _METHOD_DECISIONS,
            issues,
        )
        evidence_refs = _evidence_refs(
            item.get("evidence_refs"),
            f"{path}.evidence_refs",
            issues,
            known_refs,
        )
        baseline_refs = _string_list(
            item.get("baseline_refs"),
            f"{path}.baseline_refs",
            issues,
            unique=True,
        )
        for ref in baseline_refs:
            if ref not in known_baseline_refs:
                issues.append(f"{path}.baseline_refs 引用了未知项目基线事实：{ref}")
        domain_fact_refs: list[dict[str, str]] = []
        seen_domain_refs: set[tuple[str, str, str]] = set()
        for ref_index, raw_reference in enumerate(
            _list(
                item.get("domain_fact_refs"),
                f"{path}.domain_fact_refs",
                issues,
            )
        ):
            reference_path = f"{path}.domain_fact_refs[{ref_index}]"
            reference = _prepared_domain_fact_reference(
                raw_reference,
                reference_path,
                candidate_context,
                issues,
            )
            if reference is None:
                continue
            identity = (
                reference["model_id"],
                reference["fact_id"],
                reference["observed_commit"],
            )
            if identity in seen_domain_refs:
                issues.append(f"{reference_path} 重复")
            seen_domain_refs.add(identity)
            if (
                known_domain_model_id is not None
                and reference["model_id"] != known_domain_model_id
            ):
                issues.append(f"{reference_path} 指向其他 ProjectDomainModel")
            if (
                investigation_commit is not None
                and reference["observed_commit"] != investigation_commit
            ):
                issues.append(f"{reference_path} 未绑定 investigation_ref")
            if reference["fact_id"] not in known_domain_fact_ids:
                issues.append(f"{reference_path} 引用未知当前领域 Fact")
            domain_fact_refs.append(reference)

        allowed_techniques = {
            technique["technique_id"]
            for technique in method.get("techniques", [])
            if isinstance(technique, Mapping)
            and isinstance(technique.get("technique_id"), str)
        }
        planned_uses: list[dict[str, Any]] = []
        for use_index, use in enumerate(
            _list(item.get("planned_uses"), f"{path}.planned_uses", issues)
        ):
            use_path = f"{path}.planned_uses[{use_index}]"
            if not isinstance(use, Mapping):
                issues.append(f"{use_path} 必须是对象")
                continue
            _check_fields(
                use,
                required={
                    "use_id",
                    "stage",
                    "technique_ids",
                    "purpose",
                    "target_refs",
                    "evidence_refs",
                },
                path=use_path,
                issues=issues,
            )
            use_id = _text(use.get("use_id"), f"{use_path}.use_id", issues)
            if use_id in seen_uses:
                issues.append(f"工程方法使用身份重复：{use_id}")
            seen_uses.add(use_id)
            technique_ids = _string_list(
                use.get("technique_ids"),
                f"{use_path}.technique_ids",
                issues,
                required=True,
                unique=True,
            )
            unknown_techniques = sorted(set(technique_ids) - allowed_techniques)
            if unknown_techniques:
                issues.append(
                    f"{use_path}.technique_ids 引用未知技术："
                    + ", ".join(unknown_techniques)
                )
            uses_targets = _string_list(
                use.get("target_refs"),
                f"{use_path}.target_refs",
                issues,
                required=True,
                unique=True,
            )
            for ref in uses_targets:
                if ref not in target_refs:
                    issues.append(f"{use_path}.target_refs 引用了未知工程事实：{ref}")
            planned_uses.append(
                {
                    "use_id": use_id,
                    "stage": _enum(
                        use.get("stage"),
                        f"{use_path}.stage",
                        _METHOD_STAGES,
                        issues,
                    ),
                    "technique_ids": technique_ids,
                    "purpose": _text(
                        use.get("purpose"), f"{use_path}.purpose", issues
                    ),
                    "target_refs": uses_targets,
                    "evidence_refs": _evidence_refs(
                        use.get("evidence_refs"),
                        f"{use_path}.evidence_refs",
                        issues,
                        known_refs,
                    ),
                }
            )

        adoption_change: dict[str, Any] | None = None
        raw_adoption_change = item.get("adoption_change")
        current_status = (
            adoptions.get(method_id, {}).get("status")
            if method_id in adoptions
            else None
        )
        if raw_adoption_change is not None:
            adoption_path = f"{path}.adoption_change"
            if not isinstance(raw_adoption_change, Mapping):
                issues.append(f"{adoption_path} 必须是对象")
            else:
                _check_fields(
                    raw_adoption_change,
                    required={"from_status", "to_status", "reason", "conditions"},
                    path=adoption_path,
                    issues=issues,
                )
                raw_from_status = raw_adoption_change.get("from_status")
                from_status = (
                    None
                    if raw_from_status is None
                    else _enum(
                        raw_from_status,
                        f"{adoption_path}.from_status",
                        _METHOD_ADOPTION_STATUSES,
                        issues,
                    )
                )
                to_status = _enum(
                    raw_adoption_change.get("to_status"),
                    f"{adoption_path}.to_status",
                    _METHOD_ADOPTION_STATUSES,
                    issues,
                )
                conditions = _string_list(
                    raw_adoption_change.get("conditions"),
                    f"{adoption_path}.conditions",
                    issues,
                )
                if from_status != current_status:
                    issues.append(
                        f"{adoption_path}.from_status 与当前项目采用状态不一致"
                    )
                if to_status == "conditional" and not conditions:
                    issues.append(f"{adoption_path}.conditions 在 conditional 时不能为空")
                if to_status != "conditional" and conditions:
                    issues.append(
                        f"{adoption_path}.conditions 只适用于 conditional"
                    )
                adoption_change = {
                    "from_status": from_status,
                    "to_status": to_status,
                    "reason": _text(
                        raw_adoption_change.get("reason"),
                        f"{adoption_path}.reason",
                        issues,
                    ),
                    "conditions": conditions,
                }

        if decision == "applied" and not planned_uses:
            issues.append(f"{path}.planned_uses 在 applied 时不能为空")
        if decision == "considered_not_applied" and (
            planned_uses
            or (
                adoption_change is not None
                and adoption_change["to_status"] in {"adopted", "conditional"}
            )
        ):
            issues.append(
                f"{path} 在 considered_not_applied 时不得伪造方法使用、"
                "领域变更或方法采用"
            )
        effective_status = (
            adoption_change["to_status"]
            if adoption_change is not None
            else current_status
        )
        if decision == "applied" and effective_status not in {
            "adopted",
            "conditional",
        }:
            issues.append(
                f"{path} 只有项目已采用或在本事项中明确采用该方法时"
                "才能声明 applied"
            )
        if current_status in {"adopted", "conditional"}:
            method_baseline_ref = f"engineering-policy:method:{method_id}"
            if method_baseline_ref not in baseline_refs:
                issues.append(f"{path}.baseline_refs 缺少 {method_baseline_ref}")
            if (
                method_id == "ddd"
                and decision == "applied"
                and not domain_fact_refs
            ):
                issues.append(
                    f"{path}.domain_fact_refs 必须引用本事项实际采用的项目领域 Fact"
                )
            adopted_techniques = set(
                adoptions.get(method_id, {}).get("adopted_technique_ids", [])
            )
            used_techniques = {
                technique_id
                for use in planned_uses
                for technique_id in use["technique_ids"]
            }
            unadopted = sorted(used_techniques - adopted_techniques)
            if unadopted:
                issues.append(
                    f"{path} 使用了项目未采用的工程技术：" + ", ".join(unadopted)
                )
        if adoption_change is not None and adoption_change["to_status"] in {
            "adopted",
            "conditional",
        }:
            if decision != "applied":
                issues.append(f"{path} 采用工程方法时 decision 必须是 applied")
            if method_id == "ddd":
                if not domain_model_path or not alignment_path:
                    issues.append(
                        f"{path} 建立 DDD 采用状态时必须定位领域模型和实现对齐"
                    )
                if not any(
                    change["disposition"] in {"add", "update"}
                    for change in domain_fact_changes
                ):
                    issues.append(
                        f"{path} 建立 DDD 采用状态时必须新增或更新领域 Fact"
                    )
                alignment_operations = [
                    operation
                    for operation in operations
                    if alignment_path
                    and operation.get("repository_id") == alignment_repository_id
                    and (
                        operation.get("path") == alignment_path
                        or operation.get("to_path") == alignment_path
                    )
                    and operation.get("action") in {"create", "modify", "move"}
                    and isinstance(
                        operation.get("long_lived_artifact"), Mapping
                    )
                    and operation["long_lived_artifact"].get("artifact_type")
                    == "domain_alignment"
                ]
                if not alignment_operations:
                    issues.append(
                        f"{path} 建立 DDD 采用状态时必须计划创建或更新完整实现对齐权威"
                    )
            used_techniques = {
                technique_id
                for use in planned_uses
                for technique_id in use["technique_ids"]
            }
            missing_required = sorted(
                set(method.get("project_adoption_requires", [])) - used_techniques
            )
            if missing_required:
                issues.append(
                    f"{path} 建立项目方法采用状态时缺少必要技术："
                    + ", ".join(missing_required)
                )

        normalized.append(
            {
                "method_id": method_id,
                "decision": decision,
                "purpose": _text(item.get("purpose"), f"{path}.purpose", issues),
                "evidence_refs": evidence_refs,
                "baseline_refs": baseline_refs,
                "domain_fact_refs": domain_fact_refs,
                "planned_uses": planned_uses,
                **(
                    {"adoption_change": adoption_change}
                    if adoption_change is not None
                    else {}
                ),
            }
        )

    for method_id, method in methods.items():
        dimensions = set(method.get("consider_when", [])) & relevant_dimensions
        adoption = adoptions.get(method_id)
        requires_explicit_choice = bool(dimensions) and (
            adoption is not None
            and adoption.get("status") in {"adopted", "conditional"}
        )
        if requires_explicit_choice and method_id not in seen_methods:
            issues.append(
                f"工程方法 {method_id} 已由项目采用且与本事项影响相关，"
                "必须由智能编码代理明确提交 applied 或 considered_not_applied"
            )
    if change_kind == "create_project":
        missing_methods = sorted(set(methods) - seen_methods)
        if missing_methods:
            issues.append(
                "create_project 必须明确决定项目工程方法采用状态："
                + ", ".join(missing_methods)
            )
        for application in normalized:
            if "adoption_change" not in application:
                issues.append(
                    f"create_project 的 {application['method_id']} 缺少 adoption_change"
                )

    declared_domain_model_ids = {
        reference["model_id"]
        for reference in [
            *(
                reference
                for application in normalized
                for reference in application["domain_fact_refs"]
            ),
            *(change["target_ref"] for change in domain_fact_changes),
        ]
        if reference.get("model_id")
    }
    if len(declared_domain_model_ids) > 1:
        issues.append(
            "同一工程评估的领域 Fact 引用必须指向一个 ProjectDomainModel"
        )

    changes_method_adoption = any(
        application.get("adoption_change") is not None
        for application in normalized
    )
    if changes_method_adoption:
        baseline_operations = [
            operation
            for operation in operations
            if (
                baseline_path
                and operation.get("repository_id") == baseline_repository_id
                and (
                    operation.get("path") == baseline_path
                    or operation.get("to_path") == baseline_path
                )
                and operation.get("action") in {"create", "modify", "move"}
            )
        ]
        policy_operations = [
            operation
            for operation in operations
            if operation.get("action") in {"create", "modify", "move"}
            and isinstance(operation.get("long_lived_artifact"), Mapping)
            and operation["long_lived_artifact"].get("artifact_type")
            == "quality_policy"
        ]
        if not baseline_operations:
            issues.append(
                "工程方法采用状态发生变化时，必须计划更新项目工程基线的精确政策引用"
            )
        if not policy_operations:
            issues.append(
                "工程方法采用状态发生变化时，必须计划创建或更新项目工程政策"
            )
    return normalized


def _rule_results(
    assessment: Mapping[str, Any],
    direction: Mapping[str, Any],
    profile: Mapping[str, Any],
    issues: list[str],
) -> list[dict[str, Any]]:
    formal = assessment["change_context"]["formal_implementation"] is True
    impact_scope = _impact_by_dimension(assessment["impact_scope"])
    presence = {
        "requirement": bool(direction.get("goal"))
        and bool(direction.get("scope")),
        "acceptance": bool(direction.get("acceptance")),
        # An explicitly present empty list means the coding agent and owner considered
        # constraints and found none; no placeholder prose is required.
        "constraint": "constraints" in direction,
        "impact": len(impact_scope) == len(IMPACT_DIMENSIONS),
        "risk": bool(assessment["risk_assessments"]),
        "option": bool(assessment["alternatives_and_tradeoffs"]),
        "design": bool(assessment["design_decisions"]),
        "operation": bool(assessment["operations"]),
        "verification": bool(assessment["verification_commands"] or assessment.get("verification_reviews")),
        "delivery": bool(assessment["delivery_plan"]),
        "adr_candidate": bool(assessment["adr_plans"]),
        "unknown": bool(assessment["unknowns_and_limitations"]),
    }
    results: list[dict[str, Any]] = []
    for rule in profile["rules"]:
        if rule.get("project_not_applicable") is True:
            continue
        triggered_by: list[str] = []
        evidence_refs: list[str] = []
        if formal and rule.get("always_for_formal_implementation") is True:
            triggered_by.append("formal_implementation")
            evidence_refs.append("direction")
        for dimension in list(rule.get("impact_dimensions") or []):
            impact = impact_scope.get(dimension) or {}
            status = impact.get("status")
            if status in {"affected", "unknown"}:
                triggered_by.append(f"impact_scope.{dimension}:{status}")
                evidence_refs.extend(impact.get("evidence_refs") or [])
        if not triggered_by:
            continue
        for kind in list(rule.get("required_information_kinds") or []):
            if not presence.get(str(kind), False):
                issues.append(f"{rule['rule_id']} 缺少 {kind} 工程事实")
        results.append(
            {
                "rule_id": rule["rule_id"],
                "topic": rule["topic"],
                "source_ids": list(rule["source_ids"]),
                "minimum_assurance": rule["minimum_assurance"],
                "triggered_by": triggered_by,
                "evidence_refs": list(dict.fromkeys(evidence_refs)),
                "required_information_kinds": list(
                    rule["required_information_kinds"]
                ),
            }
        )
    return results


def validate_assessment(
    assessment: Mapping[str, Any],
    *,
    project_dir: str | Path,
    candidate_context: Mapping[str, Any],
    work_item_id: str,
    direction: Mapping[str, Any],
    direction_version: int,
    profile: Mapping[str, Any],
    known_baseline_refs: set[str] | None = None,
    domain_model_id: str | None = None,
    known_domain_fact_locations: Mapping[str, str] | None = None,
    known_authority_artifacts: Mapping[str, Mapping[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate one coding-agent assessment without adding semantics."""

    issues: list[str] = []
    if not isinstance(assessment, Mapping):
        raise EngineeringGovernanceError(["assessment 必须是对象"])
    if not isinstance(candidate_context, Mapping) or candidate_context.get(
        "schema_version"
    ) != "strixnova.engineering-candidate-context.v1":
        raise EngineeringGovernanceError(
            ["工程评估必须携带跨权威接口提供的可信候选上下文"]
        )
    code_facts = candidate_context.get("code_facts")
    if not isinstance(code_facts, Mapping) or code_facts.get(
        "schema_version"
    ) != "strixnova.engineering-candidate-code-facts.v1":
        raise EngineeringGovernanceError(["可信候选上下文缺少代码事实"])
    repository_context = candidate_context.get("repository_context")
    if not isinstance(repository_context, Mapping):
        raise EngineeringGovernanceError(["可信候选上下文缺少仓库范围"])
    if repository_context.get("issues"):
        raise EngineeringGovernanceError(repository_context["issues"])
    try:
        repository_scope = scope_for_candidate(assessment, repository_context)
        value = qualify_candidate(assessment, repository_scope)
    except ProjectContextError as error:
        raise EngineeringGovernanceError([str(error)]) from error
    required_fields = {
        "schema_version",
        "assessment_id",
        "assessment_revision",
        "direction_ref",
        "investigation_ref",
        "change_context",
        "impact_scope",
        "requested_assurance",
        "owner_view",
    }
    optional_fields = {
        "repository_scope",
        "source_references",
        "domain_fact_changes",
        "authority_change_set",
        "semantic_review",
        "method_applications",
        "risk_assessments",
        "alternatives_and_tradeoffs",
        "design_decisions",
        "operations",
        "implementation_slices",
        "adr_plans",
        "verification_commands",
        "verification_reviews",
        "verification_not_required_reason",
        "external_observation_provider_plans",
        "delivery_plan",
        "unknowns_and_limitations",
    }
    _check_fields(
        assessment,
        required=required_fields,
        optional=optional_fields,
        path="assessment",
        issues=issues,
    )
    if value.get("schema_version") != ASSESSMENT_SCHEMA:
        issues.append(f"schema_version 必须是 {ASSESSMENT_SCHEMA}")
    assessment_id = _text(
        value.get("assessment_id"), "assessment_id", issues
    )
    revision = _integer(
        value.get("assessment_revision"),
        "assessment_revision",
        issues,
        minimum=1,
    )

    current_work_item_id = _text(
        work_item_id,
        "current_work_item_id",
        issues,
    )
    if type(direction_version) is not int or direction_version < 1:
        issues.append("current_direction_version 必须是正整数")
    if not isinstance(direction, Mapping):
        issues.append("current_direction 必须是已确认方向对象")
        direction = {}
    direction_targets = _direction_target_refs(direction, issues)
    if direction.get("schema_version") != DIRECTION_SCHEMA:
        issues.append("工程评估需要当前完整方向合同")
    try:
        behavior_examples = example_catalog(direction)
    except BehaviorExampleError as error:
        issues.append(str(error))
        behavior_examples = {}
    raw_direction_ref = value.get("direction_ref")
    if not isinstance(raw_direction_ref, Mapping):
        issues.append("direction_ref 必须是对象")
        raw_direction_ref = {}
    _check_fields(
        raw_direction_ref,
        required={"work_item_id", "direction_version"},
        path="direction_ref",
        issues=issues,
    )
    referenced_work_item_id = _text(
        raw_direction_ref.get("work_item_id"),
        "direction_ref.work_item_id",
        issues,
    )
    referenced_direction_version = raw_direction_ref.get("direction_version")
    if (
        type(referenced_direction_version) is not int
        or referenced_direction_version < 1
    ):
        issues.append("direction_ref.direction_version 必须是正整数")
    if referenced_work_item_id and referenced_work_item_id != current_work_item_id:
        issues.append("direction_ref.work_item_id 不是当前 WorkItem")
    if (
        type(direction_version) is int
        and type(referenced_direction_version) is int
        and referenced_direction_version != direction_version
    ):
        issues.append("direction_ref.direction_version 不是当前已确认方向版本")
    direction_ref = {
        "work_item_id": referenced_work_item_id,
        "direction_version": referenced_direction_version,
    }
    investigation_ref = _text(
        value.get("investigation_ref"), "investigation_ref", issues
    )
    investigation_commit: str | None = None
    investigation_fact = code_facts.get("investigation")
    if not isinstance(investigation_fact, Mapping):
        issues.append("investigation_ref 缺少可信代码事实")
    else:
        current_investigation_ref = value.get("investigation_ref")
        if current_investigation_ref not in {
            investigation_fact.get("requested_ref"),
            investigation_fact.get("resolved_ref"),
        }:
            issues.append("investigation_ref 与可信代码事实不匹配")
        fact_issues = investigation_fact.get("issues")
        if isinstance(fact_issues, list):
            issues.extend(f"investigation_ref: {item}" for item in fact_issues)
        resolved_ref = investigation_fact.get("resolved_ref")
        if isinstance(resolved_ref, str) and resolved_ref:
            investigation_ref = resolved_ref
            if investigation_fact.get("immutable") is True:
                investigation_commit = resolved_ref

    raw_context = value.get("change_context")
    if not isinstance(raw_context, Mapping):
        issues.append("change_context 必须是对象")
        raw_context = {}
    _check_fields(
        raw_context,
        required={"change_kind", "formal_implementation"},
        optional={
            "project_engineering_baseline_path",
            "project_product_definition_path",
            "project_domain_model_path",
            "project_architecture_description_path",
            "project_engineering_policy_path",
            "project_implementation_alignment_path",
        },
        path="change_context",
        issues=issues,
    )
    change_kind = _enum(
        raw_context.get("change_kind"),
        "change_context.change_kind",
        {"modify_existing", "add_capability", "create_project", "exploration"},
        issues,
    )
    formal = _boolean(
        raw_context.get("formal_implementation"),
        "change_context.formal_implementation",
        issues,
    )
    change_context: dict[str, Any] = {
        "change_kind": change_kind,
        "formal_implementation": formal,
    }
    if change_kind == "create_project":
        change_context["project_engineering_baseline_path"] = (
            _repository_path(
                raw_context.get("project_engineering_baseline_path"),
                "change_context.project_engineering_baseline_path",
                issues,
            )
        )
        for field in (
            "project_product_definition_path",
            "project_domain_model_path",
            "project_architecture_description_path",
            "project_engineering_policy_path",
            "project_implementation_alignment_path",
        ):
            change_context[field] = _repository_path(
                raw_context.get(field),
                f"change_context.{field}",
                issues,
            )
    elif set(raw_context) & {
        "project_engineering_baseline_path",
        "project_product_definition_path",
        "project_domain_model_path",
        "project_architecture_description_path",
        "project_engineering_policy_path",
        "project_implementation_alignment_path",
    }:
        issues.append(
            "项目长期权威路径字段只适用于 create_project"
        )

    source_references: list[dict[str, Any]] = []
    source_ids: set[str] = set()
    for index, reference in enumerate(
        _list(
            value.get("source_references", []),
            "source_references",
            issues,
        )
    ):
        normalized = _source_reference(
            reference,
            index,
            code_facts,
            issues,
        )
        if normalized is None:
            continue
        reference_id = normalized["reference_id"]
        if reference_id in source_ids:
            issues.append(f"source reference 重复：{reference_id}")
        source_ids.add(reference_id)
        source_references.append(normalized)
    known_refs = {
        "direction",
        *source_ids,
        *(known_baseline_refs or set()),
    }
    external_observation_provider_plans = _external_observation_provider_plans(
        value.get("external_observation_provider_plans", []),
        issues,
    )

    raw_impact = value.get("impact_scope")
    if not isinstance(raw_impact, Mapping):
        issues.append("impact_scope 必须是对象")
        raw_impact = {}
    _check_fields(
        raw_impact,
        required={"affected", "unknown", "unaffected"},
        path="impact_scope",
        issues=issues,
    )
    impact_items: dict[str, dict[str, dict[str, Any]]] = {
        "affected": {},
        "unknown": {},
    }
    seen_dimensions: dict[str, str] = {}
    for status in ("affected", "unknown"):
        for index, item in enumerate(
            _list(
                raw_impact.get(status),
                f"impact_scope.{status}",
                issues,
            )
        ):
            path = f"impact_scope.{status}[{index}]"
            if not isinstance(item, Mapping):
                issues.append(f"{path} 必须是对象")
                continue
            _check_fields(
                item,
                required={"dimension", "reason", "evidence_refs"},
                path=path,
                issues=issues,
            )
            dimension = _text(
                item.get("dimension"), f"{path}.dimension", issues
            )
            if dimension not in IMPACT_DIMENSIONS:
                issues.append(f"{path}.dimension 无效")
            elif dimension in seen_dimensions:
                issues.append(
                    f"影响维度重复：{dimension}（{seen_dimensions[dimension]}、{path}）"
                )
            else:
                seen_dimensions[dimension] = path
            impact_items[status][dimension] = {
                "dimension": dimension,
                "reason": _text(
                    item.get("reason"), f"{path}.reason", issues
                ),
                "evidence_refs": _evidence_refs(
                    item.get("evidence_refs"),
                    f"{path}.evidence_refs",
                    issues,
                    known_refs,
                ),
            }

    unaffected: list[str] = []
    for index, raw_dimension in enumerate(
        _list(
            raw_impact.get("unaffected"),
            "impact_scope.unaffected",
            issues,
        )
    ):
        path = f"impact_scope.unaffected[{index}]"
        dimension = _text(raw_dimension, path, issues)
        if dimension not in IMPACT_DIMENSIONS:
            issues.append(f"{path} 无效")
            continue
        if dimension in seen_dimensions:
            issues.append(
                f"影响维度重复：{dimension}（{seen_dimensions[dimension]}、{path}）"
            )
            continue
        seen_dimensions[dimension] = path
        unaffected.append(dimension)

    missing_dimensions = [
        dimension
        for dimension in IMPACT_DIMENSIONS
        if dimension not in seen_dimensions
    ]
    if missing_dimensions:
        issues.append("impact_scope 缺少维度：" + ", ".join(missing_dimensions))
    impact_scope: dict[str, Any] = {
        "affected": [
            impact_items["affected"][dimension]
            for dimension in IMPACT_DIMENSIONS
            if dimension in impact_items["affected"]
        ],
        "unknown": [
            impact_items["unknown"][dimension]
            for dimension in IMPACT_DIMENSIONS
            if dimension in impact_items["unknown"]
        ],
        "unaffected": [
            dimension for dimension in IMPACT_DIMENSIONS if dimension in unaffected
        ],
    }

    risk_assessments: list[dict[str, Any]] = []
    risk_fields = {
        "statement",
        "likelihood",
        "consequence",
        "reversibility",
        "uncertainty",
        "external_assurance_required",
        "mitigation",
        "evidence_refs",
    }
    for index, item in enumerate(
        _list(
            value.get("risk_assessments", []),
            "risk_assessments",
            issues,
        )
    ):
        path = f"risk_assessments[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(item, required=risk_fields, path=path, issues=issues)
        likelihood = _enum(
            item.get("likelihood"),
            f"{path}.likelihood",
            {"low", "medium", "high"},
            issues,
        )
        consequence = _enum(
            item.get("consequence"),
            f"{path}.consequence",
            {"low", "medium", "high", "critical"},
            issues,
        )
        reversibility = _enum(
            item.get("reversibility"),
            f"{path}.reversibility",
            {"easy", "moderate", "difficult", "irreversible"},
            issues,
        )
        uncertainty = _enum(
            item.get("uncertainty"),
            f"{path}.uncertainty",
            {"low", "medium", "high"},
            issues,
        )
        external = _boolean(
            item.get("external_assurance_required"),
            f"{path}.external_assurance_required",
            issues,
        )
        risk_assessments.append(
            {
                "statement": _text(
                    item.get("statement"), f"{path}.statement", issues
                ),
                "likelihood": likelihood,
                "consequence": consequence,
                "reversibility": reversibility,
                "uncertainty": uncertainty,
                "external_assurance_required": external,
                "mitigation": _text(
                    item.get("mitigation"), f"{path}.mitigation", issues
                ),
                "evidence_refs": _evidence_refs(
                    item.get("evidence_refs"),
                    f"{path}.evidence_refs",
                    issues,
                    known_refs,
                ),
            }
        )
    alternatives: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(
            value.get("alternatives_and_tradeoffs", []),
            "alternatives_and_tradeoffs",
            issues,
        )
    ):
        path = f"alternatives_and_tradeoffs[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            item,
            required={
                "option",
                "disposition",
                "reason",
                "tradeoffs",
                "evidence_refs",
            },
            path=path,
            issues=issues,
        )
        disposition = _enum(
            item.get("disposition"),
            f"{path}.disposition",
            {"selected", "rejected", "deferred"},
            issues,
        )
        alternatives.append(
            {
                "option": _text(item.get("option"), f"{path}.option", issues),
                "disposition": disposition,
                "reason": _text(item.get("reason"), f"{path}.reason", issues),
                "tradeoffs": _text(
                    item.get("tradeoffs"), f"{path}.tradeoffs", issues
                ),
                "evidence_refs": _evidence_refs(
                    item.get("evidence_refs"),
                    f"{path}.evidence_refs",
                    issues,
                    known_refs,
                ),
            }
        )

    design_decisions: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(
            value.get("design_decisions", []),
            "design_decisions",
            issues,
        )
    ):
        path = f"design_decisions[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            item,
            required={"statement", "rationale", "evidence_refs"},
            path=path,
            issues=issues,
        )
        design_decisions.append(
            {
                "statement": _text(
                    item.get("statement"), f"{path}.statement", issues
                ),
                "rationale": _text(
                    item.get("rationale"), f"{path}.rationale", issues
                ),
                "evidence_refs": _evidence_refs(
                    item.get("evidence_refs"),
                    f"{path}.evidence_refs",
                    issues,
                    known_refs,
                ),
            }
        )

    implements_targets = direction_targets["requirements"] | _field_refs(
        "design_decisions", design_decisions
    )
    operations: list[dict[str, Any]] = []
    operation_paths: dict[tuple[str | None, str], str] = {}
    operation_targets: dict[tuple[str | None, str], str] = {}
    final_actions: dict[tuple[str | None, str], str] = {}
    operation_fields = {
        "action",
        "path",
        "reason",
        "evidence_refs",
        "implements",
    }
    for index, item in enumerate(
        _list(value.get("operations", []), "operations", issues)
    ):
        path = f"operations[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            item,
            required=operation_fields,
            optional={"to_path", "long_lived_artifact", "repository_id"},
            path=path,
            issues=issues,
        )
        action = _enum(
            item.get("action"),
            f"{path}.action",
            {"create", "modify", "delete", "move"},
            issues,
        )
        repository_path = _repository_path(
            item.get("path"), f"{path}.path", issues
        )
        if repository_path:
            key = repository_key(item, repository_path)
            if key in operation_paths:
                issues.append(f"操作路径重复：{repository_path}")
            operation_paths[key] = path
            final_actions[key] = action
        normalized: dict[str, Any] = {
            "action": action,
            "repository_id": item.get("repository_id"),
            "path": repository_path,
            "reason": _text(item.get("reason"), f"{path}.reason", issues),
            "evidence_refs": _evidence_refs(
                item.get("evidence_refs"),
                f"{path}.evidence_refs",
                issues,
                known_refs,
            ),
        }
        implements = _string_list(
            item.get("implements"),
            f"{path}.implements",
            issues,
            required=True,
        )
        for ref in implements:
            if ref not in implements_targets:
                issues.append(f"{path}.implements 引用了未知事实：{ref}")
        normalized["implements"] = list(dict.fromkeys(implements))
        if action == "move":
            target = _repository_path(
                item.get("to_path"), f"{path}.to_path", issues
            )
            normalized["to_path"] = target
            if target:
                key = repository_key(item, target)
                if key in operation_targets:
                    issues.append(f"移动目标重复：{target}")
                operation_targets[key] = path
                final_actions[key] = "move"
        elif "to_path" in item:
            issues.append(f"{path}.to_path 只适用于 move")
        long_lived = item.get("long_lived_artifact")
        if long_lived is not None:
            long_path = f"{path}.long_lived_artifact"
            if not isinstance(long_lived, Mapping):
                issues.append(f"{long_path} 必须是对象")
            else:
                _check_fields(
                    long_lived,
                    required={"artifact_id", "artifact_type"},
                    path=long_path,
                    issues=issues,
                )
                artifact_type = _enum(
                    long_lived.get("artifact_type"),
                    f"{long_path}.artifact_type",
                    ARTIFACT_TYPES,
                    issues,
                )
                artifact_id = _text(
                    long_lived.get("artifact_id"),
                    f"{long_path}.artifact_id",
                    issues,
                )
                core_kind = _CORE_AUTHORITY_KIND_BY_ARTIFACT_TYPE.get(
                    artifact_type
                )
                core_identity_pattern = _CORE_AUTHORITY_ID_PATTERNS.get(
                    str(core_kind or "")
                )
                if (
                    core_kind is not None
                    and artifact_id
                    and core_identity_pattern is not None
                    and core_identity_pattern.fullmatch(artifact_id) is None
                ):
                    issues.append(
                        f"{long_path}.artifact_id 必须符合 {core_kind} "
                        "稳定身份格式 "
                        f"{core_identity_pattern.pattern[1:-1]}"
                    )
                normalized["long_lived_artifact"] = {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                }
        operations.append(normalized)
    for target, target_ref in operation_targets.items():
        if target in operation_paths:
            issues.append(
                f"移动目标与另一操作路径冲突：{target}（{operation_paths[target]}、{target_ref}）"
            )
    if investigation_commit is not None:
        raw_operation_facts = code_facts.get("operation_paths")
        operation_facts = (
            raw_operation_facts
            if isinstance(raw_operation_facts, Mapping)
            else {}
        )
        for index, operation in enumerate(operations):
            operation_path = f"operations[{index}]"
            source_path = operation.get("path")
            action = operation.get("action")
            if not source_path or not action:
                continue
            source_fact_path = f"{operation_path}.path"
            source_fact = operation_facts.get(source_fact_path)
            source_exists: bool | None = None
            if not isinstance(source_fact, Mapping):
                issues.append(f"{source_fact_path} 缺少可信代码事实")
            else:
                if source_fact.get("repository_id") != operation.get("repository_id") or source_fact.get("normalized_path") != source_path:
                    issues.append(f"{source_fact_path} 与可信代码事实不匹配")
                source_exists = source_fact.get("exists")
            if action == "create" and source_exists:
                issues.append(
                    f"{operation_path}.path 在 investigation_ref 已存在，"
                    "不能声明为 create"
                )
            if action in {"modify", "delete", "move"} and not source_exists:
                issues.append(
                    f"{operation_path}.path 在 investigation_ref 不存在，"
                    f"不能声明为 {action}"
                )
            target_path = operation.get("to_path")
            if (
                action == "move"
                and target_path
            ):
                target_fact_path = f"{operation_path}.to_path"
                target_fact = operation_facts.get(target_fact_path)
                if not isinstance(target_fact, Mapping):
                    issues.append(f"{target_fact_path} 缺少可信代码事实")
                elif target_fact.get("repository_id") != operation.get("repository_id") or target_fact.get("normalized_path") != target_path:
                    issues.append(f"{target_fact_path} 与可信代码事实不匹配")
                elif target_fact.get("exists") is True:
                    issues.append(
                        f"{operation_path}.to_path 在 investigation_ref 已存在，"
                        "不能作为 move 目标"
                    )
    if not formal and operations:
        issues.append("非正式调查不得计划仓库创建、修改、删除或移动操作")

    adr_plans: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(value.get("adr_plans", []), "adr_plans", issues)
    ):
        path = f"adr_plans[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            item,
            required={"disposition", "reason", "evidence_refs"},
            optional={"artifact_id", "path", "repository_id"},
            path=path,
            issues=issues,
        )
        disposition = _enum(
            item.get("disposition"),
            f"{path}.disposition",
            {"create", "update", "not_required"},
            issues,
        )
        normalized = {
            "disposition": disposition,
            "reason": _text(item.get("reason"), f"{path}.reason", issues),
            "evidence_refs": _evidence_refs(
                item.get("evidence_refs"),
                f"{path}.evidence_refs",
                issues,
                known_refs,
            ),
        }
        if disposition in {"create", "update"}:
            artifact_id = _text(
                item.get("artifact_id"), f"{path}.artifact_id", issues
            )
            adr_path = _repository_path(item.get("path"), f"{path}.path", issues)
            normalized.update({"artifact_id": artifact_id, "path": adr_path, "repository_id": item.get("repository_id")})
            allowed_actions = {"create"} if disposition == "create" else {
                "modify",
                "move",
            }
            if final_actions.get(repository_key(item, adr_path)) not in allowed_actions:
                issues.append(
                    f"{path} 的 ADR {disposition} 缺少同路径操作：{adr_path}"
                )
        elif "artifact_id" in item or "path" in item:
            issues.append(f"{path} 在 not_required 时不得声明 ADR 身份或路径")
        adr_plans.append(normalized)

    if change_kind == "create_project":
        baseline_path = change_context.get("project_engineering_baseline_path")
        product_path = change_context.get("project_product_definition_path")
        architecture_path = change_context.get(
            "project_architecture_description_path"
        )
        domain_path = change_context.get("project_domain_model_path")
        policy_path = change_context.get("project_engineering_policy_path")
        alignment_path = change_context.get(
            "project_implementation_alignment_path"
        )
        missing = sorted(
            path
            for path in {
                "strixnova-project.yaml",
                str(baseline_path or ""),
                str(product_path or ""),
                str(architecture_path or ""),
                str(domain_path or ""),
                str(policy_path or ""),
                str(alignment_path or ""),
            }
            if path and final_actions.get((repository_scope["repositories"][0]["repository_id"], path)) != "create"
        )
        if missing:
            issues.append(
                "create_project 必须显式创建项目配置和首个长期权威："
                + ", ".join(missing)
            )
        authority_requirements = {
            str(product_path or ""): "product_governance",
            str(domain_path or ""): "domain_model",
            str(architecture_path or ""): "architecture",
            str(policy_path or ""): "quality_policy",
            str(alignment_path or ""): "domain_alignment",
        }
        missing_authorities = sorted(
            f"{path}:{artifact_type}"
            for path, artifact_type in authority_requirements.items()
            if path
            and not any(
                operation.get("action") == "create"
                and operation.get("path") == path
                and isinstance(operation.get("long_lived_artifact"), Mapping)
                and operation["long_lived_artifact"].get("artifact_type")
                == artifact_type
                for operation in operations
            )
        )
        if missing_authorities:
            issues.append(
                "create_project 的五类项目权威必须按约定类型独立建立："
                + ", ".join(missing_authorities)
            )

    if not isinstance(profile, Mapping):
        raise EngineeringGovernanceError(["工程治理上下文缺少工程政策摘要"])
    profile_value = deepcopy(dict(profile))
    scope_by_repository = {entry["repository_id"]: entry for entry in repository_scope["repositories"]}
    default_repository_id = next(iter(scope_by_repository)) if len(scope_by_repository) == 1 else None
    authority_repositories = profile_value.get("project_authority_repositories") or {}
    domain_repository_id = authority_repositories.get("domain_model", default_repository_id)
    baseline_repository_id = profile_value.get("project_baseline_repository_id", default_repository_id)
    domain_commit = (profile_value.get("project_authority_content_refs") or {}).get("domain_model", {}).get("observed_commit") or scope_by_repository.get(domain_repository_id, {}).get("investigation_ref", investigation_commit)
    if domain_commit == "working_tree":
        domain_commit = None
    method_target_refs = {
        *known_refs,
        *_impact_trace_refs(impact_scope),
        *_field_refs("design_decisions", design_decisions),
        *_field_refs("operations", operations),
        *direction_targets["requirements"],
        *direction_targets["acceptance"],
        *direction_targets["constraints"],
    }
    baseline_path = (
        str(change_context.get("project_engineering_baseline_path") or "")
        if change_kind == "create_project"
        else str(profile_value.get("project_engineering_baseline_path") or "")
    )
    if known_authority_artifacts is not None:
        adopted_authorities = {
            str(artifact_id): {"repository_id": default_repository_id, **dict(artifact)}
            for artifact_id, artifact in known_authority_artifacts.items()
        }
        authorities_by_path: dict[tuple[str | None, str], list[str]] = {}
        for artifact_id, artifact in adopted_authorities.items():
            for authority_path in (
                artifact.get("governed_paths")
                or [artifact.get("path")]
            ):
                normalized_path = str(authority_path or "")
                if normalized_path:
                    authorities_by_path.setdefault(
                        repository_key(artifact, normalized_path),
                        [],
                    ).append(artifact_id)
        adopted_core_by_kind = {
            str(artifact.get("authority_kind") or ""): artifact_id
            for artifact_id, artifact in adopted_authorities.items()
            if str(artifact.get("authority_kind") or "")
            in set(_CORE_AUTHORITY_KIND_BY_ARTIFACT_TYPE.values())
        }
        observed_sources_by_path: dict[tuple[str | None, str], set[str]] = {}
        for reference in source_references:
            if (
                reference.get("epistemic_status") == "observed"
                and reference.get("observed_ref") == scope_by_repository.get(reference.get("repository_id"), {}).get("investigation_ref")
            ):
                observed_sources_by_path.setdefault(
                    repository_key(reference, str(reference.get("path") or "")),
                    set(),
                ).add(str(reference.get("reference_id") or ""))
        baseline_update_planned = any(
            repository_key(operation, operation.get("path")) == (baseline_repository_id, baseline_path)
            and operation.get("action") in {"create", "modify", "move"}
            for operation in operations
        )
        planned_artifact_ids: set[str] = set()
        for index, operation in enumerate(operations):
            artifact = operation.get("long_lived_artifact")
            operation_path = str(operation.get("path") or "")
            operation_key = repository_key(operation, operation_path)
            authorities_at_path = authorities_by_path.get(operation_key, [])
            if (
                authorities_at_path
                and operation.get("action") in {"modify", "move", "delete"}
                and operation_key != (baseline_repository_id, baseline_path)
                and not baseline_update_planned
            ):
                issues.append(
                    f"operations[{index}] 修改、移动或删除当前采用项目权威的"
                    "治理文件时，必须同步计划更新项目工程基线中的精确权威引用："
                    + ", ".join(sorted(authorities_at_path))
                )
            if not isinstance(artifact, Mapping):
                root_authorities = [
                    artifact_id
                    for artifact_id in authorities_at_path
                    if operation_path
                    == str(adopted_authorities[artifact_id].get("path") or "")
                ]
                if root_authorities:
                    issues.append(
                        f"operations[{index}] 修改了项目工程基线当前引用的项目权威"
                        "但缺少 long_lived_artifact："
                        + ", ".join(sorted(root_authorities))
                    )
                continue
            artifact_id = str(artifact.get("artifact_id") or "")
            artifact_type = str(artifact.get("artifact_type") or "")
            core_kind = _CORE_AUTHORITY_KIND_BY_ARTIFACT_TYPE.get(artifact_type)
            adopted_core_id = adopted_core_by_kind.get(str(core_kind or ""))
            if adopted_core_id and artifact_id != adopted_core_id:
                issues.append(
                    f"operations[{index}] 试图为现有项目建立第二个核心"
                    f"{core_kind} 身份：{artifact_id}；现行稳定身份必须保持为"
                    f" {adopted_core_id}，变化只能形成新修订"
                )
            if artifact_id in planned_artifact_ids:
                issues.append(f"长期产物身份重复计划：{artifact_id}")
            planned_artifact_ids.add(artifact_id)
            adopted = adopted_authorities.get(artifact_id)
            if adopted is not None:
                if artifact_type != str(adopted.get("artifact_type") or ""):
                    issues.append(
                        f"operations[{index}].long_lived_artifact 类型与"
                        f"当前采用项目权威引用不一致：{artifact_id}"
                    )
                if operation_key != repository_key(adopted, str(adopted.get("path") or "")):
                    issues.append(
                        f"operations[{index}] 路径与当前采用项目权威引用不一致："
                        f"{artifact_id}"
                    )
                continue
            if authorities_at_path:
                issues.append(
                    f"operations[{index}].long_lived_artifact 不能把当前采用项目"
                    "权威的治理路径重分类为其他长期产物；应归属："
                    + ", ".join(sorted(authorities_at_path))
                )
            if change_kind == "create_project":
                if operation.get("action") != "create":
                    issues.append(
                        f"新项目尚未采用的长期工程文件必须由 create 建立：{artifact_id}"
                    )
                continue
            if operation.get("action") != "create":
                source_ids_for_path = observed_sources_by_path.get(
                    operation_key,
                    set(),
                )
                if not source_ids_for_path.intersection(
                    operation.get("evidence_refs", [])
                ):
                    issues.append(
                        f"普通长期工程文件的既有身份与路径必须由调查提交中的"
                        f"可重读观察来源证明并被本操作引用：{artifact_id}"
                    )
    project_authority_paths = (
        {
            "project_product_definition_path": change_context.get(
                "project_product_definition_path"
            ),
            "project_domain_model_path": change_context.get(
                "project_domain_model_path"
            ),
            "project_architecture_description_path": change_context.get(
                "project_architecture_description_path"
            ),
            "project_engineering_policy_path": change_context.get(
                "project_engineering_policy_path"
            ),
            "project_implementation_alignment_path": change_context.get(
                "project_implementation_alignment_path"
            ),
        }
        if change_kind == "create_project"
        else profile_value.get("project_authority_paths")
    )
    project_authority_paths = (
        project_authority_paths
        if isinstance(project_authority_paths, Mapping)
        else {}
    )

    def effective_long_lived_path(
        artifact_type: str,
        configured_path: Any,
    ) -> str | None:
        planned = sorted(
            {
                str(
                    operation.get("to_path")
                    if operation.get("action") == "move"
                    else operation.get("path")
                )
                for operation in operations
                if isinstance(operation.get("long_lived_artifact"), Mapping)
                and operation["long_lived_artifact"].get("artifact_type")
                == artifact_type
                and operation.get("action") != "delete"
            }
        )
        if len(planned) > 1:
            issues.append(
                f"同一评估只能计划一个 {artifact_type} 长期权威路径"
            )
        if planned:
            return planned[0]
        normalized = str(configured_path or "").strip()
        return normalized or None

    effective_domain_model_path = effective_long_lived_path(
        "domain_model",
        project_authority_paths.get("project_domain_model_path"),
    )
    effective_alignment_path = effective_long_lived_path(
        "domain_alignment",
        project_authority_paths.get("project_implementation_alignment_path"),
    )
    domain_fact_changes = _validate_domain_fact_changes(
        value.get("domain_fact_changes", []),
        candidate_context=candidate_context,
        known_refs=known_refs,
        known_domain_model_id=domain_model_id,
        known_domain_fact_ids=set((known_domain_fact_locations or {}).keys()),
        known_domain_fact_paths=dict(known_domain_fact_locations or {}),
        investigation_commit=domain_commit,
        operations=operations,
        domain_model_path=effective_domain_model_path,
        issues=issues,
        domain_repository_id=domain_repository_id,
    )
    method_applications = _validate_method_applications(
        value.get("method_applications", []),
        candidate_context=candidate_context,
        change_kind=change_kind,
        impact_scope=impact_scope,
        profile=profile_value,
        known_refs=known_refs,
        known_baseline_refs=set(known_baseline_refs or set()),
        known_domain_model_id=domain_model_id,
        known_domain_fact_ids=set(
            (known_domain_fact_locations or {}).keys()
        ),
        domain_fact_changes=domain_fact_changes,
        investigation_commit=domain_commit,
        target_refs=method_target_refs,
        operations=operations,
        baseline_path=baseline_path or None,
        domain_model_path=effective_domain_model_path,
        alignment_path=effective_alignment_path,
        issues=issues,
        baseline_repository_id=baseline_repository_id,
        alignment_repository_id=authority_repositories.get("implementation_alignment", default_repository_id),
    )

    coverage_targets = (
        direction_targets["acceptance"]
        | direction_targets["constraints"]
        | _field_refs("risk_assessments", risk_assessments)
        | set(behavior_examples)
    )
    commands: list[dict[str, Any]] = []
    for index, command in enumerate(
        _list(
            value.get("verification_commands", []),
            "verification_commands",
            issues,
        )
    ):
        path = f"verification_commands[{index}]"
        if not isinstance(command, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            command,
            required={"argv", "cwd", "run_kind", "covers", "reason"},
            optional={"optional_timeout", "case_report", "repository_id", "input_repository_ids", "dependency_checks"},
            path=path,
            issues=issues,
        )
        argv = command.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(arg, str) or not arg for arg in argv)
        ):
            issues.append(f"{path}.argv 必须是非空字符串数组")
        cwd = _text(command.get("cwd"), f"{path}.cwd", issues)
        cwd_path = PurePosixPath(cwd.replace("\\", "/")) if cwd else None
        if (
            cwd_path is None
            or cwd_path.is_absolute()
            or ".." in cwd_path.parts
            or ":" in cwd
            or bool(
                cwd_path.parts
                and cwd_path.parts[0].casefold() in _FORBIDDEN_REPOSITORY_ROOTS
            )
        ):
            issues.append(f"{path}.cwd 必须是仓库内相对目录")
        run_kind = _enum(
            command.get("run_kind"),
            f"{path}.run_kind",
            RUN_KINDS,
            issues,
        )
        covers = _string_list(
            command.get("covers"),
            f"{path}.covers",
            issues,
            required=True,
        )
        for ref in covers:
            if ref not in coverage_targets:
                issues.append(f"{path}.covers 引用了未知验证目标：{ref}")
        timeout = command.get("optional_timeout")
        if timeout is not None:
            timeout = _number(
                timeout,
                f"{path}.optional_timeout",
                issues,
                minimum=0,
                maximum=3600,
                exclusive_minimum=True,
            )
        normalized = {
            "argv": deepcopy(argv),
            "repository_id": command.get("repository_id"),
            "cwd": cwd,
            "run_kind": run_kind,
            "covers": list(dict.fromkeys(covers)),
            "reason": _text(
                command.get("reason"), f"{path}.reason", issues
            ),
        }
        if timeout is not None:
            normalized["optional_timeout"] = timeout
        if "input_repository_ids" in command:
            selected_inputs = command["input_repository_ids"]
            declared = {entry["repository_id"] for entry in (repository_scope or {}).get("repositories", [])}
            if not isinstance(selected_inputs, list) or not selected_inputs or any(not isinstance(identifier, (str, type(None))) for identifier in selected_inputs):
                issues.append(f"{path}.input_repository_ids must be a nonempty repository list")
            elif len(selected_inputs) != len(set(selected_inputs)) or set(selected_inputs) - declared or command.get("repository_id") not in selected_inputs:
                issues.append(f"{path}.input_repository_ids must include its execution repository and only declared inputs")
            else:
                normalized["input_repository_ids"] = list(selected_inputs)
        if "dependency_checks" in command:
            try:
                normalized["dependency_checks"] = normalize_dependency_checks(command["dependency_checks"])
            except ValueError as error:
                issues.append(f"{path}: {error}")
        if "case_report" in command:
            try:
                normalized["case_report"] = normalize_config(command["case_report"], examples=behavior_examples)
                normalized["case_report"].pop("example_fingerprints")
                normalized["covers"] = list(dict.fromkeys([
                    *normalized["covers"],
                    *(item["example_ref"] for item in normalized["case_report"]["bindings"]),
                ]))
            except TestCaseEvidenceError as error:
                issues.append(f"{path}.case_report: {error}")
        bound_examples = {item["example_ref"] for item in normalized.get("case_report", {}).get("bindings", [])}
        unbound_examples = set(normalized["covers"]) & set(behavior_examples) - bound_examples
        if unbound_examples:
            issues.append(f"{path} 的行为例子覆盖必须有逐用例报告关联：" + ", ".join(sorted(unbound_examples)))
        commands.append(normalized)

    verification_reviews = []
    try:
        verification_reviews = validate_reviews(
            value.get("verification_reviews", []), targets=coverage_targets - set(example_parents(behavior_examples)),
            commands=commands, known_evidence=set(known_refs),
        )
    except VerificationTargetError as error:
        issues.append(str(error) + (f"：{error.details}" if error.details else ""))
    verification_not_required_reason: str | None = None
    if commands:
        if "verification_not_required_reason" in value:
            issues.append(
                "已有 verification_commands 时不得声明 verification_not_required_reason"
            )
    else:
        verification_not_required_reason = _text(
            value.get("verification_not_required_reason"),
            "verification_not_required_reason",
            issues,
        )

    raw_delivery = value.get("delivery_plan")
    delivery_plan: dict[str, Any] | None = None
    if raw_delivery is not None:
        if not isinstance(raw_delivery, Mapping):
            issues.append("delivery_plan 必须是对象或 null")
            raw_delivery = {}
        _check_fields(
            raw_delivery,
            required={
                "expected_outcome",
                "rollback_or_recovery",
                "limitations",
                "evidence_refs",
            },
            optional={"repository_order"},
            path="delivery_plan",
            issues=issues,
        )
        limitations = [
            _text(item, f"delivery_plan.limitations[{index}]", issues)
            for index, item in enumerate(
                _list(
                    raw_delivery.get("limitations"),
                    "delivery_plan.limitations",
                    issues,
                )
            )
        ]
        delivery_plan = {
            "expected_outcome": _text(
                raw_delivery.get("expected_outcome"),
                "delivery_plan.expected_outcome",
                issues,
            ),
            "rollback_or_recovery": _text(
                raw_delivery.get("rollback_or_recovery"),
                "delivery_plan.rollback_or_recovery",
                issues,
            ),
            "limitations": limitations,
            "evidence_refs": _evidence_refs(
                raw_delivery.get("evidence_refs"),
                "delivery_plan.evidence_refs",
                issues,
                known_refs,
            ),
        }
        modified = list(dict.fromkeys(operation.get("repository_id") for operation in operations))
        order = raw_delivery.get("repository_order")
        if order is None and len(modified) > 1:
            issues.append("多仓库交付计划必须明确 repository_order")
            order = []
        elif order is None:
            order = modified
        if (not isinstance(order, list) or any(not isinstance(identifier, (str, type(None))) for identifier in order)
                or len(order) != len(modified) or len(set(order)) != len(order) or set(order) != set(modified)):
            issues.append("delivery_plan.repository_order 必须恰好覆盖各修改仓库且不重复")
        delivery_plan["repository_order"] = deepcopy(order)

    unknowns: list[dict[str, Any]] = []
    for index, item in enumerate(
        _list(
            value.get("unknowns_and_limitations", []),
            "unknowns_and_limitations",
            issues,
        )
    ):
        path = f"unknowns_and_limitations[{index}]"
        if not isinstance(item, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _check_fields(
            item,
            required={"statement", "impact", "handling", "evidence_refs"},
            path=path,
            issues=issues,
        )
        unknowns.append(
            {
                "statement": _text(
                    item.get("statement"), f"{path}.statement", issues
                ),
                "impact": _text(item.get("impact"), f"{path}.impact", issues),
                "handling": _text(
                    item.get("handling"), f"{path}.handling", issues
                ),
                "evidence_refs": _evidence_refs(
                    item.get("evidence_refs"),
                    f"{path}.evidence_refs",
                    issues,
                    known_refs,
                ),
            }
        )

    if impact_scope["unknown"] and not unknowns:
        issues.append(
            "impact_scope 存在 unknown 时必须说明 unknowns_and_limitations"
        )

    raw_assurance = value.get("requested_assurance")
    if not isinstance(raw_assurance, Mapping):
        issues.append("requested_assurance 必须是对象")
        raw_assurance = {}
    _check_fields(
        raw_assurance,
        required={"band", "reason"},
        path="requested_assurance",
        issues=issues,
    )
    requested_band = _enum(
        raw_assurance.get("band"),
        "requested_assurance.band",
        BANDS,
        issues,
    )
    requested_assurance = {
        "band": requested_band,
        "reason": _text(
            raw_assurance.get("reason"), "requested_assurance.reason", issues
        ),
    }

    valid_implements_refs = {
        *direction_targets["requirements"],
        *direction_targets["acceptance"],
        *direction_targets["constraints"],
        *_field_refs("design_decisions", design_decisions),
        *_field_refs("domain_fact_changes", domain_fact_changes),
        *_field_refs("method_applications", method_applications),
        *_field_refs("adr_plans", adr_plans),
    }
    try:
        change_planning = validate_change_planning(
            value,
            work_item_id=current_work_item_id,
            investigation_ref=investigation_ref,
            formal_implementation=formal,
            change_kind=change_kind,
            impact_scope=impact_scope,
            operations=operations,
            verification_commands=commands,
            known_authorities=known_authority_artifacts,
            known_evidence_refs=set(known_refs),
            known_decision_refs={
                "direction",
                *{
                    reference
                    for reference in (known_baseline_refs or set())
                    if reference.startswith("baseline:authority:")
                    and reference.endswith(":confirmed:current")
                },
            },
            valid_implements_refs=valid_implements_refs,
        )
    except ChangePlanningError as error:
        issues.extend(error.issues)
        change_planning = {
            "authority_change_set": None,
            "semantic_review": None,
            "implementation_slices": [],
            "owner_view": {},
        }

    _validate_domain_fact_authority_change_alignment(
        domain_fact_changes,
        change_planning["authority_change_set"],
        issues,
    )

    normalized = {
        "schema_version": ASSESSMENT_SCHEMA,
        "repository_scope": repository_scope,
        "assessment_id": assessment_id,
        "assessment_revision": revision,
        "direction_ref": direction_ref,
        "investigation_ref": investigation_ref,
        "change_context": change_context,
        "source_references": source_references,
        "impact_scope": impact_scope,
        "domain_fact_changes": domain_fact_changes,
        "authority_change_set": change_planning["authority_change_set"],
        "semantic_review": change_planning["semantic_review"],
        "method_applications": method_applications,
        "risk_assessments": risk_assessments,
        "alternatives_and_tradeoffs": alternatives,
        "design_decisions": design_decisions,
        "operations": operations,
        "implementation_slices": change_planning["implementation_slices"],
        "adr_plans": adr_plans,
        "verification_commands": commands,
        "verification_reviews": verification_reviews,
        "external_observation_provider_plans": (
            external_observation_provider_plans
        ),
        "delivery_plan": delivery_plan,
        "unknowns_and_limitations": unknowns,
        "requested_assurance": requested_assurance,
        "owner_view": change_planning["owner_view"],
    }
    if verification_not_required_reason is not None:
        normalized["verification_not_required_reason"] = (
            verification_not_required_reason
        )
    _rule_results(normalized, direction, profile_value, issues)
    if issues:
        raise EngineeringGovernanceError(issues)
    return normalized


def _max_band(first: str, second: str) -> str:
    return first if _BAND_INDEX[first] >= _BAND_INDEX[second] else second


def _risk_band(risk_assessments: list[dict[str, Any]]) -> str:
    band = "A0"
    for index, risk in enumerate(risk_assessments):
        consequence = str(risk.get("consequence") or "").strip()
        likelihood = str(risk.get("likelihood") or "").strip()
        uncertainty = str(risk.get("uncertainty") or "").strip()
        reversibility = str(risk.get("reversibility") or "").strip()
        if consequence not in {"low", "medium", "high", "critical"}:
            raise EngineeringGovernanceError(
                [f"risk_assessments[{index}].consequence 无效"]
            )
        if likelihood not in {"low", "medium", "high"}:
            raise EngineeringGovernanceError(
                [f"risk_assessments[{index}].likelihood 无效"]
            )
        if uncertainty not in {"low", "medium", "high"}:
            raise EngineeringGovernanceError(
                [f"risk_assessments[{index}].uncertainty 无效"]
            )
        if reversibility not in {
            "easy",
            "moderate",
            "difficult",
            "irreversible",
        }:
            raise EngineeringGovernanceError(
                [f"risk_assessments[{index}].reversibility 无效"]
            )
        consequence_band = {
            "low": "A0",
            "medium": "A2",
            "high": "A3",
            "critical": "A4",
        }[consequence]
        uncertainty_band = {
            "low": "A0",
            "medium": "A2",
            "high": "A3",
        }[uncertainty]
        reversibility_band = {
            "easy": "A0",
            "moderate": "A2",
            "difficult": "A3",
            "irreversible": "A4",
        }[reversibility]
        likelihood_band = {
            "low": "A0",
            "medium": "A1",
            "high": "A2",
        }[likelihood]
        band = _max_band(band, consequence_band)
        band = _max_band(band, likelihood_band)
        band = _max_band(band, uncertainty_band)
        band = _max_band(band, reversibility_band)
        if risk.get("external_assurance_required") is True:
            band = "A4"
    return band


def _compile_method_applications(
    assessment: Mapping[str, Any],
    profile: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project only explicit coding-agent method choices into plan facts."""

    impact = _impact_by_dimension(assessment["impact_scope"])
    methods = {
        method["method_id"]: method
        for method in profile.get("engineering_methods", [])
    }
    adoptions = {
        adoption["method_id"]: adoption
        for adoption in profile.get("project_method_adoptions", [])
    }
    projected: list[dict[str, Any]] = []
    for application_index, application in enumerate(
        assessment["method_applications"]
    ):
        method_id = application["method_id"]
        method = methods[method_id]
        triggered_by = [
            f"impact_scope.{dimension}:{impact[dimension]['status']}"
            for dimension in method["consider_when"]
            if dimension in impact
            and impact[dimension]["status"] in {"affected", "unknown"}
        ]
        adoption = adoptions.get(method_id)
        project_status = (
            adoption.get("status") if adoption is not None else "not_assessed"
        )
        adoption_change = application.get("adoption_change")
        planned_use_refs = [
            f"method_applications[{application_index}].planned_uses[{index}]"
            for index, _ in enumerate(application["planned_uses"])
        ]
        actual_result_requirements = {
            "use_ids": [
                str(use["use_id"])
                for use in application["planned_uses"]
            ],
        }
        projected.append(
            {
                "method_id": method_id,
                "project_status": project_status,
                "decision": application["decision"],
                "decision_source": "coding_agent_assessment",
                "triggered_by": triggered_by,
                "purpose": application["purpose"],
                "planned_use_refs": planned_use_refs,
                "domain_fact_refs": deepcopy(application["domain_fact_refs"]),
                "actual_result_requirements": actual_result_requirements,
                "adoption_change": deepcopy(adoption_change),
                "machine_validated": True,
            }
        )
    return projected


def _compile_verification_commands(
    commands: Sequence[Mapping[str, Any]],
    implementation_slices: Sequence[Mapping[str, Any]],
    *, examples: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Deduplicate commands only when they belong to the same run stage."""

    normalized: list[dict[str, Any]] = []
    source_slice_ids: dict[int, str] = {}
    for item in implementation_slices:
        slice_id = str(item.get("slice_id") or "")
        for reference in item.get("verification_command_refs") or []:
            match = re.fullmatch(r"verification_commands\[([0-9]+)\]", str(reference))
            if match is not None:
                source_slice_ids[int(match.group(1))] = slice_id
    positions: dict[tuple[Any, ...], int] = {}
    for index, raw in enumerate(commands):
        raw = deepcopy(dict(raw))
        if "case_report" in raw:
            raw["case_report"] = normalize_config(raw["case_report"], examples=examples or {})
        cwd = str(raw["cwd"]).replace("\\", "/")
        cwd = "." if cwd in {"", "."} else PurePosixPath(cwd).as_posix()
        key = (
            raw.get("repository_id"),
            tuple(raw["argv"]),
            cwd,
            str(raw["run_kind"]),
            source_slice_ids.get(index, ""),
            tuple(raw.get("input_repository_ids") or []),
            json.dumps(raw.get("dependency_checks") or [], sort_keys=True),
        )
        existing_index = positions.get(key)
        if existing_index is None:
            normalized.append(
                {
                    "command_id": f"VC-{len(normalized) + 1:03d}",
                    "repository_id": raw.get("repository_id"),
                    "argv": list(raw["argv"]),
                    "cwd": cwd,
                    "run_kind": str(raw["run_kind"]),
                    "covers": list(dict.fromkeys(raw["covers"])),
                    "reasons": [str(raw["reason"])],
                    "optional_timeout": raw.get("optional_timeout"),
                    "source_command_indexes": [index],
                }
            )
            positions[key] = len(normalized) - 1
            if "case_report" in raw:
                normalized[-1]["case_report"] = deepcopy(raw["case_report"])
            for field in ("input_repository_ids", "dependency_checks"):
                if field in raw:
                    normalized[-1][field] = deepcopy(raw[field])
            continue
        existing = normalized[existing_index]
        if "case_report" in raw:
            try:
                existing["case_report"] = merge_configs(existing.get("case_report"), raw["case_report"])
            except TestCaseEvidenceError as error:
                raise EngineeringGovernanceError([str(error)]) from error
        existing["covers"] = list(
            dict.fromkeys([*existing["covers"], *raw["covers"]])
        )
        existing["reasons"] = list(
            dict.fromkeys([*existing["reasons"], str(raw["reason"])])
        )
        existing["source_command_indexes"].append(index)
        timeouts = [
            item
            for item in (
                existing.get("optional_timeout"),
                raw.get("optional_timeout"),
            )
            if item is not None
        ]
        existing["optional_timeout"] = max(timeouts) if timeouts else None
    return normalized


def _program_identities(program: str) -> set[str]:
    """Return exact executable identities without guessing command meaning."""

    normalized = program.strip().strip('"').replace("\\", "/").casefold()
    name = PurePosixPath(normalized).name
    stem = PurePosixPath(name).stem
    return {item for item in (normalized, name, stem) if item}


def _declared_program_matches(
    declared: str,
    actual: str,
    project_dir: str | Path,
) -> bool:
    """Match an explicit path exactly; bare tool names match by identity."""

    normalized_declared = declared.replace("\\", "/")
    if "/" not in normalized_declared and not Path(declared).is_absolute():
        return bool(_program_identities(declared) & _program_identities(actual))
    project = Path(project_dir).resolve()
    declared_path = Path(declared).expanduser()
    actual_path = Path(actual).expanduser()
    expected = (
        declared_path.resolve()
        if declared_path.is_absolute()
        else (project / declared_path).resolve()
    )
    observed = (
        actual_path.resolve()
        if actual_path.is_absolute()
        else (project / actual_path).resolve()
    )
    return str(expected).casefold() == str(observed).casefold()


def _verification_policy_decision(
    commands: list[dict[str, Any]],
    *,
    profile: Mapping[str, Any],
    project_dir: str | Path,
    repository_roots: Mapping[str | None, str] | None = None,
) -> dict[str, Any]:
    """Bind exact plan commands to an already supplied project policy."""

    configured = profile.get("verification_command_policy")
    policy_ref = profile.get("project_engineering_policy_ref")
    source_kind = "project_engineering_policy"
    if isinstance(configured, Mapping) and isinstance(policy_ref, Mapping):
        allowed_programs = [
            deepcopy(dict(item))
            for item in configured.get("allowed_programs") or []
            if isinstance(item, Mapping)
        ]
        forbidden = [
            str(item)
            for item in configured.get("forbidden_agent_program_names") or []
        ]
        wrapper_policy = str(configured.get("wrapper_policy") or "")
        working_directory_policy = str(
            configured.get("working_directory_policy") or ""
        )
        plan_binding_required = configured.get("plan_binding_required")
        policy_id = str(policy_ref.get("policy_id") or "")
        revision_id = str(policy_ref.get("revision_id") or "")
        observed_commit = policy_ref.get("observed_commit")
    else:
        # A project being created has no adopted long-lived policy yet.  The
        # exact command list becomes usable only after the whole plan is
        # confirmed; opaque shell wrappers remain unavailable in this path.
        source_kind = "confirmed_plan_bootstrap"
        allowed_programs = []
        seen_programs: set[str] = set()
        for command in commands:
            program = str(command["argv"][0])
            if program in seen_programs:
                continue
            seen_programs.add(program)
            allowed_programs.append(
                {
                    "program": program,
                    "purpose": "只执行该已确认工程方案中的精确验证命令。",
                    "argument_policy": "exact_plan_only",
                }
            )
        forbidden = list(_DEFAULT_FORBIDDEN_AGENT_PROGRAM_NAMES)
        wrapper_policy = "forbidden_unless_exactly_approved"
        working_directory_policy = "project_or_authorized_worktree_only"
        plan_binding_required = True
        policy_id = "strixnova.confirmed-plan-bootstrap"
        revision_id = str(profile.get("profile_version") or "unversioned")
        observed_commit = None

    issues: list[str] = []
    forbidden_identities = {
        identity
        for name in forbidden
        for identity in _program_identities(name)
    }
    for command in commands:
        argv = list(command["argv"])
        if _program_identities(argv[0]) & forbidden_identities:
            issues.append(
                f"{command['command_id']} 的首个程序被工程政策明确禁止"
            )
            continue
        nested_forbidden = sorted(
            {
                token
                for token in argv[1:]
                if _program_identities(token) & forbidden_identities
            }
        )
        if nested_forbidden:
            issues.append(
                f"{command['command_id']} 试图通过包装参数启动被禁止的代理程序"
            )
            continue
        matched = next(
            (
                item
                for item in allowed_programs
                if _declared_program_matches(
                    str(item.get("program") or ""),
                    argv[0],
                    (repository_roots or {}).get(command.get("repository_id"), project_dir),
                )
            ),
            None,
        )
        if matched is None:
            issues.append(
                f"{command['command_id']} 的首个程序不在精确项目验证政策中"
            )
            continue
        identities = _program_identities(argv[0])
        if source_kind == "confirmed_plan_bootstrap" and (
            identities & _OPAQUE_COMMAND_WRAPPER_NAMES
        ):
            issues.append(
                f"{command['command_id']} 在项目政策建立前不得使用不透明命令包装器"
            )
            continue
        command["approved_program"] = {
            "declared_program": str(matched["program"]),
            "resolved_program": argv[0],
            "purpose": str(matched["purpose"]),
            "argument_policy": str(matched["argument_policy"]),
        }

    if issues:
        raise EngineeringGovernanceError(issues)
    return {
        "schema_version": VERIFICATION_POLICY_DECISION_SCHEMA,
        "source_kind": source_kind,
        "policy_id": policy_id,
        "policy_revision_id": revision_id,
        "observed_commit": observed_commit,
        "forbidden_agent_program_names": forbidden,
        "wrapper_policy": wrapper_policy,
        "working_directory_policy": working_directory_policy,
        "plan_binding_required": plan_binding_required,
    }


def compile_engineering_plan(
    assessment: Mapping[str, Any],
    *,
    project_dir: str | Path,
    candidate_context: Mapping[str, Any],
    direction: Mapping[str, Any],
    direction_version: int,
    profile: Mapping[str, Any],
    known_baseline_refs: set[str] | None = None,
    domain_model_id: str | None = None,
    known_domain_fact_locations: Mapping[str, str] | None = None,
    known_authority_artifacts: Mapping[str, Mapping[str, str]] | None = None,
    work_item_id: str,
) -> dict[str, Any]:
    """Apply deterministic rules to one validated coding-agent assessment."""

    if not isinstance(profile, Mapping):
        raise EngineeringGovernanceError(["工程治理上下文缺少工程政策摘要"])
    profile_value = deepcopy(dict(profile))
    normalized = validate_assessment(
        assessment,
        project_dir=project_dir,
        candidate_context=candidate_context,
        work_item_id=work_item_id,
        direction=direction,
        direction_version=direction_version,
        profile=profile_value,
        known_baseline_refs=known_baseline_refs,
        domain_model_id=domain_model_id,
        known_domain_fact_locations=known_domain_fact_locations,
        known_authority_artifacts=known_authority_artifacts,
    )
    rule_issues: list[str] = []
    direction_targets = _direction_target_refs(direction, rule_issues)
    applicable_rules = _rule_results(
        normalized,
        direction,
        profile_value,
        rule_issues,
    )
    if rule_issues:
        raise EngineeringGovernanceError(rule_issues)
    band = (
        "A1"
        if normalized["change_context"]["formal_implementation"]
        else "A0"
    )
    for rule in applicable_rules:
        band = _max_band(band, str(rule["minimum_assurance"]))
    band = _max_band(
        band,
        _risk_band(normalized["risk_assessments"]),
    )
    band = _max_band(
        band,
        normalized["requested_assurance"]["band"],
    )
    source_ids = {
        str(source["source_id"]) for source in profile_value["sources"]
    }
    unknown_rule_sources = sorted(
        {
            str(source_id)
            for rule in applicable_rules
            for source_id in rule["source_ids"]
            if str(source_id) not in source_ids
        }
    )
    if unknown_rule_sources:
        raise EngineeringGovernanceError(
            [
                "适用治理规则引用未知来源："
                + ", ".join(unknown_rule_sources)
            ]
        )
    normalized_commands = _compile_verification_commands(
        normalized["verification_commands"],
        normalized["implementation_slices"],
        examples=example_catalog(direction),
    )
    try:
        implementation_slices = compile_implementation_slices(
            normalized["implementation_slices"],
            normalized_commands,
            normalized["operations"],
        )
    except ChangePlanningError as error:
        raise EngineeringGovernanceError(error.issues) from error
    verification_policy_decision = _verification_policy_decision(
        normalized_commands,
        profile=profile_value,
        project_dir=project_dir,
        repository_roots={entry["repository_id"]: entry["path"] for entry in candidate_context["repository_context"].get("repository_roots", [])},
    )
    method_applications = _compile_method_applications(
        normalized,
        profile_value,
    )
    trace_refs: list[str] = []
    for field in (
        "risk_assessments",
        "alternatives_and_tradeoffs",
        "design_decisions",
        "operations",
        "adr_plans",
        "unknowns_and_limitations",
        "domain_fact_changes",
        "method_applications",
        "implementation_slices",
        "external_observation_provider_plans",
    ):
        trace_refs.extend(sorted(_field_refs(field, normalized[field])))
    trace_refs.extend(_impact_trace_refs(normalized["impact_scope"]))
    trace_refs.extend(
        sorted(
            direction_targets["requirements"]
            | direction_targets["constraints"]
            | direction_targets["acceptance"]
        )
    )
    if normalized["delivery_plan"] is not None:
        trace_refs.append("delivery_plan")
    if normalized["authority_change_set"] is not None:
        trace_refs.append("authority_change_set")
    if normalized["semantic_review"] is not None:
        trace_refs.append("semantic_review")
    trace_refs.append("owner_view")
    if normalized.get("verification_not_required_reason"):
        trace_refs.append("verification_not_required_reason")
    return {
        "schema_version": PLAN_SCHEMA,
        "repository_scope": deepcopy(normalized["repository_scope"]),
        "plan_id": (
            f"PLAN-{normalized['assessment_id']}-"
            f"R{normalized['assessment_revision']}"
        ),
        "assessment_ref": {
            "work_item_id": work_item_id,
            "assessment_id": normalized["assessment_id"],
            "assessment_revision": normalized["assessment_revision"],
        },
        "investigation_ref": normalized["investigation_ref"],
        "direction_ref": deepcopy(normalized["direction_ref"]),
        "change_context": deepcopy(normalized["change_context"]),
        "impact_scope": deepcopy(normalized["impact_scope"]),
        "authority_change_set": deepcopy(normalized["authority_change_set"]),
        "semantic_review": deepcopy(normalized["semantic_review"]),
        # Repository operations and delivery intent are execution-critical
        # parts of the confirmed plan.  Keeping them only in the authored
        # assessment would make slice execution and result reconciliation
        # depend on an unconfirmed upstream record.
        "operations": deepcopy(normalized["operations"]),
        "implementation_slices": implementation_slices,
        "delivery_plan": deepcopy(normalized["delivery_plan"]),
        "owner_view": deepcopy(normalized["owner_view"]),
        "domain_fact_change_refs": [
            f"domain_fact_changes[{index}]"
            for index, _ in enumerate(normalized["domain_fact_changes"])
        ],
        "actual_result_requirements": {
            "domain_fact_changes": [
                {
                    "target_ref": deepcopy(change["target_ref"]),
                    "planned_disposition": str(change["disposition"]),
                }
                for change in normalized["domain_fact_changes"]
            ]
        },
        "method_applications": method_applications,
        "assurance_band": band,
        "trace_refs": trace_refs,
        "verification_commands": normalized_commands,
        "verification_targets": compile_targets(normalized_commands, normalized["verification_reviews"], examples=example_catalog(direction)),
        "behavior_examples": example_catalog(direction),
        "external_observation_provider_plans": deepcopy(
            normalized["external_observation_provider_plans"]
        ),
        "verification_policy_decision": verification_policy_decision,
        "applicable_rules": applicable_rules,
        "governance_profile": {
            "profile_id": profile_value["profile_id"],
            "profile_version": profile_value["profile_version"],
            "project_tailoring": deepcopy(
                profile_value.get("project_tailoring") or []
            ),
        },
        "semantic_content_machine_proven": False,
    }


__all__ = [
    "ASSESSMENT_SCHEMA",
    "BANDS",
    "EngineeringGovernanceError",
    "IMPACT_DIMENSIONS",
    "INFORMATION_KINDS",
    "PLAN_SCHEMA",
    "VERIFICATION_POLICY_DECISION_SCHEMA",
    "compile_engineering_plan",
    "validate_assessment",
]
