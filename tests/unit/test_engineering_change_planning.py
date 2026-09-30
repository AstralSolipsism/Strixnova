from __future__ import annotations

from copy import deepcopy

import pytest

from strixnova.engineering_change_planning import (
    ChangePlanningError,
    compile_implementation_slices,
    implementation_reporting_coverage,
    implementation_slice_reportability,
    implementation_slice_progress,
    implementation_slices_reportable,
    permitted_slice_operation_paths,
    validate_change_planning,
)
from tests.support.governance_assessment import semantic_review_fixture


OBSERVED_COMMIT = "a" * 40


def _known_authorities() -> dict[str, dict[str, str]]:
    return {
        "PRODUCT-1111111111111111": {
            "authority_kind": "product_definition",
            "artifact_type": "product_governance",
            "path": "docs/product/definition.yaml",
            "revision_id": "REVISION-1111111111111111",
            "revision_status": "confirmed",
            "adoption_status": "current",
            "target_refs": [
                "PRODUCT-1111111111111111",
                "CAPABILITY-0000000000000001",
            ],
        },
        "MODEL-2222222222222222": {
            "authority_kind": "domain_model",
            "artifact_type": "domain_model",
            "path": "docs/domain/model.yaml",
            "revision_id": "MODELREV-2222222222222222",
            "revision_status": "confirmed",
            "adoption_status": "current",
            "target_refs": [
                "MODEL-2222222222222222",
                "FACT-0000000000000001",
            ],
        },
        "ARCH-3333333333333333": {
            "authority_kind": "target_architecture",
            "artifact_type": "architecture",
            "path": "docs/architecture/model.yaml",
            "revision_id": "ARCHREV-3333333333333333",
            "revision_status": "confirmed",
            "adoption_status": "current",
            "target_refs": [
                "ARCH-3333333333333333",
                "MODULE-0000000000000001",
            ],
        },
        "ALIGNMODEL-4444444444444444": {
            "authority_kind": "implementation_alignment",
            "artifact_type": "domain_alignment",
            "path": "docs/implementation-alignment/model.yaml",
            "revision_id": "ALIGNREV-4444444444444444",
            "revision_status": "confirmed",
            "adoption_status": "current",
            "target_refs": [
                "ALIGNMODEL-4444444444444444",
                "DEVIATION-0000000000000001",
            ],
        },
    }


def _owner_view() -> dict:
    return {
        "schema_version": "strixnova.owner-view.v1",
        "decision_support": {
            "current_problem": "增加一项可追溯能力。",
            "why_it_matters": "缺少追溯会让负责人无法判断结果来源。",
            "impact": "产品、领域和实现会增加对应读取能力。",
            "recommendation": "按上游到下游顺序实施。",
            "alternatives": ["保留现状并继续人工追溯。"],
            "no_action_consequence": "当前追溯缺口继续存在。",
            "next_step": "确认方案后执行首个切片。",
            "necessary_questions": [],
        },
        "engineering_context": {
            "product_and_domain_change": "产品能力和领域规则各增加一项对应含义。",
            "architecture_responsibilities": "现有模块承接新责任，不增加平行引擎。",
            "implementation_order": "先修改上游产品，再修改领域并分别验证。",
            "highest_impact_risks": "上下游含义不一致会让实现锚定错误目标。",
            "verification_and_observation": "每个切片运行自己的验证并保存回执。",
            "uncertainties": "没有未解决的高影响决定。",
        },
        "current_decision": "是否接受该工程方案。",
        "semantic_content_machine_proven": False,
    }


def _change_set() -> dict:
    known = _known_authorities()
    rows = (
        (
            "product_definition",
            known["PRODUCT-1111111111111111"],
            "PRODUCT-1111111111111111",
            "REVISION-AAAAAAAAAAAAAAAA",
        ),
        (
            "domain_model",
            known["MODEL-2222222222222222"],
            "MODEL-2222222222222222",
            "MODELREV-BBBBBBBBBBBBBBBB",
        ),
        (
            "target_architecture",
            known["ARCH-3333333333333333"],
            "ARCH-3333333333333333",
            "ARCHREV-CCCCCCCCCCCCCCCC",
        ),
        (
            "implementation_alignment",
            known["ALIGNMODEL-4444444444444444"],
            "ALIGNMODEL-4444444444444444",
            "ALIGNREV-DDDDDDDDDDDDDDDD",
        ),
    )
    return {
        "schema_version": "strixnova.authority-change-set.v1",
        "change_set_id": "AUTHCHANGE-AAAAAAAAAAAAAAAA",
        "work_item_id": "WI-CHANGE-PLANNING",
        "base_authorities": [
            {
                "authority_kind": kind,
                "artifact_id": artifact_id,
                "revision_id": authority["revision_id"],
                "path": authority["path"],
                "status": "confirmed",
                "observed_commit": OBSERVED_COMMIT,
            }
            for kind, authority, artifact_id, _candidate_revision in rows
        ],
        "candidate_authorities": [
            {
                "authority_kind": kind,
                "artifact_id": artifact_id,
                "revision_id": candidate_revision,
                "path": authority["path"],
                "status": "draft",
                "supersedes_revision_id": authority["revision_id"],
                "adoption_effect": "not_adopted",
            }
            for kind, authority, artifact_id, candidate_revision in rows
            if candidate_revision is not None
        ],
        "changes": [
            {
                "change_id": "AUTHOP-001",
                "authority_kind": "product_definition",
                "operation": "add",
                "target_ref": "CAPABILITY-AAAAAAAAAAAAAAAA",
                "summary": "增加一项公开产品能力。",
                "evidence_refs": ["SRC-001"],
            },
            {
                "change_id": "AUTHOP-002",
                "authority_kind": "domain_model",
                "operation": "add",
                "target_ref": "FACT-BBBBBBBBBBBBBBBB",
                "summary": "增加解释该能力的领域事实。",
                "evidence_refs": ["SRC-001"],
            },
            {
                "change_id": "AUTHOP-003",
                "authority_kind": "target_architecture",
                "operation": "modify",
                "target_ref": "ARCH-3333333333333333",
                "summary": "更新目标架构对新领域修订的精确绑定。",
                "evidence_refs": ["SRC-001"],
            },
            {
                "change_id": "AUTHOP-004",
                "authority_kind": "implementation_alignment",
                "operation": "modify",
                "target_ref": "ALIGNMODEL-4444444444444444",
                "summary": "先绑定新上游修订并如实记录当前代码缺口。",
                "evidence_refs": ["SRC-001"],
            },
        ],
        "downstream_dispositions": [
            {
                "source_authority_kind": "product_definition",
                "target_authority_kind": "domain_model",
                "disposition": "revise",
                "reason": "领域模型必须解释新增产品能力。",
            },
            {
                "source_authority_kind": "product_definition",
                "target_authority_kind": "target_architecture",
                "disposition": "revise",
                "reason": "目标架构必须绑定新的领域精确修订。",
            },
            {
                "source_authority_kind": "product_definition",
                "target_authority_kind": "implementation_alignment",
                "disposition": "revise",
                "reason": "实现对齐必须绑定新的上游精确修订。",
            },
            {
                "source_authority_kind": "domain_model",
                "target_authority_kind": "target_architecture",
                "disposition": "revise",
                "reason": "目标架构必须绑定新的领域精确修订。",
            },
            {
                "source_authority_kind": "domain_model",
                "target_authority_kind": "implementation_alignment",
                "disposition": "revise",
                "reason": "实现对齐必须绑定新的领域精确修订。",
            },
            {
                "source_authority_kind": "target_architecture",
                "target_authority_kind": "implementation_alignment",
                "disposition": "revise",
                "reason": "实现对齐必须绑定新的架构精确修订。",
            },
        ],
        "semantic_content_machine_proven": False,
    }


def _assessment() -> tuple[dict, list[dict], list[dict]]:
    operations = [
        {
            "action": "modify",
            "path": "docs/product/definition.yaml",
            "long_lived_artifact": {
                "artifact_id": "PRODUCT-1111111111111111",
                "artifact_type": "product_governance",
            },
        },
        {
            "action": "modify",
            "path": "docs/domain/model.yaml",
            "long_lived_artifact": {
                "artifact_id": "MODEL-2222222222222222",
                "artifact_type": "domain_model",
            },
        },
        {
            "action": "modify",
            "path": "docs/architecture/model.yaml",
            "long_lived_artifact": {
                "artifact_id": "ARCH-3333333333333333",
                "artifact_type": "architecture",
            },
        },
        {
            "action": "modify",
            "path": "docs/implementation-alignment/model.yaml",
            "long_lived_artifact": {
                "artifact_id": "ALIGNMODEL-4444444444444444",
                "artifact_type": "domain_alignment",
            },
        },
        {"action": "modify", "path": "src/app.py"},
    ]
    commands = [{"command_id": "VC-001"}, {"command_id": "VC-002"}]
    assessment = {
        "authority_change_set": _change_set(),
        "semantic_review": semantic_review_fixture(
            "SRC-001",
            "authority_change_set",
        ),
        "implementation_slices": [
            {
                "schema_version": "strixnova.implementation-slice.v1",
                "slice_id": "SLICE-001",
                "purpose": "先形成完整上游权威和编码前实现对齐候选。",
                "implements": [
                    "authority_change_set.changes[0]",
                    "authority_change_set.changes[1]",
                    "authority_change_set.changes[2]",
                    "authority_change_set.changes[3]",
                ],
                "operation_refs": [
                    "operations[0]",
                    "operations[1]",
                    "operations[2]",
                    "operations[3]",
                ],
                "depends_on": [],
                "parallel_safe_with": [],
                "completion_criteria": ["完整候选包和编码前缺口可通过结构校验。"],
                "verification_command_refs": ["verification_commands[0]"],
                "rollback_or_recovery": "失败时恢复产品候选后重新起草。",
            },
            {
                "schema_version": "strixnova.implementation-slice.v1",
                "slice_id": "SLICE-002",
                "purpose": "实现业务代码并最终刷新同一实现对齐草稿。",
                "implements": [
                    "direction.acceptance:DIRACC-3333333333333333"
                ],
                "operation_refs": ["operations[4]"],
                "continued_operation_refs": ["operations[3]"],
                "depends_on": ["SLICE-001"],
                "parallel_safe_with": [],
                "completion_criteria": ["业务实现与最终实现对齐一致。"],
                "verification_command_refs": ["verification_commands[1]"],
                "rollback_or_recovery": "失败时保留完整候选并修正业务实现。",
            },
        ],
        "owner_view": _owner_view(),
    }
    return assessment, operations, commands


def _validate(
    assessment: dict,
    operations: list[dict],
    commands: list[dict],
    *,
    known_authorities: dict[str, dict[str, str]] | None = None,
) -> dict:
    return validate_change_planning(
        assessment,
        work_item_id="WI-CHANGE-PLANNING",
        investigation_ref=OBSERVED_COMMIT,
        formal_implementation=True,
        change_kind="add_capability",
        impact_scope={
            "affected": [
                {"dimension": "product_scope"},
                {"dimension": "domain"},
            ],
            "unknown": [],
        },
        operations=operations,
        verification_commands=commands,
        known_authorities=known_authorities or _known_authorities(),
        known_evidence_refs={"SRC-001"},
        known_decision_refs={"direction"},
        valid_implements_refs={
            "direction.acceptance:DIRACC-3333333333333333"
        },
    )


def test_complete_change_plan_binds_exact_revisions_and_slice_progress() -> None:
    assessment, operations, commands = _assessment()

    normalized = _validate(assessment, operations, commands)
    assert normalized["owner_view"]["decision_support"] == (
        assessment["owner_view"]["decision_support"]
    )
    assert normalized["owner_view"]["engineering_context"] == (
        assessment["owner_view"]["engineering_context"]
    )
    compiled = compile_implementation_slices(
        normalized["implementation_slices"],
        commands,
        operations,
    )
    plan = {"implementation_slices": compiled, "operations": operations}

    assert [item["slice_id"] for item in compiled] == [
        "SLICE-001",
        "SLICE-002",
    ]
    assert implementation_slice_progress(plan, [])["current_slice_id"] == (
        "SLICE-001"
    )
    assert permitted_slice_operation_paths(plan, []) == {
        "schema_version": "strixnova.implementation-slice-path-scope.v1",
        "current_slice_id": "SLICE-001",
        "completed_slice_ids": [],
        "permitted_paths": [
            "docs/architecture/model.yaml",
            "docs/domain/model.yaml",
            "docs/implementation-alignment/model.yaml",
            "docs/product/definition.yaml",
        ],
        "planned_paths": [
            "docs/architecture/model.yaml",
            "docs/domain/model.yaml",
            "docs/implementation-alignment/model.yaml",
            "docs/product/definition.yaml",
            "src/app.py",
        ],
        "future_paths": ["src/app.py"],
    }
    progress = implementation_slice_progress(
        plan,
        [
            {
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": {"needs_retest": False},
            }
        ],
    )
    assert progress["completed_slice_ids"] == ["SLICE-001"]
    assert progress["current_slice_id"] == "SLICE-002"
    assert permitted_slice_operation_paths(
        plan,
        [
            {
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": {"needs_retest": False},
            }
        ],
    )["permitted_paths"] == [
        "docs/architecture/model.yaml",
        "docs/domain/model.yaml",
        "docs/implementation-alignment/model.yaml",
        "docs/product/definition.yaml",
        "src/app.py",
    ]


def test_owner_view_limits_questions_without_judging_their_meaning() -> None:
    assessment, operations, commands = _assessment()
    assessment["owner_view"]["decision_support"]["necessary_questions"] = [
        f"问题 {index}"
        for index in range(1, 7)
    ]

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("necessary_questions 最多包含 5 项" in issue for issue in captured.value.issues)


def test_owner_view_requires_decision_support_but_does_not_score_prose() -> None:
    assessment, operations, commands = _assessment()
    del assessment["owner_view"]["decision_support"]["recommendation"]

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("recommendation" in issue for issue in captured.value.issues)


def test_core_authority_move_binds_candidate_to_the_explicit_destination() -> None:
    assessment, operations, commands = _assessment()
    destination = "docs/product/product-definition.yaml"
    operations[0]["action"] = "move"
    operations[0]["to_path"] = destination
    assessment["authority_change_set"]["candidate_authorities"][0][
        "path"
    ] = destination

    normalized = _validate(assessment, operations, commands)

    assert normalized["authority_change_set"]["candidate_authorities"][0][
        "path"
    ] == destination


def test_core_authority_path_change_without_move_is_rejected() -> None:
    assessment, operations, commands = _assessment()
    assessment["authority_change_set"]["candidate_authorities"][0][
        "path"
    ] = "docs/product/product-definition.yaml"

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any(
        "只有显式 move 操作可以改变权威根路径" in issue
        or "实际候选路径" in issue
        for issue in captured.value.issues
    )


def test_zero_command_slice_is_not_reportable_without_explicit_completion() -> None:
    plan = {
        "implementation_slices": [
            {
                "schema_version": "strixnova.implementation-slice-plan.v1",
                "slice_id": "SLICE-001",
                "verification_command_ids": [],
            }
        ]
    }

    assert implementation_slices_reportable(plan, [], []) is False
    assert implementation_slices_reportable(
        plan,
        [],
        [
            {
                "schema_version": "strixnova.implementation-slice-completion.v1",
                "slice_id": "SLICE-001",
                "semantic_content_machine_proven": False,
            }
        ],
    ) is True


def test_upstream_revision_requires_an_implementation_alignment_candidate() -> None:
    assessment, operations, commands = _assessment()
    change_set = assessment["authority_change_set"]
    change_set["candidate_authorities"] = [
        item
        for item in change_set["candidate_authorities"]
        if item["authority_kind"] != "implementation_alignment"
    ]
    change_set["changes"] = [
        item
        for item in change_set["changes"]
        if item["authority_kind"] != "implementation_alignment"
    ]
    for item in change_set["downstream_dispositions"]:
        if item["target_authority_kind"] == "implementation_alignment":
            item["disposition"] = "unchanged"
            item["reason"] = "错误地继续绑定旧实现对齐。"
    operations.pop(3)
    first_slice = assessment["implementation_slices"][0]
    first_slice["implements"] = [
        "authority_change_set.changes[0]",
        "authority_change_set.changes[1]",
        "authority_change_set.changes[2]",
    ]
    first_slice["operation_refs"] = [
        "operations[0]",
        "operations[1]",
        "operations[2]",
    ]
    second_slice = assessment["implementation_slices"][1]
    second_slice["operation_refs"] = ["operations[3]"]
    second_slice["continued_operation_refs"] = []

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any(
        "上游权威修订必须同时形成实现对齐候选" in issue
        for issue in captured.value.issues
    )


def test_change_set_rejects_stale_base_and_missing_downstream_disposition() -> None:
    assessment, operations, commands = _assessment()
    assessment["authority_change_set"]["base_authorities"][0][
        "revision_id"
    ] = "REVISION-CCCCCCCCCCCCCCCC"
    assessment["authority_change_set"]["downstream_dispositions"].pop()

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("不是调查版本采用的精确权威事实" in issue for issue in captured.value.issues)
    assert any("缺少上游变化处置" in issue for issue in captured.value.issues)


def test_change_set_rejects_wrong_kind_and_dangling_target_references() -> None:
    assessment, operations, commands = _assessment()
    changes = assessment["authority_change_set"]["changes"]
    changes[0]["target_ref"] = "FACT-AAAAAAAAAAAAAAAA"
    changes[2]["target_ref"] = "MODULE-EEEEEEEEEEEEEEEE"

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("不属于 product_definition" in issue for issue in captured.value.issues)
    assert any("不是当前权威中的已知身份" in issue for issue in captured.value.issues)


def test_change_set_rejects_cross_kind_reuse_of_existing_target_identity() -> None:
    assessment, operations, commands = _assessment()
    known_authorities = _known_authorities()
    shared_constraint_id = "CONSTRAINT-AAAAAAAAAAAAAAAA"
    known_authorities["PRODUCT-1111111111111111"]["target_refs"].append(
        shared_constraint_id
    )
    architecture_change = assessment["authority_change_set"]["changes"][2]
    architecture_change["operation"] = "add"
    architecture_change["target_ref"] = shared_constraint_id

    with pytest.raises(ChangePlanningError) as captured:
        _validate(
            assessment,
            operations,
            commands,
            known_authorities=known_authorities,
        )

    assert any(
        "不能跨种类重复新增" in issue and "product_definition" in issue
        for issue in captured.value.issues
    )


def test_change_set_rejects_duplicate_new_identity_within_one_authority() -> None:
    assessment, operations, commands = _assessment()
    duplicate = deepcopy(assessment["authority_change_set"]["changes"][1])
    duplicate["change_id"] = "AUTHOP-005"
    assessment["authority_change_set"]["changes"].append(duplicate)

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any(
        "重复引入同一新增身份" in issue
        and "FACT-BBBBBBBBBBBBBBBB" in issue
        for issue in captured.value.issues
    )


def test_change_set_rejects_unnecessary_or_unverifiable_authority_claims() -> None:
    assessment, operations, commands = _assessment()

    with pytest.raises(ChangePlanningError) as captured:
        validate_change_planning(
            assessment,
            work_item_id="WI-CHANGE-PLANNING",
            investigation_ref=OBSERVED_COMMIT,
            formal_implementation=True,
            change_kind="modify_existing",
            impact_scope={"affected": [], "unknown": []},
            operations=[{"action": "modify", "path": "src/module.py"}],
            verification_commands=commands,
            known_authorities={},
            known_evidence_refs={"SRC-001"},
            known_decision_refs={"direction"},
            valid_implements_refs={
                "direction.acceptance:DIRACC-3333333333333333"
            },
        )

    assert any("不应提交 authority_change_set" in issue for issue in captured.value.issues)
    assert any("完整采用基线" in issue for issue in captured.value.issues)


def test_semantic_review_cannot_hide_open_high_impact_finding() -> None:
    assessment, operations, commands = _assessment()
    review = assessment["semantic_review"]
    review["findings"] = [
        {
            "finding_id": "FINDING-001",
            "perspective": "product_to_domain_coverage",
            "severity": "high",
            "status": "open",
            "locations": ["authority_change_set.changes[0]"],
            "statement": "新增产品能力没有完整领域解释。",
            "impact": "实现可能锚定错误含义。",
            "recommendation": "先补齐领域事实再进入确认。",
            "owner_decision_required": True,
            "decision_refs": [],
            "resolution": None,
        }
    ]
    first_check = review["checks"][0]
    first_check["status"] = "finding"
    first_check["finding_ids"] = ["FINDING-001"]
    review["question_budget"]["remaining_high_impact_decisions"] = [
        "是否接受缺失领域解释的风险"
    ]

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("未闭合的高影响语义发现" in issue for issue in captured.value.issues)
    assert any("仍有高影响决定未解决" in issue for issue in captured.value.issues)


def test_semantic_review_cannot_self_accept_an_owner_decision() -> None:
    assessment, operations, commands = _assessment()
    review = assessment["semantic_review"]
    review["findings"] = [
        {
            "finding_id": "FINDING-001",
            "perspective": "product_to_domain_coverage",
            "severity": "high",
            "status": "accepted_risk",
            "locations": ["authority_change_set.changes[0]"],
            "statement": "产品与领域暂时不完整对应。",
            "impact": "实施可能锚定不完整目标。",
            "recommendation": "由项目负责人明确决定是否接受风险。",
            "owner_decision_required": True,
            "decision_refs": ["SRC-001"],
            "resolution": "智能编码代理自行标记为接受。",
        }
    ]
    review["checks"][0]["status"] = "finding"
    review["checks"][0]["finding_ids"] = ["FINDING-001"]
    review["question_budget"]["resolved_decision_refs"] = ["SRC-001"]

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("不是已确认的项目负责人决定" in issue for issue in captured.value.issues)

    review["question_budget"]["resolved_decision_refs"] = ["direction"]
    review["findings"][0]["decision_refs"] = ["direction"]
    normalized = _validate(assessment, operations, commands)
    assert normalized["semantic_review"]["question_budget"][
        "resolved_decision_refs"
    ] == ["direction"]

    review["question_budget"]["resolved_decision_refs"] = []
    review["findings"][0]["decision_refs"] = []
    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("没有逐项引用真实已确认决定" in issue for issue in captured.value.issues)


def test_first_project_cannot_omit_semantic_review_by_marking_scope_unaffected() -> None:
    assessment, operations, commands = _assessment()
    assessment["authority_change_set"] = None
    assessment["semantic_review"] = None

    with pytest.raises(ChangePlanningError) as captured:
        validate_change_planning(
            assessment,
            work_item_id="WI-CHANGE-PLANNING",
            investigation_ref=OBSERVED_COMMIT,
            formal_implementation=True,
            change_kind="create_project",
            impact_scope={
                "affected": [],
                "unknown": [],
                "unaffected": [
                    {"dimension": "product_scope"},
                    {"dimension": "domain"},
                    {"dimension": "architecture"},
                ],
            },
            operations=operations,
            verification_commands=commands,
            known_authorities=None,
            known_evidence_refs={"SRC-001"},
            known_decision_refs={"direction"},
            valid_implements_refs={
                "direction.acceptance:DIRACC-3333333333333333"
            },
        )

    assert any("必须提交 semantic_review" in issue for issue in captured.value.issues)


def test_each_owner_decision_finding_binds_its_own_exact_decision() -> None:
    assessment, operations, commands = _assessment()
    review = assessment["semantic_review"]
    review["findings"] = [
        {
            "finding_id": "FINDING-001",
            "perspective": "product_to_domain_coverage",
            "severity": "high",
            "status": "resolved",
            "locations": ["authority_change_set.changes[0]"],
            "statement": "产品边界需要负责人定夺。",
            "impact": "决定错误会污染领域边界。",
            "recommendation": "引用精确负责人决定。",
            "owner_decision_required": True,
            "decision_refs": ["direction"],
            "resolution": "方向已经明确该产品边界。",
        },
        {
            "finding_id": "FINDING-002",
            "perspective": "domain_to_architecture_disposition",
            "severity": "high",
            "status": "accepted_risk",
            "locations": ["authority_change_set.changes[2]"],
            "statement": "架构取舍需要负责人接受风险。",
            "impact": "错误取舍会造成架构漂移。",
            "recommendation": "引用另一项精确负责人决定。",
            "owner_decision_required": True,
            "decision_refs": [],
            "resolution": "声称已经接受，但没有绑定决定。",
        },
    ]
    review["checks"][0].update(
        {"status": "finding", "finding_ids": ["FINDING-001"]}
    )
    review["checks"][2].update(
        {"status": "finding", "finding_ids": ["FINDING-002"]}
    )
    review["question_budget"]["resolved_decision_refs"] = ["direction"]

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any(
        "FINDING-002" in issue and "没有逐项引用" in issue
        for issue in captured.value.issues
    )


def test_slices_reject_duplicate_coverage_and_parallel_write_conflict() -> None:
    assessment, operations, commands = _assessment()
    second = assessment["implementation_slices"][1]
    second["operation_refs"] = ["operations[0]", "operations[1]"]
    second["depends_on"] = []
    second["parallel_safe_with"] = ["SLICE-001"]
    assessment["implementation_slices"][0]["parallel_safe_with"] = [
        "SLICE-002"
    ]
    operations[0]["path"] = "docs/domain"
    operations[1]["path"] = "docs/domain/model.yaml"

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("同时归属" in issue for issue in captured.value.issues)
    assert any("确定性写入冲突" in issue for issue in captured.value.issues)


def test_formal_slice_can_use_observable_criteria_when_no_command_applies() -> None:
    assessment = {
        "implementation_slices": [
            {
                "schema_version": "strixnova.implementation-slice.v1",
                "slice_id": "SLICE-001",
                "purpose": "修正一段不影响行为的说明文字。",
                "implements": [
                    "direction.acceptance:DIRACC-3333333333333333"
                ],
                "operation_refs": ["operations[0]"],
                "depends_on": [],
                "parallel_safe_with": [],
                "completion_criteria": ["说明文字与已确认术语一致。"],
                "verification_command_refs": [],
                "rollback_or_recovery": "失败时恢复原说明文字。",
            }
        ],
        "owner_view": _owner_view(),
    }
    operations = [{"action": "modify", "path": "docs/guide.md"}]

    normalized = validate_change_planning(
        assessment,
        work_item_id="WI-CHANGE-PLANNING",
        investigation_ref=OBSERVED_COMMIT,
        formal_implementation=True,
        change_kind="modify_existing",
        impact_scope={"affected": [], "unknown": []},
        operations=operations,
        verification_commands=[],
        known_authorities=_known_authorities(),
        known_evidence_refs={"SRC-001"},
        known_decision_refs={"direction"},
        valid_implements_refs={
            "direction.acceptance:DIRACC-3333333333333333"
        },
    )

    assert normalized["implementation_slices"][0][
        "verification_command_refs"
    ] == []


def test_formal_plan_can_mix_explicit_zero_command_and_verified_slices() -> None:
    assessment, operations, commands = _assessment()
    first, second = assessment["implementation_slices"]
    first["verification_command_refs"] = []
    second["verification_command_refs"] = [
        "verification_commands[0]",
        "verification_commands[1]",
    ]

    normalized = _validate(assessment, operations, commands)

    assert normalized["implementation_slices"][0][
        "verification_command_refs"
    ] == []
    assert normalized["implementation_slices"][1][
        "verification_command_refs"
    ] == ["verification_commands[0]", "verification_commands[1]"]


def test_agent_may_split_authority_authoring_across_dependent_governance_slices() -> None:
    assessment, operations, commands = _assessment()
    assessment["implementation_slices"] = [
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-001",
            "purpose": "先形成产品候选。",
            "implements": ["authority_change_set.changes[0]"],
            "operation_refs": ["operations[0]"],
            "depends_on": [],
            "parallel_safe_with": [],
            "completion_criteria": ["产品候选已经形成。"],
            "verification_command_refs": [],
            "rollback_or_recovery": "失败时修正产品候选。",
        },
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-002",
            "purpose": "再形成领域与目标架构候选。",
            "implements": [
                "authority_change_set.changes[1]",
                "authority_change_set.changes[2]",
            ],
            "operation_refs": ["operations[1]", "operations[2]"],
            "depends_on": ["SLICE-001"],
            "parallel_safe_with": [],
            "completion_criteria": ["领域与架构候选相互一致。"],
            "verification_command_refs": ["verification_commands[0]"],
            "rollback_or_recovery": "失败时修正领域与架构候选。",
        },
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-003",
            "purpose": "形成编码前实现对齐草稿。",
            "implements": ["authority_change_set.changes[3]"],
            "operation_refs": ["operations[3]"],
            "depends_on": ["SLICE-002"],
            "parallel_safe_with": [],
            "completion_criteria": ["实现对齐如实记录编码前缺口。"],
            "verification_command_refs": [],
            "rollback_or_recovery": "失败时修正实现对齐草稿。",
        },
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-004",
            "purpose": "实施业务代码并最终刷新实现对齐。",
            "implements": [
                "direction.acceptance:DIRACC-3333333333333333"
            ],
            "operation_refs": ["operations[4]"],
            "continued_operation_refs": ["operations[3]"],
            "depends_on": ["SLICE-003"],
            "parallel_safe_with": [],
            "completion_criteria": ["业务实现与最终实现对齐一致。"],
            "verification_command_refs": ["verification_commands[1]"],
            "rollback_or_recovery": "失败时保留候选并修正业务实现。",
        },
    ]

    normalized = _validate(assessment, operations, commands)

    assert [
        item["slice_id"] for item in normalized["implementation_slices"]
    ] == ["SLICE-001", "SLICE-002", "SLICE-003", "SLICE-004"]


def test_only_one_final_slice_can_refresh_the_same_alignment_draft() -> None:
    assessment, operations, commands = _assessment()

    normalized = _validate(assessment, operations, commands)

    assert normalized["implementation_slices"][1][
        "continued_operation_refs"
    ] == ["operations[3]"]


def test_alignment_refresh_slice_cannot_precede_later_business_work() -> None:
    assessment, operations, commands = _assessment()
    operations.append({"action": "modify", "path": "docs/later.md"})
    commands.append({"command_id": "VC-003"})
    first, refresh = assessment["implementation_slices"]
    first["operation_refs"] = [
        "operations[0]",
        "operations[1]",
        "operations[2]",
        "operations[3]",
    ]
    refresh["operation_refs"] = ["operations[4]"]
    refresh["continued_operation_refs"] = ["operations[3]"]
    refresh["implements"] = [
        "direction.acceptance:DIRACC-3333333333333333"
    ]
    assessment["implementation_slices"].append(
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-003",
            "purpose": "在实现对齐刷新后继续修改普通交付文件。",
            "implements": [
                "direction.acceptance:DIRACC-3333333333333333"
            ],
            "operation_refs": ["operations[5]"],
            "depends_on": ["SLICE-002"],
            "parallel_safe_with": [],
            "completion_criteria": ["后续说明已修改。"],
            "verification_command_refs": ["verification_commands[2]"],
            "rollback_or_recovery": "失败时恢复后续说明。",
        }
    )

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any("必须是方案中的最后一个实施切片" in issue for issue in captured.value.issues)


def test_slice_cannot_continue_an_ordinary_ancestor_operation() -> None:
    assessment, operations, commands = _assessment()
    assessment["implementation_slices"][1]["continued_operation_refs"] = [
        "operations[0]"
    ]

    with pytest.raises(ChangePlanningError) as captured:
        _validate(assessment, operations, commands)

    assert any(
        "只能用于同一实现对齐草稿" in issue
        for issue in captured.value.issues
    )


def test_zero_command_slice_requires_an_explicit_completion_record() -> None:
    plan = {
        "implementation_slices": [
            {
                "slice_id": "SLICE-001",
                "depends_on": [],
                "operation_refs": ["operations[0]"],
                "verification_command_ids": [],
            },
            {
                "slice_id": "SLICE-002",
                "depends_on": ["SLICE-001"],
                "operation_refs": ["operations[1]"],
                "verification_command_ids": ["VC-001"],
            },
        ],
        "operations": [
            {"path": "docs/first.md"},
            {"path": "src/later.py"},
        ],
    }

    before = implementation_slice_progress(plan, [])
    assert before["current_slice_id"] == "SLICE-001"
    assert before["completed_slice_ids"] == []
    assert permitted_slice_operation_paths(plan, [])["future_paths"] == [
        "src/later.py"
    ]

    completions = [
        {
            "schema_version": "strixnova.implementation-slice-completion.v1",
            "slice_id": "SLICE-001",
            "completion_summary": "说明性文档操作已经完成。",
            "semantic_content_machine_proven": False,
        }
    ]
    after = implementation_slice_progress(plan, [], completions)
    assert after["completed_slice_ids"] == ["SLICE-001"]
    assert after["current_slice_id"] == "SLICE-002"


def test_failed_current_slice_makes_downstream_non_execution_explicit() -> None:
    plan = {
        "implementation_slices": [
            {
                "slice_id": "SLICE-001",
                "depends_on": [],
                "verification_command_ids": ["VC-001"],
            },
            {
                "slice_id": "SLICE-002",
                "depends_on": ["SLICE-001"],
                "verification_command_ids": ["VC-002"],
            },
        ]
    }
    receipts = [
        {
            "command_id": "VC-001",
            "result": "failed",
            "code_change_assessment": {
                "changed_after": False,
                "needs_retest": False,
            },
        }
    ]
    coverage = {
        "schema_version": "strixnova.verification-coverage.v1",
        "verification_status": "pending",
        "required_command_ids": ["VC-001", "VC-002"],
        "latest_receipt_ids": {"VC-001": "VR-001"},
        "results": {"VC-001": "failed"},
        "missing_command_ids": ["VC-002"],
        "assessment_missing_command_ids": [],
        "retest_required_command_ids": [],
    }

    reportability = implementation_slice_reportability(plan, receipts)
    projected = implementation_reporting_coverage(plan, receipts, [], coverage)

    assert reportability == {
        "reportable": True,
        "reason": "terminal_slice_issue",
        "terminal_slice_id": "SLICE-001",
        "not_executed_slice_ids": ["SLICE-002"],
        "not_executed_command_ids": ["VC-002"],
    }
    assert projected["verification_status"] == "completed_with_issues"
    assert projected["missing_command_ids"] == []
    assert projected["not_executed_slice_ids"] == ["SLICE-002"]
    assert projected["not_executed_command_ids"] == ["VC-002"]
