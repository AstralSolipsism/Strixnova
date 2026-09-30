"""Direction-owned examples; identity and coverage, never business interpretation."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
import re
from typing import Any


DIRECTION_SCHEMA = "strixnova.direction-decision.v1"
EXAMPLE_ID = re.compile(r"DIREX-[0-9A-F]{16}")
MAX_EXAMPLES = 256




class BehaviorExampleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, code: str = "behavior_example_invalid") -> None:
    raise BehaviorExampleError(code, message)


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 16000:
        _fail(f"{field} 必须是非空且有界的文本")
    return value.strip()


def _texts(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > 64:
        _fail(f"{field} 必须是非空且有界的数组")
    result = [_text(item, field) for item in value]
    if len(set(result)) != len(result):
        _fail(f"{field} 不得重复")
    return result


def normalize_behavior(value: Any, *, allow_undetermined: bool = False) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("每项验收必须明确 behavior 例子或不适用理由")
    applicability = value.get("applicability")
    if not isinstance(applicability, str):
        _fail("behavior.applicability 必须是文本枚举")
    if applicability in {"not_applicable", "undetermined"}:
        if set(value) != {"applicability", "reason"}:
            _fail("不适用或未决的 behavior 只能包含 applicability 和 reason")
        if applicability == "undetermined" and not allow_undetermined:
            _fail("行为例子适用性尚未确定，方向不能进入确认", "behavior_examples_undetermined")
        return {"applicability": applicability, "reason": _text(value["reason"], "behavior.reason")}
    if applicability != "required" or set(value) != {"applicability", "examples"}:
        _fail("behavior 必须明确 required、not_applicable 或 undetermined")
    raw_examples = value["examples"]
    if not isinstance(raw_examples, list) or not raw_examples or len(raw_examples) > MAX_EXAMPLES:
        _fail("required 的 behavior 必须有 1 至 256 个具体例子")
    result = []
    seen: set[str] = set()
    for raw in raw_examples:
        if not isinstance(raw, Mapping) or set(raw) != {"example_id", "title", "given", "when", "then", "basis_refs"}:
            _fail("例子必须且只能包含 example_id、title、given、when、then、basis_refs")
        identifier = raw["example_id"]
        if not isinstance(identifier, str) or not EXAMPLE_ID.fullmatch(identifier):
            _fail("example_id 必须为 DIREX- 加十六位大写十六进制字符")
        if identifier in seen:
            _fail(f"行为例子身份重复：{identifier}", "behavior_example_duplicate")
        seen.add(identifier)
        result.append({
            "example_id": identifier,
            "title": _text(raw["title"], "example.title"),
            "given": _texts(raw["given"], "example.given"),
            "when": _text(raw["when"], "example.when"),
            "then": _texts(raw["then"], "example.then"),
            "basis_refs": _texts(raw["basis_refs"], "example.basis_refs"),
        })
    return {"applicability": "required", "examples": result}


def example_catalog(direction: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Return exact examples and their parent/basis from the current direction contract."""
    if direction.get("schema_version") != DIRECTION_SCHEMA:
        _fail("行为例子需要当前完整方向合同", "direction_contract_invalid")
    requirements = {
        f"direction.requirement:{item['requirement_id']}": item["statement"]
        for item in direction.get("scope", [])
    }
    constraints = {
        f"direction.constraint:{item['constraint_id']}": item["statement"]
        for item in direction.get("constraints", [])
    }
    result: dict[str, dict[str, Any]] = {}
    for acceptance in direction.get("acceptance", []):
        behavior = normalize_behavior(acceptance.get("behavior"))
        if behavior["applicability"] != "required":
            continue
        parent = f"direction.acceptance:{acceptance['acceptance_id']}"
        allowed = {
            f"direction.requirement:{identifier}"
            for identifier in acceptance["requirement_refs"]
        } | set(constraints)
        for example in behavior["examples"]:
            reference = f"direction.example:{example['example_id']}"
            if reference in result:
                _fail(f"行为例子身份跨验收重复：{example['example_id']}", "behavior_example_duplicate")
            unknown = set(example["basis_refs"]) - allowed
            if unknown:
                _fail("例子预期依据必须引用本验收的需求或当前约束：" + ", ".join(sorted(unknown)), "behavior_example_basis_unknown")
            basis = {ref: {**requirements, **constraints}[ref] for ref in example["basis_refs"]}
            binding = {"parent_acceptance_ref": parent, "acceptance_statement": acceptance["statement"], "example": example, "basis": basis}
            fingerprint = hashlib.sha256(json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
            result[reference] = {"target_ref": reference, "parent_acceptance_ref": parent, **deepcopy(example), "example_sha256": fingerprint}
    if len(result) > MAX_EXAMPLES:
        _fail("同一方向最多包含 256 个行为例子")
    return result


def example_ids(direction: Mapping[str, Any]) -> set[str]:
    identifiers: set[str] = set()
    for acceptance in direction.get("acceptance") or []:
        behavior = acceptance.get("behavior") if isinstance(acceptance, Mapping) else None
        if not isinstance(behavior, Mapping) or not isinstance(behavior.get("examples"), list):
            continue
        identifiers.update(
            example["example_id"] for example in behavior["examples"]
            if isinstance(example, Mapping) and isinstance(example.get("example_id"), str)
        )
    return identifiers


def example_parents(examples: Mapping[str, Mapping[str, Any]]) -> dict[str, list[str]]:
    parents: dict[str, list[str]] = {}
    for reference, example in examples.items():
        parents.setdefault(str(example["parent_acceptance_ref"]), []).append(reference)
    return {parent: sorted(children) for parent, children in parents.items()}
