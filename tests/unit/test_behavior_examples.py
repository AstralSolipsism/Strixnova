from copy import deepcopy

import pytest

from strixnova.behavior_examples import BehaviorExampleError, example_catalog, example_ids, normalize_behavior
from tests.support.behavior_examples import EXAMPLE, EXAMPLE_REF, direction


def test_example_basis_is_owned_by_its_acceptance_not_the_implementation():
    value = direction()
    catalog = example_catalog(value)
    assert catalog[EXAMPLE_REF]["basis_refs"] == ["direction.requirement:DIRREQ-1111111111111111"]
    value["acceptance"][0]["behavior"]["examples"][0]["basis_refs"] = ["src/implementation.py"]
    with pytest.raises(BehaviorExampleError, match="预期依据"):
        example_catalog(value)


@pytest.mark.parametrize("value", [None, {}, {"applicability": []}, {"applicability": "required", "examples": []}, {"applicability": "not_applicable", "reason": ""}, {"applicability": "not_applicable", "reason": "prose", "examples": []}])
def test_applicability_never_comes_from_missing_fields(value):
    with pytest.raises(BehaviorExampleError):
        normalize_behavior(value)


def test_undetermined_can_be_a_draft_but_not_a_confirmable_direction():
    value = {"applicability": "undetermined", "reason": "An owner decision remains"}
    assert normalize_behavior(value, allow_undetermined=True) == value
    with pytest.raises(BehaviorExampleError) as caught:
        normalize_behavior(value)
    assert caught.value.code == "behavior_examples_undetermined"


def test_examples_follow_meaning_bearing_sources_not_workflow_progress():
    value = direction()
    initial = example_catalog(value)[EXAMPLE_REF]["example_sha256"]
    value["progress"] = {"completed_slice": "slice-2"}
    assert example_catalog(value)[EXAMPLE_REF]["example_sha256"] == initial
    value["scope"][0]["statement"] = "Allow a supervisor to withdraw any receiver"
    assert example_catalog(value)[EXAMPLE_REF]["example_sha256"] != initial
    assert example_ids(value) == {EXAMPLE}


def test_example_identity_cannot_be_reused_under_another_acceptance():
    value = direction()
    extra = deepcopy(value["acceptance"][0])
    extra["acceptance_id"] = "DIRACC-5555555555555555"
    value["acceptance"].append(extra)
    with pytest.raises(BehaviorExampleError) as caught:
        example_catalog(value)
    assert caught.value.code == "behavior_example_duplicate"


def test_unknown_direction_is_rejected_without_mutating_input():
    value = direction()
    value["schema_version"] = "strixnova.direction-decision.v999"
    del value["acceptance"][0]["behavior"]
    original = deepcopy(value)
    with pytest.raises(BehaviorExampleError) as caught:
        example_catalog(value)
    assert caught.value.code == "direction_contract_invalid"
    assert value == original


def test_confirmed_example_retirement_is_preserved_across_revisions(tmp_path):
    from strixnova.workflow_authority import InvalidTransition, WorkflowAuthority

    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="Example history", raw_request="Keep the original receiver rule")
    original = direction()

    def submit_and_confirm(item, value, *, first=False):
        item = authority.transition(
            item["work_item_id"], "submit_direction" if first else "revise_direction",
            {"direction": value, "ready_for_confirmation": True, **({} if first else {"invalidation_issues": ["The expected example has changed."]})},
            expected_version=item["version"],
        )
        challenge = authority.get(item["work_item_id"])["current_action"]["confirmation_challenge"]
        return authority.transition(
            item["work_item_id"], "confirm_direction",
            {"candidate_fingerprint": challenge["candidate_fingerprint"], "user_confirmation": "Accept this candidate.", "agent_decision": {"decision": "accept", "reason": "The fixture owner accepted this exact revision."}},
            expected_version=item["version"],
        )

    item = submit_and_confirm(item, original, first=True)
    updated = deepcopy(original)
    updated["acceptance"][0]["behavior"]["examples"][0]["example_id"] = "DIREX-6666666666666666"
    item = submit_and_confirm(item, updated)
    history = authority.history(item["work_item_id"])
    with pytest.raises(InvalidTransition) as error:
        authority.transition(
            item["work_item_id"], "revise_direction",
            {"direction": original, "ready_for_confirmation": True, "invalidation_issues": ["Attempting to revive a retired example."]},
            expected_version=item["version"],
        )
    assert error.value.code == "direction_item_reused"
    assert authority.history(item["work_item_id"]) == history
