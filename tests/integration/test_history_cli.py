from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess

import pytest
from click.testing import CliRunner

from strixnova.cli import main
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.history_records import ITEM_ID, ORIGINAL_REQUEST, history_item, write_history, history_connection


def test_completed_result_is_readable_without_a_current_action_or_worktree(tmp_path: Path) -> None:
    database = write_history(tmp_path)
    (tmp_path / "strixnova-project.yaml").write_text("not: a-current-config", encoding="utf-8")
    before = database.read_bytes()

    result = CliRunner().invoke(main, [
        "history", "--project-dir", str(tmp_path),
        "--work-item-id", ITEM_ID, "--record", "result",
    ])

    assert result.exit_code == 0, result.output
    history = json.loads(result.output)["history"]
    assert history["records"]["result"]["actual_result"]["summary"] == "已支持导出"
    assert history["records"]["result"]["confirmation"]["user_confirmation"] == "接受导出结果，已知大文件尚未压测"
    assert history["work_item"]["status"] == "completed"
    assert database.read_bytes() == before


def test_history_lists_all_states_and_pages_a_filtered_consistent_snapshot(tmp_path: Path) -> None:
    write_history(tmp_path, items=[
        {"work_item_id": f"WI-{state}", "title": f"导出 {state}", "status": state, "data": history_item(tmp_path)}
        for state in ("completed", "cancelled", "discussion")
    ])
    runner = CliRunner()
    base = ["history", "--project-dir", str(tmp_path), "--query", "导出", "--limit", "2"]
    first = runner.invoke(main, base)
    assert first.exit_code == 0, first.output
    page = json.loads(first.output)["history"]
    assert [item["status"] for item in page["items"]] == ["discussion", "cancelled"]
    second = runner.invoke(main, [*base, "--cursor", page["next_cursor"]])
    assert second.exit_code == 0, second.output
    assert [item["status"] for item in json.loads(second.output)["history"]["items"]] == ["completed"]
    # A concurrent current-format fixture writer invalidates the pinned page.
    with closing(history_connection(tmp_path / ".strixnova/authority.sqlite3")) as connection, connection:
        connection.execute("INSERT INTO events(work_item_id,version,event_type,payload_json,recorded_at) VALUES ('WI-discussion',4,'discussion_updated','{}','2026-09-07T02:00:00+00:00')")
    stale = runner.invoke(main, [*base, "--cursor", page["next_cursor"]])
    assert stale.exit_code == 1
    assert json.loads(stale.output)["error"]["code"] == "history_snapshot_changed"


@pytest.mark.parametrize("record_source", ["recorded", "live"])
@pytest.mark.parametrize("filters,expected", [
    (["--since", "2026-09-08T12:00:00.123456Z"], ["late", "bound"]),
    (["--until", "2026-09-08T12:00:00.123456Z"], ["early"]),
    (["--since", "2026-09-08T12:00:00.123400Z", "--until", "2026-09-08T12:00:00.123499Z"], ["bound", "early"]),
])
def test_history_time_ranges_preserve_microseconds(
    tmp_path: Path, record_source: str, filters: list[str], expected: list[str],
) -> None:
    times = {"early": "2026-09-08T12:00:00.123400Z", "bound": "2026-09-08T12:00:00.123456Z", "late": "2026-09-08T12:00:00.123499Z"}
    if record_source == "recorded":
        database = write_history(tmp_path, items=[
            {"work_item_id": title, "title": title, "status": "completed", "data": history_item(tmp_path)}
            for title in times
        ])
    else:
        authority = WorkflowAuthority(tmp_path)
        for title in times:
            authority.create(title=title, raw_request="precise time range fixture")
        database = authority.database_path
    with closing(history_connection(database)) as connection, connection:
        connection.executemany("UPDATE work_items SET updated_at=? WHERE title=?", [(stamp, title) for title, stamp in times.items()])
    before = database.read_bytes()

    result = CliRunner().invoke(main, ["history", "--project-dir", str(tmp_path), *filters])

    assert result.exit_code == 0, result.output
    assert [item["title"] for item in json.loads(result.output)["history"]["items"]] == expected
    assert database.read_bytes() == before


def test_history_orders_and_pages_by_the_same_precise_utc_time(tmp_path: Path) -> None:
    times = {
        "zero": "2026-09-08T12:00:00Z",
        "fraction": "2026-09-08T12:00:00.000001Z",
        "equal-a": "2026-09-08T12:00:00.123456Z",
        "equal-b": "2026-09-08T20:00:00.123456+08:00",
        "earlier": "2026-09-08T11:59:59.999999Z",
    }
    database = write_history(tmp_path, items=[
        {"work_item_id": title, "title": title, "status": "completed", "data": history_item(tmp_path)}
        for title in times
    ])
    with closing(history_connection(database)) as connection, connection:
        connection.executemany("UPDATE work_items SET updated_at=? WHERE title=?", [(stamp, title) for title, stamp in times.items()])
    before = database.read_bytes()
    runner = CliRunner()
    for filters, expected in (
        ([], ["equal-a", "equal-b", "fraction", "zero", "earlier"]),
        (["--since", "2026-09-08T12:00:00.000001Z", "--until", "2026-09-08T12:00:00.123457Z"], ["equal-a", "equal-b", "fraction"]),
    ):
        cursor = None
        for index, title in enumerate(expected):
            continuation = ["--cursor", cursor] if cursor else []
            result = runner.invoke(main, ["history", "--project-dir", str(tmp_path), "--limit", "1", *filters, *continuation])
            assert result.exit_code == 0, result.output
            page = json.loads(result.output)["history"]
            assert [(item["title"], item["updated_at"]) for item in page["items"]] == [(title, times[title])]
            cursor = page["next_cursor"]
            assert bool(cursor) == (index < len(expected) - 1)
    assert database.read_bytes() == before


def test_history_events_keep_original_payload_and_distinguish_result_acceptance(tmp_path: Path) -> None:
    write_history(tmp_path)
    runner = CliRunner()
    base = ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID]
    result = runner.invoke(main, [*base, "--record", "events", "--limit", "2"])
    assert result.exit_code == 0, result.output
    events = json.loads(result.output)["history"]["records"]["events"]
    assert [event["event_type"] for event in events["items"]] == ["work_item_created", "present_actual_result"]
    assert all("payload" not in event for event in events["items"])
    next_page = runner.invoke(main, [*base, "--record", "events", "--limit", "2", "--cursor", events["next_cursor"]])
    assert next_page.exit_code == 0, next_page.output
    assert json.loads(next_page.output)["history"]["records"]["events"]["items"][0]["event_type"] == "confirm_actual_result"
    detail = runner.invoke(main, [*base, "--record", "event:1", "--record", "result", "--record", "decisions"])
    assert detail.exit_code == 0, detail.output
    records = json.loads(detail.output)["history"]["records"]
    assert records["event:1"]["payload_json"] == ORIGINAL_REQUEST
    assert records["result"]["acceptance_status"] == "accepted"
    assert records["decisions"]["raw_request"] == "导出结果，保留失败原因。"


def test_replanning_does_not_hide_old_verification_runs(tmp_path: Path) -> None:
    database = write_history(tmp_path)
    old_receipt = history_item(tmp_path)["verifications"][0]
    with closing(history_connection(database)) as connection, connection:
        connection.execute(
            "INSERT INTO events(work_item_id,version,event_type,payload_json,recorded_at) VALUES (?,4,'record_verification',?,'2026-09-07T01:00:00+00:00')",
            (ITEM_ID, json.dumps({"verification": old_receipt})),
        )
        connection.execute("UPDATE work_items SET version=4,status='replanning_required',data_json=json_set(data_json,'$.verifications',json('[]'))")
    result = CliRunner().invoke(main, [
        "history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID,
        "--record", "verifications", "--record", "verification:VR-EXPORT",
    ])
    assert result.exit_code == 0, result.output
    records = json.loads(result.output)["history"]["records"]
    assert records["verifications"]["items"][0]["receipt_id"] == "VR-EXPORT"
    assert records["verification:VR-EXPORT"]["source"] == "original_run_event"
    assert records["verification:VR-EXPORT"]["receipt"]["result"] == "passed"


def test_history_reads_bounded_receipt_output_and_reports_missing_evidence(tmp_path: Path) -> None:
    write_history(tmp_path)
    runner = CliRunner()
    base = ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID]
    result = runner.invoke(main, [
        *base, "--record", "verification:VR-EXPORT", "--record", "output:VR-EXPORT:stdout", "--bytes", "8",
    ])
    assert result.exit_code == 0, result.output
    records = json.loads(result.output)["history"]["records"]
    assert records["verification:VR-EXPORT"]["receipt"]["result"] == "passed"
    assert records["output:VR-EXPORT:stdout"]["text"] == "2 passed"
    assert records["output:VR-EXPORT:stdout"]["next_offset"] == 8
    (tmp_path / ".strixnova/artifacts" / ITEM_ID / "VR-EXPORT.stdout.log").unlink()
    missing = runner.invoke(main, [*base, "--record", "output:VR-EXPORT:stdout", "--record", "result"])
    assert missing.exit_code == 0, missing.output
    records = json.loads(missing.output)["history"]["records"]
    assert records["output:VR-EXPORT:stdout"]["availability"] == "missing"
    assert records["result"]["acceptance_status"] == "accepted"


def test_corrupt_current_body_has_a_typed_error_but_original_events_remain_readable(tmp_path: Path) -> None:
    database = write_history(tmp_path)
    with closing(history_connection(database)) as connection, connection:
        connection.execute("UPDATE work_items SET data_json='damaged-json'")
    runner = CliRunner()
    base = ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID]
    damaged = runner.invoke(main, [*base, "--record", "result"])
    assert damaged.exit_code == 1
    assert json.loads(damaged.output)["error"]["code"] == "history_data_invalid"
    original = runner.invoke(main, [*base, "--record", "event:1"])
    assert original.exit_code == 0, original.output
    assert json.loads(original.output)["history"]["records"]["event:1"]["payload_json"] == ORIGINAL_REQUEST


def test_rejected_and_accepted_candidates_keep_the_decisions_recorded_at_the_time(tmp_path: Path) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="导出方案", raw_request="明确导出的范围")
    direction = {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
        "goal": "导出全部数据",
        "scope": [{"requirement_id": "DIRREQ-1111111111111111", "statement": "提供导出"}],
        "constraints": [{"constraint_id": "DIRCON-2222222222222222", "statement": "保留原数据"}],
        "acceptance": [{"acceptance_id": "DIRACC-3333333333333333", "statement": "能取得导出文件", "requirement_refs": ["DIRREQ-1111111111111111"], "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."}}],
        "non_goals": ["改变源数据"], "tradeoffs": ["按用户明确范围导出"],
    }
    for accepted in (False, True):
        direction["goal"] = "仅导出选中数据" if accepted else "导出全部数据"
        item = authority.transition(item["work_item_id"], "submit_direction", {"direction": direction, "ready_for_confirmation": True}, expected_version=item["version"])
        challenge = authority.get(item["work_item_id"])["current_action"]["confirmation_challenge"]
        item = authority.transition(item["work_item_id"], "confirm_direction", {
            "candidate_fingerprint": challenge["candidate_fingerprint"],
            "user_confirmation": "同意这个结果" if accepted else "只导出选中数据",
            "agent_decision": {
                "decision": "accept" if accepted else "request_changes",
                "reason": "负责人接受当前候选" if accepted else "只导出选中数据",
            },
        }, expected_version=item["version"])
    result = CliRunner().invoke(main, ["history", "--project-dir", str(tmp_path), "--work-item-id", item["work_item_id"], "--record", "candidates"])
    assert result.exit_code == 0, result.output
    candidates = json.loads(result.output)["history"]["records"]["candidates"]
    assert [value["disposition"] for value in candidates["items"]] == ["rejected", "accepted"]
    detail = CliRunner().invoke(main, ["history", "--project-dir", str(tmp_path), "--work-item-id", item["work_item_id"], "--record", candidates["items"][0]["record_ref"]])
    assert detail.exit_code == 0, detail.output
    record = json.loads(detail.output)["history"]["records"][candidates["items"][0]["record_ref"]]
    assert record["candidate"]["value"]["goal"] == "导出全部数据"
    assert record["decision"]["accepted"] is False


def test_log_continuation_is_bound_to_the_first_page_bytes(tmp_path: Path) -> None:
    write_history(tmp_path)
    runner = CliRunner()
    base = ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID, "--record", "output:VR-EXPORT:stdout", "--bytes", "8"]
    first = runner.invoke(main, base)
    assert first.exit_code == 0, first.output
    page = json.loads(first.output)["history"]["records"]["output:VR-EXPORT:stdout"]
    assert page["next_cursor"]
    second = runner.invoke(main, [*base, "--cursor", page["next_cursor"]])
    assert second.exit_code == 0, second.output
    assert json.loads(second.output)["history"]["records"]["output:VR-EXPORT:stdout"]["offset"] == 8
    (tmp_path / ".strixnova/artifacts" / ITEM_ID / "VR-EXPORT.stdout.log").write_bytes(b"2 passed changed after page one\n")
    changed = runner.invoke(main, [*base, "--cursor", page["next_cursor"]])
    assert changed.exit_code == 1
    assert json.loads(changed.output)["error"]["code"] == "history_output_changed"


def test_historical_artifact_uses_recorded_commit_and_keeps_missing_git_evidence_visible(tmp_path: Path) -> None:
    def git(*args: str) -> str:
        return subprocess.run(["git", *args], cwd=tmp_path, capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()

    git("init", "-b", "main")
    git("config", "user.name", "History Test")
    git("config", "user.email", "history@example.invalid")
    artifact = tmp_path / "decision.md"
    artifact.write_text("当时确认的文件\n", encoding="utf-8")
    git("add", "decision.md")
    git("-c", "commit.gpgsign=false", "commit", "-m", "recorded artifact")
    commit = git("rev-parse", "HEAD")
    data = history_item(tmp_path)
    data["git"]["integration"] = {"integrated_commit": commit}
    data["git"]["result_commits"] = ["f" * 40]
    data["actual_result"]["long_lived_refs"] = [{"artifact_id": "ADR-EXPORT", "artifact_type": "adr", "path": "decision.md", "relation": "created"}]
    write_history(tmp_path, items=[{"work_item_id": ITEM_ID, "title": "历史文件", "status": "completed", "data": data, "delivery_events": [{"event_type": "record_local_integration", "payload": {"integration": {"integrated_commit": commit}}}]}])
    artifact.write_text("今天的未提交改动\n", encoding="utf-8")
    response = CliRunner().invoke(main, ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID, "--record", "delivery", "--record", "artifact:0"])
    assert response.exit_code == 0, response.output
    records = json.loads(response.output)["history"]["records"]
    assert records["artifact:0"]["text"] == "当时确认的文件\n"
    assert records["artifact:0"]["observed_commit"] == commit
    assert records["delivery"]["commits"][0]["availability"] == "missing_commit"


def test_large_unrequested_body_does_not_block_bounded_receipt_or_result_reads(tmp_path: Path) -> None:
    data = history_item(tmp_path)
    data["raw_request"] = "x" * (17 * 1024 * 1024)
    write_history(tmp_path, items=[{"work_item_id": ITEM_ID, "title": "有大正文的历史", "status": "completed", "data": data}])
    runner = CliRunner()
    base = ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID]
    small = runner.invoke(main, [*base, "--record", "verifications", "--record", "result", "--limit", "1"])
    assert small.exit_code == 0, small.output
    records = json.loads(small.output)["history"]["records"]
    assert len(records["verifications"]["items"]) == 1
    assert records["result"]["acceptance_status"] == "accepted"
    huge = runner.invoke(main, [*base, "--record", "request"])
    assert huge.exit_code == 1
    assert json.loads(huge.output)["error"]["code"] == "history_record_too_large"


def test_uncommitted_new_result_never_borrows_a_superseded_round_commit(tmp_path: Path) -> None:
    data = history_item(tmp_path)
    data["actual_result"] = {"summary": "新的未提交结果", "long_lived_refs": [{"artifact_id": "ADR-NEW", "artifact_type": "adr", "path": "decision.md", "relation": "updated"}]}
    data["actual_result_confirmation"] = None
    data["git"]["integration"] = {}
    database = write_history(tmp_path, items=[{"work_item_id": ITEM_ID, "title": "重规划后的候选", "status": "awaiting_actual_result", "data": data}])
    with closing(history_connection(database)) as connection, connection:
        connection.execute("DELETE FROM event_annotations WHERE event_sequence IN (SELECT sequence FROM events WHERE version>1)")
        connection.execute("DELETE FROM events WHERE version>1")
        for version, kind, payload in (
            (2, "record_result_commits", {"commits": data["git"]["result_commits"]}),
            (3, "request_replan", {"reasons": ["改变交付范围"]}),
            (4, "present_actual_result", {"actual_result": data["actual_result"]}),
        ):
            connection.execute("INSERT INTO events(work_item_id,version,event_type,payload_json,recorded_at) VALUES (?,?,?,?,?)", (ITEM_ID, version, kind, json.dumps(payload), "2026-09-07"))
        connection.execute("UPDATE work_items SET version=4")
    result = CliRunner().invoke(main, ["history", "--project-dir", str(tmp_path), "--work-item-id", ITEM_ID, "--record", "artifact:0"])
    assert result.exit_code == 0, result.output
    artifact = json.loads(result.output)["history"]["records"]["artifact:0"]
    assert artifact["availability"] == "candidate_not_committed"
    assert "text" not in artifact
