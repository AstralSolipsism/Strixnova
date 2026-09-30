"""Single local authority for WorkItem workflow facts.

The public interface is deliberately small: create one WorkItem, apply one
typed transition, and read current or historical projections. SQLite owns
physical atomicity; callers never coordinate files, pointers, or hashes.
"""

from __future__ import annotations

from collections.abc import Mapping
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Any, Iterator

from strixnova.behavior_examples import BehaviorExampleError, example_catalog, example_ids, normalize_behavior
from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance, connect_with_maintenance
from strixnova.storage_formats import (
    AUTHORITY_FORMAT, ensure_evidence_schema, insert_evidence, install_write_guards,
)

from strixnova.confirmation_protocol import (
    ConfirmationProtocolError,
    confirmation_challenge_for,
    confirmation_record_from_input,
    reproduce_confirmation_record,
)
from strixnova.current_action import current_action_for
from strixnova.work_item_repositories import (
    planned_repository_deliveries, persist_repository_view, repository_phase,
    repository_view, selected_repository, ordered_repository,
)
from strixnova.engineering_change_planning import (
    ChangePlanningError,
    validate_semantic_review,
)
from strixnova.project_authority_progress import (
    project_authority_review_matches_plan_structure,
    project_authority_stage,
)
from strixnova.work_item_relations import (
    WorkItemRelationError,
    normalize_work_item_relations,
    relation_target_ids,
)
from strixnova.follow_ups import FollowUpError, check_current_results, declared_refs, project_records, ref_key


AUTHORITY_SCHEMA_VERSION = str(AUTHORITY_FORMAT)
AUTHORITY_DATABASE_NAME = "authority.sqlite3"
DELIVERY_ACTIVITY_DATABASE_NAME = "delivery-activities.sqlite3"
AUTHORITY_GITIGNORE_LINES = ("*",)
AUTHORITY_LOCAL_EXCLUDE_LINES = (
    "/.strixnova/.gitignore",
    "/.strixnova/authority.sqlite3*",
    "/.strixnova/artifacts/",
    "/.strixnova/delivery-activities.sqlite3*",
)
DIRECTION_SCHEMA = "strixnova.direction-decision.v1"

_DIRECTION_REQUIREMENT_ID = re.compile(r"^DIRREQ-[0-9A-F]{16}$")
_DIRECTION_CONSTRAINT_ID = re.compile(r"^DIRCON-[0-9A-F]{16}$")
_DIRECTION_ACCEPTANCE_ID = re.compile(r"^DIRACC-[0-9A-F]{16}$")

WORK_ITEM_STATES = frozenset(
    {
        "discussion",
        "awaiting_direction_confirmation",
        "needs_engineering_assessment",
        "awaiting_plan_confirmation",
        "implementation_ready",
        "exploring",
        "implementing",
        "awaiting_actual_result",
        "commit_required",
        "integration_required",
        "integration_conflict",
        "cleanup_required",
        "replanning_required",
        "cancelled_changes_pending",
        "cancelled",
        "completed",
    }
)

TERMINAL_STATES = frozenset({"cancelled", "completed"})


class WorkflowAuthorityError(RuntimeError):
    """A typed failure at the WorkflowAuthority interface."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class AuthorityConflict(WorkflowAuthorityError):
    """A caller attempted a transition from an outdated WorkItem version."""


class WorkItemNotFound(WorkflowAuthorityError):
    """The requested WorkItem does not exist."""


class AuthorityNotInitialized(WorkflowAuthorityError):
    """A read requiring an existing Authority was attempted before intake."""


class InvalidTransition(WorkflowAuthorityError):
    """The requested action is not valid from the current state."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _history_time_key(value: str) -> str:
    """Compare full-precision UTC instants without rewriting recorded text."""
    instant = datetime.fromisoformat(value)
    return instant.replace(tzinfo=instant.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat(timespec="microseconds")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise InvalidTransition("invalid_payload", f"{field} 必须是对象")
    return deepcopy(dict(value))


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise InvalidTransition("invalid_payload", f"{field} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise InvalidTransition("invalid_payload", f"{field} 不能为空")
    return normalized


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise InvalidTransition("invalid_payload", f"{field} 必须是布尔值")
    return value


def _string_list(value: Any, field: str, *, required: bool = False) -> list[str]:
    if not isinstance(value, list):
        raise InvalidTransition("invalid_payload", f"{field} 必须是数组")
    normalized = [
        _text(item, f"{field}[{index}]")
        for index, item in enumerate(value)
    ]
    if required and not normalized:
        raise InvalidTransition("invalid_payload", f"{field} 不能为空")
    return normalized


def _enum(value: Any, field: str, allowed: set[str]) -> str:
    normalized = _text(value, field)
    if normalized not in allowed:
        raise InvalidTransition(
            "invalid_payload",
            f"{field} 必须是 " + "、".join(sorted(allowed)) + " 之一",
        )
    return normalized


def _direction_context_binding(value: Any) -> dict[str, Any]:
    context = _object(value, "direction.decision_context")
    required = {
        "context_ref",
        "capability_refs",
        "guardrail_dispositions",
        "assumptions",
    }
    missing = sorted(required - set(context))
    extra = sorted(set(context) - required)
    if missing:
        raise InvalidTransition(
            "direction_context_incomplete",
            "direction.decision_context 缺少字段：" + ", ".join(missing),
        )
    if extra:
        raise InvalidTransition(
            "direction_context_invalid",
            "direction.decision_context 包含未知字段：" + ", ".join(extra),
        )

    raw_context_ref = context.get("context_ref")
    context_ref = (
        None
        if raw_context_ref is None
        else _text(raw_context_ref, "direction.decision_context.context_ref")
    )
    capability_refs = _string_list(
        context.get("capability_refs"),
        "direction.decision_context.capability_refs",
    )
    if len(set(capability_refs)) != len(capability_refs):
        raise InvalidTransition(
            "direction_context_invalid",
            "direction.decision_context.capability_refs 不得重复",
        )

    raw_dispositions = context.get("guardrail_dispositions")
    if not isinstance(raw_dispositions, list):
        raise InvalidTransition(
            "direction_context_invalid",
            "direction.decision_context.guardrail_dispositions 必须是数组",
        )
    dispositions: list[dict[str, str]] = []
    for index, raw in enumerate(raw_dispositions):
        path = f"direction.decision_context.guardrail_dispositions[{index}]"
        item = _object(raw, path)
        if set(item) != {"decision_ref", "disposition", "reason"}:
            raise InvalidTransition(
                "direction_context_invalid",
                f"{path} 必须且只能包含 decision_ref、disposition 和 reason",
            )
        dispositions.append(
            {
                "decision_ref": _text(item.get("decision_ref"), f"{path}.decision_ref"),
                "disposition": _enum(
                    item.get("disposition"),
                    f"{path}.disposition",
                    {"applies", "not_applicable", "reconsider"},
                ),
                "reason": _text(item.get("reason"), f"{path}.reason"),
            }
        )
    disposition_refs = [item["decision_ref"] for item in dispositions]
    if len(set(disposition_refs)) != len(disposition_refs):
        raise InvalidTransition(
            "direction_context_invalid",
            "direction.decision_context.guardrail_dispositions.decision_ref 不得重复",
        )

    raw_assumptions = context.get("assumptions")
    if not isinstance(raw_assumptions, list):
        raise InvalidTransition(
            "direction_context_invalid",
            "direction.decision_context.assumptions 必须是数组",
        )
    assumptions: list[dict[str, str]] = []
    for index, raw in enumerate(raw_assumptions):
        path = f"direction.decision_context.assumptions[{index}]"
        item = _object(raw, path)
        if set(item) != {"statement", "reconsider_when"}:
            raise InvalidTransition(
                "direction_context_invalid",
                f"{path} 必须且只能包含 statement 和 reconsider_when",
            )
        assumptions.append(
            {
                "statement": _text(item.get("statement"), f"{path}.statement"),
                "reconsider_when": _text(
                    item.get("reconsider_when"),
                    f"{path}.reconsider_when",
                ),
            }
        )

    if context_ref is None and (capability_refs or dispositions):
        raise InvalidTransition(
            "direction_context_invalid",
            "没有已采用产品权威时，能力引用和护栏处置必须为空",
        )
    if context_ref is not None and not capability_refs:
        raise InvalidTransition(
            "direction_context_incomplete",
            "已有产品决定上下文时，智能编码代理必须选择至少一项相关能力",
        )
    return {
        "context_ref": context_ref,
        "capability_refs": capability_refs,
        "guardrail_dispositions": dispositions,
        "assumptions": assumptions,
    }


def _direction_identifier(
    value: Any,
    *,
    path: str,
    pattern: re.Pattern[str],
) -> str:
    identifier = _text(value, path)
    if identifier != value or pattern.fullmatch(identifier) is None:
        raise InvalidTransition(
            "direction_item_invalid",
            f"{path} 格式无效",
        )
    return identifier


def _direction_statement_items(
    value: Any,
    *,
    field: str,
    identifier_field: str,
    identifier_pattern: re.Pattern[str],
    required: bool = False,
) -> list[dict[str, str]]:
    raw_items = value
    if not isinstance(raw_items, list):
        raise InvalidTransition(
            "direction_item_invalid",
            f"direction.{field} 必须是数组",
        )
    if required and not raw_items:
        raise InvalidTransition(
            "direction_incomplete",
            f"direction.{field} 至少需要一项",
        )
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        path = f"direction.{field}[{index}]"
        item = _object(raw_item, path)
        if set(item) != {identifier_field, "statement"}:
            raise InvalidTransition(
                "direction_item_invalid",
                f"{path} 必须且只能包含 {identifier_field} 和 statement",
            )
        identifier = _direction_identifier(
            item.get(identifier_field),
            path=f"{path}.{identifier_field}",
            pattern=identifier_pattern,
        )
        if identifier in seen:
            raise InvalidTransition(
                "direction_item_duplicate",
                f"direction.{field} 中身份重复：{identifier}",
            )
        seen.add(identifier)
        result.append(
            {
                identifier_field: identifier,
                "statement": _text(item.get("statement"), f"{path}.statement"),
            }
        )
    return result


def _normalized_behavior(value: Any) -> dict[str, Any]:
    try:
        return normalize_behavior(value)
    except BehaviorExampleError as error:
        raise InvalidTransition(error.code, str(error)) from error


def _direction_acceptance_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise InvalidTransition(
            "direction_item_invalid",
            "direction.acceptance 必须是数组",
        )
    if not value:
        raise InvalidTransition(
            "direction_incomplete",
            "direction.acceptance 至少需要一项",
        )
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(value):
        path = f"direction.acceptance[{index}]"
        item = _object(raw_item, path)
        if set(item) != {"acceptance_id", "statement", "requirement_refs", "behavior"}:
            raise InvalidTransition(
                "direction_item_invalid",
                f"{path} 必须且只能包含 acceptance_id、statement、requirement_refs 和 behavior",
            )
        identifier = _direction_identifier(
            item.get("acceptance_id"),
            path=f"{path}.acceptance_id",
            pattern=_DIRECTION_ACCEPTANCE_ID,
        )
        if identifier in seen:
            raise InvalidTransition(
                "direction_item_duplicate",
                f"direction.acceptance 中身份重复：{identifier}",
            )
        seen.add(identifier)
        raw_refs = item.get("requirement_refs")
        if not isinstance(raw_refs, list) or not raw_refs:
            raise InvalidTransition(
                "direction_item_invalid",
                f"{path}.requirement_refs 必须是非空数组",
            )
        requirement_refs: list[str] = []
        for ref_index, raw_ref in enumerate(raw_refs):
            requirement_refs.append(
                _direction_identifier(
                    raw_ref,
                    path=f"{path}.requirement_refs[{ref_index}]",
                    pattern=_DIRECTION_REQUIREMENT_ID,
                )
            )
        if len(set(requirement_refs)) != len(requirement_refs):
            raise InvalidTransition(
                "direction_item_duplicate",
                f"{path}.requirement_refs 不得重复",
            )
        result.append(
            {
                "acceptance_id": identifier,
                "statement": _text(item.get("statement"), f"{path}.statement"),
                "requirement_refs": requirement_refs,
                "behavior": _normalized_behavior(item.get("behavior")),
            }
        )
    return result


def _confirmed_direction(
    value: Mapping[str, Any],
    *,
    source_work_item_id: str,
) -> dict[str, Any]:
    required = {
        "schema_version",
        "decision_context",
        "goal",
        "scope",
        "non_goals",
        "constraints",
        "tradeoffs",
        "acceptance",
    }
    allowed = required | {"work_item_relations"}
    missing = sorted(required - set(value))
    extra = sorted(set(value) - allowed)
    if missing:
        raise InvalidTransition(
            "direction_incomplete",
            "direction 缺少字段：" + ", ".join(missing),
        )
    if extra:
        raise InvalidTransition(
            "direction_invalid",
            "direction 包含未知字段：" + ", ".join(extra),
        )
    if value.get("schema_version") != DIRECTION_SCHEMA:
        raise InvalidTransition(
            "direction_invalid",
            f"direction.schema_version 必须是 {DIRECTION_SCHEMA}",
        )
    requirements = _direction_statement_items(
        value.get("scope"),
        field="scope",
        identifier_field="requirement_id",
        identifier_pattern=_DIRECTION_REQUIREMENT_ID,
        required=True,
    )
    constraints = _direction_statement_items(
        value.get("constraints"),
        field="constraints",
        identifier_field="constraint_id",
        identifier_pattern=_DIRECTION_CONSTRAINT_ID,
    )
    acceptance = _direction_acceptance_items(value.get("acceptance"))
    requirement_ids = {item["requirement_id"] for item in requirements}
    referenced_requirement_ids = {
        requirement_id
        for item in acceptance
        for requirement_id in item["requirement_refs"]
    }
    unknown_requirement_ids = sorted(
        referenced_requirement_ids - requirement_ids
    )
    if unknown_requirement_ids:
        raise InvalidTransition(
            "direction_requirement_ref_unknown",
            "direction.acceptance 引用了未知方向需求："
            + ", ".join(unknown_requirement_ids),
        )
    uncovered_requirement_ids = sorted(
        requirement_ids - referenced_requirement_ids
    )
    if uncovered_requirement_ids:
        raise InvalidTransition(
            "direction_requirement_uncovered",
            "方向需求缺少验收条件覆盖："
            + ", ".join(uncovered_requirement_ids),
        )
    confirmed = {
        "schema_version": DIRECTION_SCHEMA,
        "decision_context": _direction_context_binding(
            value.get("decision_context")
        ),
        "goal": _text(value.get("goal"), "direction.goal"),
        "scope": requirements,
        "non_goals": _string_list(value.get("non_goals"), "direction.non_goals"),
        "constraints": constraints,
        "tradeoffs": _string_list(value.get("tradeoffs"), "direction.tradeoffs"),
        "acceptance": acceptance,
    }
    if "work_item_relations" in value:
        try:
            confirmed["work_item_relations"] = normalize_work_item_relations(
                value.get("work_item_relations"),
                source_work_item_id=source_work_item_id,
            )
        except WorkItemRelationError as error:
            raise InvalidTransition(error.code, str(error)) from error
    try:
        example_catalog(confirmed)
    except BehaviorExampleError as error:
        raise InvalidTransition(error.code, str(error)) from error
    return confirmed


def _direction_submission(
    body: Mapping[str, Any],
    *,
    work_item_id: str,
) -> tuple[dict[str, Any], bool, list[str]]:
    direction = _object(body.get("direction"), "direction")
    if "schema_version" in direction and direction["schema_version"] != DIRECTION_SCHEMA:
        raise InvalidTransition("direction_invalid", "方向草稿的格式标记必须属于当前合同")
    ready = _boolean(
        body.get("ready_for_confirmation"),
        "ready_for_confirmation",
    )
    blockers = _string_list(
        body["blockers"] if "blockers" in body else [],
        "blockers",
    )
    if ready and blockers:
        raise InvalidTransition(
            "direction_invalid",
            "ready_for_confirmation 为 true 时 blockers 必须为空",
        )
    if not ready and not blockers:
        raise InvalidTransition(
            "direction_incomplete",
            "方向尚不能确认时必须说明 blockers",
        )
    normalized = (
        _confirmed_direction(
            direction,
            source_work_item_id=work_item_id,
        )
        if ready
        else direction
    )
    return normalized, ready, blockers


def _require_status(
    current: str,
    action: str,
    allowed: set[str] | frozenset[str],
) -> None:
    if current not in allowed:
        raise InvalidTransition(
            "invalid_transition",
            f"{action} 不能从 {current} 执行",
        )


def _validated_slice_completion(value: Any, field: str) -> dict[str, Any]:
    completion = _object(value, field)
    if (
        completion.get("schema_version")
        != "strixnova.implementation-slice-completion.v1"
        or completion.get("semantic_content_machine_proven") is not False
    ):
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片完成记录结构无效",
        )
    slice_id = _text(completion.get("slice_id"), f"{field}.slice_id")
    summary = _text(
        completion.get("completion_summary"),
        f"{field}.completion_summary",
    )
    evidence_kind = _enum(
        completion.get("evidence_kind"),
        f"{field}.evidence_kind",
        {"explicit_no_command", "verified_commands"},
    )
    source_receipt_ids = _string_list(
        completion.get("source_receipt_ids"),
        f"{field}.source_receipt_ids",
    )
    if evidence_kind == "verified_commands" and not source_receipt_ids:
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "验证切片完成记录必须引用真实验证回执",
        )
    if evidence_kind == "explicit_no_command" and source_receipt_ids:
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "无命令切片完成记录不得引用验证回执",
        )
    raw_operation_results = completion.get("operation_results")
    if not isinstance(raw_operation_results, list) or not raw_operation_results:
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片完成记录必须逐项证明计划文件操作已经形成",
        )
    operation_results: list[dict[str, Any]] = []
    seen_operation_refs: set[str] = set()
    for index, raw in enumerate(raw_operation_results):
        result = _object(raw, f"{field}.operation_results[{index}]")
        operation_ref = _text(
            result.get("operation_ref"),
            f"{field}.operation_results[{index}].operation_ref",
        )
        action = _enum(
            result.get("action"),
            f"{field}.operation_results[{index}].action",
            {"create", "modify", "delete", "move"},
        )
        path = _text(
            result.get("path"),
            f"{field}.operation_results[{index}].path",
        )
        to_path = result.get("to_path")
        if action == "move":
            to_path = _text(
                to_path,
                f"{field}.operation_results[{index}].to_path",
            )
        elif to_path is not None:
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "只有 move 操作结果可以包含 to_path",
            )
        if result.get("realized") is not True:
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "完成记录中的计划文件操作必须全部明确为已形成",
            )
        if operation_ref in seen_operation_refs:
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "完成记录中的计划文件操作引用重复",
            )
        seen_operation_refs.add(operation_ref)
        normalized_result: dict[str, Any] = {
            "operation_ref": operation_ref,
            "action": action,
            "path": path,
            "to_path": to_path if action == "move" else None,
            "realized": True,
        }
        if "repository_id" in result:
            normalized_result["repository_id"] = result["repository_id"]
        operation_results.append(normalized_result)
    raw_snapshot = completion.get("owned_path_snapshot")
    if not isinstance(raw_snapshot, list) or not raw_snapshot:
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片完成记录必须包含非空文件快照",
        )
    snapshot: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(raw_snapshot):
        entry = _object(raw, f"{field}.owned_path_snapshot[{index}]")
        path = _text(
            entry.get("path"),
            f"{field}.owned_path_snapshot[{index}].path",
        )
        state = _enum(
            entry.get("state"),
            f"{field}.owned_path_snapshot[{index}].state",
            {"file", "absent"},
        )
        sha256 = entry.get("sha256")
        if not isinstance(sha256, str) or (
            state == "file" and len(sha256) != 64
        ) or (state == "absent" and sha256 != ""):
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "实施切片文件快照散列与路径状态不一致",
            )
        path_key = (entry.get("repository_id"), path)
        if path_key in seen_paths:
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "实施切片文件快照路径重复",
            )
        seen_paths.add(path_key)
        snapshot.append({"path": path, "state": state, "sha256": sha256, **({"repository_id": entry["repository_id"]} if "repository_id" in entry else {})})
    return {
        "schema_version": "strixnova.implementation-slice-completion.v1",
        "slice_id": slice_id,
        "completion_summary": summary,
        "evidence_kind": evidence_kind,
        "source_receipt_ids": source_receipt_ids,
        "operation_results": operation_results,
        "owned_path_snapshot": snapshot,
        "semantic_content_machine_proven": False,
    }


def _require_slice_completion_matches_plan(
    data: Mapping[str, Any],
    completion: Mapping[str, Any],
) -> None:
    """Reject a structurally valid completion that does not close its slice."""

    engineering = data.get("engineering")
    plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
    if not isinstance(plan, Mapping):
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片完成记录缺少当前工程方案",
        )
    slice_id = str(completion.get("slice_id") or "")
    slice_value = next(
        (
            value
            for value in plan.get("implementation_slices") or []
            if isinstance(value, Mapping)
            and value.get("slice_id") == slice_id
        ),
        None,
    )
    if not isinstance(slice_value, Mapping):
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片完成记录不属于当前工程方案",
        )
    expected_refs = list(
        dict.fromkeys(
            [
                *(slice_value.get("operation_refs") or []),
                *(slice_value.get("continued_operation_refs") or []),
            ]
        )
    )
    actual_results = list(completion.get("operation_results") or [])
    actual_refs = [
        str(value.get("operation_ref") or "")
        for value in actual_results
        if isinstance(value, Mapping)
    ]
    if actual_refs != expected_refs:
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片完成记录必须按方案顺序逐项覆盖本切片全部操作",
        )
    operations = list(plan.get("operations") or [])
    expected_paths: set[str] = set()
    for reference, result in zip(expected_refs, actual_results, strict=True):
        index_text = (
            reference[len("operations[") : -1]
            if reference.startswith("operations[") and reference.endswith("]")
            else ""
        )
        if not index_text.isdigit() or int(index_text) >= len(operations):
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "实施切片完成记录引用了未知计划操作",
            )
        operation = operations[int(index_text)]
        if not isinstance(operation, Mapping):
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "实施切片计划操作结构无效",
            )
        expected = {
            "operation_ref": reference,
            "action": str(operation.get("action") or ""),
            "path": str(operation.get("path") or "").replace("\\", "/"),
            "to_path": (
                str(operation.get("to_path") or "").replace("\\", "/")
                if operation.get("action") == "move"
                else None
            ),
            "realized": True,
        }
        if "repository_id" in operation:
            expected["repository_id"] = operation["repository_id"]
        if dict(result) != expected:
            raise InvalidTransition(
                "implementation_slice_completion_invalid",
                "实施切片完成记录与当前方案中的精确操作不一致",
            )
        expected_paths.add((expected.get("repository_id"), expected["path"]))
        if expected["to_path"]:
            expected_paths.add((expected.get("repository_id"), str(expected["to_path"])))
    snapshot_paths = {
        (value.get("repository_id"), str(value.get("path") or ""))
        for value in completion.get("owned_path_snapshot") or []
        if isinstance(value, Mapping)
    }
    if snapshot_paths != expected_paths:
        raise InvalidTransition(
            "implementation_slice_completion_invalid",
            "实施切片文件快照必须精确覆盖本切片全部操作路径",
        )


def _initial_data(raw_request: str, project_id: str | None = None) -> dict[str, Any]:
    return {
        "raw_request": raw_request,
        "project_id": project_id,
        "repository_deliveries": [],
        "direction": None,
        "direction_confirmation": None,
        "direction_item_history": {
            "active_ids": [],
            "retired_ids": [],
        },
        "engineering": {
            "assessment": None,
            "plan": None,
            "plan_confirmation": None,
        },
        "git": {},
        "verifications": [],
        "implementation_slice_completions": [],
        "project_authority_presentations": [],
        "project_authority_reviews": [],
        "project_authority_decisions": [],
        "actual_result": None,
        "actual_result_confirmation": None,
        "authority_adoption": None,
        "cancellation": None,
        "pending_effect": None,
        "blockers": [],
    }


def _direction_item_ids(direction: Mapping[str, Any]) -> set[str]:
    return {
        *example_ids(direction),
        *(
            str(item.get("requirement_id"))
            for item in direction.get("scope") or []
            if isinstance(item, Mapping)
        ),
        *(
            str(item.get("constraint_id"))
            for item in direction.get("constraints") or []
            if isinstance(item, Mapping)
        ),
        *(
            str(item.get("acceptance_id"))
            for item in direction.get("acceptance") or []
            if isinstance(item, Mapping)
        ),
    }


def _reject_retired_direction_items(
    direction: Mapping[str, Any],
    history: Any,
) -> None:
    history_value = history if isinstance(history, Mapping) else {}
    retired_ids = {
        str(item) for item in history_value.get("retired_ids") or []
    }
    reused_ids = sorted(_direction_item_ids(direction) & retired_ids)
    if reused_ids:
        raise InvalidTransition(
            "direction_item_reused",
            "已退出的方向条目身份不能复活：" + ", ".join(reused_ids),
        )


def _advance_direction_item_history(data: dict[str, Any]) -> None:
    direction = data.get("direction")
    direction = direction if isinstance(direction, Mapping) else {}
    current_ids = _direction_item_ids(direction)
    history = data.get("direction_item_history")
    history = history if isinstance(history, Mapping) else {}
    active_ids = {str(item) for item in history.get("active_ids") or []}
    retired_ids = {str(item) for item in history.get("retired_ids") or []}
    data["direction_item_history"] = {
        "active_ids": sorted(current_ids),
        "retired_ids": sorted(retired_ids | (active_ids - current_ids)),
    }


def _validated_confirmation(
    *,
    action: str,
    data: Mapping[str, Any],
    payload: Mapping[str, Any],
    work_item_id: str,
    work_item_version: int,
) -> dict[str, Any]:
    try:
        challenge = confirmation_challenge_for(
            action_type=action,
            work_item_id=work_item_id,
            work_item_version=work_item_version,
            data=data,
        )
        return confirmation_record_from_input(challenge, payload)
    except ConfirmationProtocolError as error:
        raise InvalidTransition(error.code, str(error)) from error


def _reduce(
    status: str,
    data: dict[str, Any],
    action: str,
    payload: Mapping[str, Any],
    **identity: Any,
) -> tuple[str, dict[str, Any]]:
    """Apply one aggregate transition with a selected repository's Git facts.

    Local Git invariants are shared by every repository count. Only the aggregate
    decides when all preparation or delivery responsibilities have finished.
    """
    projected = repository_view(data, status)
    identifier = projected["selected_repository_id"]
    entries = projected.get("repository_deliveries") or []
    ordered_action = action in {"record_result_commits", "record_local_integration", "record_cleanup", "record_conflict_resolution"} or (action == "claim_external_effect" and payload.get("kind") in {"integrate", "cleanup"})
    if entries and ordered_action and identifier != ordered_repository(data, status):
        raise InvalidTransition("repository_delivery_order_mismatch", "交付动作必须遵循已确认方案中的仓库顺序")
    if "repository_id" in payload and payload["repository_id"] != identifier:
        raise InvalidTransition("repository_action_mismatch", "动作必须绑定当前选定仓库")
    if action in {"record_implementation_started", "record_result_commits", "record_local_integration", "record_cleanup", "record_target_advance", "record_target_advance_assessment", "record_conflict_resolution"} and entries:
        if not any(entry["repository_id"] == identifier for entry in entries):
            raise InvalidTransition("repository_delivery_missing", "当前仓库没有已确认的交付责任")
    next_status, updated = _reduce_selected_repository(status, projected, action, payload, **identity)
    updated = persist_repository_view(updated)
    entries = updated.get("repository_deliveries") or []
    if isinstance(updated.get("pending_effect"), dict):
        if str(updated["pending_effect"].get("kind", "")).startswith("cancel_"):
            updated["pending_effect"].pop("repository_id", None)
        else:
            updated["pending_effect"]["repository_id"] = identifier
    if action in {"record_implementation_started", "confirm_engineering_plan"} and entries and next_status in {"implementing", "implementation_ready"}:
        next_status = "implementing" if all((entry.get("git") or {}).get("work_ref") for entry in entries) else "implementation_ready"
    if action == "confirm_engineering_plan" and (updated.get("engineering", {}).get("plan_confirmation") or {}).get("accepted"):
        plan = updated["engineering"]["plan"]
        replanned = False
        for entry in entries or [{"git": updated.get("git") or {}}]:
            resolution = (entry.get("git") or {}).get("conflict_resolution")
            if isinstance(resolution, dict) and resolution.get("requires_reassessment"):
                resolution.update(requires_reassessment=False, replanned_in_plan_id=plan["plan_id"], retest_command_ids=[command["command_id"] for command in plan.get("verification_commands") or []])
                replanned = True
        if replanned:
            next_status = "implementing" if all((entry.get("git") or {}).get("work_ref") for entry in entries) else "implementation_ready"
    if action == "record_cleanup" and next_status == "completed":
        remaining = [entry for entry in entries if repository_phase(entry) != "completed"]
        if remaining:
            next_status = repository_phase(remaining[0])
    if action in {"request_replan", "revise_direction", "submit_engineering_assessment"}:
        for entry in entries:
            (entry.get("git") or {}).pop("target_advance", None)
    return next_status, updated


def _reduce_selected_repository(
    status: str,
    data: dict[str, Any],
    action: str,
    payload: Mapping[str, Any],
    *,
    work_item_id: str,
    work_item_version: int,
) -> tuple[str, dict[str, Any]]:
    updated = deepcopy(data)
    body = dict(payload)
    if action == "claim_external_effect":
        if isinstance(updated.get("pending_effect"), Mapping):
            raise InvalidTransition(
                "external_effect_in_progress",
                "当前 WorkItem 已有待完成的外部副作用",
            )
        allowed_states = {
            "prepare_work_area": {"implementation_ready"},
            "verification": {"exploring", "implementing", "integration_conflict"},
            "integrate": {"integration_required"},
            "cleanup": {"cleanup_required"},
            "cancel_cleanup": WORK_ITEM_STATES - TERMINAL_STATES,
            "cancel_discard": {"cancelled_changes_pending"},
            "project_authority_confirmation": {"implementing"},
            "authority_adoption": {"commit_required"},
        }
        kind = _enum(body.get("kind"), "kind", set(allowed_states))
        _require_status(status, action, allowed_states[kind])
        intent = _object(body["intent"] if "intent" in body else {}, "intent")
        if kind == "verification":
            approval = _object(intent.get("approved_request"), "intent.approved_request")
            if approval.get("work_item_id") != work_item_id or approval.get("work_item_version") != work_item_version + 1 or not str(intent.get("receipt_id") or ""):
                raise InvalidTransition("invalid_verification_intent", "验证执行意图必须绑定即将占位的事项版本")
            intent = deepcopy(dict(intent))
        elif kind == "prepare_work_area":
            area = _object(intent.get("work_area"), "intent.work_area")
            if area.get("schema_version") != "strixnova.git-work-area.v1" or area.get("work_item_id") != work_item_id:
                raise InvalidTransition("invalid_work_area_intent", "工作区建立意图必须绑定当前事项和精确 Git 工作区")
            intent = {"work_area": deepcopy(area)}
        elif kind == "integrate":
            strategy = _enum(
                intent.get("merge_strategy"),
                "merge_strategy",
                {"no_ff", "ff_only"},
            )
            result_commits = (
                _string_list(
                    intent.get("expected_result_commits"),
                    "intent.expected_result_commits",
                    required=True,
                )
                if "expected_result_commits" in intent
                else []
            )
            expected_target_commit = (
                _text(
                    intent.get("expected_target_commit"),
                    "intent.expected_target_commit",
                )
                if "expected_target_commit" in intent
                else None
            )
            intent = {
                "merge_strategy": strategy,
                **(
                    {"expected_result_commits": result_commits}
                    if result_commits
                    else {}
                ),
                **(
                    {"expected_target_commit": expected_target_commit}
                    if expected_target_commit is not None
                    else {}
                ),
            }
        elif kind == "cleanup":
            if intent:
                raise InvalidTransition(
                    "invalid_payload",
                    "cleanup 外部副作用不接受额外 intent",
                )
        elif kind in {
            "project_authority_confirmation",
            "authority_adoption",
        }:
            if not intent:
                raise InvalidTransition(
                    "invalid_payload",
                    f"{kind} 外部副作用必须绑定精确恢复意图",
                )
        elif kind == "cancel_cleanup":
            if intent.get("has_unmerged_work") is not False:
                raise InvalidTransition(
                    "invalid_payload",
                    "只有没有未合入工作的取消才能自动清理",
                )
            intent = {
                "reason": _text(intent.get("reason"), "intent.reason"),
                "has_unmerged_work": False,
                "git_state": (
                    _object(intent.get("git_state"), "intent.git_state")
                    if intent.get("git_state") is not None
                    else None
                ),
            }
        else:
            if intent.get("decision") != "discard":
                raise InvalidTransition(
                    "invalid_payload",
                    "cancel_discard 只能占位已确认的 discard 决定",
                )
            if intent.get("destructive_confirmed") is not True:
                raise InvalidTransition(
                    "destructive_confirmation_required",
                    "丢弃改动必须有明确破坏性确认",
                )
            details = _object(
                intent["details"] if "details" in intent else {},
                "intent.details",
            )
            intent = {
                "decision": "discard",
                "details": deepcopy(dict(details)),
                "destructive_confirmed": True,
            }
        updated["pending_effect"] = {"kind": kind, "intent": intent}
        return status, updated

    pending_effect = updated.get("pending_effect")
    if isinstance(pending_effect, Mapping):
        effect_kind = _text(pending_effect.get("kind"), "pending_effect.kind")
        allowed_actions = {
            "prepare_work_area": {"record_implementation_started", "release_external_effect"},
            "verification": {"record_verification"},
            "integrate": {
                "record_local_integration",
                "release_external_effect",
            },
            "cleanup": {"record_cleanup"},
            "cancel_cleanup": {
                "cancel_work_item",
                "record_cancel_cleanup_blocked",
                "record_repository_cleanup",
            },
            "cancel_discard": {"resolve_cancelled_work", "record_repository_cleanup"},
            "project_authority_confirmation": {
                "record_project_authority_decision_bundle"
            },
            "authority_adoption": {"record_authority_adoption"},
        }
        if action not in allowed_actions.get(effect_kind, set()):
            raise InvalidTransition(
                "external_effect_in_progress",
                f"必须先完成待处理外部副作用：{effect_kind}",
            )

    if action == "record_repository_cleanup":
        if not isinstance(pending_effect, Mapping) or pending_effect.get("kind") not in {"cancel_cleanup", "cancel_discard"}:
            raise InvalidTransition("external_effect_claim_required", "逐仓库取消清理必须绑定原取消意图")
        cleanup = _object(body.get("cleanup"), "cleanup")
        if cleanup.get("safe") is not True:
            raise InvalidTransition("repository_cleanup_not_safe", "未完成安全清理不能记为已收尾")
        git = deepcopy(updated.get("git") or {})
        git["cleanup"] = cleanup
        updated["git"] = git
        return status, updated

    if action == "release_external_effect":
        if isinstance(pending_effect, Mapping) and pending_effect.get("kind") == "prepare_work_area":
            _require_status(status, action, {"implementation_ready"})
            cleanup = _object(body.get("cleanup"), "cleanup")
            if cleanup.get("safe") is not True or cleanup.get("rolled_back") is not True:
                raise InvalidTransition("external_effect_release_invalid", "工作区建立意图只能在核实空工作已安全回收后释放")
            updated["git"] = {**pending_effect["intent"]["work_area"], "cleanup": cleanup}
            updated["pending_effect"] = None
            return status, updated
        _require_status(status, action, {"integration_required"})
        if (
            not isinstance(pending_effect, Mapping)
            or pending_effect.get("kind") != "integrate"
        ):
            raise InvalidTransition(
                "external_effect_release_invalid",
                "只有尚未发生的本地合入副作用可以安全释放",
            )
        reason = _text(body.get("reason"), "reason")
        if reason not in {
            "target_changed_before_integration",
            "ff_only_not_possible",
            "integration_candidate_changed_before_commit",
        }:
            raise InvalidTransition(
                "external_effect_release_invalid",
                "本地合入占位只能在确定没有形成目标提交时释放",
            )
        updated["pending_effect"] = None
        return status, updated

    if action == "submit_direction":
        _require_status(
            status,
            action,
            {"discussion", "replanning_required"},
        )
        direction, ready, blockers = _direction_submission(
            body,
            work_item_id=work_item_id,
        )
        if ready:
            _reject_retired_direction_items(
                direction,
                updated.get("direction_item_history"),
            )
        updated["direction"] = direction
        updated["direction_confirmation"] = None
        updated["blockers"] = blockers
        return (
            "awaiting_direction_confirmation" if ready else "discussion",
            updated,
        )

    if action == "revise_direction":
        _require_status(
            status,
            action,
            {
                "awaiting_direction_confirmation",
                "needs_engineering_assessment",
                "awaiting_plan_confirmation",
                "implementation_ready",
                "exploring",
                "implementing",
                "awaiting_actual_result",
                "replanning_required",
            },
        )
        invalidation_issues = _string_list(
            body.get("invalidation_issues"),
            "invalidation_issues",
            required=True,
        )
        direction, ready, blockers = _direction_submission(
            body,
            work_item_id=work_item_id,
        )
        if ready:
            _reject_retired_direction_items(
                direction,
                updated.get("direction_item_history"),
            )
        engineering = deepcopy(updated.get("engineering") or {})
        engineering["plan"] = None
        engineering["plan_confirmation"] = None
        updated["engineering"] = engineering
        git = deepcopy(updated.get("git") or {})
        git.pop("target_advance", None)
        updated["git"] = git
        updated["direction"] = direction
        updated["direction_confirmation"] = None
        updated["verifications"] = []
        updated["implementation_slice_completions"] = []
        updated["actual_result"] = None
        updated["actual_result_confirmation"] = None
        updated["authority_adoption"] = None
        updated["blockers"] = blockers
        return (
            "awaiting_direction_confirmation" if ready else "discussion",
            updated,
        )

    if action == "confirm_direction":
        _require_status(status, action, {"awaiting_direction_confirmation"})
        confirmation = _validated_confirmation(
            action=action,
            data=updated,
            payload=body,
            work_item_id=work_item_id,
            work_item_version=work_item_version,
        )
        accepted = bool(confirmation["accepted"])
        updated["direction_confirmation"] = confirmation
        if accepted:
            _advance_direction_item_history(updated)
        updated["blockers"] = []
        return (
            "needs_engineering_assessment" if accepted else "discussion",
            updated,
        )

    if action == "submit_engineering_assessment":
        _require_status(
            status,
            action,
            {"needs_engineering_assessment", "replanning_required"},
        )
        engineering = deepcopy(updated["engineering"])
        engineering["assessment"] = _object(
            body.get("assessment"), "assessment"
        )
        engineering["plan"] = _object(body.get("plan"), "plan")
        repository_scope = engineering["plan"].get("repository_scope")
        if isinstance(repository_scope, Mapping):
            project_id = repository_scope.get("project_id")
            if updated.get("project_id") not in {None, project_id}:
                raise InvalidTransition("work_item_project_mismatch", "方案属于其他项目")
            previous = (updated.get("engineering") or {}).get("plan") or {}
            previous_entries = updated.get("repository_deliveries") or []
            if updated.get("git", {}).get("work_ref") or any((entry.get("git") or {}).get("work_ref") for entry in previous_entries):
                before = [entry.get("repository_id") for entry in previous_entries if not ((entry.get("git") or {}).get("cleanup") or {}).get("safe")] if previous_entries else [entry.get("repository_id") for entry in (previous.get("repository_scope") or {}).get("repositories", []) if entry.get("role") == "modify"]
                after = [entry.get("repository_id") for entry in repository_scope["repositories"] if entry["role"] == "modify"]
                if not set(before).issubset(after):
                    raise InvalidTransition("repository_scope_has_unclosed_execution", "已有执行事实时不能改换仓库交付归属，需先按原事项收口")
            updated["project_id"] = project_id
            deliveries = planned_repository_deliveries(engineering["plan"])
            remaining = {entry["repository_id"] for entry in deliveries}
            for previous_entry in previous_entries:
                if previous_entry["repository_id"] in remaining:
                    continue
                previous_git = previous_entry.get("git") or {}
                if previous_git.get("work_ref") and not (previous_git.get("cleanup") or {}).get("safe"):
                    raise InvalidTransition("repository_scope_has_unclosed_execution", "重新规划不能删除尚未收口仓库的交付责任")
                if previous_git:
                    deliveries.append(deepcopy(previous_entry))
            updated["repository_deliveries"] = deliveries
            for entry in updated["repository_deliveries"]:
                previous_entry = next((value for value in previous_entries if value["repository_id"] == entry["repository_id"]), None)
                if previous_entry is not None and previous_entry.get("git") and (entry["plan_id"] != engineering["plan"]["plan_id"] or not (previous_entry["git"].get("cleanup") or {}).get("safe")):
                    entry["git"] = deepcopy(previous_entry["git"])
            selected_entry = next((entry for entry in deliveries if entry["repository_id"] == updated.get("selected_repository_id")), {})
            updated["git"] = deepcopy(selected_entry.get("git") or {})
        engineering["plan_confirmation"] = None
        updated["engineering"] = engineering
        git = deepcopy(updated.get("git") or {})
        git.pop("target_advance", None)
        updated["git"] = git
        updated["verifications"] = []
        updated["implementation_slice_completions"] = []
        updated["actual_result"] = None
        updated["actual_result_confirmation"] = None
        updated["authority_adoption"] = None
        updated["blockers"] = []
        return "awaiting_plan_confirmation", updated

    if action == "confirm_engineering_plan":
        _require_status(status, action, {"awaiting_plan_confirmation"})
        confirmation = _validated_confirmation(
            action=action,
            data=updated,
            payload=body,
            work_item_id=work_item_id,
            work_item_version=work_item_version,
        )
        accepted = bool(confirmation["accepted"])
        engineering = deepcopy(updated["engineering"])
        engineering["plan_confirmation"] = confirmation
        updated["engineering"] = engineering
        updated["blockers"] = []
        if not accepted:
            return "needs_engineering_assessment", updated
        plan = engineering.get("plan")
        change_context = (
            plan.get("change_context") if isinstance(plan, Mapping) else None
        )
        if (
            isinstance(change_context, Mapping)
            and change_context.get("formal_implementation") is False
        ):
            return "exploring", updated
        git = updated.get("git")
        if isinstance(git, Mapping) and isinstance(
            git.get("conflict_resolution"), Mapping
        ):
            return "integration_conflict", updated
        return (
            "implementing"
            if isinstance(git, Mapping)
            and git.get("schema_version") == "strixnova.git-work-area.v1"
            else "implementation_ready",
            updated,
        )

    if action == "record_implementation_started":
        _require_status(status, action, {"implementation_ready"})
        if isinstance(pending_effect, Mapping):
            if pending_effect.get("kind") != "prepare_work_area" or dict(body.get("git") or {}) != pending_effect.get("intent", {}).get("work_area"):
                raise InvalidTransition("work_area_intent_mismatch", "建立的 Git 工作区与已记录意图不一致")
            updated["pending_effect"] = None
        updated["git"] = _object(body.get("git"), "git")
        updated["blockers"] = []
        return "implementing", updated

    if action == "record_target_advance":
        _require_status(
            status,
            action,
            {"implementation_ready", "commit_required", "integration_required"},
        )
        git = deepcopy(updated.get("git") or {})
        git["target_advance"] = _object(
            body.get("target_advance"),
            "target_advance",
        )
        updated["git"] = git
        updated["blockers"] = []
        return status, updated

    if action == "record_target_advance_assessment":
        _require_status(
            status,
            action,
            {"implementation_ready", "commit_required", "integration_required"},
        )
        git = deepcopy(updated.get("git") or {})
        target_advance = git.get("target_advance")
        if not isinstance(target_advance, Mapping):
            raise InvalidTransition(
                "target_advance_missing",
                "没有待判断的目标分支变化",
            )
        assessment = _object(
            body.get("assessment"),
            "assessment",
        )
        target_advance = deepcopy(target_advance)
        target_advance["assessment"] = assessment
        git["target_advance"] = target_advance
        updated["git"] = git
        updated["blockers"] = []
        return status, updated

    if action == "record_verification":
        _require_status(
            status,
            action,
            {"exploring", "implementing", "integration_conflict"},
        )
        verification = _object(body.get("verification"), "verification")
        if isinstance(pending_effect, Mapping) and pending_effect.get("kind") == "verification":
            intent = pending_effect["intent"]
            if verification.get("receipt_id") != intent["receipt_id"] or verification.get("command_id") != intent["approved_request"]["command"]["command_id"]:
                raise InvalidTransition("verification_intent_mismatch", "验证回执不属于当前执行意图")
            updated["pending_effect"] = None
        verifications = list(updated.get("verifications") or [])
        verifications.append(verification)
        updated["verifications"] = verifications
        if status == "integration_conflict":
            updated["blockers"] = []
        return status, updated

    if action == "record_project_authority_presentation":
        _require_status(status, action, {"implementing"})
        presentation = _object(
            body.get("project_authority_presentation"),
            "project_authority_presentation",
        )
        if (
            presentation.get("schema_version")
            != "strixnova.project-authority-presentation.v1"
            or presentation.get("semantic_content_machine_proven") is not False
        ):
            raise InvalidTransition(
                "project_authority_presentation_invalid",
                "长期权威候选展示记录结构无效",
            )
        authority_kind = _enum(
            presentation.get("authority_kind"),
            "project_authority_presentation.authority_kind",
            {
                "product_definition",
                "domain_model",
                "target_architecture",
                "engineering_policy",
            },
        )
        candidate = _object(
            presentation.get("candidate"),
            "project_authority_presentation.candidate",
        )
        _object(
            presentation.get("confirmation_challenge"),
            "project_authority_presentation.confirmation_challenge",
        )
        _text(
            presentation.get("presented_at"),
            "project_authority_presentation.presented_at",
        )
        presented_version = presentation.get("presented_at_work_item_version")
        if (
            type(presented_version) is not int
            or presented_version != work_item_version + 1
        ):
            raise InvalidTransition(
                "project_authority_presentation_invalid",
                "长期权威候选展示必须绑定写入后的精确事项版本",
            )
        if candidate.get("authority_kind") != authority_kind:
            raise InvalidTransition(
                "project_authority_presentation_invalid",
                "长期权威候选展示种类与候选不一致",
            )
        presentations = list(
            updated.get("project_authority_presentations") or []
        )
        fingerprint = presentation["confirmation_challenge"].get(
            "candidate_fingerprint"
        )
        if any(
            isinstance(value, Mapping)
            and isinstance(value.get("confirmation_challenge"), Mapping)
            and value["confirmation_challenge"].get("candidate_fingerprint")
            == fingerprint
            for value in presentations
        ):
            raise InvalidTransition(
                "project_authority_candidate_already_presented",
                "同一长期权威候选已经在独立事项版本中展示",
            )
        presentations.append(deepcopy(presentation))
        updated["project_authority_presentations"] = presentations
        return status, updated

    if action == "record_project_authority_review":
        _require_status(status, action, {"implementing"})
        review = _object(
            body.get("project_authority_review"),
            "project_authority_review",
        )
        if (
            review.get("schema_version")
            != "strixnova.project-authority-review.v1"
            or review.get("semantic_content_machine_proven") is not False
        ):
            raise InvalidTransition(
                "project_authority_review_invalid",
                "长期权威候选复核记录结构无效",
            )
        _object(review.get("plan_ref"), "project_authority_review.plan_ref")
        bundle = _object(
            review.get("candidate_bundle"),
            "project_authority_review.candidate_bundle",
        )
        semantic_review = _object(
            review.get("semantic_review"),
            "project_authority_review.semantic_review",
        )
        fingerprints = review.get("presentation_fingerprints")
        if (
            not isinstance(fingerprints, list)
            or not fingerprints
            or any(not isinstance(value, str) or not value for value in fingerprints)
            or len(fingerprints) != len(set(fingerprints))
        ):
            raise InvalidTransition(
                "project_authority_review_invalid",
                "长期权威候选复核必须绑定完整且互不重复的展示指纹",
            )
        _text(review.get("reviewed_at"), "project_authority_review.reviewed_at")
        reviewed_version = review.get("reviewed_at_work_item_version")
        if type(reviewed_version) is not int or reviewed_version != work_item_version + 1:
            raise InvalidTransition(
                "project_authority_review_invalid",
                "长期权威候选复核必须绑定写入后的精确事项版本",
            )
        bundle_sha256 = _text(
            bundle.get("content_sha256"),
            "project_authority_review.candidate_bundle.content_sha256",
        )
        current_item = {
            "work_item_id": work_item_id,
            "status": status,
            "version": work_item_version,
            "data": updated,
        }
        stage = project_authority_stage(
            current_item,
            current_progress_only=False,
        )
        stage_presentations = (
            stage.get("presentations") if isinstance(stage, Mapping) else None
        )
        if (
            not isinstance(stage, Mapping)
            or stage.get("stage") != "review"
            or not isinstance(stage_presentations, list)
            or not project_authority_review_matches_plan_structure(
                current_item,
                review,
                stage_presentations,
            )
        ):
            raise InvalidTransition(
                "project_authority_review_invalid",
                "长期权威候选复核没有绑定当前完整展示包和精确工程方案",
            )
        plan = updated.get("engineering", {}).get("plan")
        plan_review = plan.get("semantic_review") if isinstance(plan, Mapping) else None
        budget = (
            plan_review.get("question_budget")
            if isinstance(plan_review, Mapping)
            else None
        )
        decision_refs = {
            "direction",
            *(
                str(value)
                for value in (
                    budget.get("resolved_decision_refs")
                    if isinstance(budget, Mapping)
                    else []
                )
                if str(value).strip()
            ),
        }
        try:
            normalized_review = validate_semantic_review(
                semantic_review,
                known_refs=set(bundle.get("reviewed_refs") or []),
                known_decision_refs=decision_refs,
            )
        except ChangePlanningError as error:
            raise InvalidTransition(
                "project_authority_review_invalid",
                "长期权威候选复核不符合八视角结构或精确引用合同："
                + "；".join(error.issues),
            ) from error
        if dict(normalized_review) != dict(semantic_review):
            raise InvalidTransition(
                "project_authority_review_invalid",
                "长期权威候选复核不是规范化的完整八视角记录",
            )
        reviews = list(updated.get("project_authority_reviews") or [])
        if any(
            isinstance(value, Mapping)
            and isinstance(value.get("candidate_bundle"), Mapping)
            and value["candidate_bundle"].get("content_sha256") == bundle_sha256
            for value in reviews
        ):
            raise InvalidTransition(
                "project_authority_review_already_recorded",
                "同一精确长期权威候选包已经完成八视角复核",
            )
        reviews.append(deepcopy(review))
        updated["project_authority_reviews"] = reviews
        return status, updated

    if action == "record_project_authority_decision_bundle":
        _require_status(status, action, {"implementing"})
        if (
            not isinstance(pending_effect, Mapping)
            or pending_effect.get("kind")
            != "project_authority_confirmation"
        ):
            raise InvalidTransition(
                "project_authority_confirmation_not_claimed",
                "长期权威决定包必须先绑定同一待恢复确认事务",
            )
        pending_intent = _object(
            pending_effect.get("intent"),
            "pending_effect.intent",
        )
        intended_decisions = pending_intent.get("decisions")
        intended_fingerprints = pending_intent.get("candidate_fingerprints")
        if (
            not isinstance(intended_decisions, list)
            or not isinstance(intended_fingerprints, list)
        ):
            raise InvalidTransition(
                "project_authority_confirmation_intent_invalid",
                "长期权威确认意图缺少完整决定顺序或候选指纹",
            )
        raw_records = body.get("project_authority_decisions")
        if not isinstance(raw_records, list) or not raw_records:
            raise InvalidTransition(
                "project_authority_decision_invalid",
                "长期权威负责人决定包必须是非空数组",
            )
        current_item = {
            "work_item_id": work_item_id,
            "status": status,
            "version": work_item_version,
            "data": updated,
        }
        stage = project_authority_stage(
            current_item,
            current_progress_only=False,
        )
        stage_presentations = (
            stage.get("presentations") if isinstance(stage, Mapping) else None
        )
        if (
            not isinstance(stage, Mapping)
            or stage.get("stage") != "confirm"
            or not isinstance(stage_presentations, list)
            or len(stage_presentations) != len(raw_records)
        ):
            raise InvalidTransition(
                "project_authority_confirmation_intent_mismatch",
                "长期权威决定包没有绑定当前已复核的完整候选包",
            )
        presentations_by_kind = {
            str(value.get("authority_kind") or ""): value
            for value in stage_presentations
            if isinstance(value, Mapping)
        }
        decisions = list(updated.get("project_authority_decisions") or [])
        known_fingerprints = {
            str(item["confirmation"].get("candidate_fingerprint") or "")
            for item in decisions
            if isinstance(item, Mapping)
            and isinstance(item.get("confirmation"), Mapping)
        }
        rejected: list[str] = []
        for index, raw_record in enumerate(raw_records):
            record = _object(
                raw_record,
                f"project_authority_decisions[{index}]",
            )
            if (
                record.get("schema_version")
                != "strixnova.project-authority-decision.v1"
                or record.get("semantic_content_machine_proven") is not False
            ):
                raise InvalidTransition(
                    "project_authority_decision_invalid",
                    f"project_authority_decisions[{index}] 结构无效",
                )
            authority_kind = _enum(
                record.get("authority_kind"),
                f"project_authority_decisions[{index}].authority_kind",
                {
                    "product_definition",
                    "domain_model",
                    "target_architecture",
                    "engineering_policy",
                },
            )
            candidate = _object(
                record.get("candidate"),
                f"project_authority_decisions[{index}].candidate",
            )
            confirmation = _object(
                record.get("confirmation"),
                f"project_authority_decisions[{index}].confirmation",
            )
            challenge = _object(
                record.get("confirmation_challenge"),
                f"project_authority_decisions[{index}].confirmation_challenge",
            )
            _text(
                record.get("confirmed_at"),
                f"project_authority_decisions[{index}].confirmed_at",
            )
            accepted = _boolean(
                confirmation.get("accepted"),
                f"project_authority_decisions[{index}].confirmation.accepted",
            )
            if candidate.get("authority_kind") != authority_kind:
                raise InvalidTransition(
                    "project_authority_decision_invalid",
                    "长期权威负责人决定种类与候选不一致",
                )
            presentation = presentations_by_kind.get(authority_kind)
            if (
                not isinstance(presentation, Mapping)
                or presentation.get("candidate") != candidate
                or presentation.get("confirmation_challenge") != challenge
            ):
                raise InvalidTransition(
                    "project_authority_confirmation_intent_mismatch",
                    "长期权威决定没有绑定当前已复核展示中的同一候选和挑战",
                )
            try:
                reproduced_confirmation = reproduce_confirmation_record(challenge, confirmation)
            except ConfirmationProtocolError as error:
                raise InvalidTransition(error.code, str(error)) from error
            if dict(reproduced_confirmation) != dict(confirmation):
                raise InvalidTransition(
                    "project_authority_decision_invalid",
                    "长期权威决定记录与原始回复、Agent 判断及候选绑定不一致",
                )
            if accepted:
                _text(
                    record.get("confirmed_on"),
                    f"project_authority_decisions[{index}].confirmed_on",
                )
                _text(
                    record.get("confirmed_content_sha256"),
                    f"project_authority_decisions[{index}].confirmed_content_sha256",
                )
            elif (
                record.get("confirmed_on") is not None
                or record.get("confirmed_content_sha256") is not None
            ):
                raise InvalidTransition(
                    "project_authority_decision_invalid",
                    "未接受的长期权威候选不得带有机械确认结果",
                )
            fingerprint = str(
                confirmation.get("candidate_fingerprint") or ""
            )
            if challenge.get("candidate_fingerprint") != fingerprint:
                raise InvalidTransition(
                    "project_authority_decision_invalid",
                    "长期权威决定与已展示确认挑战指纹不一致",
                )
            if not fingerprint or fingerprint in known_fingerprints:
                raise InvalidTransition(
                    "project_authority_decision_already_recorded",
                    "同一长期权威候选已经记录负责人决定",
                )
            known_fingerprints.add(fingerprint)
            decisions.append(deepcopy(record))
            if not accepted:
                rejected.append(
                    f"project_authority_candidate_rejected:{authority_kind}:"
                    + str(confirmation.get("summary") or "候选被退回")
                )
        intended_projection = [
            (
                str(value.get("authority_kind") or ""),
                str(value.get("candidate_fingerprint") or ""),
                str(value.get("user_confirmation") or ""),
            )
            if isinstance(value, Mapping)
            else ("", "", "")
            for value in intended_decisions
        ]
        recorded_projection = [
            (
                str(value.get("authority_kind") or ""),
                str(value["confirmation"].get("candidate_fingerprint") or ""),
                str(value["confirmation"].get("user_confirmation") or ""),
            )
            for value in raw_records
            if isinstance(value, Mapping)
            and isinstance(value.get("confirmation"), Mapping)
        ]
        if (
            recorded_projection != intended_projection
            or [value[1] for value in recorded_projection]
            != [str(value or "") for value in intended_fingerprints]
        ):
            raise InvalidTransition(
                "project_authority_confirmation_intent_mismatch",
                "长期权威决定包与已占位的精确确认意图不一致",
            )
        updated["project_authority_decisions"] = decisions
        updated["pending_effect"] = None
        if rejected:
            updated["blockers"] = rejected
            return "replanning_required", updated
        return status, updated

    if action == "complete_implementation_slice":
        _require_status(status, action, {"implementing"})
        completion = _validated_slice_completion(
            body.get("completion"),
            "completion",
        )
        _require_slice_completion_matches_plan(updated, completion)
        slice_id = str(completion["slice_id"])
        completions = list(updated.get("implementation_slice_completions") or [])
        if any(
            isinstance(item, Mapping) and item.get("slice_id") == slice_id
            for item in completions
        ):
            raise InvalidTransition(
                "implementation_slice_already_completed",
                "当前实施切片已经记录完成",
            )
        completions.append(deepcopy(completion))
        updated["implementation_slice_completions"] = completions
        return status, updated

    if action == "assess_verification":
        _require_status(
            status,
            action,
            {"exploring", "implementing", "integration_conflict"},
        )
        receipt_id = _text(body.get("receipt_id"), "receipt_id")
        assessment = _object(
            body.get("code_change_assessment"),
            "code_change_assessment",
        )
        verifications = list(updated.get("verifications") or [])
        matches = [
            index
            for index, receipt in enumerate(verifications)
            if isinstance(receipt, Mapping)
            and receipt.get("receipt_id") == receipt_id
        ]
        if len(matches) != 1:
            raise InvalidTransition(
                "verification_receipt_missing",
                "待判断验证回执不存在或身份不唯一",
            )
        index = matches[0]
        receipt = deepcopy(verifications[index])
        if receipt.get("code_change_assessment") is not None:
            raise InvalidTransition(
                "verification_already_assessed",
                "验证回执已经完成代码变化判断",
            )
        receipt["code_change_assessment"] = assessment
        verifications[index] = receipt
        updated["verifications"] = verifications
        if body.get("implementation_slice_completion") is not None:
            completion = _validated_slice_completion(
                body.get("implementation_slice_completion"),
                "implementation_slice_completion",
            )
            _require_slice_completion_matches_plan(updated, completion)
            completions = list(
                updated.get("implementation_slice_completions") or []
            )
            previous_completion = next((
                item for item in completions
                if isinstance(item, Mapping) and item.get("slice_id") == completion["slice_id"]
            ), None)
            if previous_completion is not None and previous_completion.get("source_receipt_ids") == completion.get("source_receipt_ids"):
                raise InvalidTransition("implementation_slice_already_completed", "当前实施切片已记录同一组验证证据")
            completions = [item for item in completions if item.get("slice_id") != completion["slice_id"]]
            completions.append(completion)
            updated["implementation_slice_completions"] = completions
        if body.get("conflict_candidate_snapshot") is not None:
            git = deepcopy(updated.get("git") or {})
            resolution = git.get("conflict_resolution")
            if status != "integration_conflict" or not isinstance(
                resolution,
                Mapping,
            ):
                raise InvalidTransition(
                    "conflict_candidate_snapshot_not_expected",
                    "只有已记录冲突解决判断后才能绑定复测文件快照",
                )
            required_ids = set(resolution.get("retest_command_ids") or [])
            previous_ids = set(
                resolution.get("receipt_ids_at_decision") or []
            )
            latest = {
                str(value.get("command_id") or ""): value
                for value in verifications
                if isinstance(value, Mapping)
                and value.get("receipt_id") not in previous_ids
                and value.get("command_id") in required_ids
            }
            if not required_ids or any(
                command_id not in latest
                or latest[command_id].get("result") != "passed"
                or not isinstance(
                    latest[command_id].get("code_change_assessment"),
                    Mapping,
                )
                or latest[command_id]["code_change_assessment"].get(
                    "needs_retest"
                )
                is not False
                for command_id in required_ids
            ):
                raise InvalidTransition(
                    "conflict_candidate_snapshot_premature",
                    "冲突解决文件快照必须等全部受影响命令通过并完成事后判断",
                )
            snapshot = _object(
                body.get("conflict_candidate_snapshot"),
                "conflict_candidate_snapshot",
            )
            plan = updated.get("engineering", {}).get("plan")
            if (
                snapshot.get("schema_version")
                != "strixnova.implementation-candidate-snapshot.v1"
                or not isinstance(plan, Mapping)
                or snapshot.get("plan_id") != plan.get("plan_id")
                or snapshot.get("semantic_content_machine_proven") is not False
                or not isinstance(snapshot.get("paths"), list)
                or not isinstance(snapshot.get("changed_paths"), list)
                or not str(snapshot.get("comparison_base_commit") or "")
            ):
                raise InvalidTransition(
                    "conflict_candidate_snapshot_invalid",
                    "冲突解决文件快照没有绑定当前已确认方案",
                )
            resolution = deepcopy(dict(resolution))
            resolution["implementation_candidate_snapshot"] = deepcopy(
                dict(snapshot)
            )
            git["conflict_resolution"] = resolution
            updated["git"] = git
        return status, updated

    if action == "present_actual_result":
        _require_status(
            status,
            action,
            {"exploring", "implementing", "integration_conflict"},
        )
        assessment = updated.get("engineering", {}).get("assessment")
        planned_commands = (
            assessment.get("verification_commands")
            if isinstance(assessment, Mapping)
            else None
        )
        if planned_commands and not list(updated.get("verifications") or []):
            raise InvalidTransition(
                "verification_missing",
                "形成实际结果前必须记录验证或明确 not_run",
            )
        updated["actual_result"] = _object(body.get("actual_result"), "actual_result")
        updated["actual_result_confirmation"] = None
        updated["authority_adoption"] = None
        return "awaiting_actual_result", updated

    if action == "confirm_actual_result":
        _require_status(status, action, {"awaiting_actual_result"})
        confirmation = _validated_confirmation(
            action=action,
            data=updated,
            payload=body,
            work_item_id=work_item_id,
            work_item_version=work_item_version,
        )
        accepted = bool(confirmation["accepted"])
        confirmation["confirmed_at"] = _utc_now()
        updated["actual_result_confirmation"] = confirmation
        updated["blockers"] = []
        if not accepted:
            plan = updated.get("engineering", {}).get("plan")
            change_context = (
                plan.get("change_context") if isinstance(plan, Mapping) else None
            )
            return (
                "exploring"
                if isinstance(change_context, Mapping)
                and change_context.get("formal_implementation") is False
                else "implementing"
            ), updated
        plan = updated.get("engineering", {}).get("plan")
        change_context = (
            plan.get("change_context") if isinstance(plan, Mapping) else None
        )
        if (
            isinstance(change_context, Mapping)
            and change_context.get("formal_implementation") is False
        ):
            return "completed", updated
        git = updated.get("git")
        resolution = (
            git.get("conflict_resolution") if isinstance(git, Mapping) else None
        )
        if isinstance(resolution, Mapping):
            return "integration_conflict", updated
        return "commit_required", updated

    if action == "record_authority_adoption":
        _require_status(status, action, {"commit_required"})
        if (
            not isinstance(pending_effect, Mapping)
            or pending_effect.get("kind") != "authority_adoption"
        ):
            raise InvalidTransition(
                "authority_adoption_not_claimed",
                "实现对齐机械定档必须先绑定已接受实际结果的精确恢复意图",
            )
        adoption_intent = _object(
            pending_effect.get("intent"),
            "pending_effect.intent",
        )
        result_confirmation = updated.get("actual_result_confirmation")
        actual_result = updated.get("actual_result")
        candidate_snapshot = (
            actual_result.get("authority_candidate_snapshot")
            if isinstance(actual_result, Mapping)
            else None
        )
        if (
            not isinstance(result_confirmation, Mapping)
            or result_confirmation.get("accepted") is not True
            or adoption_intent.get(
                "actual_result_confirmation_fingerprint"
            )
            != result_confirmation.get("candidate_fingerprint")
            or adoption_intent.get("candidate_baseline_sha256")
            != (
                candidate_snapshot.get("baseline_content_sha256")
                if isinstance(candidate_snapshot, Mapping)
                else ""
            )
        ):
            raise InvalidTransition(
                "authority_adoption_intent_mismatch",
                "实现对齐机械定档意图与当前已接受实际结果不一致",
            )
        record = _object(
            body.get("authority_adoption"),
            "authority_adoption",
        )
        if record.get("schema_version") != "strixnova.authority-adoption.v1":
            raise InvalidTransition(
                "authority_adoption_invalid",
                "实现对齐机械定档记录结构无效",
            )
        if (
            record.get("required") is not True
            or record.get("authorized_by_actual_result_confirmation") is not True
            or record.get("accepted_candidate_snapshot_verified") is not True
            or record.get("mechanical_adoption_final_state_verified")
            is not True
            or record.get("ready_for_atomic_commits") is not True
            or list(record.get("blocking_issues") or [])
            or list(record.get("authority_updates") or [])
            or record.get("baseline_update") is not None
        ):
            raise InvalidTransition(
                "authority_adoption_invalid",
                "实现对齐机械定档尚未闭合，不能记录为已完成",
            )
        updated["authority_adoption"] = deepcopy(record)
        updated["pending_effect"] = None
        updated["blockers"] = []
        return "commit_required", updated

    if action == "record_result_commits":
        _require_status(status, action, {"commit_required"})
        commits = _string_list(body.get("commits"), "commits", required=True)
        git = deepcopy(updated.get("git") or {})
        snapshot = (updated.get("actual_result") or {}).get("implementation_candidate_snapshot")
        if isinstance(snapshot, Mapping) and snapshot.get("schema_version") == "strixnova.project-implementation-snapshot.v1":
            snapshot = next((entry for entry in snapshot["repositories"] if entry["repository_id"] == updated.get("selected_repository_id")), None)
        if isinstance(snapshot, Mapping):
            git["accepted_content_snapshot"] = deepcopy(snapshot)
        git["result_commits"] = commits
        updated["git"] = git
        return "integration_required", updated

    if action == "record_local_integration":
        _require_status(
            status,
            action,
            {"integration_required", "integration_conflict"},
        )
        outcome = _enum(
            body.get("outcome"),
            "outcome",
            {"integrated", "conflict"},
        )
        git = deepcopy(updated.get("git") or {})
        if status == "integration_required":
            if not isinstance(pending_effect, Mapping) or pending_effect.get(
                "kind"
            ) != "integrate":
                raise InvalidTransition(
                    "external_effect_claim_required",
                    "本地合入前必须先由 Authority 占位",
                )
            updated["pending_effect"] = None
        integration = _object(body.get("integration"), "integration")
        if outcome == "integrated":
            integrated_result_commits = _string_list(
                integration.get("result_commits"),
                "integration.result_commits",
                required=True,
            )
            recorded_result_commits = list(git.get("result_commits") or [])
            if integrated_result_commits != recorded_result_commits:
                raise InvalidTransition(
                    "integration_result_commits_mismatch",
                    "本地合入回执必须绑定当前 WorkItem 已记录的同一组结果提交",
                )
            integrated_commit = _text(
                integration.get("integrated_commit"),
                "integration.integrated_commit",
            )
            actual_result = updated.get("actual_result")
            candidate_snapshot = (
                actual_result.get("authority_candidate_snapshot")
                if isinstance(actual_result, Mapping)
                else None
            )
            if (
                isinstance(candidate_snapshot, Mapping)
                and candidate_snapshot.get("required") is True
            ):
                proof = _object(
                    integration.get(
                        "authority_candidate_snapshot_verification"
                    ),
                    "integration.authority_candidate_snapshot_verification",
                )
                if (
                    proof.get("schema_version")
                    != "strixnova.integrated-authority-snapshot.v1"
                    or proof.get("required") is not True
                    or proof.get("integrated_commit") != integrated_commit
                    or proof.get("accepted_candidate_snapshot_verified")
                    is not True
                    or proof.get("mechanical_adoption_final_state_verified")
                    is not True
                    or list(proof.get("blocking_issues") or [])
                    or proof.get("semantic_content_machine_proven") is not False
                ):
                    raise InvalidTransition(
                        "integrated_authority_snapshot_invalid",
                        "本地合入回执没有证明集成提交仍等于已接受权威快照",
                    )
        git["integration"] = integration
        if outcome == "integrated":
            snapshot = integration.get("implementation_content_snapshot") or (git.get("conflict_resolution") or {}).get("implementation_candidate_snapshot") or git.get("accepted_content_snapshot")
            if isinstance(snapshot, Mapping):
                git["integrated_content_snapshot"] = deepcopy(snapshot)
        if outcome == "conflict":
            git.pop("conflict_resolution", None)
            updated["git"] = git
            updated["blockers"] = _string_list(
                body["blockers"] if "blockers" in body else ["git_conflict"],
                "blockers",
                required=True,
            )
            return "integration_conflict", updated
        if status == "integration_conflict":
            resolution = git.get("conflict_resolution")
            if not isinstance(resolution, Mapping):
                raise InvalidTransition(
                    "conflict_resolution_missing",
                    "Git 冲突必须先由 Agent 记录解决判断",
                )
            required_ids = set(resolution.get("retest_command_ids") or [])
            previous_receipt_ids = set(
                resolution.get("receipt_ids_at_decision") or []
            )
            latest: dict[str, Mapping[str, Any]] = {}
            for receipt in updated.get("verifications") or []:
                if (
                    isinstance(receipt, Mapping)
                    and receipt.get("receipt_id") not in previous_receipt_ids
                    and receipt.get("command_id") in required_ids
                ):
                    latest[str(receipt["command_id"])] = receipt
            incomplete = required_ids - set(latest)
            unassessed = {
                command_id
                for command_id, receipt in latest.items()
                if not isinstance(
                    receipt.get("code_change_assessment"), Mapping
                )
            }
            stale = {
                command_id
                for command_id, receipt in latest.items()
                if isinstance(
                    receipt.get("code_change_assessment"), Mapping
                )
                and receipt["code_change_assessment"].get("needs_retest")
                is True
            }
            if incomplete or unassessed or stale:
                raise InvalidTransition(
                    "conflict_reverification_missing",
                    "Git 冲突解决后必须重跑并事后判断全部受影响验证",
                )
            negative = {
                command_id
                for command_id, receipt in latest.items()
                if receipt.get("result") != "passed"
            }
            if negative:
                confirmation = updated.get("actual_result_confirmation")
                if (
                    not isinstance(confirmation, Mapping)
                    or confirmation.get("accepted") is not True
                    or confirmation.get("confirmed_at")
                    == resolution.get("confirmation_at_decision")
                ):
                    raise InvalidTransition(
                        "conflict_result_reconfirmation_required",
                        "冲突复测存在未通过项，必须重新展示实际限制并由用户确认",
                    )
        updated["git"] = git
        updated["blockers"] = []
        return "cleanup_required", updated

    if action == "record_conflict_resolution":
        _require_status(status, action, {"integration_conflict"})
        visible_changed = _boolean(
            body.get("user_visible_result_changed"),
            "user_visible_result_changed",
        )
        decision_changed = _boolean(
            body.get("confirmed_direction_or_plan_changed"),
            "confirmed_direction_or_plan_changed",
        )
        reason = _text(body.get("reason"), "reason")
        retest_command_ids = _string_list(
            body.get("retest_command_ids"),
            "retest_command_ids",
            required=False,
        )
        git = deepcopy(updated.get("git") or {})
        prior_integration = git.get("integration")
        prior_resolution = git.get("conflict_resolution")
        conflict_entries = (
            list(prior_integration.get("conflict_entries") or [])
            if isinstance(prior_integration, Mapping)
            else list(prior_resolution.get("conflict_entries") or [])
            if isinstance(prior_resolution, Mapping)
            else []
        )
        if not conflict_entries:
            raise InvalidTransition(
                "conflict_entries_missing",
                "Git 冲突判断必须绑定首次原生合入回执中的精确冲突路径",
            )
        existing_confirmation = updated.get("actual_result_confirmation")
        if visible_changed or decision_changed:
            history = list(updated.get("superseded_deliveries") or [])
            history.append({
                "plan_id": (updated.get("engineering", {}).get("plan") or {}).get("plan_id"),
                "actual_result": deepcopy(updated.get("actual_result")),
                "actual_result_confirmation": deepcopy(existing_confirmation),
                "authority_adoption": deepcopy(updated.get("authority_adoption")),
                "repository_deliveries": deepcopy(updated.get("repository_deliveries") or []),
                "superseded_by_replan_reasons": [reason],
            })
            updated["superseded_deliveries"] = history
        git["conflict_resolution"] = {
            "user_visible_result_changed": visible_changed,
            "confirmed_direction_or_plan_changed": decision_changed,
            "reason": reason,
            "retest_command_ids": retest_command_ids,
            "receipt_ids_at_decision": [
                str(receipt.get("receipt_id"))
                for receipt in updated.get("verifications") or []
                if isinstance(receipt, Mapping)
                and str(receipt.get("receipt_id") or "").strip()
            ],
            "confirmation_at_decision": (
                existing_confirmation.get("confirmed_at")
                if isinstance(existing_confirmation, Mapping)
                else None
            ),
            "conflict_entries": conflict_entries,
            "requires_reassessment": decision_changed,
        }
        candidate_snapshot = body.get("implementation_candidate_snapshot")
        if not retest_command_ids:
            snapshot = _object(
                candidate_snapshot,
                "implementation_candidate_snapshot",
            )
            plan = updated.get("engineering", {}).get("plan")
            if (
                snapshot.get("schema_version")
                != "strixnova.implementation-candidate-snapshot.v1"
                or not isinstance(plan, Mapping)
                or snapshot.get("plan_id") != plan.get("plan_id")
                or snapshot.get("semantic_content_machine_proven") is not False
                or not isinstance(snapshot.get("paths"), list)
                or not isinstance(snapshot.get("changed_paths"), list)
                or not str(snapshot.get("comparison_base_commit") or "")
            ):
                raise InvalidTransition(
                    "conflict_candidate_snapshot_invalid",
                    "零验证命令的冲突解决没有绑定当前已确认方案的精确文件快照",
                )
            git["conflict_resolution"]["implementation_candidate_snapshot"] = (
                deepcopy(dict(snapshot))
            )
        elif candidate_snapshot is not None:
            raise InvalidTransition(
                "conflict_candidate_snapshot_premature",
                "存在受影响验证命令时，必须等复测通过后再形成冲突文件快照",
            )
        git.pop("integration", None)
        updated["git"] = git
        updated["blockers"] = []
        if decision_changed:
            engineering = deepcopy(updated["engineering"])
            engineering["plan"] = None
            engineering["plan_confirmation"] = None
            updated["engineering"] = engineering
            updated["verifications"] = []
            updated["implementation_slice_completions"] = []
            updated["actual_result"] = None
            updated["actual_result_confirmation"] = None
            updated["authority_adoption"] = None
            updated["blockers"] = [reason]
            return "replanning_required", updated
        if visible_changed:
            updated["actual_result"] = None
            updated["actual_result_confirmation"] = None
            updated["authority_adoption"] = None
            return "integration_conflict", updated
        updated["blockers"] = ["verification_after_conflict_required"]
        return "integration_conflict", updated

    if action == "record_cleanup":
        _require_status(status, action, {"cleanup_required"})
        if not isinstance(pending_effect, Mapping) or pending_effect.get(
            "kind"
        ) != "cleanup":
            raise InvalidTransition(
                "external_effect_claim_required",
                "清理 Git 工作区前必须先由 Authority 占位",
            )
        cleanup = _object(body.get("cleanup"), "cleanup")
        if cleanup.get("safe") is not True:
            updated["blockers"] = list(
                cleanup.get("blockers") or ["cleanup_not_safe"]
            )
            return "cleanup_required", updated
        git = deepcopy(updated.get("git") or {})
        git["cleanup"] = cleanup
        updated["git"] = git
        updated["pending_effect"] = None
        updated["blockers"] = []
        return "completed", updated

    if action == "request_replan":
        _require_status(
            status,
            action,
            {
                "implementation_ready",
                "exploring",
                "implementing",
                "commit_required",
                "integration_required",
                "integration_conflict",
            },
        )
        engineering = deepcopy(updated.get("engineering") or {})
        if status in {"commit_required", "integration_required", "integration_conflict"}:
            history = list(updated.get("superseded_deliveries") or [])
            history.append(
                {
                    "plan_id": (
                        engineering.get("plan", {}).get("plan_id")
                        if isinstance(engineering.get("plan"), Mapping)
                        else None
                    ),
                    "actual_result": deepcopy(updated.get("actual_result")),
                    "actual_result_confirmation": deepcopy(
                        updated.get("actual_result_confirmation")
                    ),
                    "authority_adoption": deepcopy(
                        updated.get("authority_adoption")
                    ),
                    "result_commits": list(
                        (updated.get("git") or {}).get("result_commits") or []
                    ),
                    "repository_deliveries": deepcopy(updated.get("repository_deliveries") or []),
                    "superseded_by_replan_reasons": _string_list(
                        body.get("reasons"),
                        "reasons",
                        required=True,
                    ),
                }
            )
            updated["superseded_deliveries"] = history
        engineering["plan"] = None
        engineering["plan_confirmation"] = None
        updated["engineering"] = engineering
        updated["verifications"] = []
        updated["implementation_slice_completions"] = []
        updated["actual_result"] = None
        updated["actual_result_confirmation"] = None
        updated["authority_adoption"] = None
        for entry in updated.get("repository_deliveries") or []:
            resolution = (entry.get("git") or {}).get("conflict_resolution")
            if isinstance(resolution, dict) and not ((entry.get("git") or {}).get("integration") or {}).get("integrated_commit"):
                resolution["requires_reassessment"] = True
        if isinstance((updated.get("git") or {}).get("conflict_resolution"), dict):
            updated["git"]["conflict_resolution"]["requires_reassessment"] = True
        updated["blockers"] = _string_list(
            body.get("reasons"),
            "reasons",
            required=True,
        )
        return "replanning_required", updated

    if action == "cancel_work_item":
        if status in TERMINAL_STATES:
            raise InvalidTransition(
                "invalid_transition",
                f"终态 {status} 不能取消",
            )
        if isinstance(pending_effect, Mapping):
            intent = _object(pending_effect.get("intent"), "pending_effect.intent")
            if pending_effect.get("kind") != "cancel_cleanup":
                raise InvalidTransition(
                    "external_effect_in_progress",
                    "当前外部副作用不是取消清理",
                )
            if body.get("cleanup") is None:
                raise InvalidTransition(
                    "invalid_payload",
                    "取消清理完成时必须记录 cleanup",
                )
            reason = _text(intent.get("reason"), "intent.reason")
            has_unmerged_work = False
            git_state = intent.get("git_state")
            updated["pending_effect"] = None
        else:
            if body.get("cleanup") is not None:
                raise InvalidTransition(
                    "external_effect_claim_required",
                    "取消中的 Git 清理必须先由 Authority 占位",
                )
            reason = _text(body.get("reason"), "reason")
            has_unmerged_work = _boolean(
                body.get("has_unmerged_work"),
                "has_unmerged_work",
            )
            git_state = body.get("git_state")
        updated["cancellation"] = {
            "reason": reason,
            "has_unmerged_work": has_unmerged_work,
            "git_state": (
                _object(git_state, "git_state")
                if git_state is not None
                else None
            ),
        }
        if body.get("cleanup") is not None and "repositories" not in body["cleanup"]:
            git = deepcopy(updated.get("git") or {})
            git["cleanup"] = _object(body.get("cleanup"), "cleanup")
            updated["git"] = git
        return (
            "cancelled_changes_pending" if has_unmerged_work else "cancelled",
            updated,
        )

    if action == "record_cancel_cleanup_blocked":
        if not isinstance(pending_effect, Mapping) or pending_effect.get(
            "kind"
        ) != "cancel_cleanup":
            raise InvalidTransition(
                "external_effect_claim_required",
                "当前没有待完成的取消清理",
            )
        intent = _object(pending_effect.get("intent"), "pending_effect.intent")
        git_state = _object(body.get("git_state"), "git_state")
        if git_state.get("requires_user_decision") is not True:
            raise InvalidTransition(
                "invalid_payload",
                "只有 Git 已出现待处置工作时才能停止自动清理",
            )
        updated["cancellation"] = {
            "reason": _text(intent.get("reason"), "intent.reason"),
            "has_unmerged_work": True,
            "git_state": git_state,
        }
        updated["pending_effect"] = None
        updated["blockers"] = ["cancelled_work_requires_user_decision"]
        return "cancelled_changes_pending", updated

    if action == "resolve_cancelled_work":
        _require_status(status, action, {"cancelled_changes_pending"})
        if isinstance(pending_effect, Mapping):
            if pending_effect.get("kind") != "cancel_discard":
                raise InvalidTransition(
                    "external_effect_in_progress",
                    "当前外部副作用不是取消丢弃",
                )
            intent = _object(pending_effect.get("intent"), "pending_effect.intent")
            decision = "discard"
            details = deepcopy(
                _object(
                    intent["details"] if "details" in intent else {},
                    "pending_effect.intent.details",
                )
            )
            destructive_confirmed = True
            updated["pending_effect"] = None
        else:
            decision = _enum(
                body.get("decision"),
                "decision",
                {"preserve", "transfer", "discard"},
            )
            details = _object(
                body["details"] if "details" in body else {},
                "details",
            )
            destructive_confirmed = (
                _boolean(
                    body.get("destructive_confirmed"),
                    "destructive_confirmed",
                )
                if "destructive_confirmed" in body
                else False
            )
        if decision == "discard" and not destructive_confirmed:
            raise InvalidTransition(
                "destructive_confirmation_required",
                "丢弃改动必须有明确破坏性确认",
            )
        if decision == "discard" and not isinstance(pending_effect, Mapping):
            raise InvalidTransition(
                "external_effect_claim_required",
                "破坏性丢弃前必须先由 Authority 占位",
            )
        cancellation = deepcopy(updated.get("cancellation") or {})
        cancellation["resolution"] = {
            "decision": decision,
            "details": deepcopy(dict(details)),
        }
        updated["cancellation"] = cancellation
        updated["blockers"] = []
        return "cancelled", updated

    raise InvalidTransition("unknown_action", f"未知 Authority 动作：{action}")


def _recorded_history_facts(
    current: Mapping[str, Any], data: Mapping[str, Any], action: str, status: str, version: int,
) -> dict[str, Any] | None:
    """Capture this transition's normalized facts once, never during a query."""

    slots = {
        "direction": ("direction", "direction_confirmation", "confirm_direction"),
        "engineering_plan": ("plan", "plan_confirmation", "confirm_engineering_plan"),
        "actual_result": ("actual_result", "actual_result_confirmation", "confirm_actual_result"),
    }
    presentations = {"submit_direction": "direction", "revise_direction": "direction", "submit_engineering_assessment": "engineering_plan", "present_actual_result": "actual_result"}
    decisions = {definition[2]: kind for kind, definition in slots.items()}

    def container(value: Mapping[str, Any], kind: str) -> Mapping[str, Any]:
        return value.get("engineering") or {} if kind == "engineering_plan" else value

    facts: dict[str, Any] = {"schema_version": "strixnova.recorded-history-facts.v1"}
    kind = presentations.get(action)
    if kind is not None:
        slot, _confirmation, confirm_action = slots[kind]
        value = container(data, kind).get(slot)
        if isinstance(value, Mapping):
            challenge = confirmation_challenge_for(action_type=confirm_action, work_item_id=str(current["work_item_id"]), work_item_version=version, data=data)
            facts["candidate"] = {"kind": kind, "value": deepcopy(value), "fingerprint": challenge["candidate_fingerprint"], "state_at_recording": status}
    kind = decisions.get(action)
    if kind is not None:
        slot, confirmation_slot, _confirm_action = slots[kind]
        decision = container(data, kind).get(confirmation_slot)
        facts["decision"] = {"kind": kind, **deepcopy(dict(decision or {}))}
    invalidated = [
        kind for kind, (slot, _confirmation, _action) in slots.items()
        if container(current["data"], kind).get(slot) is not None and container(data, kind).get(slot) is None
    ]
    if action == "request_replan":
        invalidated = sorted(set(invalidated) | {"engineering_plan", "actual_result"})
    if action == "cancel_work_item":
        invalidated = list(slots)
    if invalidated:
        facts["invalidated_kinds"] = invalidated
    return facts if len(facts) > 1 else None


class WorkflowAuthority:
    """Deep module for local WorkItem state and history."""

    def __init__(self, project_dir: str | Path, *, project_id: str | None = None) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self.expected_project_id = project_id
        if project_id is not None and re.fullmatch(r"PROJECT-[0-9A-F]{16}", project_id) is None:
            raise WorkflowAuthorityError("project_identity_invalid", "事项库项目身份无效")
        if not self.project.is_dir():
            raise WorkflowAuthorityError(
                "project_missing",
                f"项目目录不存在：{self.project}",
            )
        self.strixnova_root = self.project / ".strixnova"
        self.database_path = self.strixnova_root / AUTHORITY_DATABASE_NAME

    def initialize(self) -> None:
        ProjectMaintenance(self.project).assert_available()
        if self.database_path.exists():
            self._ensure_layout(create=False)
            if self.database_path.is_symlink() or not self.database_path.is_file():
                raise WorkflowAuthorityError(
                    "unsafe_authority_path",
                    "Authority 数据库必须是 .strixnova 内的普通文件",
                )
            # A pre-existing database is inspected read-only before Strixnova
            # creates or updates any local support file. Development builds
            # support exactly one current format and never migrate old state.
            with self._read_connection():
                pass
            self._ensure_layout()
            return
        # Reject unrelated pre-existing material before creating support files.
        self._ensure_layout(create=False)
        try:
            with ProjectMaintenance(self.project).authority_initialization():
                if self.database_path.exists():
                    # Another creator may have completed while this caller waited.
                    self.initialize()
                    return
                self._ensure_layout()
                with self._transaction() as connection:
                    self._ensure_schema(connection)
        except MaintenanceError as error:
            if error.code == "unsupported_authority_format":
                raise WorkflowAuthorityError(error.code, str(error)) from error
            raise

    def create(self, *, title: str, raw_request: str) -> dict[str, Any]:
        clean_title = _text(title, "title")
        clean_request = _text(raw_request, "raw_request")
        now = _utc_now()
        data = _initial_data(clean_request, self.expected_project_id)
        # Inspect any pre-existing Authority store through the read-only
        # format gate before opening a writable SQLite connection. A
        # development checkout supports exactly one format; an older or
        # otherwise unsupported database must remain untouched.
        self.initialize()
        with self._transaction() as connection:
            for _attempt in range(32):
                work_item_id = (
                    f"WI-{now[:10].replace('-', '')}-"
                    f"{secrets.token_hex(4).upper()}"
                )
                try:
                    connection.execute(
                        """
                        INSERT INTO work_items(
                            work_item_id, title, status, version,
                            data_json, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            work_item_id,
                            clean_title,
                            "discussion",
                            1,
                            _json(data),
                            now,
                            now,
                        ),
                    )
                    connection.execute(
                        """
                        INSERT INTO events(
                            work_item_id, version, event_type,
                            payload_json, recorded_at
                        ) VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            work_item_id,
                            1,
                            "work_item_created",
                            _json(
                                {
                                    "title": clean_title,
                                    "raw_request": clean_request,
                                }
                            ),
                            now,
                        ),
                    )
                    row = connection.execute(
                        "SELECT * FROM work_items WHERE work_item_id = ?",
                        (work_item_id,),
                    ).fetchone()
                    return self._row_to_work_item(row)
                except sqlite3.IntegrityError:
                    continue
        raise WorkflowAuthorityError(
            "work_item_id_exhausted",
            "无法生成唯一 WorkItem ID",
        )

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS work_items (
                work_item_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                version INTEGER NOT NULL,
                data_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS events (
                sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                work_item_id TEXT NOT NULL,
                version INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                recorded_at TEXT NOT NULL,
                UNIQUE (work_item_id, version),
                FOREIGN KEY (work_item_id)
                    REFERENCES work_items(work_item_id)
                    ON DELETE RESTRICT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS events_by_work_item
                ON events(work_item_id, sequence)
            """,
        )
        for statement in statements:
            connection.execute(statement)
        ensure_evidence_schema(connection)
        install_write_guards(connection)
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        if row is None:
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("schema_version", AUTHORITY_SCHEMA_VERSION),
            )
        elif str(row[0]) != AUTHORITY_SCHEMA_VERSION:
            raise WorkflowAuthorityError(
                "unsupported_authority_format",
                "Authority 格式不受支持，请归档后重新初始化",
            )

    def transition(
        self,
        work_item_id: str,
        action: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        self.initialize()
        identifier = _text(work_item_id, "work_item_id")
        action_name = _text(action, "action")
        if not isinstance(payload, Mapping):
            raise InvalidTransition("invalid_payload", "payload 必须是对象")
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_item_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise WorkItemNotFound(
                    "work_item_not_found",
                    f"WorkItem 不存在：{identifier}",
                )
            current = self._row_to_work_item(row)
            payload = dict(payload)
            repository_actions = {"record_implementation_started", "record_target_advance", "record_target_advance_assessment", "record_result_commits", "record_local_integration", "record_conflict_resolution", "record_cleanup", "record_repository_cleanup"}
            if action_name in repository_actions or (action_name == "claim_external_effect" and payload.get("kind") in {"prepare_work_area", "integrate", "cleanup", "verification"}):
                payload.setdefault("repository_id", selected_repository(current["data"], current["status"]))
            if (
                not isinstance(expected_version, int)
                or isinstance(expected_version, bool)
                or expected_version < 1
            ):
                raise AuthorityConflict(
                    "expected_version_required",
                    "写入 WorkItem 必须携带刚读取的整数 version",
                )
            if expected_version != current["version"]:
                raise AuthorityConflict(
                    "authority_conflict",
                    (
                        f"WorkItem 已从 version {expected_version} "
                        f"前进到 {current['version']}，请重新读取"
                    ),
                )
            next_status, next_data = _reduce(
                current["status"],
                current["data"],
                action_name,
                payload,
                work_item_id=identifier,
                work_item_version=current["version"],
            )
            if (
                action_name in {"submit_direction", "revise_direction"}
                and next_status == "awaiting_direction_confirmation"
            ):
                direction = next_data.get("direction")
                direction = direction if isinstance(direction, Mapping) else {}
                relations = direction.get("work_item_relations") or []
                for target_id in relation_target_ids(relations):
                    target_exists = connection.execute(
                        "SELECT 1 FROM work_items WHERE work_item_id = ?",
                        (target_id,),
                    ).fetchone()
                    if target_exists is None:
                        raise InvalidTransition(
                            "work_item_relation_target_not_found",
                            f"关系目标 WorkItem 不存在：{target_id}",
                        )
            if action_name in {"submit_direction", "revise_direction", "confirm_direction", "present_actual_result", "confirm_actual_result"}:
                refs = declared_refs(next_data.get("direction") or {})
                result = next_data.get("actual_result") or {}
                if refs or result.get("follow_up_items") or result.get("follow_up_results"):
                    try:
                        state = self._follow_up_state(connection)
                        if (
                            action_name in {"submit_direction", "revise_direction"} and next_status == "awaiting_direction_confirmation"
                        ) or (
                            action_name == "confirm_direction" and (next_data.get("direction_confirmation") or {}).get("accepted") is True
                        ):
                            for ref in refs:
                                if ref_key(ref) not in state or state[ref_key(ref)]["state"] != "open":
                                    raise FollowUpError("follow_up_not_open", "跟进引用必须指向已接受且仍待处理的原问题")
                        if action_name == "present_actual_result" or (
                            action_name == "confirm_actual_result" and (next_data.get("actual_result_confirmation") or {}).get("accepted") is True
                        ):
                            check_current_results(result, state, identifier)
                    except FollowUpError as error:
                        raise InvalidTransition(error.code, str(error)) from error
            if next_status not in WORK_ITEM_STATES:
                raise WorkflowAuthorityError(
                    "invalid_reducer_state",
                    f"Reducer 产生未知状态：{next_status}",
                )
            next_version = current["version"] + 1
            if action_name == "confirm_direction":
                confirmation = next_data.get("direction_confirmation")
                if isinstance(confirmation, Mapping):
                    confirmation = deepcopy(dict(confirmation))
                    confirmation["direction_version"] = next_version
                    next_data["direction_confirmation"] = confirmation
            now = _utc_now()
            updated = connection.execute(
                """
                UPDATE work_items
                SET status = ?, version = ?, data_json = ?, updated_at = ?
                WHERE work_item_id = ? AND version = ?
                """,
                (
                    next_status,
                    next_version,
                    _json(next_data),
                    now,
                    identifier,
                    current["version"],
                ),
            )
            if updated.rowcount != 1:
                raise AuthorityConflict(
                    "authority_conflict",
                    "WorkItem 在写入期间发生变化，请重新读取",
                )
            connection.execute(
                """
                INSERT INTO events(
                    work_item_id, version, event_type,
                    payload_json, recorded_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    next_version,
                    action_name,
                    _json(dict(payload)),
                    now,
                ),
            )
            facts = _recorded_history_facts(current, next_data, action_name, next_status, next_version)
            if facts is not None:
                sequence = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
                if facts.get("decision") and not connection.execute(
                    "SELECT 1 FROM event_annotations WHERE work_item_id=? AND json_extract(record_json,'$.candidate.fingerprint')=? LIMIT 1",
                    (identifier, facts["decision"].get("candidate_fingerprint")),
                ).fetchone():
                    raise WorkflowAuthorityError("confirmation_candidate_missing", "确认缺少对应的已记录精确候选，不能补造历史依据")
                connection.execute("INSERT INTO event_annotations(event_sequence,work_item_id,record_json) VALUES (?,?,?)", (sequence, identifier, _json(facts)))
            if action_name == "record_verification" and "output_evidence" in payload:
                evidence = payload["output_evidence"]
                expected_streams = {"stdout", "stderr"}
                if isinstance(payload.get("verification", {}).get("case_evidence"), Mapping):
                    expected_streams.add("cases")
                if not isinstance(evidence, list) or len(evidence) != len(expected_streams) or {value.get("stream") for value in evidence if isinstance(value, Mapping)} != expected_streams:
                    raise WorkflowAuthorityError("verification_evidence_invalid", "验证必须记录对应的输出与逐用例报告来源")
                for value in evidence:
                    if value.get("work_item_id") != identifier or value.get("receipt_id") != payload["verification"].get("receipt_id"):
                        raise WorkflowAuthorityError("verification_evidence_invalid", "输出来源必须属于当前事项及回执")
                    insert_evidence(connection, value)
            row = connection.execute(
                "SELECT * FROM work_items WHERE work_item_id = ?",
                (identifier,),
            ).fetchone()
            result = self._row_to_work_item(row)
            result["data"] = repository_view(result["data"], result["status"])
            return result

    def get(self, work_item_id: str) -> dict[str, Any]:
        item = self.historical_item(work_item_id, history_read=False)
        item["data"] = repository_view(item["data"], item["status"])
        item["current_action"] = current_action_for(item)
        return item

    @staticmethod
    def _follow_up_state(connection: sqlite3.Connection) -> dict:
        rows = connection.execute("""
            SELECT e.sequence,e.work_item_id,e.version,a.record_json
            FROM events e JOIN event_annotations a ON a.event_sequence=e.sequence
            WHERE json_extract(a.record_json,'$.candidate.kind')='actual_result'
               OR json_extract(a.record_json,'$.decision.kind')='actual_result'
            ORDER BY e.sequence
        """)
        return project_records({"sequence": row[0], "work_item_id": row[1], "version": row[2], "facts": json.loads(row[3])} for row in rows)

    def follow_up_snapshot(self) -> dict[str, Any]:
        """Read explicit accepted obligations in one SQLite snapshot, without adoption."""
        if not self._read_ready():
            return {"revision": 0, "items": [], "assignments": []}
        try:
            with self._read_connection(history_read=True) as connection:
                state = self._follow_up_state(connection)
                revision = int(connection.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()[0])
                assignments = []
                for row in connection.execute("SELECT work_item_id,title,status,data_json FROM work_items"):
                    data = json.loads(row[3])
                    if (data.get("direction_confirmation") or {}).get("accepted") is not True:
                        continue
                    for ref in declared_refs(data.get("direction") or {}):
                        assignments.append({"follow_up_ref": ref, "work_item_id": row[0], "title": row[1], "status": row[2]})
                return {"revision": revision, "items": list(state.values()), "assignments": assignments}
        except FollowUpError as error:
            raise WorkflowAuthorityError(error.code, str(error)) from error
        except (sqlite3.Error, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
            raise WorkflowAuthorityError("follow_up_history_invalid", "跟进历史记录不完整，不能推断问题已经解决") from error

    def historical_item(self, work_item_id: str, *, history_read: bool = True, include_data: bool = True, fields: tuple[str, ...] | None = None) -> dict[str, Any]:
        """Read stored facts without interpreting today's workflow or project."""

        identifier = _text(work_item_id, "work_item_id")
        if not self._read_ready():
            raise AuthorityNotInitialized(
                "authority_not_initialized",
                "项目尚未 intake，WorkflowAuthority 不存在",
            )
        try:
            with self._read_connection(history_read=history_read) as connection:
                expression = "data_json" if include_data else "'{}'"
                if fields is not None:
                    allowed = {"raw_request", "direction", "direction_confirmation", "engineering", "git", "repository_deliveries", "project_id", "actual_result", "actual_result_confirmation", "superseded_deliveries", "cancellation", "project_authority_decisions", "authority_adoption"}
                    if any(field not in allowed for field in fields):
                        raise WorkflowAuthorityError("history_record_invalid", "历史读取包含未知数据字段")
                    expression = "json_object(" + ",".join(f"'{field}',json_extract(data_json,'$.{field}')" for field in fields) + ")"
                if history_read:
                    size = connection.execute(f"SELECT length(CAST({expression} AS BLOB)) FROM work_items WHERE work_item_id=?", (identifier,)).fetchone()
                    if size and int(size[0]) > 16 * 1024 * 1024:
                        raise WorkflowAuthorityError("history_record_too_large", "请求的历史正文超过 16 MiB；请缩小记录范围")
                columns = f"work_item_id,title,status,version,created_at,updated_at,{expression} AS data_json"
                row = connection.execute(
                    f"SELECT {columns} FROM work_items WHERE work_item_id = ?",
                    (identifier,),
                ).fetchone()
        except sqlite3.Error as error:
            raise WorkflowAuthorityError("history_data_invalid", "事项存储不能按声明结构读取") from error
        if row is None:
            raise WorkItemNotFound(
                "work_item_not_found",
                f"WorkItem 不存在：{identifier}",
            )
        try:
            item = self._row_to_work_item(row)
            if not isinstance(item["data"], dict):
                raise ValueError
            return item
        except (ValueError, TypeError, KeyError) as error:
            raise WorkflowAuthorityError("history_data_invalid", "事项当前正文损坏；可单独读取仍完整的原始事件") from error

    def list(self) -> list[dict[str, Any]]:
        if not self._read_ready():
            return []
        with self._read_connection() as connection:
            rows = connection.execute(
                """
                SELECT * FROM work_items
                ORDER BY updated_at DESC, work_item_id ASC
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = self._row_to_work_item(row)
            item["data"] = repository_view(item["data"], item["status"])
            item["current_action"] = current_action_for(item)
            result.append(item)
        return result

    def historical_items(
        self, *, limit: int, query: str = "", statuses: tuple[str, ...] = (),
        since: str | None = None, until: str | None = None,
        after: tuple[str, str] | None = None, expected_revision: int | None = None,
    ) -> dict[str, Any]:
        """Page stored summaries in SQL, without loading complete item payloads."""

        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkflowAuthorityError("history_limit_invalid", "历史页大小必须为 1 到 100")
        if not self._read_ready():
            if expected_revision not in {None, 0}:
                raise WorkflowAuthorityError("history_snapshot_changed", "历史来源已变化，请重新查询")
            return {"revision": 0, "items": [], "more": False, "last_key": None}
        predicates: list[str] = []
        parameters: list[Any] = []
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            predicates.append("title LIKE ? ESCAPE '\\'")
            parameters.append(f"%{escaped}%")
        if statuses:
            predicates.append("status IN (" + ",".join("?" for _ in statuses) + ")")
            parameters.extend(statuses)
        time_key = "strixnova_history_time(updated_at)"
        for operator, value in ((">=", since), ("<", until)):
            if value is not None:
                predicates.append(f"{time_key} {operator} strixnova_history_time(?)")
                parameters.append(value)
        if after is not None:
            predicates.append(f"({time_key} < strixnova_history_time(?) OR ({time_key} = strixnova_history_time(?) AND work_item_id > ?))")
            parameters.extend((after[0], after[0], after[1]))
        where = " WHERE " + " AND ".join(predicates) if predicates else ""
        try:
            with self._read_connection(history_read=True) as connection:
                connection.create_function("strixnova_history_time", 1, _history_time_key, deterministic=True)
                revision = int(connection.execute("SELECT COALESCE(MAX(sequence),0) FROM events").fetchone()[0])
                if expected_revision is not None and expected_revision != revision:
                    raise WorkflowAuthorityError("history_snapshot_changed", "历史来源已变化，请重新查询")
                rows = connection.execute(
                    "SELECT work_item_id,title,status,version,created_at,updated_at,"
                    "CASE WHEN json_valid(data_json) THEN json_extract(data_json,'$.actual_result_confirmation.accepted') END AS result_accepted,"
                    "CASE WHEN json_valid(data_json) THEN 'valid_json' ELSE 'invalid_json' END AS data_integrity "
                    "FROM work_items" + where + f" ORDER BY {time_key} DESC,work_item_id ASC LIMIT ?",
                    (*parameters, limit + 1),
                ).fetchall()
        except sqlite3.Error as error:
            raise WorkflowAuthorityError("history_data_invalid", "历史存储无法按声明格式读取") from error
        items = [dict(row) for row in rows[:limit]]
        return {
            "revision": revision, "items": items, "more": len(rows) > limit,
            "last_key": [items[-1]["updated_at"], items[-1]["work_item_id"]] if items else None,
        }

    def historical_events(
        self, work_item_id: str, *, expected_version: int,
        after_sequence: int = 0, limit: int = 25, sequence: int | None = None,
    ) -> dict[str, Any]:
        """Read one event or bounded event headers from a pinned item version."""

        identifier = _text(work_item_id, "work_item_id")
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkflowAuthorityError("history_limit_invalid", "历史页大小必须为 1 到 100")
        if not self._read_ready():
            raise AuthorityNotInitialized("authority_not_initialized", "没有事项历史数据库")
        try:
            with self._read_connection(history_read=True) as connection:
                item = connection.execute("SELECT version FROM work_items WHERE work_item_id=?", (identifier,)).fetchone()
                if item is None:
                    raise WorkItemNotFound("work_item_not_found", f"WorkItem 不存在：{identifier}")
                if int(item[0]) != expected_version:
                    raise AuthorityConflict("history_snapshot_changed", "事项在读取期间发生变化，请重新查询")
                if sequence is not None:
                    header = connection.execute(
                        "SELECT length(CAST(payload_json AS BLOB)) FROM events WHERE work_item_id=? AND sequence=?",
                        (identifier, sequence),
                    ).fetchone()
                    if header is None:
                        raise WorkItemNotFound("history_event_missing", "该事件不属于所查询事项或已不存在")
                    if int(header[0]) > 16 * 1024 * 1024:
                        raise WorkflowAuthorityError("history_record_too_large", "事件正文超过 16 MiB 读取上限")
                    event = connection.execute(
                        "SELECT sequence,version,event_type,payload_json,recorded_at FROM events WHERE work_item_id=? AND sequence=?",
                        (identifier, sequence),
                    ).fetchone()
                    recorded = dict(event)
                    annotation = connection.execute("SELECT record_json FROM event_annotations WHERE event_sequence=?", (sequence,)).fetchone()
                    recorded["recorded_facts_json"] = annotation[0] if annotation else None
                    return {"event": recorded, "version": expected_version}
                rows = connection.execute(
                    "SELECT sequence,version,event_type,recorded_at,length(CAST(payload_json AS BLOB)) AS payload_bytes "
                    "FROM events WHERE work_item_id=? AND sequence>? ORDER BY sequence ASC LIMIT ?",
                    (identifier, after_sequence, limit + 1),
                ).fetchall()
        except sqlite3.Error as error:
            raise WorkflowAuthorityError("history_data_invalid", "历史事件存储无法读取") from error
        selected = [dict(row) for row in rows[:limit]]
        return {
            "items": selected, "version": expected_version, "more": len(rows) > limit,
            "last_sequence": selected[-1]["sequence"] if selected else after_sequence,
        }

    def historical_verification(self, work_item_id: str, receipt_id: str, *, expected_version: int) -> dict[str, Any] | None:
        """Read one receipt, without materializing all current receipts in Python."""

        identifier = _text(work_item_id, "work_item_id")
        try:
            with self._read_connection(history_read=True) as connection:
                row = connection.execute("SELECT version FROM work_items WHERE work_item_id=?", (identifier,)).fetchone()
                if row is None or int(row[0]) != expected_version:
                    raise AuthorityConflict("history_snapshot_changed", "事项已变化，请重新查询")
                current = connection.execute(
                    "SELECT j.value FROM work_items w,json_each(w.data_json,'$.verifications') j WHERE w.work_item_id=? AND json_extract(j.value,'$.receipt_id')=? LIMIT 1",
                    (identifier, receipt_id),
                ).fetchone()
                if current:
                    if len(current[0].encode("utf-8")) > 16 * 1024 * 1024:
                        raise WorkflowAuthorityError("history_record_too_large", "验证回执超过读取上限")
                    receipt = json.loads(current[0])
                    return {"source": "stored_current_record", "receipt": receipt}
                event = connection.execute(
                    "SELECT sequence,payload_json FROM events WHERE work_item_id=? "
                    "AND event_type='record_verification' AND json_extract(payload_json,'$.verification.receipt_id')=? "
                    "ORDER BY sequence DESC LIMIT 1", (identifier, receipt_id),
                ).fetchone()
                if event:
                    if len(event[1].encode("utf-8")) > 16 * 1024 * 1024:
                        raise WorkflowAuthorityError("history_record_too_large", "原始验证事件超过读取上限")
                    receipt = json.loads(event[1])["verification"]
                    if not isinstance(receipt, dict):
                        raise ValueError
                    return {"source": "original_run_event", "sequence": int(event[0]), "receipt": receipt, "assessment_note": "后续变化判断请沿事件时间线读取"}
                return None
        except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise WorkflowAuthorityError("history_data_invalid", "当前或原始验证回执损坏，不能据此报告为没有验证") from error

    def historical_verifications(
        self, work_item_id: str, *, expected_version: int, limit: int = 25, after_receipt: str = "",
    ) -> dict[str, Any]:
        """Page distinct runs, including runs removed from the current plan."""

        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkflowAuthorityError("history_limit_invalid", "历史页大小必须为 1 到 100")
        try:
            with self._read_connection(history_read=True) as connection:
                row = connection.execute("SELECT version FROM work_items WHERE work_item_id=?", (work_item_id,)).fetchone()
                if row is None or int(row[0]) != expected_version:
                    raise AuthorityConflict("history_snapshot_changed", "事项已变化，请重新查询")
                rows = connection.execute("""
                    WITH receipts AS (
                        SELECT json_extract(j.value,'$.receipt_id') AS receipt_id,j.value AS receipt,0 AS source_rank,0 AS sequence
                        FROM work_items w,json_each(w.data_json,'$.verifications') j WHERE w.work_item_id=?
                        UNION ALL
                        SELECT json_extract(payload_json,'$.verification.receipt_id'),
                            json_extract(payload_json,'$.verification'),1,sequence
                        FROM events WHERE work_item_id=? AND event_type='record_verification'
                    ), ranked AS (
                        SELECT *,row_number() OVER(PARTITION BY receipt_id ORDER BY source_rank,sequence DESC) AS choice FROM receipts
                    )
                    SELECT receipt_id,sequence,source_rank,
                        json_extract(receipt,'$.command_id') AS command_id,
                        json_extract(receipt,'$.result') AS result,
                        json_extract(receipt,'$.started_at') AS started_at
                    FROM ranked WHERE choice=1 AND receipt_id>? ORDER BY receipt_id LIMIT ?
                """, (work_item_id, work_item_id, after_receipt, limit + 1)).fetchall()
        except sqlite3.Error as error:
            raise WorkflowAuthorityError("history_data_invalid", "历史验证记录无法读取") from error
        items = [dict(row) for row in rows[:limit]]
        return {"items": items, "more": len(rows) > limit, "last_receipt": items[-1]["receipt_id"] if items else after_receipt}

    def historical_output(self, work_item_id: str, receipt_id: str, stream: str) -> dict[str, Any] | None:
        with self._read_connection(history_read=True) as connection:
            row = connection.execute(
                "SELECT * FROM evidence_outputs WHERE work_item_id=? AND receipt_id=? AND stream=?",
                (work_item_id, receipt_id, stream),
            ).fetchone()
            return dict(row) if row else None

    def historical_candidates(
        self, work_item_id: str, *, expected_version: int, limit: int = 25,
        after_sequence: int = 0, sequence: int | None = None,
    ) -> dict[str, Any]:
        actions = {"submit_direction": "direction", "revise_direction": "direction", "submit_engineering_assessment": "engineering_plan", "present_actual_result": "actual_result"}
        if type(limit) is not int or not 1 <= limit <= 100:
            raise WorkflowAuthorityError("history_limit_invalid", "历史页大小必须为 1 到 100")
        try:
            with self._read_connection(history_read=True) as connection:
                version = connection.execute("SELECT version FROM work_items WHERE work_item_id=?", (work_item_id,)).fetchone()
                if version is None or int(version[0]) != expected_version:
                    raise AuthorityConflict("history_snapshot_changed", "事项已变化，请重新读取历史候选")
                fields = ("e.sequence,e.version,e.event_type,e.recorded_at,"
                          "json_extract(a.record_json,'$.candidate.kind') AS candidate_kind,"
                          "json_extract(a.record_json,'$.candidate.fingerprint') AS fingerprint,"
                          "json_extract(a.record_json,'$.candidate.state_at_recording') AS candidate_state")
                if sequence is not None:
                    fields += ",a.record_json"
                join = " LEFT JOIN event_annotations a ON a.event_sequence=e.sequence"
                where = "e.work_item_id=? AND e.event_type IN ('submit_direction','revise_direction','submit_engineering_assessment','present_actual_result')"
                parameters: list[Any] = [work_item_id]
                if sequence is None:
                    where += " AND e.sequence>?"
                    parameters.append(after_sequence)
                else:
                    where += " AND e.sequence=?"
                    parameters.append(sequence)
                    size = connection.execute(
                        f"SELECT length(CAST(e.payload_json AS BLOB))+COALESCE(length(CAST(a.record_json AS BLOB)),0) FROM events e{join} WHERE {where}", parameters,
                    ).fetchone()
                    if size and int(size[0]) > 16 * 1024 * 1024:
                        raise WorkflowAuthorityError("history_record_too_large", "候选及其原始正文超过 16 MiB 读取上限")
                rows = connection.execute(f"SELECT {fields} FROM events e{join} WHERE {where} ORDER BY e.sequence LIMIT ?", (*parameters, limit + 1 if sequence is None else 1)).fetchall()
                result = []
                for raw in rows[:limit]:
                    row = dict(raw)
                    kind = row["candidate_kind"]
                    if kind != actions[row["event_type"]] or not isinstance(row["fingerprint"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", row["fingerprint"]) or not isinstance(row["candidate_state"], str):
                        raise WorkflowAuthorityError("history_data_invalid", "候选事件缺少完整的规范化候选事实")
                    decision_field = "json_extract(record_json,'$.decision')" if sequence is not None else "json_extract(record_json,'$.decision.accepted')"
                    recorded = connection.execute(
                        f"SELECT {decision_field} FROM event_annotations WHERE work_item_id=? AND json_extract(record_json,'$.decision.candidate_fingerprint')=? ORDER BY event_sequence DESC LIMIT 1",
                        (work_item_id, row["fingerprint"]),
                    ).fetchone()
                    decision = None
                    if recorded is not None:
                        if sequence is None:
                            if recorded[0] not in (0, 1):
                                raise WorkflowAuthorityError("history_data_invalid", "已记录决定缺少明确接受状态")
                            decision = {"accepted": bool(recorded[0])}
                        else:
                            decision = json.loads(recorded[0])
                            if not isinstance(decision, dict) or type(decision.get("accepted")) is not bool:
                                raise WorkflowAuthorityError("history_data_invalid", "已记录决定结构无效")
                    superseded = bool(connection.execute(
                        "SELECT 1 FROM event_annotations a WHERE a.work_item_id=? AND a.event_sequence>? AND "
                        "(json_extract(a.record_json,'$.candidate.kind')=? OR EXISTS(SELECT 1 FROM json_each(a.record_json,'$.invalidated_kinds') WHERE value=?)) LIMIT 1",
                        (work_item_id, row["sequence"], kind, kind),
                    ).fetchone())
                    if decision and decision["accepted"] is False:
                        disposition = "rejected"
                    elif decision and decision["accepted"] is True:
                        disposition = "accepted_then_superseded" if superseded else "accepted"
                    else:
                        disposition = "superseded_without_decision" if superseded else "draft" if row["candidate_state"] == "discussion" else "awaiting_confirmation"
                    value = {"sequence": row["sequence"], "version": row["version"], "kind": kind, "recorded_at": row["recorded_at"], "disposition": disposition, "record_ref": f"candidate:{row['sequence']}", "binding_source": "recorded_candidate"}
                    if sequence is not None:
                        value["candidate"] = json.loads(row["record_json"])["candidate"]
                        value["decision"] = decision
                    result.append(value)
                if sequence is not None and not result:
                    raise WorkItemNotFound("history_candidate_missing", "该事件不是指定事项的候选记录")
        except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise WorkflowAuthorityError("history_data_invalid", "历史候选或记录的规范化判断损坏") from error
        return {"items": result, "more": len(rows) > limit, "last_sequence": result[-1]["sequence"] if result else after_sequence}

    def historical_result_binding(
        self, work_item_id: str, *, expected_version: int, result: Mapping[str, Any], fingerprint: str | None, repository_id: str | None = None,
    ) -> dict[str, Any]:
        """Bind a result to delivery events in its own presentation interval."""

        try:
            with self._read_connection(history_read=True) as connection:
                current = connection.execute("SELECT version FROM work_items WHERE work_item_id=?", (work_item_id,)).fetchone()
                if current is None or int(current[0]) != expected_version:
                    raise AuthorityConflict("history_snapshot_changed", "事项已变化，请重新读取结果交付绑定")
                predicate = "work_item_id=? AND json_extract(record_json,'$.candidate.kind')='actual_result' AND json_extract(record_json,'$.candidate.value')=?"
                parameters = [work_item_id, _json(result)]
                if fingerprint:
                    predicate += " AND json_extract(record_json,'$.candidate.fingerprint')=?"
                    parameters.append(fingerprint)
                row = connection.execute(f"SELECT event_sequence FROM event_annotations WHERE {predicate} ORDER BY event_sequence DESC LIMIT 1", parameters).fetchone()
                start = int(row[0]) if row else None
                if start is None:
                    return {"commit": None, "source": "presentation_not_bound"}
                end = connection.execute("SELECT MIN(sequence) FROM events WHERE work_item_id=? AND sequence>? AND event_type IN ('present_actual_result','submit_direction','revise_direction','submit_engineering_assessment','request_replan')", (work_item_id, start)).fetchone()[0]
                for row in connection.execute(
                    "SELECT sequence,event_type,payload_json FROM events WHERE work_item_id=? AND sequence>? AND (? IS NULL OR sequence<?) AND event_type IN ('record_result_commits','record_local_integration') ORDER BY sequence DESC",
                    (work_item_id, start, end, end),
                ):
                    payload = json.loads(row[2])
                    if payload.get("repository_id") != repository_id:
                        continue
                    commit = (payload.get("integration") or {}).get("integrated_commit") if row[1] == "record_local_integration" else (payload.get("commits") or [None])[-1]
                    if commit:
                        return {"commit": commit, "source": "delivery_event", "presentation_sequence": start, "delivery_sequence": int(row[0])}
                return {"commit": None, "source": "not_committed_for_this_result", "presentation_sequence": start}
        except (sqlite3.Error, ValueError, TypeError, KeyError, AttributeError) as error:
            raise WorkflowAuthorityError("history_data_invalid", "结果交付事件损坏，不能借用其他轮次的提交") from error

    def history(self, work_item_id: str) -> list[dict[str, Any]]:
        identifier = _text(work_item_id, "work_item_id")
        if not self._read_ready():
            raise AuthorityNotInitialized(
                "authority_not_initialized",
                "项目尚未 intake，WorkflowAuthority 不存在",
            )
        with self._read_connection() as connection:
            exists = connection.execute(
                "SELECT 1 FROM work_items WHERE work_item_id = ?",
                (identifier,),
            ).fetchone()
            if exists is None:
                raise WorkItemNotFound(
                    "work_item_not_found",
                    f"WorkItem 不存在：{identifier}",
                )
            rows = connection.execute(
                """
                SELECT sequence, version, event_type, payload_json, recorded_at
                FROM events
                WHERE work_item_id = ?
                ORDER BY sequence ASC
                """,
                (identifier,),
            ).fetchall()
        return [
            {
                "sequence": int(row["sequence"]),
                "work_item_id": identifier,
                "version": int(row["version"]),
                "event_type": str(row["event_type"]),
                "payload": json.loads(str(row["payload_json"])),
                "recorded_at": str(row["recorded_at"]),
            }
            for row in rows
        ]

    def revision(self) -> dict[str, Any]:
        """Return a small polling cursor derived from the event sequence."""

        if not self._read_ready():
            return {
                "schema_version": "strixnova.authority-revision.v1",
                "revision": 0,
                "updated_at": None,
            }
        with self._read_connection() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(MAX(sequence), 0) AS sequence,
                       MAX(recorded_at) AS recorded_at
                FROM events
                """
            ).fetchone()
        sequence = int(row["sequence"] if row is not None else 0)
        return {
            "schema_version": "strixnova.authority-revision.v1",
            "revision": sequence,
            "updated_at": (
                str(row["recorded_at"])
                if row is not None and row["recorded_at"] is not None
                else None
            ),
        }

    def _read_ready(self) -> bool:
        if not self.strixnova_root.exists():
            return False
        self._ensure_layout(create=False)
        if not self.database_path.exists():
            return False
        if self.database_path.is_symlink() or not self.database_path.is_file():
            raise WorkflowAuthorityError(
                "unsafe_authority_path",
                "Authority 数据库必须是 .strixnova 内的普通文件",
            )
        return True

    def _ensure_layout(self, *, create: bool = True) -> None:
        if self.strixnova_root.is_symlink() or self.strixnova_root.is_junction():
            raise WorkflowAuthorityError(
                "unsafe_strixnova_path",
                ".strixnova 不得是符号链接",
            )
        if not self.strixnova_root.exists():
            if not create:
                return
            self.strixnova_root.mkdir(exist_ok=True)
        elif not self.strixnova_root.is_dir():
            raise WorkflowAuthorityError(
                "unsafe_strixnova_path",
                ".strixnova 必须是目录",
            )
        allowed_current_entries = {
            ".gitignore",
            AUTHORITY_DATABASE_NAME,
            f"{AUTHORITY_DATABASE_NAME}-journal",
            f"{AUTHORITY_DATABASE_NAME}-shm",
            f"{AUTHORITY_DATABASE_NAME}-wal",
            DELIVERY_ACTIVITY_DATABASE_NAME,
            f"{DELIVERY_ACTIVITY_DATABASE_NAME}-journal",
            f"{DELIVERY_ACTIVITY_DATABASE_NAME}-shm",
            f"{DELIVERY_ACTIVITY_DATABASE_NAME}-wal",
            "artifacts",
        }
        present_entries = {item.name for item in self.strixnova_root.iterdir()}
        unsupported_entries = sorted(present_entries - allowed_current_entries)
        uninitialized_read_entries = {".gitignore"}
        artifact_root = self.strixnova_root / "artifacts"
        if create and not self.database_path.exists():
            ProjectMaintenance(self.project).validate_initialization_artifacts()
            uninitialized_read_entries.add("artifacts")
        if (
            not create
            and artifact_root.is_dir()
            and not artifact_root.is_symlink()
            and not artifact_root.is_junction()
        ):
            # A worktree can hold generated artifacts while its controlling
            # project owns the Authority database. Reading it must not create
            # another database or treat those opaque artifacts as workflow facts.
            uninitialized_read_entries.add("artifacts")
        orphaned_entries = sorted(
            present_entries - uninitialized_read_entries
            if not self.database_path.exists()
            else set()
        )
        if unsupported_entries or orphaned_entries:
            details = sorted(set(unsupported_entries + orphaned_entries))
            raise WorkflowAuthorityError(
                "unsupported_authority_format",
                "检测到不受支持的本地状态，请归档 .strixnova 后重新初始化："
                + ", ".join(details),
            )
        ignore_path = self.strixnova_root / ".gitignore"
        if ignore_path.exists() and ignore_path.is_symlink():
            raise WorkflowAuthorityError(
                "unsafe_gitignore_path",
                ".strixnova/.gitignore 不得是符号链接",
            )
        if not ignore_path.exists() and create:
            ignore_path.write_text(
                "\n".join(AUTHORITY_GITIGNORE_LINES) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    def _connect(self, *, read_only: bool = False) -> sqlite3.Connection:
        target = (
            f"{self.database_path.as_uri()}?mode=ro"
            if read_only
            else str(self.database_path)
        )
        connection = None
        try:
            connection = connect_with_maintenance(
                self.project, target, read_only=read_only,
                timeout=5.0, isolation_level=None, uri=read_only,
            )
            connection.row_factory = sqlite3.Row
            connection.create_function("strixnova_write_contract", 0, lambda: AUTHORITY_FORMAT, deterministic=True)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 5000")
            if read_only:
                connection.execute("PRAGMA query_only = ON")
            else:
                connection.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error as error:
            if connection is not None:
                connection.close()
            raise WorkflowAuthorityError("authority_open_failed", "事项数据库被占用或无法初始化连接") from error
        except MaintenanceError as error:
            if connection is not None:
                connection.close()
            if error.code == "unsupported_authority_format":
                raise WorkflowAuthorityError(error.code, str(error)) from error
            raise
        return connection

    def require_project_identity(self) -> None:
        """Check the selected store before any operation support files are written."""
        if self.expected_project_id is None or not self.database_path.exists():
            return
        with self._read_connection() as connection:
            row = connection.execute("SELECT value FROM metadata WHERE key='project_id'").fetchone()
            if row is not None and row[0] != self.expected_project_id:
                raise WorkflowAuthorityError("authority_project_mismatch", "管理位置已归属于另一个项目，不能共享事项库")

    @contextmanager
    def _read_connection(self, *, history_read: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self._connect(read_only=True)
        try:
            connection.execute("BEGIN")
            try:
                row = connection.execute(
                    "SELECT value FROM metadata WHERE key = 'schema_version'"
                ).fetchone()
            except sqlite3.Error as error:
                raise WorkflowAuthorityError(
                    "unsupported_authority_format",
                    "Authority 格式不受支持，请归档后重新初始化",
                ) from error
            if row is None or str(row[0]) != AUTHORITY_SCHEMA_VERSION:
                raise WorkflowAuthorityError(
                    "unsupported_authority_format",
                    "Authority 格式不受当前构建支持，不能读取或改写该存储",
                )
            required = {
                "work_items": "work_item_id,title,status,version,data_json,created_at,updated_at",
                "events": "sequence,work_item_id,version,event_type,payload_json,recorded_at",
            }
            required["evidence_outputs"] = "work_item_id,receipt_id,stream,relative_path,sha256,size_bytes,observation_kind,observed_at,availability"
            required["event_annotations"] = "event_sequence,work_item_id,record_json"
            if self.expected_project_id is not None:
                project_row = connection.execute("SELECT value FROM metadata WHERE key='project_id'").fetchone()
                if project_row is not None and project_row[0] != self.expected_project_id:
                    raise WorkflowAuthorityError("authority_project_mismatch", "管理位置已归属于另一个项目")
            try:
                for table, columns in required.items():
                    connection.execute(f"SELECT {columns} FROM {table} LIMIT 0")
            except sqlite3.Error as error:
                raise WorkflowAuthorityError("history_data_invalid" if history_read else "unsupported_authority_format", "Authority 的格式标记与实际表结构不一致，禁止写入") from error
            yield connection
        finally:
            connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            if self.expected_project_id is not None:
                has_metadata = connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='metadata'").fetchone()
                if has_metadata:
                    row = connection.execute("SELECT value FROM metadata WHERE key='project_id'").fetchone()
                    if row is not None and row[0] != self.expected_project_id:
                        raise WorkflowAuthorityError("authority_project_mismatch", "管理位置已归属于另一个项目")
                    if row is None:
                        connection.execute("INSERT INTO metadata(key,value) VALUES ('project_id',?)", (self.expected_project_id,))
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _row_to_work_item(row: sqlite3.Row | None) -> dict[str, Any]:
        if row is None:
            raise WorkflowAuthorityError(
                "authority_row_missing",
                "Authority 写入后无法读取 WorkItem",
            )
        return {
            "schema_version": "strixnova.work-item.v1",
            "work_item_id": str(row["work_item_id"]),
            "title": str(row["title"]),
            "status": str(row["status"]),
            "version": int(row["version"]),
            "data": json.loads(str(row["data_json"])),
            "created_at": str(row["created_at"]),
            "updated_at": str(row["updated_at"]),
        }


__all__ = [
    "AUTHORITY_DATABASE_NAME",
    "AUTHORITY_SCHEMA_VERSION",
    "DIRECTION_SCHEMA",
    "AuthorityConflict",
    "AuthorityNotInitialized",
    "InvalidTransition",
    "TERMINAL_STATES",
    "WORK_ITEM_STATES",
    "WorkItemNotFound",
    "WorkflowAuthority",
    "WorkflowAuthorityError",
]
