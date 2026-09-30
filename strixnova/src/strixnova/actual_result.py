"""Validate coding-agent actual-result candidates without executing commands."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any
import re
from strixnova.verification_targets import VerificationTargetError, assess_targets
from strixnova.follow_ups import FollowUpError, validate_items, validate_results

ACTUAL_RESULT_SCHEMA = "strixnova.actual-result.v1"
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
VERIFICATION_STATUSES = frozenset(
    {"not_required", "pending", "passed", "completed_with_issues"}
)
_FORBIDDEN_REPOSITORY_ROOTS = frozenset({".git", ".strixnova"})


class ActualResultError(ValueError):
    """An actual-result candidate does not satisfy its domain contract."""

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


def _text(
    value: Any,
    field: str,
    *,
    code: str = "actual_result_invalid",
) -> str:
    if not isinstance(value, str):
        raise ActualResultError(code, f"{field} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise ActualResultError(code, f"{field} 不能为空")
    return normalized


def _enum(
    value: Any,
    field: str,
    allowed: Sequence[str],
    *,
    code: str = "actual_result_invalid",
) -> str:
    normalized = _text(value, field, code=code)
    vocabulary = frozenset(allowed)
    if normalized not in vocabulary:
        raise ActualResultError(
            code,
            f"{field} 必须是 " + "、".join(sorted(vocabulary)) + " 之一",
        )
    return normalized


def _string_list(
    value: Any,
    field: str,
    *,
    required: bool = False,
    unique: bool = False,
    code: str = "invalid_actual_result",
) -> list[str]:
    if not isinstance(value, list):
        raise ActualResultError(code, f"{field} 必须是数组")
    normalized = [
        _text(item, f"{field}[{index}]", code=code)
        for index, item in enumerate(value)
    ]
    if required and not normalized:
        raise ActualResultError(code, f"{field} 不能为空")
    if unique and len(set(normalized)) != len(normalized):
        raise ActualResultError(code, f"{field} 不能包含重复值")
    return normalized


def validate_actual_result(
    value: Mapping[str, Any],
    coverage: Mapping[str, Any],
    *,
    project_dir: str | Path | None = None,
    repository_readers: Mapping[str | None, Any] | None = None,
    planned_operations: Sequence[Mapping[str, Any]] = (),
    planned_method_applications: Sequence[Mapping[str, Any]] = (),
    planned_domain_fact_changes: Sequence[Mapping[str, Any]] = (),
    planned_governance_rules: Sequence[Mapping[str, Any]] = (),
    planned_semantic_reviews: Sequence[Mapping[str, Any]] = (),
    planned_verification_targets: Sequence[Mapping[str, Any]] | None = None,
    planned_follow_up_refs: Sequence[Mapping[str, Any]] = (),
    expected_review_subject_ref: str | None = None,
) -> dict[str, Any]:
    """Validate coding-agent result claims against recorded receipt refs."""

    if not isinstance(value, Mapping):
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result 必须是对象",
        )
    required_fields = {
        "schema_version",
        "effect_summary",
        "delivered_outcomes",
        "deviations",
        "limitations",
        "verification_receipt_ids",
        "long_lived_refs",
        "method_application_results",
        "governance_rule_results",
        "semantic_content_machine_proven",
        "review_subject_ref",
    }
    allowed_fields = required_fields | {
        "domain_fact_change_results",
        "semantic_finding_results",
        "verification_review_results",
        "target_verification",
        "follow_up_items",
        "follow_up_results",
    }
    missing_fields = sorted(required_fields - set(value))
    extra_fields = sorted(set(value) - allowed_fields)
    if missing_fields or extra_fields:
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result 字段不完整"
            + (
                f"；缺少 {', '.join(missing_fields)}"
                if missing_fields
                else ""
            )
            + (
                f"；未知 {', '.join(extra_fields)}"
                if extra_fields
                else ""
            ),
        )
    if value.get("schema_version") != ACTUAL_RESULT_SCHEMA:
        raise ActualResultError(
            "invalid_actual_result",
            f"actual_result.schema_version 必须是 {ACTUAL_RESULT_SCHEMA}",
        )
    subject_ref = value.get("review_subject_ref")
    if not isinstance(subject_ref, str) or re.fullmatch(r"review-subject:[0-9a-f]{64}", subject_ref) is None:
        raise ActualResultError("review_subject_invalid", "实际结果必须引用审阅前取得的内容身份")
    if expected_review_subject_ref is not None and subject_ref != expected_review_subject_ref:
        raise ActualResultError("review_subject_changed", "审阅对象已变化；重新取得当前对象，核对受影响内容后再提交结论")
    if value.get("semantic_content_machine_proven") is not False:
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result.semantic_content_machine_proven 必须明确为 false",
        )
    try:
        verification_status = _enum(
            coverage.get("verification_status"),
            "verification_status",
            VERIFICATION_STATUSES,
            code="invalid_verification_coverage",
        )
    except ActualResultError as error:
        error.details = dict(coverage)
        raise
    if verification_status == "pending":
        raise ActualResultError(
            "verification_incomplete",
            "仍有未记录或明确要求重测的验证，不能展示实际结果",
            details=dict(coverage),
        )

    def actual_string_list(field: str, *, required: bool = False) -> list[str]:
        return _string_list(
            value.get(field),
            f"actual_result.{field}",
            required=required,
        )

    raw_latest_receipts = coverage.get("latest_receipt_ids")
    if not isinstance(raw_latest_receipts, Mapping):
        raise ActualResultError(
            "invalid_verification_coverage",
            "latest_receipt_ids 必须是对象",
        )
    expected_receipts = {
        _text(
            item,
            f"latest_receipt_ids.{command_id}",
            code="invalid_verification_coverage",
        )
        for command_id, item in raw_latest_receipts.items()
    }
    receipt_ids = actual_string_list(
        "verification_receipt_ids",
        required=bool(expected_receipts),
    )
    if set(receipt_ids) != expected_receipts or len(receipt_ids) != len(
        expected_receipts
    ):
        raise ActualResultError(
            "actual_result_receipts_mismatch",
            "actual_result 必须引用每项验证的最新回执且不得引用旧回执",
            details={
                "expected": sorted(expected_receipts),
                "submitted": receipt_ids,
            },
        )
    raw_refs = value.get("long_lived_refs")
    if not isinstance(raw_refs, list):
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result.long_lived_refs 必须是数组",
        )
    project = (
        Path(project_dir).expanduser().resolve()
        if project_dir is not None
        else None
    )
    normalized_refs: list[dict[str, str]] = []
    identities: set[tuple[str | None, str, str]] = set()
    for index, item in enumerate(raw_refs):
        if not isinstance(item, Mapping):
            raise ActualResultError(
                "invalid_actual_result",
                f"actual_result.long_lived_refs[{index}] 必须是对象",
            )
        expected_fields = {"artifact_id", "artifact_type", "path", "relation"}
        if not expected_fields.issubset(item) or set(item) - expected_fields - {"repository_id"}:
            raise ActualResultError(
                "invalid_actual_result",
                f"actual_result.long_lived_refs[{index}] 字段不完整或包含未知字段",
            )
        artifact_id = _text(
            item.get("artifact_id"),
            f"actual_result.long_lived_refs[{index}].artifact_id",
            code="invalid_actual_result",
        )
        artifact_type = _enum(
            item.get("artifact_type"),
            f"actual_result.long_lived_refs[{index}].artifact_type",
            ARTIFACT_TYPES,
            code="invalid_actual_result",
        )
        raw_path = _text(
            item.get("path"),
            f"actual_result.long_lived_refs[{index}].path",
            code="invalid_actual_result",
        )
        path = PurePosixPath(raw_path.replace("\\", "/"))
        if (
            path.is_absolute()
            or ".." in path.parts
            or ":" in raw_path
            or not path.parts
            or path.parts[0].casefold() in _FORBIDDEN_REPOSITORY_ROOTS
        ):
            raise ActualResultError(
                "invalid_actual_result",
                f"actual_result.long_lived_refs[{index}].path 必须是仓库内相对路径",
            )
        relative = path.as_posix()
        relation = _enum(
            item.get("relation"),
            f"actual_result.long_lived_refs[{index}].relation",
            {"introduced", "updated", "realized", "removed"},
            code="invalid_actual_result",
        )
        identifier = item.get("repository_id")
        if planned_operations:
            owners = {operation.get("repository_id") for operation in planned_operations if
                      (operation.get("long_lived_artifact") or {}).get("artifact_id") == artifact_id
                      and (operation.get("long_lived_artifact") or {}).get("artifact_type") == artifact_type
                      and (operation.get("to_path") if operation.get("action") == "move" else operation.get("path")) == relative}
            if identifier is None and len(owners) == 1:
                identifier = next(iter(owners))
            elif owners and identifier not in owners:
                raise ActualResultError("long_lived_repository_mismatch", "长期产物必须明确引用已计划的仓库")
        reader = None
        if repository_readers is not None:
            reader = repository_readers.get(identifier)
            if reader is None:
                raise ActualResultError("long_lived_repository_unavailable", "长期产物的仓库未绑定或引用不明确")
        elif identifier is not None and project is not None:
            raise ActualResultError("long_lived_repository_unavailable", "已限定仓库的产物必须使用该仓库读取器核对")
        if reader is not None:
            exists = reader.exists(relative)
        elif project is None:
            exists = True
        else:
            target = project.joinpath(*path.parts)
            if not target.resolve().is_relative_to(project) or any(parent.is_symlink() or parent.is_junction() for parent in (target, *target.parents) if parent != project and parent.is_relative_to(project)):
                raise ActualResultError("long_lived_artifact_outside_repository", "长期产物必须位于所选仓库的普通路径内")
            exists = target.is_file()
        if relation == "removed" and (project is not None or reader is not None) and exists:
            raise ActualResultError(
                "long_lived_artifact_not_removed",
                f"长期工程文件仍然存在：{relative}",
            )
        if relation != "removed" and not exists:
            raise ActualResultError(
                "long_lived_artifact_missing",
                f"长期工程文件不存在：{relative}",
            )
        identity = (identifier, artifact_id, relative)
        if identity in identities:
            raise ActualResultError(
                "invalid_actual_result",
                f"长期工程文件引用重复：{artifact_id} {relative}",
            )
        identities.add(identity)
        normalized_refs.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "path": relative,
                "relation": relation,
                **({"repository_id": identifier} if identifier is not None else {}),
            }
        )
    delivered_outcomes = actual_string_list("delivered_outcomes", required=True)
    deviations = actual_string_list("deviations")
    limitations = actual_string_list("limitations")
    if verification_status == "completed_with_issues" and not limitations:
        raise ActualResultError(
            "actual_result_limitations_missing",
            "验证存在失败、阻断或未运行项时，actual_result.limitations 不能为空",
        )
    expected_method_uses = {
        (application["method_id"], use["use_id"])
        for application in planned_method_applications
        if application.get("decision") == "applied"
        for use in application.get("planned_uses", [])
    }
    expected_methods = {method_id for method_id, _ in expected_method_uses}
    expected_fact_changes = {
        change["target_ref"]["fact_id"]: change
        for change in planned_domain_fact_changes
    }
    raw_method_results = value.get("method_application_results")
    if not isinstance(raw_method_results, list):
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result.method_application_results 必须是数组",
        )
    normalized_method_results: list[dict[str, Any]] = []
    seen_methods: set[str] = set()
    seen_uses: set[tuple[str, str]] = set()
    valid_result_evidence = {
        *receipt_ids,
        *{
            f"delivered_outcomes[{index}]"
            for index, _ in enumerate(delivered_outcomes)
        },
        *{f"deviations[{index}]" for index, _ in enumerate(deviations)},
        *{f"limitations[{index}]" for index, _ in enumerate(limitations)},
        *{f"artifact:{item['artifact_id']}" for item in normalized_refs},
    }
    expected_semantic_findings: dict[tuple[str, str], Mapping[str, Any]] = {}
    for review_index, review in enumerate(planned_semantic_reviews):
        if not isinstance(review, Mapping):
            raise ActualResultError(
                "invalid_semantic_review_plan",
                f"planned_semantic_reviews[{review_index}] 必须是对象",
            )
        review_id = _text(
            review.get("review_id"),
            f"planned_semantic_reviews[{review_index}].review_id",
            code="invalid_semantic_review_plan",
        )
        findings = review.get("findings")
        if not isinstance(findings, list):
            raise ActualResultError(
                "invalid_semantic_review_plan",
                f"planned_semantic_reviews[{review_index}].findings 必须是数组",
            )
        for finding_index, finding in enumerate(findings):
            path = (
                f"planned_semantic_reviews[{review_index}].findings"
                f"[{finding_index}]"
            )
            if not isinstance(finding, Mapping):
                raise ActualResultError(
                    "invalid_semantic_review_plan",
                    f"{path} 必须是对象",
                )
            finding_id = _text(
                finding.get("finding_id"),
                f"{path}.finding_id",
                code="invalid_semantic_review_plan",
            )
            status = _enum(
                finding.get("status"),
                f"{path}.status",
                {"open", "resolved", "accepted_risk"},
                code="invalid_semantic_review_plan",
            )
            identity = (review_id, finding_id)
            if identity in expected_semantic_findings:
                raise ActualResultError(
                    "invalid_semantic_review_plan",
                    f"语义发现身份重复：{review_id}/{finding_id}",
                )
            if status != "resolved":
                expected_semantic_findings[identity] = finding

    raw_finding_results = value.get("semantic_finding_results", [])
    if not isinstance(raw_finding_results, list):
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result.semantic_finding_results 必须是数组",
        )
    normalized_finding_results: list[dict[str, Any]] = []
    seen_finding_results: set[tuple[str, str]] = set()
    limitation_refs = {
        f"limitations[{index}]" for index, _ in enumerate(limitations)
    }
    for result_index, result in enumerate(raw_finding_results):
        path = f"actual_result.semantic_finding_results[{result_index}]"
        expected_fields = {
            "review_id",
            "finding_id",
            "outcome",
            "evidence_refs",
            "limitation_refs",
        }
        if not isinstance(result, Mapping) or set(result) != expected_fields:
            raise ActualResultError(
                "semantic_finding_result_mismatch",
                f"{path} 字段不完整或包含未知字段",
            )
        review_id = _text(
            result.get("review_id"),
            f"{path}.review_id",
            code="semantic_finding_result_mismatch",
        )
        finding_id = _text(
            result.get("finding_id"),
            f"{path}.finding_id",
            code="semantic_finding_result_mismatch",
        )
        identity = (review_id, finding_id)
        if identity not in expected_semantic_findings:
            raise ActualResultError(
                "semantic_finding_result_mismatch",
                f"{path} 引用了未计划或已经闭合的语义发现",
            )
        if identity in seen_finding_results:
            raise ActualResultError(
                "semantic_finding_result_mismatch",
                f"语义发现结果重复：{review_id}/{finding_id}",
            )
        seen_finding_results.add(identity)
        outcome = _enum(
            result.get("outcome"),
            f"{path}.outcome",
            {"resolved", "carried_as_limitation"},
            code="semantic_finding_result_mismatch",
        )
        evidence_refs = _string_list(
            result.get("evidence_refs"),
            f"{path}.evidence_refs",
            unique=True,
            code="semantic_finding_result_mismatch",
        )
        submitted_limitation_refs = _string_list(
            result.get("limitation_refs"),
            f"{path}.limitation_refs",
            unique=True,
            code="semantic_finding_result_mismatch",
        )
        unknown_evidence = sorted(set(evidence_refs) - valid_result_evidence)
        unknown_limitations = sorted(
            set(submitted_limitation_refs) - limitation_refs
        )
        if unknown_evidence or unknown_limitations:
            raise ActualResultError(
                "semantic_finding_result_mismatch",
                f"{path} 引用了未知实际证据或限制",
                details={
                    "unknown_evidence_refs": unknown_evidence,
                    "unknown_limitation_refs": unknown_limitations,
                },
            )
        if outcome == "resolved":
            if not evidence_refs or submitted_limitation_refs:
                raise ActualResultError(
                    "semantic_finding_result_mismatch",
                    f"{path} 声称已解决时必须提供实际证据且不得继续引用限制",
                )
        elif not submitted_limitation_refs:
            raise ActualResultError(
                "semantic_finding_result_mismatch",
                f"{path} 继续保留时必须精确引用 actual_result.limitations",
            )
        normalized_finding_results.append(
            {
                "review_id": review_id,
                "finding_id": finding_id,
                "outcome": outcome,
                "evidence_refs": evidence_refs,
                "limitation_refs": submitted_limitation_refs,
            }
        )
    missing_finding_results = sorted(
        expected_semantic_findings.keys() - seen_finding_results
    )
    if missing_finding_results:
        raise ActualResultError(
            "semantic_finding_result_mismatch",
            "actual_result 缺少仍开放或已接受风险的语义发现逐项结果",
            details=[
                f"{review_id}/{finding_id}"
                for review_id, finding_id in missing_finding_results
            ],
        )
    planned_rule_ids: list[str] = []
    for index, rule in enumerate(planned_governance_rules):
        if not isinstance(rule, Mapping):
            raise ActualResultError(
                "invalid_governance_rule_plan",
                f"planned_governance_rules[{index}] 必须是对象",
            )
        planned_rule_ids.append(
            _text(
                rule.get("rule_id"),
                f"planned_governance_rules[{index}].rule_id",
                code="invalid_governance_rule_plan",
            )
        )
    if len(planned_rule_ids) != len(set(planned_rule_ids)):
        raise ActualResultError(
            "invalid_governance_rule_plan",
            "planned_governance_rules 的 rule_id 不得重复",
        )
    expected_rule_ids = set(planned_rule_ids)
    raw_rule_results = value.get("governance_rule_results")
    if not isinstance(raw_rule_results, list):
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result.governance_rule_results 必须是数组",
        )
    normalized_rule_results: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()
    incomplete_rule_result = False
    for index, result in enumerate(raw_rule_results):
        result_path = f"actual_result.governance_rule_results[{index}]"
        expected_fields = {
            "rule_id",
            "status",
            "evidence_refs",
            "gaps",
            "remediation_actions",
            "limitations",
        }
        if not isinstance(result, Mapping) or set(result) != expected_fields:
            raise ActualResultError(
                "invalid_actual_result",
                f"{result_path} 字段不完整或包含未知字段",
            )
        rule_id = _text(
            result.get("rule_id"),
            f"{result_path}.rule_id",
            code="invalid_actual_result",
        )
        if rule_id not in expected_rule_ids:
            raise ActualResultError(
                "governance_rule_result_mismatch",
                f"{result_path} 引用了未计划的治理规则：{rule_id}",
            )
        if rule_id in seen_rule_ids:
            raise ActualResultError(
                "governance_rule_result_mismatch",
                f"治理规则结果重复：{rule_id}",
            )
        seen_rule_ids.add(rule_id)
        status = _enum(
            result.get("status"),
            f"{result_path}.status",
            {
                "satisfied",
                "partially_satisfied",
                "not_satisfied",
                "unknown",
            },
            code="invalid_actual_result",
        )
        evidence_refs = _string_list(
            result.get("evidence_refs"),
            f"{result_path}.evidence_refs",
            unique=True,
        )
        gaps = _string_list(
            result.get("gaps"),
            f"{result_path}.gaps",
            unique=True,
        )
        remediation_actions = _string_list(
            result.get("remediation_actions"),
            f"{result_path}.remediation_actions",
            unique=True,
        )
        rule_limitations = _string_list(
            result.get("limitations"),
            f"{result_path}.limitations",
            unique=True,
        )
        unknown_evidence = sorted(set(evidence_refs) - valid_result_evidence)
        if unknown_evidence:
            raise ActualResultError(
                "governance_rule_result_mismatch",
                f"{result_path}.evidence_refs 引用了未知实际证据："
                + ", ".join(unknown_evidence),
            )
        if status == "satisfied":
            if not evidence_refs:
                raise ActualResultError(
                    "governance_rule_result_mismatch",
                    f"{rule_id} 声称满足时必须引用实际证据",
                )
            if gaps or remediation_actions:
                raise ActualResultError(
                    "governance_rule_result_mismatch",
                    f"{rule_id} 声称满足时不得同时保留缺口或纠偏行动",
                )
        else:
            incomplete_rule_result = True
            if not gaps or not remediation_actions:
                raise ActualResultError(
                    "governance_rule_result_mismatch",
                    f"{rule_id} 未完全满足时必须同时记录缺口和纠偏行动",
                )
            if status == "partially_satisfied" and not evidence_refs:
                raise ActualResultError(
                    "governance_rule_result_mismatch",
                    f"{rule_id} 部分满足时必须引用已满足部分的实际证据",
                )
        normalized_rule_results.append(
            {
                "rule_id": rule_id,
                "status": status,
                "evidence_refs": evidence_refs,
                "gaps": gaps,
                "remediation_actions": remediation_actions,
                "limitations": rule_limitations,
            }
        )
    missing_rule_ids = sorted(expected_rule_ids - seen_rule_ids)
    if missing_rule_ids:
        raise ActualResultError(
            "governance_rule_result_mismatch",
            "actual_result 缺少已计划治理规则的逐项结果",
            details=missing_rule_ids,
        )
    any_not_realized = False
    normalized_fact_results: list[dict[str, Any]] = []
    seen_fact_changes: set[str] = set()
    raw_fact_results = value.get("domain_fact_change_results", [])
    if not isinstance(raw_fact_results, list):
        raise ActualResultError(
            "invalid_actual_result",
            "actual_result.domain_fact_change_results 必须是数组",
        )
    for result_index, change_result in enumerate(raw_fact_results):
        result_path = f"actual_result.domain_fact_change_results[{result_index}]"
        if not isinstance(change_result, Mapping) or set(change_result) != {
            "target_ref",
            "outcome",
            "evidence_refs",
            "limitations",
        }:
            raise ActualResultError(
                "invalid_actual_result",
                f"{result_path} 字段不完整或包含未知字段",
            )
        raw_target_ref = change_result.get("target_ref")
        if not isinstance(raw_target_ref, Mapping):
            raise ActualResultError(
                "invalid_actual_result",
                f"{result_path}.target_ref 无效",
            )
        fact_id = raw_target_ref.get("fact_id")
        if not isinstance(fact_id, str) or not fact_id.strip():
            raise ActualResultError(
                "invalid_actual_result",
                f"{result_path}.target_ref.fact_id 无效",
            )
        planned_change = expected_fact_changes.get(fact_id)
        target_ref = dict(raw_target_ref)
        if planned_change is None or target_ref != planned_change["target_ref"]:
            raise ActualResultError(
                "domain_fact_change_result_mismatch",
                f"{result_path} 引用了未计划的领域 Fact 变化",
            )
        if fact_id in seen_fact_changes:
            raise ActualResultError(
                "domain_fact_change_result_mismatch",
                f"{result_path} 重复",
            )
        seen_fact_changes.add(fact_id)
        change_evidence = _string_list(
            change_result.get("evidence_refs"),
            f"{result_path}.evidence_refs",
            required=True,
            unique=True,
        )
        change_limitations = _string_list(
            change_result.get("limitations"),
            f"{result_path}.limitations",
        )
        unknown_evidence = sorted(set(change_evidence) - valid_result_evidence)
        if unknown_evidence:
            raise ActualResultError(
                "domain_fact_change_result_mismatch",
                f"{result_path}.evidence_refs 引用了未知实际证据："
                + ", ".join(unknown_evidence),
            )
        outcome = _enum(
            change_result.get("outcome"),
            f"{result_path}.outcome",
            {"realized", "deferred", "deviated"},
            code="invalid_actual_result",
        )
        if outcome != "realized":
            any_not_realized = True
            if not change_limitations:
                raise ActualResultError(
                    "domain_fact_change_result_mismatch",
                    f"{result_path}.limitations 必须解释未落实的领域变化",
                )
        normalized_fact_results.append(
            {
                "target_ref": target_ref,
                "outcome": outcome,
                "evidence_refs": change_evidence,
                "limitations": change_limitations,
            }
        )

    for method_index, method_result in enumerate(raw_method_results):
        method_path = f"actual_result.method_application_results[{method_index}]"
        if not isinstance(method_result, Mapping):
            raise ActualResultError(
                "invalid_actual_result",
                f"{method_path} 必须是对象",
            )
        expected_method_fields = {
            "method_id",
            "use_results",
            "deviations",
        }
        if set(method_result) != expected_method_fields:
            raise ActualResultError(
                "invalid_actual_result",
                f"{method_path} 字段不完整或包含未知字段",
            )
        method_id = _text(
            method_result.get("method_id"),
            f"{method_path}.method_id",
            code="invalid_actual_result",
        )
        if method_id not in expected_methods:
            raise ActualResultError(
                "method_application_result_mismatch",
                f"{method_path} 引用了未计划应用的方法：{method_id}",
            )
        if method_id in seen_methods:
            raise ActualResultError(
                "method_application_result_mismatch",
                f"工程方法结果重复：{method_id}",
            )
        seen_methods.add(method_id)
        method_deviations = _string_list(
            method_result.get("deviations"),
            f"{method_path}.deviations",
        )
        raw_use_results = method_result.get("use_results")
        if not isinstance(raw_use_results, list) or not raw_use_results:
            raise ActualResultError(
                "invalid_actual_result",
                f"{method_path}.use_results 不能为空",
            )
        normalized_uses: list[dict[str, Any]] = []
        method_has_not_realized = False
        for use_index, use_result in enumerate(raw_use_results):
            use_path = f"{method_path}.use_results[{use_index}]"
            if not isinstance(use_result, Mapping):
                raise ActualResultError(
                    "invalid_actual_result",
                    f"{use_path} 必须是对象",
                )
            expected_use_fields = {"use_id", "status", "outcome", "evidence_refs"}
            if set(use_result) != expected_use_fields:
                raise ActualResultError(
                    "invalid_actual_result",
                    f"{use_path} 字段不完整或包含未知字段",
                )
            use_id = _text(
                use_result.get("use_id"),
                f"{use_path}.use_id",
                code="invalid_actual_result",
            )
            identity = (method_id, use_id)
            if identity not in expected_method_uses:
                raise ActualResultError(
                    "method_application_result_mismatch",
                    f"{use_path} 引用了未计划的方法使用：{method_id}/{use_id}",
                )
            if identity in seen_uses:
                raise ActualResultError(
                    "method_application_result_mismatch",
                    f"方法使用结果重复：{method_id}/{use_id}",
                )
            seen_uses.add(identity)
            evidence_refs = _string_list(
                use_result.get("evidence_refs"),
                f"{use_path}.evidence_refs",
                required=True,
                unique=True,
            )
            unknown_evidence = sorted(set(evidence_refs) - valid_result_evidence)
            if unknown_evidence:
                raise ActualResultError(
                    "method_application_result_mismatch",
                    f"{use_path}.evidence_refs 引用了未知实际证据："
                    + ", ".join(unknown_evidence),
                )
            status = _enum(
                use_result.get("status"),
                f"{use_path}.status",
                {"realized", "not_realized"},
                code="invalid_actual_result",
            )
            if status == "not_realized":
                any_not_realized = True
                method_has_not_realized = True
            normalized_uses.append(
                {
                    "use_id": use_id,
                    "status": status,
                    "outcome": _text(
                        use_result.get("outcome"),
                        f"{use_path}.outcome",
                        code="invalid_actual_result",
                    ),
                    "evidence_refs": evidence_refs,
                }
            )
        if method_has_not_realized and not method_deviations:
            raise ActualResultError(
                "method_application_result_mismatch",
                f"{method_path}.deviations 必须解释未实现的方法使用",
            )
        normalized_method_results.append(
            {
                "method_id": method_id,
                "use_results": normalized_uses,
                "deviations": method_deviations,
            }
        )
    missing_method_uses = sorted(expected_method_uses - seen_uses)
    if missing_method_uses:
        raise ActualResultError(
            "method_application_result_mismatch",
            "actual_result 缺少已计划方法使用的实际结果",
            details=[f"{method_id}/{use_id}" for method_id, use_id in missing_method_uses],
        )
    missing_fact_changes = sorted(
        set(expected_fact_changes) - seen_fact_changes
    )
    if missing_fact_changes:
        raise ActualResultError(
            "domain_fact_change_result_mismatch",
            "actual_result 缺少已计划领域 Fact 变化的实际结果",
            details=missing_fact_changes,
        )
    if incomplete_rule_result and not limitations:
        raise ActualResultError(
            "governance_rule_result_mismatch",
            "存在未完全满足的治理规则时，actual_result.limitations 不能为空",
        )
    if any_not_realized and not limitations:
        raise ActualResultError(
            "method_application_result_mismatch",
            "存在未实现的方法使用或领域变化时，actual_result.limitations 不能为空",
        )
    try:
        review_results, target_verification = assess_targets(
            planned_verification_targets, value.get("verification_review_results", []),
            coverage=coverage, known_evidence=valid_result_evidence, limitations=limitations,
        )
        if "target_verification" in value and value["target_verification"] != target_verification:
            raise ActualResultError("verification_target_summary_changed", "逐项目标核验摘要必须由当前方案与结果派生，不能自行替换")
        follow_up_items = validate_items(value.get("follow_up_items", []), limitations)
        follow_up_results = validate_results(
            value.get("follow_up_results", []), expected_refs=list(planned_follow_up_refs),
            known_evidence=valid_result_evidence, limitations=limitations,
        )
    except (VerificationTargetError, FollowUpError) as error:
        raise ActualResultError(error.code, str(error), details=error.details) from error
    return {
        "schema_version": ACTUAL_RESULT_SCHEMA,
        "review_subject_ref": subject_ref,
        "verification_review_results": review_results,
        "target_verification": target_verification,
        "follow_up_items": follow_up_items,
        "follow_up_results": follow_up_results,
        "effect_summary": _text(
            value.get("effect_summary"),
            "actual_result.effect_summary",
            code="invalid_actual_result",
        ),
        "delivered_outcomes": delivered_outcomes,
        "deviations": deviations,
        "limitations": limitations,
        "verification_receipt_ids": receipt_ids,
        "long_lived_refs": normalized_refs,
        "domain_fact_change_results": normalized_fact_results,
        "semantic_finding_results": normalized_finding_results,
        "method_application_results": normalized_method_results,
        "governance_rule_results": normalized_rule_results,
        "semantic_content_machine_proven": False,
    }

__all__ = [
    "ACTUAL_RESULT_SCHEMA",
    "ActualResultError",
    "validate_actual_result",
]
