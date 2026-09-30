from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest
import yaml

from strixnova.project_product_definition import (
    PROJECT_DIRECTION_CONTEXT_SCHEMA,
    PRODUCT_DEFINITION_SCHEMA,
    ProjectProductDefinition,
    ProjectProductDefinitionError,
    project_direction_context,
    unadopted_project_direction_context,
    validate_direction_context_binding,
)


def _definition() -> dict:
    return {
        "schema_version": PRODUCT_DEFINITION_SCHEMA,
        "product_id": "PRODUCT-7A14F6C93D20B851",
        "revision": {
            "revision_id": "REVISION-C63B58E41A7D209F",
            "status": "ready_for_confirmation",
            "supersedes_revision_id": None,
            "confirmed_by_owner_id": None,
            "confirmed_on": None,
        },
        "title": "示例产品定义",
        "purpose": "帮助项目负责人把目标持续推进为可验证交付。",
        "product_owner": {
            "owner_id": "OWNER-B2951C7E4A803DF6",
            "display_name": "当前项目负责人",
        },
        "primary_users": [
            {
                "user_id": "USER-1D80A7F2C64BE359",
                "title": "项目负责人",
                "description": "能够表达目标和取舍，但不必掌握全部软件工程细节。",
            }
        ],
        "problems": [
            {
                "problem_id": "PROBLEM-839A50D2F14C67BE",
                "user_ids": ["USER-1D80A7F2C64BE359"],
                "statement": "初始愿望通常不足以直接指导完整工程建设。",
            }
        ],
        "desired_outcomes": [
            {
                "outcome_id": "OUTCOME-A207F4E85C39D16B",
                "statement": "目标、建设和证据保持可追溯的一致关系。",
            }
        ],
        "capabilities": [
            {
                "capability_id": "CAPABILITY-6E29C4B801F7A35D",
                "title": "项目权威治理",
                "description": "管理经确认的目标及其演进关系。",
                "outcome_ids": ["OUTCOME-A207F4E85C39D16B"],
            }
        ],
        "non_goals": [
            {
                "non_goal_id": "NONGOAL-4901CB7E3D82A65F",
                "statement": "不替项目负责人作产品决定。",
            }
        ],
        "constraints": [
            {
                "constraint_id": "CONSTRAINT-D7148E2A6B3059CF",
                "statement": "程序不得生成或裁决工程语义。",
            }
        ],
        "success_criteria": [
            {
                "criterion_id": "CRITERION-5C91E7A20D48B63F",
                "statement": "所有长期目标均有精确版本和确认状态。",
                "outcome_ids": ["OUTCOME-A207F4E85C39D16B"],
            }
        ],
        "delivery_stages": [
            {
                "stage_id": "STAGE-20B6D91F4E8A73C5",
                "title": "当前建设阶段",
                "commitment": "current_target",
                "description": "完成本地单项目的软件工程全链路治理。",
            },
            {
                "stage_id": "STAGE-FC6712A09E4D38B5",
                "title": "未来候选阶段",
                "commitment": "future_candidate",
                "description": "经新的产品决定后再考虑扩展外部协作能力。",
            },
        ],
        "unresolved_decisions": [],
    }


def _write_definition(project: Path, value: dict) -> str:
    path = "docs/product/definition.yaml"
    target = project / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _confirmed_definition() -> dict:
    value = _definition()
    value["revision"].update(
        {
            "status": "confirmed",
            "confirmed_by_owner_id": value["product_owner"]["owner_id"],
            "confirmed_on": "2026-08-29",
        }
    )
    return value


def test_direction_context_projects_every_capability_and_guardrail_without_ranking() -> None:
    value = _confirmed_definition()

    context = project_direction_context(value, observed_commit="a" * 40)

    assert context["schema_version"] == PROJECT_DIRECTION_CONTEXT_SCHEMA
    assert context["authority_scope"] == "adopted_integration_commit"
    assert context["product"]["purpose"] == value["purpose"]
    assert [item["capability_id"] for item in context["capability_catalog"]] == [
        "CAPABILITY-6E29C4B801F7A35D"
    ]
    assert [item["kind"] for item in context["guardrails"]] == [
        "non_goal",
        "constraint",
    ]
    assert context["semantic_relevance_machine_proven"] is False


def test_direction_context_binding_checks_refs_coverage_and_staleness_only() -> None:
    context = project_direction_context(
        _confirmed_definition(),
        observed_commit="b" * 40,
    )
    binding = {
        "context_ref": context["context_ref"],
        "capability_refs": [
            context["capability_catalog"][0]["capability_ref"]
        ],
        "guardrail_dispositions": [
            {
                "decision_ref": guardrail["decision_ref"],
                "disposition": "not_applicable",
                "reason": "这是智能编码代理提交的理由，程序不评价其含义。",
            }
            for guardrail in context["guardrails"]
        ],
        "assumptions": [],
    }

    validate_direction_context_binding(binding, context)

    missing = {**binding, "guardrail_dispositions": binding["guardrail_dispositions"][:-1]}
    with pytest.raises(ProjectProductDefinitionError) as captured:
        validate_direction_context_binding(missing, context)
    assert "没有逐项覆盖" in str(captured.value)

    stale = {**binding, "context_ref": "product-definition:stale"}
    with pytest.raises(ProjectProductDefinitionError) as captured:
        validate_direction_context_binding(stale, context)
    assert "已经过期" in str(captured.value)

    duplicate = {
        **binding,
        "guardrail_dispositions": [
            *binding["guardrail_dispositions"],
            binding["guardrail_dispositions"][0],
        ],
    }
    with pytest.raises(ProjectProductDefinitionError) as captured:
        validate_direction_context_binding(duplicate, context)
    assert "重复处置" in str(captured.value)


def test_unadopted_project_direction_context_is_explicitly_empty() -> None:
    context = unadopted_project_direction_context()

    assert context == {
        "schema_version": PROJECT_DIRECTION_CONTEXT_SCHEMA,
        "authority_scope": "unadopted_project",
        "observed_commit": None,
        "context_ref": None,
        "product": None,
        "capability_catalog": [],
        "guardrails": [],
        "semantic_relevance_machine_proven": False,
    }


def _git(repo: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def test_ready_definition_loads_as_structure_not_semantic_proof(
    tmp_path: Path,
) -> None:
    path = _write_definition(tmp_path, _definition())

    loaded = ProjectProductDefinition(tmp_path, path).load()

    assert loaded["schema_version"] == PRODUCT_DEFINITION_SCHEMA
    assert loaded["revision"]["status"] == "ready_for_confirmation"
    assert loaded["capabilities"][0]["capability_id"] == (
        "CAPABILITY-6E29C4B801F7A35D"
    )
    assert loaded["_manifest_path"] == path
    assert loaded["_observed_commit"] is None
    assert loaded["_semantic_content_machine_proven"] is False


def test_definition_rejects_implementation_or_architecture_fields(
    tmp_path: Path,
) -> None:
    value = _definition()
    value["capabilities"][0]["implementation_paths"] = ["src/product.py"]
    path = _write_definition(tmp_path, value)

    with pytest.raises(ProjectProductDefinitionError) as raised:
        ProjectProductDefinition(tmp_path, path).load()

    assert raised.value.issues == [
        "product_definition.capabilities[0] 包含未知字段：implementation_paths"
    ]


def test_definition_rejects_duplicate_identities_and_dangling_references(
    tmp_path: Path,
) -> None:
    value = _definition()
    value["desired_outcomes"].append(
        {
            "outcome_id": "OUTCOME-A207F4E85C39D16B",
            "statement": "重复身份不代表第二个目标结果。",
        }
    )
    value["problems"][0]["user_ids"] = ["USER-FFFFFFFFFFFFFFFF"]
    value["capabilities"][0]["outcome_ids"] = [
        "OUTCOME-EEEEEEEEEEEEEEEE"
    ]
    path = _write_definition(tmp_path, value)

    with pytest.raises(ProjectProductDefinitionError) as raised:
        ProjectProductDefinition(tmp_path, path).load()

    assert "product_definition.desired_outcomes 身份重复：OUTCOME-A207F4E85C39D16B" in (
        raised.value.issues
    )
    assert (
        "product_definition.problems[0].user_ids 引用未知用户："
        "USER-FFFFFFFFFFFFFFFF"
    ) in raised.value.issues
    assert (
        "product_definition.capabilities[0].outcome_ids 引用未知目标结果："
        "OUTCOME-EEEEEEEEEEEEEEEE"
    ) in raised.value.issues


def test_ready_definition_requires_structural_outcome_coverage(
    tmp_path: Path,
) -> None:
    value = _definition()
    value["desired_outcomes"].append(
        {
            "outcome_id": "OUTCOME-03AC7E91B5D824F6",
            "statement": "新增目标结果。",
        }
    )
    path = _write_definition(tmp_path, value)

    with pytest.raises(ProjectProductDefinitionError) as raised:
        ProjectProductDefinition(tmp_path, path).load()

    assert (
        "可确认的产品定义中，以下目标结果没有产品能力承接："
        "OUTCOME-03AC7E91B5D824F6"
    ) in raised.value.issues
    assert (
        "可确认的产品定义中，以下目标结果没有成功判断："
        "OUTCOME-03AC7E91B5D824F6"
    ) in raised.value.issues


def test_confirmation_requires_no_open_decisions_and_exact_owner(
    tmp_path: Path,
) -> None:
    value = _definition()
    value["unresolved_decisions"] = [
        {
            "decision_id": "DECISION-29D7A0C1F548B63E",
            "statement": "是否改变产品范围？",
            "impact": "会改变后续领域模型。",
        }
    ]
    path = _write_definition(tmp_path, value)

    with pytest.raises(ProjectProductDefinitionError) as open_decision:
        ProjectProductDefinition(tmp_path, path).load()
    assert "可确认或已确认的产品定义不得保留未决决定" in (
        open_decision.value.issues
    )

    value["unresolved_decisions"] = []
    value["revision"].update(
        {
            "status": "confirmed",
            "confirmed_by_owner_id": "OWNER-0000000000000000",
            "confirmed_on": "2026-08-25",
        }
    )
    _write_definition(tmp_path, value)
    with pytest.raises(ProjectProductDefinitionError) as wrong_owner:
        ProjectProductDefinition(tmp_path, path).load()
    assert "产品定义必须由当前产品负责人确认" in wrong_owner.value.issues

    value["revision"]["confirmed_by_owner_id"] = value["product_owner"][
        "owner_id"
    ]
    _write_definition(tmp_path, value)
    assert ProjectProductDefinition(tmp_path, path).load()["revision"][
        "status"
    ] == "confirmed"


def test_definition_can_be_read_at_an_exact_git_revision(tmp_path: Path) -> None:
    path = _write_definition(tmp_path, _definition())
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", path)
    _git(tmp_path, "commit", "-m", "initial product definition")
    initial = _git(tmp_path, "rev-parse", "HEAD")

    changed = _definition()
    changed["title"] = "工作树中的新标题"
    _write_definition(tmp_path, changed)

    current = ProjectProductDefinition(tmp_path, path).load()
    observed = ProjectProductDefinition(
        tmp_path,
        path,
        observed_ref=initial,
    ).load()

    assert current["title"] == "工作树中的新标题"
    assert observed["title"] == "示例产品定义"
    assert observed["_observed_commit"] == initial
