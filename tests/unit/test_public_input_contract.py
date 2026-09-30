from __future__ import annotations

from importlib.resources import files
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator
import pytest

from strixnova.public_input_contract import (
    PublicInputContractError,
    input_contract_for,
)


ACTION_INPUTS = {
    "submit_direction": ("direction", "submit"),
    "revise_direction": ("direction", "submit"),
    "confirm_direction": ("direction_confirmation", "confirm"),
    "submit_engineering_assessment": ("engineering_assessment", "submit"),
    "confirm_engineering_plan": ("engineering_plan_confirmation", "confirm"),
    "begin_implementation": ("begin_implementation", "delivery"),
    "author_project_authority_candidate": (
        "project_authority_candidate",
        "authority",
    ),
    "confirm_project_authority_candidates": (
        "project_authority_confirmation_bundle",
        "authority",
    ),
    "investigate_and_report": ("actual_result", "delivery"),
    "implement_and_verify": ("verification", "verify"),
    "assess_verification_change": ("verification_assessment", "verify"),
    "present_actual_result": ("actual_result", "delivery"),
    "confirm_actual_result": ("actual_result_confirmation", "confirm"),
    "create_atomic_commits": ("commit_and_integrate", "delivery"),
    "integrate_target": ("integrate", "delivery"),
    "resolve_git_conflict": ("conflict_resolution", "submit"),
    "verify_after_git_conflict": ("conflict_retest", "verify"),
    "complete_git_merge": ("complete_merge", "delivery"),
    "cleanup_work_area": ("cleanup", "delivery"),
    "revise_engineering_plan": ("replan", "submit"),
    "decide_cancelled_work": ("cancellation_decision", "cancel"),
    "assess_target_advance": ("target_advance_assessment", "submit"),
    "resume_integrate": ("resume_external_effect", "delivery"),
    "resume_cleanup": ("resume_external_effect", "delivery"),
    "resume_cancel_cleanup": ("resume_external_effect", "cancel"),
    "resume_cancel_discard": ("resume_external_effect", "cancel"),
}


PACKAGED_SKILL_ROOT = (
    Path(__file__).parents[2]
    / "strixnova"
    / "src"
    / "strixnova"
    / "resources"
    / "agent-skill"
    / "strixnova"
)


INPUT_GUIDANCE = {
    "direction": {"references/direction.md"},
    "direction_confirmation": {"references/confirmation-and-cancel.md"},
    "engineering_assessment": {"references/engineering-assessment.md"},
    "engineering_plan_confirmation": {
        "references/confirmation-and-cancel.md"
    },
    "begin_implementation": {"references/delivery.md"},
    "project_authority_candidate": {"references/authority-authoring.md"},
    "project_authority_confirmation_bundle": {
        "references/confirmation-and-cancel.md",
    },
    "actual_result": {"references/delivery.md"},
    "verification": {"references/verification.md"},
    "verification_assessment": {"references/verification.md"},
    "actual_result_confirmation": {
        "references/confirmation-and-cancel.md"
    },
    "commit_and_integrate": {"references/delivery.md"},
    "integrate": {"references/delivery.md"},
    "conflict_resolution": {"references/replanning.md"},
    "conflict_retest": {"references/verification.md"},
    "complete_merge": {"references/delivery.md"},
    "cleanup": {"references/delivery.md"},
    "replan": {"references/replanning.md"},
    "cancellation_decision": {"references/confirmation-and-cancel.md"},
    "target_advance_assessment": {"references/replanning.md"},
    "resume_external_effect": {
        "references/replanning.md#resume-a-recorded-effect",
    },
}


def _public_input_routes() -> list[str]:
    skill_text = (PACKAGED_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    section = skill_text.split("## Follow the public input contract", 1)[1]
    section = section.split("\n## ", 1)[0]
    routes: list[str] = []
    current: list[str] = []
    for line in section.splitlines():
        if line.startswith("| ") and "`" in line.split("|")[1]:
            if current:
                routes.append(" ".join(current))
                current = []
            routes.append(line)
        elif line.startswith("- "):
            if current:
                routes.append(" ".join(current))
            current = [line[2:].strip()]
        elif current:
            current.append(line.strip())
    if current:
        routes.append(" ".join(current))
    return routes


def _action(action_type: str, input_kind: str, intent: str) -> dict:
    action = {
        "action_type": action_type,
        "input_kind": input_kind,
        "intent": intent,
        "input_contract_ref": f"input.contract:{action_type}",
    }
    if action_type == "confirm_project_authority_candidates":
        decision_label = "当前展示的产品定义候选"
        action["authority_kinds"] = ["product_definition"]
        action["confirmation_challenges"] = [
            {
                "schema_version": "strixnova.confirmation-challenge.v1",
                "candidate_kind": "project_authority:product_definition",
                "candidate_fingerprint": f"sha256:{'0' * 64}",
                "decision_label": decision_label,
                "decision_interpreter": "coding_agent",
            }
        ]
    if intent == "confirm":
        labels = {
            "confirm_direction": ("direction", "当前展示的方向"),
            "confirm_engineering_plan": (
                "engineering_plan",
                "当前展示的工程方案",
            ),
            "confirm_actual_result": (
                "actual_result",
                "当前展示的实际结果",
            ),
        }
        candidate_kind, decision_label = labels[action_type]
        action["confirmation_challenge"] = {
            "schema_version": "strixnova.confirmation-challenge.v1",
            "candidate_kind": candidate_kind,
            "candidate_fingerprint": f"sha256:{'0' * 64}",
            "decision_label": decision_label,
            "decision_interpreter": "coding_agent",
        }
    return action


def test_every_current_input_kind_has_one_direct_guidance_route() -> None:
    public_input_kinds = {input_kind for input_kind, _ in ACTION_INPUTS.values()}
    routes = _public_input_routes()

    assert public_input_kinds == set(INPUT_GUIDANCE)
    for input_kind, references in INPUT_GUIDANCE.items():
        matches = [item for item in routes if f"`{input_kind}`" in item]
        assert len(matches) == 1, input_kind
        for reference in references:
            assert f"]({reference})" in matches[0], input_kind
            path, _, anchor = reference.partition("#")
            target = (PACKAGED_SKILL_ROOT / path).read_text(encoding="utf-8")
            if anchor:
                headings = re.findall(r"^#+ (.+)$", target, re.MULTILINE)
                assert anchor in {heading.lower().replace(" ", "-") for heading in headings}

    resume_route = next(
        item for item in routes if "`resume_external_effect`" in item
    )
    assert "`verify`" in resume_route
    assert "`delivery`" in resume_route
    assert "`cancel`" in resume_route


@pytest.mark.parametrize(
    ("action_type", "input_kind", "intent"),
    [
        (action_type, input_kind, intent)
        for action_type, (input_kind, intent) in ACTION_INPUTS.items()
    ],
)
def test_every_public_current_action_has_a_valid_progressive_input_contract(
    action_type: str,
    input_kind: str,
    intent: str,
) -> None:
    contract = input_contract_for(_action(action_type, input_kind, intent))
    contract_schema = json.loads(
        files("strixnova.resources")
        .joinpath("input-contract-v1.schema.json")
        .read_text(encoding="utf-8")
    )

    Draft202012Validator(contract_schema).validate(contract)
    Draft202012Validator.check_schema(contract["payload_schema"])
    assert contract["contract_ref"] == f"input.contract:{action_type}"
    assert contract["command"] == (
        "authority"
        if action_type
        in {
            "author_project_authority_candidate",
            "confirm_project_authority_candidates",
        }
        else intent
    )
    assert contract["instructions"]


@pytest.mark.parametrize(
    ("action_type", "input_kind"),
    [
        ("confirm_direction", "direction_confirmation"),
        ("confirm_engineering_plan", "engineering_plan_confirmation"),
        ("confirm_actual_result", "actual_result_confirmation"),
    ],
)
def test_confirmation_contract_requires_a_later_user_message_after_presentation(
    action_type: str,
    input_kind: str,
) -> None:
    contract = input_contract_for(_action(action_type, input_kind, "confirm"))
    schema = contract["payload_schema"]
    validator = Draft202012Validator(schema)
    challenge = _action(action_type, input_kind, "confirm")[
        "confirmation_challenge"
    ]
    validator.validate(
        {
            "candidate_fingerprint": challenge["candidate_fingerprint"],
            "user_confirmation": "I accept the displayed candidate.",
            "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
        }
    )
    assert not validator.is_valid(
        {"accepted": True, "summary": "把方案选择误当成确认"}
    )
    assert not validator.is_valid(
        {
            "candidate_fingerprint": challenge["candidate_fingerprint"],
            "user_confirmation": "选择第 1 种推荐方案",
        }
    )


@pytest.mark.parametrize(
    ("action_type", "input_kind", "boundary_text"),
    [
        ("confirm_direction", "direction_confirmation", "不授权修改源码"),
        (
            "confirm_engineering_plan",
            "engineering_plan_confirmation",
            "本地实施并验证",
        ),
        (
            "confirm_actual_result",
            "actual_result_confirmation",
            "组织本地 Git 提交、合入和清理",
        ),
    ],
)
def test_confirmation_contract_guides_decision_ready_explanation_without_system_fields(
    action_type: str,
    input_kind: str,
    boundary_text: str,
) -> None:
    contract = input_contract_for(_action(action_type, input_kind, "confirm"))
    instructions = "\n".join(contract["instructions"])

    assert "当前状态与问题" in instructions
    assert "产品与用户效果" in instructions
    assert "推荐结论" in instructions
    assert boundary_text in instructions
    assert "不要求固定口令或修改前缀" in instructions
    assert "用户不填写这些内部字段" in instructions
    assert "用户表示没看懂或继续提问" in instructions
    assert "不得改变候选、事项版本或确认绑定" in instructions
    assert "不判断用户意图" in instructions


def test_actual_result_contract_requires_the_previously_observed_review_subject() -> None:
    contract = input_contract_for(_action("present_actual_result", "actual_result", "delivery"))
    assert "review_subject_ref" in contract["payload_schema"]["required"]
    assert any(route["trigger_code"] == "review_subject_changed" for route in contract["recovery_routes"])


def test_actual_result_contract_exposes_plan_drift_recovery() -> None:
    contract = input_contract_for(
        _action("present_actual_result", "actual_result", "delivery")
    )
    assert contract["payload_schema"]["$id"] == "strixnova.actual-result.v1"
    assert "replan-request-v1.schema.json" in contract["referenced_schemas"]
    assert contract["recovery_routes"][0]["trigger_code"] == (
        "unplanned_repository_change"
    )
    assert contract["recovery_routes"][0]["command"] == "submit"
    assert contract["recovery_routes"][0]["payload_schema"] == {
        "$ref": "replan-request-v1.schema.json"
    }


def test_direction_revision_reuses_the_direction_shape_after_context_drift() -> None:
    contract = input_contract_for(
        _action("revise_direction", "direction", "submit")
    )

    assert contract["payload_schema"]["$id"] == (
        "strixnova.direction-submission.v1"
    )
    assert "direction-decision-v1.schema.json" in contract["referenced_schemas"]
    assert contract["command"] == "submit"


def test_contract_reference_must_match_the_exact_current_action() -> None:
    action = _action("submit_direction", "direction", "submit")
    action["input_contract_ref"] = "input.contract:confirm_direction"

    with pytest.raises(PublicInputContractError):
        input_contract_for(action)
