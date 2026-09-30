"""Per-target verification arrangements and explicitly attributed results.

Command coverage is derived from the existing command list. Only the targets
that use Agent review, prior evidence or an explicit exception need more input.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any

from strixnova.behavior_examples import example_parents

class VerificationTargetError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code, self.details = code, details


def _fail(message: str, *, code: str = "verification_target_invalid", details: Any = None) -> None:
    raise VerificationTargetError(code, message, details=details)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} 必须是非空文本")
    return value.strip()


def _refs(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        _fail(f"{field} 必须是引用数组")
    result = [_text(item, field) for item in value]
    if len(result) != len(set(result)):
        _fail(f"{field} 引用重复")
    return result


def validate_reviews(
    value: Any, *, targets: set[str], commands: Sequence[Mapping[str, Any]],
    known_evidence: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail("verification_reviews 必须是数组")
    covered = {ref for command in commands for ref in command["covers"]}
    result, seen = [], set()
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"target_ref", "method", "reason", "evidence_refs"}:
            _fail("核验安排必须包含 target_ref、method、reason、evidence_refs")
        target = _text(raw["target_ref"], "target_ref")
        if target not in targets or target in seen or target in covered:
            _fail("核验目标未知、重复或已经由命令覆盖", details=target)
        method = _text(raw["method"], "method")
        if method not in {"agent_review", "existing_evidence", "not_verified"}:
            _fail("核验方式只允许 agent_review、existing_evidence、not_verified")
        evidence = _refs(raw["evidence_refs"], "evidence_refs")
        if set(evidence) - known_evidence or (method != "not_verified" and not evidence):
            _fail("审阅或证据复用必须引用本轮已知依据", details=target)
        seen.add(target)
        result.append({"target_ref": target, "method": method, "reason": _text(raw["reason"], "reason"), "evidence_refs": evidence})
    missing = sorted(targets - covered - seen)
    if missing:
        _fail("以下验收、约束或风险尚无核验安排或明确处置", code="verification_targets_uncovered", details=missing)
    return result


def compile_targets(
    commands: Sequence[Mapping[str, Any]], reviews: Sequence[Mapping[str, Any]],
    *, examples: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    examples = examples or {}
    entries = {item["target_ref"]: {**item, "command_ids": []} for item in reviews}
    for command in commands:
        for target in command["covers"]:
            entry = entries.setdefault(target, {"target_ref": target, "method": "command", "command_ids": [], "evidence_refs": [], "reason": "使用已确认命令的覆盖声明与实际回执；声明不证明测试充分。"})
            entry["command_ids"].append(command["command_id"])
    for ref, example in examples.items():
        if ref not in entries:
            _fail("行为例子缺少已校验核验安排", details=ref)
        entries[ref]["example"] = deepcopy(dict(example))
        if entries[ref]["method"] == "command":
            entries[ref]["assertion_review_required"] = True
            entries[ref]["case_bindings"] = [
                {"command_id": command["command_id"], "test_ids": list(binding["test_ids"])}
                for command in commands
                for binding in command.get("case_report", {}).get("bindings", [])
                if binding["example_ref"] == ref
            ]
    for parent, children in example_parents(examples).items():
        entries[parent] = {
            "target_ref": parent, "method": "examples", "reason": "验收结果由所属例子的实际证据与 Agent 审阅派生。",
            "evidence_refs": [], "command_ids": [], "child_example_refs": children,
        }
    return [entries[key] for key in sorted(entries)]


def assess_targets(
    plan_targets: Sequence[Mapping[str, Any]] | None, value: Any,
    *, coverage: Mapping[str, Any], known_evidence: set[str], limitations: Sequence[str],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not isinstance(value, list):
        _fail("verification_review_results 必须是数组")
    if plan_targets is None:
        _fail("当前工程方案缺少逐项核验目标，不能形成结果", code="verification_targets_missing")
    expected = {item["target_ref"]: item for item in plan_targets if item["method"] not in {"command", "examples"} or item.get("example")}
    submitted = {}
    for raw in value:
        if not isinstance(raw, Mapping) or set(raw) != {"target_ref", "outcome", "rationale", "evidence_refs"}:
            _fail("核验结果必须包含 target_ref、outcome、rationale、evidence_refs")
        target = _text(raw["target_ref"], "target_ref")
        if target not in expected or target in submitted:
            _fail("审阅结果引用未计划或重复的核验目标", details=target)
        plan = expected[target]
        outcome = _text(raw["outcome"], "outcome")
        if outcome not in {"supported", "not_supported", "not_verified"}:
            _fail("审阅结果 outcome 无效")
        if plan["method"] == "not_verified" and outcome != "not_verified":
            _fail("明确不核验的计划不能直接宣称已获支持；请先修订核验安排")
        evidence = _refs(raw["evidence_refs"], "evidence_refs")
        if set(evidence) - (known_evidence | set(plan["evidence_refs"])):
            _fail("核验结果引用未知证据", details=target)
        if outcome != "not_verified" and not evidence:
            _fail("审阅结论必须有明确依据", details=target)
        if outcome != "supported" and not limitations:
            _fail("未核验或不获支持的目标必须保留实际结果限制", details=target)
        submitted[target] = {"target_ref": target, "outcome": outcome, "rationale": _text(raw["rationale"], "rationale"), "evidence_refs": evidence}
    if set(expected) != set(submitted):
        _fail("实际结果缺少已计划的逐项审阅或未核验说明", code="verification_target_results_missing", details=sorted(set(expected) - set(submitted)))
    rows = []
    for plan in plan_targets:
        target = plan["target_ref"]
        if plan["method"] == "examples":
            continue
        if plan["method"] == "command":
            commands = plan["command_ids"]
            results = [coverage.get("results", {}).get(command) for command in commands]
            status = "command_evidence_passed" if results and all(result == "passed" for result in results) else "command_evidence_incomplete"
            row = {"target_ref": target, "method": "command", "status": status, "evidence_refs": [coverage["latest_receipt_ids"][command] for command in commands if command in coverage.get("latest_receipt_ids", {})], "semantic_judgment": "not_machine_proven"}
            if plan.get("example"):
                executions = []
                for binding in plan.get("case_bindings", []):
                    command_id = binding["command_id"]
                    evidence = coverage.get("case_evidence_by_command", {}).get(command_id, {})
                    matches = [item for item in evidence.get("example_results", []) if item["example_ref"] == target]
                    matched = matches[0] if len(matches) == 1 else None
                    valid = bool(
                        evidence.get("status") == "recorded"
                        and evidence.get("freshness") != "stale"
                        and coverage.get("results", {}).get(command_id) == "passed"
                        and matched is not None
                        and matched.get("example_sha256") == plan["example"]["example_sha256"]
                        and [item["test_id"] for item in matched.get("tests", [])] == binding["test_ids"]
                        and matched.get("status") == "passed"
                    )
                    executions.append({"command_id": command_id, "command_result": coverage.get("results", {}).get(command_id, "not_run"), "report_status": evidence.get("status", "unavailable"), "status": "passed" if valid else "with_gaps", "tests": deepcopy(matched["tests"]) if matched else [{"test_id": identifier, "status": "not_run"} for identifier in binding["test_ids"]], "report_ref": evidence.get("report_ref"), "freshness": evidence.get("freshness", "unavailable")})
                executed = bool(executions) and all(item["status"] == "passed" for item in executions)
                review = submitted[target]
                row.update({
                    "status": "case_evidence_passed" if executed and review["outcome"] == "supported" else "case_evidence_incomplete",
                    "example": deepcopy(plan["example"]), "execution_results": executions,
                    "assertion_review": review, "semantic_judgment": "agent",
                })
                if row["status"] != "case_evidence_passed" and not limitations:
                    _fail("行为例子尚未验证或断言审阅未获支持，必须保留限制", details=target)
            rows.append(row)
        else:
            row = submitted[target]
            rows.append({**row, "method": plan["method"], "status": "agent_" + row["outcome"], "semantic_judgment": "agent", **({"example": deepcopy(plan["example"])} if plan.get("example") else {})})
    successful = {"command_evidence_passed", "case_evidence_passed", "agent_supported", "example_evidence_recorded"}
    by_ref = {row["target_ref"]: row for row in rows}
    for plan in plan_targets:
        if plan["method"] != "examples":
            continue
        children = plan["child_example_refs"]
        passed = all(child in by_ref and by_ref[child]["status"] in successful for child in children)
        rows.append({"target_ref": plan["target_ref"], "method": "examples", "status": "example_evidence_recorded" if passed else "example_evidence_incomplete", "child_example_refs": list(children), "semantic_judgment": "agent"})
    complete = all(row["status"] in successful for row in rows)
    return list(submitted.values()), {"schema_version": "strixnova.target-verification.v1", "status": "evidence_recorded" if complete else "with_gaps", "items": rows, "semantic_content_machine_proven": False}
