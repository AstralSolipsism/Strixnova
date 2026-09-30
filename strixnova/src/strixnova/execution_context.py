"""Rebuild execution material from one recorded WorkItem and its exact plan.

No prose is generated or judged here. Project authority material is supplied by
the read model; this module owns the join between the recorded execution facts.
"""

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from strixnova.engineering_change_planning import focused_slice
from strixnova.project_content_snapshot import content_fingerprint
from strixnova.project_authority_progress import current_semantic_reviews


class ExecutionContextError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _object(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def resolved_operations(plan: Mapping[str, Any], implementation_slice: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    operations = list(plan.get("operations") or [])
    if implementation_slice is None:
        references = [(f"operations[{index}]", "plan") for index in range(len(operations))]
    else:
        references = [
            (reference, ownership)
            for field, ownership in (("operation_refs", "owned"), ("continued_operation_refs", "continued"))
            for reference in implementation_slice.get(field) or []
        ]
    result = []
    for reference, ownership in references:
        prefix = "operations["
        index_text = reference[len(prefix):-1] if isinstance(reference, str) and reference.startswith(prefix) and reference.endswith("]") else ""
        if not index_text.isascii() or not index_text.isdigit() or int(index_text) >= len(operations):
            raise ExecutionContextError("plan_operation_missing", f"实施材料引用的文件操作不存在：{reference}")
        operation = operations[int(index_text)]
        if not isinstance(operation, Mapping):
            raise ExecutionContextError("plan_operation_missing", f"实施材料引用的文件操作无效：{reference}")
        result.append({"operation_ref": reference, "slice_ownership": ownership, "operation": deepcopy(dict(operation))})
    return result


def execution_context(work_item: Mapping[str, Any], *, slice_id: str | None = None) -> dict[str, Any]:
    """Select an explicit/current slice while retaining plan-wide constraints."""

    data = _object(work_item.get("data"))
    engineering = _object(data.get("engineering"))
    plan = _object(engineering.get("plan"))
    if not plan:
        raise ExecutionContextError("record_missing", "当前事项尚无工程方案，不能生成实施材料")
    if slice_id is not None:
        matches = [item for item in plan.get("implementation_slices") or [] if item.get("slice_id") == slice_id]
        if len(matches) != 1:
            raise ExecutionContextError("record_missing", f"当前工程方案不存在唯一实施切片：{slice_id}")
        implementation_slice = matches[0]
    else:
        implementation_slice = focused_slice(plan, data.get("verifications") or [], data.get("implementation_slice_completions") or [])
    operations = resolved_operations(plan, implementation_slice)
    command_ids = set(implementation_slice.get("verification_command_ids") or []) if implementation_slice else None
    commands = [command for command in plan.get("verification_commands") or [] if command_ids is None or command["command_id"] in command_ids]
    if command_ids is not None and command_ids != {command["command_id"] for command in commands}:
        raise ExecutionContextError("plan_command_missing", "当前实施切片引用了不存在的验证命令")
    findings = [
        {"review_id": entry["review"].get("review_id"), "source_ref": f"{entry['source_ref']}/findings/{index}", "finding": deepcopy(dict(finding))}
        for entry in current_semantic_reviews(work_item)
        for index, finding in enumerate(entry["review"].get("findings") or [])
        if finding.get("status") != "resolved"
    ]
    assessment = _object(engineering.get("assessment"))
    assessment_ref = _object(plan.get("assessment_ref"))
    assessment_bound = assessment_ref.get("work_item_id") == work_item.get("work_item_id") and all(
        assessment_ref.get(field) is not None and assessment_ref[field] == assessment.get(field)
        for field in ("assessment_id", "assessment_revision")
    )
    gaps = []
    if assessment_bound:
        assessment_material = {
            "source_ref": "engineering.assessment",
            "source_sha256": content_fingerprint(assessment),
            "records": {field: deepcopy(assessment[field]) for field in (
                "source_references", "design_decisions", "alternatives_and_tradeoffs",
                "risk_assessments", "unknowns_and_limitations", "domain_fact_changes", "adr_plans",
            ) if field in assessment},
        }
    else:
        assessment_material = None
        gaps.append({"code": "execution_assessment_not_bound", "message": "工程评估未与当前方案精确绑定，未拼入其中的设计和风险说明"})
    confirmation = _object(data.get("direction_confirmation"))
    return {
        "schema_version": "strixnova.execution-context.v1",
        "source": {
            "work_item_id": work_item.get("work_item_id"),
            "work_item_version": work_item.get("version"),
            "plan_id": plan.get("plan_id"),
            "plan_sha256": content_fingerprint(plan),
            "assessment_ref": deepcopy(dict(assessment_ref)),
            "direction_version": confirmation.get("direction_version"),
            "direction_sha256": content_fingerprint(data.get("direction")),
        },
        "direction": deepcopy(data.get("direction")),
        "slice": deepcopy(implementation_slice),
        "resolved_operations": operations,
        "applicable_rules": deepcopy(plan.get("applicable_rules") or []),
        "assessment_material": assessment_material,
        "open_findings": findings,
        # Plan-wide review arrangements include constraints and risks whose
        # applicability must not be inferred from matching words or filenames.
        "verification_targets": deepcopy(plan.get("verification_targets") or []),
        "verification_commands": deepcopy(commands),
        "blockers": deepcopy(data.get("blockers") or []),
        "gaps": gaps,
        "semantic_content_machine_proven": False,
        "writes_performed": False,
    }
