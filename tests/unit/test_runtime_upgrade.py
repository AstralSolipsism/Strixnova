from __future__ import annotations

from pathlib import Path
from contextlib import closing
import os
import sqlite3
import json
import hashlib
import subprocess

import pytest

from strixnova.storage_formats import AUTHORITY_FORMAT

from strixnova.host_adapter import LocalHostAdapter
from strixnova.workflow_authority import WorkflowAuthority, WorkflowAuthorityError
from tests.support.history_records import ITEM_ID, ORIGINAL_REQUEST, write_history, history_connection





def test_linked_worktree_git_operation_blocks_precheck(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError

    repository = tmp_path / "repository"
    repository.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "main")
    git("config", "user.name", "Strixnova fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("commit", "--allow-empty", "-m", "fixture")
    linked = tmp_path / "linked"
    git("worktree", "add", "-b", "topic", str(linked))
    WorkflowAuthority(linked).create(title="linked project", raw_request="preserve")
    metadata = Path(subprocess.run(["git", "-C", str(linked), "rev-parse", "--absolute-git-dir"], check=True, capture_output=True, text=True).stdout.strip())
    assert (linked / ".git").is_file()
    (metadata / "MERGE_HEAD").write_text(git("rev-parse", "HEAD") + "\n", encoding="utf-8")
    with pytest.raises(RuntimeUpgradeError) as caught:
        RuntimeUpgrade(linked).check()
    assert caught.value.code == "upgrade_pending_git_operation"


def test_restore_refuses_a_new_activity_database_created_after_upgrade(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError
    from strixnova.delivery_activity import DeliveryActivityAuthority
    from tests.unit.test_delivery_activity import _plan

    write_history(tmp_path)
    upgrade = RuntimeUpgrade(tmp_path)
    completed = upgrade.apply(upgrade.check())
    activity = DeliveryActivityAuthority(tmp_path)
    created = activity.plan(_plan(), work_item_id=ITEM_ID, work_item_version=3, engineering_plan_id="PLAN-NEW")
    with pytest.raises(RuntimeUpgradeError) as caught:
        upgrade.recover(completed["upgrade_id"], mode="restore")
    assert caught.value.code == "upgrade_restore_would_discard_new_facts"
    assert activity.get(created["activity_id"]) == created
    assert upgrade.check()["source_formats"]["authority"] == AUTHORITY_FORMAT


def test_completed_inflight_write_invalidates_plan_without_stranding_maintenance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError

    authority = WorkflowAuthority(tmp_path)
    authority.create(title="existing", raw_request="keep")
    upgrade = RuntimeUpgrade(tmp_path)
    plan = upgrade.check()
    original_begin = upgrade.maintenance.begin
    added = None

    def finish_inflight(upgrade_id: str, **kwargs: object) -> None:
        nonlocal added
        added = authority.create(title="finished while draining", raw_request="preserve this writeback")
        original_begin(upgrade_id, **kwargs)

    monkeypatch.setattr(upgrade.maintenance, "begin", finish_inflight)
    with pytest.raises(RuntimeUpgradeError) as caught:
        upgrade.apply(plan)
    assert caught.value.code == "upgrade_plan_stale"
    assert upgrade.status()["state"] == "clear"
    assert authority.get(added["work_item_id"])["data"]["raw_request"] == "preserve this writeback"
    assert upgrade.check()["plan_id"] != plan["plan_id"]


def test_initial_upgrade_journal_cannot_follow_a_directory_junction(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError

    if os.name != "nt":
        pytest.skip("Windows junction boundary")
    project = tmp_path / "project"
    write_history(project)
    upgrade = RuntimeUpgrade(project)
    plan = upgrade.check()
    upgrade_id = "UPGRADE-" + hashlib.sha256(plan["plan_id"].encode()).hexdigest()[:24].upper()
    directory = project / ".strixnova/artifacts/maintenance" / upgrade_id
    directory.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "unrelated"
    outside.mkdir()
    created = subprocess.run(["cmd", "/c", "mklink", "/J", str(directory), str(outside)], capture_output=True)
    if created.returncode:
        pytest.skip("This filesystem cannot create junctions")
    try:
        with pytest.raises(RuntimeUpgradeError) as caught:
            upgrade.apply(plan)
        assert caught.value.code in {"upgrade_journal_invalid", "upgrade_directory_occupied"}
        assert list(outside.iterdir()) == []
    finally:
        os.rmdir(directory)


def test_runtime_maintenance_preserves_original_records_and_current_format(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade

    database = write_history(tmp_path)
    with closing(history_connection(database)) as connection:
        before = list(connection.execute("SELECT work_item_id,data_json FROM work_items ORDER BY work_item_id"))
        events = list(connection.execute("SELECT * FROM events ORDER BY sequence"))
        annotations = list(connection.execute("SELECT * FROM event_annotations ORDER BY event_sequence"))
    upgrade = RuntimeUpgrade(tmp_path)
    plan = upgrade.check()
    assert plan["source_formats"]["authority"] == AUTHORITY_FORMAT
    assert all(plan["target_formats"][kind] == version for kind, version in plan["source_formats"].items())
    assert upgrade.apply(plan)["business_records_preserved"] is True
    with closing(history_connection(database)) as connection:
        assert list(connection.execute("SELECT work_item_id,data_json FROM work_items ORDER BY work_item_id")) == before
        assert list(connection.execute("SELECT * FROM events ORDER BY sequence")) == events
        assert list(connection.execute("SELECT * FROM event_annotations ORDER BY event_sequence")) == annotations
        assert connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0] == str(AUTHORITY_FORMAT)
        connection.create_function("strixnova_write_contract", 0, lambda: AUTHORITY_FORMAT + 1)
        with pytest.raises(sqlite3.IntegrityError, match="strixnova_write_contract_required"):
            connection.execute("UPDATE work_items SET title='incompatible writer'")



def test_runtime_maintenance_preserves_records_and_reports_missing_logs(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade

    database = write_history(tmp_path)
    (tmp_path / ".strixnova/artifacts" / ITEM_ID / "VR-EXPORT.stderr.log").unlink()
    before = database.read_bytes()
    upgrade = RuntimeUpgrade(tmp_path)
    plan = upgrade.check()
    assert plan["source_formats"]["authority"] == AUTHORITY_FORMAT
    assert plan["target_formats"]["authority"] == AUTHORITY_FORMAT
    assert database.read_bytes() == before
    assert upgrade.maintenance.status()["state"] == "clear"

    result = upgrade.apply(plan)

    assert result["state"] == "completed"
    assert result["business_records_preserved"] is True
    assert Path(result["backup_directory"]).is_dir()
    history = LocalHostAdapter(tmp_path).history(work_item_id=ITEM_ID, records=("event:1", "result", "output:VR-EXPORT:stderr"))
    assert history["records"]["event:1"]["payload_json"] == ORIGINAL_REQUEST
    assert history["records"]["result"]["confirmation"]["user_confirmation"] == "接受导出结果，已知大文件尚未压测"
    assert history["records"]["output:VR-EXPORT:stderr"]["availability"] == "missing"
    assert upgrade.status(result["upgrade_id"])["state"] == "completed"








def test_current_log_references_survive_project_move_and_detect_changed_bytes(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade

    project = tmp_path / "project"
    write_history(project)
    upgrade = RuntimeUpgrade(project)
    upgrade.apply(upgrade.check())
    moved = tmp_path / "moved"
    project.rename(moved)
    adapter = LocalHostAdapter(moved)
    before = adapter.history(work_item_id=ITEM_ID, records=("output:VR-EXPORT:stdout",))["records"]["output:VR-EXPORT:stdout"]
    assert before["availability"] == "available"
    assert before["integrity"] == "verified_since_execution"
    (moved / ".strixnova/artifacts" / ITEM_ID / "VR-EXPORT.stdout.log").write_text("替换后的内容", encoding="utf-8")
    after = adapter.history(work_item_id=ITEM_ID, records=("output:VR-EXPORT:stdout",))["records"]["output:VR-EXPORT:stdout"]
    assert after["availability"] == "hash_mismatch"
    assert "text" not in after


def test_partial_database_switch_can_resume_without_repeating_completed_replacements(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError

    write_history(tmp_path)
    activity = tmp_path / ".strixnova/delivery-activities.sqlite3"
    from strixnova.delivery_activity import DeliveryActivityAuthority
    from tests.unit.test_delivery_activity import _plan
    DeliveryActivityAuthority(tmp_path).plan(_plan(), work_item_id=ITEM_ID, work_item_version=3, engineering_plan_id="PLAN-KEEP")
    upgrade = RuntimeUpgrade(tmp_path)
    plan = upgrade.check()
    replace = os.replace

    def fail_activity(source: object, target: object) -> None:
        if Path(target) == activity:
            raise OSError("模拟活动库切换失败")
        replace(source, target)

    with monkeypatch.context() as fault:
        fault.setattr(os, "replace", fail_activity)
        with pytest.raises(RuntimeUpgradeError):
            upgrade.apply(plan)
    interrupted = upgrade.status()
    assert interrupted["state"] == "switching"
    resumed = upgrade.recover(interrupted["upgrade_id"], mode="resume")
    assert resumed["state"] == "completed"
    assert resumed["business_records_preserved"] is True
    assert upgrade.status()["state"] == "clear"
    assert LocalHostAdapter(tmp_path).history(work_item_id=ITEM_ID, records=("event:1",))["records"]["event:1"]["payload_json"] == ORIGINAL_REQUEST


def test_restore_preserves_new_facts_and_only_restores_an_unchanged_generation(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError

    first = tmp_path / "unchanged"
    write_history(first)
    upgrade = RuntimeUpgrade(first)
    result = upgrade.apply(upgrade.check())
    restored = upgrade.recover(result["upgrade_id"], mode="restore")
    assert restored["state"] == "restored"
    assert upgrade.check()["source_formats"]["authority"] == AUTHORITY_FORMAT
    assert LocalHostAdapter(first).history(work_item_id=ITEM_ID, records=("result",))["records"]["result"]["acceptance_status"] == "accepted"

    second = tmp_path / "has-new-work"
    write_history(second)
    upgrade = RuntimeUpgrade(second)
    result = upgrade.apply(upgrade.check())
    new_item = WorkflowAuthority(second).create(title="新版中的新事项", raw_request="不能丢掉这项新工作")
    with pytest.raises(RuntimeUpgradeError) as blocked:
        upgrade.recover(result["upgrade_id"], mode="restore")
    assert blocked.value.code == "upgrade_restore_would_discard_new_facts"
    assert WorkflowAuthority(second).get(new_item["work_item_id"])["data"]["raw_request"] == "不能丢掉这项新工作"
    assert upgrade.status()["state"] == "clear"




def test_open_wal_reader_blocks_switch_and_committed_wal_facts_are_preserved(tmp_path: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError

    database = write_history(tmp_path)
    upgrade = RuntimeUpgrade(tmp_path)
    with closing(history_connection(database)) as old_reader:
        old_reader.execute("PRAGMA journal_mode=WAL")
        old_reader.execute("UPDATE work_items SET title='已经提交到 WAL 的标题'")
        old_reader.commit()
        old_reader.execute("BEGIN")
        old_reader.execute("SELECT * FROM work_items").fetchall()
        plan = upgrade.check()
        with pytest.raises(RuntimeUpgradeError) as blocked:
            upgrade.apply(plan)
        assert blocked.value.code == "upgrade_connections_open"
    assert upgrade.status()["state"] == "clear"  # No source files were changed.
    result = upgrade.apply(upgrade.check())
    assert result["state"] == "completed"
    assert WorkflowAuthority(tmp_path).get(ITEM_ID)["title"] == "已经提交到 WAL 的标题"


def test_recovery_finishes_after_restoring_runtime_selection_then_crashing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from copy import deepcopy
    from strixnova.managed_installation import ManagedInstallation
    from strixnova.runtime_identity import runtime_identity
    from strixnova.runtime_upgrade import RuntimeUpgrade

    project = tmp_path / "project"
    project.mkdir()
    WorkflowAuthority(project).create(title="keep this work", raw_request="preserve")
    upgrade = RuntimeUpgrade(project)
    manager = ManagedInstallation(tmp_path / "installed", project)
    identity = runtime_identity()
    source = {"python_path": "old-python", "entrypoint": "old-entry", "build_sha256": "original-program", "skill_sha256": "original-skill", "authority_format": AUTHORITY_FORMAT, "activity_format": 1}
    target = {"python_path": "new-python", "entrypoint": "new-entry", "build_sha256": identity["build_sha256"], "skill_sha256": identity["skill_sha256"], "authority_format": AUTHORITY_FORMAT, "activity_format": 1}
    request = {"installation_root": str(manager.root), "target_wheel": "fixture", "source_python": "old-python", "builder_python": "fixture", "wheelhouse": None}
    installation = {"installation_root": str(manager.root), "target": identity, "source_runtime": source, "previous_selection": None, "builder_python": "fixture", "wheelhouse": None, "request": request}
    monkeypatch.setattr(ManagedInstallation, "plan", lambda *args, **kwargs: deepcopy(installation))
    monkeypatch.setattr(ManagedInstallation, "prepare", lambda *args, **kwargs: {"runtime": deepcopy(target)})
    monkeypatch.setattr(ManagedInstallation, "probe", lambda self, python: deepcopy(source if python == "old-python" else target))
    trials = []
    def trial(self, runtime, **kwargs):
        trials.append(runtime["python_path"])
        assert upgrade.status()["state"] == "switching"
        return {"actual_entrypoint": "fixture"}
    monkeypatch.setattr(ManagedInstallation, "validate_project", trial, raising=False)
    completed = upgrade.apply(upgrade.check(installation=request))
    assert trials == ["new-python"]  # Equal build hashes still require the target entry.
    with monkeypatch.context() as crash:
        crash.setattr(upgrade, "_close", lambda journal: (_ for _ in ()).throw(OSError("crash after selecting old runtime")))
        with pytest.raises(OSError):
            upgrade.recover(completed["upgrade_id"], mode="restore")
    assert manager.active()["runtime"] == source
    resumed = upgrade.recover(completed["upgrade_id"], mode="restore")
    assert resumed["state"] == "restored"
    assert upgrade.status()["state"] == "clear"
    assert manager.active()["runtime"] == source


@pytest.mark.parametrize("writer_format", [None, 999])
@pytest.mark.parametrize("maintained", [False, True])
def test_database_rejects_missing_or_incompatible_write_contract(tmp_path: Path, writer_format: int | None, maintained: bool) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade

    database = write_history(tmp_path)
    if maintained:
        operation = RuntimeUpgrade(tmp_path)
        operation.apply(operation.check())
    with closing(sqlite3.connect(database)) as connection:
        if writer_format is not None:
            connection.create_function("strixnova_write_contract", 0, lambda: writer_format)
        before = connection.execute("SELECT title FROM work_items").fetchall()
        with pytest.raises(sqlite3.DatabaseError):
            connection.execute("UPDATE work_items SET title='unregistered writer'")
        assert connection.execute("SELECT title FROM work_items").fetchall() == before



def test_fence_only_recovery_preserves_a_late_activity_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade, RuntimeUpgradeError
    from strixnova.storage_formats import install_write_guards

    write_history(tmp_path)
    activity = tmp_path / ".strixnova/delivery-activities.sqlite3"
    from strixnova.delivery_activity import DeliveryActivityAuthority
    from tests.unit.test_delivery_activity import _plan
    DeliveryActivityAuthority(tmp_path).plan(_plan(), work_item_id=ITEM_ID, work_item_version=3, engineering_plan_id="PLAN-KEEP")
    upgrade = RuntimeUpgrade(tmp_path)

    def interrupt_fencing(journal):
        journal["state"] = "fencing"
        upgrade._save(journal)
        # Model an external current-format write before this database was fenced.
        # The controller then dies after fencing that database, before switching.
        with closing(history_connection(activity)) as connection, connection:
            connection.execute("UPDATE activities SET version=2,state='canceled',payload=json_set(payload,'$.version',2,'$.state','canceled')")
            connection.execute("INSERT INTO activity_events SELECT activity_id,2,'canceled','2026-09-07',payload FROM activities")
            install_write_guards(connection, temporary=True)
        raise OSError("interrupted while fencing activity writes")

    monkeypatch.setattr(upgrade, "_fence_sources", interrupt_fencing)
    with pytest.raises(RuntimeUpgradeError):
        upgrade.apply(upgrade.check())
    interrupted = upgrade.status()
    result = upgrade.recover(interrupted["upgrade_id"], mode="restore")
    assert result["state"] == "aborted"
    assert result["aborted_before_replacement"] is True
    assert upgrade.status()["state"] == "clear"
    with closing(history_connection(activity)) as connection:
        assert connection.execute("SELECT version,state FROM activities").fetchone() == (2, "canceled")
        assert connection.execute("SELECT count(*) FROM activity_events").fetchone()[0] == 2
        triggers = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert not any(name.startswith("strixnova_maintenance_guard__") for name in triggers)
        assert any(name.startswith("strixnova_writer_guard__") for name in triggers)
