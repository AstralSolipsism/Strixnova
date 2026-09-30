from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
import base64
import hashlib
import json
import subprocess
import sys
import threading

import pytest
from click.testing import CliRunner

from strixnova.project_maintenance import ProjectMaintenance, project_operation
from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError
from strixnova.storage_formats import AUTHORITY_FORMAT
from strixnova.workflow_authority import WorkflowAuthority


@pytest.mark.parametrize("inside_read_admission", [False, True])
def test_crashed_writer_cannot_be_mistaken_for_a_safely_drained_operation(tmp_path: Path, inside_read_admission: bool) -> None:
    item = WorkflowAuthority(tmp_path).create(title="keep history", raw_request="preserve")
    # A new child process uses the repository interpreter and dies without
    # running Python finally blocks. Its OS lease is released by the kernel.
    outer = "with project_operation(project, read_only=True):\n    " if inside_read_admission else ""
    script = "from pathlib import Path\nimport os,sys\nfrom strixnova.project_maintenance import project_operation\nproject=Path(sys.argv[1])\n" + outer + "with project_operation(project):\n" + ("    " if inside_read_admission else "") + "    os._exit(23)\n"
    # Ensure a read admission has an existing control directory to lease.
    (tmp_path / ".strixnova/artifacts/maintenance").mkdir(parents=True, exist_ok=True)
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", script, str(tmp_path)], capture_output=True)
    assert child.returncode == 23, child.stderr.decode(errors="replace")
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    with pytest.raises(RuntimeUpgradeError) as caught:
        RuntimeUpgrade(tmp_path).check()
    assert caught.value.code == "upgrade_unclosed_operations"
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before
    assert WorkflowAuthority(tmp_path).get(item["work_item_id"])["title"] == "keep history"


def test_public_recovery_binds_stop_evidence_and_preserves_the_original_start_record(tmp_path: Path) -> None:
    from strixnova.cli import main

    authority = WorkflowAuthority(tmp_path)
    authority.create(title="existing", raw_request="preserve")
    command = "import os,sys\nfrom strixnova.project_maintenance import project_operation\nwith project_operation(sys.argv[1]):\n    os._exit(23)"
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", command, str(tmp_path)], capture_output=True)
    assert child.returncode == 23
    runner = CliRunner()
    listing = runner.invoke(main, ["upgrade", "operations", "--project-dir", str(tmp_path)])
    assert listing.exit_code == 0, listing.output
    operation = json.loads(listing.output)["operations"][0]
    path = tmp_path / ".strixnova/artifacts/maintenance" / (operation["operation_id"] + ".json")
    original = path.read_bytes()
    evidence_file = tmp_path / "owned-process-exit.json"
    evidence_file.write_text(json.dumps({"command": command, "returncode": child.returncode, "spawned_descendants": [], "scope": "only the child explicitly launched by this test"}), encoding="utf-8")
    evidence = {
        "schema_version": "strixnova.execution-stop-evidence.v1", "scope": operation["stop_evidence_scope"],
        "observed_at": datetime.now(timezone.utc).isoformat(), "performed_by": "isolated test harness",
        "method": "wait for the only owned process; the recorded script starts no children",
        "findings": "the owned process exited with code 23 and cannot write again",
        "execution_stopped": True, "descendants_settled": True, "continuous_stop": True,
        "evidence_files": [{"path": str(evidence_file), "sha256": hashlib.sha256(evidence_file.read_bytes()).hexdigest()}],
    }
    stale = json.loads(json.dumps(evidence))
    stale["scope"]["record_sha256"] = "0" * 64
    arguments = ["upgrade", "recover-operation", "--project-dir", str(tmp_path), "--operation-id", operation["operation_id"], "--input"]
    rejected = runner.invoke(main, [*arguments, json.dumps(stale)])
    assert rejected.exit_code != 0
    assert path.read_bytes() == original
    recovered = runner.invoke(main, [*arguments, json.dumps(evidence)])
    assert recovered.exit_code == 0, recovered.output
    assert json.loads(recovered.output)["operation"]["external_truth_machine_proven"] is False
    saved = json.loads(path.read_bytes())
    assert base64.b64decode(saved["original_record_base64"]) == original
    assert ProjectMaintenance(tmp_path).unclosed_operations() == []
    assert RuntimeUpgrade(tmp_path).check()["source_formats"]["authority"] == AUTHORITY_FORMAT
    authority.create(title="can continue", raw_request="new authorized operation")
    assert runner.invoke(main, [*arguments, json.dumps(evidence)]).exit_code == 0


def test_normally_returned_or_rejected_operations_do_not_leave_unclosed_writes(tmp_path: Path) -> None:
    authority = WorkflowAuthority(tmp_path)
    authority.create(title="existing", raw_request="preserve")
    with project_operation(tmp_path):
        authority.create(title="returned", raw_request="recorded")
    with pytest.raises(ValueError):
        with project_operation(tmp_path):
            raise ValueError("a normal rejected request has unwound")
    assert ProjectMaintenance(tmp_path).unclosed_operations() == []
    assert RuntimeUpgrade(tmp_path).check()["source_formats"]["authority"] == AUTHORITY_FORMAT


def test_interrupted_installation_is_tracked_before_any_business_database_exists(tmp_path: Path) -> None:
    from strixnova.project_maintenance import MaintenanceError, installation_preparation

    command = "import os,sys\nfrom strixnova.project_maintenance import installation_preparation\nwith installation_preparation(sys.argv[1]):\n    os._exit(24)"
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", command, str(tmp_path)], capture_output=True)
    assert child.returncode == 24
    records = ProjectMaintenance(tmp_path).unclosed_operations()
    assert len(records) == 1
    assert records[0]["operation"] == "installation-prepare"
    assert records[0]["state"] == "interrupted"
    with pytest.raises(MaintenanceError) as caught:
        with installation_preparation(tmp_path):
            pytest.fail("do not restart pip over an unclosed preparation")
    assert caught.value.code == "operation_recovery_required"
    assert not (tmp_path / ".strixnova/authority.sqlite3").exists()


def test_writer_dying_between_record_and_lock_scans_is_not_drained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.project_maintenance import MaintenanceError

    WorkflowAuthority(tmp_path).create(title="existing", raw_request="preserve")
    running, interrupt = threading.Event(), threading.Event()
    def writer():
        try:
            with project_operation(tmp_path):
                running.set()
                assert interrupt.wait(5)
                raise SystemExit("interrupt after the first record scan")
        except SystemExit:
            pass
    thread = threading.Thread(target=writer)
    thread.start()
    assert running.wait(5)
    maintenance = ProjectMaintenance(tmp_path)
    original = maintenance.unclosed_operations
    first = True
    def scan(**kwargs):
        nonlocal first
        records = original(**kwargs)
        if first:
            first = False
            assert records[0]["state"] == "running"
            interrupt.set()
            thread.join(5)
            assert not thread.is_alive()
        return records
    monkeypatch.setattr(maintenance, "unclosed_operations", scan)
    try:
        with pytest.raises(MaintenanceError) as caught:
            maintenance.begin("UPGRADE-RACE", timeout=1)
        assert caught.value.code == "maintenance_unclosed_operations"
    finally:
        interrupt.set()
        thread.join(5)


def test_failed_process_cleanup_keeps_the_durable_start_after_error_wrapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError
    from strixnova.process_supervisor import ProcessExecutionError
    from strixnova.project_maintenance import installation_preparation

    def cannot_clean(*args, **kwargs):
        raise ProcessExecutionError("cleanup_failed", "process tree did not stop", command_name="fixture")
    monkeypatch.setattr("strixnova.managed_installation.run_process", cannot_clean)
    with pytest.raises(ManagedInstallationError):
        with installation_preparation(tmp_path):
            ManagedInstallation._run(["fixture"], cwd=tmp_path)
    records = ProjectMaintenance(tmp_path).unclosed_operations()
    assert len(records) == 1
    assert records[0]["state"] == "interrupted"
