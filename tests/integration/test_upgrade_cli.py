from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from click.testing import CliRunner

from strixnova.cli import main
from tests.support.history_records import ITEM_ID, write_history



def test_public_upgrade_precheck_apply_status_and_history(tmp_path: Path) -> None:
    write_history(tmp_path)
    runner = CliRunner()
    checked = runner.invoke(main, ["upgrade", "check", "--project-dir", str(tmp_path)])
    assert checked.exit_code == 0, checked.output
    plan = json.loads(checked.output)["upgrade"]
    assert plan["writes_performed"] is False
    assert "assets" not in plan
    applied = runner.invoke(main, ["upgrade", "apply", "--project-dir", str(tmp_path), "--input", json.dumps(plan)])
    assert applied.exit_code == 0, applied.output
    result = json.loads(applied.output)["upgrade"]
    assert result["state"] == "completed"
    assert "plan" not in result
    status = runner.invoke(main, ["upgrade", "status", "--project-dir", str(tmp_path), "--upgrade-id", result["upgrade_id"]])
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["upgrade"]["state"] == "completed"
    history = runner.invoke(main, ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID, "--record", "result"])
    assert history.exit_code == 0, history.output


def test_native_entry_reads_switched_history_inside_maintenance_without_writing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, installed_python: Path) -> None:
    from strixnova.managed_installation import ManagedInstallation
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError, _digest

    project = tmp_path / "project"
    write_history(project)
    upgrade = RuntimeUpgrade(project)
    with monkeypatch.context() as crash:
        crash.setattr(upgrade, "_close", lambda journal: (_ for _ in ()).throw(OSError("stop before ending maintenance")))
        with pytest.raises(RuntimeUpgradeError):
            upgrade.apply(upgrade.check())
    journal = upgrade.status()
    before = {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()}
    manager = ManagedInstallation(tmp_path / "installation", project)
    runtime = manager.probe(str(installed_python))
    trial = manager.validate_project(runtime, upgrade_id=journal["upgrade_id"], expected_snapshot_sha256=_digest({entry["kind"]: entry["candidate_snapshot"] for entry in journal["replacements"]}))
    assert trial["exit_code"] == 0
    assert trial["history_sample_count"] == 1
    assert trial["writes_performed"] is False
    assert trial["actual_entrypoint"] == runtime["entrypoint"]
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    with upgrade.maintenance.read_trial(journal["upgrade_id"]):
        from strixnova.project_maintenance import MaintenanceError
        from strixnova.workflow_authority import WorkflowAuthority
        with pytest.raises(MaintenanceError) as caught:
            WorkflowAuthority(project).create(title="forbidden", raw_request="trial cannot write")
        assert caught.value.code in {"project_under_maintenance", "maintenance_trial_read_only"}
    assert {path.relative_to(project): path.read_bytes() for path in project.rglob("*") if path.is_file()} == before
    assert upgrade.recover(journal["upgrade_id"], mode="resume")["state"] == "completed"
