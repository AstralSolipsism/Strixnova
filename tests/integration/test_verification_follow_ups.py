"""Public CLI flow for review-only evidence and an accepted deferred issue."""

import json
from pathlib import Path

from click.testing import CliRunner

from strixnova.cli import main
from tests.support.governance_assessment import direction_fixture, exploration_assessment


def test_public_review_and_deferred_issue_flow_without_fake_test_commands(tmp_path: Path):
    runner = CliRunner()

    def call(command, *arguments):
        response = runner.invoke(main, [command, "--project-dir", str(tmp_path), *arguments])
        assert response.exit_code == 0, response.output
        return json.loads(response.output)

    def write(command, current, payload):
        from tests.support.review_subject import bind_subject
        payload = bind_subject(tmp_path, current["work_item_id"], payload)
        return call(command, "--work-item-id", current["work_item_id"], "--version", str(current["work_item_version"]), "--input", json.dumps(payload))["next"]

    def accept(current):
        challenge = current["current_action"]["confirmation_challenge"]
        return write("confirm", current, {"candidate_fingerprint": challenge["candidate_fingerprint"], "user_confirmation": "I accept the explained candidate", "agent_decision": {"decision": "accept", "reason": "Explicit synthetic owner decision for this candidate"}})

    def begin(ref=None):
        current = call("intake", "--input", json.dumps({"title": "Review the explicit issue", "request": "Read and explain the relevant evidence"}))["next"]
        direction = direction_fixture()
        if ref:
            direction["work_item_relations"] = [{"target_work_item_id": ref["work_item_id"], "relation_type": "follows_up", "reason": "Review this original issue", "follow_up_refs": [ref]}]
        current = write("submit", current, {"direction": direction, "ready_for_confirmation": True, "blockers": []})
        current = accept(current)
        assessment = exploration_assessment(tmp_path)
        assessment["direction_ref"] = {"work_item_id": current["work_item_id"], "direction_version": current["work_item_version"]}
        missing = {**assessment, "verification_reviews": assessment["verification_reviews"][:1]}
        rejected = runner.invoke(main, ["submit", "--project-dir", str(tmp_path), "--work-item-id", current["work_item_id"], "--version", str(current["work_item_version"]), "--input", json.dumps(missing)])
        assert rejected.exit_code != 0
        assert json.loads(rejected.output)["ok"] is False
        assert call("next", "--work-item-id", current["work_item_id"])["next"]["work_item_version"] == current["work_item_version"]
        current = write("submit", current, assessment)
        return accept(current), assessment

    def result(assessment):
        return {"schema_version": "strixnova.actual-result.v1", "effect_summary": "Reviewed the original sources", "delivered_outcomes": ["The reviewed evidence supports the stated observations"], "deviations": [], "limitations": ["The capacity limit still needs explicit disposition"], "verification_receipt_ids": [], "long_lived_refs": [], "method_application_results": [], "governance_rule_results": [], "verification_review_results": [{"target_ref": item["target_ref"], "outcome": "supported", "rationale": "Compared the observed source with the promised result", "evidence_refs": ["direction"]} for item in assessment["verification_reviews"]], "semantic_content_machine_proven": False}

    parent, assessment = begin()
    parent_id = parent["work_item_id"]
    from tests.support.review_subject import bind_subject
    reviewed = bind_subject(tmp_path, parent_id, result(assessment))
    (tmp_path / "reviewed-note.md").write_text("The evidence changed after review.\n", encoding="utf-8")
    stale = runner.invoke(main, ["delivery", "--project-dir", str(tmp_path), "--work-item-id", parent_id,
                                "--version", str(parent["work_item_version"]), "--input", json.dumps(reviewed)])
    assert stale.exit_code != 0
    assert json.loads(stale.output)["error"]["code"] == "review_subject_changed"
    assert call("next", "--work-item-id", parent_id)["next"]["work_item_version"] == parent["work_item_version"]
    payload = result(assessment)
    payload["follow_up_items"] = [{"follow_up_id": "FOLLOWUP-ABCDEF0123456789", "limitation_refs": ["limitations[0]"], "disposition": "deferred", "reason": "Review before the next capacity increase", "responsible_party": "project maintainer", "due_on": None, "review_condition": "Before the next capacity increase", "completion_criteria": "Review measurements and record whether the original limit is resolved"}]
    parent = write("delivery", parent, payload)
    assert call("status", "--follow-ups")["follow_ups"]["total"] == 0
    accept(parent)
    record = call("status", "--follow-ups")["follow_ups"]["items"][0]
    assert record["follow_up_ref"]["work_item_id"] == parent_id

    child, assessment = begin(record["follow_up_ref"])
    payload = result(assessment)
    payload["follow_up_results"] = [{"follow_up_ref": record["follow_up_ref"], "expected_version": record["version"], "outcome": "resolved", "rationale": "The follow-up review explicitly resolves the original finding", "evidence_refs": ["delivered_outcomes[0]"], "limitation_refs": []}]
    child = write("delivery", child, payload)
    assert call("status", "--follow-ups")["follow_ups"]["total"] == 1
    accept(child)
    assert call("status", "--follow-ups")["follow_ups"]["total"] == 0
    resolved = call("status", "--follow-ups", "--include-closed")["follow_ups"]["items"][0]
    assert resolved["state"] == "resolved"
    assert resolved["latest_resolution"]["work_item_id"] == child["work_item_id"]
