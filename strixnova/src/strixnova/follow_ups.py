"""Explicit deferred obligations derived from accepted WorkItem results.

Original results stay immutable. Later accepted results address exact source
entries; a completed or cancelled related WorkItem alone resolves nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from datetime import date
import re
from typing import Any


class FollowUpError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code, self.details = code, details


def _fail(message: str, code: str = "follow_up_invalid", details: Any = None) -> None:
    raise FollowUpError(code, message, details=details)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{field} 必须是非空文本")
    return value.strip()


def _refs(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        _fail(f"{field} 必须是引用数组")
    result = [_text(item, field) for item in value]
    if len(result) != len(set(result)):
        _fail(f"{field} 不得重复")
    return result


def normalize_ref(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"work_item_id", "result_version", "follow_up_id"}:
        _fail("跟进引用必须绑定原事项、结果展示版本和跟进条目身份")
    identifier = _text(value["follow_up_id"], "follow_up_id")
    if not re.fullmatch(r"FOLLOWUP-[0-9A-F]{16}", identifier):
        _fail("follow_up_id 格式无效")
    version = value["result_version"]
    if type(version) is not int or version < 1:
        _fail("result_version 必须是正整数")
    return {"work_item_id": _text(value["work_item_id"], "work_item_id"), "result_version": version, "follow_up_id": identifier}


def ref_key(value: Mapping[str, Any]) -> tuple[str, int, str]:
    ref = normalize_ref(value)
    return ref["work_item_id"], ref["result_version"], ref["follow_up_id"]


def declared_refs(direction: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [normalize_ref(ref) for relation in direction.get("work_item_relations", []) for ref in relation.get("follow_up_refs", [])]


def validate_items(value: Any, limitations: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail("follow_up_items 必须是数组")
    result, seen, bound = [], set(), set()
    valid_limits = {f"limitations[{index}]" for index in range(len(limitations))}
    for raw in value:
        fields = {"follow_up_id", "limitation_refs", "disposition", "reason", "responsible_party", "due_on", "review_condition", "completion_criteria"}
        if not isinstance(raw, Mapping) or set(raw) != fields:
            _fail("跟进条目字段不完整或包含未知字段")
        identifier = _text(raw["follow_up_id"], "follow_up_id")
        if not re.fullmatch(r"FOLLOWUP-[0-9A-F]{16}", identifier) or identifier in seen:
            _fail("跟进条目身份无效或重复")
        refs = _refs(raw["limitation_refs"], "limitation_refs")
        if not refs or set(refs) - valid_limits or set(refs) & bound:
            _fail("跟进条目必须唯一处置实际存在的限制")
        disposition = _text(raw["disposition"], "disposition")
        if disposition not in {"deferred", "accepted_limitation"}:
            _fail("跟进处置必须是 deferred 或 accepted_limitation")
        optional = {key: None if raw[key] is None else _text(raw[key], key) for key in ("responsible_party", "due_on", "review_condition", "completion_criteria")}
        if optional["due_on"] is not None:
            try:
                if date.fromisoformat(optional["due_on"]).isoformat() != optional["due_on"]:
                    raise ValueError
            except ValueError:
                _fail("due_on 必须是 YYYY-MM-DD 日期")
        if disposition == "deferred":
            if not optional["responsible_party"] or not optional["completion_criteria"] or not (optional["due_on"] or optional["review_condition"]):
                _fail("延期处理须说明责任、复查日期或条件，以及完成标准")
        elif any(optional.values()):
            _fail("接受限制而结束跟进时，不应同时留下延期承诺")
        seen.add(identifier)
        bound.update(refs)
        result.append({"follow_up_id": identifier, "limitation_refs": refs, "disposition": disposition, "reason": _text(raw["reason"], "reason"), **optional})
    return result


def validate_results(
    value: Any, *, expected_refs: list[dict[str, Any]], known_evidence: set[str],
    limitations: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        _fail("follow_up_results 必须是数组")
    expected, seen, result = {ref_key(ref) for ref in expected_refs}, set(), []
    valid_limits = {f"limitations[{index}]" for index in range(len(limitations))}
    for raw in value:
        fields = {"follow_up_ref", "expected_version", "outcome", "rationale", "evidence_refs", "limitation_refs"}
        if not isinstance(raw, Mapping) or set(raw) != fields:
            _fail("跟进结果字段不完整或包含未知字段")
        ref = normalize_ref(raw["follow_up_ref"])
        key = ref_key(ref)
        if key not in expected or key in seen:
            _fail("跟进结果没有对应已确认方向中的精确关系，或重复处置")
        version = raw["expected_version"]
        if type(version) is not int or version < 1:
            _fail("跟进结果必须携带刚读取的 expected_version")
        outcome = _text(raw["outcome"], "outcome")
        if outcome not in {"resolved", "partially_resolved", "still_open", "accepted_limitation"}:
            _fail("跟进结果 outcome 无效")
        evidence = _refs(raw["evidence_refs"], "evidence_refs")
        refs = _refs(raw["limitation_refs"], "limitation_refs")
        if set(evidence) - known_evidence or set(refs) - valid_limits:
            _fail("跟进结果引用未知证据或限制")
        if outcome == "resolved":
            if not evidence or refs:
                _fail("已解决必须引用实际依据，不能同时继续保留该限制")
        elif not refs:
            _fail("部分解决、继续跟进或接受限制必须保留明确限制")
        seen.add(key)
        result.append({"follow_up_ref": ref, "expected_version": version, "outcome": outcome, "rationale": _text(raw["rationale"], "rationale"), "evidence_refs": evidence, "limitation_refs": refs})
    if seen != expected:
        _fail("实际结果缺少已承接问题的逐项处置", "follow_up_results_missing", [list(key) for key in sorted(expected - seen)])
    return result


def project_records(records: Iterable[Mapping[str, Any]]) -> dict[tuple[str, int, str], dict[str, Any]]:
    """Consume recorded candidate/decision facts without re-parsing user text."""
    candidates, result = {}, {}
    for record in records:
        work_item_id, facts = record["work_item_id"], record["facts"]
        candidate = facts.get("candidate")
        if isinstance(candidate, Mapping) and candidate.get("kind") == "actual_result":
            value = candidate.get("value") or {}
            if value.get("schema_version") == "strixnova.actual-result.v1" and (value.get("follow_up_items") or value.get("follow_up_results")):
                candidates[(work_item_id, candidate["fingerprint"])] = (record["version"], value)
        decision = facts.get("decision")
        if not isinstance(decision, Mapping) or decision.get("kind") != "actual_result" or decision.get("accepted") is not True:
            continue
        accepted = candidates.get((work_item_id, decision.get("candidate_fingerprint")))
        if accepted is None:
            continue
        result_version, value = accepted
        for item in value.get("follow_up_items", []):
            ref = {"work_item_id": work_item_id, "result_version": result_version, "follow_up_id": item["follow_up_id"]}
            key = ref_key(ref)
            if key in result:
                _fail("同一跟进条目存在重复接受记录", "follow_up_history_invalid")
            result[key] = {"follow_up_ref": ref, "version": record["sequence"], "origin": deepcopy(item), "limitations": [value["limitations"][int(ref_text[12:-1])] for ref_text in item["limitation_refs"]], "state": "open" if item["disposition"] == "deferred" else "accepted_limitation", "latest_resolution": None}
        for resolution in value.get("follow_up_results", []):
            key = ref_key(resolution["follow_up_ref"])
            if key not in result or result[key]["version"] != resolution["expected_version"]:
                _fail("跟进历史的处置链不连续", "follow_up_history_invalid")
            target = result[key]
            target["state"] = resolution["outcome"] if resolution["outcome"] in {"resolved", "accepted_limitation"} else "open"
            target["version"] = record["sequence"]
            target["latest_resolution"] = {**deepcopy(resolution), "work_item_id": work_item_id, "result_version": result_version}
    return result


def check_current_results(value: Mapping[str, Any], state: Mapping[tuple[str, int, str], Mapping[str, Any]], work_item_id: str) -> None:
    """Called again inside the accepting Authority transaction to fence races."""
    identifiers = {key[2] for key in state if key[0] == work_item_id}
    if any(item["follow_up_id"] in identifiers for item in value.get("follow_up_items", [])):
        _fail("已接受的跟进身份不能用于另一份结果；请提交原条目的处置", "follow_up_identity_reused")
    for resolution in value.get("follow_up_results", []):
        key = ref_key(resolution["follow_up_ref"])
        current = state.get(key)
        if current is None or current["state"] != "open":
            _fail("所引用的跟进问题不存在、未接受或已经结束", "follow_up_not_open")
        if current["version"] != resolution["expected_version"]:
            _fail("跟进问题已被其他结果推进，请重新读取并复核当前候选", "follow_up_conflict")
