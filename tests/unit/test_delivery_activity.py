from __future__ import annotations

from pathlib import Path
import json
import sqlite3
from contextlib import closing

import pytest
from click.testing import CliRunner

from strixnova.application_coordinator import (
    ApplicationCoordinator,
    ApplicationCoordinatorError,
)
from strixnova.cli import main
from strixnova.delivery_activity import (
    DeliveryActivityAuthority,
    DeliveryActivityError,
)
from strixnova.work_item_read_model import WorkItemReadModel
from strixnova.workflow_authority import WorkflowAuthority
from strixnova.storage_formats import AUTHORITY_FORMAT


@pytest.mark.parametrize("under_maintenance", [False, True])
def test_activity_store_rejects_unregistered_writers(tmp_path: Path, under_maintenance: bool) -> None:
    from strixnova.project_maintenance import ProjectMaintenance

    WorkflowAuthority(tmp_path).initialize()
    activity = DeliveryActivityAuthority(tmp_path)
    created = activity.plan(_plan(), work_item_id="WI-GUARD", work_item_version=1, engineering_plan_id="PLAN-GUARD")
    maintenance = ProjectMaintenance(tmp_path)
    if under_maintenance:
        maintenance.begin("TEST-ACTIVITY-GUARD")
    try:
        with closing(sqlite3.connect(activity.database_path)) as connection:
            with pytest.raises(sqlite3.DatabaseError):
                connection.execute("UPDATE activities SET state='canceled'")
            assert connection.execute("SELECT version,state FROM activities").fetchall() == [(1, "planned")]
            assert connection.execute("SELECT event_version,event_kind FROM activity_events").fetchall() == [(1, "planned")]
    finally:
        if under_maintenance:
            maintenance.finish("TEST-ACTIVITY-GUARD")
    assert activity.get(created["activity_id"]) == created
    canceled = activity.cancel_planned(created["activity_id"], expected_version=1, canceled_by="fixture owner", reason="current writer remains usable")
    assert canceled["state"] == "canceled"
    assert canceled["version"] == 2



@pytest.mark.parametrize("operation", ["read", "write"])
def test_future_activity_format_is_rejected_without_repair(tmp_path: Path, operation: str) -> None:
    authority = DeliveryActivityAuthority(tmp_path)
    authority.plan(_plan(), work_item_id="WI-FORMAT", work_item_version=1, engineering_plan_id="PLAN-FORMAT")
    database = tmp_path / ".strixnova/delivery-activities.sqlite3"
    with closing(sqlite3.connect(database)) as connection, connection:
        # Construct future-format input through a current-contract fixture
        # writer; unregistered writers are deliberately rejected by the guards.
        connection.create_function("strixnova_write_contract", 0, lambda: AUTHORITY_FORMAT)
        connection.execute("UPDATE metadata SET value='999' WHERE key='schema_version'")
    original = database.read_bytes()
    with pytest.raises(DeliveryActivityError) as caught:
        if operation == "read":
            authority.list()
        else:
            authority.plan(_plan(), work_item_id="WI-FORMAT", work_item_version=1, engineering_plan_id="PLAN-FORMAT")
    assert caught.value.code == "unsupported_activity_format"
    assert database.read_bytes() == original


def test_dangling_activity_database_link_cannot_create_an_outside_database(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".strixnova").mkdir(parents=True)
    outside = tmp_path / "outside.sqlite3"
    try:
        (project / ".strixnova/delivery-activities.sqlite3").symlink_to(outside)
    except OSError:
        pytest.skip("此宿主不允许创建文件符号链接")
    with pytest.raises(DeliveryActivityError) as blocked:
        DeliveryActivityAuthority(project).plan(_plan(), work_item_id="WI-LINK", work_item_version=1, engineering_plan_id="PLAN-LINK")
    assert blocked.value.code == "unsupported_activity_format"
    assert not outside.exists()


def _confirmation_payload(
    authority: WorkflowAuthority,
    work_item_id: str,
) -> dict[str, str]:
    challenge = authority.get(work_item_id)["current_action"][
        "confirmation_challenge"
    ]
    return {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "I accept the displayed candidate.",
        "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
    }


def _plan() -> dict:
    return {
        "schema_version": "strixnova.delivery-activity-plan.v1",
        "activity_kind": "deployment",
        "target_environment": {
            "environment_id": "ENV-STAGING",
            "description": "项目负责人控制的预发布环境。",
        },
        "objective": "把已接受构建部署到预发布环境并取得真实回执。",
        "responsible_party": "项目负责人指定的发布执行人",
        "external_system": {
            "system_id": "SYSTEM-DEPLOYMENT",
            "name": "外部部署平台",
            "execution_owner": "项目负责人",
            "receipt_channel": "部署平台作业回执",
        },
        "preconditions": ["建设事项实际结果已经接受。"],
        "success_criteria": ["外部平台报告部署完成且后置检查完成。"],
        "stop_conditions": ["目标环境身份与计划不一致。"],
        "rollback_or_recovery": "由外部平台按已确认版本回退。",
        "evidence_requirements": ["保留外部作业身份和原始结果引用。"],
    }


def _receipt(event_kind: str, receipt_id: str) -> dict:
    return {
        "schema_version": "strixnova.delivery-activity-receipt.v1",
        "receipt_id": receipt_id,
        "event_kind": event_kind,
        "external_system_id": "SYSTEM-DEPLOYMENT",
        "observed_at": "2026-08-26T12:00:00Z",
        "source": "外部部署平台作业回执",
        "request_summary": "对已确认构建执行预发布部署。",
        "result_summary": f"外部平台报告 {event_kind}。",
        "raw_evidence_refs": [f"external-job:{receipt_id}"],
        "limitations": [],
        "irreversible_effects": [],
        "follow_up_responsibilities": [],
    }


def _planned(tmp_path: Path) -> tuple[DeliveryActivityAuthority, dict]:
    authority = DeliveryActivityAuthority(tmp_path)
    activity = authority.plan(
        _plan(),
        work_item_id="WI-ACTIVITY",
        work_item_version=8,
        engineering_plan_id="PLAN-ACTIVITY-R1",
    )
    return authority, activity


def _work_item_with_confirmed_plan(tmp_path: Path) -> dict:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="外部部署", raw_request="治理预发布部署活动。")
    item = authority.transition(
        item["work_item_id"],
        "submit_direction",
        {
            "direction": {
                "schema_version": "strixnova.direction-decision.v1",
                "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
                "goal": "形成可追溯的预发布部署活动",
                "scope": [
                    {
                        "requirement_id": "DIRREQ-1111111111111111",
                        "statement": "外部交付活动治理记录",
                    }
                ],
                "non_goals": ["由 Strixnova 执行外部部署"],
                "constraints": [
                    {
                        "constraint_id": "DIRCON-2222222222222222",
                        "statement": "只接受外部系统的事实回执",
                    }
                ],
                "acceptance": [
                    {
                        "acceptance_id": "DIRACC-3333333333333333",
                        "statement": "计划、授权与回执可以独立追溯",
                        "requirement_refs": ["DIRREQ-1111111111111111"],
                        "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
                    }
                ],
                "tradeoffs": ["外部执行进度依赖外部系统回执"],
            },
            "ready_for_confirmation": True,
        },
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "submit_engineering_assessment",
        {
            "assessment": {
                "change_context": {"formal_implementation": False},
                "verification_commands": [],
                "verification_not_required_reason": "仅建立外部活动治理记录。",
            },
            "plan": {
                "plan_id": "PLAN-EXTERNAL-ACTIVITY",
                "change_context": {"formal_implementation": False},
                "verification_commands": [],
            },
        },
        expected_version=item["version"],
    )
    return authority.transition(
        item["work_item_id"],
        "confirm_engineering_plan",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )


def test_activity_capability_never_claims_external_execution(tmp_path: Path) -> None:
    authority, activity = _planned(tmp_path)

    assert activity["state"] == "planned"
    assert activity["capabilities"] == {
        "schema_version": "strixnova.delivery-activity-capability.v1",
        "plans_activities": True,
        "accepts_external_receipts": True,
        "executes_external_activities": False,
        "external_execution_required": True,
    }
    assert authority.get(activity["activity_id"]) == activity


def test_activity_requires_accepted_result_before_authorization(
    tmp_path: Path,
) -> None:
    authority, activity = _planned(tmp_path)

    with pytest.raises(DeliveryActivityError) as rejected:
        authority.authorize(
            activity["activity_id"],
            expected_version=1,
            authorization_ref={
                "work_item_id": "WI-ACTIVITY",
                "work_item_version": 9,
                "actual_result_accepted": False,
            },
        )
    assert rejected.value.code == "delivery_activity_not_authorized"


@pytest.mark.parametrize("terminal_event", ["completed", "failed", "canceled"])
def test_external_receipts_drive_the_real_activity_lifecycle(
    tmp_path: Path, terminal_event: str,
) -> None:
    authority, activity = _planned(tmp_path)
    authorized = authority.authorize(
        activity["activity_id"],
        expected_version=1,
        authorization_ref={
            "work_item_id": "WI-ACTIVITY",
            "work_item_version": 9,
            "actual_result_accepted": True,
        },
    )
    running = authority.record_external_receipt(
        activity["activity_id"],
        _receipt("started", "AR-START"),
        expected_version=authorized["version"],
    )
    finished = authority.record_external_receipt(
        activity["activity_id"],
        _receipt(terminal_event, "AR-FINISH"),
        expected_version=running["version"],
    )

    assert finished["state"] == terminal_event
    assert [item["event_kind"] for item in finished["external_receipts"]] == [
        "started",
        terminal_event,
    ]
    assert [item["event_kind"] for item in authority.history(activity["activity_id"])] == [
        "planned",
        "authorized",
        "started",
        terminal_event,
    ]


def test_authorized_activity_can_be_canceled_without_a_start_receipt(
    tmp_path: Path,
) -> None:
    authority, activity = _planned(tmp_path)
    authorized = authority.authorize(
        activity["activity_id"],
        expected_version=activity["version"],
        authorization_ref={
            "work_item_id": "WI-ACTIVITY",
            "work_item_version": 9,
            "actual_result_accepted": True,
        },
    )
    original_history = authority.history(activity["activity_id"])

    with pytest.raises(DeliveryActivityError) as rejected:
        authority.cancel_planned(
            activity["activity_id"],
            expected_version=authorized["version"],
            canceled_by="项目负责人",
            reason="只有取消意图，还没有外部事实。",
        )
    assert rejected.value.code == "invalid_delivery_activity_transition"

    receipt = _receipt("canceled", "AR-CANCEL-BEFORE-START")
    receipt["result_summary"] = "外部平台确认任务在启动前撤销，没有执行部署。"
    receipt["limitations"] = ["未执行部署及其后置检查。"]
    canceled = authority.record_external_receipt(
        activity["activity_id"], receipt, expected_version=authorized["version"],
    )

    assert canceled["state"] == "canceled"
    assert canceled["version"] == authorized["version"] + 1
    assert canceled["authorization_ref"] == authorized["authorization_ref"]
    assert canceled["external_receipts"] == [receipt]
    history = authority.history(activity["activity_id"])
    assert history[:-1] == original_history
    assert [item["event_kind"] for item in history] == [
        "planned", "authorized", "canceled",
    ]

    with pytest.raises(DeliveryActivityError) as after_cancel:
        authority.record_external_receipt(
            activity["activity_id"], _receipt("started", "AR-LATE-START"),
            expected_version=canceled["version"],
        )
    assert after_cancel.value.code == "invalid_delivery_activity_transition"
    assert authority.get(activity["activity_id"]) == canceled
    assert authority.history(activity["activity_id"]) == history


@pytest.mark.parametrize(
    ("case", "error_code"),
    [
        ("missing_evidence", "invalid_delivery_activity_receipt"),
        ("wrong_system", "delivery_activity_receipt_mismatch"),
        ("stale_version", "delivery_activity_stale"),
        ("completed", "invalid_delivery_activity_transition"),
        ("failed", "invalid_delivery_activity_transition"),
    ],
)
def test_prestart_receipt_rejection_preserves_activity(
    tmp_path: Path, case: str, error_code: str,
) -> None:
    authority, activity = _planned(tmp_path)
    authorized = authority.authorize(
        activity["activity_id"],
        expected_version=activity["version"],
        authorization_ref={
            "work_item_id": "WI-ACTIVITY",
            "work_item_version": 9,
            "actual_result_accepted": True,
        },
    )
    original_history = authority.history(activity["activity_id"])
    receipt = _receipt("canceled", "AR-PRESTART")
    expected_version = authorized["version"]
    if case == "missing_evidence":
        receipt["raw_evidence_refs"] = []
    elif case == "wrong_system":
        receipt["external_system_id"] = "SYSTEM-OTHER"
    elif case == "stale_version":
        expected_version = activity["version"]
    else:
        receipt["event_kind"] = case

    with pytest.raises(DeliveryActivityError) as rejected:
        authority.record_external_receipt(
            activity["activity_id"], receipt, expected_version=expected_version,
        )
    assert rejected.value.code == error_code
    assert authority.get(activity["activity_id"]) == authorized
    assert authority.history(activity["activity_id"]) == original_history


def test_activity_rejects_stale_writes_and_wrong_external_system(
    tmp_path: Path,
) -> None:
    authority, activity = _planned(tmp_path)
    authorized = authority.authorize(
        activity["activity_id"],
        expected_version=1,
        authorization_ref={
            "work_item_id": "WI-ACTIVITY",
            "work_item_version": 9,
            "actual_result_accepted": True,
        },
    )
    wrong = _receipt("started", "AR-WRONG")
    wrong["external_system_id"] = "SYSTEM-OTHER"

    with pytest.raises(DeliveryActivityError) as mismatch:
        authority.record_external_receipt(
            activity["activity_id"],
            wrong,
            expected_version=authorized["version"],
        )
    assert mismatch.value.code == "delivery_activity_receipt_mismatch"

    with pytest.raises(DeliveryActivityError) as stale:
        authority.authorize(
            activity["activity_id"],
            expected_version=1,
            authorization_ref={
                "work_item_id": "WI-ACTIVITY",
                "work_item_version": 9,
                "actual_result_accepted": True,
            },
        )
    assert stale.value.code == "delivery_activity_stale"


def test_unexecuted_plan_can_be_canceled_without_external_receipt(
    tmp_path: Path,
) -> None:
    authority, activity = _planned(tmp_path)
    canceled = authority.cancel_planned(
        activity["activity_id"],
        expected_version=1,
        canceled_by="项目负责人",
        reason="外部环境不再需要此次活动。",
    )

    assert canceled["state"] == "canceled"
    assert canceled["external_receipts"] == []


def test_application_coordinator_binds_activity_to_work_item_acceptance(
    tmp_path: Path,
) -> None:
    item = _work_item_with_confirmed_plan(tmp_path)
    coordinator = ApplicationCoordinator(tmp_path)
    activity = coordinator.plan_delivery_activity(
        item["work_item_id"],
        _plan(),
        expected_version=item["version"],
    )

    with pytest.raises(ApplicationCoordinatorError) as blocked:
        coordinator.authorize_delivery_activity(
            activity["activity_id"],
            expected_activity_version=activity["version"],
            expected_work_item_version=item["version"],
        )
    assert blocked.value.code == "delivery_activity_not_authorized", str(blocked.value)

    authority = WorkflowAuthority(tmp_path)
    item = authority.transition(
        item["work_item_id"],
        "present_actual_result",
        {"actual_result": {"effect_summary": "活动计划已经形成。"}},
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "confirm_actual_result",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )
    authorized = coordinator.authorize_delivery_activity(
        activity["activity_id"],
        expected_activity_version=activity["version"],
        expected_work_item_version=item["version"],
    )

    assert authorized["state"] == "authorized"
    view = WorkItemReadModel(tmp_path).delivery_activities(
        work_item_id=item["work_item_id"]
    )
    assert view["summary"]["by_state"] == {"authorized": 1}
    assert view["summary"]["external_execution_performed_by_strixnova"] is False

    receipt = _receipt("canceled", "AR-CLI-CANCEL-BEFORE-START")
    receipt["result_summary"] = "外部平台确认授权任务在执行前取消。"
    result = CliRunner().invoke(
        main,
        [
            "activity", "--project-dir", str(tmp_path), "--input",
            json.dumps({
                "action": "record",
                "activity_id": activity["activity_id"],
                "activity_version": authorized["version"],
                "receipt": receipt,
            }),
        ],
    )
    assert result.exit_code == 0, result.output
    recorded = json.loads(result.output)["activity"]
    assert recorded["state"] == "canceled"
    assert recorded["external_receipts"] == [receipt]
    view = WorkItemReadModel(tmp_path).delivery_activities(
        work_item_id=item["work_item_id"],
    )
    assert view["summary"]["by_state"] == {"canceled": 1}
    assert view["summary"]["external_execution_performed_by_strixnova"] is False


def test_activity_cli_exposes_plan_and_query_without_execution_claim(
    tmp_path: Path,
) -> None:
    item = _work_item_with_confirmed_plan(tmp_path)
    request = {
        "action": "plan",
        "work_item_id": item["work_item_id"],
        "work_item_version": item["version"],
        "plan": _plan(),
    }
    runner = CliRunner()
    planned = runner.invoke(
        main,
        [
            "activity",
            "--project-dir",
            str(tmp_path),
            "--input",
            json.dumps(request, ensure_ascii=False),
        ],
    )

    assert planned.exit_code == 0, planned.output
    payload = json.loads(planned.output)
    assert payload["activity"]["state"] == "planned"
    assert "不执行" in payload["capability_notice"]

    listed = runner.invoke(
        main,
        [
            "activity",
            "--project-dir",
            str(tmp_path),
            "--input",
            json.dumps({"action": "list"}),
        ],
    )
    assert listed.exit_code == 0, listed.output
    listed_payload = json.loads(listed.output)
    assert listed_payload["summary"]["total"] == 1
    assert listed_payload["capabilities"]["executes_external_activities"] is False


def test_status_cli_is_read_only_and_does_not_invent_project_adoption(
    tmp_path: Path,
) -> None:
    result = CliRunner().invoke(
        main,
        ["status", "--project-dir", str(tmp_path)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["status"]["baseline_id"] is None
    assert payload["status"]["next_required_actions"] == [
        "adopt_project_authorities_before_repository_delivery"
    ]
    assert payload["status"]["overall_usability_machine_decided"] is False
    assert not (tmp_path / ".strixnova").exists()
