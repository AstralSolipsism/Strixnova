import json
from pathlib import Path
import sys

from click.testing import CliRunner
import pytest

from strixnova.cli import main
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.review_subject import bind_subject
from tests.support.behavior_examples import EXAMPLE_REF, PARENT_REF, case_config, direction
from tests.support.governance_assessment import exploration_assessment, satisfied_governance_rule_results


def invoke(runner, project, command, *, item=None, payload=None, extra=(), success=True):
    args = [command, "--project-dir", str(project)]
    if item is not None:
        args += ["--work-item-id", item["work_item_id"]]
        if command not in {"next", "history", "status"}:
            args += ["--version", str(item["work_item_version"])]
    if payload is not None:
        if item is not None:
            payload = bind_subject(project, item["work_item_id"], payload)
        args += ["--input", json.dumps(payload)]
    args += list(extra)
    response = runner.invoke(main, args)
    assert (response.exit_code == 0) is success, response.output
    return json.loads(response.output)


def accept(runner, project, item):
    challenge = item["current_action"]["confirmation_challenge"]
    return invoke(runner, project, "confirm", item=item, payload={
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "I accept this exact displayed candidate.",
        "agent_decision": {"decision": "accept", "reason": "The owner accepted this candidate without changes."},
    })["next"]


def prepared(runner, project, *, skipped=False):
    (project / "business.py").write_text("def withdraw(receivers, actor):\n    return [value for value in receivers if value != actor]\n", encoding="utf-8")
    test = "from business import withdraw\n"
    if skipped:
        test += "import pytest\n@pytest.mark.skip(reason='deliberately not exercised')\n"
    test += "def test_other_remains():\n    assert withdraw(['Lee', 'Chen'], 'Lee') == ['Chen']\n"
    (project / "test_behavior.py").write_text(test, encoding="utf-8")
    (project / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    current = invoke(runner, project, "intake", payload={"title": "Check withdrawal behavior", "request": "Verify the declared receiver example against this isolated implementation."})["next"]
    current = invoke(runner, project, "submit", item=current, payload={"direction": direction(), "ready_for_confirmation": True})["next"]
    current = accept(runner, project, current)
    assessment = exploration_assessment(project)
    assessment["direction_ref"] = {"work_item_id": current["work_item_id"], "direction_version": current["work_item_version"]}
    assessment.pop("verification_not_required_reason")
    assessment["verification_reviews"] = []
    assessment["verification_commands"] = [{
        "argv": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_behavior.py"],
        "cwd": ".", "run_kind": "acceptance_test", "covers": [PARENT_REF],
        "reason": "Observe withdrawal through the real public function.",
        "case_report": case_config(["test_behavior.py::test_other_remains"], input_paths=["business.py", "test_behavior.py", "pytest.ini"], bound=False),
    }]
    current = invoke(runner, project, "submit", item=current, payload=assessment)["next"]
    current = accept(runner, project, current)
    assert current["current_action"]["intent"] == "verify"
    response = invoke(runner, project, "verify", item=current, payload={"command_id": "VC-001", "mode": "run", "limitations": []})
    current = response["next"]
    receipt = WorkflowAuthority(project).get(current["work_item_id"])["data"]["verifications"][-1]
    current = invoke(runner, project, "verify", item=current, payload={
        "command_id": "VC-001", "mode": "assess", "receipt_id": receipt["receipt_id"],
        "code_change_assessment": {"changed_after": False, "needs_retest": False, "rationale": "The declared source and test inputs are unchanged."},
    })["next"]
    return current, receipt


@pytest.mark.parametrize("skipped", [False, True])
def test_public_example_to_report_result_and_historical_artifact(tmp_path, skipped):
    runner = CliRunner()
    current, receipt = prepared(runner, tmp_path, skipped=skipped)
    assert current["current_action"]["input_kind"] == "actual_result"
    data = WorkflowAuthority(tmp_path).get(current["work_item_id"])["data"]
    plan = data["engineering"]["plan"]
    payload = {
        "schema_version": "strixnova.actual-result.v1", "effect_summary": "Observed the declared withdrawal example.",
        "delivered_outcomes": ["Recorded execution and assertion review separately."],
        "deviations": [], "limitations": [], "verification_receipt_ids": [receipt["receipt_id"]],
        "long_lived_refs": [], "method_application_results": [],
        "governance_rule_results": satisfied_governance_rule_results(plan, receipt["receipt_id"]),
        "verification_review_results": [{"target_ref": EXAMPLE_REF, "outcome": "supported", "rationale": "The assertion compares the remaining receiver with the independently stated requirement.", "evidence_refs": [receipt["receipt_id"]]}],
        "semantic_content_machine_proven": False,
    }
    if skipped:
        failure = invoke(runner, tmp_path, "delivery", item=current, payload=payload, success=False)
        assert failure["error"]["code"] == "verification_target_invalid"
        payload["limitations"] = ["The example test was skipped, so execution does not support its behavior."]
    current = invoke(runner, tmp_path, "delivery", item=current, payload=payload)["next"]
    current = accept(runner, tmp_path, current)
    result = WorkflowAuthority(tmp_path).get(current["work_item_id"])["data"]["actual_result"]
    assert result["target_verification"]["status"] == ("with_gaps" if skipped else "evidence_recorded")
    assert result["target_verification"]["semantic_content_machine_proven"] is False
    receipt_view = invoke(runner, tmp_path, "history", item=current, extra=["--record", f"verification:{receipt['receipt_id']}"])
    output_refs = receipt_view["history"]["records"][f"verification:{receipt['receipt_id']}"]["output_record_refs"]
    assert f"output:{receipt['receipt_id']}:cases" in output_refs
    history = invoke(runner, tmp_path, "history", item=current, extra=["--record", output_refs[-1]])
    report = history["history"]["records"][f"output:{receipt['receipt_id']}:cases"]
    assert report["availability"] == "available"
    assert "strixnova.test-case-report.v1" in report["text"]
    original = Path(receipt["case_evidence"]["report_ref"])
    original.write_text("replaced report", encoding="utf-8")
    changed = invoke(runner, tmp_path, "history", item=current, extra=["--record", f"output:{receipt['receipt_id']}:cases"])
    assert changed["history"]["records"][f"output:{receipt['receipt_id']}:cases"]["availability"] == "hash_mismatch"
    original.unlink()
    missing = invoke(runner, tmp_path, "history", item=current, extra=["--record", f"output:{receipt['receipt_id']}:cases"])
    assert missing["history"]["records"][f"output:{receipt['receipt_id']}:cases"]["availability"] == "missing"
    assert WorkflowAuthority(tmp_path).get(current["work_item_id"])["data"]["actual_result"] == result


def test_changed_uncommitted_input_returns_to_verification_without_reconfirming_direction(tmp_path):
    runner = CliRunner()
    current, old_receipt = prepared(runner, tmp_path)
    (tmp_path / "business.py").write_text("def withdraw(receivers, actor):\n    return [value for value in receivers if value != actor]\n# a new uncommitted input snapshot\n", encoding="utf-8")
    next_step = invoke(runner, tmp_path, "next", item=current)["next"]
    assert next_step["current_action"]["intent"] == "verify"
    response = invoke(runner, tmp_path, "verify", item=next_step, payload={"command_id": "VC-001", "mode": "run", "limitations": []})
    item = WorkflowAuthority(tmp_path).get(current["work_item_id"])
    assert len(item["data"]["verifications"]) == 2
    assert item["data"]["verifications"][0]["receipt_id"] == old_receipt["receipt_id"]
    assert item["data"]["direction_confirmation"]["accepted"] is True
    assert response["next"]["current_action"]["input_kind"] == "verification_assessment"


def test_case_report_is_preserved_by_maintenance_backup_and_restore(tmp_path):
    from strixnova.runtime_upgrade import RuntimeUpgrade
    runner = CliRunner()
    current, receipt = prepared(runner, tmp_path)
    original = Path(receipt["case_evidence"]["report_ref"]).read_bytes()
    upgrade = RuntimeUpgrade(tmp_path)
    finished = upgrade.apply(upgrade.check())
    assert finished["state"] == "completed"
    assert finished["business_records_preserved"] is True
    backups = list(Path(finished["backup_directory"]).rglob(f"{receipt['receipt_id']}.cases.json"))
    assert len(backups) == 1
    assert backups[0].read_bytes() == original
    restored = upgrade.recover(finished["upgrade_id"], mode="restore")
    assert restored["state"] == "restored"
    response = invoke(runner, tmp_path, "history", item=current, extra=["--record", f"output:{receipt['receipt_id']}:cases"])
    assert response["history"]["records"][f"output:{receipt['receipt_id']}:cases"]["availability"] == "available"
    assert Path(receipt["case_evidence"]["report_ref"]).read_bytes() == original
