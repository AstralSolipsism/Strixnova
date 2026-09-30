"""Synthetic current-format records for bounded history and integrity tests.

These explicitly constructed record views are not an end-to-end workflow,
real owner acceptance, or Agent acceptance. Current workflow tests exercise
the transition API separately. No previous product or storage format is read.
"""
from __future__ import annotations

from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from strixnova.confirmation_protocol import confirmation_challenge_for, confirmation_record_from_input
from strixnova.persistent_evidence import capture_outputs
from strixnova.storage_formats import AUTHORITY_FORMAT, insert_evidence
from strixnova.workflow_authority import WorkflowAuthority, _initial_data

ITEM_ID = "WI-20260928-HISTORY"
ORIGINAL_REQUEST = '{ "request" : "导出结果，保留失败原因。" }'


def history_connection(path: Path, **kwargs) -> sqlite3.Connection:
    connection = sqlite3.connect(path, **kwargs)
    connection.create_function("strixnova_write_contract", 0, lambda: AUTHORITY_FORMAT)
    return connection


def history_item(project: Path) -> dict:
    data = _initial_data("导出结果，保留失败原因。", None)
    data["git"] = {
        "worktree_path": str(project / "deleted-worktree"),
        "result_commits": ["1" * 40],
        "integration": {"integration_commit": "2" * 40},
        "cleanup": {"completed": True},
    }
    data["verifications"] = [{
        "schema_version": "strixnova.verification-summary.v1",
        "work_item_id": ITEM_ID, "receipt_id": "VR-EXPORT", "command_id": "TEST-EXPORT",
        "argv": ["fixture-tool", "export"], "cwd": ".", "run_kind": "targeted_test",
        "covers": ["direction.acceptance:export"], "reasons": ["固定历史读取夹具"],
        "started_at": "2026-09-07T00:00:00+00:00", "duration_seconds": 1.0,
        "exit_code": 0, "result": "passed", "output_summary": {"stdout": "2 passed", "stderr": ""},
        "raw_output_refs": {
            "stdout": f".strixnova/artifacts/{ITEM_ID}/VR-EXPORT.stdout.log",
            "stderr": f".strixnova/artifacts/{ITEM_ID}/VR-EXPORT.stderr.log",
        },
        "limitations": ["合成记录仅用于测试读取与完整性"], "approval_ref": {},
        "code_change_assessment": None,
    }]
    data["actual_result"] = {"summary": "已支持导出", "limitations": ["尚未做大文件压测"]}
    data["actual_result_confirmation"] = {
        "accepted": True, "user_confirmation": "接受导出结果，已知大文件尚未压测",
    }
    return data


def write_history(project: Path, *, items: list[dict] | None = None, anchored_outputs: bool = True) -> Path:
    project.mkdir(parents=True, exist_ok=True)
    authority = WorkflowAuthority(project)
    authority.initialize()
    database = authority.database_path
    supplied = items or [{"work_item_id": ITEM_ID, "title": "导出结果", "status": "completed", "data": history_item(project)}]
    with closing(history_connection(database)) as connection, connection:
        for index, original in enumerate(supplied):
            item = deepcopy(original)
            identifier = item["work_item_id"]
            data = item["data"]
            recorded = f"2026-09-07T00:{index:02d}:00+00:00"
            for receipt in data.get("verifications", []):
                receipt["work_item_id"] = identifier
                for stream, reference in receipt.get("raw_output_refs", {}).items():
                    if isinstance(reference, str) and reference.startswith(f".strixnova/artifacts/{ITEM_ID}/"):
                        receipt["raw_output_refs"][stream] = reference.replace(f".strixnova/artifacts/{ITEM_ID}/", f".strixnova/artifacts/{identifier}/", 1)
            confirmation = data.get("actual_result_confirmation")
            challenge = confirmation_challenge_for(
                action_type="confirm_actual_result", work_item_id=identifier,
                work_item_version=2, data=data,
            )
            if confirmation is not None:
                confirmation = confirmation_record_from_input(challenge, {
                    "candidate_fingerprint": challenge["candidate_fingerprint"],
                    "user_confirmation": confirmation["user_confirmation"],
                    "agent_decision": {"decision": "accept" if confirmation["accepted"] else "request_changes", "reason": "预先固定的合成记录，不代表真人接受"},
                })
                data["actual_result_confirmation"] = confirmation
            connection.execute("INSERT INTO work_items VALUES (?,?,?,?,?,?,?)", (
                identifier, item["title"], item["status"], 3,
                json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")), recorded, recorded,
            ))
            for version, event, payload in (
                (1, "work_item_created", ORIGINAL_REQUEST),
                (2, "present_actual_result", json.dumps({"actual_result": data["actual_result"]}, ensure_ascii=False)),
                (3, "confirm_actual_result" if confirmation is not None else "discussion_updated", json.dumps(confirmation or {}, ensure_ascii=False)),
            ):
                cursor = connection.execute("INSERT INTO events(work_item_id,version,event_type,payload_json,recorded_at) VALUES (?,?,?,?,?)", (identifier, version, event, payload, recorded))
                facts = {"schema_version": "strixnova.recorded-history-facts.v1"}
                if version == 2:
                    facts["candidate"] = {"kind": "actual_result", "value": data["actual_result"], "fingerprint": challenge["candidate_fingerprint"], "state_at_recording": "awaiting_actual_result_confirmation"}
                elif version == 3 and confirmation is not None:
                    facts["decision"] = {"kind": "actual_result", **confirmation}
                if len(facts) > 1:
                    connection.execute("INSERT INTO event_annotations VALUES (?,?,?)", (cursor.lastrowid, identifier, json.dumps(facts, ensure_ascii=False, sort_keys=True, separators=(",", ":"))))
            for version, event in enumerate(item.get("delivery_events", []), 4):
                connection.execute("INSERT INTO events(work_item_id,version,event_type,payload_json,recorded_at) VALUES (?,?,?,?,?)", (identifier, version, event["event_type"], json.dumps(event["payload"], ensure_ascii=False), recorded))
                connection.execute("UPDATE work_items SET version=? WHERE work_item_id=?", (version, identifier))
            for receipt in data.get("verifications", []):
                log_root = project / ".strixnova/artifacts" / identifier
                log_root.mkdir(parents=True, exist_ok=True)
                (log_root / f"{receipt['receipt_id']}.stdout.log").write_bytes("2 passed\n详细结果\n".encode("utf-8"))
                (log_root / f"{receipt['receipt_id']}.stderr.log").write_bytes(b"")
                if anchored_outputs:
                    for evidence in capture_outputs(project, identifier, receipt, observation_kind="execution", observed_at=recorded):
                        insert_evidence(connection, evidence)
    return database
