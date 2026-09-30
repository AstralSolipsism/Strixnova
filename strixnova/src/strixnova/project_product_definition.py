"""Read one project-owned product definition without judging its meaning."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
import re
from typing import Any

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
    repository_relative_path,
)


PRODUCT_DEFINITION_SCHEMA = "strixnova.project-product-definition.v1"
PROJECT_DIRECTION_CONTEXT_SCHEMA = "strixnova.project-direction-context.v1"
PRODUCT_DEFINITION_STATUSES = frozenset(
    {"draft", "ready_for_confirmation", "confirmed"}
)
DELIVERY_STAGE_COMMITMENTS = frozenset(
    {"current_target", "future_candidate"}
)

_PRODUCT_ID = re.compile(r"PRODUCT-[0-9A-F]{16}")
_REVISION_ID = re.compile(r"REVISION-[0-9A-F]{16}")
_OWNER_ID = re.compile(r"OWNER-[0-9A-F]{16}")
_USER_ID = re.compile(r"USER-[0-9A-F]{16}")
_PROBLEM_ID = re.compile(r"PROBLEM-[0-9A-F]{16}")
_OUTCOME_ID = re.compile(r"OUTCOME-[0-9A-F]{16}")
_CAPABILITY_ID = re.compile(r"CAPABILITY-[0-9A-F]{16}")
_NON_GOAL_ID = re.compile(r"NONGOAL-[0-9A-F]{16}")
_CONSTRAINT_ID = re.compile(r"CONSTRAINT-[0-9A-F]{16}")
_CRITERION_ID = re.compile(r"CRITERION-[0-9A-F]{16}")
_STAGE_ID = re.compile(r"STAGE-[0-9A-F]{16}")
_DECISION_ID = re.compile(r"DECISION-[0-9A-F]{16}")


class ProjectProductDefinitionError(ValueError):
    """The project product definition is structurally invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目产品定义无效")


def unadopted_project_direction_context() -> dict[str, Any]:
    """Return the truthful empty context for a project without adopted authority."""

    return {
        "schema_version": PROJECT_DIRECTION_CONTEXT_SCHEMA,
        "authority_scope": "unadopted_project",
        "observed_commit": None,
        "context_ref": None,
        "product": None,
        "capability_catalog": [],
        "guardrails": [],
        "semantic_relevance_machine_proven": False,
    }


def project_direction_context(
    product_definition: Mapping[str, Any],
    *,
    observed_commit: str | None,
) -> dict[str, Any]:
    """Project all current product choices without selecting what is relevant.

    The digest is only an internal freshness binding. It is computed over the
    complete projected product purpose, capability catalog and guardrail text;
    it neither classifies those values nor proves their meaning.
    """

    revision = product_definition.get("revision")
    revision = revision if isinstance(revision, Mapping) else {}
    stages = list(product_definition.get("delivery_stages") or [])
    current_stages = [
        stage
        for stage in stages
        if isinstance(stage, Mapping)
        and stage.get("commitment") == "current_target"
    ]
    if revision.get("status") != "confirmed" or len(current_stages) != 1:
        raise ProjectProductDefinitionError(
            ["方向决定上下文只能从已确认且具有唯一当前阶段的产品定义投影"]
        )

    product = {
        "product_id": str(product_definition.get("product_id") or ""),
        "revision_id": str(revision.get("revision_id") or ""),
        "title": str(product_definition.get("title") or ""),
        "purpose": str(product_definition.get("purpose") or ""),
        "current_stage": {
            "stage_id": str(current_stages[0].get("stage_id") or ""),
            "title": str(current_stages[0].get("title") or ""),
            "description": str(current_stages[0].get("description") or ""),
        },
    }
    capabilities = [
        {
            "capability_ref": "product.capability:"
            + str(capability.get("capability_id") or ""),
            "capability_id": str(capability.get("capability_id") or ""),
            "title": str(capability.get("title") or ""),
            "description": str(capability.get("description") or ""),
        }
        for capability in product_definition.get("capabilities") or []
        if isinstance(capability, Mapping)
    ]
    guardrails = [
        {
            "decision_ref": "product.non_goal:"
            + str(item.get("non_goal_id") or ""),
            "kind": "non_goal",
            "stable_id": str(item.get("non_goal_id") or ""),
            "statement": str(item.get("statement") or ""),
        }
        for item in product_definition.get("non_goals") or []
        if isinstance(item, Mapping)
    ] + [
        {
            "decision_ref": "product.constraint:"
            + str(item.get("constraint_id") or ""),
            "kind": "constraint",
            "stable_id": str(item.get("constraint_id") or ""),
            "statement": str(item.get("statement") or ""),
        }
        for item in product_definition.get("constraints") or []
        if isinstance(item, Mapping)
    ]
    content = {
        "product": product,
        "capability_catalog": capabilities,
        "guardrails": guardrails,
    }
    digest = hashlib.sha256(
        json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "schema_version": PROJECT_DIRECTION_CONTEXT_SCHEMA,
        "authority_scope": "adopted_integration_commit",
        "observed_commit": observed_commit,
        "context_ref": (
            "product-definition:"
            + product["product_id"]
            + ":"
            + product["revision_id"]
            + ":sha256:"
            + digest
        ),
        **content,
        "semantic_relevance_machine_proven": False,
    }


def validate_direction_context_binding(
    binding: Mapping[str, Any],
    current_context: Mapping[str, Any],
) -> None:
    """Check only freshness, reference existence, uniqueness and coverage."""

    issues: list[str] = []
    expected_context_ref = current_context.get("context_ref")
    if binding.get("context_ref") != expected_context_ref:
        issues.append("方向决定绑定的产品上下文已经过期，请重新读取当前决定上下文")

    capability_refs = list(binding.get("capability_refs") or [])
    if len(capability_refs) != len(set(capability_refs)):
        issues.append("方向决定重复引用了同一产品能力")
    known_capability_refs = {
        str(item.get("capability_ref") or "")
        for item in current_context.get("capability_catalog") or []
        if isinstance(item, Mapping)
    }
    unknown_capabilities = sorted(set(capability_refs) - known_capability_refs)
    if unknown_capabilities:
        issues.append(
            "方向决定引用了当前产品中不存在的能力："
            + ", ".join(unknown_capabilities)
        )

    dispositions = list(binding.get("guardrail_dispositions") or [])
    disposition_refs = [
        str(item.get("decision_ref") or "")
        for item in dispositions
        if isinstance(item, Mapping)
    ]
    if len(disposition_refs) != len(set(disposition_refs)):
        issues.append("方向决定重复处置了同一产品护栏")
    known_guardrail_refs = {
        str(item.get("decision_ref") or "")
        for item in current_context.get("guardrails") or []
        if isinstance(item, Mapping)
    }
    missing_guardrails = sorted(known_guardrail_refs - set(disposition_refs))
    unknown_guardrails = sorted(set(disposition_refs) - known_guardrail_refs)
    if missing_guardrails:
        issues.append(
            "方向决定没有逐项覆盖当前全部产品护栏："
            + ", ".join(missing_guardrails)
        )
    if unknown_guardrails:
        issues.append(
            "方向决定引用了当前产品中不存在的护栏："
            + ", ".join(unknown_guardrails)
        )

    if expected_context_ref is None:
        if capability_refs or disposition_refs:
            issues.append("尚未采用产品权威时，方向决定不得伪造能力或护栏引用")
    elif not capability_refs:
        issues.append("已有产品权威时，方向决定必须由智能编码代理选择至少一项相关能力")

    if issues:
        raise ProjectProductDefinitionError(issues)


def _fields(
    value: Mapping[str, Any],
    required: set[str],
    path: str,
    issues: list[str],
) -> None:
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        issues.append(f"{path} 缺少字段：" + ", ".join(missing))
    if extra:
        issues.append(f"{path} 包含未知字段：" + ", ".join(extra))


def _text(value: Any, path: str, issues: list[str]) -> str:
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{path} 必须是非空字符串")
        return ""
    return value.strip()


def _identity(
    value: Any,
    path: str,
    pattern: re.Pattern[str],
    issues: list[str],
) -> str:
    identifier = _text(value, path, issues)
    if identifier and pattern.fullmatch(identifier) is None:
        issues.append(f"{path} 必须使用稳定随机身份")
    return identifier


def _nullable_identity(
    value: Any,
    path: str,
    pattern: re.Pattern[str],
    issues: list[str],
) -> str | None:
    if value is None:
        return None
    return _identity(value, path, pattern, issues)


def _items(
    value: Any,
    path: str,
    issues: list[str],
    *,
    required: bool,
) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        issues.append(f"{path} 必须是数组")
        return []
    if required and not value:
        issues.append(f"{path} 不能为空")
    result: list[Mapping[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, Mapping):
            issues.append(f"{path}[{index}] 必须是对象")
            continue
        result.append(item)
    return result


def _identity_list(
    value: Any,
    path: str,
    pattern: re.Pattern[str],
    issues: list[str],
    *,
    required: bool,
) -> list[str]:
    if not isinstance(value, list):
        issues.append(f"{path} 必须是数组")
        return []
    if required and not value:
        issues.append(f"{path} 不能为空")
    result = [
        _identity(item, f"{path}[{index}]", pattern, issues)
        for index, item in enumerate(value)
    ]
    if len(result) != len(set(result)):
        issues.append(f"{path} 不得包含重复项")
    return result


def _remember_identity(
    identifier: str,
    known: set[str],
    collection_path: str,
    issues: list[str],
) -> None:
    if not identifier:
        return
    if identifier in known:
        issues.append(f"{collection_path} 身份重复：{identifier}")
    known.add(identifier)


def _nullable_date(value: Any, path: str, issues: list[str]) -> str | None:
    if value is None:
        return None
    text = _text(value, path, issues)
    if not text:
        return ""
    try:
        parsed = date.fromisoformat(text)
    except ValueError:
        issues.append(f"{path} 必须是有效公历日期")
        return text
    if parsed.isoformat() != text:
        issues.append(f"{path} 必须使用 YYYY-MM-DD 格式")
    return text


class ProjectProductDefinition:
    """Validate structure while leaving all product meaning to its authors."""

    def __init__(
        self,
        project_dir: str | Path,
        definition_path: str,
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
    ) -> None:
        try:
            self.reader = project_reader_for_scope(
                project_dir,
                observed_ref=observed_ref,
                shared_reader=shared_reader,
            )
            self.definition_path = repository_relative_path(
                definition_path,
                "product_definition_path",
            )
        except GitProjectReaderError as error:
            raise ProjectProductDefinitionError([str(error)]) from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit

    def load(self) -> dict[str, Any]:
        try:
            value = self.reader.load_yaml(
                self.definition_path,
                "项目产品定义",
            )
        except GitProjectReaderError as error:
            raise ProjectProductDefinitionError([str(error)]) from error
        if not isinstance(value, Mapping):
            raise ProjectProductDefinitionError(["项目产品定义必须是对象"])
        required = {
            "schema_version",
            "product_id",
            "revision",
            "title",
            "purpose",
            "product_owner",
            "primary_users",
            "problems",
            "desired_outcomes",
            "capabilities",
            "non_goals",
            "constraints",
            "success_criteria",
            "delivery_stages",
            "unresolved_decisions",
        }
        issues: list[str] = []
        _fields(value, required, "product_definition", issues)
        if value.get("schema_version") != PRODUCT_DEFINITION_SCHEMA:
            issues.append(
                "product_definition.schema_version 必须是 "
                + PRODUCT_DEFINITION_SCHEMA
            )

        _identity(
            value.get("product_id"),
            "product_definition.product_id",
            _PRODUCT_ID,
            issues,
        )
        _text(value.get("title"), "product_definition.title", issues)
        _text(value.get("purpose"), "product_definition.purpose", issues)

        owner_id = ""
        owner = value.get("product_owner")
        if not isinstance(owner, Mapping):
            issues.append("product_definition.product_owner 必须是对象")
        else:
            _fields(
                owner,
                {"owner_id", "display_name"},
                "product_definition.product_owner",
                issues,
            )
            owner_id = _identity(
                owner.get("owner_id"),
                "product_definition.product_owner.owner_id",
                _OWNER_ID,
                issues,
            )
            _text(
                owner.get("display_name"),
                "product_definition.product_owner.display_name",
                issues,
            )

        revision_id = ""
        revision_status = ""
        confirmed_by_owner_id: str | None = None
        confirmed_on: str | None = None
        revision = value.get("revision")
        if not isinstance(revision, Mapping):
            issues.append("product_definition.revision 必须是对象")
        else:
            revision_path = "product_definition.revision"
            _fields(
                revision,
                {
                    "revision_id",
                    "status",
                    "supersedes_revision_id",
                    "confirmed_by_owner_id",
                    "confirmed_on",
                },
                revision_path,
                issues,
            )
            revision_id = _identity(
                revision.get("revision_id"),
                f"{revision_path}.revision_id",
                _REVISION_ID,
                issues,
            )
            revision_status = _text(
                revision.get("status"),
                f"{revision_path}.status",
                issues,
            )
            if (
                revision_status
                and revision_status not in PRODUCT_DEFINITION_STATUSES
            ):
                issues.append(f"{revision_path}.status 不受支持")
            supersedes = _nullable_identity(
                revision.get("supersedes_revision_id"),
                f"{revision_path}.supersedes_revision_id",
                _REVISION_ID,
                issues,
            )
            if supersedes and supersedes == revision_id:
                issues.append("产品定义修订不得取代自身")
            confirmed_by_owner_id = _nullable_identity(
                revision.get("confirmed_by_owner_id"),
                f"{revision_path}.confirmed_by_owner_id",
                _OWNER_ID,
                issues,
            )
            confirmed_on = _nullable_date(
                revision.get("confirmed_on"),
                f"{revision_path}.confirmed_on",
                issues,
            )

        user_ids: set[str] = set()
        users_path = "product_definition.primary_users"
        for index, user in enumerate(
            _items(value.get("primary_users"), users_path, issues, required=True)
        ):
            path = f"{users_path}[{index}]"
            _fields(
                user,
                {"user_id", "title", "description"},
                path,
                issues,
            )
            identifier = _identity(
                user.get("user_id"), f"{path}.user_id", _USER_ID, issues
            )
            _remember_identity(identifier, user_ids, users_path, issues)
            _text(user.get("title"), f"{path}.title", issues)
            _text(user.get("description"), f"{path}.description", issues)

        problem_ids: set[str] = set()
        problems_path = "product_definition.problems"
        for index, problem in enumerate(
            _items(value.get("problems"), problems_path, issues, required=True)
        ):
            path = f"{problems_path}[{index}]"
            _fields(
                problem,
                {"problem_id", "user_ids", "statement"},
                path,
                issues,
            )
            identifier = _identity(
                problem.get("problem_id"),
                f"{path}.problem_id",
                _PROBLEM_ID,
                issues,
            )
            _remember_identity(identifier, problem_ids, problems_path, issues)
            references = _identity_list(
                problem.get("user_ids"),
                f"{path}.user_ids",
                _USER_ID,
                issues,
                required=True,
            )
            unknown = sorted(set(references) - user_ids)
            if unknown:
                issues.append(
                    f"{path}.user_ids 引用未知用户：" + ", ".join(unknown)
                )
            _text(problem.get("statement"), f"{path}.statement", issues)

        outcome_ids: set[str] = set()
        outcomes_path = "product_definition.desired_outcomes"
        for index, outcome in enumerate(
            _items(
                value.get("desired_outcomes"),
                outcomes_path,
                issues,
                required=True,
            )
        ):
            path = f"{outcomes_path}[{index}]"
            _fields(outcome, {"outcome_id", "statement"}, path, issues)
            identifier = _identity(
                outcome.get("outcome_id"),
                f"{path}.outcome_id",
                _OUTCOME_ID,
                issues,
            )
            _remember_identity(identifier, outcome_ids, outcomes_path, issues)
            _text(outcome.get("statement"), f"{path}.statement", issues)

        capability_ids: set[str] = set()
        capability_outcome_ids: set[str] = set()
        capabilities_path = "product_definition.capabilities"
        for index, capability in enumerate(
            _items(
                value.get("capabilities"),
                capabilities_path,
                issues,
                required=True,
            )
        ):
            path = f"{capabilities_path}[{index}]"
            _fields(
                capability,
                {
                    "capability_id",
                    "title",
                    "description",
                    "outcome_ids",
                },
                path,
                issues,
            )
            identifier = _identity(
                capability.get("capability_id"),
                f"{path}.capability_id",
                _CAPABILITY_ID,
                issues,
            )
            _remember_identity(
                identifier, capability_ids, capabilities_path, issues
            )
            _text(capability.get("title"), f"{path}.title", issues)
            _text(
                capability.get("description"),
                f"{path}.description",
                issues,
            )
            references = _identity_list(
                capability.get("outcome_ids"),
                f"{path}.outcome_ids",
                _OUTCOME_ID,
                issues,
                required=True,
            )
            capability_outcome_ids.update(references)
            unknown = sorted(set(references) - outcome_ids)
            if unknown:
                issues.append(
                    f"{path}.outcome_ids 引用未知目标结果："
                    + ", ".join(unknown)
                )

        for collection_name, id_field, pattern in (
            ("non_goals", "non_goal_id", _NON_GOAL_ID),
            ("constraints", "constraint_id", _CONSTRAINT_ID),
        ):
            collection_path = f"product_definition.{collection_name}"
            known: set[str] = set()
            for index, item in enumerate(
                _items(
                    value.get(collection_name),
                    collection_path,
                    issues,
                    required=True,
                )
            ):
                path = f"{collection_path}[{index}]"
                _fields(item, {id_field, "statement"}, path, issues)
                identifier = _identity(
                    item.get(id_field), f"{path}.{id_field}", pattern, issues
                )
                _remember_identity(identifier, known, collection_path, issues)
                _text(item.get("statement"), f"{path}.statement", issues)

        criterion_ids: set[str] = set()
        criterion_outcome_ids: set[str] = set()
        criteria_path = "product_definition.success_criteria"
        for index, criterion in enumerate(
            _items(
                value.get("success_criteria"),
                criteria_path,
                issues,
                required=True,
            )
        ):
            path = f"{criteria_path}[{index}]"
            _fields(
                criterion,
                {"criterion_id", "statement", "outcome_ids"},
                path,
                issues,
            )
            identifier = _identity(
                criterion.get("criterion_id"),
                f"{path}.criterion_id",
                _CRITERION_ID,
                issues,
            )
            _remember_identity(identifier, criterion_ids, criteria_path, issues)
            _text(criterion.get("statement"), f"{path}.statement", issues)
            references = _identity_list(
                criterion.get("outcome_ids"),
                f"{path}.outcome_ids",
                _OUTCOME_ID,
                issues,
                required=True,
            )
            criterion_outcome_ids.update(references)
            unknown = sorted(set(references) - outcome_ids)
            if unknown:
                issues.append(
                    f"{path}.outcome_ids 引用未知目标结果："
                    + ", ".join(unknown)
                )

        stage_ids: set[str] = set()
        current_stage_count = 0
        stages_path = "product_definition.delivery_stages"
        for index, stage in enumerate(
            _items(
                value.get("delivery_stages"),
                stages_path,
                issues,
                required=True,
            )
        ):
            path = f"{stages_path}[{index}]"
            _fields(
                stage,
                {"stage_id", "title", "commitment", "description"},
                path,
                issues,
            )
            identifier = _identity(
                stage.get("stage_id"),
                f"{path}.stage_id",
                _STAGE_ID,
                issues,
            )
            _remember_identity(identifier, stage_ids, stages_path, issues)
            _text(stage.get("title"), f"{path}.title", issues)
            commitment = _text(
                stage.get("commitment"), f"{path}.commitment", issues
            )
            if commitment and commitment not in DELIVERY_STAGE_COMMITMENTS:
                issues.append(f"{path}.commitment 不受支持")
            if commitment == "current_target":
                current_stage_count += 1
            _text(stage.get("description"), f"{path}.description", issues)
        if current_stage_count != 1:
            issues.append("product_definition.delivery_stages 必须恰有一个当前目标阶段")

        decision_ids: set[str] = set()
        decisions_path = "product_definition.unresolved_decisions"
        unresolved_decisions = _items(
            value.get("unresolved_decisions"),
            decisions_path,
            issues,
            required=False,
        )
        for index, decision in enumerate(unresolved_decisions):
            path = f"{decisions_path}[{index}]"
            _fields(
                decision,
                {"decision_id", "statement", "impact"},
                path,
                issues,
            )
            identifier = _identity(
                decision.get("decision_id"),
                f"{path}.decision_id",
                _DECISION_ID,
                issues,
            )
            _remember_identity(identifier, decision_ids, decisions_path, issues)
            _text(decision.get("statement"), f"{path}.statement", issues)
            _text(decision.get("impact"), f"{path}.impact", issues)

        if revision_status in {"ready_for_confirmation", "confirmed"}:
            if unresolved_decisions:
                issues.append("可确认或已确认的产品定义不得保留未决决定")
            outcomes_without_capability = sorted(
                outcome_ids - capability_outcome_ids
            )
            if outcomes_without_capability:
                issues.append(
                    "可确认的产品定义中，以下目标结果没有产品能力承接："
                    + ", ".join(outcomes_without_capability)
                )
            outcomes_without_criterion = sorted(
                outcome_ids - criterion_outcome_ids
            )
            if outcomes_without_criterion:
                issues.append(
                    "可确认的产品定义中，以下目标结果没有成功判断："
                    + ", ".join(outcomes_without_criterion)
                )
        if revision_status == "confirmed":
            if not confirmed_by_owner_id or not confirmed_on:
                issues.append("已确认的产品定义必须记录确认负责人和确认日期")
            elif owner_id and confirmed_by_owner_id != owner_id:
                issues.append("产品定义必须由当前产品负责人确认")
        elif confirmed_by_owner_id is not None or confirmed_on is not None:
            issues.append("未确认的产品定义不得记录确认负责人或确认日期")

        if issues:
            raise ProjectProductDefinitionError(issues)
        result = deepcopy(dict(value))
        result.update(
            {
                "_manifest_path": self.definition_path,
                "_observed_commit": self.observed_commit,
                "_semantic_content_machine_proven": False,
            }
        )
        return result


__all__ = [
    "DELIVERY_STAGE_COMMITMENTS",
    "PROJECT_DIRECTION_CONTEXT_SCHEMA",
    "PRODUCT_DEFINITION_SCHEMA",
    "PRODUCT_DEFINITION_STATUSES",
    "ProjectProductDefinition",
    "ProjectProductDefinitionError",
    "project_direction_context",
    "unadopted_project_direction_context",
    "validate_direction_context_binding",
]
