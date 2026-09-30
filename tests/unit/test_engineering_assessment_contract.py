from __future__ import annotations

import os
from importlib.resources import files
import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource

import strixnova.engineering_governance as engineering_governance_module
from strixnova.engineering_governance import (
    ASSESSMENT_SCHEMA,
    EngineeringGovernanceError,
    IMPACT_DIMENSIONS,
    compile_engineering_plan as _governance_compile_engineering_plan,
    validate_assessment as _governance_validate_assessment,
)
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_engineering_policy import load_base_governance_profile
from tests.support.governance_assessment import (
    DEFAULT_DIRECTION_VERSION,
    assessment_fixture,
    clone_assessment,
    direction_fixture,
    exploration_assessment,
    new_project_adr_assessment,
    refresh_single_slice,
    semantic_review_fixture,
)
from tests.support.project_baseline import (
    TEST_DOMAIN_MODEL_ID,
    TEST_TERM_FACT_ID,
)


WORK_ITEM_ID = "WI-TEST-001"


def _validate_assessment(
    assessment: dict,
    *,
    project_dir: Path,
    **kwargs,
) -> dict:
    kwargs.setdefault("profile", load_base_governance_profile())
    return _governance_validate_assessment(
        assessment,
        project_dir=project_dir,
        candidate_context=ProjectAuthorityConsistency(
            project_dir
        ).engineering_candidate_context(assessment),
        **kwargs,
    )


def _compile_engineering_plan(
    assessment: dict,
    *,
    project_dir: Path,
    **kwargs,
) -> dict:
    kwargs.setdefault("profile", load_base_governance_profile())
    return _governance_compile_engineering_plan(
        assessment,
        project_dir=project_dir,
        candidate_context=ProjectAuthorityConsistency(
            project_dir
        ).engineering_candidate_context(assessment),
        **kwargs,
    )


def _fact_ref(fact_id: str = TEST_TERM_FACT_ID) -> dict[str, str]:
    return {
        "schema_version": "strixnova.domain-fact-reference.v1",
        "authority_kind": "project_domain_model",
        "model_id": TEST_DOMAIN_MODEL_ID,
        "fact_id": fact_id,
        "observed_commit": "a" * 40,
    }


def test_domain_fact_ledger_must_match_authority_change_set_identity_and_action() -> None:
    fact_id = "FACT-1111111111111111"
    fact_changes = [
        {
            "disposition": "update",
            "target_ref": {"fact_id": fact_id},
        }
    ]
    mismatched_change_set = {
        "changes": [
            {
                "authority_kind": "domain_model",
                "operation": "modify",
                "target_ref": "FACT-2222222222222222",
            }
        ]
    }
    issues: list[str] = []

    engineering_governance_module._validate_domain_fact_authority_change_alignment(
        fact_changes,
        mismatched_change_set,
        issues,
    )

    assert any(fact_id in issue for issue in issues)
    assert any("FACT-2222222222222222" in issue for issue in issues)


def validate_assessment(assessment: dict, *, project_dir: Path) -> dict:
    return _validate_assessment(
        assessment,
        project_dir=project_dir,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
    )


def compile_engineering_plan(
    assessment: dict,
    *,
    project_dir: Path,
    work_item_id: str,
) -> dict:
    return _compile_engineering_plan(
        assessment,
        project_dir=project_dir,
        work_item_id=work_item_id,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
    )


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


def test_one_assessment_compiles_plan_without_review_artifact(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)

    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )

    assert assessment["schema_version"] == ASSESSMENT_SCHEMA
    assert "information_items" not in assessment
    assert "governance_applicability" not in assessment
    assert plan["assessment_ref"] == {
        "work_item_id": WORK_ITEM_ID,
        "assessment_id": "EA-TEST-001",
        "assessment_revision": 1,
    }
    assert "review_ref" not in plan
    assert plan["semantic_content_machine_proven"] is False
    assert all(rule["source_ids"] for rule in plan["applicable_rules"])
    assert {rule["rule_id"] for rule in plan["applicable_rules"]} >= {
        "STRIXNOVA-GOV-REQ-001",
        "STRIXNOVA-GOV-LIFE-001",
        "STRIXNOVA-GOV-TEST-001",
    }
    assert (
        "direction.acceptance:DIRACC-3333333333333333"
        in plan["trace_refs"]
    )
    assert (
        "direction.requirement:DIRREQ-1111111111111111"
        in plan["trace_refs"]
    )
    assert plan["direction_ref"] == {
        "work_item_id": WORK_ITEM_ID,
        "direction_version": DEFAULT_DIRECTION_VERSION,
    }
    assert plan["method_applications"] == []
    assert plan["operations"] == [
        {**operation, "repository_id": plan["repository_scope"]["repositories"][0]["repository_id"]}
        for operation in assessment["operations"]
    ]
    assert plan["delivery_plan"] == {**assessment["delivery_plan"], "repository_order": [None]}
    assert plan["verification_commands"]


def test_engineering_assessment_rejects_retired_positional_direction_refs(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["verification_commands"][0]["covers"][0] = (
        "direction.acceptance[0]"
    )

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert any(
        "direction.acceptance[0]" in issue and "未知验证目标" in issue
        for issue in captured.value.issues
    )


def test_engineering_operation_accepts_stable_requirement_reference(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["operations"][0]["implements"] = [
        "direction.requirement:DIRREQ-1111111111111111"
    ]

    normalized = validate_assessment(assessment, project_dir=tmp_path)

    assert normalized["operations"][0]["implements"] == [
        "direction.requirement:DIRREQ-1111111111111111"
    ]


def test_external_observation_provider_plan_is_normalized_into_confirmable_plan(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["external_observation_provider_plans"] = [
        {
            "provider_plan_id": "OBSPROVPLAN-1111111111111111",
            "scope_id": "OBSCOPE-2222222222222222",
            "language_id": "csharp",
            "provider_id": "roslyn-project-graph",
            "provider_version": "1.0.0",
            "command": ["dotnet", "tool", "run", "strixnova-roslyn-observer"],
            "materials": [
                {
                    "role": "executable",
                    "path": "C:/tools/dotnet.exe",
                    "sha256": "0" * 64,
                    "command_argument_index": 0,
                }
            ],
            "source_globs": ["**/*.cs", "**/*.csproj", "**/*.sln"],
            "process_policy": {
                "policy_id": "PROCESSPOLICY-3333333333333333",
                "purpose": "读取已确认范围内的 C# 项目图。",
                "forbidden_program_names": ["codex"],
            },
            "limits": {
                "timeout_seconds": 90,
                "cleanup_timeout_seconds": 10,
                "max_input_bytes": 1048576,
                "max_output_bytes": 16777216,
            },
        }
    ]

    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )

    assert plan["external_observation_provider_plans"] == [
        {**assessment["external_observation_provider_plans"][0], "repository_id": None}
    ]
    assert plan["semantic_content_machine_proven"] is False


def test_external_observation_provider_plan_rejects_shell_and_path_escape(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["external_observation_provider_plans"] = [
        {
            "provider_plan_id": "OBSPROVPLAN-1111111111111111",
            "scope_id": "OBSCOPE-2222222222222222",
            "language_id": "cpp",
            "provider_id": "clang-project-graph",
            "provider_version": "1.0.0",
            "command": ["pwsh", "-Command", "clang-scan-deps"],
            "materials": [
                {
                    "role": "executable",
                    "path": "C:/tools/pwsh.exe",
                    "sha256": "0" * 64,
                    "command_argument_index": 0,
                }
            ],
            "source_globs": ["../outside/**/*.cpp"],
            "process_policy": {
                "policy_id": "PROCESSPOLICY-3333333333333333",
                "purpose": "读取 C++ 构建图。",
                "forbidden_program_names": [],
            },
            "limits": {
                "timeout_seconds": 90,
                "cleanup_timeout_seconds": 10,
                "max_input_bytes": 1048576,
                "max_output_bytes": 16777216,
            },
        }
    ]

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert any("source_globs" in issue for issue in captured.value.issues)
    assert any("包装器" in issue for issue in captured.value.issues)


def test_external_observation_provider_plan_rejects_inline_runtime_code(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["external_observation_provider_plans"] = [
        {
            "provider_plan_id": "OBSPROVPLAN-1111111111111111",
            "scope_id": "OBSCOPE-2222222222222222",
            "language_id": "kotlin",
            "provider_id": "inline-provider",
            "provider_version": "1.0.0",
            "command": ["python", "-c", "print('not a provider artifact')"],
            "materials": [
                {
                    "role": "executable",
                    "path": "C:/tools/python.exe",
                    "sha256": "0" * 64,
                    "command_argument_index": 0,
                }
            ],
            "source_globs": ["**/*.kt"],
            "process_policy": {
                "policy_id": "PROCESSPOLICY-3333333333333333",
                "purpose": "This deliberately invalid plan executes inline code.",
                "forbidden_program_names": [],
            },
            "limits": {
                "timeout_seconds": 90,
                "cleanup_timeout_seconds": 10,
                "max_input_bytes": 1048576,
                "max_output_bytes": 16777216,
            },
        }
    ]

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert any("内联代码" in issue for issue in captured.value.issues)


def test_external_observation_provider_plan_rejects_unbounded_output(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["external_observation_provider_plans"] = [
        {
            "provider_plan_id": "OBSPROVPLAN-1111111111111111",
            "scope_id": "OBSCOPE-2222222222222222",
            "language_id": "cpp",
            "provider_id": "clang-project-graph",
            "provider_version": "1.0.0",
            "command": ["C:/tools/observer.exe"],
            "materials": [
                {
                    "role": "executable",
                    "path": "C:/tools/observer.exe",
                    "sha256": "0" * 64,
                    "command_argument_index": 0,
                }
            ],
            "source_globs": ["**/*.cpp"],
            "process_policy": {
                "policy_id": "PROCESSPOLICY-3333333333333333",
                "purpose": "读取 C++ 构建图。",
                "forbidden_program_names": [],
            },
            "limits": {
                "timeout_seconds": 90,
                "cleanup_timeout_seconds": 10,
                "max_input_bytes": 1048576,
                "max_output_bytes": 10**100,
            },
        }
    ]

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert any("max_output_bytes" in issue for issue in captured.value.issues)
    assert any("268435456" in issue for issue in captured.value.issues)


def test_project_baseline_index_cannot_masquerade_as_owner_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, set[str]] = {}
    original = engineering_governance_module.validate_change_planning

    def capture_decision_refs(*args, **kwargs):
        observed["refs"] = set(kwargs["known_decision_refs"])
        return original(*args, **kwargs)

    monkeypatch.setattr(
        engineering_governance_module,
        "validate_change_planning",
        capture_decision_refs,
    )
    assessment = assessment_fixture(tmp_path)
    _validate_assessment(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        known_baseline_refs={
            "baseline:project",
            "baseline:authority:product_definition:PRODUCT-1111111111111111:"
            "REVISION-1111111111111111:confirmed:current",
            "baseline:authority:domain_model:MODEL-1111111111111111:"
            "MODELREV-1111111111111111:draft:not_adopted",
        },
    )

    assert "baseline:project" not in observed["refs"]
    assert "direction" in observed["refs"]
    assert (
        "baseline:authority:product_definition:PRODUCT-1111111111111111:"
        "REVISION-1111111111111111:confirmed:current"
        in observed["refs"]
    )
    assert not any(
        reference.endswith(":draft:not_adopted")
        for reference in observed["refs"]
    )


def test_identical_commands_in_different_slices_keep_distinct_run_identities(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["operations"].append(
        {
            "action": "create",
            "path": "docs/result.md",
            "reason": "第二切片记录验证后的结果说明。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
        }
    )
    assessment["verification_commands"].append(
        clone_assessment(assessment["verification_commands"][0])
    )
    assessment["implementation_slices"] = [
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-001",
            "purpose": "先修改行为并运行针对性验证。",
            "implements": ["design_decisions[0]"],
            "operation_refs": ["operations[0]"],
            "depends_on": [],
            "parallel_safe_with": [],
            "completion_criteria": ["行为修改通过第一次验证。"],
            "verification_command_refs": ["verification_commands[0]"],
            "rollback_or_recovery": "失败时修正第一切片并重测。",
        },
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-002",
            "purpose": "再记录结果并对新状态运行同一验证。",
            "implements": ["design_decisions[0]"],
            "operation_refs": ["operations[1]"],
            "depends_on": ["SLICE-001"],
            "parallel_safe_with": [],
            "completion_criteria": ["结果说明形成后取得新的验证回执。"],
            "verification_command_refs": ["verification_commands[1]"],
            "rollback_or_recovery": "失败时保留第一切片并修正第二切片。",
        },
    ]

    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )

    assert [
        command["command_id"] for command in plan["verification_commands"]
    ] == ["VC-001", "VC-002"]
    assert [
        item["verification_command_ids"]
        for item in plan["implementation_slices"]
    ] == [["VC-001"], ["VC-002"]]
    assert plan["verification_commands"][0]["command_id"] == "VC-001"
    assert "verification_command_count" not in plan

    resource_root = files("strixnova.resources")
    plan_schema = json.loads(
        resource_root.joinpath("engineering-plan-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    registry_entries = []
    for resource_path in resource_root.iterdir():
        if not resource_path.name.endswith(".schema.json"):
            continue
        contents = json.loads(resource_path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents)
        registry_entries.append((resource_path.name, resource))
        registry_entries.append((contents["$id"], resource))
    Draft202012Validator(
        plan_schema,
        registry=Registry().with_resources(registry_entries),
    ).validate(plan)


def test_governance_profile_keeps_verified_sources_and_usage_boundaries() -> None:
    profile = load_base_governance_profile()

    assert profile["sources"]
    assert profile["rules"]
    assert all(
        source["official_url"].startswith("https://")
        for source in profile["sources"]
    )
    assert all(source["verification_basis"] for source in profile["sources"])
    assert all(source["allowed_use"] for source in profile["sources"])
    assert all(source["content_boundary"] for source in profile["sources"])
    assert [method["method_id"] for method in profile["engineering_methods"]] == [
        "ddd"
    ]
    ddd_source = next(
        source
        for source in profile["sources"]
        if source["source_id"] == "DDD-REFERENCE-2015"
    )
    assert ddd_source["rights_status"] == "creative_commons_attribution_4_0"


def test_adopted_ddd_requires_explicit_coding_agent_choice_when_impact_is_relevant(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["impact_scope"]["unaffected"].remove("domain")
    assessment["impact_scope"]["affected"].append(
        {
            "dimension": "domain",
            "reason": "领域术语和不变量将发生变化。",
            "evidence_refs": ["SRC-001"],
        }
    )
    profile = load_base_governance_profile()
    profile["project_method_adoptions"] = [
        {
            "method_id": "ddd",
            "status": "adopted",
            "reason": "项目已采用 DDD。",
            "conditions": [],
            "adopted_technique_ids": [
                "ubiquitous_language",
                "bounded_context",
                "context_map",
                "domain_invariant_trace",
            ],
        }
    ]
    baseline_refs = {"engineering-policy:method:ddd"}

    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_baseline_refs=baseline_refs,
        )

    assessment["method_applications"] = [
        {
            "method_id": "ddd",
            "decision": "considered_not_applied",
            "purpose": "本事项只调整技术性输出，不需要读取或改变领域事实。",
            "evidence_refs": ["SRC-001"],
            "baseline_refs": ["engineering-policy:method:ddd"],
            "domain_fact_refs": [],
            "planned_uses": [],
        }
    ]
    assessment["semantic_review"] = semantic_review_fixture("SRC-001")
    not_applied = _validate_assessment(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        profile=profile,
        known_baseline_refs=baseline_refs,
        domain_model_id=TEST_DOMAIN_MODEL_ID,
        known_domain_fact_locations={
            TEST_TERM_FACT_ID: "docs/domain/sources/core.yaml"
        },
    )
    assert not_applied["method_applications"][0]["domain_fact_refs"] == []

    assessment["method_applications"] = [
        {
            "method_id": "ddd",
            "decision": "applied",
            "purpose": "更新受影响的统一语言，并追溯到当前设计决定。",
            "evidence_refs": ["SRC-001"],
            "baseline_refs": ["engineering-policy:method:ddd"],
            "domain_fact_refs": [_fact_ref()],
            "planned_uses": [
                {
                    "use_id": "DDD-USE-001",
                    "stage": "domain_analysis",
                    "technique_ids": ["ubiquitous_language"],
                    "purpose": "校正当前事项涉及的项目术语。",
                    "target_refs": ["impact_scope.affected[1]"],
                    "evidence_refs": ["SRC-001"],
                }
            ],
        }
    ]
    assessment["domain_fact_changes"] = [
        {
            "disposition": "retain",
            "target_ref": _fact_ref(),
            "source_path": "docs/domain/sources/core.yaml",
            "reason": "现有 WorkItem 术语含义仍然适用。",
            "evidence_refs": ["SRC-001"],
            "lineage": [],
        }
    ]
    plan = _compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        profile=profile,
        known_baseline_refs=baseline_refs,
        domain_model_id=TEST_DOMAIN_MODEL_ID,
        known_domain_fact_locations={
            TEST_TERM_FACT_ID: "docs/domain/sources/core.yaml"
        },
    )

    assert plan["method_applications"][0]["decision"] == "applied"
    assert plan["method_applications"][0]["decision_source"] == (
        "coding_agent_assessment"
    )
    assert "impact_scope.domain:affected" in plan["method_applications"][0][
        "triggered_by"
    ]
    assert plan["method_applications"][0]["actual_result_requirements"] == {
        "use_ids": ["DDD-USE-001"],
    }
    assert plan["actual_result_requirements"] == {
        "domain_fact_changes": [
            {
                "target_ref": _fact_ref(),
                "planned_disposition": "retain",
            }
        ],
    }
    assert plan["assurance_band"] == "A1"


def test_ddd_cannot_be_applied_before_project_adoption(tmp_path: Path) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["impact_scope"]["unaffected"].remove("domain")
    assessment["impact_scope"]["affected"].append(
        {
            "dimension": "domain",
            "reason": "当前事项需要使用项目领域模型。",
            "evidence_refs": ["SRC-001"],
        }
    )
    assessment["method_applications"] = [
        {
            "method_id": "ddd",
            "decision": "applied",
            "purpose": "尝试在没有项目采用事实时直接使用 DDD。",
            "evidence_refs": ["SRC-001"],
            "baseline_refs": ["engineering-policy:method:ddd"],
            "domain_fact_refs": [_fact_ref()],
            "planned_uses": [
                {
                    "use_id": "DDD-USE-UNADOPTED",
                    "stage": "domain_analysis",
                    "technique_ids": ["ubiquitous_language"],
                    "purpose": "使用尚未由项目采用的统一语言。",
                    "target_refs": ["impact_scope.affected[1]"],
                    "evidence_refs": ["SRC-001"],
                }
            ],
        }
    ]
    profile = load_base_governance_profile()
    profile["project_method_adoptions"] = [
        {
            "method_id": "ddd",
            "status": "not_assessed",
            "reason": "项目尚未完成 DDD 采用判断。",
            "conditions": [],
            "adopted_technique_ids": [],
        }
    ]

    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_baseline_refs={"engineering-policy:method:ddd"},
        )

    application = assessment["method_applications"][0]
    application["adoption_change"] = {
        "from_status": "not_assessed",
        "to_status": "adopted",
        "reason": "本事项决定正式采用 DDD。",
        "conditions": [],
    }
    application["planned_uses"][0]["technique_ids"] = [
        "ubiquitous_language",
        "bounded_context",
        "context_map",
        "domain_invariant_trace",
    ]
    assessment["domain_fact_changes"] = []
    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_baseline_refs={
                "engineering-policy:method:ddd",
            },
            domain_model_id=TEST_DOMAIN_MODEL_ID,
            known_domain_fact_locations={
                TEST_TERM_FACT_ID: "docs/domain/sources/core.yaml"
            },
        )

    new_model_id = "MODEL-4444444444444444"
    new_fact_id = "FACT-4444444444444444"
    application["domain_fact_refs"] = []
    assessment["domain_fact_changes"] = [
        {
            "disposition": "add",
            "target_ref": {
                "schema_version": "strixnova.domain-fact-reference.v1",
                "authority_kind": "project_domain_model",
                "model_id": new_model_id,
                "fact_id": new_fact_id,
                "observed_commit": "a" * 40,
            },
            "source_path": "docs/domain/sources/core.yaml",
            "reason": "建立首个正式领域 Fact。",
            "evidence_refs": ["SRC-001"],
            "lineage": [],
        }
    ]
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text("existing baseline\n", encoding="utf-8")
    policy_path = tmp_path / "docs" / "engineering" / "policy.yaml"
    policy_path.write_text("existing policy\n", encoding="utf-8")
    assessment["operations"].extend(
        [
            {
                "action": "modify",
                "path": "docs/engineering/baseline.yaml",
                "reason": "记录 DDD 采用状态和独立权威路径。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
            },
            {
                "action": "modify",
                "path": "docs/engineering/policy.yaml",
                "reason": "记录项目 DDD 方法采用状态。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
                "long_lived_artifact": {
                    "artifact_id": "POLICY-4444444444444444",
                    "artifact_type": "quality_policy",
                },
            },
            {
                "action": "create",
                "path": "docs/domain/model.yaml",
                "reason": "建立独立 ProjectDomainModel 清单。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
                "long_lived_artifact": {
                    "artifact_id": new_model_id,
                    "artifact_type": "domain_model",
                },
            },
            {
                "action": "create",
                "path": "docs/domain/sources/core.yaml",
                "reason": "写入首个领域 Fact 规范正文。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
            },
            {
                "action": "create",
                "path": "docs/engineering/domain-alignment.yaml",
                "reason": "建立独立领域实现对齐权威。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
                "long_lived_artifact": {
                    "artifact_id": "ALIGNMODEL-4444444444444444",
                    "artifact_type": "domain_alignment",
                },
            },
        ]
    )
    assessment["adr_plans"] = [
        {
            "disposition": "not_required",
            "reason": "采用既有四权威边界，不引入新的架构决定。",
            "evidence_refs": ["SRC-001"],
        }
    ]
    profile["project_engineering_baseline_path"] = (
        "docs/engineering/baseline.yaml"
    )
    profile["project_authority_paths"] = {
        "project_domain_model_path": None,
        "project_architecture_description_path": "docs/engineering/architecture.yaml",
        "project_implementation_alignment_path": None,
    }
    assessment["semantic_review"] = semantic_review_fixture("SRC-001")
    assessment["implementation_slices"] = [
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-001",
            "purpose": "先形成并确认完整长期权威候选与编码前实现对齐。",
            "implements": ["design_decisions[0]"],
            "operation_refs": [
                "operations[1]",
                "operations[2]",
                "operations[3]",
                "operations[4]",
                "operations[5]",
            ],
            "depends_on": [],
            "parallel_safe_with": [],
            "completion_criteria": ["完整候选包已形成并完成独立确认。"],
            "verification_command_refs": [],
            "rollback_or_recovery": "候选不完整时保留草稿并修正当前治理切片。",
        },
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-002",
            "purpose": "在权威确认后实施源码，并最终刷新同一实现对齐。",
            "implements": ["design_decisions[0]"],
            "operation_refs": ["operations[0]"],
            "continued_operation_refs": ["operations[5]"],
            "depends_on": ["SLICE-001"],
            "parallel_safe_with": [],
            "completion_criteria": ["源码改动与最终实现对齐均由真实验证闭合。"],
            "verification_command_refs": ["verification_commands[0]"],
            "rollback_or_recovery": "验证失败时保留未提交改动并修正当前业务切片。",
        },
    ]

    adopted = _validate_assessment(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        profile=profile,
        known_baseline_refs={"engineering-policy:method:ddd"},
    )

    assert adopted["method_applications"][0]["adoption_change"][
        "to_status"
    ] == "adopted"

    mixed_models = clone_assessment(assessment)
    mixed_models["method_applications"][0]["domain_fact_refs"] = [
        _fact_ref()
    ]
    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            mixed_models,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_baseline_refs={"engineering-policy:method:ddd"},
        )


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda value: value["change_context"].update(change_kind=True), "change_kind"),
        (
            lambda value: value["source_references"][0].update(
                epistemic_status=False
            ),
            "epistemic_status",
        ),
        (lambda value: value["risk_assessments"][0].update(likelihood=1), "likelihood"),
        (
            lambda value: value["alternatives_and_tradeoffs"].append(
                {
                    "option": "错误类型",
                    "disposition": [],
                    "reason": "验证严格边界。",
                    "tradeoffs": "无。",
                    "evidence_refs": ["SRC-001"],
                }
            ),
            "disposition",
        ),
        (lambda value: value["operations"][0].update(action={}), "action"),
        (lambda value: value["operations"][0].update(implements=[True]), "implements"),
        (
            lambda value: value["verification_commands"][0].update(run_kind=True),
            "run_kind",
        ),
        (
            lambda value: value["verification_commands"][0].update(covers=[1]),
            "covers",
        ),
        (lambda value: value["requested_assurance"].update(band=False), "band"),
    ],
)
def test_semantic_contract_values_never_coerce_non_text_json_types(
    tmp_path: Path,
    mutate,
    expected: str,
) -> None:
    assessment = assessment_fixture(tmp_path)
    mutate(assessment)

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert any(expected in issue and "必须是" in issue for issue in captured.value.issues)


def test_assessment_rejects_missing_or_unknown_fields(tmp_path: Path) -> None:
    missing = assessment_fixture(tmp_path)
    missing.pop("impact_scope")
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(missing, project_dir=tmp_path)

    unknown = assessment_fixture(tmp_path)
    unknown["invented_semantics"] = "程序不应接受平行语义"
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(unknown, project_dir=tmp_path)


def test_all_twelve_impact_dimensions_are_required(tmp_path: Path) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["impact_scope"]["unaffected"].remove("security_privacy")

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert "impact_scope 缺少维度：security_privacy" in captured.value.issues
    normalized = validate_assessment(
        assessment_fixture(tmp_path), project_dir=tmp_path
    )
    covered = {
        item["dimension"]
        for status in ("affected", "unknown")
        for item in normalized["impact_scope"][status]
    } | set(normalized["impact_scope"]["unaffected"])
    assert covered == set(IMPACT_DIMENSIONS)


def test_architecture_impact_activates_rule_and_requires_real_decisions(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["impact_scope"]["unaffected"].remove("architecture")
    assessment["impact_scope"]["affected"].append(
        {
            "dimension": "architecture",
            "reason": "当前设计边界会发生变化。",
            "evidence_refs": ["SRC-001"],
        }
    )

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)
    assert "STRIXNOVA-GOV-ARCH-001 缺少 option 工程事实" in captured.value.issues
    assert "STRIXNOVA-GOV-ARCH-001 缺少 adr_candidate 工程事实" in captured.value.issues

    assessment["alternatives_and_tradeoffs"] = [
        {
            "option": "SQLite Authority",
            "disposition": "selected",
            "reason": "需要原子状态事务。",
            "tradeoffs": "增加本地数据库依赖，但不复制 Git 正文。",
            "evidence_refs": ["SRC-001"],
        }
    ]
    assessment["operations"].append(
        {
            "action": "create",
            "path": "docs/adr/ADR-001.md",
            "reason": "记录长期架构决定。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": "ADR-001",
                "artifact_type": "adr",
            },
        }
    )
    assessment["adr_plans"] = [
        {
            "disposition": "create",
            "reason": "架构边界发生长期变化。",
            "evidence_refs": ["SRC-001"],
            "artifact_id": "ADR-001",
            "path": "docs/adr/ADR-001.md",
        }
    ]
    assessment["semantic_review"] = semantic_review_fixture("SRC-001")
    refresh_single_slice(assessment)

    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )
    assert plan["assurance_band"] == "A3"
    assert any(
        rule["rule_id"] == "STRIXNOVA-GOV-ARCH-001"
        and "impact_scope.architecture:affected" in rule["triggered_by"]
        for rule in plan["applicable_rules"]
    )


def test_source_reference_is_frozen_to_observed_git_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    assessment = assessment_fixture(tmp_path)
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "initial")
    observed = _git(tmp_path, "rev-parse", "HEAD")
    assessment["source_references"][0]["observed_ref"] = "HEAD"
    assessment["investigation_ref"] = "HEAD"

    normalized = validate_assessment(assessment, project_dir=tmp_path)
    (tmp_path / "src.py").write_text("changed\n", encoding="utf-8")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "advance")

    assert normalized["source_references"][0]["observed_ref"] == observed
    assert normalized["investigation_ref"] == observed
    assert _git(tmp_path, "rev-parse", "HEAD") != observed


def test_operation_paths_are_explicit_but_not_prejudged_from_working_tree(
    tmp_path: Path,
) -> None:
    duplicate = assessment_fixture(tmp_path)
    duplicate["operations"].append(clone_assessment(duplicate["operations"][0]))
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(duplicate, project_dir=tmp_path)

    create_existing = assessment_fixture(tmp_path)
    create_existing["operations"][0]["action"] = "create"
    normalized = validate_assessment(create_existing, project_dir=tmp_path)
    assert normalized["operations"][0]["action"] == "create"

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "freeze investigation state")
    create_existing["investigation_ref"] = "HEAD"
    create_existing["source_references"][0]["observed_ref"] = "HEAD"
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(create_existing, project_dir=tmp_path)

    missing_modify = assessment_fixture(tmp_path)
    missing_modify["investigation_ref"] = "HEAD"
    missing_modify["source_references"][0]["observed_ref"] = "HEAD"
    missing_modify["operations"][0]["path"] = "missing.py"
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(missing_modify, project_dir=tmp_path)

    crossing = assessment_fixture(tmp_path)
    crossing["operations"][0].update(
        {"action": "move", "to_path": "moved.py"}
    )
    crossing["operations"].append(
        {
            "action": "create",
            "path": "moved.py",
            "reason": "制造候选内部冲突。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
        }
    )
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(crossing, project_dir=tmp_path)


def test_adopted_authorities_must_match_the_project_baseline_references(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    profile = load_base_governance_profile()
    profile["project_engineering_baseline_path"] = (
        "docs/engineering/baseline.yaml"
    )
    known = {
        "ARCH-1111111111111111": {
            "artifact_type": "architecture",
            "path": "src.py",
        }
    }

    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_authority_artifacts=known,
        )

    assessment["operations"][0]["long_lived_artifact"] = {
        "artifact_id": "MODEL-1111111111111111",
        "artifact_type": "domain_model",
    }
    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_authority_artifacts=known,
        )

    source_operation = assessment_fixture(tmp_path)
    source_operation["operations"][0].update(
        {
            "path": "docs/domain/sources/world-time.yaml",
            "long_lived_artifact": {
                "artifact_id": "MODEL-2222222222222222",
                "artifact_type": "domain_model",
            },
        }
    )
    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            source_operation,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_authority_artifacts=known,
        )

    assessment["operations"][0]["long_lived_artifact"] = {
        "artifact_id": "ARCH-1111111111111111",
        "artifact_type": "architecture",
    }
    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_authority_artifacts=known,
        )

    assessment["operations"].append(
        {
            "action": "modify",
            "path": "docs/engineering/baseline.yaml",
            "reason": "记录本事项对长期架构产物的更新关系。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
        }
    )
    refresh_single_slice(assessment)
    normalized = _validate_assessment(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        profile=profile,
        known_authority_artifacts=known,
    )

    assert normalized["operations"][0]["long_lived_artifact"] == {
        "artifact_id": "ARCH-1111111111111111",
        "artifact_type": "architecture",
    }


def test_ordinary_long_lived_artifact_update_uses_exact_observed_source(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "record existing interface artifact")
    investigation_ref = _git(tmp_path, "rev-parse", "HEAD")
    assessment["investigation_ref"] = investigation_ref
    assessment["source_references"][0]["observed_ref"] = investigation_ref
    assessment["operations"][0]["long_lived_artifact"] = {
        "artifact_id": "IFACE-001",
        "artifact_type": "interface",
    }

    normalized = _validate_assessment(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        profile=load_base_governance_profile(),
        known_authority_artifacts={},
    )

    assert normalized["operations"][0]["long_lived_artifact"] == {
        "artifact_id": "IFACE-001",
        "artifact_type": "interface",
    }


def test_existing_project_rejects_second_core_authority_identity(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["operations"][0].update(
        {
            "action": "create",
            "path": "docs/domain/replacement.yaml",
            "long_lived_artifact": {
                "artifact_id": "MODEL-2222222222222222",
                "artifact_type": "domain_model",
            },
        }
    )
    refresh_single_slice(assessment)
    known = {
        "MODEL-1111111111111111": {
            "authority_kind": "domain_model",
            "artifact_type": "domain_model",
            "path": "docs/domain/model.yaml",
        }
    }

    with pytest.raises(EngineeringGovernanceError) as captured:
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=load_base_governance_profile(),
            known_authority_artifacts=known,
        )

    assert any(
        "第二个核心domain_model 身份" in issue
        for issue in captured.value.issues
    )


@pytest.mark.parametrize("action", ["modify", "move", "delete"])
def test_current_authority_changes_require_a_baseline_reference_operation(
    tmp_path: Path,
    action: str,
) -> None:
    assessment = assessment_fixture(tmp_path)
    profile = load_base_governance_profile()
    profile["project_engineering_baseline_path"] = (
        "docs/engineering/baseline.yaml"
    )
    assessment["operations"][0].update(
        {
            "action": action,
            "long_lived_artifact": {
                "artifact_id": "ARCH-1111111111111111",
                "artifact_type": "architecture",
            },
        }
    )
    if action == "move":
        assessment["operations"][0]["to_path"] = "architecture-moved.yaml"
    known = {
        "ARCH-1111111111111111": {
            "artifact_type": "architecture",
            "path": "src.py",
        },
    }

    with pytest.raises(EngineeringGovernanceError):
        _validate_assessment(
            assessment,
            project_dir=tmp_path,
            work_item_id=WORK_ITEM_ID,
            direction=direction_fixture(),
            direction_version=DEFAULT_DIRECTION_VERSION,
            profile=profile,
            known_authority_artifacts=known,
        )

    assessment["operations"].append(
        {
            "action": "modify",
            "path": "docs/engineering/baseline.yaml",
            "reason": "同步长期产物的路径或建设关系。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
        }
    )
    refresh_single_slice(assessment)

    normalized = _validate_assessment(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
        direction=direction_fixture(),
        direction_version=DEFAULT_DIRECTION_VERSION,
        profile=profile,
        known_authority_artifacts=known,
    )

    assert normalized["operations"][0]["action"] == action


def test_create_project_requires_config_and_first_baseline_operations(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["change_context"].update(
        {
            "change_kind": "create_project",
            "project_engineering_baseline_path": "docs/engineering/baseline.yaml",
            "project_product_definition_path": "docs/product/definition.yaml",
            "project_domain_model_path": "docs/domain/model.yaml",
            "project_architecture_description_path": "docs/engineering/architecture.yaml",
            "project_engineering_policy_path": "docs/engineering/policy.yaml",
            "project_implementation_alignment_path": "docs/engineering/alignment.yaml",
        }
    )

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)
    assert any(
        issue.startswith(
            "create_project 必须显式创建项目配置和首个长期权威"
        )
        for issue in captured.value.issues
    )


def test_create_project_requires_each_authority_at_its_declared_path(
    tmp_path: Path,
) -> None:
    assessment = new_project_adr_assessment(tmp_path)
    product_operation = next(
        operation
        for operation in assessment["operations"]
        if operation.get("path") == "docs/product/definition.yaml"
    )
    product_operation["long_lived_artifact"]["artifact_type"] = "interface"

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert any(
        issue.startswith(
            "create_project 的五类项目权威必须按约定类型独立建立"
        )
        for issue in captured.value.issues
    )


@pytest.mark.parametrize(
    ("authority_path", "invalid_identity", "authority_kind", "identity_pattern"),
    [
        (
            "docs/product/definition.yaml",
            "PRODUCT-DEFINITION-001",
            "product_definition",
            "PRODUCT-[0-9A-F]{16}",
        ),
        (
            "docs/domain/model.yaml",
            "DOMAIN-MODEL-001",
            "domain_model",
            "MODEL-[0-9A-F]{16}",
        ),
        (
            "docs/architecture/model.yaml",
            "ARCHITECTURE-001",
            "target_architecture",
            "ARCH-[0-9A-F]{16}",
        ),
        (
            "docs/engineering/policy.yaml",
            "ENGINEERING-POLICY-001",
            "engineering_policy",
            "POLICY-[0-9A-F]{16}",
        ),
        (
            "docs/engineering/alignment.yaml",
            "IMPLEMENTATION-ALIGNMENT-001",
            "implementation_alignment",
            "ALIGNMODEL-[0-9A-F]{16}",
        ),
    ],
)
def test_create_project_rejects_core_authority_identities_that_candidates_cannot_use(
    tmp_path: Path,
    authority_path: str,
    invalid_identity: str,
    authority_kind: str,
    identity_pattern: str,
) -> None:
    assessment = new_project_adr_assessment(tmp_path)
    authority_operation = next(
        operation
        for operation in assessment["operations"]
        if operation.get("path") == authority_path
    )
    authority_operation["long_lived_artifact"]["artifact_id"] = invalid_identity

    with pytest.raises(EngineeringGovernanceError) as captured:
        validate_assessment(assessment, project_dir=tmp_path)

    assert (
        f"long_lived_artifact.artifact_id 必须符合 {authority_kind} "
        f"稳定身份格式 {identity_pattern}"
        in "；".join(captured.value.issues)
    )


def test_a0_assessment_has_no_repository_operation_or_fake_verification(
    tmp_path: Path,
) -> None:
    assessment = exploration_assessment(tmp_path)
    normalized = validate_assessment(assessment, project_dir=tmp_path)
    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )

    assert normalized["operations"] == []
    assert normalized["verification_commands"] == []
    assert plan["assurance_band"] == "A0"

    invalid = exploration_assessment(tmp_path)
    invalid["operations"] = clone_assessment(
        assessment_fixture(tmp_path)["operations"]
    )
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(invalid, project_dir=tmp_path)


def test_risk_facts_raise_assurance_without_file_count_heuristics(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["risk_assessments"][0].update(
        {
            "consequence": "critical",
            "reversibility": "irreversible",
            "external_assurance_required": True,
        }
    )

    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )
    assert plan["assurance_band"] == "A4"


def test_a0_can_omit_empty_engineering_sections_without_fake_semantics(
    tmp_path: Path,
) -> None:
    assessment = exploration_assessment(tmp_path)

    assert "risk_assessments" not in assessment
    assert "operations" not in assessment
    assert "verification_commands" not in assessment
    assert "delivery_plan" not in assessment

    normalized = validate_assessment(assessment, project_dir=tmp_path)

    assert normalized["risk_assessments"] == []
    assert normalized["operations"] == []
    assert normalized["verification_commands"] == []
    assert normalized["delivery_plan"] is None
    assert normalized["verification_not_required_reason"]


def test_non_command_review_can_fulfil_the_verification_information_obligation(tmp_path: Path) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["verification_commands"] = []
    assessment["verification_not_required_reason"] = "本例通过来源审阅验证，不生成占位命令。"
    assessment["verification_reviews"] = [
        {"target_ref": ref, "method": "agent_review", "reason": "对照来源审阅已声明的具体条件。", "evidence_refs": ["direction"]}
        for ref in ("direction.acceptance:DIRACC-3333333333333333", "direction.constraint:DIRCON-2222222222222222", "risk_assessments[0]")
    ]
    refresh_single_slice(assessment)
    normalized = validate_assessment(assessment, project_dir=tmp_path)
    assert normalized["verification_commands"] == []
    assert len(normalized["verification_reviews"]) == 3


def test_formal_low_impact_change_can_explain_why_no_command_is_needed(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    testing = next(
        item
        for item in assessment["impact_scope"]["affected"]
        if item["dimension"] == "testing"
    )
    assessment["impact_scope"]["affected"].remove(testing)
    assessment["impact_scope"]["unaffected"].append("testing")
    assessment["risk_assessments"] = []
    assessment["verification_commands"] = []
    assessment["verification_not_required_reason"] = (
        "本次只调整说明文字，源码行为和测试行为均不改变。"
    )
    assessment["verification_reviews"] = [
        {"target_ref": ref, "method": "agent_review", "reason": "对照原说明与当前候选审阅文字含义及执行约束。", "evidence_refs": ["direction"]}
        for ref in ("direction.acceptance:DIRACC-3333333333333333", "direction.constraint:DIRCON-2222222222222222")
    ]
    refresh_single_slice(assessment)

    normalized = validate_assessment(assessment, project_dir=tmp_path)
    plan = compile_engineering_plan(
        assessment,
        project_dir=tmp_path,
        work_item_id=WORK_ITEM_ID,
    )

    assert normalized["risk_assessments"] == []
    assert normalized["verification_commands"] == []
    assert plan["assurance_band"] == "A1"
    assert all(
        rule["rule_id"] != "STRIXNOVA-GOV-TEST-001"
        for rule in plan["applicable_rules"]
    )


def test_assessment_binds_current_direction_and_rejects_coerced_semantics(
    tmp_path: Path,
) -> None:
    stale = assessment_fixture(tmp_path)
    stale["direction_ref"]["direction_version"] -= 1
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(stale, project_dir=tmp_path)

    non_string = assessment_fixture(tmp_path)
    non_string["assessment_id"] = True
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(non_string, project_dir=tmp_path)

    non_string_path = assessment_fixture(tmp_path)
    non_string_path["verification_commands"][0]["cwd"] = 123
    with pytest.raises(EngineeringGovernanceError):
        validate_assessment(non_string_path, project_dir=tmp_path)
