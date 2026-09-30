from __future__ import annotations

from pathlib import Path
import sys

import pytest

from strixnova.actual_result import ActualResultError, validate_actual_result
from strixnova.verification_runner import (
    VerificationRunner,
    VerificationRunnerError,
    normalize_verification_commands,
)
from tests.support.verification_approval import (
    approval_expectations,
    approved_verification_request,
)


def _command(*, code: str = "print('verified')") -> dict:
    return {
        "argv": [sys.executable, "-c", code],
        "cwd": ".",
        "run_kind": "targeted_test",
        "covers": ["AC-001"],
        "reason": "验证已确认的验收行为。",
    }


def _assessment(*, needs_retest: bool = False) -> dict:
    return {
        "changed_after": needs_retest,
        "needs_retest": needs_retest,
        "rationale": (
            "验证后相关实现发生变化，需要重测。"
            if needs_retest
            else "本回执记录时尚未继续修改相关实现。"
        ),
    }


def _approved(command: dict, work_item_id: str) -> tuple[dict, dict]:
    request = approved_verification_request(
        command,
        work_item_id=work_item_id,
    )
    return request, approval_expectations(request)


def test_unclosed_process_cleanup_does_not_become_a_completed_blocked_receipt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.process_supervisor import ProcessExecutionError

    command = normalize_verification_commands([_command()])[0]
    approved, expected = _approved(command, "WI-UNCLOSED")
    def cleanup_failed(*args, **kwargs):
        raise ProcessExecutionError("cleanup_failed", "children are not confirmed stopped", command_name="fixture")
    monkeypatch.setattr("strixnova.verification_runner.run_process", cleanup_failed)
    output = tmp_path / "receipts"
    with pytest.raises(VerificationRunnerError) as caught:
        VerificationRunner(tmp_path, artifact_root=output).run(approved, **expected, limitations=[])
    assert caught.value.code == "verification_execution_unclosed"
    assert not output.exists()


def test_deduplicates_only_by_argv_cwd_and_run_kind() -> None:
    first = _command()
    first["optional_timeout"] = 20
    duplicate = {
        **_command(),
        "covers": ["AC-002"],
        "reason": "同一次执行也覆盖第二项验收。",
        "optional_timeout": 30,
    }
    different_kind = {**_command(), "run_kind": "full_regression"}

    normalized = normalize_verification_commands(
        [first, duplicate, different_kind]
    )

    assert len(normalized) == 2
    assert normalized[0]["covers"] == ["AC-001", "AC-002"]
    assert normalized[0]["reasons"] == [
        "验证已确认的验收行为。",
        "同一次执行也覆盖第二项验收。",
    ]
    assert normalized[0]["optional_timeout"] == 30
    assert normalized[0]["source_command_indexes"] == [0, 1]
    assert normalized[1]["run_kind"] == "full_regression"
    assert all("executor_role" not in item for item in normalized)


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), float("-inf")],
)
def test_verification_timeout_rejects_non_finite_numbers(value: float) -> None:
    command = {**_command(), "optional_timeout": value}

    with pytest.raises(VerificationRunnerError) as raised:
        normalize_verification_commands([command])
    assert raised.value.code == "invalid_verification_command"


def test_code_change_assessment_rejects_unknown_semantic_fields(
    tmp_path: Path,
) -> None:
    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")
    command = normalize_verification_commands([_command()])[0]
    approved, expected = _approved(command, "WI-STRICT-ASSESSMENT")
    with pytest.raises(VerificationRunnerError) as captured:
        runner.not_run(
            approved,
            **expected,
            reason="本环境不具备执行条件。",
            limitations=[],
            code_change_assessment={**_assessment(), "generated_summary": "伪语义"},
        )
    assert captured.value.code == "invalid_code_change_assessment"


def test_runs_exact_selected_command_and_records_bounded_outputs(
    tmp_path: Path,
) -> None:
    commands = normalize_verification_commands([_command()])
    runner = VerificationRunner(
        tmp_path,
        artifact_root=tmp_path / "receipts",
    )

    approved, expected = _approved(commands[0], "WI-VERIFY")
    receipt = runner.run(
        approved,
        **expected,
        limitations=[],
    )

    assert receipt["result"] == "passed"
    assert receipt["exit_code"] == 0
    assert receipt["argv"] == commands[0]["argv"]
    assert receipt["output_summary"]["stdout"] == "verified\r\n" or (
        receipt["output_summary"]["stdout"] == "verified\n"
    )
    assert Path(receipt["raw_output_refs"]["stdout"]).read_text(
        encoding="utf-8"
    ).strip() == "verified"
    assert receipt["code_change_assessment"] is None
    pending = runner.coverage_status(
        commands,
        [receipt],
        work_item_id="WI-VERIFY",
    )
    assert pending["verification_status"] == "pending"
    assert pending["assessment_missing_command_ids"] == ["VC-001"]

    assessed = runner.assess_receipt(receipt, _assessment())
    ready = runner.coverage_status(
        commands,
        [assessed],
        work_item_id="WI-VERIFY",
    )
    assert ready["verification_status"] == "passed"
    assert "ready_for_actual_result" not in ready
    assert "all_passed" not in ready


def test_execution_rejects_stale_or_unconfirmed_plan_approval(
    tmp_path: Path,
) -> None:
    command = normalize_verification_commands([_command()])[0]
    approved, expected = _approved(command, "WI-APPROVAL")
    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")

    with pytest.raises(VerificationRunnerError) as stale:
        runner.run(
            approved,
            **{**expected, "expected_work_item_version": 2},
            limitations=[],
        )
    assert stale.value.code == "verification_approval_stale"

    rejected = {
        **approved,
        "plan_confirmation": {
            "plan_id": approved["plan_id"],
            "accepted": False,
        },
    }
    with pytest.raises(VerificationRunnerError) as unconfirmed:
        runner.run(rejected, **expected, limitations=[])
    assert unconfirmed.value.code == "verification_plan_not_confirmed"


@pytest.mark.parametrize(
    ("argv", "expected_code"),
    [
        (["codex", "exec", "work"], "forbidden_agent_program"),
        ([sys.executable, "codex"], "forbidden_agent_wrapper"),
        (["agy.exe", "--version"], "forbidden_agent_program"),
        ([sys.executable, "agy"], "forbidden_agent_wrapper"),
    ],
)
def test_execution_rejects_agent_program_and_wrapper(
    tmp_path: Path,
    argv: list[str],
    expected_code: str,
) -> None:
    command = normalize_verification_commands(
        [{**_command(), "argv": argv}]
    )[0]
    approved, expected = _approved(command, "WI-NO-AGENT")

    with pytest.raises(VerificationRunnerError) as rejected:
        VerificationRunner(tmp_path).run(
            approved,
            **expected,
            limitations=[],
        )
    assert rejected.value.code == expected_code


def test_nonzero_exit_is_failed_and_timeout_is_blocked(tmp_path: Path) -> None:
    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")
    failed = normalize_verification_commands(
        [_command(code="import sys; print('bad'); sys.exit(7)")]
    )[0]

    approved_failure, expected_failure = _approved(failed, "WI-FAIL")
    failure_receipt = runner.run(
        approved_failure,
        **expected_failure,
        limitations=[],
    )
    assert failure_receipt["result"] == "failed"
    assert failure_receipt["exit_code"] == 7

    timed = _command(code="import time; time.sleep(5)")
    timed["optional_timeout"] = 0.1
    approved_timeout, expected_timeout = _approved(
        normalize_verification_commands([timed])[0],
        "WI-TIMEOUT",
    )
    timeout_receipt = runner.run(
        approved_timeout,
        **expected_timeout,
        limitations=[],
    )
    assert timeout_receipt["result"] == "blocked"
    assert any("timeout" in item for item in timeout_receipt["limitations"])


def test_not_run_is_explicit_and_never_counts_as_passed(tmp_path: Path) -> None:
    commands = normalize_verification_commands([_command()])
    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")

    approved, expected = _approved(commands[0], "WI-NOT-RUN")
    receipt = runner.not_run(
        approved,
        **expected,
        reason="缺少项目负责人控制的硬件。",
        limitations=["没有取得硬件侧结果。"],
        code_change_assessment=_assessment(),
    )
    coverage = runner.coverage_status(
        commands,
        [receipt],
        work_item_id="WI-NOT-RUN",
    )

    assert receipt["result"] == "not_run"
    assert receipt["not_run_reason"] == "缺少项目负责人控制的硬件。"
    assert coverage["verification_status"] == "completed_with_issues"
    assert coverage["results"] == {"VC-001": "not_run"}

    actual_result = {
        "schema_version": "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64,
        "semantic_content_machine_proven": False,
        "effect_summary": "当前环境未完成硬件侧验证。",
        "delivered_outcomes": ["已如实记录未运行的验证。"],
        "deviations": [],
        "limitations": [],
        "verification_receipt_ids": [receipt["receipt_id"]],
        "long_lived_refs": [],
        "method_application_results": [],
        "governance_rule_results": [],
    }
    with pytest.raises(ActualResultError) as raised:
        validate_actual_result(actual_result, coverage, planned_verification_targets=[],)
    assert raised.value.code == "actual_result_limitations_missing"

    accepted = validate_actual_result(
        {
            **actual_result,
            "limitations": ["没有取得硬件侧结果。"],
        },
        coverage, planned_verification_targets=[],
    )
    assert accepted["limitations"] == ["没有取得硬件侧结果。"]


def test_not_run_requires_a_user_visible_limitation(tmp_path: Path) -> None:
    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")
    command = normalize_verification_commands([_command()])[0]
    approved, expected = _approved(command, "WI-NO-LIMITATION")

    with pytest.raises(VerificationRunnerError) as raised:
        runner.not_run(
            approved,
            **expected,
            reason="当前环境不具备执行条件。",
            limitations=[],
            code_change_assessment=_assessment(),
        )
    assert raised.value.code == "invalid_verification_limitations"


def test_missing_or_stale_receipt_blocks_actual_result_readiness(
    tmp_path: Path,
) -> None:
    commands = normalize_verification_commands([_command()])
    empty = VerificationRunner.coverage_status(
        commands,
        [],
        work_item_id="WI-RETEST",
    )
    assert empty["verification_status"] == "pending"
    assert empty["missing_command_ids"] == ["VC-001"]

    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")
    approved, expected = _approved(commands[0], "WI-RETEST")
    receipt = runner.not_run(
        approved,
        **expected,
        reason="当前环境不具备执行条件。",
        limitations=["当前没有可用的执行环境。"],
        code_change_assessment=_assessment(needs_retest=True),
    )
    stale = runner.coverage_status(
        commands,
        [receipt],
        work_item_id="WI-RETEST",
    )
    assert stale["verification_status"] == "pending"
    assert stale["retest_required_command_ids"] == ["VC-001"]


def test_no_planned_command_is_not_required_instead_of_failed() -> None:
    coverage = VerificationRunner.coverage_status(
        [],
        [],
        work_item_id="WI-NO-VERIFICATION",
    )

    assert coverage["verification_status"] == "not_required"
    assert coverage["required_command_ids"] == []
    assert "ready_for_actual_result" not in coverage
    assert "all_passed" not in coverage


def test_receipt_must_match_the_exact_command_and_have_a_real_identity(
    tmp_path: Path,
) -> None:
    commands = normalize_verification_commands([_command()])
    runner = VerificationRunner(tmp_path, artifact_root=tmp_path / "receipts")
    approved, expected = _approved(commands[0], "WI-RECEIPT")
    receipt = runner.not_run(
        approved,
        **expected,
        reason="当前环境不具备执行条件。",
        limitations=["当前没有可用的执行环境。"],
        code_change_assessment=_assessment(),
    )

    empty_identity = {**receipt, "receipt_id": ""}
    with pytest.raises(VerificationRunnerError) as empty:
        runner.coverage_status(
            commands,
            [empty_identity],
            work_item_id="WI-RECEIPT",
        )
    assert empty.value.code == "invalid_verification_receipt"

    changed_command = {**receipt, "argv": [sys.executable, "-c", "print('fake')"]}
    with pytest.raises(VerificationRunnerError) as changed:
        runner.coverage_status(
            commands,
            [changed_command],
            work_item_id="WI-RECEIPT",
        )
    assert changed.value.code == "invalid_verification_receipt"

    with pytest.raises(VerificationRunnerError) as duplicate:
        runner.coverage_status(
            commands,
            [receipt, receipt],
            work_item_id="WI-RECEIPT",
        )
    assert duplicate.value.code == "invalid_verification_receipt"

    replayed = {**receipt, "work_item_id": "WI-OTHER"}
    with pytest.raises(VerificationRunnerError) as replay:
        runner.coverage_status(
            commands,
            [replayed],
            work_item_id="WI-RECEIPT",
        )
    assert replay.value.code == "invalid_verification_receipt"

    missing_limitation = {**receipt, "limitations": []}
    with pytest.raises(VerificationRunnerError) as missing:
        runner.coverage_status(
            commands,
            [missing_limitation],
            work_item_id="WI-RECEIPT",
        )
    assert missing.value.code == "invalid_verification_receipt"


def test_rejects_working_directories_outside_the_worktree(
    tmp_path: Path,
) -> None:
    invalid = {**_command(), "cwd": "../outside"}
    with pytest.raises(VerificationRunnerError) as caught:
        normalize_verification_commands([invalid])
    assert caught.value.code == "invalid_verification_cwd"


def test_actual_result_records_only_real_existing_long_lived_artifacts(
    tmp_path: Path,
) -> None:
    adr = tmp_path / "docs" / "adr" / "ADR-0042.md"
    adr.parent.mkdir(parents=True)
    adr.write_text("# 决定\n", encoding="utf-8")
    coverage = {
        "verification_status": "passed",
        "latest_receipt_ids": {"VC-001": "VR-001"},
    }

    result = validate_actual_result(
        {
            "schema_version": "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64,
            "semantic_content_machine_proven": False,
            "effect_summary": "形成长期架构决定。",
            "delivered_outcomes": ["ADR 已写入项目文件。"],
            "deviations": [],
            "limitations": [],
            "verification_receipt_ids": ["VR-001"],
            "long_lived_refs": [
                {
                    "artifact_id": "ADR-0042",
                    "artifact_type": "adr",
                    "path": "docs/adr/ADR-0042.md",
                    "relation": "introduced",
                }
            ],
            "method_application_results": [],
            "governance_rule_results": [],
        },
        coverage,
        project_dir=tmp_path, planned_verification_targets=[],
    )

    assert result["long_lived_refs"][0]["path"] == (
        "docs/adr/ADR-0042.md"
    )

    with pytest.raises(ActualResultError) as captured:
        validate_actual_result(
            {**result, "program_generated_conclusion": "不应进入 Authority"},
            coverage,
            project_dir=tmp_path, planned_verification_targets=[],
        )
    assert captured.value.code == "invalid_actual_result"
    assert "未知 program_generated_conclusion" in str(captured.value)

    adr.unlink()
    with pytest.raises(ActualResultError) as captured:
        validate_actual_result(result, coverage, project_dir=tmp_path, planned_verification_targets=[],)
    assert captured.value.code == "long_lived_artifact_missing"


def test_actual_result_closes_each_planned_engineering_method_use() -> None:
    coverage = {
        "verification_status": "passed",
        "latest_receipt_ids": {"VC-001": "VR-001"},
    }
    planned = [
        {
            "method_id": "ddd",
            "decision": "applied",
            "planned_uses": [{"use_id": "DDD-USE-001"}],
        }
    ]
    value = {
        "schema_version": "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64,
        "semantic_content_machine_proven": False,
        "effect_summary": "领域术语已按工程方案校正。",
        "delivered_outcomes": ["统一语言与实现使用同一 WorkItem 含义。"],
        "deviations": [],
        "limitations": [],
        "verification_receipt_ids": ["VR-001"],
        "long_lived_refs": [],
        "method_application_results": [
            {
                "method_id": "ddd",
                "use_results": [
                    {
                        "use_id": "DDD-USE-001",
                        "status": "realized",
                        "outcome": "术语合同和实现已对齐。",
                        "evidence_refs": ["VR-001", "delivered_outcomes[0]"],
                    }
                ],
                "deviations": [],
            }
        ],
        "governance_rule_results": [],
    }

    result = validate_actual_result(
        value,
        coverage,
        planned_method_applications=planned, planned_verification_targets=[],
    )
    assert result["method_application_results"][0]["use_results"][0][
        "status"
    ] == "realized"

    missing = {**value, "method_application_results": []}
    with pytest.raises(ActualResultError) as captured:
        validate_actual_result(
            missing,
            coverage,
            planned_method_applications=planned, planned_verification_targets=[],
        )
    assert captured.value.code == "method_application_result_mismatch"

    not_realized = {
        **value,
        "method_application_results": [
            {
                "method_id": "ddd",
                "use_results": [
                    {
                        "use_id": "DDD-USE-001",
                        "status": "not_realized",
                        "outcome": "术语校正尚未完成。",
                        "evidence_refs": ["VR-001"],
                    }
                ],
                "deviations": ["未完成计划的统一语言校正。"],
            }
        ],
    }
    with pytest.raises(ActualResultError) as raised:
        validate_actual_result(
            not_realized,
            coverage,
            planned_method_applications=planned, planned_verification_targets=[],
        )
    assert raised.value.code == "method_application_result_mismatch"


def test_actual_result_closes_each_applicable_governance_rule() -> None:
    coverage = {
        "verification_status": "passed",
        "latest_receipt_ids": {"VC-001": "VR-001"},
    }
    planned_rules = [{"rule_id": "STRIXNOVA-GOV-TEST-001"}]
    value = {
        "schema_version": "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64,
        "semantic_content_machine_proven": False,
        "effect_summary": "已执行工程方案要求的验证。",
        "delivered_outcomes": ["已记录规则逐项闭合结果。"],
        "deviations": [],
        "limitations": [],
        "verification_receipt_ids": ["VR-001"],
        "long_lived_refs": [],
        "method_application_results": [],
        "governance_rule_results": [
            {
                "rule_id": "STRIXNOVA-GOV-TEST-001",
                "status": "satisfied",
                "evidence_refs": ["VR-001"],
                "gaps": [],
                "remediation_actions": [],
                "limitations": [],
            }
        ],
    }

    result = validate_actual_result(
        value,
        coverage,
        planned_governance_rules=planned_rules, planned_verification_targets=[],
    )

    assert result["governance_rule_results"][0]["status"] == "satisfied"
    with pytest.raises(ActualResultError) as missing:
        validate_actual_result(
            {**value, "governance_rule_results": []},
            coverage,
            planned_governance_rules=planned_rules, planned_verification_targets=[],
        )
    assert missing.value.code == "governance_rule_result_mismatch"

    partial = {
        **value,
        "governance_rule_results": [
            {
                "rule_id": "STRIXNOVA-GOV-TEST-001",
                "status": "partially_satisfied",
                "evidence_refs": ["VR-001"],
                "gaps": ["隔离安装验收尚未执行。"],
                "remediation_actions": ["执行隔离安装验收。"],
                "limitations": [],
            }
        ],
    }
    with pytest.raises(ActualResultError) as incomplete:
        validate_actual_result(
            partial,
            coverage,
            planned_governance_rules=planned_rules, planned_verification_targets=[],
        )
    assert incomplete.value.code == "governance_rule_result_mismatch"


def test_actual_result_keeps_each_open_semantic_finding_visible() -> None:
    coverage = {
        "verification_status": "passed",
        "latest_receipt_ids": {"VC-001": "VR-001"},
    }
    planned_reviews = [
        {
            "review_id": "SEMREVIEW-1111111111111111",
            "findings": [
                {
                    "finding_id": "FINDING-001",
                    "status": "open",
                }
            ],
        }
    ]
    value = {
        "schema_version": "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64,
        "semantic_content_machine_proven": False,
        "effect_summary": "已完成可交付部分。",
        "delivered_outcomes": ["实现已通过当前验证。"],
        "deviations": [],
        "limitations": [],
        "verification_receipt_ids": ["VR-001"],
        "long_lived_refs": [],
        "method_application_results": [],
        "governance_rule_results": [],
    }

    with pytest.raises(ActualResultError) as missing:
        validate_actual_result(
            value,
            coverage,
            planned_semantic_reviews=planned_reviews, planned_verification_targets=[],
        )

    assert missing.value.code == "semantic_finding_result_mismatch"
    carried = validate_actual_result(
        {
            **value,
            "limitations": ["FINDING-001 的兼容性影响仍待后续验证。"],
            "semantic_finding_results": [
                {
                    "review_id": "SEMREVIEW-1111111111111111",
                    "finding_id": "FINDING-001",
                    "outcome": "carried_as_limitation",
                    "evidence_refs": [],
                    "limitation_refs": ["limitations[0]"],
                }
            ],
        },
        coverage,
        planned_semantic_reviews=planned_reviews, planned_verification_targets=[],
    )

    assert carried["semantic_finding_results"][0]["finding_id"] == (
        "FINDING-001"
    )

    resolved = validate_actual_result(
        {
            **value,
            "semantic_finding_results": [
                {
                    "review_id": "SEMREVIEW-1111111111111111",
                    "finding_id": "FINDING-001",
                    "outcome": "resolved",
                    "evidence_refs": ["VR-001"],
                    "limitation_refs": [],
                }
            ],
        },
        coverage,
        planned_semantic_reviews=planned_reviews, planned_verification_targets=[],
    )

    assert resolved["semantic_finding_results"][0]["outcome"] == "resolved"
