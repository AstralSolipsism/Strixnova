"""Deterministic candidate binding for the three user confirmation gates.

The protocol deliberately does not decide whether a candidate is good or
whether an explanation was understood. The Agent interprets the user's later
message; the program binds that explicit interpretation and verbatim message
to one candidate and WorkItem version.
"""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any


CONFIRMATION_CHALLENGE_SCHEMA = "strixnova.confirmation-challenge.v1"
USER_CONFIRMATION_SCHEMA = "strixnova.user-confirmation.v1"

_CONFIRMATION_SPECS = {
    "confirm_direction": ("direction", "当前展示的方向"),
    "confirm_engineering_plan": (
        "engineering_plan",
        "当前展示的工程方案",
    ),
    "confirm_actual_result": ("actual_result", "当前展示的实际结果"),
}

class ConfirmationProtocolError(ValueError):
    """One confirmation challenge or reply is structurally invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfirmationProtocolError(
            "confirmation_input_invalid",
            f"{field} 必须是非空字符串",
        )
    return value.strip()


def _candidate_for(
    action_type: str,
    data: Mapping[str, Any],
) -> Mapping[str, Any]:
    if action_type == "confirm_direction":
        candidate = data.get("direction")
    elif action_type == "confirm_engineering_plan":
        engineering = data.get("engineering")
        candidate = (
            engineering.get("plan")
            if isinstance(engineering, Mapping)
            else None
        )
    elif action_type == "confirm_actual_result":
        candidate = data.get("actual_result")
    else:
        raise ConfirmationProtocolError(
            "confirmation_action_invalid",
            f"当前动作不是用户确认：{action_type or '<empty>'}",
        )
    if not isinstance(candidate, Mapping):
        raise ConfirmationProtocolError(
            "confirmation_candidate_missing",
            "当前确认动作缺少完整候选记录",
        )
    return candidate


def confirmation_challenge_for(
    *,
    action_type: str,
    work_item_id: str,
    work_item_version: int,
    data: Mapping[str, Any],
) -> dict[str, Any]:
    """Project one stable challenge from exact stored candidate identity."""

    spec = _CONFIRMATION_SPECS.get(action_type)
    if spec is None:
        raise ConfirmationProtocolError(
            "confirmation_action_invalid",
            f"当前动作不是用户确认：{action_type or '<empty>'}",
        )
    identifier = _required_text(work_item_id, "work_item_id")
    if type(work_item_version) is not int or work_item_version < 1:
        raise ConfirmationProtocolError(
            "confirmation_version_invalid",
            "work_item_version 必须是正整数",
        )
    candidate_kind, decision_label = spec
    candidate = _candidate_for(action_type, data)
    envelope = {
        "schema_version": CONFIRMATION_CHALLENGE_SCHEMA,
        "work_item_id": identifier,
        "work_item_version": work_item_version,
        "action_type": action_type,
        "candidate": candidate,
    }
    try:
        canonical = json.dumps(
            envelope,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ConfirmationProtocolError(
            "confirmation_candidate_invalid",
            "当前候选无法形成稳定身份指纹",
        ) from error
    digest = hashlib.sha256(canonical).hexdigest()
    return {
        "schema_version": CONFIRMATION_CHALLENGE_SCHEMA,
        "candidate_kind": candidate_kind,
        "candidate_fingerprint": f"sha256:{digest}",
        "decision_label": decision_label,
        "decision_interpreter": "coding_agent",
    }


def confirmation_input_schema(
    challenge: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact public payload schema for one challenge."""

    fingerprint = _required_text(
        challenge.get("candidate_fingerprint"),
        "candidate_fingerprint",
    )
    common = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "additionalProperties": False,
        "required": ["candidate_fingerprint", "user_confirmation", "agent_decision"],
        "properties": {
            "candidate_fingerprint": {"const": fingerprint},
            "user_confirmation": {"type": "string", "pattern": r"\S"},
        },
    }
    branches = []
    for decision in ("accept", "request_changes"):
        branches.append({
            **common,
            "properties": {
                **common["properties"],
                "agent_decision": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["decision", "reason"],
                    "properties": {
                        "decision": {"const": decision},
                        "reason": {"type": "string", "pattern": r"\S"},
                    },
                },
            },
        })
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "strixnova.user-confirmation-input.v1",
        "oneOf": branches,
    }




def confirmation_record_from_input(
    challenge: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate bindings and record Agent interpretation, without reading intent."""

    if not isinstance(payload, Mapping) or set(payload) != {
        "candidate_fingerprint", "user_confirmation", "agent_decision"
    }:
        raise ConfirmationProtocolError(
            "confirmation_input_invalid",
            "确认输入必须包含 candidate_fingerprint、用户原话 user_confirmation 和 agent_decision",
        )
    fingerprint = _required_text(challenge.get("candidate_fingerprint"), "candidate_fingerprint")
    if _required_text(payload.get("candidate_fingerprint"), "candidate_fingerprint") != fingerprint:
        raise ConfirmationProtocolError(
            "confirmation_candidate_mismatch", "当前输入不属于已展示的精确候选",
        )
    message = payload.get("user_confirmation")
    _required_text(message, "user_confirmation")
    interpretation = payload.get("agent_decision")
    if not isinstance(interpretation, Mapping) or set(interpretation) != {"decision", "reason"}:
        raise ConfirmationProtocolError(
            "confirmation_input_invalid", "agent_decision 必须包含 decision 和 reason",
        )
    decision = interpretation.get("decision")
    if decision not in ("accept", "request_changes"):
        raise ConfirmationProtocolError(
            "confirmation_input_invalid", "未明确的答复不得提交确认；应先解释或澄清",
        )
    reason = _required_text(interpretation.get("reason"), "agent_decision.reason")
    return {
        "schema_version": USER_CONFIRMATION_SCHEMA,
        "accepted": decision == "accept",
        "candidate_kind": _required_text(challenge.get("candidate_kind"), "candidate_kind"),
        "candidate_fingerprint": fingerprint,
        "decision_label": _required_text(challenge.get("decision_label"), "decision_label"),
        "user_confirmation": message,
        "summary": reason,
        "agent_decision": {"decision": decision, "reason": reason},
        "decision_interpreter": "coding_agent",
        "semantic_content_machine_proven": False,
    }



def attach_confirmation_message(
    payload: Mapping[str, Any], message: str,
) -> dict[str, Any]:
    """Attach caller-provided original text without interpreting or authenticating it.

    A caller may supply one raw message for an explicitly scoped decision bundle.
    This only expands transport fields; the normal candidate and decision
    validators still run on submission. Never generate this source from a summary.
    """

    _required_text(message, "user_confirmation")
    if not isinstance(payload, Mapping):
        raise ConfirmationProtocolError("confirmation_input_invalid", "Expected an object")
    result = deepcopy(dict(payload))
    if "decisions" in result:
        decisions = result["decisions"]
        if not isinstance(decisions, list) or not decisions:
            raise ConfirmationProtocolError("confirmation_input_invalid", "decisions must be nonempty")
        if "user_confirmation" in result:
            raise ConfirmationProtocolError("confirmation_message_ambiguous", "Provide only one message source")
    else:
        decisions = [result]
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ConfirmationProtocolError("confirmation_input_invalid", "Each decision must be an object")
        if "user_confirmation" in decision:
            raise ConfirmationProtocolError("confirmation_message_ambiguous", "Provide only one message source")
        decision["user_confirmation"] = message
    return result


def reproduce_confirmation_record(
    challenge: Mapping[str, Any], record: Mapping[str, Any],
) -> dict[str, Any]:
    """Recheck persisted decisions using their recorded interpretation contract."""

    payload = {key: record.get(key) for key in ("candidate_fingerprint", "user_confirmation")}
    if record.get("schema_version") == USER_CONFIRMATION_SCHEMA:
        payload["agent_decision"] = record.get("agent_decision")
        return confirmation_record_from_input(challenge, payload)
    raise ConfirmationProtocolError(
        "confirmation_input_invalid", "不支持该确认记录版本",
    )


__all__ = [
    "CONFIRMATION_CHALLENGE_SCHEMA",
    "USER_CONFIRMATION_SCHEMA",
    "ConfirmationProtocolError",
    "confirmation_challenge_for",
    "confirmation_input_schema",
    "confirmation_record_from_input",
    "attach_confirmation_message",
    "reproduce_confirmation_record",
]
