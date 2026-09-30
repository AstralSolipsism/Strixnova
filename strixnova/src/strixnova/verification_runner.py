"""Bounded execution of coding-agent-selected local verification commands."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime, timezone
import math
import json
import os
from pathlib import Path, PurePosixPath
import secrets
from typing import Any
from strixnova.verification_dependencies import normalize_dependency_checks, collect_dependency_evidence, dependency_evidence_stale, validate_dependency_evidence

from strixnova.test_case_evidence import (
    CaseExecution, TestCaseEvidenceError, merge_configs, normalize_config,
    receipts_with_freshness, snapshot_matches, validate_evidence,
)
from strixnova.process_supervisor import (
    ProcessExecutionError,
    ProcessLimits,
    ProcessPolicy,
    ProcessResult,
    run_process,
)
VERIFICATION_SUMMARY_SCHEMA = "strixnova.verification-summary.v1"
APPROVED_VERIFICATION_REQUEST_SCHEMA = (
    "strixnova.approved-verification-request.v1"
)
VERIFICATION_POLICY_DECISION_SCHEMA = (
    "strixnova.verification-policy-decision.v1"
)
RUN_KINDS = frozenset(
    {
        "targeted_test",
        "integration_test",
        "acceptance_test",
        "typecheck",
        "build",
        "lint",
        "manual_check",
        "full_regression",
    }
)
RESULTS = frozenset({"passed", "failed", "blocked", "not_run"})
VERIFICATION_STATUSES = frozenset(
    {"not_required", "pending", "passed", "completed_with_issues"}
)
_FORBIDDEN_REPOSITORY_ROOTS = frozenset({".git", ".strixnova"})
_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "work_item_id",
        "receipt_id",
        "command_id",
        "argv",
        "cwd",
        "run_kind",
        "covers",
        "reasons",
        "started_at",
        "duration_seconds",
        "exit_code",
        "result",
        "not_run_reason",
        "output_summary",
        "raw_output_refs",
        "limitations",
        "code_change_assessment",
        "approval_ref",
        "case_evidence",
        "repository_id",
        "project_input_snapshot",
        "inputs_changed_during_execution",
        "execution_evidence_unavailable",
        "dependency_evidence",
    }
)


class VerificationRunnerError(RuntimeError):
    """A command or receipt did not satisfy the runner contract."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _text(
    value: Any,
    field: str,
    *,
    code: str = "invalid_verification_command",
) -> str:
    if not isinstance(value, str):
        raise VerificationRunnerError(code, f"{field} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise VerificationRunnerError(code, f"{field} 不能为空")
    return normalized


def _enum(
    value: Any,
    field: str,
    allowed: Sequence[str],
    *,
    code: str = "invalid_verification_command",
) -> str:
    normalized = _text(value, field, code=code)
    vocabulary = frozenset(allowed)
    if normalized not in vocabulary:
        raise VerificationRunnerError(
            code,
            f"{field} 必须是 " + "、".join(sorted(vocabulary)) + " 之一",
        )
    return normalized


def _string_list(
    value: Any,
    field: str,
    *,
    required: bool = False,
    code: str = "invalid_verification_command",
) -> list[str]:
    if not isinstance(value, list):
        raise VerificationRunnerError(code, f"{field} 必须是数组")
    normalized = [
        _text(item, f"{field}[{index}]", code=code)
        for index, item in enumerate(value)
    ]
    if required and not normalized:
        raise VerificationRunnerError(code, f"{field} 不能为空")
    return normalized


def _number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
    exclusive_minimum: bool = False,
    code: str = "invalid_verification_command",
) -> int | float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise VerificationRunnerError(code, f"{field} 必须是数字")
    if isinstance(value, float) and not math.isfinite(value):
        raise VerificationRunnerError(code, f"{field} 必须是有限数字")
    if minimum is not None and (
        value <= minimum if exclusive_minimum else value < minimum
    ):
        qualifier = "大于" if exclusive_minimum else "大于或等于"
        raise VerificationRunnerError(
            code,
            f"{field} 必须{qualifier} {minimum:g}",
        )
    if maximum is not None and value > maximum:
        raise VerificationRunnerError(
            code,
            f"{field} 必须小于或等于 {maximum:g}",
        )
    return value


def _relative_cwd(value: Any) -> str:
    raw = _text(value, "cwd").replace("\\", "/")
    path = PurePosixPath(raw) if raw else None
    if (
        path is None
        or path.is_absolute()
        or ".." in path.parts
        or ":" in raw
        or bool(
            path.parts
            and path.parts[0].casefold() in _FORBIDDEN_REPOSITORY_ROOTS
        )
    ):
        raise VerificationRunnerError(
            "invalid_verification_cwd",
            "验证 cwd 必须是工作树内相对目录",
        )
    normalized = path.as_posix()
    return "." if normalized in {"", "."} else normalized


def _command_key(command: Mapping[str, Any]) -> tuple[tuple[str, ...], str, str, str]:
    return (
        tuple(command["argv"]),
        str(command["cwd"]),
        str(command["run_kind"]),
        str(command.get("command_id") or ""),
        command.get("repository_id"),
        tuple(command.get("input_repository_ids") or []),
        json.dumps(command.get("dependency_checks") or [], sort_keys=True),
    )


def _program_identities(program: str) -> set[str]:
    normalized = program.strip().strip('"').replace("\\", "/").casefold()
    name = PurePosixPath(normalized).name
    stem = PurePosixPath(name).stem
    return {item for item in (normalized, name, stem) if item}


def normalize_verification_commands(
    commands: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Deduplicate execution identities without inventing a command."""

    if not isinstance(commands, Sequence) or isinstance(commands, (str, bytes)):
        raise VerificationRunnerError(
            "invalid_verification_commands",
            "verification_commands 必须是数组",
        )
    normalized: list[dict[str, Any]] = []
    positions: dict[tuple[tuple[str, ...], str, str, str], int] = {}
    for index, raw in enumerate(commands):
        if not isinstance(raw, Mapping):
            raise VerificationRunnerError(
                "invalid_verification_command",
                f"verification_commands[{index}] 必须是对象",
            )
        argv = raw.get("argv")
        if (
            not isinstance(argv, list)
            or not argv
            or any(not isinstance(item, str) or not item for item in argv)
        ):
            raise VerificationRunnerError(
                "invalid_verification_command",
                f"verification_commands[{index}].argv 必须是非空字符串数组",
            )
        cwd = _relative_cwd(raw.get("cwd"))
        run_kind = _enum(
            raw.get("run_kind"),
            f"verification_commands[{index}].run_kind",
            RUN_KINDS,
        )
        covers = _string_list(
            raw.get("covers"),
            f"verification_commands[{index}].covers",
            required=True,
        )
        reason_value = raw.get("reason")
        if reason_value is None:
            existing_reasons = raw.get("reasons")
            if isinstance(existing_reasons, list) and existing_reasons:
                reason_value = existing_reasons[0]
        reason = _text(
            reason_value,
            f"verification_commands[{index}].reason",
        )
        timeout = raw.get("optional_timeout")
        if timeout is not None:
            timeout = _number(
                timeout,
                f"verification_commands[{index}].optional_timeout",
                minimum=0,
                maximum=3600,
                exclusive_minimum=True,
            )
        candidate = {
            "argv": list(argv),
            "cwd": cwd,
            "run_kind": run_kind,
        }
        for field in ("repository_id", "input_repository_ids"):
            if field in raw:
                candidate[field] = raw[field]
        if "dependency_checks" in raw:
            try:
                candidate["dependency_checks"] = normalize_dependency_checks(raw["dependency_checks"])
            except ValueError as error:
                raise VerificationRunnerError("verification_dependency_invalid", str(error)) from error
        if raw.get("command_id") is not None:
            candidate["command_id"] = _text(raw["command_id"], "command_id")
        case_report = None
        if "case_report" in raw:
            try:
                case_report = normalize_config(raw["case_report"], bound=True)
            except TestCaseEvidenceError as error:
                raise VerificationRunnerError(error.code, str(error)) from error
        key = _command_key(candidate)
        existing_index = positions.get(key)
        if existing_index is None:
            command_id = candidate.get("command_id") or f"VC-{len(normalized) + 1:03d}"
            normalized.append(
                {
                    "command_id": command_id,
                    **candidate,
                    "covers": list(dict.fromkeys(covers)),
                    "reasons": [reason],
                    "optional_timeout": timeout,
                    "source_command_indexes": [index],
                }
            )
            if case_report is not None:
                normalized[-1]["case_report"] = case_report
            positions[key] = len(normalized) - 1
            continue
        existing = normalized[existing_index]
        if case_report is not None:
            try:
                existing["case_report"] = merge_configs(existing.get("case_report"), case_report)
            except TestCaseEvidenceError as error:
                raise VerificationRunnerError(error.code, str(error)) from error
        existing["covers"] = list(
            dict.fromkeys([*existing["covers"], *covers])
        )
        existing["reasons"] = list(
            dict.fromkeys([*existing["reasons"], reason])
        )
        existing["source_command_indexes"].append(index)
        timeouts = [
            item
            for item in (existing.get("optional_timeout"), timeout)
            if item is not None
        ]
        existing["optional_timeout"] = max(timeouts) if timeouts else None
    return normalized


def _assessment(
    value: Mapping[str, Any] | None,
    *,
    required: bool = True,
) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        if not required and value is None:
            return None
        raise VerificationRunnerError(
            "code_change_assessment_required",
            "必须由 Agent 明确判断验证后是否发生相关代码变化",
        )
    expected_fields = {"changed_after", "needs_retest", "rationale"}
    if set(value) != expected_fields:
        raise VerificationRunnerError(
            "invalid_code_change_assessment",
            "代码变化判断必须且只能包含 changed_after、needs_retest 和 rationale",
        )
    changed = value.get("changed_after")
    needs_retest = value.get("needs_retest")
    if type(changed) is not bool or type(needs_retest) is not bool:
        raise VerificationRunnerError(
            "invalid_code_change_assessment",
            "changed_after 和 needs_retest 必须是布尔值",
        )
    return {
        "changed_after": changed,
        "needs_retest": needs_retest,
        "rationale": _text(value.get("rationale"), "rationale"),
    }


def _validated_receipt(
    value: Mapping[str, Any],
    expected: Mapping[str, Any],
    *,
    work_item_id: str,
) -> dict[str, Any]:
    """Validate an execution receipt against the exact selected command."""

    def fail(message: str) -> None:
        raise VerificationRunnerError(
            "invalid_verification_receipt",
            message,
        )

    keys = set(value) - {"_case_input_stale"}
    required = _RECEIPT_FIELDS - {"not_run_reason", "case_evidence", "repository_id", "project_input_snapshot", "inputs_changed_during_execution", "execution_evidence_unavailable", "dependency_evidence"}
    missing = sorted(required - keys)
    extra = sorted(keys - _RECEIPT_FIELDS)
    if missing or extra:
        fail(
            "验证回执字段不完整"
            + (f"；缺少 {', '.join(missing)}" if missing else "")
            + (f"；未知 {', '.join(extra)}" if extra else "")
        )
    if value.get("schema_version") != VERIFICATION_SUMMARY_SCHEMA:
        fail("验证回执 schema_version 无效")
    receipt_work_item_id = _text(
        value.get("work_item_id"),
        "work_item_id",
        code="invalid_verification_receipt",
    )
    if receipt_work_item_id != work_item_id:
        fail("验证回执不属于当前 WorkItem")
    receipt_id = _text(
        value.get("receipt_id"),
        "receipt_id",
        code="invalid_verification_receipt",
    )
    command_id = _text(
        value.get("command_id"),
        "command_id",
        code="invalid_verification_receipt",
    )
    if command_id != expected["command_id"]:
        fail(f"验证回执引用错误命令：{command_id or '<empty>'}")
    if value.get("argv") != expected["argv"]:
        fail(f"{command_id} 回执 argv 与工程方案不一致")
    if value.get("cwd") != expected["cwd"]:
        fail(f"{command_id} 回执 cwd 与工程方案不一致")
    if value.get("run_kind") != expected["run_kind"]:
        fail(f"{command_id} 回执 run_kind 与工程方案不一致")
    if value.get("covers") != expected["covers"]:
        fail(f"{command_id} 回执 covers 与工程方案不一致")
    if value.get("reasons") != expected["reasons"]:
        fail(f"{command_id} 回执 reasons 与工程方案不一致")
    if not isinstance(value.get("started_at"), str) or not value["started_at"].strip():
        fail(f"{command_id} 回执缺少 started_at")
    duration = value.get("duration_seconds")
    if (
        not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or duration < 0
    ):
        fail(f"{command_id} 回执 duration_seconds 无效")
    exit_code = value.get("exit_code")
    if exit_code is not None and (
        not isinstance(exit_code, int) or isinstance(exit_code, bool)
    ):
        fail(f"{command_id} 回执 exit_code 无效")
    result = _enum(
        value.get("result"),
        "result",
        RESULTS,
        code="invalid_verification_receipt",
    )
    output = value.get("output_summary")
    if (
        not isinstance(output, Mapping)
        or set(output) != {"stdout", "stderr"}
        or any(not isinstance(output[name], str) for name in ("stdout", "stderr"))
    ):
        fail(f"{command_id} 回执 output_summary 无效")
    raw_refs = value.get("raw_output_refs")
    if (
        not isinstance(raw_refs, Mapping)
        or set(raw_refs) != {"stdout", "stderr"}
        or any(
            raw_refs[name] is not None and not isinstance(raw_refs[name], str)
            for name in ("stdout", "stderr")
        )
    ):
        fail(f"{command_id} 回执 raw_output_refs 无效")
    limitations = value.get("limitations")
    if (
        not isinstance(limitations, list)
        or any(not isinstance(item, str) or not item.strip() for item in limitations)
    ):
        fail(f"{command_id} 回执 limitations 无效")
    assessment = _assessment(
        value.get("code_change_assessment"),
        required=False,
    )
    approval_ref = value.get("approval_ref")
    if (
        not isinstance(approval_ref, Mapping)
        or set(approval_ref)
        != {
            "schema_version",
            "work_item_version",
            "plan_id",
            "policy_id",
            "policy_revision_id",
            "policy_observed_commit",
        }
        or approval_ref.get("schema_version")
        != "strixnova.verification-approval-ref.v1"
        or not isinstance(approval_ref.get("work_item_version"), int)
        or isinstance(approval_ref.get("work_item_version"), bool)
        or int(approval_ref["work_item_version"]) < 1
        or any(
            not isinstance(approval_ref.get(name), str)
            or not str(approval_ref[name]).strip()
            for name in ("plan_id", "policy_id", "policy_revision_id")
        )
        or (
            approval_ref.get("policy_observed_commit") is not None
            and (
                not isinstance(
                    approval_ref.get("policy_observed_commit"), str
                )
                or not str(approval_ref["policy_observed_commit"]).strip()
            )
        )
    ):
        fail(f"{command_id} 回执缺少有效的精确批准引用")

    if result == "passed" and exit_code != 0:
        fail(f"{command_id} passed 回执必须有 exit_code=0")
    if result == "failed" and (
        not isinstance(exit_code, int) or exit_code == 0
    ):
        fail(f"{command_id} failed 回执必须有非零 exit_code")
    if result == "not_run":
        try:
            _text(
                value.get("not_run_reason"),
                "not_run_reason",
                code="invalid_verification_receipt",
            )
        except VerificationRunnerError:
            fail(f"{command_id} not_run 回执必须说明原因")
        if not limitations:
            fail(f"{command_id} not_run 回执必须明确记录至少一项限制")
        if exit_code is not None or duration != 0:
            fail(f"{command_id} not_run 回执不能伪造执行结果")
        if any(raw_refs[name] is not None for name in ("stdout", "stderr")):
            fail(f"{command_id} not_run 回执不能引用执行输出")
    elif "not_run_reason" in value:
        fail(f"{command_id} 已执行回执不能携带 not_run_reason")
    elif value.get("execution_evidence_unavailable") is True:
        if result != "blocked" or any(raw_refs[name] is not None for name in ("stdout", "stderr")) or not limitations:
            fail("丢失执行证据只能记录为具有明确限制的 blocked 回执")
    elif any(
        not isinstance(raw_refs[name], str) or not raw_refs[name].strip()
        for name in ("stdout", "stderr")
    ):
        fail(f"{command_id} 已执行回执必须引用原始输出")

    normalized = {key: item for key, item in value.items() if key != "_case_input_stale"}
    normalized["work_item_id"] = receipt_work_item_id
    normalized["receipt_id"] = receipt_id
    normalized["command_id"] = command_id
    normalized["result"] = result
    normalized["code_change_assessment"] = assessment
    if expected.get("dependency_checks") and result != "not_run" and value.get("execution_evidence_unavailable") is not True:
        try:
            validate_dependency_evidence(value.get("dependency_evidence"), expected["dependency_checks"])
        except ValueError as error:
            fail(str(error))
        if result == "passed" and value["dependency_evidence"]["status"] != "complete":
            fail("缺少或不匹配的依赖证据不能记为通过")
    if "case_report" in expected and result != "not_run" and value.get("execution_evidence_unavailable") is not True:
        try:
            normalized["case_evidence"] = validate_evidence(value.get("case_evidence"), expected["case_report"], receipt_id=receipt_id)
        except TestCaseEvidenceError as error:
            fail(str(error))
        if normalized["case_evidence"]["plan_id"] != value["approval_ref"]["plan_id"]:
            fail("逐用例证据未绑定当前工程方案")
    elif "case_evidence" in value:
        fail("无逐例安排或未运行的命令不能携带逐例执行证据")
    return normalized


class VerificationRunner:
    """Deep module for command normalization, execution, and receipts."""

    def __init__(
        self,
        execution_root: str | Path,
        *,
        artifact_root: str | Path | None = None,
    ) -> None:
        self.execution_root = Path(execution_root).expanduser().resolve()
        if not self.execution_root.is_dir():
            raise VerificationRunnerError(
                "execution_root_missing",
                f"验证工作树不存在：{self.execution_root}",
            )
        self.artifact_root = (
            Path(artifact_root).expanduser().resolve()
            if artifact_root is not None
            else self.execution_root / ".strixnova" / "artifacts"
        )

    def run(
        self,
        approved_request: Mapping[str, Any],
        *,
        expected_work_item_id: str,
        expected_work_item_version: int,
        expected_plan_id: str,
        limitations: Sequence[str],
        cancellation_requested: Callable[[], bool] | None = None,
        receipt_id: str | None = None,
    ) -> dict[str, Any]:
        selected, approval_ref, process_policy = self._approved_command(
            approved_request,
            expected_work_item_id=expected_work_item_id,
            expected_work_item_version=expected_work_item_version,
            expected_plan_id=expected_plan_id,
        )
        working_directory = self._working_directory(selected["cwd"])
        clean_limitations = self._limitations(limitations)
        receipt_id = receipt_id or self._receipt_id(expected_work_item_id)
        self._receipt_path(expected_work_item_id, receipt_id)
        case_execution = None
        if "case_report" in selected:
            try:
                case_execution = CaseExecution(
                    selected["case_report"], execution_root=self.execution_root,
                    artifact_root=self.artifact_root, work_item_id=expected_work_item_id,
                    receipt_id=receipt_id, plan_id=expected_plan_id,
                )
            except (TestCaseEvidenceError, OSError) as error:
                raise VerificationRunnerError(getattr(error, "code", "test_case_input_unavailable"), str(error)) from error
        timeout = selected.get("optional_timeout") or 900
        started_at = _utc_now()
        result: ProcessResult | None = None
        process_error: ProcessExecutionError | None = None
        try:
            result = run_process(
                selected["argv"],
                cwd=working_directory,
                policy=process_policy,
                limits=ProcessLimits(
                    timeout_seconds=float(timeout),
                    cleanup_timeout_seconds=10,
                    max_output_bytes=16 * 1024 * 1024,
                ),
                cancellation_requested=cancellation_requested,
                **({"env": case_execution.env} if case_execution is not None else {}),
            )
        except ProcessExecutionError as error:
            if error.reason == "cleanup_failed":
                raise VerificationRunnerError("verification_execution_unclosed", "验证进程树未确认结束，请先通过维护入口核验并收口该执行") from error
            process_error = error
            if isinstance(error.partial_result, ProcessResult):
                result = error.partial_result

        stdout = result.stdout if result is not None else b""
        stderr = result.stderr if result is not None else b""
        output_refs = self._save_outputs(
            expected_work_item_id,
            receipt_id,
            stdout,
            stderr,
        )
        if process_error is not None:
            outcome = "blocked"
            clean_limitations.append(
                f"{process_error.reason}: {str(process_error)}"
            )
        elif result is not None and result.exit_code == 0:
            outcome = "passed"
        else:
            outcome = "failed"
        receipt = {
            "schema_version": VERIFICATION_SUMMARY_SCHEMA,
            "work_item_id": expected_work_item_id,
            "receipt_id": receipt_id,
            "command_id": selected["command_id"],
            "argv": list(selected["argv"]),
            "cwd": selected["cwd"],
            "run_kind": selected["run_kind"],
            "covers": list(selected["covers"]),
            "reasons": list(selected["reasons"]),
            "started_at": started_at,
            "duration_seconds": (
                result.duration_seconds if result is not None else 0.0
            ),
            "exit_code": result.exit_code if result is not None else None,
            "result": outcome,
            "output_summary": {
                "stdout": self._summary(stdout),
                "stderr": self._summary(stderr),
            },
            "raw_output_refs": output_refs,
            "limitations": clean_limitations,
            "approval_ref": approval_ref,
            # This is intentionally completed by the Agent after the command.
            # Accepting it as run input would turn an observation into a guess.
            "code_change_assessment": None,
        }
        if case_execution is not None:
            receipt["case_evidence"] = case_execution.finish(exit_code=receipt["exit_code"])
        if selected.get("dependency_checks"):
            evidence = collect_dependency_evidence(selected["dependency_checks"], stdout, observed_at=started_at)
            receipt["dependency_evidence"] = evidence
            if evidence["status"] != "complete":
                if receipt["result"] == "passed":
                    receipt["result"] = "blocked"
                receipt["limitations"].append("必要依赖的实际版本、契约或环境证据不完整或不匹配。")
        return receipt

    def _receipt_path(self, work_item_id: str, receipt_id: str) -> Path:
        if not receipt_id or any(not (character.isalnum() or character in '._-') for character in receipt_id):
            raise VerificationRunnerError("verification_receipt_identity_invalid", "验证回执身份不能包含路径")
        safe = ''.join(character if character.isalnum() or character in '._-' else '-' for character in work_item_id).strip('-')
        directory = self.artifact_root / safe
        for path in (self.artifact_root, directory):
            if path.is_symlink() or path.is_junction():
                raise VerificationRunnerError("verification_receipt_path_invalid", "验证回执目录不能经过链接")
        return directory / f'{receipt_id}.receipt.json'

    def save_receipt(self, receipt: Mapping[str, Any]) -> None:
        path = self._receipt_path(receipt['work_item_id'], receipt['receipt_id'])
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(dict(receipt), ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        if path.exists():
            if path.read_bytes() != payload:
                raise VerificationRunnerError("verification_receipt_changed", "已有恢复回执不等于本次执行结果")
            return
        temporary = path.with_name('.' + path.name + '.next')
        with temporary.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def recover_receipt(self, approved_request: Mapping[str, Any], receipt_id: str) -> dict[str, Any]:
        selected, approval, _ = self._approved_command(approved_request, expected_work_item_id=approved_request['work_item_id'], expected_work_item_version=approved_request['work_item_version'], expected_plan_id=approved_request['plan_id'])
        path = self._receipt_path(approved_request['work_item_id'], receipt_id)
        if path.is_symlink() or path.is_junction() or (path.exists() and (not path.is_file() or path.stat().st_size > 16 * 1024 * 1024)):
            raise VerificationRunnerError("verification_receipt_path_invalid", "验证恢复回执不是有界普通文件")
        if path.is_file():
            try:
                receipt = json.loads(path.read_text(encoding='utf-8'))
                validated = _validated_receipt(receipt, selected, work_item_id=approved_request['work_item_id'])
            except (ValueError, TypeError) as error:
                raise VerificationRunnerError("verification_receipt_invalid", "验证恢复回执不可读") from error
            if validated['receipt_id'] != receipt_id or validated['approval_ref'] != approval:
                raise VerificationRunnerError("verification_receipt_binding_changed", "验证恢复回执不属于原执行意图")
            return validated
        # ProjectMaintenance admits this operation only after an interrupted
        # predecessor has been settled. Missing output is never a passed run.
        return {
            'schema_version': VERIFICATION_SUMMARY_SCHEMA, 'work_item_id': approved_request['work_item_id'],
            'receipt_id': receipt_id, 'command_id': selected['command_id'],
            'argv': list(selected['argv']), 'cwd': selected['cwd'], 'run_kind': selected['run_kind'],
            'covers': list(selected['covers']), 'reasons': list(selected['reasons']),
            'started_at': _utc_now(), 'duration_seconds': 0.0, 'exit_code': None, 'result': 'blocked',
            'output_summary': {'stdout': '', 'stderr': ''}, 'raw_output_refs': {'stdout': None, 'stderr': None},
            'limitations': ['原执行没有留下完整回执；结果未知，未重复运行命令。'],
            'approval_ref': approval, 'code_change_assessment': None, 'execution_evidence_unavailable': True,
        }

    def not_run(
        self,
        approved_request: Mapping[str, Any],
        *,
        expected_work_item_id: str,
        expected_work_item_version: int,
        expected_plan_id: str,
        reason: str,
        limitations: Sequence[str],
        code_change_assessment: Mapping[str, Any],
    ) -> dict[str, Any]:
        selected, approval_ref, _ = self._approved_command(
            approved_request,
            expected_work_item_id=expected_work_item_id,
            expected_work_item_version=expected_work_item_version,
            expected_plan_id=expected_plan_id,
        )
        assessment = _assessment(code_change_assessment)
        assert assessment is not None
        clean_limitations = self._limitations(limitations)
        if not clean_limitations:
            raise VerificationRunnerError(
                "invalid_verification_limitations",
                "not_run 必须明确记录至少一项限制",
            )
        return {
            "schema_version": VERIFICATION_SUMMARY_SCHEMA,
            "work_item_id": expected_work_item_id,
            "receipt_id": self._receipt_id(expected_work_item_id),
            "command_id": selected["command_id"],
            "argv": list(selected["argv"]),
            "cwd": selected["cwd"],
            "run_kind": selected["run_kind"],
            "covers": list(selected["covers"]),
            "reasons": list(selected["reasons"]),
            "started_at": _utc_now(),
            "duration_seconds": 0.0,
            "exit_code": None,
            "result": "not_run",
            "not_run_reason": _text(reason, "not_run_reason"),
            "output_summary": {"stdout": "", "stderr": ""},
            "raw_output_refs": {"stdout": None, "stderr": None},
            "limitations": clean_limitations,
            "code_change_assessment": assessment,
            "approval_ref": approval_ref,
        }

    @staticmethod
    def assess_receipt(
        receipt: Mapping[str, Any],
        code_change_assessment: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Attach the Agent's judgment only after execution evidence exists."""

        if not isinstance(receipt, Mapping):
            raise VerificationRunnerError(
                "invalid_verification_receipt",
                "待判断验证回执必须是对象",
            )
        if receipt.get("code_change_assessment") is not None:
            raise VerificationRunnerError(
                "verification_already_assessed",
                "该验证回执已经完成代码变化判断；需要重测时应产生新回执",
            )
        assessment = _assessment(code_change_assessment)
        assert assessment is not None
        updated = dict(receipt)
        updated["code_change_assessment"] = assessment
        return updated

    @staticmethod
    def coverage_status(
        commands: Sequence[Mapping[str, Any]],
        receipts: Sequence[Mapping[str, Any]],
        *,
        work_item_id: str,
        execution_root: str | Path | None = None,
    ) -> dict[str, Any]:
        expected_work_item_id = _text(work_item_id, "work_item_id")
        normalized = normalize_verification_commands(commands)
        expected_by_id = {item["command_id"]: item for item in normalized}
        expected = set(expected_by_id)
        latest: dict[str, dict[str, Any]] = {}
        receipt_ids: set[str] = set()
        effective_receipts = receipts_with_freshness(receipts, Path(execution_root) if execution_root is not None else None)
        for index, receipt in enumerate(effective_receipts):
            if not isinstance(receipt, Mapping):
                raise VerificationRunnerError(
                    "invalid_verification_receipt",
                    f"verifications[{index}] 必须是对象",
                )
            command_id = _text(
                receipt.get("command_id"),
                f"verifications[{index}].command_id",
                code="invalid_verification_receipt",
            )
            if command_id not in expected_by_id:
                raise VerificationRunnerError(
                    "unknown_verification_command",
                    f"验证回执引用未知命令：{command_id}",
                )
            validated = _validated_receipt(
                receipt,
                expected_by_id[command_id],
                work_item_id=expected_work_item_id,
            )
            receipt_id = validated["receipt_id"]
            if receipt_id in receipt_ids:
                raise VerificationRunnerError(
                    "invalid_verification_receipt",
                    f"验证回执身份重复：{receipt_id}",
                )
            receipt_ids.add(receipt_id)
            if receipt.get("_case_input_stale") is True or (receipt.get("dependency_evidence") and dependency_evidence_stale(receipt["dependency_evidence"])):
                validated["_case_input_stale"] = True
            latest[command_id] = validated
        missing = sorted(expected - set(latest))
        retest_required = sorted(
            command_id
            for command_id, receipt in latest.items()
            if receipt.get("_case_input_stale") is True or (
                isinstance(receipt.get("code_change_assessment"), Mapping)
                and receipt["code_change_assessment"].get("needs_retest") is True
            )
        )
        case_evidence = {}
        for command_id, receipt in latest.items():
            recorded = receipt.get("case_evidence")
            if recorded is None:
                continue
            evidence = dict(recorded)
            evidence["freshness"] = "as_recorded"
            if execution_root is not None:
                evidence["freshness"] = "current" if snapshot_matches(Path(execution_root), evidence["input_snapshot"]) else "stale"
            if evidence["status"] == "inputs_changed" or evidence["freshness"] == "stale":
                retest_required.append(command_id)
            case_evidence[command_id] = evidence
        retest_required = sorted(set(retest_required))
        assessment_missing = sorted(
            command_id
            for command_id, receipt in latest.items()
            if receipt.get("code_change_assessment") is None
        )
        results = {
            command_id: str(receipt["result"])
            for command_id, receipt in sorted(latest.items())
        }
        if not expected:
            verification_status = "not_required"
        elif missing or assessment_missing or retest_required:
            verification_status = "pending"
        elif all(result == "passed" for result in results.values()):
            verification_status = "passed"
        else:
            verification_status = "completed_with_issues"
        return {
            "schema_version": "strixnova.verification-coverage.v1",
            "verification_status": verification_status,
            "required_command_ids": sorted(expected),
            "latest_receipt_ids": {
                command_id: str(receipt.get("receipt_id") or "")
                for command_id, receipt in sorted(latest.items())
            },
            "results": results,
            "missing_command_ids": missing,
            "assessment_missing_command_ids": assessment_missing,
            "retest_required_command_ids": retest_required,
            "case_evidence_by_command": case_evidence,
        }

    def _selected_command(self, command: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(command, Mapping):
            raise VerificationRunnerError(
                "invalid_verification_command",
                "验证命令必须是对象",
            )
        normalized = normalize_verification_commands(
            [
                {
                    "argv": command.get("argv"),
                    "cwd": command.get("cwd"),
                    "run_kind": command.get("run_kind"),
                    "covers": command.get("covers"),
                    "reason": (
                        list(command.get("reasons") or [""])[0]
                        if not command.get("reason")
                        else command.get("reason")
                    ),
                    "optional_timeout": command.get("optional_timeout"),
                    **({"case_report": command["case_report"]} if "case_report" in command else {}),
                    **{field: command[field] for field in ("repository_id", "input_repository_ids", "dependency_checks") if field in command},
                }
            ]
        )[0]
        command_id = _text(command.get("command_id"), "command_id")
        normalized["command_id"] = command_id
        normalized["reasons"] = [
            _text(item, "reasons[]")
            for item in list(command.get("reasons") or normalized["reasons"])
        ]
        normalized["covers"] = list(
            dict.fromkeys(
                _string_list(
                    command.get("covers"),
                    "covers",
                    required=True,
                )
            )
        )
        return normalized

    def _approved_command(
        self,
        value: Mapping[str, Any],
        *,
        expected_work_item_id: str,
        expected_work_item_version: int,
        expected_plan_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], ProcessPolicy]:
        """Validate a complete current-plan approval without reading authorities."""

        expected_fields = {
            "schema_version",
            "work_item_id",
            "work_item_version",
            "plan_id",
            "plan_confirmation",
            "policy_decision",
            "command",
        }
        if not isinstance(value, Mapping) or set(value) != expected_fields:
            raise VerificationRunnerError(
                "invalid_verification_approval",
                "验证执行请求必须携带完整且唯一的批准字段",
            )
        if value.get("schema_version") != APPROVED_VERIFICATION_REQUEST_SCHEMA:
            raise VerificationRunnerError(
                "invalid_verification_approval",
                "验证执行请求的结构版本无效",
            )
        if value.get("work_item_id") != expected_work_item_id:
            raise VerificationRunnerError(
                "verification_approval_mismatch",
                "验证批准不属于当前建设事项",
            )
        version = value.get("work_item_version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version != expected_work_item_version
        ):
            raise VerificationRunnerError(
                "verification_approval_stale",
                "验证批准没有绑定当前建设事项版本",
            )
        if value.get("plan_id") != expected_plan_id:
            raise VerificationRunnerError(
                "verification_approval_mismatch",
                "验证批准没有绑定当前工程方案",
            )
        confirmation = value.get("plan_confirmation")
        if confirmation != {"plan_id": expected_plan_id, "accepted": True}:
            raise VerificationRunnerError(
                "verification_plan_not_confirmed",
                "验证执行必须绑定已接受的精确工程方案",
            )

        decision = value.get("policy_decision")
        decision_fields = {
            "schema_version",
            "source_kind",
            "policy_id",
            "policy_revision_id",
            "observed_commit",
            "forbidden_agent_program_names",
            "wrapper_policy",
            "working_directory_policy",
            "plan_binding_required",
        }
        if not isinstance(decision, Mapping) or set(decision) != decision_fields:
            raise VerificationRunnerError(
                "invalid_verification_policy_decision",
                "验证请求没有携带完整政策决议",
            )
        if (
            decision.get("schema_version")
            != VERIFICATION_POLICY_DECISION_SCHEMA
            or decision.get("source_kind")
            not in {"project_engineering_policy", "confirmed_plan_bootstrap"}
            or decision.get("wrapper_policy")
            != "forbidden_unless_exactly_approved"
            or decision.get("working_directory_policy")
            != "project_or_authorized_worktree_only"
            or decision.get("plan_binding_required") is not True
        ):
            raise VerificationRunnerError(
                "invalid_verification_policy_decision",
                "验证政策决议不满足执行硬门",
            )
        for name in ("policy_id", "policy_revision_id"):
            if not isinstance(decision.get(name), str) or not str(
                decision[name]
            ).strip():
                raise VerificationRunnerError(
                    "invalid_verification_policy_decision",
                    "验证政策决议缺少精确身份",
                )
        observed_commit = decision.get("observed_commit")
        if observed_commit is not None and (
            not isinstance(observed_commit, str) or not observed_commit.strip()
        ):
            raise VerificationRunnerError(
                "invalid_verification_policy_decision",
                "验证政策决议的观察版本无效",
            )
        forbidden = decision.get("forbidden_agent_program_names")
        if (
            not isinstance(forbidden, list)
            or not forbidden
            or any(not isinstance(item, str) or not item.strip() for item in forbidden)
        ):
            raise VerificationRunnerError(
                "invalid_verification_policy_decision",
                "验证政策决议必须明确禁止代理程序",
            )

        command = value.get("command")
        if not isinstance(command, Mapping):
            raise VerificationRunnerError(
                "invalid_verification_approval",
                "验证批准缺少精确命令",
            )
        approved_program = command.get("approved_program")
        approved_fields = {
            "declared_program",
            "resolved_program",
            "purpose",
            "argument_policy",
        }
        if (
            not isinstance(approved_program, Mapping)
            or set(approved_program) != approved_fields
            or approved_program.get("argument_policy") != "exact_plan_only"
            or any(
                not isinstance(approved_program.get(name), str)
                or not str(approved_program[name]).strip()
                for name in ("declared_program", "resolved_program", "purpose")
            )
        ):
            raise VerificationRunnerError(
                "invalid_verification_approval",
                "验证命令缺少精确允许程序决议",
            )
        selected = self._selected_command(command)
        if approved_program["resolved_program"] != selected["argv"][0]:
            raise VerificationRunnerError(
                "verification_program_mismatch",
                "验证首个程序与批准结果不一致",
            )
        forbidden_identities = {
            identity
            for name in forbidden
            for identity in _program_identities(name)
        }
        if _program_identities(selected["argv"][0]) & forbidden_identities:
            raise VerificationRunnerError(
                "forbidden_agent_program",
                "验证政策禁止启动智能编码代理程序",
            )
        if any(
            _program_identities(token) & forbidden_identities
            for token in selected["argv"][1:]
        ):
            raise VerificationRunnerError(
                "forbidden_agent_wrapper",
                "验证政策禁止通过包装参数启动智能编码代理程序",
            )
        approval_ref = {
            "schema_version": "strixnova.verification-approval-ref.v1",
            "work_item_version": version,
            "plan_id": expected_plan_id,
            "policy_id": str(decision["policy_id"]),
            "policy_revision_id": str(decision["policy_revision_id"]),
            "policy_observed_commit": observed_commit,
        }
        return (
            selected,
            approval_ref,
            ProcessPolicy.exact(
                f"{decision['policy_id']}@{decision['policy_revision_id']}",
                str(approved_program["purpose"]),
                selected["argv"],
                forbidden_program_names=forbidden,
            ),
        )

    def _working_directory(self, relative: str) -> Path:
        path = (self.execution_root / relative).resolve()
        if path != self.execution_root and self.execution_root not in path.parents:
            raise VerificationRunnerError(
                "verification_cwd_outside_worktree",
                "验证 cwd 超出 WorkItem 工作树",
            )
        if not path.is_dir():
            raise VerificationRunnerError(
                "verification_cwd_missing",
                f"验证 cwd 不存在：{relative}",
            )
        return path

    @staticmethod
    def _limitations(value: Sequence[str]) -> list[str]:
        if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
            raise VerificationRunnerError(
                "invalid_verification_limitations",
                "limitations 必须是字符串数组",
            )
        return [_text(item, "limitations[]") for item in value]

    @staticmethod
    def _summary(payload: bytes, limit: int = 4000) -> str:
        value = payload.decode("utf-8", errors="replace")
        if len(value) <= limit:
            return value
        return value[:limit] + "\n...[output truncated; see raw output]"

    def _receipt_id(self, work_item_id: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in _text(work_item_id, "work_item_id")
        ).strip("-")
        return f"VR-{safe}-{secrets.token_hex(5).upper()}"

    def _save_outputs(
        self,
        work_item_id: str,
        receipt_id: str,
        stdout: bytes,
        stderr: bytes,
    ) -> dict[str, str]:
        safe_work_item = "".join(
            character if character.isalnum() or character in "._-" else "-"
            for character in work_item_id
        ).strip("-")
        directory = self.artifact_root / safe_work_item
        directory.mkdir(parents=True, exist_ok=True)
        refs: dict[str, str] = {}
        for name, payload in (("stdout", stdout), ("stderr", stderr)):
            target = directory / f"{receipt_id}.{name}.log"
            temporary = directory / f".{target.name}.{secrets.token_hex(4)}.tmp"
            temporary.write_bytes(payload)
            os.replace(temporary, target)
            refs[name] = str(target)
        return refs


__all__ = [
    "APPROVED_VERIFICATION_REQUEST_SCHEMA",
    "RESULTS",
    "RUN_KINDS",
    "VERIFICATION_STATUSES",
    "VERIFICATION_SUMMARY_SCHEMA",
    "VERIFICATION_POLICY_DECISION_SCHEMA",
    "VerificationRunner",
    "VerificationRunnerError",
    "normalize_verification_commands",
]
