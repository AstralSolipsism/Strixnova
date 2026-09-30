"""Small, deterministic next-step projection for one WorkItem.

The projection tells an Agent what Strixnova expects next and which existing
records may be read on demand. It never embeds those records or invents
project meaning.
"""

from __future__ import annotations

from strixnova.work_item_repositories import repository_view
from strixnova.verification_dependencies import dependency_evidence_stale

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from strixnova.confirmation_protocol import (
    ConfirmationProtocolError,
    confirmation_challenge_for,
)
from strixnova.engineering_change_planning import (
    focused_slice,
    implementation_slice_reportability,
)
from strixnova.project_authority_progress import (
    ProjectAuthorityDecisionError,
    project_authority_stage,
)


CURRENT_ACTION_SCHEMA = "strixnova.current-action.v1"

ActionDefinition = tuple[str, str, str, str, tuple[str, ...]]


def _action(
    action_type: str,
    actor: str,
    intent: str,
    input_kind: str,
    *record_refs: str,
) -> ActionDefinition:
    return action_type, actor, intent, input_kind, tuple(record_refs)


_ACTION_BY_STATUS: dict[str, ActionDefinition] = {
    "discussion": _action(
        "submit_direction",
        "coding_agent",
        "submit",
        "direction",
        "request",
        "project.direction_context",
        "project.follow_ups",
    ),
    "awaiting_direction_confirmation": _action(
        "confirm_direction",
        "user",
        "confirm",
        "direction_confirmation",
        "direction",
        "project.direction_context",
    ),
    "needs_engineering_assessment": _action(
        "submit_engineering_assessment",
        "coding_agent",
        "submit",
        "engineering_assessment",
        "direction",
        "direction_confirmation",
        "project.direction_context",
        "project.engineering",
        "project.engineering.assurance",
        "project.follow_ups",
        "project.domain.catalog",
        "project.architecture",
        "project.domain.alignment",
    ),
    "awaiting_plan_confirmation": _action(
        "confirm_engineering_plan",
        "user",
        "confirm",
        "engineering_plan_confirmation",
        "engineering.plan",
        "repository_deliveries",
    ),
    "implementation_ready": _action(
        "begin_implementation",
        "coding_agent",
        "delivery",
        "begin_implementation",
        "engineering.plan",
    ),
    "exploring": _action(
        "investigate_and_report",
        "coding_agent",
        "delivery",
        "actual_result",
        "engineering.plan",
    ),
    "implementing": _action(
        "implement_and_verify",
        "coding_agent",
        "verify",
        "verification",
        "engineering.plan.verification_commands",
        "git",
    ),
    "awaiting_actual_result": _action(
        "confirm_actual_result",
        "user",
        "confirm",
        "actual_result_confirmation",
        "actual_result",
    ),
    "commit_required": _action(
        "create_atomic_commits",
        "coding_agent",
        "delivery",
        "commit_and_integrate",
        "actual_result_confirmation",
        "delivery.authority_adoption",
        "git",
    ),
    "integration_required": _action(
        "integrate_target",
        "strixnova",
        "delivery",
        "integrate",
        "git.result_commits",
    ),
    "integration_conflict": _action(
        "resolve_git_conflict",
        "coding_agent",
        "submit",
        "conflict_resolution",
        "git.integration",
        "engineering.plan",
    ),
    "cleanup_required": _action(
        "cleanup_work_area",
        "strixnova",
        "delivery",
        "cleanup",
        "git.integration",
    ),
    "replanning_required": _action(
        "revise_engineering_plan",
        "coding_agent",
        "submit",
        "replan",
        "blockers",
        "direction",
        "project.direction_context",
        "engineering.assessment",
        "project.domain.catalog",
        "project.architecture",
        "project.domain.alignment",
    ),
    "cancelled_changes_pending": _action(
        "decide_cancelled_work",
        "user",
        "cancel",
        "cancellation_decision",
        "git",
        "cancellation",
    ),
}

TERMINAL_WORK_ITEM_STATES = frozenset({"completed", "cancelled"})

_CONDITIONAL_RECORD_REFS_BY_ACTION = {
    "submit_engineering_assessment": frozenset(
        {
            "project.engineering",
            "project.engineering.assurance",
            "project.domain.catalog",
            "project.architecture",
            "project.domain.alignment",
        }
    ),
    "revise_engineering_plan": frozenset(
        {
            "project.domain.catalog",
            "project.architecture",
            "project.domain.alignment",
        }
    ),
}


class CurrentActionError(ValueError):
    """The supplied WorkItem projection cannot produce one safe action."""


def _blockers(data: Mapping[str, Any]) -> list[str]:
    raw = data.get("blockers")
    if not isinstance(raw, list):
        return []
    return [str(item).strip() for item in raw if str(item).strip()]


def _pending_assessment_refs(data: Mapping[str, Any]) -> tuple[str, ...]:
    verifications = data.get("verifications")
    if not isinstance(verifications, list):
        return ()
    return tuple(
        f"verifications:{receipt_id}"
        for receipt in verifications
        if isinstance(receipt, Mapping)
        and receipt.get("code_change_assessment") is None
        and (receipt_id := str(receipt.get("receipt_id") or "").strip())
    )


def _verification_commands(data: Mapping[str, Any]) -> list[Any] | None:
    engineering = data.get("engineering")
    if not isinstance(engineering, Mapping):
        return None
    plan = engineering.get("plan")
    if isinstance(plan, Mapping) and isinstance(
        plan.get("verification_commands"), list
    ):
        return list(plan["verification_commands"])
    assessment = engineering.get("assessment")
    if isinstance(assessment, Mapping) and isinstance(
        assessment.get("verification_commands"), list
    ):
        return list(assessment["verification_commands"])
    return None


def _verification_status(data: Mapping[str, Any]) -> str | None:
    """Derive the aggregate status without revalidating stored receipts."""

    commands = _verification_commands(data)
    if commands is None:
        return None
    required_ids = {
        str(command.get("command_id") or f"VC-{index + 1:03d}")
        for index, command in enumerate(commands)
        if isinstance(command, Mapping)
    }
    latest: dict[str, Mapping[str, Any]] = {}
    for receipt in data.get("verifications") or []:
        if not isinstance(receipt, Mapping):
            continue
        command_id = str(receipt.get("command_id") or "").strip()
        if command_id in required_ids:
            latest[command_id] = receipt
    if not required_ids:
        return "not_required"
    if required_ids - set(latest):
        return "pending"
    if any(
        not isinstance(receipt.get("code_change_assessment"), Mapping)
        or receipt["code_change_assessment"].get("needs_retest") is not False
        or receipt.get("_case_input_stale") is True
        for receipt in latest.values()
    ):
        return "pending"
    if all(receipt.get("result") == "passed" for receipt in latest.values()):
        return "passed"
    return "completed_with_issues"


def _focused_implementation_slice(
    data: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project the next confirmed slice without dispatching an Agent."""

    engineering = data.get("engineering")
    plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
    if not isinstance(plan, Mapping):
        return None
    receipts = data.get("verifications")
    completions = data.get("implementation_slice_completions")
    return focused_slice(
        plan,
        receipts if isinstance(receipts, list) else [],
        completions if isinstance(completions, list) else [],
    )


def _implementation_slice_reportability(data: Mapping[str, Any]) -> dict[str, Any]:
    engineering = data.get("engineering")
    plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
    if not isinstance(plan, Mapping):
        return {"reportable": True, "reason": "not_planned"}
    receipts = data.get("verifications")
    completions = data.get("implementation_slice_completions")
    return implementation_slice_reportability(
        plan,
        receipts if isinstance(receipts, list) else [],
        completions if isinstance(completions, list) else [],
    )


def _current_project_authority_stage(
    work_item: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Project author, presentation, and confirmation as separate steps."""

    try:
        return project_authority_stage(
            work_item,
            current_progress_only=True,
        )
    except ProjectAuthorityDecisionError as error:
        raise CurrentActionError(str(error)) from error


def _integration_conflict_action(
    data: Mapping[str, Any],
    pending_assessments: tuple[str, ...],
) -> ActionDefinition:
    if pending_assessments:
        return _action(
            "assess_verification_change",
            "coding_agent",
            "verify",
            "verification_assessment",
            *pending_assessments,
        )
    git = data.get("git")
    resolution = (
        git.get("conflict_resolution") if isinstance(git, Mapping) else None
    )
    if not isinstance(resolution, Mapping):
        return _ACTION_BY_STATUS["integration_conflict"]
    if resolution.get("requires_reassessment") is True:
        return _ACTION_BY_STATUS["integration_conflict"]

    result_changed = (
        resolution.get("user_visible_result_changed") is True
        or resolution.get("confirmed_direction_or_plan_changed") is True
    )
    confirmation = data.get("actual_result_confirmation")
    confirmation_is_new = (
        isinstance(confirmation, Mapping)
        and confirmation.get("accepted") is True
        and confirmation.get("confirmed_at")
        != resolution.get("confirmation_at_decision")
    )
    if result_changed and confirmation_is_new:
        return _action(
            "complete_git_merge",
            "coding_agent",
            "delivery",
            "complete_merge",
            "actual_result_confirmation",
            "git.conflict_resolution",
        )

    required_ids = set(resolution.get("retest_command_ids") or [])
    previous_receipt_ids = set(
        resolution.get("receipt_ids_at_decision") or []
    )
    latest: dict[str, Mapping[str, Any]] = {}
    for receipt in data.get("verifications") or []:
        if (
            isinstance(receipt, Mapping)
            and receipt.get("receipt_id") not in previous_receipt_ids
            and receipt.get("command_id") in required_ids
        ):
            latest[str(receipt["command_id"])] = receipt
    needs_retest = any(
        receipt.get("_case_input_stale") is True or (
            isinstance(receipt.get("code_change_assessment"), Mapping)
            and receipt["code_change_assessment"].get("needs_retest") is True
        )
        for receipt in latest.values()
    )
    if required_ids - set(latest) or needs_retest:
        return _action(
            "verify_after_git_conflict",
            "coding_agent",
            "verify",
            "conflict_retest",
            "git.conflict_resolution",
            "engineering.plan.verification_commands",
        )

    negative = any(
        receipt.get("result") != "passed" for receipt in latest.values()
    )
    if (result_changed or negative) and not confirmation_is_new:
        return _action(
            "present_actual_result_after_conflict",
            "coding_agent",
            "delivery",
            "actual_result",
            "verifications",
            "git.conflict_resolution",
        )
    return _action(
        "complete_git_merge",
        "coding_agent",
        "delivery",
        "complete_merge",
        "git.conflict_resolution",
        "verifications",
    )


def current_action_for(work_item: Mapping[str, Any]) -> dict[str, Any] | None:
    action = _current_action_for(work_item)
    if action is not None and action.get("actor") == "coding_agent":
        if work_item.get("data", {}).get("engineering", {}).get("plan") and action["action_type"] in {
            "begin_implementation", "implement_and_verify", "complete_implementation_slice",
            "present_actual_result", "revise_engineering_plan", "assess_verification_change",
            "author_project_authority_candidate", "review_project_authority_candidates",
            "resolve_git_conflict", "assess_target_advance",
        }:
            action["record_refs"].append("engineering.execution_context")
        if work_item.get("data", {}).get("engineering", {}).get("plan") and action["action_type"] in {
            "implement_and_verify", "complete_implementation_slice", "present_actual_result",
            "investigate_and_report", "investigate_and_verify", "present_actual_result_after_conflict",
        }:
            action["record_refs"].append("engineering.review_subject")
        contexts = []
        for entry in work_item.get("data", {}).get("repository_deliveries") or []:
            area = entry.get("git") or {}
            integrated = (area.get("integration") or {}).get("integrated_commit")
            mode = "integrated" if integrated else "target" if area.get("conflict_resolution") or (area.get("integration") or {}).get("outcome") == "conflict" else "worktree"
            root = area.get("repository") if mode != "worktree" else area.get("worktree_path")
            if root:
                contexts.append({"repository_id": entry["repository_id"], "path": root, "mode": mode})
        if contexts:
            action["repository_execution_contexts"] = contexts
    return action


def _current_action_for(work_item: Mapping[str, Any]) -> dict[str, Any] | None:
    """Project one operational next step from authoritative stored facts."""

    work_item_id = str(work_item.get("work_item_id") or "").strip()
    status = str(work_item.get("status") or "").strip()
    version = work_item.get("version")
    if not work_item_id:
        raise CurrentActionError("WorkItem 缺少 work_item_id")
    if type(version) is not int or version < 1:
        raise CurrentActionError("WorkItem version 无效")
    if status in TERMINAL_WORK_ITEM_STATES:
        return None
    definition = _ACTION_BY_STATUS.get(status)
    if definition is None:
        raise CurrentActionError(f"未知 WorkItem 状态：{status or '<empty>'}")

    raw_data = work_item.get("data")
    data = repository_view(raw_data, status) if isinstance(raw_data, Mapping) else {}
    for receipt in data.get("verifications") or []:
        if receipt.get("dependency_evidence") and dependency_evidence_stale(receipt["dependency_evidence"]):
            receipt["_case_input_stale"] = True
    pending_effect = data.get("pending_effect")
    if isinstance(pending_effect, Mapping):
        effect_kind = str(pending_effect.get("kind") or "").strip()
        if effect_kind not in {
            "prepare_work_area",
            "verification",
            "integrate",
            "cleanup",
            "cancel_cleanup",
            "cancel_discard",
            "project_authority_confirmation",
            "authority_adoption",
        }:
            raise CurrentActionError("WorkItem pending_effect 无效")
        if effect_kind == "project_authority_confirmation":
            definition = _action(
                "confirm_project_authority_candidates",
                "user",
                "authority",
                "project_authority_confirmation_bundle",
                "engineering.plan",
                "pending_effect",
            )
        elif effect_kind == "authority_adoption":
            definition = _ACTION_BY_STATUS[status]
        else:
            intent = (
                "cancel" if effect_kind.startswith("cancel_") else "verify" if effect_kind == "verification" else "delivery"
            )
            definition = _action(
                f"resume_{effect_kind}",
                "strixnova",
                intent,
                "resume_external_effect",
                "pending_effect",
                "git",
            )
    else:
        pending_assessments = _pending_assessment_refs(data)
        if status in {"exploring", "implementing"}:
            verification_status = _verification_status(data)
            authority_stage = (
                _current_project_authority_stage(work_item)
                if status == "implementing"
                else None
            )
            if authority_stage is not None:
                if authority_stage["stage"] == "author":
                    definition = _action(
                        "author_project_authority_candidate",
                        "coding_agent",
                        "authority",
                        "project_authority_candidate",
                        "engineering.plan",
                        "git",
                    )
                elif authority_stage["stage"] == "review":
                    definition = _action(
                        "review_project_authority_candidates",
                        "coding_agent",
                        "authority",
                        "project_authority_review_submission",
                        "engineering.plan",
                        "project_authority_presentations",
                    )
                else:
                    definition = _action(
                        "confirm_project_authority_candidates",
                        "user",
                        "authority",
                        "project_authority_confirmation_bundle",
                        "engineering.plan",
                    )
            elif pending_assessments:
                definition = _action(
                    "assess_verification_change",
                    "coding_agent",
                    "verify",
                    "verification_assessment",
                    *pending_assessments,
                )
            elif status == "exploring" and verification_status == "pending":
                definition = _action(
                    "investigate_and_verify",
                    "coding_agent",
                    "verify",
                    "verification",
                    "engineering.plan.verification_commands",
                )
            elif status == "exploring" and verification_status in {
                "not_required",
                "passed",
                "completed_with_issues",
            }:
                definition = _action(
                    "present_actual_result",
                    "coding_agent",
                    "delivery",
                    "actual_result",
                    "engineering.plan",
                    "verifications",
                )
            elif status == "implementing":
                if (
                    (
                        _implementation_slice_reportability(data).get("reason")
                        == "terminal_slice_issue"
                    )
                    or (
                        verification_status == "completed_with_issues"
                        and _implementation_slice_reportability(data).get(
                            "reportable"
                        )
                        is True
                    )
                ):
                    # Every planned command has a current, assessed receipt. A
                    # failed, blocked, or not-run result is honest evidence for
                    # the actual-result boundary; it must not unlock dependent
                    # slices as though the command had passed.
                    definition = _action(
                        "present_actual_result",
                        "coding_agent",
                        "delivery",
                        "actual_result",
                        "engineering.plan",
                        "verifications",
                    )
                else:
                    implementation_slice = _focused_implementation_slice(data)
                    if implementation_slice is not None:
                        slice_ref = (
                            "engineering.plan.implementation_slice:"
                            + str(implementation_slice["slice_id"])
                        )
                        if not implementation_slice.get(
                            "verification_command_ids"
                        ):
                            definition = _action(
                                "complete_implementation_slice",
                                "coding_agent",
                                "submit",
                                "implementation_slice_completion",
                                slice_ref,
                                "git",
                            )
                        else:
                            definition = _action(
                                "implement_and_verify",
                                "coding_agent",
                                "verify",
                                "verification",
                                slice_ref,
                                "engineering.plan.verification_commands",
                                "git",
                            )
                    elif verification_status in {
                        "not_required",
                        "passed",
                        "completed_with_issues",
                    }:
                        definition = _action(
                            "present_actual_result",
                            "coding_agent",
                            "delivery",
                            "actual_result",
                            "engineering.plan",
                            "verifications",
                        )
        if status in {
            "implementation_ready",
            "commit_required",
            "integration_required",
        }:
            git = data.get("git")
            target_advance = (
                git.get("target_advance")
                if isinstance(git, Mapping)
                else None
            )
            if isinstance(target_advance, Mapping) and not isinstance(
                target_advance.get("assessment"), Mapping
            ):
                definition = _action(
                    "assess_target_advance",
                    "coding_agent",
                    "submit",
                    "target_advance_assessment",
                    "git.target_advance",
                    "engineering.plan",
                )
        if status == "integration_conflict":
            definition = _integration_conflict_action(
                data,
                pending_assessments,
            )

    action_type, actor, intent, input_kind, record_refs = definition
    conditional_record_refs = _CONDITIONAL_RECORD_REFS_BY_ACTION.get(
        action_type,
        frozenset(),
    )
    result = {
        "schema_version": CURRENT_ACTION_SCHEMA,
        "work_item_id": work_item_id,
        "work_item_version": version,
        "action_type": action_type,
        "actor": actor,
        "intent": intent,
        "input_kind": input_kind,
        "input_contract_ref": f"input.contract:{action_type}",
        "record_refs": [
            ref for ref in record_refs if ref not in conditional_record_refs
        ],
        "conditional_record_refs": [
            ref for ref in record_refs if ref in conditional_record_refs
        ],
        "blocking_facts": _blockers(data),
    }
    if action_type in {"begin_implementation", "create_atomic_commits", "integrate_target", "resolve_git_conflict", "cleanup_work_area", "assess_target_advance", "complete_git_merge", "resume_prepare_work_area", "resume_integrate", "resume_cleanup", "resume_verification"}:
        result["repository_id"] = data.get("selected_repository_id")
        if "repository_deliveries" not in result["record_refs"]:
            result["record_refs"].append("repository_deliveries")
    if action_type in {
        "author_project_authority_candidate",
        "review_project_authority_candidates",
        "confirm_project_authority_candidates",
    }:
        authority_stage = _current_project_authority_stage(work_item)
        assert authority_stage is not None
        authority_kind = str(authority_stage["authority_kind"])
        result["authority_kind"] = authority_kind
        result["authority_kinds"] = list(
            authority_stage.get("authority_kinds") or [authority_kind]
        )
        result["blocking_facts"] = [
            *result["blocking_facts"],
            (
                "project_authority_review_required:"
                if action_type == "review_project_authority_candidates"
                else "project_authority_decision_required:"
            )
            + authority_kind,
        ]
        presentation = authority_stage.get("presentation")
        if (
            action_type == "confirm_project_authority_candidates"
        ):
            presentations = authority_stage.get("presentations")
            result["confirmation_challenges"] = [
                deepcopy(dict(value["confirmation_challenge"]))
                for value in presentations or []
                if isinstance(value, Mapping)
                and isinstance(value.get("confirmation_challenge"), Mapping)
            ]
    if intent == "confirm":
        try:
            result["confirmation_challenge"] = confirmation_challenge_for(
                action_type=action_type,
                work_item_id=work_item_id,
                work_item_version=version,
                data=data,
            )
        except ConfirmationProtocolError as error:
            raise CurrentActionError(str(error)) from error
    return result


def direction_revision_action_for(
    work_item: Mapping[str, Any],
    issues: Sequence[str],
) -> dict[str, Any]:
    """Project the recovery action after deterministic product-context drift.

    The caller owns the read-only comparison with the current project
    authority.  This pure WorkItem projection only turns those exact issues
    into one recoverable next step; it does not interpret their meaning.
    """

    work_item_id = str(work_item.get("work_item_id") or "").strip()
    version = work_item.get("version")
    if not work_item_id:
        raise CurrentActionError("WorkItem 缺少 work_item_id")
    if type(version) is not int or version < 1:
        raise CurrentActionError("WorkItem version 无效")
    normalized_issues = [str(issue).strip() for issue in issues if str(issue).strip()]
    if not normalized_issues:
        raise CurrentActionError("修订方向动作必须包含确定性的上下文失效事实")
    raw_data = work_item.get("data")
    data = raw_data if isinstance(raw_data, Mapping) else {}
    return {
        "schema_version": CURRENT_ACTION_SCHEMA,
        "work_item_id": work_item_id,
        "work_item_version": version,
        "action_type": "revise_direction",
        "actor": "coding_agent",
        "intent": "submit",
        "input_kind": "direction",
        "input_contract_ref": "input.contract:revise_direction",
        "record_refs": [
            "request",
            "direction",
            "direction_confirmation",
            "engineering.plan",
            "project.direction_context",
        ],
        "conditional_record_refs": [],
        "blocking_facts": [
            *_blockers(data),
            *[
                f"direction_context_invalid:{issue}"
                for issue in normalized_issues
            ],
        ],
    }


__all__ = [
    "CURRENT_ACTION_SCHEMA",
    "CurrentActionError",
    "TERMINAL_WORK_ITEM_STATES",
    "current_action_for",
    "direction_revision_action_for",
]
