"""Declared persistent formats and the additive evidence index owned by Authority."""

from __future__ import annotations

import sqlite3
from typing import Any, Mapping


AUTHORITY_FORMAT = 1
ACTIVITY_FORMAT = 1
EVIDENCE_FORMAT = 1
MAINTENANCE_TRIGGER_PREFIX = "strixnova_maintenance_guard__"
WRITER_TRIGGER_PREFIX = "strixnova_writer_guard__"


def write_guard_definitions(tables: set[str], *, temporary: bool = False) -> list[dict[str, str]]:
    controlled = {"metadata", "work_items", "events", "evidence_outputs", "event_annotations", "activities", "activity_events"}
    result = []
    for table in sorted(tables & controlled):
        for operation in ("INSERT", "UPDATE", "DELETE"):
            name = (MAINTENANCE_TRIGGER_PREFIX if temporary else WRITER_TRIGGER_PREFIX) + table + "__" + operation.lower()
            condition = "" if temporary else f" WHEN strixnova_write_contract() <> {AUTHORITY_FORMAT}"
            sql = f'CREATE TRIGGER "{name}" BEFORE {operation} ON "{table}"{condition} BEGIN SELECT RAISE(ABORT, \'strixnova_write_contract_required\'); END'
            result.append({"type": "trigger", "name": name, "tbl_name": table, "sql": sql})
    return result


def install_write_guards(connection: sqlite3.Connection, *, temporary: bool = False) -> None:
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    existing = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    for definition in write_guard_definitions(tables, temporary=temporary):
        if definition["name"] not in existing:
            connection.execute(definition["sql"])


def remove_write_guards(connection: sqlite3.Connection) -> None:
    for (name,) in connection.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall():
        if name.startswith((WRITER_TRIGGER_PREFIX, MAINTENANCE_TRIGGER_PREFIX)):
            connection.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')


def ensure_evidence_schema(connection: sqlite3.Connection) -> None:
    connection.execute("""
        CREATE TABLE IF NOT EXISTS evidence_outputs (
            work_item_id TEXT NOT NULL,
            receipt_id TEXT NOT NULL,
            stream TEXT NOT NULL CHECK(stream IN ('stdout','stderr','cases')),
            relative_path TEXT,
            sha256 TEXT,
            size_bytes INTEGER,
            observation_kind TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            availability TEXT NOT NULL,
            PRIMARY KEY(work_item_id,receipt_id,stream),
            FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        )
    """)
    connection.execute("""
        CREATE TABLE IF NOT EXISTS event_annotations (
            event_sequence INTEGER PRIMARY KEY,
            work_item_id TEXT NOT NULL,
            record_json TEXT NOT NULL,
            FOREIGN KEY(event_sequence) REFERENCES events(sequence) ON DELETE RESTRICT,
            FOREIGN KEY(work_item_id) REFERENCES work_items(work_item_id) ON DELETE RESTRICT
        )
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS annotations_by_item ON event_annotations(work_item_id,event_sequence)")


def insert_evidence(connection: sqlite3.Connection, evidence: Mapping[str, Any]) -> None:
    fields = ("work_item_id", "receipt_id", "stream", "relative_path", "sha256", "size_bytes", "observation_kind", "observed_at", "availability")
    connection.execute(
        "INSERT INTO evidence_outputs(" + ",".join(fields) + ") VALUES (" + ",".join("?" for _ in fields) + ")",
        [evidence[field] for field in fields],
    )
