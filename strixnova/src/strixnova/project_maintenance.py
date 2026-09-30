"""Coordinate ordinary project operations with explicit recoverable maintenance.

Operation leases use OS locks, not PID guesses. The admission lock is short;
independent operations keep separate leases and may execute concurrently.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import json
import hashlib
import base64
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
from typing import Any, Iterator
import uuid

from strixnova.storage_formats import ACTIVITY_FORMAT, AUTHORITY_FORMAT
from strixnova.execution_stop_evidence import ExecutionStopEvidenceError, validate_stop_evidence


_LOCAL = threading.local()
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


class MaintenanceError(RuntimeError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _maintenance_record_digest(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sync_directory(path: Path) -> None:
    if os.name != "nt":
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_maintenance_json(path: Path, value: Any) -> None:
    """Publish a durable journal update beside its final destination."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.next")
    try:
        with temporary.open("xb") as stream:
            stream.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _lock(stream: Any) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock(stream: Any) -> None:
    stream.seek(0)
    if os.name == "nt":
        import msvcrt
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl
        fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


@contextmanager
def _locked(path: Path, *, timeout: float = 5.0) -> Iterator[None]:
    if path.is_symlink() or path.is_junction():
        raise MaintenanceError("maintenance_path_unsafe", "维护锁不能是链接")
    stream = path.open("a+b")
    acquired = False
    try:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b"\0")
            stream.flush()
        deadline = time.monotonic() + timeout
        while True:
            try:
                _lock(stream)
                acquired = True
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise MaintenanceError("maintenance_busy", "另一个操作仍持有维护锁") from None
                time.sleep(0.02)
        yield
    finally:
        if acquired:
            _unlock(stream)
        stream.close()


class ProjectMaintenance:
    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self.root = self.project / ".strixnova" / "artifacts" / "maintenance"
        self.active_path = self.root / "active.json"

    def _safe_root(self, *, create: bool = False) -> None:
        current = self.project
        for part in (".strixnova", "artifacts", "maintenance"):
            current = current / part
            if current.is_symlink() or current.is_junction() or (current.exists() and not current.is_dir()):
                raise MaintenanceError("maintenance_path_unsafe", "维护目录必须是项目内普通目录")
        if create:
            self.root.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def installation_executor(self, installation_root: Path) -> Iterator[None]:
        """Serialize preparations and selection without stopping ordinary work."""
        self._safe_root(create=True)
        identity = hashlib.sha256(str(installation_root).encode("utf-8")).hexdigest()
        try:
            with self.executor(), _locked(self.root / f"installation-{identity}.lock", timeout=0):
                yield
        except MaintenanceError as error:
            if error.code == "maintenance_busy":
                raise MaintenanceError("installation_busy", "该受管安装已有准备或选择操作，请等待其完成") from error
            raise

    @contextmanager
    def read_trial(self, upgrade_id: str) -> Iterator[None]:
        """Admit only reads by a validator of this exact active maintenance."""
        if self.status().get("upgrade_id") != upgrade_id:
            raise MaintenanceError("upgrade_identity_mismatch", "试读必须绑定当前维护身份")
        previous = getattr(_LOCAL, "maintenance_reads", {})
        _LOCAL.maintenance_reads = {**previous, str(self.project): upgrade_id}
        try:
            yield
        finally:
            _LOCAL.maintenance_reads = previous

    def status(self) -> dict[str, Any]:
        self._safe_root()
        if not self.active_path.exists():
            return {"state": "clear", "upgrade_id": None}
        if self.active_path.is_symlink() or not self.active_path.is_file():
            raise MaintenanceError("maintenance_state_invalid", "维护状态不是普通文件")
        try:
            if self.active_path.stat().st_size > 65536:
                raise ValueError
            value = json.loads(self.active_path.read_text(encoding="utf-8"))
            if value.get("schema_version") != "strixnova.project-maintenance.v1" or not _ID.fullmatch(value["upgrade_id"]):
                raise ValueError
            return {**value, "state": "maintenance"}
        except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
            raise MaintenanceError("maintenance_state_invalid", "维护状态损坏，必须先恢复，不能清空后继续") from error

    def assert_available(self) -> None:
        if str(self.project) in getattr(_LOCAL, "operations", {}):
            return
        if self.status()["state"] != "clear":
            raise MaintenanceError("project_under_maintenance", "项目正在升级维护；请先查看升级状态或恢复该操作")




    @contextmanager
    def executor(self) -> Iterator[None]:
        self._safe_root(create=True)
        key = str(self.project)
        owned = getattr(_LOCAL, "maintenance_executors", frozenset())
        if key in owned:
            yield
            return
        with _locked(self.root / "executor.lock", timeout=0):
            _LOCAL.maintenance_executors = owned | {key}
            try:
                yield
            finally:
                _LOCAL.maintenance_executors = owned

    def read_upgrade_record(self, upgrade_id: str) -> dict[str, Any]:
        self._safe_root()
        if not isinstance(upgrade_id, str) or not upgrade_id.startswith("UPGRADE-") or not upgrade_id.removeprefix("UPGRADE-").isalnum():
            raise MaintenanceError("upgrade_id_invalid", "升级身份无效")
        path = self.root / upgrade_id / "journal.json"
        if path.is_symlink() or path.parent.is_symlink() or path.parent.is_junction():
            raise MaintenanceError("upgrade_journal_invalid", "升级记录路径不安全")
        try:
            if path.stat().st_size > 64 * 1024 * 1024:
                raise ValueError
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("schema_version") != "strixnova.runtime-upgrade-journal.v1" or value.get("upgrade_id") != upgrade_id or value.get("project") != str(self.project):
                raise ValueError
            if value.get("state") not in {"prepared", "backed_up", "fencing", "verified", "switching", "completed", "restoring", "restored", "aborted"}:
                raise ValueError
            if value.get("journal_sha256") != _maintenance_record_digest({key: entry for key, entry in value.items() if key != "journal_sha256"}):
                raise ValueError
            plan = value["plan"]
            if plan.get("project") != str(self.project) or plan.get("plan_id") != "UPLAN-" + _maintenance_record_digest({key: entry for key, entry in plan.items() if key != "plan_id"}):
                raise ValueError
            if upgrade_id != "UPGRADE-" + hashlib.sha256(plan["plan_id"].encode()).hexdigest()[:24].upper():
                raise ValueError
            kinds = {"authority": ".strixnova/authority.sqlite3", "delivery_activities": ".strixnova/delivery-activities.sqlite3"}
            if not isinstance(value.get("replacements"), list) or len({entry.get("kind") for entry in value["replacements"]}) != len(value["replacements"]):
                raise ValueError
            if any(entry.get("kind") not in kinds or entry.get("target") != kinds[entry["kind"]] for entry in value["replacements"]):
                raise ValueError
            return value
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as error:
            raise MaintenanceError("upgrade_journal_invalid", "无法读取精确升级记录") from error

    def validate_initialization_artifacts(self) -> None:
        """Recognize bootstrap coordination material without accepting lost business data."""
        self._safe_root()
        artifacts = self.root.parent
        if not artifacts.exists():
            return

        def invalid() -> None:
            raise MaintenanceError("unsupported_authority_format", "首次建库发现无法识别的原有材料；未初始化，也未删除任何内容")

        if any(path.name != "maintenance" for path in artifacts.iterdir()):
            invalid()
        if not self.root.exists():
            return
        records = {}
        recovery = None
        for path in self.root.iterdir():
            if path.is_symlink() or path.is_junction():
                raise MaintenanceError("maintenance_path_unsafe", "首次建库的维护材料不能经过链接")
            if path.name == "operation-recovery" and path.is_dir():
                recovery = path
            elif path.is_file() and re.fullmatch(r"operation-[0-9a-f]{32}\.json", path.name):
                try:
                    value, _ = self._operation_record(path)
                except FileNotFoundError:
                    continue
                if value.get("operation") not in {"installation-prepare", "authority-initialize"}:
                    invalid()
                records[path.stem] = value
            elif not (path.is_file() and path.stat().st_size <= 1 and (
                path.name in {"admission.lock", "executor.lock"}
                or re.fullmatch(r"(?:installation-[0-9a-f]{64}|operation-[0-9a-f]{32})\.lock", path.name)
            )):
                invalid()
        if recovery is not None:
            for directory in recovery.iterdir():
                value = records.get(directory.name, {})
                if directory.is_symlink() or directory.is_junction() or not directory.is_dir() or value.get("state") != "resolved":
                    invalid()
                stop_evidence = value.get("stop_evidence")
                materials = stop_evidence.get("evidence_files") if isinstance(stop_evidence, dict) else None
                if not isinstance(materials, list):
                    invalid()
                expected = {f"{index:02d}-{material.get('sha256')}.evidence" for index, material in enumerate(materials) if isinstance(material, dict)}
                if len(expected) != len(materials) or {path.name for path in directory.iterdir()} != expected:
                    invalid()
                for path in directory.iterdir():
                    if path.is_symlink() or path.is_junction() or not path.is_file():
                        invalid()
                    with path.open("rb") as source:
                        if hashlib.file_digest(source, "sha256").hexdigest() != path.name.split("-", 1)[1].removesuffix(".evidence"):
                            invalid()


    @contextmanager
    def authority_initialization(self) -> Iterator[None]:
        """Serialize first storage creation with installation and maintenance."""
        self.assert_available()
        self.validate_initialization_artifacts()
        with self.executor(), ExitStack() as locks:
            self.assert_available()
            # Include locks left by older installers using the per-root lock.
            for path in self.root.glob("installation-*.lock"):
                try:
                    locks.enter_context(_locked(path, timeout=0))
                except MaintenanceError as error:
                    if error.code == "maintenance_busy":
                        raise MaintenanceError("installation_busy", "安装仍在进行，尚未创建事项数据库") from error
                    raise
            if not (self.project / ".strixnova/authority.sqlite3").exists():
                self.validate_initialization_artifacts()
                pending = self.unclosed_operations()
                if pending:
                    raise MaintenanceError("operation_recovery_required", "首次建库前必须等待或恢复尚未收口的安装操作", details=pending)
            with _operation_lease(self, read_only=False, operation_name="authority-initialize"):
                yield

    def _operation_record(self, path: Path) -> tuple[dict[str, Any], bytes]:
        if path.is_symlink() or path.is_junction() or not path.is_file() or path.stat().st_size > 65536:
            raise MaintenanceError("operation_record_invalid", "操作记录不是有界普通文件")
        try:
            raw = path.read_bytes()
            value = json.loads(raw)
            if (value.get("schema_version") != "strixnova.project-operation.v1"
                or value.get("project") != str(self.project) or value.get("operation_id") != path.stem
                or not re.fullmatch(r"operation-[0-9a-f]{32}", path.stem)
                or value.get("state") not in {"running", "finished", "resolved"}):
                raise ValueError
            return value, raw
        except (ValueError, TypeError, AttributeError) as error:
            raise MaintenanceError("operation_record_invalid", "操作记录损坏或不属于当前项目，不能推断执行已经停止", details={"operation_id": path.stem}) from error

    def unclosed_operations(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Read durable starts; a released OS lock is not a completion receipt."""
        self._safe_root()
        records = []
        for path in sorted(self.root.glob("operation-*.json")):
            try:
                value, raw = self._operation_record(path)
                if value["state"] != "running":
                    continue
                active = False
                lock_path = path.with_suffix(".lock")
                if lock_path.is_symlink():
                    raise ValueError
                if lock_path.exists():
                    with lock_path.open("r+b") as stream:
                        try:
                            _lock(stream)
                        except OSError:
                            active = True
                        else:
                            _unlock(stream)
                records.append({**value, "state": "running" if active else "interrupted", "record_sha256": hashlib.sha256(raw).hexdigest()})
                if len(records) >= limit:
                    break
            except FileNotFoundError:
                # A normally finished writer may remove its receipt meanwhile.
                continue
            except (OSError, ValueError, TypeError, AttributeError) as error:
                raise MaintenanceError("operation_record_invalid", "操作结束记录缺失或损坏，不能推断执行已经停止", details={"operation_id": path.stem}) from error
        return records

    def _start_write_record(self, lease: dict[str, Any], operation_name: str) -> None:
        if lease.get("record") is not None:
            return
        path = lease["path"].with_suffix(".json")
        record = {
            "schema_version": "strixnova.project-operation.v1", "operation_id": path.stem,
            "project": str(self.project), "operation": operation_name,
            "state": "running", "started_at": datetime.now(timezone.utc).isoformat(),
            "process_id": os.getpid(),
        }
        write_maintenance_json(path, record)
        lease["record"] = record

    def resolve_operation(self, operation_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        """Record external stop evidence without replaying or discarding work."""
        if not isinstance(operation_id, str) or not re.fullmatch(r"operation-[0-9a-f]{32}", operation_id):
            raise MaintenanceError("operation_id_invalid", "需要明确的未收口操作身份")
        self._safe_root()
        path = self.root / (operation_id + ".json")
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise MaintenanceError("operation_record_invalid", "没有可恢复的普通操作记录")
        with _locked(self.root / "admission.lock"), _locked(path.with_suffix(".lock"), timeout=0):
            try:
                raw = path.read_bytes()
                original = json.loads(raw)
                if original.get("schema_version") != "strixnova.project-operation.v1" or original.get("operation_id") != operation_id or original.get("project") != str(self.project):
                    raise ValueError
                if original.get("state") == "resolved":
                    if original.get("stop_evidence") != evidence:
                        raise ValueError
                    return {"operation_id": operation_id, "state": "resolved", "external_truth_machine_proven": False}
                if original.get("state") != "running":
                    raise ValueError
                scope = {"kind": "project_operation", "project": str(self.project), "operation_id": operation_id, "record_sha256": hashlib.sha256(raw).hexdigest()}
                validated = validate_stop_evidence(evidence, scope)
                directory = self.root / "operation-recovery" / operation_id
                for target in (directory.parent, directory):
                    if target.is_symlink() or target.is_junction() or (target.exists() and not target.is_dir()):
                        raise ValueError
                directory.mkdir(parents=True, exist_ok=True)
                for index, reference in enumerate(validated["evidence_files"]):
                    content = Path(reference["path"]).read_bytes()
                    if hashlib.sha256(content).hexdigest() != reference["sha256"]:
                        raise ExecutionStopEvidenceError("execution_stop_evidence_changed", "归档前停机证据字节发生变化")
                    destination = directory / f"{index:02d}-{reference['sha256']}.evidence"
                    if destination.is_symlink():
                        raise ValueError
                    if destination.exists():
                        if destination.read_bytes() != content:
                            raise ValueError
                    else:
                        with destination.open("xb") as output:
                            output.write(content)
                            output.flush()
                            os.fsync(output.fileno())
                write_maintenance_json(path, {
                    **original, "state": "resolved", "resolved_at": datetime.now(timezone.utc).isoformat(),
                    "original_record_base64": base64.b64encode(raw).decode("ascii"),
                    "stop_evidence": validated, "external_truth_machine_proven": False,
                })
            except ExecutionStopEvidenceError as error:
                raise MaintenanceError(error.code, str(error)) from error
            except (OSError, ValueError, TypeError, AttributeError) as error:
                raise MaintenanceError("operation_recovery_invalid", "操作记录、恢复请求或证据材料不一致，未收口为已停止") from error
        return {"operation_id": operation_id, "state": "resolved", "external_truth_machine_proven": False}

    def begin(self, upgrade_id: str, *, timeout: float = 30.0) -> None:
        if not isinstance(upgrade_id, str) or not _ID.fullmatch(upgrade_id):
            raise MaintenanceError("upgrade_id_invalid", "升级身份无效")
        self._safe_root(create=True)
        with _locked(self.root / "admission.lock"):
            active = self.status()
            if active["state"] != "clear" and active["upgrade_id"] != upgrade_id:
                raise MaintenanceError("project_under_maintenance", "另一个升级尚未恢复")
            if active["state"] == "clear":
                write_maintenance_json(self.active_path, {
                    "schema_version": "strixnova.project-maintenance.v1", "upgrade_id": upgrade_id,
                    "started_at": datetime.now(timezone.utc).isoformat(),
                })
        deadline = time.monotonic() + timeout
        while True:
            interrupted = [record for record in self.unclosed_operations() if record["state"] == "interrupted"]
            if interrupted:
                raise MaintenanceError("maintenance_unclosed_operations", "旧操作没有结束记录，不能仅凭进程锁释放就继续升级", details=interrupted)
            active_leases = []
            for path in self.root.glob("operation-*.lock"):
                try:
                    with _locked(path, timeout=0):
                        pass
                    try:
                        path.unlink(missing_ok=True)
                    except OSError:
                        # An unlocked leftover is not an active operation.
                        # A Windows scanner may still hold a closing handle.
                        pass
                except MaintenanceError as error:
                    if error.code != "maintenance_busy":
                        raise
                    active_leases.append(path.name)
            if not active_leases:
                interrupted = [record for record in self.unclosed_operations() if record["state"] == "interrupted"]
                if interrupted:
                    raise MaintenanceError("maintenance_unclosed_operations", "操作在排空期间中断且没有结束记录，必须先核验停止依据", details=interrupted)
                return
            if time.monotonic() >= deadline:
                raise MaintenanceError("maintenance_operations_pending", "已有操作或验证回写尚未结束", details=active_leases)
            time.sleep(0.025)

    def finish(self, upgrade_id: str) -> None:
        with _locked(self.root / "admission.lock"):
            if self.status().get("upgrade_id") != upgrade_id:
                raise MaintenanceError("upgrade_identity_mismatch", "只能结束当前精确升级")
            self.active_path.unlink()
            _sync_directory(self.root)


@contextmanager
def project_operation(project_dir: str | Path, *, read_only: bool = False, writer_format: int | None = None, activity_format: int | None = None, operation_name: str = "project-write") -> Iterator[None]:
    if not isinstance(operation_name, str) or not operation_name.strip() or len(operation_name) > 128:
        raise MaintenanceError("operation_name_invalid", "操作名称必须是有界的内部用途说明")
    maintenance = ProjectMaintenance(project_dir)
    expected_authority = AUTHORITY_FORMAT if writer_format is None else writer_format
    expected_activity = ACTIVITY_FORMAT if activity_format is None else activity_format
    if type(expected_authority) is not int or expected_authority < 1 or type(expected_activity) is not int or expected_activity < 1:
        raise MaintenanceError("maintenance_contract_invalid", "运行程序声明的格式合同无效")
    key = str(maintenance.project)
    trial = getattr(_LOCAL, "maintenance_reads", {}).get(key)
    if trial is not None:
        if not read_only:
            raise MaintenanceError("maintenance_trial_read_only", "维护试读不能执行任何业务写入")
        if maintenance.status().get("upgrade_id") != trial:
            raise MaintenanceError("upgrade_identity_mismatch", "维护身份已变化，停止试读")
        yield
        return
    owned = getattr(_LOCAL, "operations", {})
    if key in owned:
        if not read_only:
            maintenance._start_write_record(owned[key], operation_name)
        yield
        return
    maintenance.assert_available()
    database = maintenance.project / ".strixnova" / "authority.sqlite3"
    activity = maintenance.project / ".strixnova" / "delivery-activities.sqlite3"
    if not database.exists() and not activity.exists():
        yield
        return
    # Old or corrupt input must still fail at its original read-before-write
    # boundary. Do not create support files while merely identifying it.
    authority_version = None
    if database.exists():
        try:
            connection = sqlite3.connect(f"{database.as_uri()}?mode=ro", uri=True)
            try:
                row = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            finally:
                connection.close()
            authority_version = str(row[0]) if row is not None else None
            supported = authority_version == str(AUTHORITY_FORMAT)
        except sqlite3.Error as error:
            initializing = [record for record in maintenance.unclosed_operations() if record.get("operation") == "authority-initialize"]
            if initializing:
                raise MaintenanceError("authority_initialization_pending", "事项数据库正在首次建立或尚未收口，请等待完成或恢复该操作", details=initializing) from error
            code = getattr(error, "sqlite_errorcode", 0) or 0
            raise MaintenanceError("maintenance_probe_failed" if code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CANTOPEN} else "unsupported_authority_format", "无法确定事项存储格式，未开始任何受管操作") from error
        if not supported:
            raise MaintenanceError("unsupported_authority_format", "事项存储格式不受当前构建支持")
        if not read_only and int(row[0]) != expected_authority:
            raise MaintenanceError("authority_upgrade_required", "事项数据需要显式升级，请先运行 upgrade check")
    if activity.exists():
        try:
            connection = sqlite3.connect(f"{activity.as_uri()}?mode=ro", uri=True)
            try:
                row = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
            finally:
                connection.close()
            supported = row is not None and str(row[0]) == str(expected_activity)
        except sqlite3.Error as error:
            code = getattr(error, "sqlite_errorcode", 0) or 0
            raise MaintenanceError("maintenance_probe_failed" if code & 255 in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_CANTOPEN} else "unsupported_activity_format", "无法确定活动存储格式，未开始任何受管操作") from error
        if not supported:
            raise MaintenanceError("unsupported_activity_format", "活动存储格式不受当前构建支持")
    if read_only and not maintenance.root.exists():
        yield
        return
    with _operation_lease(maintenance, read_only=read_only, operation_name=operation_name):
        yield


@contextmanager
def installation_preparation(project_dir: str | Path) -> Iterator[None]:
    """Track venv/pip lifetimes even before a project has business storage."""
    maintenance = ProjectMaintenance(project_dir)
    interrupted = [record for record in maintenance.unclosed_operations() if record["state"] == "interrupted"]
    if interrupted:
        raise MaintenanceError("operation_recovery_required", "安装准备有未收口执行，先核验旧子进程及其写入已停止", details=interrupted)
    with _operation_lease(maintenance, read_only=False, operation_name="installation-prepare"):
        yield


@contextmanager
def _operation_lease(maintenance: ProjectMaintenance, *, read_only: bool, operation_name: str) -> Iterator[None]:
    key = str(maintenance.project)
    owned = getattr(_LOCAL, "operations", {})
    if key in owned:
        if not read_only:
            maintenance._start_write_record(owned[key], operation_name)
        yield
        return
    maintenance._safe_root(create=True)
    path = maintenance.root / f"operation-{uuid.uuid4().hex}.lock"
    lease = None
    entry = {"path": path, "record": None}
    settled = False
    try:
        with _locked(maintenance.root / "admission.lock"):
            maintenance.assert_available()
            lease = _locked(path, timeout=0)
            lease.__enter__()
            if not read_only:
                maintenance._start_write_record(entry, operation_name)
            _LOCAL.operations = {**owned, key: entry}
        yield
        settled = True
    except Exception as error:
        settled = True
        current: BaseException | None = error
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            if getattr(current, "reason", None) == "cleanup_failed":
                settled = False
                break
            current = current.__cause__ or current.__context__
        raise
    finally:
        if lease is not None:
            record = entry.get("record")
            if settled and record is not None:
                record_path = path.with_suffix(".json")
                try:
                    write_maintenance_json(record_path, {**record, "state": "finished", "finished_at": datetime.now(timezone.utc).isoformat()})
                    record_path.unlink(missing_ok=True)
                except OSError:
                    # Keep a durable unknown if finishing could not be saved.
                    # Bookkeeping must not overturn a committed business result.
                    pass
            _LOCAL.operations = owned
            lease.__exit__(None, None, None)
            try:
                path.unlink(missing_ok=True)
            except OSError:
                # The lease is already unlocked and closed. Housekeeping must
                # never turn a committed business operation into a failure.
                pass


class _MaintainedConnection(sqlite3.Connection):
    _project_lease: Any = None

    def close(self) -> None:
        try:
            super().close()
        finally:
            if self._project_lease is not None:
                lease, self._project_lease = self._project_lease, None
                lease.__exit__(None, None, None)


def connect_with_maintenance(project: Path, target: str | Path, *, read_only: bool, **kwargs: Any) -> sqlite3.Connection:
    lease = project_operation(project, read_only=read_only)
    lease.__enter__()
    try:
        connection = sqlite3.connect(target, factory=_MaintainedConnection, **kwargs)
        connection._project_lease = lease
        return connection
    except BaseException:
        lease.__exit__(None, None, None)
        raise
