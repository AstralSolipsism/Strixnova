from __future__ import annotations

from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading
import json
import os
import sqlite3
from contextlib import closing

from click.testing import CliRunner

import pytest

from strixnova.workflow_authority import WorkflowAuthority


def test_maintenance_blocks_new_facts_until_explicitly_finished(tmp_path: Path) -> None:
    from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance

    authority = WorkflowAuthority(tmp_path)
    first = authority.create(title="保留事项", raw_request="继续当前工作")
    maintenance = ProjectMaintenance(tmp_path)
    with maintenance.executor():
        maintenance.begin("UPGRADE-TEST", timeout=0.1)
        with pytest.raises(MaintenanceError) as blocked:
            authority.create(title="不应写入", raw_request="维护期间的请求")
        assert blocked.value.code == "project_under_maintenance"
        assert maintenance.status()["upgrade_id"] == "UPGRADE-TEST"
        maintenance.finish("UPGRADE-TEST")
    assert [item["work_item_id"] for item in authority.list()] == [first["work_item_id"]]


def test_maintenance_drains_existing_parallel_operations_and_keeps_failed_attempt_visible(tmp_path: Path) -> None:
    from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance, project_operation

    authority = WorkflowAuthority(tmp_path)
    authority.create(title="现有项目", raw_request="允许并行操作")
    entered = [threading.Event(), threading.Event()]
    release = threading.Event()

    def operation(index: int) -> None:
        with project_operation(tmp_path):
            entered[index].set()
            assert release.wait(5)
            authority.create(title=f"已经开始的操作 {index}", raw_request="回写真实结果")

    maintenance = ProjectMaintenance(tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(operation, index) for index in range(2)]
        try:
            assert all(event.wait(5) for event in entered)
            with maintenance.executor():
                with pytest.raises(MaintenanceError) as blocked:
                    maintenance.begin("UPGRADE-DRAIN", timeout=0.01)
                assert blocked.value.code == "maintenance_operations_pending"
                assert maintenance.status()["state"] == "maintenance"
        finally:
            release.set()
        for future in futures:
            future.result()
    with maintenance.executor():
        maintenance.begin("UPGRADE-DRAIN", timeout=0.1)
        maintenance.finish("UPGRADE-DRAIN")
    assert len(authority.list()) == 3


def test_cli_reports_maintenance_without_a_traceback(tmp_path: Path) -> None:
    from strixnova.cli import main
    from strixnova.project_maintenance import ProjectMaintenance

    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="活动事项", raw_request="等待升级")
    maintenance = ProjectMaintenance(tmp_path)
    with maintenance.executor():
        maintenance.begin("UPGRADE-CLI")
        response = CliRunner().invoke(main, ["next", "--project-dir", str(tmp_path), "--work-item-id", item["work_item_id"]])
        assert response.exit_code == 1
        assert json.loads(response.output)["error"]["code"] == "project_under_maintenance"
        maintenance.finish("UPGRADE-CLI")


def test_failed_database_open_releases_its_operation_lease(tmp_path: Path) -> None:
    from strixnova.project_maintenance import ProjectMaintenance
    from strixnova.workflow_authority import WorkflowAuthorityError

    authority = WorkflowAuthority(tmp_path)
    authority.create(title="原事项", raw_request="保留原数据")
    database = tmp_path / ".strixnova/authority.sqlite3"
    with closing(sqlite3.connect(database)) as blocker:
        blocker.execute("PRAGMA journal_mode=DELETE")
        blocker.execute("BEGIN")
        blocker.execute("SELECT * FROM work_items").fetchall()
        with pytest.raises(WorkflowAuthorityError) as captured:
            authority.create(title="无法开始", raw_request="被外部读取阻塞")
        assert captured.value.code == "authority_open_failed"
    maintenance = ProjectMaintenance(tmp_path)
    with maintenance.executor():
        maintenance.begin("UPGRADE-AFTER-OPEN-FAILURE", timeout=0.1)
        maintenance.finish("UPGRADE-AFTER-OPEN-FAILURE")


def test_lease_cleanup_failure_cannot_reject_an_already_committed_request(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.application_coordinator import ApplicationCoordinator

    authority = WorkflowAuthority(tmp_path)
    authority.create(title="原事项", raw_request="保留原数据")
    unlink = os.unlink

    def occupied(path: object, *args: object, **kwargs: object) -> None:
        if Path(path).name.startswith("operation-"):
            raise PermissionError("模拟排空扫描尚持有文件句柄")
        unlink(path, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(os, "unlink", occupied)
        created = ApplicationCoordinator(tmp_path).intake(title="已经提交", raw_request="清理失败不能丢掉返回结果")
    assert authority.get(created["work_item_id"])["title"] == "已经提交"


def test_failed_format_probe_cannot_start_an_unleased_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.project_maintenance import MaintenanceError, project_operation

    WorkflowAuthority(tmp_path).create(title="原事项", raw_request="继续工作")
    entered = False

    def busy(*args: object, **kwargs: object) -> None:
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise error

    with monkeypatch.context() as fault:
        fault.setattr(sqlite3, "connect", busy)
        with pytest.raises(MaintenanceError) as blocked:
            with project_operation(tmp_path):
                entered = True
    assert blocked.value.code == "maintenance_probe_failed"
    assert entered is False


def test_connection_creation_failure_has_a_structured_owner_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.workflow_authority import WorkflowAuthorityError

    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="原事项", raw_request="继续工作")
    connect = sqlite3.connect

    def cannot_open(*args: object, **kwargs: object):
        if "factory" in kwargs:
            raise sqlite3.OperationalError("cannot open database")
        return connect(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(sqlite3, "connect", cannot_open)
        with pytest.raises(WorkflowAuthorityError) as blocked:
            authority.get(item["work_item_id"])
    assert blocked.value.code == "authority_open_failed"
