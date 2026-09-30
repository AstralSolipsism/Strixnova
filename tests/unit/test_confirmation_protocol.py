from __future__ import annotations

from jsonschema import Draft202012Validator
import pytest

from strixnova.confirmation_protocol import (
    ConfirmationProtocolError, confirmation_challenge_for,
    confirmation_input_schema, confirmation_record_from_input,
    reproduce_confirmation_record,
)


def _challenge(*, version: int = 2, goal: str = "建设能力") -> dict:
    return confirmation_challenge_for(
        action_type="confirm_direction", work_item_id="WI-CONFIRMATION",
        work_item_version=version,
        data={"direction": {"goal": goal, "scope": ["本地改动"]}},
    )


def _reply(challenge: dict, decision: str = "accept") -> dict:
    return {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "  认同这个方案，按这个做。\n",
        "agent_decision": {"decision": decision, "reason": "The Agent interpreted the later reply against this candidate."},
    }


def test_challenge_binds_candidate_and_version_without_a_password() -> None:
    original = _challenge()
    assert _challenge() == original
    assert _challenge(goal="另一个能力")["candidate_fingerprint"] != original["candidate_fingerprint"]
    assert _challenge(version=3)["candidate_fingerprint"] != original["candidate_fingerprint"]
    assert original["decision_label"] == "当前展示的方向"
    assert original["decision_interpreter"] == "coding_agent"
    assert "accept_text" not in original
    assert "reject_text_prefix" not in original


@pytest.mark.parametrize("decision", ["accept", "request_changes"])
def test_explicit_agent_decision_preserves_full_original_message(decision: str) -> None:
    challenge = _challenge()
    payload = _reply(challenge, decision)
    assert Draft202012Validator(confirmation_input_schema(challenge)).is_valid(payload)
    record = confirmation_record_from_input(challenge, payload)
    assert record["accepted"] is (decision == "accept")
    assert record["user_confirmation"] == payload["user_confirmation"]
    assert record["agent_decision"] == payload["agent_decision"]
    assert record["semantic_content_machine_proven"] is False
    assert reproduce_confirmation_record(challenge, record) == record


@pytest.mark.parametrize("field,value", [
    ("user_confirmation", " \n"), ("agent_decision", None),
    ("agent_decision", {"decision": "unclear", "reason": "Needs explanation"}),
    ("agent_decision", {"decision": "accept", "reason": " "}),
    ("agent_decision", {"decision": "accept", "reason": "yes", "extra": True}),
])
def test_incomplete_or_undecided_input_cannot_advance(field: str, value: object) -> None:
    challenge = _challenge()
    payload = _reply(challenge)
    payload[field] = value
    assert not Draft202012Validator(confirmation_input_schema(challenge)).is_valid(payload)
    with pytest.raises(ConfirmationProtocolError) as error:
        confirmation_record_from_input(challenge, payload)
    assert error.value.code == "confirmation_input_invalid"


def test_raw_reply_alone_cannot_advance() -> None:
    challenge = _challenge()
    payload = _reply(challenge)
    del payload["agent_decision"]
    assert not Draft202012Validator(confirmation_input_schema(challenge)).is_valid(payload)
    with pytest.raises(ConfirmationProtocolError):
        confirmation_record_from_input(challenge, payload)


def test_stale_candidate_is_rejected() -> None:
    payload = _reply(_challenge(version=2))
    challenge = _challenge(version=3)
    assert not Draft202012Validator(confirmation_input_schema(challenge)).is_valid(payload)
    with pytest.raises(ConfirmationProtocolError) as error:
        confirmation_record_from_input(challenge, payload)
    assert error.value.code == "confirmation_candidate_mismatch"


def test_unrecognized_stored_confirmation_is_rejected() -> None:
    challenge = _challenge()
    record = confirmation_record_from_input(challenge, _reply(challenge))
    record["schema_version"] = "strixnova.user-confirmation.v999"
    with pytest.raises(ConfirmationProtocolError) as caught:
        reproduce_confirmation_record(challenge, record)
    assert caught.value.code == "confirmation_input_invalid"


def test_supplied_raw_message_expands_only_explicit_decisions():
    from strixnova.confirmation_protocol import attach_confirmation_message
    from copy import deepcopy
    raw = "  同意第一项。\r\n第二项先修改，条件见下文。\r\n  "
    a = _reply(_challenge())
    b = _reply(_challenge(version=3), "request_changes")
    for value in (a, b):
        del value["user_confirmation"]
    payload = {"decisions": [a, b]}
    before = deepcopy(payload)
    result = attach_confirmation_message(payload, raw)
    assert payload == before
    for index, version in enumerate((2, 3)):
        record = confirmation_record_from_input(_challenge(version=version), result["decisions"][index])
        assert record["user_confirmation"].encode("utf-8") == raw.encode("utf-8")
        assert record["agent_decision"] == payload["decisions"][index]["agent_decision"]
    assert result["decisions"][1]["agent_decision"]["decision"] == "request_changes"


def test_raw_message_source_does_not_supply_decision_or_rebind_candidate():
    from strixnova.confirmation_protocol import attach_confirmation_message
    payload = {"candidate_fingerprint": _challenge()["candidate_fingerprint"]}
    assembled = attach_confirmation_message(payload, "同意")
    with pytest.raises(ConfirmationProtocolError):
        confirmation_record_from_input(_challenge(), assembled)
    assembled["agent_decision"] = {"decision": "accept", "reason": "Explicit interpretation"}
    with pytest.raises(ConfirmationProtocolError, match="精确候选"):
        confirmation_record_from_input(_challenge(version=3), assembled)


def test_multiple_message_sources_are_rejected():
    from strixnova.confirmation_protocol import attach_confirmation_message
    with pytest.raises(ConfirmationProtocolError) as caught:
        attach_confirmation_message(_reply(_challenge()), "a second source")
    assert caught.value.code == "confirmation_message_ambiguous"
