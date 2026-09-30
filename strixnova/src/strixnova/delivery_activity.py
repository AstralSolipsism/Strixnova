"""Lifecycle authority for externally executed delivery and runtime activities."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import secrets
import sqlite3
from contextlib import closing

from strixnova.project_maintenance import connect_with_maintenance
from strixnova.storage_formats import ACTIVITY_FORMAT, AUTHORITY_FORMAT, install_write_guards
from typing import Any


DELIVERY_ACTIVITY_PLAN_SCHEMA = "strixnova.delivery-activity-plan.v1"
DELIVERY_ACTIVITY_SCHEMA = "strixnova.delivery-activity.v1"
DELIVERY_ACTIVITY_RECEIPT_SCHEMA = "strixnova.delivery-activity-receipt.v1"
DELIVERY_ACTIVITY_CAPABILITY_SCHEMA = "strixnova.delivery-activity-capability.v1"

ACTIVITY_KINDS = frozenset(
    {
        "delivery",
        "release",
        "deployment",
        "rollback",
        "observation",
        "operations_maintenance",
    }
)
ACTIVITY_STATES = frozenset(
    {"planned", "authorized", "running", "completed", "failed", "canceled"}
)
RECEIPT_EVENTS = frozenset({"started", "completed", "failed", "canceled"})


class DeliveryActivityError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            f"{field} 必须是非空字符串",
        )
    return value.strip()


def _text_list(
    value: Any,
    field: str,
    *,
    required: bool = False,
) -> list[str]:
    if not isinstance(value, list):
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            f"{field} 必须是字符串数组",
        )
    normalized = [_text(item, f"{field}[]") for item in value]
    if required and not normalized:
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            f"{field} 至少需要一项",
        )
    if len(normalized) != len(set(normalized)):
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            f"{field} 不得重复",
        )
    return normalized


def _object(
    value: Any,
    field: str,
    *,
    required: set[str],
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            f"{field} 必须是对象",
        )
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing or extra:
        message = f"{field} 字段不完整"
        if missing:
            message += "；缺少 " + ", ".join(missing)
        if extra:
            message += "；未知 " + ", ".join(extra)
        raise DeliveryActivityError("invalid_delivery_activity", message)
    return dict(value)


def validate_activity_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "activity_kind",
        "target_environment",
        "objective",
        "responsible_party",
        "external_system",
        "preconditions",
        "success_criteria",
        "stop_conditions",
        "rollback_or_recovery",
        "evidence_requirements",
    }
    plan = _object(value, "activity_plan", required=fields)
    if plan.get("schema_version") != DELIVERY_ACTIVITY_PLAN_SCHEMA:
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            "activity_plan.schema_version 无效",
        )
    kind = _text(plan.get("activity_kind"), "activity_kind")
    if kind not in ACTIVITY_KINDS:
        raise DeliveryActivityError(
            "invalid_delivery_activity",
            "activity_kind 不在允许的封闭集合中",
        )
    environment = _object(
        plan.get("target_environment"),
        "target_environment",
        required={"environment_id", "description"},
    )
    external = _object(
        plan.get("external_system"),
        "external_system",
        required={"system_id", "name", "execution_owner", "receipt_channel"},
    )
    return {
        "schema_version": DELIVERY_ACTIVITY_PLAN_SCHEMA,
        "activity_kind": kind,
        "target_environment": {
            "environment_id": _text(
                environment.get("environment_id"),
                "target_environment.environment_id",
            ),
            "description": _text(
                environment.get("description"),
                "target_environment.description",
            ),
        },
        "objective": _text(plan.get("objective"), "objective"),
        "responsible_party": _text(
            plan.get("responsible_party"),
            "responsible_party",
        ),
        "external_system": {
            "system_id": _text(
                external.get("system_id"),
                "external_system.system_id",
            ),
            "name": _text(external.get("name"), "external_system.name"),
            "execution_owner": _text(
                external.get("execution_owner"),
                "external_system.execution_owner",
            ),
            "receipt_channel": _text(
                external.get("receipt_channel"),
                "external_system.receipt_channel",
            ),
        },
        "preconditions": _text_list(
            plan.get("preconditions"),
            "preconditions",
            required=True,
        ),
        "success_criteria": _text_list(
            plan.get("success_criteria"),
            "success_criteria",
            required=True,
        ),
        "stop_conditions": _text_list(
            plan.get("stop_conditions"),
            "stop_conditions",
            required=True,
        ),
        "rollback_or_recovery": _text(
            plan.get("rollback_or_recovery"),
            "rollback_or_recovery",
        ),
        "evidence_requirements": _text_list(
            plan.get("evidence_requirements"),
            "evidence_requirements",
            required=True,
        ),
    }


def validate_activity_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "receipt_id",
        "event_kind",
        "external_system_id",
        "observed_at",
        "source",
        "request_summary",
        "result_summary",
        "raw_evidence_refs",
        "limitations",
        "irreversible_effects",
        "follow_up_responsibilities",
    }
    receipt = _object(value, "external_receipt", required=fields)
    if receipt.get("schema_version") != DELIVERY_ACTIVITY_RECEIPT_SCHEMA:
        raise DeliveryActivityError(
            "invalid_delivery_activity_receipt",
            "external_receipt.schema_version 无效",
        )
    event = _text(receipt.get("event_kind"), "event_kind")
    if event not in RECEIPT_EVENTS:
        raise DeliveryActivityError(
            "invalid_delivery_activity_receipt",
            "event_kind 不在允许的封闭集合中",
        )
    try:
        return {
            "schema_version": DELIVERY_ACTIVITY_RECEIPT_SCHEMA,
            "receipt_id": _text(receipt.get("receipt_id"), "receipt_id"),
            "event_kind": event,
            "external_system_id": _text(
                receipt.get("external_system_id"),
                "external_system_id",
            ),
            "observed_at": _text(receipt.get("observed_at"), "observed_at"),
            "source": _text(receipt.get("source"), "source"),
            "request_summary": _text(
                receipt.get("request_summary"),
                "request_summary",
            ),
            "result_summary": _text(
                receipt.get("result_summary"),
                "result_summary",
            ),
            "raw_evidence_refs": _text_list(
                receipt.get("raw_evidence_refs"),
                "raw_evidence_refs",
                required=True,
            ),
            "limitations": _text_list(
                receipt.get("limitations"),
                "limitations",
            ),
            "irreversible_effects": _text_list(
                receipt.get("irreversible_effects"),
                "irreversible_effects",
            ),
            "follow_up_responsibilities": _text_list(
                receipt.get("follow_up_responsibilities"),
                "follow_up_responsibilities",
            ),
        }
    except DeliveryActivityError as error:
        raise DeliveryActivityError(
            "invalid_delivery_activity_receipt",
            str(error),
        ) from error


class DeliveryActivityAuthority:
    """Versioned local state; external systems remain the execution authority."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        if not self.project.is_dir():
            raise DeliveryActivityError(
                "project_missing",
                f"项目目录不存在：{self.project}",
            )
        self.database_path = (
            self.project / ".strixnova" / "delivery-activities.sqlite3"
        )

    @staticmethod
    def capabilities() -> dict[str, Any]:
        return {
            "schema_version": DELIVERY_ACTIVITY_CAPABILITY_SCHEMA,
            "plans_activities": True,
            "accepts_external_receipts": True,
            "executes_external_activities": False,
            "external_execution_required": True,
        }

    def plan(
        self,
        candidate: Mapping[str, Any],
        *,
        work_item_id: str,
        work_item_version: int,
        engineering_plan_id: str,
    ) -> dict[str, Any]:
        plan = validate_activity_plan(candidate)
        work_item = _text(work_item_id, "work_item_id")
        plan_id = _text(engineering_plan_id, "engineering_plan_id")
        if (
            not isinstance(work_item_version, int)
            or isinstance(work_item_version, bool)
            or work_item_version < 1
        ):
            raise DeliveryActivityError(
                "invalid_delivery_activity",
                "work_item_version 必须是正整数",
            )
        activity_id = (
            "DA-"
            + datetime.now(timezone.utc).strftime("%Y%m%d")
            + "-"
            + secrets.token_hex(5).upper()
        )
        now = _utc_now()
        activity = {
            "schema_version": DELIVERY_ACTIVITY_SCHEMA,
            "activity_id": activity_id,
            "version": 1,
            "state": "planned",
            "work_item_ref": {
                "work_item_id": work_item,
                "work_item_version": work_item_version,
                "engineering_plan_id": plan_id,
            },
            "plan": plan,
            "authorization_ref": None,
            "external_receipts": [],
            "created_at": now,
            "updated_at": now,
            "capabilities": self.capabilities(),
        }
        connection = self._connect(write=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO activities(activity_id, version, state, payload) "
                "VALUES (?, ?, ?, ?)",
                (activity_id, 1, "planned", self._encode(activity)),
            )
            self._append_event(
                connection,
                activity_id,
                1,
                "planned",
                {"plan": plan, "work_item_ref": activity["work_item_ref"]},
            )
            connection.commit()
        except sqlite3.Error as error:
            connection.rollback()
            raise DeliveryActivityError(
                "delivery_activity_persistence_failed",
                "交付运行活动计划无法保存",
            ) from error
        finally:
            connection.close()
        return deepcopy(activity)

    def authorize(
        self,
        activity_id: str,
        *,
        expected_version: int,
        authorization_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        required = {
            "work_item_id",
            "work_item_version",
            "actual_result_accepted",
        }
        authorization = _object(
            authorization_ref,
            "authorization_ref",
            required=required,
        )
        if authorization.get("actual_result_accepted") is not True:
            raise DeliveryActivityError(
                "delivery_activity_not_authorized",
                "外部活动只有在实际结果已接受后才能授权",
            )

        def transition(current: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            if current["state"] != "planned":
                raise DeliveryActivityError(
                    "invalid_delivery_activity_transition",
                    f"当前活动状态 {current['state']} 不能授权",
                )
            if authorization.get("work_item_id") != current["work_item_ref"][
                "work_item_id"
            ]:
                raise DeliveryActivityError(
                    "delivery_activity_authorization_mismatch",
                    "活动授权不属于其绑定建设事项",
                )
            updated = deepcopy(current)
            updated["authorization_ref"] = deepcopy(authorization)
            return "authorized", updated

        return self._transition(
            activity_id,
            expected_version=expected_version,
            event_kind="authorized",
            event_payload={"authorization_ref": deepcopy(authorization)},
            transition=transition,
        )

    def record_external_receipt(
        self,
        activity_id: str,
        receipt: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        normalized = validate_activity_receipt(receipt)
        target_state = {
            "started": "running",
            "completed": "completed",
            "failed": "failed",
            "canceled": "canceled",
        }[normalized["event_kind"]]

        def transition(current: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            allowed_from = {
                "started": {"authorized"},
                "completed": {"running"},
                "failed": {"running"},
                # A real cancellation receipt can precede external execution.
                "canceled": {"authorized", "running"},
            }[normalized["event_kind"]]
            if current["state"] not in allowed_from:
                raise DeliveryActivityError(
                    "invalid_delivery_activity_transition",
                    (
                        f"当前活动状态 {current['state']} 不能记录 "
                        f"{normalized['event_kind']} 外部事实"
                    ),
                )
            expected_system = current["plan"]["external_system"]["system_id"]
            if normalized["external_system_id"] != expected_system:
                raise DeliveryActivityError(
                    "delivery_activity_receipt_mismatch",
                    "外部回执系统身份与已确认活动计划不一致",
                )
            if any(
                item["receipt_id"] == normalized["receipt_id"]
                for item in current["external_receipts"]
            ):
                raise DeliveryActivityError(
                    "delivery_activity_receipt_replayed",
                    "外部活动回执身份已经记录",
                )
            updated = deepcopy(current)
            updated["external_receipts"].append(deepcopy(normalized))
            return target_state, updated

        return self._transition(
            activity_id,
            expected_version=expected_version,
            event_kind=normalized["event_kind"],
            event_payload={"external_receipt": deepcopy(normalized)},
            transition=transition,
        )

    def cancel_planned(
        self,
        activity_id: str,
        *,
        expected_version: int,
        canceled_by: str,
        reason: str,
    ) -> dict[str, Any]:
        cancellation = {
            "canceled_by": _text(canceled_by, "canceled_by"),
            "reason": _text(reason, "reason"),
        }

        def transition(current: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            if current["state"] != "planned":
                raise DeliveryActivityError(
                    "invalid_delivery_activity_transition",
                    "只有尚未授权和执行的计划活动可以无外部回执取消",
                )
            updated = deepcopy(current)
            updated["cancellation"] = deepcopy(cancellation)
            return "canceled", updated

        return self._transition(
            activity_id,
            expected_version=expected_version,
            event_kind="canceled",
            event_payload=cancellation,
            transition=transition,
        )

    def get(self, activity_id: str) -> dict[str, Any]:
        identifier = _text(activity_id, "activity_id")
        if not self.database_path.is_file():
            raise DeliveryActivityError(
                "delivery_activity_missing",
                f"交付运行活动不存在：{identifier}",
            )
        connection = self._connect(write=False)
        try:
            row = connection.execute(
                "SELECT payload FROM activities WHERE activity_id = ?",
                (identifier,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise DeliveryActivityError(
                "delivery_activity_missing",
                f"交付运行活动不存在：{identifier}",
            )
        return self._decode(row[0])

    def list(self, *, work_item_id: str | None = None) -> list[dict[str, Any]]:
        if not self.database_path.is_file():
            return []
        connection = self._connect(write=False)
        try:
            rows = connection.execute(
                "SELECT payload FROM activities ORDER BY rowid"
            ).fetchall()
        finally:
            connection.close()
        activities = [self._decode(row[0]) for row in rows]
        if work_item_id is not None:
            identifier = _text(work_item_id, "work_item_id")
            activities = [
                item
                for item in activities
                if item["work_item_ref"]["work_item_id"] == identifier
            ]
        return activities

    def history(self, activity_id: str) -> list[dict[str, Any]]:
        self.get(activity_id)
        connection = self._connect(write=False)
        try:
            rows = connection.execute(
                "SELECT event_version, event_kind, recorded_at, payload "
                "FROM activity_events WHERE activity_id = ? ORDER BY event_version",
                (activity_id,),
            ).fetchall()
        finally:
            connection.close()
        return [
            {
                "activity_id": activity_id,
                "activity_version": int(version),
                "event_kind": kind,
                "recorded_at": recorded_at,
                "payload": self._decode(payload),
            }
            for version, kind, recorded_at, payload in rows
        ]

    def _transition(
        self,
        activity_id: str,
        *,
        expected_version: int,
        event_kind: str,
        event_payload: Mapping[str, Any],
        transition: Any,
    ) -> dict[str, Any]:
        identifier = _text(activity_id, "activity_id")
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 1
        ):
            raise DeliveryActivityError(
                "invalid_delivery_activity_version",
                "expected_version 必须是正整数",
            )
        connection = self._connect(write=True)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT version, payload FROM activities WHERE activity_id = ?",
                (identifier,),
            ).fetchone()
            if row is None:
                raise DeliveryActivityError(
                    "delivery_activity_missing",
                    f"交付运行活动不存在：{identifier}",
                )
            version = int(row[0])
            if version != expected_version:
                raise DeliveryActivityError(
                    "delivery_activity_stale",
                    f"活动已是版本 {version}，调用方仍基于版本 {expected_version}",
                )
            current = self._decode(row[1])
            new_state, updated = transition(current)
            if new_state not in ACTIVITY_STATES:
                raise AssertionError("invalid internal activity state")
            next_version = version + 1
            updated["version"] = next_version
            updated["state"] = new_state
            updated["updated_at"] = _utc_now()
            connection.execute(
                "UPDATE activities SET version = ?, state = ?, payload = ? "
                "WHERE activity_id = ? AND version = ?",
                (
                    next_version,
                    new_state,
                    self._encode(updated),
                    identifier,
                    version,
                ),
            )
            self._append_event(
                connection,
                identifier,
                next_version,
                event_kind,
                event_payload,
            )
            connection.commit()
            return deepcopy(updated)
        except DeliveryActivityError:
            connection.rollback()
            raise
        except sqlite3.Error as error:
            connection.rollback()
            raise DeliveryActivityError(
                "delivery_activity_persistence_failed",
                "交付运行活动状态无法保存",
            ) from error
        finally:
            connection.close()

    def _connect(self, *, write: bool) -> sqlite3.Connection:
        if self.database_path.is_symlink() or self.database_path.is_junction():
            raise DeliveryActivityError("unsupported_activity_format", "活动数据库不得是链接，包括失效链接")
        if self.database_path.exists():
            if self.database_path.is_symlink() or self.database_path.is_junction() or not self.database_path.is_file():
                raise DeliveryActivityError("unsupported_activity_format", "活动数据库必须是普通文件")
            try:
                with closing(sqlite3.connect(f"{self.database_path.as_uri()}?mode=ro", uri=True)) as probe:
                    row = probe.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone()
                    if row is None or str(row[0]) != str(ACTIVITY_FORMAT):
                        raise DeliveryActivityError("unsupported_activity_format", "活动库格式不受当前构建支持；不能隐式修复或升级")
                    probe.execute("SELECT activity_id,version,state,payload FROM activities LIMIT 0")
                    probe.execute("SELECT activity_id,event_version,event_kind,recorded_at,payload FROM activity_events LIMIT 0")
            except sqlite3.Error as error:
                raise DeliveryActivityError("unsupported_activity_format", "活动库格式或表结构不受支持，请先显式预检升级") from error
        if write:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = None
        try:
            connection = connect_with_maintenance(
                self.project,
                self.database_path if write else f"{self.database_path.as_uri()}?mode=ro",
                read_only=not write, uri=not write, timeout=30,
            )
            connection.create_function("strixnova_write_contract", 0, lambda: AUTHORITY_FORMAT, deterministic=True)
            connection.execute("PRAGMA foreign_keys = ON")
            if write:
                connection.execute("PRAGMA journal_mode = WAL")
                connection.execute("BEGIN IMMEDIATE")
                connection.execute("CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
                connection.execute("INSERT OR IGNORE INTO metadata VALUES ('schema_version',?)", (str(ACTIVITY_FORMAT),))
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS activities (
                        activity_id TEXT PRIMARY KEY,
                        version INTEGER NOT NULL,
                        state TEXT NOT NULL,
                        payload TEXT NOT NULL
                    )
                    """
                )
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS activity_events (
                        activity_id TEXT NOT NULL,
                        event_version INTEGER NOT NULL,
                        event_kind TEXT NOT NULL,
                        recorded_at TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        PRIMARY KEY(activity_id, event_version)
                    )
                    """
                )
                # Publish the schema and its unregistered-writer protection in one
                # transaction, including stores first created after upgrade.
                install_write_guards(connection)
                connection.commit()
        except sqlite3.Error as error:
            if connection is not None:
                connection.rollback()
                connection.close()
            raise DeliveryActivityError("delivery_activity_persistence_failed", "活动数据库连接初始化失败") from error
        return connection

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        activity_id: str,
        version: int,
        event_kind: str,
        payload: Mapping[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO activity_events(activity_id, event_version, event_kind, "
            "recorded_at, payload) VALUES (?, ?, ?, ?, ?)",
            (
                activity_id,
                version,
                event_kind,
                _utc_now(),
                DeliveryActivityAuthority._encode(payload),
            ),
        )

    @staticmethod
    def _encode(value: Mapping[str, Any]) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(value: str) -> dict[str, Any]:
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise DeliveryActivityError(
                "delivery_activity_persistence_invalid",
                "交付运行活动持久化内容无效",
            )
        return decoded


__all__ = [
    "ACTIVITY_KINDS",
    "ACTIVITY_STATES",
    "DELIVERY_ACTIVITY_CAPABILITY_SCHEMA",
    "DELIVERY_ACTIVITY_PLAN_SCHEMA",
    "DELIVERY_ACTIVITY_RECEIPT_SCHEMA",
    "DELIVERY_ACTIVITY_SCHEMA",
    "DeliveryActivityAuthority",
    "DeliveryActivityError",
    "validate_activity_plan",
    "validate_activity_receipt",
]
