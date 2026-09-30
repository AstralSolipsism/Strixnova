from pathlib import Path
import json
import re

import pytest
import yaml

from strixnova.agent_setup import AgentSetupError, install_agent_skill
from strixnova.cli import main
from strixnova.delivery_activity import (
    validate_activity_plan,
    validate_activity_receipt,
)


EXPECTED_SKILL_FILES = {
    "SKILL.md",
    "agents/openai.yaml",
    "references/architecture-artifact-contracts.md",
    "references/artifact-documentation.md",
    "references/artifact-formation.md",
    "references/code-review.md",
    "references/behavior-contracts.md",
    "references/behavior-examples.md",
    "references/confirmation-and-cancel.md",
    "references/authority-authoring.md",
    "references/cross-artifact-review.md",
    "references/delivery.md",
    "references/direction.md",
    "references/domain-documentation.md",
    "references/domain-fact-contracts.md",
    "references/domain-modeling-and-alignment.md",
    "references/engineering-assessment.md",
    "references/engineering-methods.md",
    "references/engineering-policy-contracts.md",
    "references/history-and-upgrade.md",
    "references/follow-ups.md",
    "references/implementation-alignment-artifact-contracts.md",
    "references/implementation-alignment-workflow.md",
    "references/implementation-practices.md",
    "references/ux-design.md",
    "references/prd-authoring.md",
    "references/product-discovery.md",
    "references/replanning.md",
    "references/spec-authoring.md",
    "references/verification.md",
}


PROJECT_ROOT = Path(__file__).parents[2]
PACKAGED_SKILL_ROOT = (
    PROJECT_ROOT
    / "strixnova"
    / "src"
    / "strixnova"
    / "resources"
    / "agent-skill"
    / "strixnova"
)


CAPABILITY_GUIDANCE = {
    "Strixnova 自身升级与恢复保障": (
        "references/history-and-upgrade.md",
        "## Upgrade Strixnova itself",
    ),
    "项目产品权威治理": (
        "references/domain-modeling-and-alignment.md",
        "## 建立或修订产品定义",
    ),
    "项目领域模型治理": (
        "references/domain-modeling-and-alignment.md",
        "## 建立或修订领域模型",
    ),
    "目标架构治理": (
        "references/domain-modeling-and-alignment.md",
        "## 建立或修订目标架构",
    ),
    "实现对齐与漂移治理": (
        "references/implementation-alignment-workflow.md",
        "# Installed implementation-alignment workflow",
    ),
    "产品发现与想法验证": (
        "references/product-discovery.md",
        "## First decide whether discovery is needed",
    ),
    "引导式方向澄清": (
        "references/direction.md",
        "## Clarify proportionally before submission",
    ),
    "软件工程评估与方案治理": (
        "references/engineering-assessment.md",
        "# Engineering assessment submission",
    ),
    "建设事项与本地交付协调": (
        "SKILL.md",
        "## Start a WorkItem",
    ),
    "验证与实际证据治理": (
        "references/verification.md",
        "## Run a command",
    ),
    "交付发布与运行维护治理": (
        "references/delivery.md",
        "## 治理外部活动",
    ),
    "全链路追溯与下一步投影": (
        "SKILL.md",
        "engineering.trace.current",
    ),
    "受支持智能编码代理交互": (
        "SKILL.md",
        "## Choose the public route",
    ),
}


def _named_json_example(text: str, name: str) -> dict:
    match = re.search(
        rf"<!-- strixnova-example:{re.escape(name)} -->\s*"
        r"```json\s*(.*?)\s*```\s*<!-- /strixnova-example -->",
        text,
        re.DOTALL,
    )
    assert match is not None, name
    value = json.loads(match.group(1))
    assert isinstance(value, dict)
    return value


def test_packaged_agent_skill_has_one_entry_and_reachable_internal_references() -> None:
    entrypoints = [
        path.relative_to(PACKAGED_SKILL_ROOT).as_posix()
        for path in PACKAGED_SKILL_ROOT.rglob("SKILL.md")
    ]
    assert entrypoints == ["SKILL.md"]

    root = PACKAGED_SKILL_ROOT.resolve()
    pending = [root / "SKILL.md"]
    visited: set[Path] = set()
    while pending:
        document = pending.pop()
        if document in visited:
            continue
        visited.add(document)
        for link in re.findall(r"\]\(([^)\s]+)\)", document.read_text(encoding="utf-8")):
            if "://" in link or link.startswith("#"):
                continue
            relative = link.split("#", 1)[0]
            if not relative.endswith(".md"):
                continue
            target = (document.parent / relative).resolve()
            assert target.is_relative_to(root), (document, link)
            assert target.is_file(), (document, link)
            pending.append(target)
    linked_references = {
        path.relative_to(root).as_posix()
        for path in visited
        if path.parent == root / "references"
    }
    packaged_references = {
        path.relative_to(PACKAGED_SKILL_ROOT).as_posix()
        for path in (PACKAGED_SKILL_ROOT / "references").glob("*.md")
    }
    assert linked_references == packaged_references

    packaged_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PACKAGED_SKILL_ROOT.rglob("*.md")
    )
    assert "C:\\Users\\" not in packaged_text
    assert "/.agents/skills/" not in packaged_text
    assert "/.codex/skills/" not in packaged_text


def test_product_discovery_guidance_is_optional_and_has_bounded_outcomes() -> None:
    entry = (PACKAGED_SKILL_ROOT / "SKILL.md").read_text(encoding="utf-8")
    discovery = (
        PACKAGED_SKILL_ROOT / "references" / "product-discovery.md"
    ).read_text(encoding="utf-8")

    assert "[product-discovery.md](references/product-discovery.md)" in entry
    assert "Skip it for a clear bounded request" in entry
    assert "Product discovery may end" in entry
    assert "without a WorkItem" in entry
    for heading in (
        "## Action 1: frame the problem",
        "## Action 2: expand genuinely different options",
        "## Action 3: stress-test the load-bearing assumption",
        "## Action 4: investigate decision-changing evidence",
        "## Action 5: synthesize the product understanding",
    ):
        assert heading in discovery
    assert "they are not stages" in discovery
    assert "Do not ask the owner to choose a Strixnova mode" in discovery
    assert "The last three outcomes do not require a WorkItem" in discovery
    assert "remain outside\n`.strixnova`" in discovery
    assert re.search(r"`strixnova [a-z]", discovery) is None

def test_domain_fact_reference_matches_every_runtime_fact_contract() -> None:
    reference = (
        PACKAGED_SKILL_ROOT / "references" / "domain-fact-contracts.md"
    ).read_text(encoding="utf-8")
    schema = json.loads(
        (
            PROJECT_ROOT
            / "strixnova"
            / "src"
            / "strixnova"
            / "resources"
            / "project-domain-source-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    definition_names = {
        "actor": "actor_content",
        "product_capability": "product_capability_content",
        "domain_scenario": "domain_scenario_content",
        "domain_entity": "domain_entity_content",
        "value_object": "value_object_content",
        "lifecycle": "lifecycle_content",
        "domain_event": "domain_event_content",
        "domain_rule": "domain_rule_content",
        "domain_invariant": "domain_invariant_content",
        "decision_authority": "decision_authority_content",
        "bounded_context": "bounded_context_content",
        "context_relationship": "context_relationship_content",
        "external_system": "external_system_content",
        "term": "term_content",
    }
    assert set(schema["$defs"]["kind"]["enum"]) == set(definition_names)
    for kind, definition_name in definition_names.items():
        assert f"`{kind}`" in reference
        for field_name in schema["$defs"][definition_name]["required"]:
            assert f"`{field_name}`" in reference

    for nested_name in (
        "scenario_requirement",
        "value_component",
        "lifecycle_state",
        "lifecycle_transition",
    ):
        for field_name in schema["$defs"][nested_name]["required"]:
            assert f"`{field_name}`" in reference


def test_architecture_reference_matches_every_runtime_artifact_contract() -> None:
    reference = (
        PACKAGED_SKILL_ROOT
        / "references"
        / "architecture-artifact-contracts.md"
    ).read_text(encoding="utf-8")
    schema = json.loads(
        (
            PROJECT_ROOT
            / "strixnova"
            / "src"
            / "strixnova"
            / "resources"
            / "project-architecture-description-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    schema_versions = (
        "strixnova.architecture-modules.v1",
        "strixnova.architecture-relationships.v1",
        "strixnova.architecture-constraints.v1",
        "strixnova.architecture-domain-fact-dispositions.v1",
        "strixnova.architecture-implementation-stages.v1",
    )
    for schema_version in schema_versions:
        assert f"`{schema_version}`" in reference

    for definition_name in (
        "operation",
        "public_interface",
        "module",
        "module_catalog",
        "relationship",
        "relationship_catalog",
        "verification_method",
        "constraint",
        "constraint_catalog",
        "disposition",
        "disposition_catalog",
        "stage",
        "stage_catalog",
    ):
        for field_name in schema["$defs"][definition_name]["required"]:
            assert f"`{field_name}`" in reference
def test_alignment_reference_matches_every_runtime_artifact_contract() -> None:
    reference = (
        PACKAGED_SKILL_ROOT
        / "references"
        / "implementation-alignment-artifact-contracts.md"
    ).read_text(encoding="utf-8")
    schema = json.loads(
        (
            PROJECT_ROOT
            / "strixnova"
            / "src"
            / "strixnova"
            / "resources"
            / "project-implementation-alignment-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    schema_versions = (
        "strixnova.implementation-source-ownership.v1",
        "strixnova.implementation-actual-dependencies.v1",
        "strixnova.implementation-target-responsibilities.v1",
        "strixnova.implementation-deviations.v1",
    )
    for schema_version in schema_versions:
        assert f"`{schema_version}`" in reference

    for definition_name in (
        "source_record",
        "source_ownership_catalog",
        "dependency_record",
        "dependency_catalog",
        "evidence",
        "responsibility_record",
        "responsibility_catalog",
        "deviation",
        "deviation_catalog",
    ):
        for field_name in schema["$defs"][definition_name]["required"]:
            assert f"`{field_name}`" in reference


def test_engineering_policy_reference_matches_every_runtime_nested_contract() -> None:
    reference = (
        PACKAGED_SKILL_ROOT
        / "references"
        / "engineering-policy-contracts.md"
    ).read_text(encoding="utf-8")
    schema = json.loads(
        (
            PROJECT_ROOT
            / "strixnova"
            / "src"
            / "strixnova"
            / "resources"
            / "project-engineering-policy-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    for definition_name in (
        "method_adoption",
        "policy_statements",
        "project_source",
        "rule_extension",
        "rule_tailoring",
        "verification_program",
        "verification_policy",
        "delivery_gates",
        "evidence_requirements",
        "unresolved_decision",
    ):
        for field_name in schema["$defs"][definition_name]["required"]:
            assert f"`{field_name}`" in reference

    for status in schema["$defs"]["project_source"]["properties"]["status"][
        "enum"
    ]:
        assert f"`{status}`" in reference


def test_engineering_assessment_reference_covers_external_provider_plan() -> None:
    reference = (
        PACKAGED_SKILL_ROOT / "references" / "engineering-assessment.md"
    ).read_text(encoding="utf-8")
    schema = json.loads(
        (
            PROJECT_ROOT
            / "strixnova"
            / "src"
            / "strixnova"
            / "resources"
            / "engineering-assessment-v1.schema.json"
        ).read_text(encoding="utf-8")
    )

    for field_name in schema["$defs"]["external_observation_provider_plan"][
        "required"
    ]:
        assert f'"{field_name}"' in reference
    for nested_name in (
        "external_observation_process_policy",
        "external_observation_limits",
    ):
        for field_name in schema["$defs"][nested_name]["required"]:
            assert f'"{field_name}"' in reference
    assert "`strixnova.engineering-plan.v1`" in reference
    assert "`strixnova alignment" in reference


def test_agent_skill_routes_every_public_runtime_command() -> None:
    packaged_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in PACKAGED_SKILL_ROOT.rglob("*.md")
    )
    runtime_commands = set(main.commands) - {"setup-agent"}

    assert runtime_commands == {
        "activity",
        "alignment",
        "authority",
        "cancel",
        "confirm",
        "context",
        "delivery",
        "intake",
        "next",
        "status",
        "submit",
        "verify",
        "history",
        "upgrade",
    }
    for command in runtime_commands:
        assert f"`strixnova {command}`" in packaged_text


def test_agent_skill_has_structural_guidance_for_every_product_capability() -> None:
    product = yaml.safe_load(
        (PROJECT_ROOT / "docs" / "product" / "definition.yaml").read_text(
            encoding="utf-8"
        )
    )
    capability_titles = {item["title"] for item in product["capabilities"]}

    assert capability_titles == set(CAPABILITY_GUIDANCE)
    for title, (relative_path, anchor) in CAPABILITY_GUIDANCE.items():
        guidance = (PACKAGED_SKILL_ROOT / relative_path).read_text(
            encoding="utf-8"
        )
        assert anchor in guidance, title


def test_agent_skill_activity_examples_match_the_runtime_contract() -> None:
    delivery = (
        PACKAGED_SKILL_ROOT / "references" / "delivery.md"
    ).read_text(encoding="utf-8")
    plan_request = _named_json_example(delivery, "activity-plan")
    receipt_request = _named_json_example(delivery, "activity-receipt")

    assert plan_request["action"] == "plan"
    assert validate_activity_plan(plan_request["plan"]) == plan_request["plan"]
    assert receipt_request["action"] == "record"
    assert (
        validate_activity_receipt(receipt_request["receipt"])
        == receipt_request["receipt"]
    )
    assert (
        receipt_request["receipt"]["external_system_id"]
        == plan_request["plan"]["external_system"]["system_id"]
    )


def test_agent_skill_ui_metadata_is_valid() -> None:
    interface = yaml.safe_load(
        (PACKAGED_SKILL_ROOT / "agents" / "openai.yaml").read_text(
            encoding="utf-8"
        )
    )["interface"]
    assert interface["display_name"] == "Strixnova工程治理"
    assert 25 <= len(interface["short_description"]) <= 64
    assert "$strixnova" in interface["default_prompt"]


def test_agent_skill_install_is_local_idempotent_and_has_no_host_side_effects(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"

    installed = install_agent_skill(skills_dir=skills_dir)

    target = skills_dir / "strixnova"
    assert installed == {
        "schema_version": "strixnova.agent-skill-install.v1",
        "status": "installed",
        "target_path": str(target.resolve()),
        "backup_path": None,
        "modifies_host_config": False,
        "installs_hooks": False,
        "installs_plugins": False,
        "issues_credentials": False,
    }
    installed_files = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    }
    assert installed_files == EXPECTED_SKILL_FILES
    assert install_agent_skill(skills_dir=skills_dir)["status"] == "unchanged"


def test_agent_skill_requires_explicit_replace_and_preserves_a_backup(
    tmp_path: Path,
) -> None:
    skills_dir = tmp_path / "skills"
    install_agent_skill(skills_dir=skills_dir)
    existing = skills_dir / "strixnova" / "SKILL.md"
    existing.write_text("user version", encoding="utf-8")

    with pytest.raises(AgentSetupError) as raised:
        install_agent_skill(skills_dir=skills_dir)

    assert raised.value.code == "skill_already_exists"
    assert existing.read_text(encoding="utf-8") == "user version"

    replaced = install_agent_skill(skills_dir=skills_dir, replace=True)

    backup = Path(str(replaced["backup_path"]))
    assert replaced["status"] == "replaced"
    assert backup.is_dir()
    assert (backup / "SKILL.md").read_text(encoding="utf-8") == "user version"
    assert install_agent_skill(skills_dir=skills_dir)["status"] == "unchanged"
