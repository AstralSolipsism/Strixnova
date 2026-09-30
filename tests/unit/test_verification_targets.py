from copy import deepcopy

import pytest

from strixnova.verification_targets import VerificationTargetError, assess_targets, compile_targets, validate_reviews


A = "direction.acceptance:DIRACC-1111111111111111"
B = "direction.acceptance:DIRACC-2222222222222222"
R = "risk_assessments[0]"


def review(target=B, method="agent_review"):
    return {"target_ref": target, "method": method, "reason": "Compare the stated outcome with the observed evidence", "evidence_refs": ["SRC-001"] if method != "not_verified" else []}


def test_passing_a_command_does_not_account_for_an_unplanned_acceptance_or_risk():
    with pytest.raises(VerificationTargetError) as caught:
        validate_reviews([], targets={A, B, R}, commands=[{"covers": [A]}], known_evidence={"SRC-001"})
    assert caught.value.code == "verification_targets_uncovered"
    assert set(caught.value.details) == {B, R}


def test_one_command_can_cover_several_targets_without_duplicate_arrangements():
    commands = [{"command_id": "VC-001", "covers": [A, B, R]}]
    assert validate_reviews([], targets={A, B, R}, commands=commands, known_evidence=set()) == []
    _, summary = assess_targets(compile_targets(commands, []), [], coverage={"results": {"VC-001": "passed"}, "latest_receipt_ids": {"VC-001": "VR-real"}}, known_evidence={"VR-real"}, limitations=[])
    assert summary["status"] == "evidence_recorded"
    assert {row["target_ref"] for row in summary["items"]} == {A, B, R}
    assert all(row["status"] == "command_evidence_passed" for row in summary["items"])
    assert summary["semantic_content_machine_proven"] is False


@pytest.mark.parametrize("method", ["agent_review", "existing_evidence"])
def test_non_command_review_is_recorded_without_a_synthetic_command_receipt(method):
    planned = validate_reviews([review(method=method)], targets={B}, commands=[], known_evidence={"SRC-001"})
    payload = [{"target_ref": B, "outcome": "supported", "rationale": "The exact reviewed source supports this claim", "evidence_refs": ["SRC-001"]}]
    results, summary = assess_targets(compile_targets([], planned), payload, coverage={"latest_receipt_ids": {}, "results": {}}, known_evidence=set(), limitations=[])
    assert results == payload
    assert summary["items"][0]["status"] == "agent_supported"
    assert summary["items"][0]["semantic_judgment"] == "agent"


def test_unverified_target_cannot_be_reported_as_supported_or_lose_its_limitation():
    planned = compile_targets([], [review(method="not_verified")])
    payload = [{"target_ref": B, "outcome": "supported", "rationale": "No execution available", "evidence_refs": []}]
    with pytest.raises(VerificationTargetError):
        assess_targets(planned, payload, coverage={}, known_evidence=set(), limitations=["Unavailable environment"])
    payload[0]["outcome"] = "not_verified"
    with pytest.raises(VerificationTargetError):
        assess_targets(planned, payload, coverage={}, known_evidence=set(), limitations=[])
    _, summary = assess_targets(planned, payload, coverage={}, known_evidence=set(), limitations=["Unavailable environment"])
    assert summary["status"] == "with_gaps"


@pytest.mark.parametrize("change", ["unknown", "duplicate", "already_covered", "unknown_evidence"])
def test_arrangement_identity_and_evidence_are_checked(change):
    entries, commands = [review()], []
    if change == "unknown": entries[0]["target_ref"] = "made-up"
    if change == "duplicate": entries.append(deepcopy(entries[0]))
    if change == "already_covered": commands = [{"covers": [B]}]
    if change == "unknown_evidence": entries[0]["evidence_refs"] = ["unread-file"]
    with pytest.raises(VerificationTargetError):
        validate_reviews(entries, targets={B}, commands=commands, known_evidence={"SRC-001"})


def test_missing_review_result_and_missing_target_plan_are_blocked():
    with pytest.raises(VerificationTargetError) as caught:
        assess_targets(compile_targets([], [review()]), [], coverage={}, known_evidence=set(), limitations=[])
    assert caught.value.code == "verification_target_results_missing"
    with pytest.raises(VerificationTargetError) as missing:
        assess_targets(None, [], coverage={"verification_status": "passed"}, known_evidence=set(), limitations=[])
    assert missing.value.code == "verification_targets_missing"
