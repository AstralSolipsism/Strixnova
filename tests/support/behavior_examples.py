"""Small declared behavior fixtures independent of this repository's current state."""

from copy import deepcopy

from strixnova.behavior_examples import example_catalog


REQUIREMENT = "DIRREQ-1111111111111111"
ACCEPTANCE = "DIRACC-3333333333333333"
EXAMPLE = "DIREX-4444444444444444"
EXAMPLE_REF = f"direction.example:{EXAMPLE}"
PARENT_REF = f"direction.acceptance:{ACCEPTANCE}"


def behavior():
    return {"applicability": "required", "examples": [{
        "example_id": EXAMPLE, "title": "Withdraw only the acting receiver",
        "given": ["Lee and Chen have received the item"], "when": "Lee withdraws",
        "then": ["Chen's receipt remains"], "basis_refs": [f"direction.requirement:{REQUIREMENT}"],
    }]}


def direction():
    return {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
        "goal": "Correct a mistaken receipt without changing another receiver",
        "scope": [{"requirement_id": REQUIREMENT, "statement": "Withdraw only the acting receiver"}],
        "constraints": [], "non_goals": ["Transfer responsibility"], "tradeoffs": [],
        "acceptance": [{"acceptance_id": ACCEPTANCE, "statement": "Other receivers remain after withdrawal", "requirement_refs": [REQUIREMENT], "behavior": behavior()}],
    }


def case_config(test_ids, *, input_paths=None, bound=True):
    value = {
        "adapter": "pytest", "test_root": ".",
        "input_paths": list(input_paths or ["test_behavior.py"]),
        "bindings": [{"example_ref": EXAMPLE_REF, "test_ids": list(test_ids)}],
    }
    if bound:
        value["example_fingerprints"] = {EXAMPLE_REF: example_catalog(direction())[EXAMPLE_REF]["example_sha256"]}
    return deepcopy(value)
