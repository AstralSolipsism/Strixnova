"""First-use admission preserves installation coordination and unknown material."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import threading

from click.testing import CliRunner
import pytest

from strixnova.cli import main
from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance, installation_preparation
from strixnova.workflow_authority import WorkflowAuthority, WorkflowAuthorityError


def installed_coordination(project: Path) -> ProjectMaintenance:
    maintenance = ProjectMaintenance(project)
    with maintenance.installation_executor(project.parent / "installation"):
        with installation_preparation(project):
            pass
    return maintenance


def snapshot(project: Path) -> dict[str, bytes]:
    return {path.relative_to(project).as_posix(): path.read_bytes() for path in project.rglob("*") if path.is_file()}


def operation_record(project: Path, *, state="running") -> Path:
    path = project / ".strixnova/artifacts/maintenance" / ("operation-" + "a" * 32 + ".json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema_version": "strixnova.project-operation.v1",
        "operation_id": path.stem, "project": str(project.resolve()),
        "operation": "installation-prepare", "state": state,
        "started_at": "2026-09-11T00:00:00Z", "process_id": 123,
    }), encoding="utf-8")
    return path


def test_first_public_intake_preserves_completed_installation_and_repeated_intake(tmp_path):
    installed_coordination(tmp_path)
    before = snapshot(tmp_path)
    assert before and all(name.endswith(".lock") for name in before)
    assert WorkflowAuthority(tmp_path).list() == []
    assert snapshot(tmp_path) == before
    runner = CliRunner()
    identifiers = []
    for title in ("First request", "Second request"):
        response = runner.invoke(main, ["intake", "--project-dir", str(tmp_path), "--input", json.dumps({"title": title, "request": title})])
        assert response.exit_code == 0, response.output
        identifiers.append(json.loads(response.output)["next"]["work_item_id"])
    assert len(set(identifiers)) == 2
    assert {item["work_item_id"] for item in WorkflowAuthority(tmp_path).list()} == set(identifiers)
    assert all((tmp_path / name).read_bytes() == contents for name, contents in before.items())


@pytest.mark.parametrize("relative", ["unexpected.json", "maintenance/foreign.json", "maintenance/installation-unknown.lock"])
def test_known_installation_files_do_not_hide_unrecognized_material(tmp_path, relative):
    installed_coordination(tmp_path)
    path = tmp_path / ".strixnova/artifacts" / relative
    path.write_bytes(b"preserve this unclassified material")
    before = snapshot(tmp_path)
    with pytest.raises(WorkflowAuthorityError) as error:
        WorkflowAuthority(tmp_path).initialize()
    assert error.value.code == "unsupported_authority_format"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("contents", ["invalid json", '{"schema_version":"unknown"}'])
def test_invalid_installation_record_does_not_initialize_or_erase_evidence(tmp_path, contents):
    installed_coordination(tmp_path)
    path = operation_record(tmp_path)
    path.write_text(contents, encoding="utf-8")
    before = snapshot(tmp_path)
    with pytest.raises(MaintenanceError) as error:
        WorkflowAuthority(tmp_path).initialize()
    assert error.value.code == "operation_record_invalid"
    assert snapshot(tmp_path) == before


def test_interrupted_installation_requires_recovery_even_when_its_lock_is_free(tmp_path):
    installed_coordination(tmp_path)
    record = operation_record(tmp_path)
    original = record.read_bytes()
    with pytest.raises(MaintenanceError) as error:
        WorkflowAuthority(tmp_path).create(title="Not admitted", raw_request="Preserve the unfinished installation.")
    assert error.value.code == "operation_recovery_required"
    assert record.read_bytes() == original
    assert not (tmp_path / ".strixnova/authority.sqlite3").exists()


def test_running_installation_blocks_first_creation_until_it_finishes(tmp_path):
    maintenance = ProjectMaintenance(tmp_path)
    entered, release = threading.Event(), threading.Event()

    def install():
        with maintenance.installation_executor(tmp_path.parent / "installation"):
            with installation_preparation(tmp_path):
                entered.set()
                assert release.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(install)
        try:
            assert entered.wait(10)
            with pytest.raises(MaintenanceError) as error:
                WorkflowAuthority(tmp_path).create(title="Too early", raw_request="Still installing.")
            assert error.value.code in {"maintenance_busy", "installation_busy"}
            assert not (tmp_path / ".strixnova/authority.sqlite3").exists()
        finally:
            release.set()
        future.result()
    assert WorkflowAuthority(tmp_path).create(title="Ready", raw_request="Installation finished.")["title"] == "Ready"


def test_concurrent_first_creator_is_told_to_retry_without_overwriting_storage(tmp_path, monkeypatch):
    opened, release = threading.Event(), threading.Event()
    ensure_schema = WorkflowAuthority._ensure_schema

    def held_schema(connection):
        opened.set()
        assert release.wait(10)
        ensure_schema(connection)

    with ThreadPoolExecutor(max_workers=1) as pool, monkeypatch.context() as patch:
        patch.setattr(WorkflowAuthority, "_ensure_schema", staticmethod(held_schema))
        future = pool.submit(WorkflowAuthority(tmp_path).create, title="First", raw_request="Create once.")
        try:
            assert opened.wait(10)
            with pytest.raises(MaintenanceError) as error:
                WorkflowAuthority(tmp_path).create(title="Second", raw_request="Wait for the same database.")
            assert error.value.code == "authority_initialization_pending"
        finally:
            release.set()
        first = future.result()
    second = WorkflowAuthority(tmp_path).create(title="Second", raw_request="Retry after initialization.")
    assert {item["work_item_id"] for item in WorkflowAuthority(tmp_path).list()} == {first["work_item_id"], second["work_item_id"]}


def test_reentrant_maintenance_executor_does_not_allow_another_thread(tmp_path):
    maintenance = ProjectMaintenance(tmp_path)
    with maintenance.executor():
        with maintenance.executor():
            pass
        def competing():
            with pytest.raises(MaintenanceError) as error:
                with ProjectMaintenance(tmp_path).executor():
                    pass
            return error.value.code
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(competing).result() == "maintenance_busy"


def test_recovered_installation_can_initialize_without_losing_stop_evidence(tmp_path):
    import base64
    from datetime import datetime, timezone
    import hashlib
    import subprocess
    import sys

    command = "import os,sys\nfrom strixnova.project_maintenance import installation_preparation\nwith installation_preparation(sys.argv[1]):\n    os._exit(24)"
    child = subprocess.run([sys.executable, "-X", "utf8", "-c", command, str(tmp_path)], capture_output=True)
    assert child.returncode == 24, child.stderr
    maintenance = ProjectMaintenance(tmp_path)
    operation = maintenance.unclosed_operations()[0]
    record = maintenance.root / (operation["operation_id"] + ".json")
    original = record.read_bytes()
    observed = tmp_path / "owned-exit.json"
    observed.write_text(json.dumps({"exit_code": child.returncode, "command": command, "descendants_spawned": []}), encoding="utf-8")
    evidence = {
        "schema_version": "strixnova.execution-stop-evidence.v1",
        "scope": {"kind": "project_operation", "project": str(tmp_path.resolve()), "operation_id": operation["operation_id"], "record_sha256": operation["record_sha256"]},
        "observed_at": datetime.now(timezone.utc).isoformat(), "performed_by": "isolated fixture",
        "method": "Wait for the exact child launched by this fixture; it starts no descendants.",
        "findings": "The child exited with code 24.", "execution_stopped": True, "descendants_settled": True, "continuous_stop": True,
        "evidence_files": [{"path": str(observed), "sha256": hashlib.sha256(observed.read_bytes()).hexdigest()}],
    }
    maintenance.resolve_operation(operation["operation_id"], evidence)
    retained = {path: path.read_bytes() for path in maintenance.root.rglob("*") if path.is_file()}
    assert base64.b64decode(json.loads(record.read_bytes())["original_record_base64"]) == original
    WorkflowAuthority(tmp_path).create(title="Recovered", raw_request="The installation was explicitly recovered.")
    assert all(path.read_bytes() == content for path, content in retained.items())


def test_first_initialization_rejects_a_link_in_maintenance_without_touching_its_target(tmp_path):
    import subprocess

    outside = tmp_path / "outside"
    outside.mkdir()
    kept = outside / "keep.txt"
    kept.write_bytes(b"keep outside material")
    maintenance = installed_coordination(tmp_path)
    link = maintenance.root / "linked"
    # This is an isolated junction fixture; neither cmd nor a traversal deletes it.
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
    if result.returncode:
        pytest.skip("This host cannot create the junction fixture.")
    try:
        with pytest.raises(MaintenanceError) as error:
            WorkflowAuthority(tmp_path).initialize()
        assert error.value.code == "maintenance_path_unsafe"
        assert kept.read_bytes() == b"keep outside material"
        assert not (tmp_path / ".strixnova/authority.sqlite3").exists()
    finally:
        link.rmdir()
