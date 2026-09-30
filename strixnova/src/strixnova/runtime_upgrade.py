"""Explicit current-format runtime maintenance with preserved records and recoverable copies."""

from __future__ import annotations

from contextlib import closing, nullcontext
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import sqlite3
from typing import Any, Mapping

from strixnova.runtime_identity import runtime_identity
from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance, write_maintenance_json
from strixnova.storage_formats import AUTHORITY_FORMAT, ACTIVITY_FORMAT, MAINTENANCE_TRIGGER_PREFIX, install_write_guards, remove_write_guards, write_guard_definitions
from strixnova.managed_installation import ManagedInstallation
from strixnova.project_authority_consistency import ProjectAuthorityConsistency, ProjectAuthorityConsistencyError
from strixnova.project_engineering_baseline import AUTHORITY_KINDS
from strixnova.work_item_history import WorkItemHistory, HistoryQueryError
from strixnova.workflow_authority import WorkflowAuthorityError
from strixnova.execution_stop_evidence import stop_evidence_contract
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.project_context import ProjectContextResolver


class RuntimeUpgradeError(MaintenanceError):
    pass


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value)).hexdigest()


def _file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


_TABLE_ORDER = {
    "metadata": "key", "work_items": "work_item_id", "events": "sequence",
    "sqlite_sequence": "name", "evidence_outputs": "work_item_id,receipt_id,stream",
    "activities": "activity_id", "activity_events": "activity_id,event_version",
    "event_annotations": "event_sequence",
}


def _database_snapshot(path: Path, kind: str, *, existing_connection: sqlite3.Connection | None = None) -> dict[str, Any]:
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise RuntimeUpgradeError("upgrade_source_invalid", "升级源必须是普通数据库文件")
    try:
        scope = nullcontext(existing_connection) if existing_connection is not None else closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True))
        with scope as connection:
            if existing_connection is None:
                connection.execute("PRAGMA query_only=ON")
                connection.execute("BEGIN")
            if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or connection.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeUpgradeError("upgrade_integrity_failed", "源数据库完整性检查失败")
            names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if names - _TABLE_ORDER.keys():
                raise RuntimeUpgradeError("upgrade_source_invalid", "源数据库包含未声明的表")
            raw_version = connection.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()[0]
            version = int(raw_version)
            if str(version) != str(raw_version):
                raise ValueError("noncanonical format")
            if kind == "authority":
                if version != AUTHORITY_FORMAT:
                    raise RuntimeUpgradeError("unsupported_upgrade_source", "只支持当前声明的 Authority 格式")
                required = {"metadata", "work_items", "events"}
            else:
                if version != ACTIVITY_FORMAT:
                    raise RuntimeUpgradeError("unsupported_upgrade_source", "活动库格式不受当前升级器支持")
                required = {"metadata", "activities", "activity_events"}
            if not required <= names:
                raise RuntimeUpgradeError("upgrade_source_invalid", "源数据库缺少必要的表")
            if kind == "authority" and not {"evidence_outputs", "event_annotations"} <= names:
                raise RuntimeUpgradeError("upgrade_source_invalid", "当前格式缺少历史或证据表，不能隐式修复")
            columns = {
                "work_items": "work_item_id,title,status,version,data_json,created_at,updated_at",
                "events": "sequence,work_item_id,version,event_type,payload_json,recorded_at",
                "evidence_outputs": "work_item_id,receipt_id,stream,relative_path,sha256,size_bytes,observation_kind,observed_at,availability",
                "event_annotations": "event_sequence,work_item_id,record_json",
                "activities": "activity_id,version,state,payload", "activity_events": "activity_id,event_version,event_kind,recorded_at,payload",
            }
            for table in names & columns.keys():
                connection.execute(f"SELECT {columns[table]} FROM {table} LIMIT 0")
            schema = [dict(zip(("type", "name", "tbl_name", "sql"), row)) for row in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
            complete, business = hashlib.sha256(), hashlib.sha256()
            counts = {}
            for name in sorted(names):
                complete.update(_json(name))
                if name in {"work_items", "events", "activities", "activity_events"}:
                    business.update(_json(name))
                count = 0
                for row in connection.execute(f'SELECT * FROM "{name}" ORDER BY {_TABLE_ORDER[name]}'):
                    encoded = _json(list(row))
                    complete.update(encoded)
                    if name in {"work_items", "events", "activities", "activity_events"}:
                        business.update(encoded)
                    if name == "event_annotations":
                        if count == 0:
                            business.update(_json(name))
                        business.update(encoded)
                    count += 1
                counts[name] = count
            if kind == "authority":
                for item_version, raw in connection.execute("SELECT version,data_json FROM work_items"):
                    data = json.loads(raw)
                    if not isinstance(data, dict) or type(item_version) is not int or item_version < 1:
                        raise ValueError("invalid item data")
                    if data.get("pending_effect") is not None:
                        raise RuntimeUpgradeError("upgrade_pending_effect", "事项还有未完成的副作用，必须先恢复")
                for (raw,) in connection.execute("SELECT payload_json FROM events"):
                    json.loads(raw)
            if "event_annotations" in names:
                for (raw,) in connection.execute("SELECT record_json FROM event_annotations"):
                    value = json.loads(raw)
                    if not isinstance(value, dict) or value.get("schema_version") != "strixnova.recorded-history-facts.v1":
                        raise ValueError("invalid recorded history")
            data_sha = complete.hexdigest()
            project_identity = None
            if kind == "authority":
                binding = connection.execute("SELECT value FROM metadata WHERE key='project_id'").fetchone()
                project_identity = binding[0] if binding is not None else None
                if project_identity is not None and re.fullmatch(r"PROJECT-[0-9A-F]{16}", project_identity) is None:
                    raise ValueError("invalid stored project identity")
            return {"format": version, "sha256": _digest({"data": data_sha, "schema": schema}), "data_sha256": data_sha, "schema": schema, "business_sha256": business.hexdigest(), "counts": counts, "project_id": project_identity}
    except RuntimeUpgradeError:
        raise
    except (sqlite3.Error, ValueError, TypeError, IndexError) as error:
        raise RuntimeUpgradeError("upgrade_source_invalid", "无法按声明格式读取源数据库") from error


class RuntimeUpgrade:
    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        if not self.project.is_dir():
            raise RuntimeUpgradeError("project_missing", "升级项目目录不存在")
        self.maintenance = ProjectMaintenance(self.project)

    def _sources(self) -> dict[str, Path]:
        authority = self.project / ".strixnova" / "authority.sqlite3"
        paths = {"authority": authority} if authority.exists() or authority.is_symlink() else {}
        activity = self.project / ".strixnova" / "delivery-activities.sqlite3"
        if activity.exists():
            paths["delivery_activities"] = activity
        return paths

    @staticmethod
    def _matches_original_or_fenced(current: Mapping[str, Any], original: Mapping[str, Any]) -> bool:
        if current == original:
            return True
        if current.get("format") != original.get("format") or current.get("data_sha256") != original.get("data_sha256"):
            return False
        extras = [entry for entry in current["schema"] if entry["name"].startswith(MAINTENANCE_TRIGGER_PREFIX)]
        retained = [entry for entry in current["schema"] if not entry["name"].startswith(MAINTENANCE_TRIGGER_PREFIX)]
        tables = {entry["name"] for entry in original["schema"] if entry["type"] == "table"}
        expected = sorted(write_guard_definitions(tables, temporary=True), key=lambda entry: (entry["type"], entry["name"]))
        return retained == original["schema"] and extras == expected

    def _quiesce(self, path: Path) -> None:
        try:
            with closing(sqlite3.connect(path, timeout=0.5, isolation_level=None)) as connection:
                checkpoint = connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
                if checkpoint and checkpoint[0] != 0:
                    raise sqlite3.OperationalError("WAL checkpoint blocked")
                mode = connection.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
                if str(mode).casefold() != "delete":
                    raise sqlite3.OperationalError("journal mode remains active")
                connection.execute("BEGIN EXCLUSIVE")
                connection.rollback()
        except sqlite3.Error as error:
            raise RuntimeUpgradeError("upgrade_connections_open", "仍有数据库连接或写入未退出，不能安全切换；关闭旧客户端后恢复", details={"database": path.name}) from error

    def _fence_sources(self, journal: dict[str, Any]) -> None:
        journal["state"] = "fencing"
        self._save(journal)
        for kind, path in sorted(self._sources().items(), key=lambda entry: entry[0] == "authority"):
            with closing(sqlite3.connect(path, timeout=0.5, isolation_level=None)) as connection:
                connection.execute("BEGIN EXCLUSIVE")
                try:
                    current = _database_snapshot(path, kind, existing_connection=connection)
                    if not self._matches_original_or_fenced(current, journal["plan"]["sources"][kind]):
                        raise RuntimeUpgradeError("upgrade_source_changed", "取得排他写入保护时源数据已经变化")
                    install_write_guards(connection, temporary=True)
                    connection.commit()
                except BaseException:
                    connection.rollback()
                    raise

    def _assets(self) -> dict[str, dict[str, Any]]:
        root = self.project / ".strixnova" / "artifacts"
        values: dict[str, dict[str, Any]] = {}
        for directory, folders, files in os.walk(root, followlinks=False) if root.exists() else ():
            parent = Path(directory)
            if parent == root:
                folders[:] = [name for name in folders if name != "maintenance"]
            for name in [*folders, *files]:
                candidate = parent / name
                if candidate.is_symlink() or candidate.is_junction():
                    raise RuntimeUpgradeError("upgrade_evidence_path_unsafe", "证据目录包含链接，不能安全备份")
            for name in files:
                path = parent / name
                values[path.relative_to(self.project).as_posix()] = {"sha256": _file_digest(path), "size_bytes": path.stat().st_size}
        configuration = self.project / "strixnova-project.yaml"
        if configuration.is_symlink():
            raise RuntimeUpgradeError("upgrade_project_documents_invalid", "项目配置不能是链接")
        if configuration.exists():
            try:
                checker = ProjectAuthorityConsistency(self.project)
                try:
                    authorities = checker.load()
                except ProjectAuthorityConsistencyError:
                    authorities = checker.load_working_tree_candidate(None)
                paths = {"strixnova-project.yaml", checker.baseline_reader.locate().relative_to(self.project).as_posix()}
                for kind in AUTHORITY_KINDS:
                    paths.update(checker.authority_governed_paths(authorities, kind))
                for relative in sorted(paths):
                    target = checker.reader.absolute_path(relative)
                    values[relative] = {"sha256": _file_digest(target), "size_bytes": target.stat().st_size}
            except (ProjectAuthorityConsistencyError, OSError, ValueError) as error:
                raise RuntimeUpgradeError("upgrade_project_documents_invalid", "项目长期文件的格式或精确引用不满足当前程序合同；升级不能隐式改写这些文件", details={"reason": str(error)}) from error
        return values

    def _inspect(self, installation: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.maintenance._safe_root()
        for relative in (".strixnova/artifacts/document-transactions", ".strixnova/artifacts/implementation-alignment/transactions"):
            transactions = self.project / relative
            if transactions.is_symlink() or transactions.is_junction():
                raise RuntimeUpgradeError("upgrade_pending_document_transaction", "文件事务目录不是普通目录")
            if transactions.exists() and any(transactions.iterdir()):
                raise RuntimeUpgradeError("upgrade_pending_document_transaction", "仍有未收口的文件事务，必须先恢复")
        if (self.project / ".git").exists():
            try:
                pending = GitProjectReader(self.project).pending_operations()
            except GitProjectReaderError as error:
                raise RuntimeUpgradeError("upgrade_git_state_invalid", "无法核验项目真实 Git 状态，不能切换", details={"reason": error.code}) from error
            if pending:
                raise RuntimeUpgradeError("upgrade_pending_git_operation", "仍有未结束的 Git 操作，不能切换", details={"operations": pending})
        sources = {kind: _database_snapshot(path, kind) for kind, path in self._sources().items()}
        if "authority" not in sources:
            raise RuntimeUpgradeError("upgrade_source_invalid", "没有可维护的事项库；新项目应先初始化")
        context = ProjectContextResolver(self.project).configured()
        stored_identity = sources["authority"].get("project_id")
        project_identity = context.project_id if context is not None else stored_identity
        if stored_identity is not None and stored_identity != project_identity:
            raise RuntimeUpgradeError("authority_project_mismatch", "管理库和声明的项目身份不一致，不能覆盖归属")
        interrupted = [record for record in self.maintenance.unclosed_operations() if record["state"] == "interrupted"]
        if interrupted:
            raise RuntimeUpgradeError("upgrade_unclosed_operations", "存在没有结束记录的执行，必须先核验执行停止及实际副作用", details=interrupted)
        target = runtime_identity()
        install_plan = None
        if installation is not None:
            required = {"installation_root", "target_wheel", "source_python", "builder_python", "wheelhouse"}
            if not isinstance(installation, Mapping) or set(installation) != required:
                raise RuntimeUpgradeError("upgrade_installation_request_invalid", "安装升级请求字段不完整")
            manager = ManagedInstallation(installation["installation_root"], self.project)
            install_plan = manager.plan(installation["target_wheel"], source_python=installation["source_python"], builder_python=installation["builder_python"], wheelhouse=installation["wheelhouse"])
            if install_plan["source_runtime"]["authority_format"] != AUTHORITY_FORMAT or install_plan["source_runtime"]["activity_format"] != ACTIVITY_FORMAT:
                raise RuntimeUpgradeError("source_runtime_format_mismatch", "源程序与当前数据格式不匹配")
            declared = install_plan["target"]
            if declared["formats"] != target["formats"]:
                raise RuntimeUpgradeError("unsupported_upgrade_target", "目标程序必须支持当前完整数据格式；本版本不执行格式转换")
            target = {"schema_version": "strixnova.runtime-identity.v1", "identity_source": "wheel_declaration", **{key: declared[key] for key in ("version", "build_sha256", "skill_sha256", "package_file_count", "formats", "dependency_lock_sha256")}}
        plan = {
            "schema_version": "strixnova.runtime-upgrade-plan.v1", "project": str(self.project),
            "source_formats": {kind: value["format"] for kind, value in sources.items()},
            "target_formats": target["formats"], "sources": sources, "assets": self._assets(),
            "target_runtime": target, "project_identity": project_identity,
            "requires_maintenance_window": True,
            "writes_performed": False, "maintenance_revision": self._last_closed(),
            "installation": install_plan,
        }
        plan["plan_id"] = "UPLAN-" + _digest(plan)
        return plan

    def _last_closed(self) -> Any:
        path = self.maintenance.root / "last-closed.json"
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
            raise RuntimeUpgradeError("upgrade_journal_invalid", "维护修订记录不安全")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {"upgrade_id", "state"}:
                raise ValueError
            return value
        except (OSError, ValueError, TypeError) as error:
            raise RuntimeUpgradeError("upgrade_journal_invalid", "维护修订记录损坏") from error

    def _close(self, journal: dict[str, Any]) -> dict[str, Any]:
        self._save(journal)
        write_maintenance_json(self.maintenance.root / "last-closed.json", {"upgrade_id": journal["upgrade_id"], "state": journal["state"]})
        self.maintenance.finish(journal["upgrade_id"])
        return journal

    def check(self, *, installation: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self.maintenance.assert_available()
        return self._inspect(installation)



    def operations(self) -> dict[str, Any]:
        records = self.maintenance.unclosed_operations()
        return {
            "schema_version": "strixnova.operation-recovery-catalog.v1", "project": str(self.project),
            "operations": [{**record, "stop_evidence_scope": {
                "kind": "project_operation", "project": str(self.project),
                "operation_id": record["operation_id"], "record_sha256": record["record_sha256"],
            }} for record in records],
            "may_have_more": len(records) == 100, "writes_performed": False,
        }

    def resolve_operation(self, operation_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        return self.maintenance.resolve_operation(operation_id, evidence)

    @staticmethod
    def plan_view(plan: Mapping[str, Any]) -> dict[str, Any]:
        fields = ("schema_version", "project", "plan_id", "source_formats", "target_formats", "target_runtime", "requires_maintenance_window", "writes_performed", "maintenance_revision")
        return {
            "project_identity": plan.get("project_identity"),
            **{key: plan[key] for key in fields},
            "asset_count": len(plan["assets"]),
            "asset_bytes": sum(value["size_bytes"] for value in plan["assets"].values()),
            "record_counts": {kind: source["counts"] for kind, source in plan["sources"].items()},
            "installation": plan.get("installation"),
        }

    @staticmethod
    def status_view(journal: Mapping[str, Any]) -> dict[str, Any]:
        fields = ("schema_version", "project", "upgrade_id", "state", "backup_directory", "created_at", "completed_at", "restored_at", "business_records_preserved", "failure", "runtime_selection", "restored_runtime", "host_reload_required", "entrypoint_validation", "aborted_before_source_change")
        state = journal.get("state")
        return {
            **{key: journal[key] for key in fields if key in journal},
            "recovery_modes": ["resume", "restore"] if state in {"verified", "switching"} else ["restore"] if state in {"prepared", "backed_up", "fencing", "restoring", "completed"} else [],
        }

    def status(self, upgrade_id: str | None = None) -> dict[str, Any]:
        self.maintenance._safe_root()
        if upgrade_id is None:
            active = self.maintenance.status()
            upgrade_id = active.get("upgrade_id")
            if upgrade_id is None:
                return {"state": "clear", "upgrade_id": None}
        try:
            return self.maintenance.read_upgrade_record(upgrade_id)
        except MaintenanceError as error:
            raise RuntimeUpgradeError(error.code, str(error), details=error.details) from error

    def _save(self, journal: dict[str, Any]) -> None:
        self.maintenance._safe_root()
        directory = self.maintenance.root / journal["upgrade_id"]
        if directory.is_symlink() or directory.is_junction() or (directory.exists() and not directory.is_dir()):
            raise RuntimeUpgradeError("upgrade_journal_invalid", "升级会话目录必须是受控普通目录")
        journal["journal_sha256"] = _digest({key: value for key, value in journal.items() if key != "journal_sha256"})
        write_maintenance_json(directory / "journal.json", journal)

    def _existing_attempt(self, plan: Mapping[str, Any], upgrade_id: str) -> dict[str, Any] | None:
        self.maintenance._safe_root()
        directory = self.maintenance.root / upgrade_id
        if directory.is_symlink() or directory.is_junction():
            raise RuntimeUpgradeError("upgrade_journal_invalid", "升级会话目录不能通过链接访问")
        if not directory.exists():
            return None
        if not directory.is_dir() or not (directory / "journal.json").is_file():
            raise RuntimeUpgradeError("upgrade_directory_occupied", "升级目录已被没有完整记录的内容占用")
        previous = self.status(upgrade_id)
        if dict(plan) != previous["plan"] and dict(plan) != self.plan_view(previous["plan"]):
            raise RuntimeUpgradeError("upgrade_plan_invalid", "重复请求必须与原升级计划完全一致")
        if previous["state"] == "completed":
            return previous
        raise RuntimeUpgradeError("upgrade_recovery_required", "该升级未完成或已中止，请查看状态并重新预检")

    def _abort_before_source_change(self, journal: dict[str, Any]) -> dict[str, Any]:
        """Close an attempt that has not fenced or replaced any source file."""
        if journal["state"] not in {"prepared", "backed_up", "aborted"}:
            raise RuntimeUpgradeError("upgrade_recovery_required", "已经改变源存储的尝试必须按恢复记录处理")
        journal["state"] = "aborted"
        journal["aborted_before_source_change"] = not journal.get("source_fences_removed", False)
        journal["aborted_before_replacement"] = True
        journal.setdefault("aborted_at", datetime.now(timezone.utc).isoformat())
        self._save(journal)
        active = self.maintenance.status()
        if active["state"] == "clear" or active.get("upgrade_id") == journal["upgrade_id"]:
            write_maintenance_json(self.maintenance.root / "last-closed.json", {"upgrade_id": journal["upgrade_id"], "state": "aborted"})
            if active["state"] != "clear":
                self.maintenance.finish(journal["upgrade_id"])
        return journal

    def _abort_fenced_sources(self, journal: dict[str, Any]) -> dict[str, Any]:
        """Undo only our guards before any candidate was switched in.

        An activity change observed during an interrupted maintenance attempt must
        remain recorded. Restoring an earlier business snapshot would lose it.
        """
        self.maintenance.begin(journal["upgrade_id"])
        current_sources = self._sources()
        if not set(journal["plan"]["sources"]) <= set(current_sources):
            raise RuntimeUpgradeError("upgrade_recovery_conflict", "源数据库已经缺失，不能把单纯解除保护当作恢复")
        for kind, original in journal["plan"]["sources"].items():
            current = _database_snapshot(current_sources[kind], kind)
            schema = [entry for entry in current["schema"] if not entry["name"].startswith(MAINTENANCE_TRIGGER_PREFIX)]
            extras = [entry for entry in current["schema"] if entry["name"].startswith(MAINTENANCE_TRIGGER_PREFIX)]
            tables = {entry["name"] for entry in original["schema"] if entry["type"] == "table"}
            expected_guards = write_guard_definitions(tables, temporary=True)
            if current["format"] != original["format"] or schema != original["schema"] or any(entry not in expected_guards for entry in extras):
                raise RuntimeUpgradeError("upgrade_recovery_conflict", "源结构已经出现不属于本次临时保护的变化")
        for kind in journal["plan"]["sources"]:
            with closing(sqlite3.connect(current_sources[kind], timeout=0.5)) as connection:
                for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
                    if name.startswith(MAINTENANCE_TRIGGER_PREFIX):
                        connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
                connection.commit()
        journal["state"] = "aborted"
        journal["source_fences_removed"] = True
        return self._abort_before_source_change(journal)

    def apply(self, plan: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(plan, Mapping) or not isinstance(plan.get("plan_id"), str):
            raise RuntimeUpgradeError("upgrade_plan_invalid", "必须提供预检返回的完整计划")
        if plan.get("schema_version") != "strixnova.runtime-upgrade-plan.v1" or plan.get("project") != str(self.project):
            raise RuntimeUpgradeError("upgrade_plan_invalid", "升级计划缺少正确的公开合同与项目绑定")
        if any(plan.get(key) is not None and not isinstance(plan[key], Mapping) for key in ("installation",)):
            raise RuntimeUpgradeError("upgrade_plan_invalid", "升级来源、安装或停止证据必须使用预检返回的对象")
        upgrade_id = "UPGRADE-" + hashlib.sha256(plan["plan_id"].encode()).hexdigest()[:24].upper()
        directory = self.maintenance.root / upgrade_id
        previous = self._existing_attempt(plan, upgrade_id)
        if previous is not None:
            return previous
        installation = plan.get("installation")
        install_request = installation.get("request") if isinstance(installation, Mapping) else None
        inspected = self.check(installation=install_request)
        if dict(plan) != inspected and dict(plan) != self.plan_view(inspected):
            raise RuntimeUpgradeError("upgrade_plan_stale", "源数据或目标构建已经变化，请重新预检")
        plan = inspected
        prepared = None
        if installation is not None:
            manager = ManagedInstallation(plan["installation"]["installation_root"], self.project)
            prepared = manager.prepare(plan["installation"]["target"], builder_python=plan["installation"]["builder_python"], wheelhouse=plan["installation"]["wheelhouse"])
            if prepared["runtime"]["build_sha256"] != runtime_identity()["build_sha256"]:
                return self._delegate_apply(plan, prepared)
        with self.maintenance.executor():
            previous = self._existing_attempt(plan, upgrade_id)
            if previous is not None:
                return previous
            journal: dict[str, Any] = {
                "schema_version": "strixnova.runtime-upgrade-journal.v1", "project": str(self.project),
                "upgrade_id": upgrade_id, "state": "prepared", "plan": dict(plan),
                "backup_directory": str(directory / "backup"), "created_at": datetime.now(timezone.utc).isoformat(),
                "replacements": [],
                "prepared_installation": prepared,
            }
            self._save(journal)
            try:
                self.maintenance.begin(upgrade_id)
                if self._inspect(install_request) != dict(plan):
                    raise RuntimeUpgradeError("upgrade_plan_stale", "已有操作结束后源数据变化，请恢复维护并重新预检")
                if {kind: _database_snapshot(path, kind) for kind, path in self._sources().items()} != plan["sources"] or self._assets() != plan["assets"]:
                    raise RuntimeUpgradeError("upgrade_plan_stale", "关闭旧程序准入时来源已变化，保持事实并重新预检")
                for path in self._sources().values():
                    self._quiesce(path)
                required = sum(path.stat().st_size for path in self._sources().values()) * 3 + sum(value["size_bytes"] for value in plan["assets"].values()) * 2
                if shutil.disk_usage(self.project).free < required + 1024 * 1024:
                    raise RuntimeUpgradeError("upgrade_space_insufficient", "备份和转换空间不足")
                backup = directory / "backup"
                candidate = directory / "candidate"
                backup.mkdir()
                candidate.mkdir()
                for kind, path in self._sources().items():
                    destination = backup / path.name
                    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as source, closing(sqlite3.connect(destination)) as output:
                        source.backup(output)
                    if _database_snapshot(destination, kind) != plan["sources"][kind]:
                        raise RuntimeUpgradeError("upgrade_backup_mismatch", "数据库备份与预检不一致")
                    shutil.copyfile(destination, candidate / path.name)
                    journal["replacements"].append({"kind": kind, "target": path.relative_to(self.project).as_posix(), "backup_sha256": _file_digest(destination)})
                for relative, expected in plan["assets"].items():
                    destination = backup / "files" / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(self.project / relative, destination)
                    if _file_digest(destination) != expected["sha256"]:
                        raise RuntimeUpgradeError("upgrade_backup_mismatch", "证据备份与预检不一致")
                journal["state"] = "backed_up"
                self._save(journal)
                self._fence_sources(journal)
                authority_copy = candidate / "authority.sqlite3"
                if "authority" in plan["sources"]:
                    with closing(sqlite3.connect(authority_copy)) as connection:
                        remove_write_guards(connection)
                        if plan.get("project_identity") is not None:
                            connection.execute("INSERT INTO metadata(key,value) VALUES ('project_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (plan["project_identity"],))
                        install_write_guards(connection)
                        connection.commit()
                if "delivery_activities" in plan["sources"]:
                    with closing(sqlite3.connect(candidate / "delivery-activities.sqlite3")) as connection:
                        remove_write_guards(connection)
                        install_write_guards(connection)
                        connection.commit()
                for replacement in journal["replacements"]:
                    path = candidate / Path(replacement["target"]).name
                    snapshot = _database_snapshot(path, replacement["kind"])
                    if snapshot["business_sha256"] != plan["sources"][replacement["kind"]]["business_sha256"]:
                        raise RuntimeUpgradeError("upgrade_records_changed", "转换改变了原始业务记录")
                    replacement["candidate_sha256"] = _file_digest(path)
                    replacement["candidate_snapshot"] = snapshot
                journal["state"] = "verified"
                self._save(journal)
                if self._assets() != plan["assets"] or any(not self._matches_original_or_fenced(_database_snapshot(path, kind), plan["sources"][kind]) for kind, path in self._sources().items()):
                    raise RuntimeUpgradeError("upgrade_source_changed", "切换前源数据或证据发生变化")
                journal["state"] = "switching"
                self._save(journal)
                return self._finish_switch(journal)
            except BaseException as error:
                journal["failure"] = {"code": getattr(error, "code", "upgrade_interrupted"), "message": str(error)}
                self._save(journal)
                if journal["state"] in {"prepared", "backed_up"}:
                    self._abort_before_source_change(journal)
                if isinstance(error, OSError):
                    raise RuntimeUpgradeError("upgrade_io_failed", "升级文件操作失败，原备份与维护记录已保留", details={"upgrade_id": upgrade_id}) from error
                raise

    def _delegate_apply(self, plan: Mapping[str, Any], prepared: Mapping[str, Any]) -> dict[str, Any]:
        installation = plan["installation"]
        manager = ManagedInstallation(installation["installation_root"], self.project)
        plan_file = manager.root / "requests" / (plan["plan_id"] + ".json")
        write_maintenance_json(plan_file, self.plan_view(plan))
        command = [prepared["runtime"]["entrypoint"], "upgrade", "apply", "--project-dir", str(self.project), "--input", "@" + str(plan_file)]
        response = manager._run(command, cwd=self.project, timeout=1800)
        try:
            value = json.loads(response.stdout)
            if value.get("ok") is not True or value["upgrade"]["state"] != "completed":
                raise ValueError
            return value["upgrade"]
        except (ValueError, KeyError, TypeError) as error:
            raise RuntimeUpgradeError("upgrade_target_response_invalid", "目标程序没有返回完整升级结果") from error

    def _session_file(self, upgrade_id: str, group: str, name: str) -> Path:
        if group not in {"candidate", "backup", "restore"} or name not in {"authority.sqlite3", "delivery-activities.sqlite3"}:
            raise RuntimeUpgradeError("upgrade_journal_invalid", "升级记录包含未授权的文件位置")
        root = self.maintenance.root / upgrade_id
        path = root / group / name
        for candidate in (root, root / group, path):
            if candidate.is_symlink() or candidate.is_junction():
                raise RuntimeUpgradeError("upgrade_journal_invalid", "升级工作文件不能通过链接访问")
        return path

    def _assets_unchanged(self, journal: Mapping[str, Any]) -> bool:
        return self._assets() == journal["plan"]["assets"]

    def _finish_switch(self, journal: dict[str, Any]) -> dict[str, Any]:
        names = {"authority": "authority.sqlite3", "delivery_activities": "delivery-activities.sqlite3"}
        for replacement in journal["replacements"]:
            kind = replacement["kind"]
            name = names.get(kind)
            if name is None or replacement["target"] != f".strixnova/{name}":
                raise RuntimeUpgradeError("upgrade_journal_invalid", "升级目标不属于已声明的数据库")
            target = self.project / ".strixnova" / name
            current = _database_snapshot(target, kind)
            if current == replacement["candidate_snapshot"]:
                continue
            if not self._matches_original_or_fenced(current, journal["plan"]["sources"][kind]):
                raise RuntimeUpgradeError("upgrade_recovery_conflict", "数据库已出现不属于本次切换的变化，拒绝覆盖")
            candidate = self._session_file(journal["upgrade_id"], "candidate", name)
            if not candidate.is_file() or _file_digest(candidate) != replacement["candidate_sha256"]:
                raise RuntimeUpgradeError("upgrade_candidate_invalid", "已核验转换副本缺失或发生变化")
            os.replace(candidate, target)
            if _database_snapshot(target, kind) != replacement["candidate_snapshot"]:
                raise RuntimeUpgradeError("upgrade_activation_invalid", "实际目标数据库与已核验副本不一致")
        installation = journal["plan"].get("installation")
        if installation is not None:
            manager = ManagedInstallation(installation["installation_root"], self.project)
            target_runtime = journal["prepared_installation"]["runtime"]
            selected = manager.active()
            expected_selection = {"schema_version": "strixnova.runtime-selection.v1", "project": str(self.project), "upgrade_id": journal["upgrade_id"], "runtime": target_runtime}
            if selected != expected_selection:
                selected = manager.select(target_runtime, upgrade_id=journal["upgrade_id"], expected=installation["previous_selection"])
            journal["runtime_selection"] = selected
            journal["host_reload_required"] = True
            journal["entrypoint_validation"] = manager.validate_project(
                target_runtime, upgrade_id=journal["upgrade_id"],
                expected_snapshot_sha256=_digest({entry["kind"]: entry["candidate_snapshot"] for entry in journal["replacements"]}),
            )
        else:
            journal["entrypoint_validation"] = self.validate_target(journal["upgrade_id"])
        journal["state"] = "completed"
        journal["business_records_preserved"] = True
        journal["completed_at"] = datetime.now(timezone.utc).isoformat()
        journal.pop("failure", None)
        return self._close(journal)

    def validate_target(self, upgrade_id: str) -> dict[str, Any]:
        """Read exact switched databases and a bounded historical sample."""
        journal = self.status(upgrade_id)
        identity = runtime_identity()
        if journal["state"] not in {"verified", "switching", "completed"} or identity["build_sha256"] != journal["plan"]["target_runtime"]["build_sha256"]:
            raise RuntimeUpgradeError("upgrade_trial_unavailable", "当前维护阶段或运行构建不能用于目标试读")
        expected = {entry["kind"]: entry["candidate_snapshot"] for entry in journal["replacements"]}
        with self.maintenance.read_trial(upgrade_id):
            actual = {kind: _database_snapshot(path, kind) for kind, path in self._sources().items()}
            if actual != expected:
                raise RuntimeUpgradeError("upgrade_trial_mismatch", "实际项目尚未完整切换为已核验目标组合")
            try:
                sample = {"items": [], "snapshot_revision": None}
                if "authority" in actual:
                    history = WorkItemHistory(self.project)
                    sample = history.query(limit=1)
                    if sample["items"]:
                        history.query(work_item_id=sample["items"][0]["work_item_id"], records=("request", "result", "events", "verifications"), limit=1)
            except (HistoryQueryError, WorkflowAuthorityError) as error:
                raise RuntimeUpgradeError("upgrade_trial_history_failed", "目标程序无法读取已切换项目的历史事实", details={"reason": error.code}) from error
        return {
            "schema_version": "strixnova.runtime-upgrade-validation.v1", "project": str(self.project),
            "upgrade_id": upgrade_id, "build_sha256": identity["build_sha256"], "skill_sha256": identity["skill_sha256"],
            "database_snapshot_sha256": _digest(actual), "history_sample_count": len(sample["items"]),
            "snapshot_revision": sample["snapshot_revision"], "writes_performed": False,
        }

    def _restore(self, journal: dict[str, Any]) -> dict[str, Any]:
        if journal["state"] in {"prepared", "backed_up", "aborted"}:
            return self._abort_before_source_change(journal)
        if journal["state"] in {"fencing", "verified"}:
            return self._abort_fenced_sources(journal)
        was_clear = self.maintenance.status()["state"] == "clear"
        names = {"authority": "authority.sqlite3", "delivery_activities": "delivery-activities.sqlite3"}
        try:
            self.maintenance.begin(journal["upgrade_id"])
            installation = journal["plan"].get("installation")
            if installation:
                manager = ManagedInstallation(installation["installation_root"], self.project)
                if manager.probe(installation["source_runtime"]["python_path"]) != installation["source_runtime"]:
                    raise RuntimeUpgradeError("upgrade_source_runtime_changed", "原程序或 Skill 已变化，不能先恢复数据再猜测程序版本")
                active = manager.active()
                expected_current = journal.get("runtime_selection") or {"schema_version": "strixnova.runtime-selection.v1", "project": str(self.project), "upgrade_id": journal["upgrade_id"], "runtime": journal["prepared_installation"]["runtime"]}
                expected_restored = {"schema_version": "strixnova.runtime-selection.v1", "project": str(self.project), "upgrade_id": journal["upgrade_id"], "runtime": installation["source_runtime"]}
                allowed_selections = [installation["previous_selection"], expected_current]
                if journal["state"] == "restoring":
                    allowed_selections.append(expected_restored)
                if active not in allowed_selections:
                    raise RuntimeUpgradeError("upgrade_restore_would_discard_new_facts", "当前安装选择已发生其他变化，拒绝覆盖")
            if set(self._sources()) != set(journal["plan"]["sources"]):
                raise RuntimeUpgradeError("upgrade_restore_would_discard_new_facts", "数据库集合已有变化，不能用旧备份覆盖新的活动或事项事实")
            if not self._assets_unchanged(journal):
                raise RuntimeUpgradeError("upgrade_restore_would_discard_new_facts", "证据文件已有变化，不能覆盖旧备份")
            replacements = {entry["kind"]: entry for entry in journal["replacements"]}
            to_restore = []
            for kind, original in journal["plan"]["sources"].items():
                if kind not in names:
                    raise RuntimeUpgradeError("upgrade_journal_invalid", "恢复清单包含未知数据库")
                current = _database_snapshot(self.project / ".strixnova" / names[kind], kind)
                if current == original:
                    continue
                replacement = replacements.get(kind)
                if replacement is None or (current != replacement.get("candidate_snapshot") and not self._matches_original_or_fenced(current, original)):
                    raise RuntimeUpgradeError("upgrade_restore_would_discard_new_facts", "新版已有新记录或未识别变化，必须保全新增事实并向前修复")
                backup = self._session_file(journal["upgrade_id"], "backup", names[kind])
                if not backup.is_file() or _file_digest(backup) != replacement["backup_sha256"] or _database_snapshot(backup, kind) != original:
                    raise RuntimeUpgradeError("upgrade_backup_invalid", "备份缺失或与原数据不一致")
                to_restore.append((kind, backup))
        except BaseException:
            if was_clear and self.maintenance.status().get("upgrade_id") == journal["upgrade_id"]:
                self.maintenance.finish(journal["upgrade_id"])
            raise
        journal["state"] = "restoring"
        self._save(journal)
        for kind, backup in to_restore:
            destination = self._session_file(journal["upgrade_id"], "restore", names[kind])
            destination.parent.mkdir(exist_ok=True)
            shutil.copyfile(backup, destination)
            if _file_digest(destination) != replacements[kind]["backup_sha256"]:
                raise RuntimeUpgradeError("upgrade_backup_invalid", "恢复副本字节不一致")
            os.replace(destination, self.project / ".strixnova" / names[kind])
        for kind, original in journal["plan"]["sources"].items():
            if _database_snapshot(self.project / ".strixnova" / names[kind], kind) != original:
                raise RuntimeUpgradeError("upgrade_restore_invalid", "恢复后的实际数据库不一致")
        journal["state"] = "restored"
        journal["restored_at"] = datetime.now(timezone.utc).isoformat()
        journal["business_records_preserved"] = True
        if installation:
            source = installation["source_runtime"]
            selected = manager.active()
            if selected != expected_restored:
                selected = manager.select(source, upgrade_id=journal["upgrade_id"], expected=selected)
            journal["restored_runtime"] = selected
            journal["host_reload_required"] = True
        journal.pop("failure", None)
        return self._close(journal)

    def recover(self, upgrade_id: str, *, mode: str = "resume") -> dict[str, Any]:
        if not isinstance(upgrade_id, str) or not upgrade_id:
            raise RuntimeUpgradeError("upgrade_id_invalid", "恢复需要明确升级身份")
        if mode not in {"resume", "restore"}:
            raise RuntimeUpgradeError("upgrade_recovery_mode_invalid", "当前恢复操作无效")
        preliminary = self.status(upgrade_id)
        installed = preliminary.get("prepared_installation")
        if installed and installed["runtime"]["build_sha256"] != runtime_identity()["build_sha256"]:
            installation = preliminary["plan"]["installation"]
            manager = ManagedInstallation(installation["installation_root"], self.project)
            if manager.probe(installed["runtime"]["python_path"]) != installed["runtime"]:
                raise RuntimeUpgradeError("upgrade_target_changed", "恢复目标程序已经变化")
            response = manager._run([installed["runtime"]["entrypoint"], "upgrade", "recover", "--project-dir", str(self.project), "--upgrade-id", upgrade_id, "--mode", mode], cwd=self.project, timeout=1800)
            try:
                return json.loads(response.stdout)["upgrade"]
            except (ValueError, KeyError, TypeError) as error:
                raise RuntimeUpgradeError("upgrade_target_response_invalid", "目标程序恢复返回无效") from error
        with self.maintenance.executor():
            journal = self.status(upgrade_id)
            if journal["state"] in {"prepared", "backed_up", "aborted"}:
                return self._abort_before_source_change(journal)
            if journal["state"] == "restored":
                if self.maintenance.status().get("upgrade_id") == upgrade_id:
                    return self._close(journal)
                return journal
            if mode == "restore" or journal["state"] == "restoring":
                return self._restore(journal)
            if journal["state"] == "completed":
                if self.maintenance.status().get("upgrade_id") == upgrade_id:
                    return self._close(journal)
                return journal
            if journal["state"] not in {"verified", "switching"}:
                raise RuntimeUpgradeError("upgrade_not_verified", "尚无完整已核验副本，不能继续切换")
            if runtime_identity()["build_sha256"] != journal["plan"]["target_runtime"]["build_sha256"]:
                raise RuntimeUpgradeError("upgrade_target_changed", "恢复执行程序与原目标构建不一致")
            self.maintenance.begin(upgrade_id)
            if not self._assets_unchanged(journal):
                raise RuntimeUpgradeError("upgrade_recovery_conflict", "升级期间证据文件发生变化，拒绝猜测恢复")
            journal["state"] = "switching"
            self._save(journal)
            try:
                return self._finish_switch(journal)
            except OSError as error:
                raise RuntimeUpgradeError("upgrade_io_failed", "恢复切换失败，维护和备份继续保留") from error
