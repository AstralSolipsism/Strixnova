from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from strixnova.project_engineering_policy import (
    ProjectEngineeringPolicy,
    ProjectEngineeringPolicyError,
    load_base_governance_profile,
)


PROJECT_ROOT = Path(__file__).parents[2]
POLICY_PATH = "docs/engineering/policy.yaml"


def _policy() -> ProjectEngineeringPolicy:
    return ProjectEngineeringPolicy(PROJECT_ROOT, POLICY_PATH)


def _write_policy(tmp_path: Path, value: dict) -> None:
    target = tmp_path / POLICY_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_repository_policy_is_the_current_independent_candidate() -> None:
    policy = _policy().load()

    assert policy["schema_version"] == "strixnova.project-engineering-policy.v1"
    assert policy["revision"]["status"] == "draft"
    assert policy["product_definition_ref"] == {
        "product_id": "PRODUCT-8312417768A84DE4",
        "revision_id": "REVISION-59EB5B9A3F3F46C0",
    }
    assert policy["_semantic_content_machine_proven"] is False


def test_policy_profile_applies_method_adoption_and_owner_tailoring() -> None:
    profile = _policy().governance_profile()
    rules = {item["rule_id"]: item for item in profile["rules"]}

    assert profile["project_method_adoptions"][0]["method_id"] == "ddd"
    assert profile["project_method_adoptions"][0]["status"] == "adopted"
    assert rules["STRIXNOVA-GOV-REQ-001"]["project_tailoring"] == {
        "disposition": "retained",
        "reason": "非专业项目负责人仍需要完整需求和验收引导。",
        "owner_confirmed": True,
    }
    assert profile["project_engineering_policy_ref"]["revision_id"] == (
        "POLICYREV-6151D5CB5D3D4E51"
    )
    assert profile["verification_command_policy"]["plan_binding_required"] is True


def test_policy_projects_only_deterministic_obligations_from_supplied_impacts() -> None:
    result = _policy().obligations(
        ["architecture", "testing"],
        "A1",
    )

    assert result["minimum_required_assurance_band"] == "A3"
    assert {item["rule_id"] for item in result["rules"]} >= {
        "STRIXNOVA-GOV-REQ-001",
        "STRIXNOVA-GOV-LIFE-001",
        "STRIXNOVA-GOV-ARCH-001",
        "STRIXNOVA-GOV-TEST-001",
    }
    assert result["semantic_content_machine_proven"] is False


def test_policy_rejects_unknown_method_and_weakened_strengthening(
    tmp_path: Path,
) -> None:
    value = _policy().load()
    for key in [key for key in value if key.startswith("_")]:
        value.pop(key)
    value["method_adoptions"][0]["method_id"] = "unknown-method"
    value["rule_tailoring"][0]["disposition"] = "strengthened"
    value["rule_tailoring"][0]["minimum_assurance"] = "A0"
    _write_policy(tmp_path, value)

    with pytest.raises(ProjectEngineeringPolicyError) as caught:
        ProjectEngineeringPolicy(tmp_path, POLICY_PATH).load()

    assert any("未知方法" in issue for issue in caught.value.issues)
    assert any("不得降低" in issue for issue in caught.value.issues)


def test_base_profile_keeps_sources_separate_from_project_policy() -> None:
    profile = load_base_governance_profile()

    assert profile["profile_id"] == "strixnova-general-software-engineering"
    assert all(item["source_kind"] != "project_artifact" for item in profile["sources"])


def test_policy_rejects_agent_allow_conflict_and_missing_required_denial(
    tmp_path: Path,
) -> None:
    value = _policy().load()
    for key in [key for key in value if key.startswith("_")]:
        value.pop(key)
    value["verification_command_policy"]["allowed_programs"].append(
        {
            "program": "codex",
            "purpose": "错误地把代理当成验证程序。",
            "argument_policy": "exact_plan_only",
        }
    )
    value["verification_command_policy"]["forbidden_agent_program_names"].remove(
        "windsurf"
    )
    _write_policy(tmp_path, value)

    with pytest.raises(ProjectEngineeringPolicyError) as caught:
        ProjectEngineeringPolicy(tmp_path, POLICY_PATH).load()

    assert any("缺少必须禁止" in issue for issue in caught.value.issues)
    assert any("同时允许并禁止" in issue for issue in caught.value.issues)


def test_policy_reports_exact_project_source_field_errors(tmp_path: Path) -> None:
    value = _policy().load()
    for key in [key for key in value if key.startswith("_")]:
        value.pop(key)
    source = value["project_sources"][0]
    source["reference"] = source.pop("path")
    _write_policy(tmp_path, value)

    with pytest.raises(ProjectEngineeringPolicyError) as caught:
        ProjectEngineeringPolicy(tmp_path, POLICY_PATH).load()

    issues = caught.value.issues
    assert any(
        "项目工程政策.project_sources.0" in issue
        and "缺少必填字段：path" in issue
        for issue in issues
    )
    assert any(
        "项目工程政策.project_sources.0" in issue
        and "包含不允许字段：reference" in issue
        for issue in issues
    )
    assert all("is a required property" not in issue for issue in issues)


def test_policy_requires_known_antigravity_entry_in_agent_denials(tmp_path: Path) -> None:
    value = _policy().load()
    for key in [key for key in value if key.startswith("_")]:
        value.pop(key)
    value["verification_command_policy"]["forbidden_agent_program_names"].remove("agy")
    _write_policy(tmp_path, value)
    with pytest.raises(ProjectEngineeringPolicyError) as rejected:
        ProjectEngineeringPolicy(tmp_path, POLICY_PATH).load()
    assert any("缺少必须禁止" in issue and "agy" in issue for issue in rejected.value.issues)
