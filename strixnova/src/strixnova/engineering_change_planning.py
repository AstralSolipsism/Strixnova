"""Deterministic contracts for authority changes, reviews, and implementation slices.

The coding agent authors every semantic statement.  This module only checks
identity, exact baselines, references, dependency shape, declared coverage,
and state claims that can be decided without understanding natural language.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from pathlib import PurePosixPath
import re
from typing import Any


AUTHORITY_CHANGE_SET_SCHEMA = "strixnova.authority-change-set.v1"
SEMANTIC_REVIEW_SCHEMA = "strixnova.semantic-review.v1"
IMPLEMENTATION_SLICE_SCHEMA = "strixnova.implementation-slice.v1"
OWNER_VIEW_SCHEMA = "strixnova.owner-view.v1"

AUTHORITY_KINDS = (
    "product_definition",
    "domain_model",
    "target_architecture",
    "implementation_alignment",
)

SEMANTIC_REVIEW_PERSPECTIVES = (
    "product_to_domain_coverage",
    "terminology_authority_rules_invariants",
    "domain_to_architecture_disposition",
    "plan_and_slice_coverage",
    "orphan_and_authority_inversion",
    "scenario_coverage",
    "nonfunctional_and_risk_coverage",
    "evidence_and_claim_boundaries",
)

_AUTHORITY_ARTIFACT_TYPES = {
    "product_governance": "product_definition",
    "domain_model": "domain_model",
    "architecture": "target_architecture",
    "domain_alignment": "implementation_alignment",
}

_DOWNSTREAM_REQUIREMENTS = {
    "product_definition": (
        "domain_model",
        "target_architecture",
        "implementation_alignment",
    ),
    "domain_model": (
        "target_architecture",
        "implementation_alignment",
    ),
    "target_architecture": ("implementation_alignment",),
    "implementation_alignment": (),
}

_REVISION_PATTERNS = {
    "product_definition": re.compile(r"^REVISION-[0-9A-F]{16}$"),
    "domain_model": re.compile(r"^MODELREV-[0-9A-F]{16}$"),
    "target_architecture": re.compile(r"^ARCHREV-[0-9A-F]{16}$"),
    "implementation_alignment": re.compile(r"^ALIGNREV-[0-9A-F]{16}$"),
}

_ID_PATTERNS = {
    "product_definition": re.compile(r"^PRODUCT-[0-9A-F]{16}$"),
    "domain_model": re.compile(r"^MODEL-[0-9A-F]{16}$"),
    "target_architecture": re.compile(r"^ARCH-[0-9A-F]{16}$"),
    "implementation_alignment": re.compile(r"^ALIGNMODEL-[0-9A-F]{16}$"),
}

_TARGET_REF_PATTERNS = {
    "product_definition": re.compile(
        r"^(?:PRODUCT|USER|PROBLEM|OUTCOME|CAPABILITY|NONGOAL|"
        r"CONSTRAINT|CRITERION|STAGE|DECISION)-[0-9A-F]{16}$"
    ),
    "domain_model": re.compile(r"^(?:MODEL|FACT)-[0-9A-F]{16}$"),
    "target_architecture": re.compile(
        r"^(?:ARCH|MODULE|INTERFACE|RELATION|CONSTRAINT|ARCHSTAGE)-"
        r"[0-9A-F]{16}$"
    ),
    "implementation_alignment": re.compile(
        r"^(?:ALIGNMODEL|DEVIATION)-[0-9A-F]{16}$"
    ),
}

_SLICE_ID = re.compile(r"^SLICE-[0-9]{3,}$")
_CHANGE_SET_ID = re.compile(r"^AUTHCHANGE-[0-9A-F]{16}$")
_CHANGE_ID = re.compile(r"^AUTHOP-[0-9]{3,}$")
_REVIEW_ID = re.compile(r"^SEMREVIEW-[0-9A-F]{16}$")
_FINDING_ID = re.compile(r"^FINDING-[0-9]{3,}$")
_OPERATION_REF = re.compile(r"^operations\[([0-9]+)\]$")
_VERIFICATION_REF = re.compile(r"^verification_commands\[([0-9]+)\]$")


class ChangePlanningError(ValueError):
    """One or more deterministic change-planning rules failed."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "工程变更规划输入无效")


def _text(value: Any, path: str, issues: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{path} 必须是非空字符串")
        return ""
    return value.strip()


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
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    if type(value) is not int or value < minimum:
        issues.append(f"{path} 必须是大于或等于 {minimum} 的整数")
        return 0
    if maximum is not None and value > maximum:
        issues.append(f"{path} 必须小于或等于 {maximum}")
    return value


def _list(value: Any, path: str, issues: list[str]) -> list[Any]:
    if not isinstance(value, list):
        issues.append(f"{path} 必须是数组")
        return []
    return value


def _string_list(
    value: Any,
    path: str,
    issues: list[str],
    *,
    required: bool = False,
    unique: bool = False,
) -> list[str]:
    values = [
        _text(item, f"{path}[{index}]", issues)
        for index, item in enumerate(_list(value, path, issues))
    ]
    if required and not values:
        issues.append(f"{path} 不能为空")
    if unique and len(values) != len(set(values)):
        issues.append(f"{path} 不能包含重复值")
    return values


def _enum(
    value: Any,
    path: str,
    allowed: Sequence[str] | set[str],
    issues: list[str],
) -> str:
    result = _text(value, path, issues)
    if result and result not in set(allowed):
        issues.append(f"{path} 必须是 " + "、".join(sorted(allowed)) + " 之一")
        return ""
    return result


def _fields(
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


def _repository_path(value: Any, path: str, issues: list[str]) -> str:
    raw = _text(value, path, issues).replace("\\", "/")
    candidate = PurePosixPath(raw)
    if (
        not raw
        or candidate.is_absolute()
        or ".." in candidate.parts
        or ":" in raw
        or not candidate.parts
        or candidate.parts[0].casefold() in {".git", ".strixnova"}
    ):
        issues.append(f"{path} 必须是仓库内安全相对路径")
        return ""
    return candidate.as_posix()


def _changed_authority_kinds(
    operations: Sequence[Mapping[str, Any]],
    known_authorities: Mapping[str, Mapping[str, Any]] | None,
) -> set[str]:
    """Return only revisions of authorities adopted at the investigation ref.

    A newly created long-lived artifact can use the same artifact type as an
    authority without being a revision of an already adopted authority.  The
    change-set rule therefore keys off the trusted adopted-authority context,
    never off the candidate's type label alone.
    """

    known_by_kind = _authority_by_kind(known_authorities)
    known_identity_to_kind = {
        str(authority.get("artifact_id") or ""): kind
        for kind, authority in known_by_kind.items()
    }
    known_path_to_kind = {
        str(path).replace("\\", "/"): kind
        for kind, authority in known_by_kind.items()
        for path in (
            authority.get("governed_paths")
            or [authority.get("path")]
        )
        if str(path or "").strip()
    }
    result: set[str] = set()
    for operation in operations:
        for field in ("path", "to_path"):
            kind = known_path_to_kind.get(
                str(operation.get(field) or "").replace("\\", "/")
            )
            if kind is not None and kind in AUTHORITY_KINDS:
                result.add(kind)
        artifact = operation.get("long_lived_artifact")
        if not isinstance(artifact, Mapping):
            continue
        authority_kind = _AUTHORITY_ARTIFACT_TYPES.get(
            str(artifact.get("artifact_type") or "")
        )
        artifact_id = str(artifact.get("artifact_id") or "")
        if (
            authority_kind is not None
            and known_identity_to_kind.get(artifact_id) == authority_kind
        ):
            result.add(authority_kind)
    return result


def _authority_by_kind(
    known_authorities: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    if known_authorities is None:
        return {}
    result: dict[str, dict[str, Any]] = {}
    for artifact_id, authority in known_authorities.items():
        if not isinstance(authority, Mapping):
            continue
        kind = str(authority.get("authority_kind") or "")
        if kind in AUTHORITY_KINDS:
            result[kind] = {"artifact_id": str(artifact_id), **dict(authority)}
    return result


def _validate_authority_ref(
    value: Any,
    *,
    path: str,
    candidate: bool,
    issues: list[str],
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        issues.append(f"{path} 必须是对象")
        return None
    required = {
        "authority_kind",
        "artifact_id",
        "revision_id",
        "path",
    }
    if candidate:
        required |= {
            "status",
            "supersedes_revision_id",
            "adoption_effect",
        }
    else:
        required |= {"status", "observed_commit"}
    _fields(value, required=required, optional={"repository_id"}, path=path, issues=issues)
    authority_kind = _enum(
        value.get("authority_kind"),
        f"{path}.authority_kind",
        AUTHORITY_KINDS,
        issues,
    )
    artifact_id = _text(value.get("artifact_id"), f"{path}.artifact_id", issues)
    revision_id = _text(value.get("revision_id"), f"{path}.revision_id", issues)
    if authority_kind:
        if artifact_id and not _ID_PATTERNS[authority_kind].fullmatch(artifact_id):
            issues.append(f"{path}.artifact_id 与权威类型不匹配")
        if revision_id and not _REVISION_PATTERNS[authority_kind].fullmatch(
            revision_id
        ):
            issues.append(f"{path}.revision_id 与权威类型不匹配")
    normalized: dict[str, Any] = {
        "authority_kind": authority_kind,
        "artifact_id": artifact_id,
        "revision_id": revision_id,
        "path": _repository_path(value.get("path"), f"{path}.path", issues),
    }
    if "repository_id" in value:
        normalized["repository_id"] = value["repository_id"]
    if candidate:
        normalized.update(
            {
                "status": _enum(
                    value.get("status"),
                    f"{path}.status",
                    {"draft", "ready_for_confirmation"},
                    issues,
                ),
                "supersedes_revision_id": _text(
                    value.get("supersedes_revision_id"),
                    f"{path}.supersedes_revision_id",
                    issues,
                ),
                "adoption_effect": _enum(
                    value.get("adoption_effect"),
                    f"{path}.adoption_effect",
                    {"not_adopted"},
                    issues,
                ),
            }
        )
    else:
        normalized.update(
            {
                "status": _enum(
                    value.get("status"),
                    f"{path}.status",
                    {"confirmed"},
                    issues,
                ),
                "observed_commit": _text(
                    value.get("observed_commit"),
                    f"{path}.observed_commit",
                    issues,
                ),
            }
        )
    return normalized


def _validate_authority_change_set(
    value: Any,
    *,
    work_item_id: str,
    investigation_ref: str,
    changed_authority_kinds: set[str],
    known_authorities: Mapping[str, Mapping[str, Any]] | None,
    known_evidence_refs: set[str],
    formal_implementation: bool,
    operations: Sequence[Mapping[str, Any]],
    issues: list[str],
) -> dict[str, Any] | None:
    if value is None:
        if changed_authority_kinds:
            issues.append(
                "修改现有产品、领域、目标架构或实现对齐时必须提交 authority_change_set"
            )
        return None
    if not isinstance(value, Mapping):
        issues.append("authority_change_set 必须是对象")
        return None
    if not changed_authority_kinds:
        issues.append(
            "当前操作没有修订现行核心权威，不应提交 authority_change_set"
        )
    _fields(
        value,
        required={
            "schema_version",
            "change_set_id",
            "work_item_id",
            "base_authorities",
            "candidate_authorities",
            "changes",
            "downstream_dispositions",
            "semantic_content_machine_proven",
        },
        path="authority_change_set",
        issues=issues,
    )
    if value.get("schema_version") != AUTHORITY_CHANGE_SET_SCHEMA:
        issues.append(
            "authority_change_set.schema_version 必须是 "
            + AUTHORITY_CHANGE_SET_SCHEMA
        )
    change_set_id = _text(
        value.get("change_set_id"), "authority_change_set.change_set_id", issues
    )
    if change_set_id and not _CHANGE_SET_ID.fullmatch(change_set_id):
        issues.append("authority_change_set.change_set_id 格式无效")
    submitted_work_item_id = _text(
        value.get("work_item_id"), "authority_change_set.work_item_id", issues
    )
    if submitted_work_item_id and submitted_work_item_id != work_item_id:
        issues.append("authority_change_set.work_item_id 不是当前 WorkItem")
    if value.get("semantic_content_machine_proven") is not False:
        issues.append(
            "authority_change_set.semantic_content_machine_proven 必须明确为 false"
        )

    known_by_kind = _authority_by_kind(known_authorities)
    known_target_owners: dict[str, set[str]] = {}
    for known_kind, authority in known_by_kind.items():
        for target in authority.get("target_refs") or []:
            known_target_owners.setdefault(str(target), set()).add(
                str(known_kind)
            )
    if set(known_by_kind) != set(AUTHORITY_KINDS):
        issues.append(
            "authority_change_set 无法取得产品、领域、目标架构和实现对齐的完整采用基线"
        )
    bases: list[dict[str, Any]] = []
    bases_by_kind: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(
        _list(value.get("base_authorities"), "authority_change_set.base_authorities", issues)
    ):
        base = _validate_authority_ref(
            raw,
            path=f"authority_change_set.base_authorities[{index}]",
            candidate=False,
            issues=issues,
        )
        if base is None:
            continue
        kind = str(base["authority_kind"])
        if kind in bases_by_kind:
            issues.append(f"authority_change_set.base_authorities 重复：{kind}")
        bases_by_kind[kind] = base
        bases.append(base)
        known = known_by_kind.get(kind)
        if known is None:
            issues.append(f"authority_change_set.base_authorities 引用了未采用权威：{kind}")
            continue
        if known.get("adoption_status") != "current":
            issues.append(
                f"authority_change_set.base_authorities 引用的权威尚未采用：{kind}"
            )
        expected = {
            "artifact_id": str(known.get("artifact_id") or ""),
            "revision_id": str(known.get("revision_id") or ""),
            "path": str(known.get("path") or ""),
            "status": str(known.get("revision_status") or ""),
            "observed_commit": known.get("observed_commit") or investigation_ref,
        }
        if "repository_id" in known:
            if "repository_id" in base and base["repository_id"] != known["repository_id"]:
                issues.append(f"authority_change_set.base_authorities[{index}].repository_id does not match the adopted authority")
            base["repository_id"] = known["repository_id"]
        for field, expected_value in expected.items():
            if base.get(field) != expected_value:
                issues.append(
                    f"authority_change_set.base_authorities[{index}].{field} "
                    "不是调查版本采用的精确权威事实"
                )
    if set(bases_by_kind) != set(AUTHORITY_KINDS):
        missing = sorted(set(AUTHORITY_KINDS) - set(bases_by_kind))
        extra = sorted(set(bases_by_kind) - set(AUTHORITY_KINDS))
        if missing:
            issues.append(
                "authority_change_set.base_authorities 缺少完整长期权威基线："
                + ", ".join(missing)
            )
        if extra:
            issues.append(
                "authority_change_set.base_authorities 包含非目标权威："
                + ", ".join(extra)
            )

    candidates: list[dict[str, Any]] = []
    candidates_by_kind: dict[str, dict[str, Any]] = {}
    raw_candidates = _list(
        value.get("candidate_authorities"),
        "authority_change_set.candidate_authorities",
        issues,
    )
    if not raw_candidates:
        issues.append("authority_change_set.candidate_authorities 不能为空")
    for index, raw in enumerate(
        raw_candidates
    ):
        candidate = _validate_authority_ref(
            raw,
            path=f"authority_change_set.candidate_authorities[{index}]",
            candidate=True,
            issues=issues,
        )
        if candidate is None:
            continue
        kind = str(candidate["authority_kind"])
        if kind in candidates_by_kind:
            issues.append(f"authority_change_set.candidate_authorities 重复：{kind}")
        candidates_by_kind[kind] = candidate
        candidates.append(candidate)
        base = bases_by_kind.get(kind)
        if base is not None:
            if "repository_id" in base:
                if "repository_id" in candidate and candidate["repository_id"] != base["repository_id"]:
                    issues.append(f"authority_change_set.candidate_authorities[{index}] cannot change repository ownership")
                candidate["repository_id"] = base["repository_id"]
            if candidate["artifact_id"] != base["artifact_id"]:
                issues.append(
                    f"authority_change_set.candidate_authorities[{index}] 不得更换权威身份"
                )
            root_operations = [
                operation
                for operation in operations
                if isinstance(operation.get("long_lived_artifact"), Mapping)
                and operation["long_lived_artifact"].get("artifact_id")
                == base["artifact_id"]
            ]
            if len(root_operations) != 1:
                issues.append(
                    f"authority_change_set.candidate_authorities[{index}] "
                    "必须有且只有一个同身份权威根文件操作"
                )
            else:
                root_operation = root_operations[0]
                if "repository_id" in base and root_operation.get("repository_id") != base["repository_id"]:
                    issues.append(f"authority_change_set.candidate_authorities[{index}] root operation belongs to another repository")
                source_path = str(root_operation.get("path") or "")
                effective_path = str(
                    (
                        root_operation.get("to_path")
                        if root_operation.get("action") == "move"
                        else root_operation.get("path")
                    )
                    or ""
                )
                if source_path != base["path"]:
                    issues.append(
                        f"authority_change_set.candidate_authorities[{index}] "
                        "根文件操作没有精确引用调查版本中的权威路径"
                    )
                if candidate["path"] != effective_path:
                    issues.append(
                        f"authority_change_set.candidate_authorities[{index}] "
                        "路径必须等于根文件操作的实际候选路径"
                    )
                if (
                    root_operation.get("action") != "move"
                    and candidate["path"] != base["path"]
                ):
                    issues.append(
                        f"authority_change_set.candidate_authorities[{index}] "
                        "只有显式 move 操作可以改变权威根路径"
                    )
            if candidate["supersedes_revision_id"] != base["revision_id"]:
                issues.append(
                    f"authority_change_set.candidate_authorities[{index}] 未精确承接当前修订"
                )
            if candidate["revision_id"] == base["revision_id"]:
                issues.append(
                    f"authority_change_set.candidate_authorities[{index}] 必须使用新修订身份"
                )
    if set(candidates_by_kind) != changed_authority_kinds:
        missing = sorted(changed_authority_kinds - set(candidates_by_kind))
        extra = sorted(set(candidates_by_kind) - changed_authority_kinds)
        if missing:
            issues.append(
                "authority_change_set.candidate_authorities 缺少已计划变更权威："
                + ", ".join(missing)
            )
        if extra:
            issues.append(
                "authority_change_set.candidate_authorities 声明了没有文件操作的权威："
                + ", ".join(extra)
            )

    changes: list[dict[str, Any]] = []
    introduced_target_owners: dict[str, set[str]] = {}
    introduced_target_counts: dict[str, int] = {}
    seen_change_ids: set[str] = set()
    kinds_with_changes: set[str] = set()
    raw_changes = _list(value.get("changes"), "authority_change_set.changes", issues)
    if not raw_changes:
        issues.append("authority_change_set.changes 不能为空")
    for index, raw in enumerate(raw_changes):
        path = f"authority_change_set.changes[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _fields(
            raw,
            required={
                "change_id",
                "authority_kind",
                "operation",
                "target_ref",
                "summary",
                "evidence_refs",
            },
            optional={"replacement_ref"},
            path=path,
            issues=issues,
        )
        change_id = _text(raw.get("change_id"), f"{path}.change_id", issues)
        if change_id and not _CHANGE_ID.fullmatch(change_id):
            issues.append(f"{path}.change_id 格式无效")
        if change_id in seen_change_ids:
            issues.append(f"authority_change_set.changes 重复身份：{change_id}")
        seen_change_ids.add(change_id)
        kind = _enum(
            raw.get("authority_kind"),
            f"{path}.authority_kind",
            AUTHORITY_KINDS,
            issues,
        )
        operation = _enum(
            raw.get("operation"),
            f"{path}.operation",
            {"add", "modify", "retire", "rename"},
            issues,
        )
        replacement_ref: str | None = None
        if operation == "rename":
            replacement_ref = _text(
                raw.get("replacement_ref"), f"{path}.replacement_ref", issues
            )
        elif "replacement_ref" in raw:
            issues.append(f"{path}.replacement_ref 只适用于 rename")
        evidence_refs = _string_list(
            raw.get("evidence_refs"),
            f"{path}.evidence_refs",
            issues,
            required=True,
            unique=True,
        )
        unknown_refs = sorted(set(evidence_refs) - known_evidence_refs)
        if unknown_refs:
            issues.append(
                f"{path}.evidence_refs 引用了未知证据：" + ", ".join(unknown_refs)
            )
        if kind and kind not in candidates_by_kind:
            issues.append(f"{path} 没有对应候选权威修订")
        kinds_with_changes.add(kind)
        target_ref = _text(raw.get("target_ref"), f"{path}.target_ref", issues)
        if kind and target_ref:
            if _TARGET_REF_PATTERNS[kind].fullmatch(target_ref) is None:
                issues.append(f"{path}.target_ref 不属于 {kind} 的身份空间")
            else:
                known_targets = {
                    str(item)
                    for item in (known_by_kind.get(kind) or {}).get(
                        "target_refs", []
                    )
                }
                if operation == "add":
                    existing_owners = known_target_owners.get(target_ref, set())
                    if existing_owners:
                        issues.append(
                            f"{path}.target_ref 已由这些长期权威种类占用，"
                            "不能跨种类重复新增："
                            + ", ".join(sorted(existing_owners))
                        )
                    introduced_target_owners.setdefault(
                        target_ref, set()
                    ).add(kind)
                    introduced_target_counts[target_ref] = (
                        introduced_target_counts.get(target_ref, 0) + 1
                    )
                elif target_ref not in known_targets:
                    issues.append(
                        f"{path}.target_ref 不是当前权威中的已知身份"
                    )
        if replacement_ref is not None and kind:
            if _TARGET_REF_PATTERNS[kind].fullmatch(replacement_ref) is None:
                issues.append(
                    f"{path}.replacement_ref 不属于 {kind} 的身份空间"
                )
            known_targets = {
                str(item)
                for item in (known_by_kind.get(kind) or {}).get("target_refs", [])
            }
            existing_owners = known_target_owners.get(replacement_ref, set())
            if existing_owners:
                issues.append(
                    f"{path}.replacement_ref 已由这些长期权威种类占用，"
                    "不能作为更名目标："
                    + ", ".join(sorted(existing_owners))
                )
            introduced_target_owners.setdefault(
                replacement_ref, set()
            ).add(kind)
            introduced_target_counts[replacement_ref] = (
                introduced_target_counts.get(replacement_ref, 0) + 1
            )
        normalized_change = {
            "change_id": change_id,
            "authority_kind": kind,
            "operation": operation,
            "target_ref": target_ref,
            "summary": _text(raw.get("summary"), f"{path}.summary", issues),
            "evidence_refs": evidence_refs,
        }
        if replacement_ref is not None:
            normalized_change["replacement_ref"] = replacement_ref
        changes.append(normalized_change)
    for target, owners in sorted(introduced_target_owners.items()):
        if len(owners) > 1:
            issues.append(
                "authority_change_set.changes 跨种类复用了同一新增身份："
                f"{target} -> {', '.join(sorted(owners))}"
            )
        if introduced_target_counts.get(target, 0) > 1:
            issues.append(
                "authority_change_set.changes 重复引入同一新增身份："
                f"{target}"
            )
    missing_change_kinds = sorted(changed_authority_kinds - kinds_with_changes)
    if missing_change_kinds:
        issues.append(
            "authority_change_set.changes 未说明这些候选的具体变化："
            + ", ".join(missing_change_kinds)
        )

    dispositions: list[dict[str, str]] = []
    dispositions_by_pair: dict[tuple[str, str], dict[str, str]] = {}
    for index, raw in enumerate(
        _list(
            value.get("downstream_dispositions"),
            "authority_change_set.downstream_dispositions",
            issues,
        )
    ):
        path = f"authority_change_set.downstream_dispositions[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _fields(
            raw,
            required={
                "source_authority_kind",
                "target_authority_kind",
                "disposition",
                "reason",
            },
            path=path,
            issues=issues,
        )
        source_kind = _enum(
            raw.get("source_authority_kind"),
            f"{path}.source_authority_kind",
            AUTHORITY_KINDS,
            issues,
        )
        target_kind = _enum(
            raw.get("target_authority_kind"),
            f"{path}.target_authority_kind",
            AUTHORITY_KINDS,
            issues,
        )
        disposition = _enum(
            raw.get("disposition"),
            f"{path}.disposition",
            {"revise", "unchanged", "blocked"},
            issues,
        )
        pair = (source_kind, target_kind)
        if pair in dispositions_by_pair:
            issues.append(
                "authority_change_set.downstream_dispositions 重复："
                + "/".join(pair)
            )
        if target_kind not in _DOWNSTREAM_REQUIREMENTS.get(source_kind, ()):
            issues.append(f"{path} 不是合法的单向下游处置关系")
        if source_kind not in changed_authority_kinds:
            issues.append(f"{path} 的上游权威没有在当前操作中修订")
        if disposition == "revise" and target_kind not in candidates_by_kind:
            issues.append(f"{path} 声明 revise 但没有对应下游候选修订")
        if disposition == "blocked" and formal_implementation:
            issues.append(f"{path} 仍为 blocked，不能进入可确认的正式实施方案")
        normalized_disposition = {
            "source_authority_kind": source_kind,
            "target_authority_kind": target_kind,
            "disposition": disposition,
            "reason": _text(raw.get("reason"), f"{path}.reason", issues),
        }
        dispositions_by_pair[pair] = normalized_disposition
        dispositions.append(normalized_disposition)
    required_pairs = {
        (source_kind, target_kind)
        for source_kind in changed_authority_kinds
        for target_kind in _DOWNSTREAM_REQUIREMENTS[source_kind]
    }
    missing_pairs = sorted(required_pairs - set(dispositions_by_pair))
    if missing_pairs:
        issues.append(
            "authority_change_set.downstream_dispositions 缺少上游变化处置："
            + ", ".join(f"{source}->{target}" for source, target in missing_pairs)
        )
    if formal_implementation:
        for source_kind in sorted(changed_authority_kinds):
            for target_kind in _DOWNSTREAM_REQUIREMENTS[source_kind]:
                if target_kind not in candidates_by_kind:
                    issues.append(
                        "上游权威修订必须同时形成实现对齐候选"
                        if target_kind == "implementation_alignment"
                        else "上游权威修订必须同时形成精确下游候选："
                        + f"{source_kind}->{target_kind}"
                    )
                    continue
                disposition = dispositions_by_pair.get(
                    (source_kind, target_kind)
                )
                if (
                    disposition is not None
                    and disposition.get("disposition") != "revise"
                ):
                    issues.append(
                        "已有精确下游候选时处置必须为 revise："
                        f"{source_kind}->{target_kind}"
                    )

    return {
        "schema_version": AUTHORITY_CHANGE_SET_SCHEMA,
        "change_set_id": change_set_id,
        "work_item_id": submitted_work_item_id,
        "base_authorities": bases,
        "candidate_authorities": candidates,
        "changes": changes,
        "downstream_dispositions": dispositions,
        "semantic_content_machine_proven": False,
    }


def _validate_semantic_review(
    value: Any,
    *,
    required: bool,
    known_refs: set[str],
    known_decision_refs: set[str],
    issues: list[str],
) -> dict[str, Any] | None:
    if value is None:
        if required:
            issues.append("当前影响涉及产品、领域或架构，必须提交 semantic_review")
        return None
    if not isinstance(value, Mapping):
        issues.append("semantic_review 必须是对象")
        return None
    _fields(
        value,
        required={
            "schema_version",
            "review_id",
            "reviewed_refs",
            "checks",
            "findings",
            "question_budget",
            "semantic_content_machine_proven",
        },
        path="semantic_review",
        issues=issues,
    )
    if value.get("schema_version") != SEMANTIC_REVIEW_SCHEMA:
        issues.append("semantic_review.schema_version 必须是 " + SEMANTIC_REVIEW_SCHEMA)
    review_id = _text(value.get("review_id"), "semantic_review.review_id", issues)
    if review_id and not _REVIEW_ID.fullmatch(review_id):
        issues.append("semantic_review.review_id 格式无效")
    if value.get("semantic_content_machine_proven") is not False:
        issues.append("semantic_review.semantic_content_machine_proven 必须明确为 false")
    reviewed_refs = _string_list(
        value.get("reviewed_refs"),
        "semantic_review.reviewed_refs",
        issues,
        required=True,
        unique=True,
    )
    unknown_reviewed_refs = sorted(set(reviewed_refs) - known_refs)
    if unknown_reviewed_refs:
        issues.append(
            "semantic_review.reviewed_refs 引用了未知记录："
            + ", ".join(unknown_reviewed_refs)
        )

    findings: list[dict[str, Any]] = []
    findings_by_id: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(
        _list(value.get("findings"), "semantic_review.findings", issues)
    ):
        path = f"semantic_review.findings[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _fields(
            raw,
            required={
                "finding_id",
                "perspective",
                "severity",
                "status",
                "locations",
                "statement",
                "impact",
                "recommendation",
                "owner_decision_required",
                "decision_refs",
                "resolution",
            },
            path=path,
            issues=issues,
        )
        finding_id = _text(raw.get("finding_id"), f"{path}.finding_id", issues)
        if finding_id and not _FINDING_ID.fullmatch(finding_id):
            issues.append(f"{path}.finding_id 格式无效")
        if finding_id in findings_by_id:
            issues.append(f"semantic_review.findings 重复身份：{finding_id}")
        perspective = _enum(
            raw.get("perspective"),
            f"{path}.perspective",
            SEMANTIC_REVIEW_PERSPECTIVES,
            issues,
        )
        severity = _enum(
            raw.get("severity"),
            f"{path}.severity",
            {"low", "medium", "high", "critical"},
            issues,
        )
        status = _enum(
            raw.get("status"),
            f"{path}.status",
            {"open", "resolved", "accepted_risk"},
            issues,
        )
        owner_decision_required = _boolean(
            raw.get("owner_decision_required"),
            f"{path}.owner_decision_required",
            issues,
        )
        decision_refs = _string_list(
            raw.get("decision_refs"),
            f"{path}.decision_refs",
            issues,
            unique=True,
        )
        unknown_decision_refs = sorted(
            set(decision_refs) - known_decision_refs
        )
        if unknown_decision_refs:
            issues.append(
                f"{path}.decision_refs 引用的记录不是已确认的项目负责人决定："
                + ", ".join(unknown_decision_refs)
            )
        resolution_value = raw.get("resolution")
        resolution = (
            None
            if resolution_value is None
            else _text(resolution_value, f"{path}.resolution", issues)
        )
        if status == "open" and resolution is not None:
            issues.append(f"{path}.resolution 在 open 状态必须为 null")
        if status != "open" and resolution is None:
            issues.append(f"{path}.resolution 在已处置状态不能为空")
        if status == "open" and (
            severity in {"high", "critical"} or owner_decision_required
        ):
            issues.append(f"{path} 是未闭合的高影响语义发现，不能进入实施方案确认")
        if (
            owner_decision_required
            and status in {"resolved", "accepted_risk"}
            and not decision_refs
        ):
            issues.append(
                f"{path}（{finding_id}）没有逐项引用真实已确认决定"
            )
        if (status == "open" or not owner_decision_required) and decision_refs:
            issues.append(
                f"{path}.decision_refs 只适用于已处置且需要负责人决定的发现"
            )
        locations = _string_list(
            raw.get("locations"),
            f"{path}.locations",
            issues,
            required=True,
            unique=True,
        )
        normalized = {
            "finding_id": finding_id,
            "perspective": perspective,
            "severity": severity,
            "status": status,
            "locations": locations,
            "statement": _text(raw.get("statement"), f"{path}.statement", issues),
            "impact": _text(raw.get("impact"), f"{path}.impact", issues),
            "recommendation": _text(
                raw.get("recommendation"), f"{path}.recommendation", issues
            ),
            "owner_decision_required": owner_decision_required,
            "decision_refs": decision_refs,
            "resolution": resolution,
        }
        findings_by_id[finding_id] = normalized
        findings.append(normalized)

    checks: list[dict[str, Any]] = []
    checks_by_perspective: dict[str, dict[str, Any]] = {}
    referenced_finding_ids: set[str] = set()
    for index, raw in enumerate(
        _list(value.get("checks"), "semantic_review.checks", issues)
    ):
        path = f"semantic_review.checks[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _fields(
            raw,
            required={"perspective", "status", "summary", "evidence_refs", "finding_ids"},
            path=path,
            issues=issues,
        )
        perspective = _enum(
            raw.get("perspective"),
            f"{path}.perspective",
            SEMANTIC_REVIEW_PERSPECTIVES,
            issues,
        )
        if perspective in checks_by_perspective:
            issues.append(f"semantic_review.checks 重复视角：{perspective}")
        status = _enum(
            raw.get("status"),
            f"{path}.status",
            {"aligned", "finding", "not_applicable"},
            issues,
        )
        evidence_refs = _string_list(
            raw.get("evidence_refs"),
            f"{path}.evidence_refs",
            issues,
            required=True,
            unique=True,
        )
        unknown_evidence = sorted(set(evidence_refs) - known_refs)
        if unknown_evidence:
            issues.append(
                f"{path}.evidence_refs 引用了未知记录："
                + ", ".join(unknown_evidence)
            )
        finding_ids = _string_list(
            raw.get("finding_ids"),
            f"{path}.finding_ids",
            issues,
            unique=True,
        )
        if status == "finding" and not finding_ids:
            issues.append(f"{path}.finding_ids 在 finding 状态不能为空")
        if status != "finding" and finding_ids:
            issues.append(f"{path}.finding_ids 只适用于 finding 状态")
        for finding_id in finding_ids:
            finding = findings_by_id.get(finding_id)
            if finding is None:
                issues.append(f"{path}.finding_ids 引用了未知发现：{finding_id}")
            elif finding["perspective"] != perspective:
                issues.append(f"{path}.finding_ids 引用了其他审查视角的发现：{finding_id}")
        referenced_finding_ids.update(finding_ids)
        normalized = {
            "perspective": perspective,
            "status": status,
            "summary": _text(raw.get("summary"), f"{path}.summary", issues),
            "evidence_refs": evidence_refs,
            "finding_ids": finding_ids,
        }
        checks_by_perspective[perspective] = normalized
        checks.append(normalized)
    missing_perspectives = sorted(
        set(SEMANTIC_REVIEW_PERSPECTIVES) - set(checks_by_perspective)
    )
    extra_findings = sorted(set(findings_by_id) - referenced_finding_ids)
    if missing_perspectives:
        issues.append(
            "semantic_review.checks 缺少审查视角：" + ", ".join(missing_perspectives)
        )
    if extra_findings:
        issues.append(
            "semantic_review.findings 存在未被检查项引用的发现："
            + ", ".join(extra_findings)
        )

    raw_budget = value.get("question_budget")
    budget: dict[str, Any]
    if not isinstance(raw_budget, Mapping):
        issues.append("semantic_review.question_budget 必须是对象")
        raw_budget = {}
    _fields(
        raw_budget,
        required={
            "maximum_questions",
            "questions_asked",
            "resolved_decision_refs",
            "remaining_high_impact_decisions",
        },
        path="semantic_review.question_budget",
        issues=issues,
    )
    maximum_questions = _integer(
        raw_budget.get("maximum_questions"),
        "semantic_review.question_budget.maximum_questions",
        issues,
        minimum=1,
        maximum=5,
    )
    if maximum_questions != 5:
        issues.append("semantic_review.question_budget.maximum_questions 必须固定为 5")
    questions_asked = _integer(
        raw_budget.get("questions_asked"),
        "semantic_review.question_budget.questions_asked",
        issues,
        minimum=0,
        maximum=5,
    )
    if questions_asked > maximum_questions:
        issues.append("semantic_review.question_budget.questions_asked 超过问题预算")
    resolved_decision_refs = _string_list(
        raw_budget.get("resolved_decision_refs"),
        "semantic_review.question_budget.resolved_decision_refs",
        issues,
        unique=True,
    )
    unknown_decision_refs = sorted(
        set(resolved_decision_refs) - known_decision_refs
    )
    if unknown_decision_refs:
        issues.append(
            "semantic_review.question_budget.resolved_decision_refs "
            "引用的记录不是已确认的项目负责人决定："
            + ", ".join(unknown_decision_refs)
        )
    finding_decision_refs = {
        reference
        for finding in findings
        for reference in finding["decision_refs"]
    }
    if set(resolved_decision_refs) != finding_decision_refs:
        issues.append(
            "semantic_review.question_budget.resolved_decision_refs 必须恰好汇总"
            "各项语义发现绑定的负责人决定"
        )
    remaining = _string_list(
        raw_budget.get("remaining_high_impact_decisions"),
        "semantic_review.question_budget.remaining_high_impact_decisions",
        issues,
        unique=True,
    )
    if remaining:
        issues.append(
            "semantic_review 仍有高影响决定未解决，不能进入工程方案确认"
        )
    budget = {
        "maximum_questions": maximum_questions,
        "questions_asked": questions_asked,
        "resolved_decision_refs": resolved_decision_refs,
        "remaining_high_impact_decisions": remaining,
    }
    return {
        "schema_version": SEMANTIC_REVIEW_SCHEMA,
        "review_id": review_id,
        "reviewed_refs": reviewed_refs,
        "checks": checks,
        "findings": findings,
        "question_budget": budget,
        "semantic_content_machine_proven": False,
    }


def validate_semantic_review(
    value: Any,
    *,
    known_refs: set[str],
    known_decision_refs: set[str],
) -> dict[str, Any]:
    """Validate one agent-authored eight-view review against exact refs."""

    issues: list[str] = []
    normalized = _validate_semantic_review(
        value,
        required=True,
        known_refs=set(known_refs),
        known_decision_refs=set(known_decision_refs),
        issues=issues,
    )
    if issues or normalized is None:
        raise ChangePlanningError(issues or ["semantic_review 无效"])
    return normalized


def _paths_conflict(first: str, second: str) -> bool:
    left = PurePosixPath(first).parts
    right = PurePosixPath(second).parts
    shared = min(len(left), len(right))
    return left[:shared] == right[:shared]


def _slice_write_paths(
    slice_value: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
) -> set[str]:
    result: set[str] = set()
    for reference in [
        *(slice_value.get("operation_refs") or []),
        *(slice_value.get("continued_operation_refs") or []),
    ]:
        match = _OPERATION_REF.fullmatch(str(reference))
        if match is None:
            continue
        index = int(match.group(1))
        if index >= len(operations):
            continue
        operation = operations[index]
        for key in ("path", "to_path"):
            value = str(operation.get(key) or "").strip()
            if value:
                result.add(value)
    return result


def _has_dependency_path(
    start: str,
    target: str,
    dependencies: Mapping[str, set[str]],
) -> bool:
    pending = list(dependencies.get(start, set()))
    visited: set[str] = set()
    while pending:
        current = pending.pop()
        if current == target:
            return True
        if current in visited:
            continue
        visited.add(current)
        pending.extend(dependencies.get(current, set()))
    return False


def _validate_slices(
    value: Any,
    *,
    formal_implementation: bool,
    change_kind: str,
    operations: Sequence[Mapping[str, Any]],
    verification_commands: Sequence[Mapping[str, Any]],
    known_authorities: Mapping[str, Mapping[str, Any]] | None,
    valid_implements_refs: set[str],
    issues: list[str],
) -> list[dict[str, Any]]:
    if value is None:
        if formal_implementation:
            issues.append("正式实施必须提交 implementation_slices")
        return []
    raw_slices = _list(value, "implementation_slices", issues)
    if formal_implementation and not raw_slices:
        issues.append("正式实施的 implementation_slices 不能为空")
    if not formal_implementation:
        if raw_slices:
            issues.append("非正式调查不得声明 implementation_slices")
        # Normalized read-only plans contain an empty list. Their verification
        # commands do not become implementation operations on revalidation.
        return []
    slices: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    operation_owners: dict[str, str] = {}
    verification_owners: dict[str, str] = {}
    for index, raw in enumerate(raw_slices):
        path = f"implementation_slices[{index}]"
        if not isinstance(raw, Mapping):
            issues.append(f"{path} 必须是对象")
            continue
        _fields(
            raw,
            required={
                "schema_version",
                "slice_id",
                "purpose",
                "implements",
                "operation_refs",
                "depends_on",
                "parallel_safe_with",
                "completion_criteria",
                "verification_command_refs",
                "rollback_or_recovery",
            },
            optional={"continued_operation_refs"},
            path=path,
            issues=issues,
        )
        if raw.get("schema_version") != IMPLEMENTATION_SLICE_SCHEMA:
            issues.append(f"{path}.schema_version 必须是 {IMPLEMENTATION_SLICE_SCHEMA}")
        slice_id = _text(raw.get("slice_id"), f"{path}.slice_id", issues)
        if slice_id and not _SLICE_ID.fullmatch(slice_id):
            issues.append(f"{path}.slice_id 格式无效")
        if slice_id in seen_ids:
            issues.append(f"implementation_slices 重复身份：{slice_id}")
        seen_ids.add(slice_id)
        implements = _string_list(
            raw.get("implements"),
            f"{path}.implements",
            issues,
            required=True,
            unique=True,
        )
        unknown_implements = sorted(set(implements) - valid_implements_refs)
        if unknown_implements:
            issues.append(
                f"{path}.implements 引用了未知上游目标："
                + ", ".join(unknown_implements)
            )
        operation_refs = _string_list(
            raw.get("operation_refs"),
            f"{path}.operation_refs",
            issues,
            required=True,
            unique=True,
        )
        for reference in operation_refs:
            match = _OPERATION_REF.fullmatch(reference)
            if match is None or int(match.group(1)) >= len(operations):
                issues.append(f"{path}.operation_refs 引用了未知文件操作：{reference}")
            if reference in operation_owners:
                issues.append(
                    f"{reference} 同时归属 {operation_owners[reference]} 和 {slice_id}"
                )
            operation_owners[reference] = slice_id
        continued_operation_refs = _string_list(
            raw.get("continued_operation_refs", []),
            f"{path}.continued_operation_refs",
            issues,
            unique=True,
        )
        overlap = sorted(set(operation_refs).intersection(continued_operation_refs))
        if overlap:
            issues.append(
                f"{path}.continued_operation_refs 不得重复本切片拥有的操作："
                + ", ".join(overlap)
            )
        for reference in continued_operation_refs:
            match = _OPERATION_REF.fullmatch(reference)
            if match is None or int(match.group(1)) >= len(operations):
                issues.append(
                    f"{path}.continued_operation_refs 引用了未知文件操作：{reference}"
                )
        verification_refs = _string_list(
            raw.get("verification_command_refs"),
            f"{path}.verification_command_refs",
            issues,
            # One plan may mix a documentation/governance slice with no
            # applicable command and later executable slices.  The former is
            # closed only through an explicit completion record; every actual
            # command is still assigned exactly once by the coverage check
            # below.
            required=False,
            unique=True,
        )
        for reference in verification_refs:
            match = _VERIFICATION_REF.fullmatch(reference)
            if match is None or int(match.group(1)) >= len(verification_commands):
                issues.append(
                    f"{path}.verification_command_refs 引用了未知验证命令：{reference}"
                )
            if reference in verification_owners:
                issues.append(
                    f"{reference} 同时归属 {verification_owners[reference]} 和 {slice_id}"
                )
            verification_owners[reference] = slice_id
        slices.append(
            {
                "schema_version": IMPLEMENTATION_SLICE_SCHEMA,
                "slice_id": slice_id,
                "purpose": _text(raw.get("purpose"), f"{path}.purpose", issues),
                "implements": implements,
                "operation_refs": operation_refs,
                "continued_operation_refs": continued_operation_refs,
                "depends_on": _string_list(
                    raw.get("depends_on"),
                    f"{path}.depends_on",
                    issues,
                    unique=True,
                ),
                "parallel_safe_with": _string_list(
                    raw.get("parallel_safe_with"),
                    f"{path}.parallel_safe_with",
                    issues,
                    unique=True,
                ),
                "completion_criteria": _string_list(
                    raw.get("completion_criteria"),
                    f"{path}.completion_criteria",
                    issues,
                    required=True,
                    unique=True,
                ),
                "verification_command_refs": verification_refs,
                "rollback_or_recovery": _text(
                    raw.get("rollback_or_recovery"),
                    f"{path}.rollback_or_recovery",
                    issues,
                ),
            }
        )
    expected_operation_refs = {f"operations[{index}]" for index in range(len(operations))}
    expected_verification_refs = {
        f"verification_commands[{index}]" for index in range(len(verification_commands))
    }
    missing_operations = sorted(expected_operation_refs - set(operation_owners))
    missing_verifications = sorted(
        expected_verification_refs - set(verification_owners)
    )
    if missing_operations:
        issues.append(
            "implementation_slices 没有覆盖全部文件操作："
            + ", ".join(missing_operations)
        )
    if missing_verifications:
        issues.append(
            "implementation_slices 没有覆盖全部验证命令："
            + ", ".join(missing_verifications)
        )

    indexes = {item["slice_id"]: index for index, item in enumerate(slices)}
    dependencies: dict[str, set[str]] = {}
    parallel: dict[str, set[str]] = {}
    for index, item in enumerate(slices):
        slice_id = str(item["slice_id"])
        dependency_ids = set(item["depends_on"])
        parallel_ids = set(item["parallel_safe_with"])
        dependencies[slice_id] = dependency_ids
        parallel[slice_id] = parallel_ids
        if slice_id in dependency_ids:
            issues.append(f"implementation_slices[{index}].depends_on 不得引用自身")
        if slice_id in parallel_ids:
            issues.append(
                f"implementation_slices[{index}].parallel_safe_with 不得引用自身"
            )
        unknown_dependencies = sorted(dependency_ids - set(indexes))
        unknown_parallel = sorted(parallel_ids - set(indexes))
        if unknown_dependencies:
            issues.append(
                f"implementation_slices[{index}].depends_on 引用了未知切片："
                + ", ".join(unknown_dependencies)
            )
        if unknown_parallel:
            issues.append(
                f"implementation_slices[{index}].parallel_safe_with 引用了未知切片："
                + ", ".join(unknown_parallel)
            )
        later_dependencies = sorted(
            dependency
            for dependency in dependency_ids
            if dependency in indexes and indexes[dependency] >= index
        )
        if later_dependencies:
            issues.append(
                f"implementation_slices[{index}].depends_on 必须引用排在前面的切片："
                + ", ".join(later_dependencies)
            )
    for slice_id in dependencies:
        if _has_dependency_path(slice_id, slice_id, dependencies):
            issues.append(f"implementation_slices 依赖形成循环：{slice_id}")
    known_alignment = _authority_by_kind(known_authorities).get(
        "implementation_alignment",
        {},
    )
    known_alignment_paths = {
        str(path).replace("\\", "/")
        for path in (
            known_alignment.get("governed_paths")
            or [known_alignment.get("path")]
        )
        if str(path or "").strip()
    }
    continuation_slices = [
        str(item["slice_id"])
        for item in slices
        if item.get("continued_operation_refs")
    ]
    if len(continuation_slices) > 1:
        issues.append(
            "implementation_slices 只允许一个最终实现对齐刷新切片："
            + ", ".join(continuation_slices)
        )
    if continuation_slices:
        final_slice_id = continuation_slices[0]
        final_index = indexes.get(final_slice_id, -1)
        if final_index != len(slices) - 1:
            issues.append(
                "实现对齐最终刷新切片必须是方案中的最后一个实施切片："
                + final_slice_id
            )
        missing_predecessors = sorted(
            str(item["slice_id"])
            for item in slices[: max(final_index, 0)]
            if not _has_dependency_path(
                final_slice_id,
                str(item["slice_id"]),
                dependencies,
            )
        )
        if missing_predecessors:
            issues.append(
                "实现对齐最终刷新切片必须依赖全部前置实施切片："
                + ", ".join(missing_predecessors)
            )
    continued_by_ref: dict[str, str] = {}
    for index, item in enumerate(slices):
        slice_id = str(item["slice_id"])
        continued_refs = list(item.get("continued_operation_refs") or [])
        owners = {
            operation_owners.get(str(reference))
            for reference in continued_refs
            if operation_owners.get(str(reference)) is not None
        }
        if len(owners) > 1:
            issues.append(
                f"implementation_slices[{index}].continued_operation_refs "
                "必须全部延续同一个前置切片中的实现对齐权威"
            )
        owner = next(iter(owners), None)
        owner_slice = (
            next(
                (
                    value
                    for value in slices
                    if value.get("slice_id") == owner
                ),
                None,
            )
            if owner is not None
            else None
        )
        owner_alignment_root_refs: set[str] = set()
        owner_alignment_root_parents: set[tuple[str | None, PurePosixPath]] = set()
        if isinstance(owner_slice, Mapping):
            for owner_reference in owner_slice.get("operation_refs") or []:
                match = _OPERATION_REF.fullmatch(str(owner_reference))
                if match is None or int(match.group(1)) >= len(operations):
                    continue
                operation = operations[int(match.group(1))]
                artifact = operation.get("long_lived_artifact")
                if (
                    isinstance(artifact, Mapping)
                    and artifact.get("artifact_type") == "domain_alignment"
                ):
                    owner_alignment_root_refs.add(str(owner_reference))
                    root_path = str(operation.get("path") or "").replace(
                        "\\", "/"
                    )
                    if root_path:
                        owner_alignment_root_parents.add(
                            (operation.get("repository_id"), PurePosixPath(root_path).parent)
                        )
        if continued_refs and not owner_alignment_root_refs.intersection(
            continued_refs
        ):
            issues.append(
                f"implementation_slices[{index}].continued_operation_refs "
                "必须显式包含前置切片的实现对齐根操作"
            )
        for reference in continued_refs:
            owner = operation_owners.get(str(reference))
            if owner is None:
                continue
            if not _has_dependency_path(slice_id, owner, dependencies):
                issues.append(
                    f"implementation_slices[{index}].continued_operation_refs "
                    f"只能延续依赖祖先切片的操作：{reference} 属于 {owner}"
                )
            previous = continued_by_ref.get(str(reference))
            if previous is not None and previous != slice_id:
                issues.append(
                    f"{reference} 不能被多个后续切片重复延续："
                    f"{previous}/{slice_id}"
                )
            continued_by_ref[str(reference)] = slice_id
            match = _OPERATION_REF.fullmatch(str(reference))
            if match is None or int(match.group(1)) >= len(operations):
                continue
            operation = operations[int(match.group(1))]
            artifact = operation.get("long_lived_artifact")
            artifact_is_alignment = bool(
                isinstance(artifact, Mapping)
                and artifact.get("artifact_type") == "domain_alignment"
            )
            operation_paths = {
                str(operation.get(field) or "").replace("\\", "/")
                for field in ("path", "to_path")
                if str(operation.get(field) or "").strip()
            }
            adopted_alignment_path = bool(
                operation_paths
                and operation.get("repository_id") == known_alignment.get("repository_id")
                and operation_paths.issubset(known_alignment_paths)
            )
            initial_alignment_path = bool(
                change_kind == "create_project"
                and operation_paths
                and owner_alignment_root_parents
                and all(
                    (operation.get("repository_id"), PurePosixPath(path).parent)
                    in owner_alignment_root_parents
                    for path in operation_paths
                )
            )
            if not (
                artifact_is_alignment
                or adopted_alignment_path
                or initial_alignment_path
            ):
                issues.append(
                    f"implementation_slices[{index}].continued_operation_refs "
                    "只能用于同一实现对齐草稿的最终刷新，不能延续普通文件操作："
                    + str(reference)
                )
    authority_type_by_phase = {
        "product_governance": "product_definition",
        "domain_model": "domain_model",
        "architecture": "target_architecture",
        "quality_policy": "engineering_policy",
        "domain_alignment": "implementation_alignment",
    }
    phases_by_slice: dict[str, set[str]] = {}
    for item in slices:
        phases: set[str] = set()
        for reference in item.get("operation_refs") or []:
            match = _OPERATION_REF.fullmatch(str(reference))
            if match is None or int(match.group(1)) >= len(operations):
                continue
            artifact = operations[int(match.group(1))].get(
                "long_lived_artifact"
            )
            artifact_type = (
                str(artifact.get("artifact_type") or "")
                if isinstance(artifact, Mapping)
                else ""
            )
            phase = authority_type_by_phase.get(artifact_type)
            if phase is not None:
                phases.add(phase)
        phases_by_slice[str(item["slice_id"])] = phases

    def depends_on_slice(slice_id: str, predecessor_id: str) -> bool:
        return slice_id == predecessor_id or _has_dependency_path(
            slice_id,
            predecessor_id,
            dependencies,
        )

    slices_by_phase = {
        phase: {
            slice_id
            for slice_id, phases in phases_by_slice.items()
            if phase in phases
        }
        for phase in authority_type_by_phase.values()
    }
    prerequisite_phases = {
        "domain_model": {"product_definition"},
        "target_architecture": {"domain_model"},
        "engineering_policy": {"product_definition"},
        "implementation_alignment": {
            "product_definition",
            "domain_model",
            "target_architecture",
            "engineering_policy",
        },
    }
    for phase, prerequisites in prerequisite_phases.items():
        for slice_id in slices_by_phase[phase]:
            missing_predecessors = sorted(
                predecessor_id
                for prerequisite in prerequisites
                for predecessor_id in slices_by_phase[prerequisite]
                if not depends_on_slice(slice_id, predecessor_id)
            )
            if missing_predecessors:
                issues.append(
                    f"实施切片 {slice_id} 的 {phase} 候选没有依赖全部上游权威切片："
                    + ", ".join(missing_predecessors)
                )
    governance_slice_ids = {
        slice_id for slice_id, phases in phases_by_slice.items() if phases
    }
    for slice_id, phases in phases_by_slice.items():
        if phases:
            continue
        missing_governance = sorted(
            governance_id
            for governance_id in governance_slice_ids
            if not depends_on_slice(slice_id, governance_id)
        )
        if missing_governance:
            issues.append(
                f"业务实施切片 {slice_id} 必须排在全部长期权威和编码前实现对齐切片之后："
                + ", ".join(missing_governance)
            )
    slices_by_id = {str(item["slice_id"]): item for item in slices}
    for slice_id, peers in parallel.items():
        for peer in peers:
            if peer not in slices_by_id:
                continue
            if slice_id not in parallel.get(peer, set()):
                issues.append(
                    f"implementation_slices 的并行安全声明必须双向：{slice_id}/{peer}"
                )
            if _has_dependency_path(slice_id, peer, dependencies) or _has_dependency_path(
                peer, slice_id, dependencies
            ):
                issues.append(
                    f"有依赖关系的切片不得声明并行安全：{slice_id}/{peer}"
                )
            first_paths = _slice_write_paths(slices_by_id[slice_id], operations)
            second_paths = _slice_write_paths(slices_by_id[peer], operations)
            conflicts = sorted(
                f"{first}<->{second}"
                for first in first_paths
                for second in second_paths
                if _paths_conflict(first, second)
            )
            if conflicts:
                issues.append(
                    f"并行切片 {slice_id}/{peer} 存在确定性写入冲突："
                    + ", ".join(conflicts)
                )
    return slices


def _validate_owner_view(value: Any, issues: list[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        issues.append("owner_view 必须是对象")
        value = {}
    fields = {
        "schema_version",
        "decision_support",
        "engineering_context",
        "current_decision",
        "semantic_content_machine_proven",
    }
    _fields(value, required=fields, path="owner_view", issues=issues)
    if value.get("schema_version") != OWNER_VIEW_SCHEMA:
        issues.append(f"owner_view.schema_version 必须是 {OWNER_VIEW_SCHEMA}")
    if value.get("semantic_content_machine_proven") is not False:
        issues.append("owner_view.semantic_content_machine_proven 必须明确为 false")

    decision_support = value.get("decision_support")
    if not isinstance(decision_support, Mapping):
        issues.append("owner_view.decision_support 必须是对象")
        decision_support = {}
    decision_fields = {
        "current_problem",
        "why_it_matters",
        "impact",
        "recommendation",
        "alternatives",
        "no_action_consequence",
        "next_step",
        "necessary_questions",
    }
    _fields(
        decision_support,
        required=decision_fields,
        path="owner_view.decision_support",
        issues=issues,
    )
    alternatives = _string_list(
        decision_support.get("alternatives"),
        "owner_view.decision_support.alternatives",
        issues,
        required=True,
    )
    necessary_questions = _string_list(
        decision_support.get("necessary_questions"),
        "owner_view.decision_support.necessary_questions",
        issues,
    )
    if len(alternatives) > 5:
        issues.append("owner_view.decision_support.alternatives 最多包含 5 项")
    if len(necessary_questions) > 5:
        issues.append("owner_view.decision_support.necessary_questions 最多包含 5 项")

    engineering_context = value.get("engineering_context")
    if not isinstance(engineering_context, Mapping):
        issues.append("owner_view.engineering_context 必须是对象")
        engineering_context = {}
    context_fields = {
        "product_and_domain_change",
        "architecture_responsibilities",
        "implementation_order",
        "highest_impact_risks",
        "verification_and_observation",
        "uncertainties",
    }
    _fields(
        engineering_context,
        required=context_fields,
        path="owner_view.engineering_context",
        issues=issues,
    )
    return {
        "schema_version": OWNER_VIEW_SCHEMA,
        "decision_support": {
            **{
                field: _text(
                    decision_support.get(field),
                    f"owner_view.decision_support.{field}",
                    issues,
                )
                for field in (
                    "current_problem",
                    "why_it_matters",
                    "impact",
                    "recommendation",
                    "no_action_consequence",
                    "next_step",
                )
            },
            "alternatives": alternatives,
            "necessary_questions": necessary_questions,
        },
        "engineering_context": {
            field: _text(
                engineering_context.get(field),
                f"owner_view.engineering_context.{field}",
                issues,
            )
            for field in (
                "product_and_domain_change",
                "architecture_responsibilities",
                "implementation_order",
                "highest_impact_risks",
                "verification_and_observation",
                "uncertainties",
            )
        },
        "current_decision": _text(
            value.get("current_decision"),
            "owner_view.current_decision",
            issues,
        ),
        "semantic_content_machine_proven": False,
    }


def validate_change_planning(
    assessment: Mapping[str, Any],
    *,
    work_item_id: str,
    investigation_ref: str,
    formal_implementation: bool,
    change_kind: str,
    impact_scope: Mapping[str, Any],
    operations: Sequence[Mapping[str, Any]],
    verification_commands: Sequence[Mapping[str, Any]],
    known_authorities: Mapping[str, Mapping[str, Any]] | None,
    known_evidence_refs: set[str],
    known_decision_refs: set[str],
    valid_implements_refs: set[str],
) -> dict[str, Any]:
    """Validate all new planning records without assessing their prose."""

    issues: list[str] = []
    changed_authorities = (
        set()
        if change_kind == "create_project"
        else _changed_authority_kinds(operations, known_authorities)
    )
    authority_change_set = _validate_authority_change_set(
        assessment.get("authority_change_set"),
        work_item_id=work_item_id,
        investigation_ref=investigation_ref,
        changed_authority_kinds=changed_authorities,
        known_authorities=known_authorities,
        known_evidence_refs=known_evidence_refs,
        formal_implementation=formal_implementation,
        operations=operations,
        issues=issues,
    )
    if change_kind == "create_project" and assessment.get("authority_change_set") is not None:
        issues.append(
            "新项目首次建立完整权威时不得使用 authority_change_set；它只用于现行权威修订"
        )
    relevant_dimensions = {
        str(item.get("dimension") or "")
        for status in ("affected", "unknown")
        for item in impact_scope.get(status) or []
        if isinstance(item, Mapping)
    }
    review_required = bool(
        change_kind == "create_project"
        or {"product_scope", "domain", "architecture"}.intersection(
            relevant_dimensions
        )
        or authority_change_set is not None
    )
    review_refs = set(known_evidence_refs)
    if authority_change_set is not None:
        review_refs.add("authority_change_set")
        review_refs.update(
            f"authority_change_set.changes[{index}]"
            for index, _ in enumerate(authority_change_set["changes"])
        )
    semantic_review = _validate_semantic_review(
        assessment.get("semantic_review"),
        required=review_required,
        known_refs=review_refs,
        known_decision_refs=known_decision_refs,
        issues=issues,
    )
    effective_implements_refs = set(valid_implements_refs)
    if authority_change_set is not None:
        effective_implements_refs.update(
            f"authority_change_set.changes[{index}]"
            for index, _ in enumerate(authority_change_set["changes"])
        )
    if semantic_review is not None:
        effective_implements_refs.update(
            f"semantic_review.findings[{index}]"
            for index, _ in enumerate(semantic_review["findings"])
        )
    implementation_slices = _validate_slices(
        assessment.get("implementation_slices"),
        formal_implementation=formal_implementation,
        change_kind=change_kind,
        operations=operations,
        verification_commands=verification_commands,
        known_authorities=known_authorities,
        valid_implements_refs=effective_implements_refs,
        issues=issues,
    )
    owner_view = _validate_owner_view(assessment.get("owner_view"), issues)
    if issues:
        raise ChangePlanningError(issues)
    return {
        "authority_change_set": authority_change_set,
        "semantic_review": semantic_review,
        "implementation_slices": implementation_slices,
        "owner_view": owner_view,
    }


def compile_implementation_slices(
    slices: Sequence[Mapping[str, Any]],
    verification_commands: Sequence[Mapping[str, Any]],
    operations: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Compile one complete slice contract with exact commands and repository scope."""

    command_ids_by_source_index: dict[int, str] = {}
    for position, command in enumerate(verification_commands):
        source_indexes = list(command.get("source_command_indexes") or [position])
        for source_index in source_indexes:
            command_ids_by_source_index[int(source_index)] = str(
                command["command_id"]
            )
    compiled: list[dict[str, Any]] = []
    for index, item in enumerate(slices):
        command_ids = []
        for reference in item.get("verification_command_refs") or []:
            match = _VERIFICATION_REF.fullmatch(str(reference))
            source_index = int(match.group(1)) if match is not None else -1
            command_id = command_ids_by_source_index.get(source_index)
            if command_id is None:
                raise ChangePlanningError(
                    [
                        f"implementation_slices[{index}].verification_command_refs "
                        f"无法绑定：{reference}"
                    ]
                )
            if command_id not in command_ids:
                command_ids.append(command_id)
        repositories = []
        for reference in [*item.get("operation_refs", []), *item.get("continued_operation_refs", [])]:
            match = _OPERATION_REF.fullmatch(str(reference))
            operation_index = int(match.group(1)) if match is not None else -1
            if not 0 <= operation_index < len(operations):
                raise ChangePlanningError([f"implementation_slices[{index}] 无法绑定操作：{reference}"])
            repositories.append(operations[operation_index].get("repository_id"))
        repositories.extend(command.get("repository_id") for command in verification_commands
                            if command["command_id"] in command_ids)
        compiled.append(
            {
                "schema_version": "strixnova.implementation-slice-plan.v1",
                "repository_ids": list(dict.fromkeys(repositories)),
                "slice_id": str(item["slice_id"]),
                "source_slice_ref": f"implementation_slices[{index}]",
                "purpose": str(item["purpose"]),
                "implements": list(item.get("implements") or []),
                "operation_refs": list(item.get("operation_refs") or []),
                "continued_operation_refs": list(
                    item.get("continued_operation_refs") or []
                ),
                "depends_on": list(item.get("depends_on") or []),
                "parallel_safe_with": list(item.get("parallel_safe_with") or []),
                "completion_criteria": list(item.get("completion_criteria") or []),
                "verification_command_ids": command_ids,
                "rollback_or_recovery": str(item["rollback_or_recovery"]),
                "machine_validated": True,
            }
        )
    return compiled


def implementation_slice_progress(
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Project deterministic slice progress from the latest command receipts."""

    slices = [
        dict(item)
        for item in plan.get("implementation_slices") or []
        if isinstance(item, Mapping)
    ]
    if not slices:
        return {
            "schema_version": "strixnova.implementation-slice-progress.v1",
            "status": "not_planned",
            "current_slice_id": None,
            "available_slice_ids": [],
            "completed_slice_ids": [],
            "blocked_slice_ids": [],
        }
    latest: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        if not isinstance(receipt, Mapping):
            continue
        command_id = str(receipt.get("command_id") or "")
        if command_id:
            latest[command_id] = receipt
    completed: set[str] = set()
    explicitly_completed = {
        str(item.get("slice_id") or "")
        for item in completions
        if isinstance(item, Mapping)
        and item.get("schema_version")
        == "strixnova.implementation-slice-completion.v1"
        and item.get("semantic_content_machine_proven") is False
    }
    for item in slices:
        command_ids = set(item.get("verification_command_ids") or [])
        slice_id = str(item.get("slice_id") or "")
        if not command_ids and slice_id in explicitly_completed:
            completed.add(slice_id)
        elif command_ids and all(
            command_id in latest
            and latest[command_id].get("result") == "passed"
            and latest[command_id].get("_case_input_stale") is not True
            and isinstance(latest[command_id].get("code_change_assessment"), Mapping)
            and latest[command_id]["code_change_assessment"].get("needs_retest")
            is False
            for command_id in command_ids
        ):
            completed.add(str(item.get("slice_id") or ""))
    available = [
        str(item["slice_id"])
        for item in slices
        if str(item["slice_id"]) not in completed
        and set(item.get("depends_on") or []).issubset(completed)
    ]
    blocked = [
        str(item["slice_id"])
        for item in slices
        if str(item["slice_id"]) not in completed
        and str(item["slice_id"]) not in available
    ]
    return {
        "schema_version": "strixnova.implementation-slice-progress.v1",
        "status": "completed" if len(completed) == len(slices) else "in_progress",
        "current_slice_id": available[0] if available else None,
        "available_slice_ids": available,
        "completed_slice_ids": [
            str(item["slice_id"])
            for item in slices
            if str(item["slice_id"]) in completed
        ],
        "blocked_slice_ids": blocked,
    }


def focused_slice(
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any] | None:
    """Return the first currently executable slice in confirmed plan order."""

    progress = implementation_slice_progress(plan, receipts, completions)
    current_slice_id = progress["current_slice_id"]
    if current_slice_id is None:
        return None
    for item in plan.get("implementation_slices") or []:
        if isinstance(item, Mapping) and item.get("slice_id") == current_slice_id:
            return deepcopy(dict(item))
    return None


def implementation_slice_reportability(
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Project the successful or terminal-failure result-reporting boundary."""

    slices = [
        item
        for item in plan.get("implementation_slices") or []
        if isinstance(item, Mapping)
    ]
    if not slices:
        return {
            "reportable": True,
            "reason": "not_planned",
            "terminal_slice_id": None,
            "not_executed_slice_ids": [],
            "not_executed_command_ids": [],
        }
    latest: dict[str, Mapping[str, Any]] = {}
    for receipt in receipts:
        if isinstance(receipt, Mapping) and str(receipt.get("command_id") or ""):
            latest[str(receipt["command_id"])] = receipt
    explicit = {
        str(item.get("slice_id") or "")
        for item in completions
        if isinstance(item, Mapping)
        and item.get("schema_version")
        == "strixnova.implementation-slice-completion.v1"
        and item.get("semantic_content_machine_proven") is False
    }
    all_complete = True
    for item in slices:
        command_ids = set(item.get("verification_command_ids") or [])
        if not command_ids:
            if str(item.get("slice_id") or "") not in explicit:
                all_complete = False
            continue
        if any(
            command_id not in latest
            or latest[command_id].get("_case_input_stale") is True
            or not isinstance(
                latest[command_id].get("code_change_assessment"), Mapping
            )
            or latest[command_id]["code_change_assessment"].get(
                "needs_retest"
            )
            is not False
            for command_id in command_ids
        ):
            all_complete = False
    if all_complete:
        return {
            "reportable": True,
            "reason": "all_slices_evidenced",
            "terminal_slice_id": None,
            "not_executed_slice_ids": [],
            "not_executed_command_ids": [],
        }

    progress = implementation_slice_progress(plan, receipts, completions)
    current_slice_id = progress.get("current_slice_id")
    current = next(
        (
            item
            for item in slices
            if str(item.get("slice_id") or "") == current_slice_id
        ),
        None,
    )
    command_ids = set(current.get("verification_command_ids") or []) if current else set()
    terminal_failure = bool(command_ids) and all(
        command_id in latest
        and latest[command_id].get("_case_input_stale") is not True
        and isinstance(latest[command_id].get("code_change_assessment"), Mapping)
        and latest[command_id]["code_change_assessment"].get("needs_retest")
        is False
        for command_id in command_ids
    ) and any(latest[command_id].get("result") != "passed" for command_id in command_ids)
    if terminal_failure:
        planned_command_ids = {
            str(command_id)
            for item in slices
            for command_id in item.get("verification_command_ids") or []
        }
        return {
            "reportable": True,
            "reason": "terminal_slice_issue",
            "terminal_slice_id": current_slice_id,
            "not_executed_slice_ids": [
                str(item.get("slice_id") or "")
                for item in slices
                if str(item.get("slice_id") or "")
                != str(current_slice_id or "")
                and str(item.get("slice_id") or "")
                not in set(progress.get("completed_slice_ids") or [])
            ],
            "not_executed_command_ids": sorted(planned_command_ids - set(latest)),
        }
    return {
        "reportable": False,
        "reason": "incomplete",
        "terminal_slice_id": current_slice_id,
        "not_executed_slice_ids": [],
        "not_executed_command_ids": [],
    }


def implementation_slices_reportable(
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]] = (),
) -> bool:
    """Return whether implementation can truthfully reach ActualResult."""

    return bool(
        implementation_slice_reportability(plan, receipts, completions)[
            "reportable"
        ]
    )


def implementation_reporting_coverage(
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]],
    coverage: Mapping[str, Any],
) -> dict[str, Any]:
    """Make dependency-blocked commands explicit at the result boundary."""

    result = deepcopy(dict(coverage))
    reportability = implementation_slice_reportability(
        plan,
        receipts,
        completions,
    )
    if reportability["reason"] != "terminal_slice_issue":
        return result
    result["verification_status"] = "completed_with_issues"
    result["missing_command_ids"] = []
    result["terminal_slice_id"] = reportability["terminal_slice_id"]
    result["not_executed_slice_ids"] = reportability[
        "not_executed_slice_ids"
    ]
    result["not_executed_command_ids"] = reportability[
        "not_executed_command_ids"
    ]
    return result


def permitted_slice_operation_paths(
    plan: Mapping[str, Any],
    receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]] = (),
    *, repository_id: Any = ...,
) -> dict[str, Any]:
    """Return cumulative paths owned by completed and current slices.

    Git reports a cumulative worktree diff, so paths from completed slices
    remain permitted while the next slice is implemented.  Paths assigned only
    to a later blocked slice are deliberately excluded.
    """

    progress = implementation_slice_progress(plan, receipts, completions)
    active_slice_ids = set(progress["completed_slice_ids"])
    current_slice_id = progress["current_slice_id"]
    if current_slice_id is not None:
        active_slice_ids.add(str(current_slice_id))
    operations = [
        dict(item)
        for item in plan.get("operations") or []
        if isinstance(item, Mapping)
    ]
    permitted_paths: set[str] = set()
    planned_paths: set[str] = set()
    for slice_value in plan.get("implementation_slices") or []:
        if not isinstance(slice_value, Mapping):
            continue
        active = str(slice_value.get("slice_id") or "") in active_slice_ids
        references = [
            *(slice_value.get("operation_refs") or []),
            *(slice_value.get("continued_operation_refs") or []),
        ]
        for reference in references:
            match = _OPERATION_REF.fullmatch(str(reference))
            if match is None:
                continue
            index = int(match.group(1))
            if index >= len(operations):
                continue
            operation = operations[index]
            if repository_id is not ... and operation.get("repository_id") != repository_id:
                continue
            for field in ("path", "to_path"):
                value = operation.get(field)
                if isinstance(value, str) and value.strip():
                    normalized = value.strip()
                    if reference in (slice_value.get("operation_refs") or []):
                        planned_paths.add(normalized)
                    if active:
                        permitted_paths.add(normalized)
    return {
        "schema_version": "strixnova.implementation-slice-path-scope.v1",
        "current_slice_id": current_slice_id,
        "completed_slice_ids": list(progress["completed_slice_ids"]),
        "permitted_paths": sorted(permitted_paths),
        "planned_paths": sorted(planned_paths),
        "future_paths": sorted(planned_paths - permitted_paths),
    }


__all__ = [
    "AUTHORITY_CHANGE_SET_SCHEMA",
    "AUTHORITY_KINDS",
    "ChangePlanningError",
    "IMPLEMENTATION_SLICE_SCHEMA",
    "OWNER_VIEW_SCHEMA",
    "SEMANTIC_REVIEW_PERSPECTIVES",
    "SEMANTIC_REVIEW_SCHEMA",
    "compile_implementation_slices",
    "focused_slice",
    "implementation_slice_progress",
    "implementation_slice_reportability",
    "implementation_reporting_coverage",
    "implementation_slices_reportable",
    "permitted_slice_operation_paths",
    "validate_semantic_review",
    "validate_change_planning",
]
