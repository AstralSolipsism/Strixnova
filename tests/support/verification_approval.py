from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from strixnova.verification_runner import APPROVED_VERIFICATION_REQUEST_SCHEMA


FORBIDDEN_AGENT_PROGRAM_NAMES = [
    "agy",
    "aider",
    "claude",
    "codex",
    "cursor",
    "gemini",
    "opencode",
    "windsurf",
]


def approved_verification_request(
    command: Mapping[str, Any],
    *,
    work_item_id: str,
    work_item_version: int = 1,
    plan_id: str | None = None,
) -> dict[str, Any]:
    selected = deepcopy(dict(command))
    selected["approved_program"] = {
        "declared_program": str(selected["argv"][0]),
        "resolved_program": str(selected["argv"][0]),
        "purpose": "执行测试明确批准的精确验证命令。",
        "argument_policy": "exact_plan_only",
    }
    exact_plan_id = plan_id or f"PLAN-{work_item_id}"
    return {
        "schema_version": APPROVED_VERIFICATION_REQUEST_SCHEMA,
        "work_item_id": work_item_id,
        "work_item_version": work_item_version,
        "plan_id": exact_plan_id,
        "plan_confirmation": {
            "plan_id": exact_plan_id,
            "accepted": True,
        },
        "policy_decision": {
            "schema_version": "strixnova.verification-policy-decision.v1",
            "source_kind": "confirmed_plan_bootstrap",
            "policy_id": "test.confirmed-plan-policy",
            "policy_revision_id": "1",
            "observed_commit": None,
            "forbidden_agent_program_names": list(
                FORBIDDEN_AGENT_PROGRAM_NAMES
            ),
            "wrapper_policy": "forbidden_unless_exactly_approved",
            "working_directory_policy": "project_or_authorized_worktree_only",
            "plan_binding_required": True,
        },
        "command": selected,
    }


def approval_expectations(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "expected_work_item_id": str(request["work_item_id"]),
        "expected_work_item_version": int(request["work_item_version"]),
        "expected_plan_id": str(request["plan_id"]),
    }
