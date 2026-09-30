from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

import yaml
from tests.support.project_configuration import configure_repository
from tests.support.project_context import FRONTEND
from strixnova.project_content_snapshot import repository_path_key


TEST_DOMAIN_MODEL_ID = "MODEL-1111111111111111"
TEST_DOMAIN_REVISION_ID = "MODELREV-1111111111111111"
TEST_TERM_FACT_ID = "FACT-1111111111111111"
TEST_CONTEXT_FACT_ID = "FACT-2222222222222222"
TEST_INVARIANT_FACT_ID = "FACT-3333333333333333"
TEST_ALIGNMENT_ID = "ALIGNMODEL-1111111111111111"
TEST_ALIGNMENT_REVISION_ID = "ALIGNREV-1111111111111111"
TEST_ARCHITECTURE_ID = "ARCH-1111111111111111"
TEST_ARCHITECTURE_REVISION_ID = "ARCHREV-1111111111111111"
TEST_MODULE_ID = "MODULE-1111111111111111"
TEST_READER_MODULE_ID = "MODULE-2222222222222222"
TEST_PRODUCT_ID = "PRODUCT-1111111111111111"
TEST_PRODUCT_REVISION_ID = "REVISION-1111111111111111"
TEST_OWNER_ID = "OWNER-1111111111111111"
TEST_CAPABILITY_ID = "CAPABILITY-1111111111111111"
TEST_POLICY_ID = "POLICY-1111111111111111"
TEST_POLICY_REVISION_ID = "POLICYREV-1111111111111111"
TEST_STAGE_ID = "ARCHSTAGE-1111111111111111"


def _write_yaml(project: Path, relative_path: str, value: object) -> None:
    target = project / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _stable_id(prefix: str, seed: str) -> str:
    if seed.startswith(prefix + "-") and len(seed) == len(prefix) + 17:
        return seed
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16].upper()
    return f"{prefix}-{digest}"


def _canonical_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _product_document() -> dict:
    return {
        "schema_version": "strixnova.project-product-definition.v1",
        "product_id": TEST_PRODUCT_ID,
        "revision": {
            "revision_id": TEST_PRODUCT_REVISION_ID,
            "status": "confirmed",
            "supersedes_revision_id": None,
            "confirmed_by_owner_id": TEST_OWNER_ID,
            "confirmed_on": "2026-08-26",
        },
        "title": "隔离测试项目产品定义",
        "purpose": "为公开接口测试提供最小但完整的产品权威。",
        "product_owner": {
            "owner_id": TEST_OWNER_ID,
            "display_name": "隔离测试项目负责人",
        },
        "primary_users": [
            {
                "user_id": "USER-1111111111111111",
                "title": "测试用户",
                "description": "通过公开接口验证确定性行为。",
            }
        ],
        "problems": [
            {
                "problem_id": "PROBLEM-1111111111111111",
                "user_ids": ["USER-1111111111111111"],
                "statement": "需要隔离、可重复地验证项目治理行为。",
            }
        ],
        "desired_outcomes": [
            {
                "outcome_id": "OUTCOME-1111111111111111",
                "statement": "公开接口能够给出确定性且可检查的结果。",
            }
        ],
        "capabilities": [
            {
                "capability_id": TEST_CAPABILITY_ID,
                "title": "测试治理能力",
                "description": "承载隔离测试所需的最小产品范围。",
                "outcome_ids": ["OUTCOME-1111111111111111"],
            }
        ],
        "non_goals": [
            {
                "non_goal_id": "NONGOAL-1111111111111111",
                "statement": "测试程序不裁决工程语义。",
            }
        ],
        "constraints": [
            {
                "constraint_id": "CONSTRAINT-AAAAAAAAAAAAAAAA",
                "statement": "结构校验不得冒充语义正确性。",
            }
        ],
        "success_criteria": [
            {
                "criterion_id": "CRITERION-1111111111111111",
                "statement": "公开接口正常、拒绝和失败行为可重复验证。",
                "outcome_ids": ["OUTCOME-1111111111111111"],
            }
        ],
        "delivery_stages": [
            {
                "stage_id": "STAGE-1111111111111111",
                "title": "当前隔离测试阶段",
                "commitment": "current_target",
                "description": "只覆盖当前测试声明的本地行为。",
            }
        ],
        "unresolved_decisions": [],
    }


def _policy_document(*, ddd_status: str) -> dict:
    adopted = (
        [
            "ubiquitous_language",
            "bounded_context",
            "context_map",
            "domain_invariant_trace",
        ]
        if ddd_status == "adopted"
        else []
    )
    return {
        "schema_version": "strixnova.project-engineering-policy.v1",
        "policy_id": TEST_POLICY_ID,
        "revision": {
            "revision_id": TEST_POLICY_REVISION_ID,
            "status": "confirmed",
            "supersedes_revision_id": None,
            "confirmed_by_owner_id": TEST_OWNER_ID,
            "confirmed_on": "2026-08-26",
        },
        "product_definition_ref": {
            "product_id": TEST_PRODUCT_ID,
            "revision_id": TEST_PRODUCT_REVISION_ID,
        },
        "base_profile_ref": {
            "profile_id": "strixnova-general-software-engineering",
            "profile_version": "2026-08-23",
        },
        "method_adoptions": [
            {
                "method_id": "ddd",
                "status": ddd_status,
                "reason": "隔离测试显式声明工程方法采用状态。",
                "conditions": [],
                "adopted_technique_ids": adopted,
            }
        ],
        "policy_statements": {
            "quality": ["结构、语义和效果证据分开报告。"],
            "testing": ["只运行测试明确安排的命令。"],
            "security": ["不建立代理身份或会话。"],
            "release": ["只验证本地交付。"],
            "operations": ["外部操作必须有真实回执。"],
            "maintenance": ["新接口接管后删除旧机制。"],
            "compatibility": ["隔离测试不读取旧权威合同。"],
        },
        "project_sources": [],
        "rule_extensions": [],
        "rule_tailoring": [],
        "verification_command_policy": {
            "allowed_programs": [
                {
                    "program": sys.executable,
                    "purpose": "运行隔离测试。",
                    "argument_policy": "exact_plan_only",
                }
            ],
            "forbidden_agent_program_names": [
                "agy",
                "aider",
                "claude",
                "codex",
                "cursor",
                "gemini",
                "opencode",
                "windsurf",
            ],
            "wrapper_policy": "forbidden_unless_exactly_approved",
            "working_directory_policy": "project_or_authorized_worktree_only",
            "plan_binding_required": True,
        },
        "delivery_gates": {
            "result_acceptance_before_commit": True,
            "local_integration_only": True,
            "external_execution_requires_external_receipt": True,
            "remote_operations_in_scope": False,
        },
        "evidence_requirements": {
            "separate_structure_semantics_confirmation_effect_and_conformance": True,
            "unrun_items_visible": True,
            "semantic_correctness_machine_proven": False,
            "external_conformance_without_external_evidence": False,
        },
        "unresolved_decisions": [],
    }


def _domain_documents(
    *, domain_facts: list[dict]
) -> tuple[dict[str, dict], str, str]:
    model_path = "docs/domain/model.yaml"
    collection_path = "docs/domain/collections/core.yaml"
    source_path = "docs/domain/sources/core.yaml"
    values = {
        model_path: {
            "schema_version": "strixnova.project-domain-model.v1",
            "model_id": TEST_DOMAIN_MODEL_ID,
            "revision": {
                "revision_id": TEST_DOMAIN_REVISION_ID,
                "status": "confirmed",
                "supersedes_revision_id": None,
                "confirmed_by_owner_id": TEST_OWNER_ID,
                "confirmed_on": "2026-08-26",
            },
            "product_definition_ref": {
                "product_id": TEST_PRODUCT_ID,
                "revision_id": TEST_PRODUCT_REVISION_ID,
            },
            "title": "测试项目领域模型",
            "purpose": "验证类型化领域事实、引用和实现对齐。",
            "root_collection_paths": [collection_path],
            "unresolved_decisions": [],
        },
        collection_path: {
            "schema_version": "strixnova.project-domain-collection.v1",
            "model_id": TEST_DOMAIN_MODEL_ID,
            "model_revision_id": TEST_DOMAIN_REVISION_ID,
            "collection_id": "COLL-1111111111111111",
            "title": "测试领域集合",
            "routing_summary": "测试领域事实。",
            "child_collection_paths": [],
            "sources": [
                {
                    "source_id": "SRC-1111111111111111",
                    "title": "测试领域事实",
                    "routing_summary": "隔离测试所需事实。",
                    "path": source_path,
                }
            ],
        },
        source_path: {
            "schema_version": "strixnova.project-domain-source.v1",
            "model_id": TEST_DOMAIN_MODEL_ID,
            "model_revision_id": TEST_DOMAIN_REVISION_ID,
            "source_id": "SRC-1111111111111111",
            "scope_fact_ids": [TEST_CONTEXT_FACT_ID],
            "facts": domain_facts,
        },
    }
    return values, model_path, source_path


def _architecture_documents(
    architecture_path: str, *, domain_fact_ids: list[str]
) -> dict[str, dict]:
    parent = PurePosixPath(architecture_path).parent.as_posix()
    artifact_paths = {
        "modules": f"{parent}/architecture-modules.yaml",
        "relationships": f"{parent}/architecture-relationships.yaml",
        "constraints": f"{parent}/architecture-constraints.yaml",
        "domain_fact_dispositions": f"{parent}/architecture-domain-facts.yaml",
        "implementation_stages": f"{parent}/architecture-stages.yaml",
    }
    domain_ref = {
        "model_id": TEST_DOMAIN_MODEL_ID,
        "revision_id": TEST_DOMAIN_REVISION_ID,
    }
    return {
        architecture_path: {
            "schema_version": "strixnova.project-architecture-description.v1",
            "architecture_id": TEST_ARCHITECTURE_ID,
            "revision": {
                "revision_id": TEST_ARCHITECTURE_REVISION_ID,
                "status": "confirmed",
                "supersedes_revision_id": None,
                "confirmed_by_owner_id": TEST_OWNER_ID,
                "confirmed_on": "2026-08-26",
            },
            "domain_model_ref": domain_ref,
            "title": "隔离测试项目目标架构",
            "purpose": "验证第二版长期架构权威。",
            "artifact_paths": artifact_paths,
            "unresolved_decisions": [],
        },
        artifact_paths["modules"]: {
            "schema_version": "strixnova.architecture-modules.v1",
            "architecture_id": TEST_ARCHITECTURE_ID,
            "architecture_revision_id": TEST_ARCHITECTURE_REVISION_ID,
            "modules": [
                {
                    "module_id": TEST_MODULE_ID,
                    "title": "测试应用模块",
                    "layer": "application",
                    "responsibility": "承载测试用例。",
                    "not_responsible_for": ["不保存外部读取实现。"],
                    "public_interface": {
                        "interface_id": "INTERFACE-1111111111111111",
                        "title": "测试应用接口",
                        "operations": [
                            {"name": "执行测试用例", "meaning": "执行确定性测试行为。"}
                        ],
                    },
                },
                {
                    "module_id": TEST_READER_MODULE_ID,
                    "title": "测试读取模块",
                    "layer": "infrastructure",
                    "responsibility": "提供测试读取事实。",
                    "not_responsible_for": ["不决定测试语义。"],
                    "public_interface": {
                        "interface_id": "INTERFACE-2222222222222222",
                        "title": "测试读取接口",
                        "operations": [
                            {"name": "读取测试事实", "meaning": "返回确定性测试事实。"}
                        ],
                    },
                },
            ],
        },
        artifact_paths["relationships"]: {
            "schema_version": "strixnova.architecture-relationships.v1",
            "architecture_id": TEST_ARCHITECTURE_ID,
            "architecture_revision_id": TEST_ARCHITECTURE_REVISION_ID,
            "default_relationship_policy": "forbidden",
            "relationships": [
                {
                    "relationship_id": "RELATION-1111111111111111",
                    "from_module_id": TEST_MODULE_ID,
                    "to_module_id": TEST_READER_MODULE_ID,
                    "mode": "read_only_projection",
                    "mediator_module_id": None,
                    "contract": "测试应用只读取得测试事实。",
                    "reason": "保持写入和读取职责分离。",
                }
            ],
        },
        artifact_paths["constraints"]: {
            "schema_version": "strixnova.architecture-constraints.v1",
            "architecture_id": TEST_ARCHITECTURE_ID,
            "architecture_revision_id": TEST_ARCHITECTURE_REVISION_ID,
            "constraints": [
                {
                    "constraint_id": "CONSTRAINT-1111111111111111",
                    "title": "测试职责分离",
                    "statement": "测试应用不得反向修改读取事实。",
                    "applies_to_module_ids": [TEST_MODULE_ID, TEST_READER_MODULE_ID],
                    "verification_methods": [
                        {
                            "method_type": "behavior_acceptance",
                            "description": "通过公开行为测试验证职责分离。",
                        }
                    ],
                }
            ],
        },
        artifact_paths["domain_fact_dispositions"]: {
            "schema_version": "strixnova.architecture-domain-fact-dispositions.v1",
            "architecture_id": TEST_ARCHITECTURE_ID,
            "architecture_revision_id": TEST_ARCHITECTURE_REVISION_ID,
            "domain_model_ref": domain_ref,
            "dispositions": [
                {
                    "domain_fact_id": fact_id,
                    "disposition_type": "primary_module",
                    "primary_module_id": TEST_MODULE_ID,
                    "collaborator_module_ids": [],
                    "relationship_ids": [],
                    "constraint_ids": ["CONSTRAINT-1111111111111111"],
                    "rationale": "测试事实由测试应用模块主要承载。",
                }
                for fact_id in domain_fact_ids
            ],
        },
        artifact_paths["implementation_stages"]: {
            "schema_version": "strixnova.architecture-implementation-stages.v1",
            "architecture_id": TEST_ARCHITECTURE_ID,
            "architecture_revision_id": TEST_ARCHITECTURE_REVISION_ID,
            "stages": [
                {
                    "stage_id": TEST_STAGE_ID,
                    "order": 1,
                    "title": "当前测试阶段",
                    "scope": "current_product_stage",
                    "prerequisite_stage_ids": [],
                    "module_ids": [TEST_MODULE_ID, TEST_READER_MODULE_ID],
                    "entry_conditions": ["测试目标已经确认。"],
                    "completion_conditions": ["测试公开行为通过。"],
                }
            ],
        },
    }


def _alignment_documents(
    alignment_path: str,
    *,
    implementation_path: str,
    implementation_sha256: str,
    verification_path: str | None,
) -> dict[str, dict]:
    parent = PurePosixPath(alignment_path).parent.as_posix()
    artifact_paths = {
        "source_ownership": f"{parent}/source-ownership.yaml",
        "actual_dependencies": f"{parent}/actual-dependencies.yaml",
        "target_responsibilities": f"{parent}/target-responsibilities.yaml",
        "deviations": f"{parent}/deviations.yaml",
    }
    evidence = [
        {
            "kind": "source",
            "ref": implementation_path,
            "claim": "测试实现路径承载目标模块公开行为。",
        }
    ]
    if verification_path:
        evidence.append(
            {
                "kind": "test",
                "ref": verification_path,
                "claim": "测试路径验证目标模块公开行为。",
            }
        )
    responsibilities = [
        ("module", TEST_MODULE_ID),
        ("module", TEST_READER_MODULE_ID),
        ("relationship", "RELATION-1111111111111111"),
        ("constraint", "CONSTRAINT-1111111111111111"),
    ]
    binding = {
        "alignment_model_id": TEST_ALIGNMENT_ID,
        "alignment_revision_id": TEST_ALIGNMENT_REVISION_ID,
    }
    observation_scope_id = "OBSCOPE-1111111111111111"
    package_name = PurePosixPath(implementation_path).stem
    implementation_key = repository_path_key(FRONTEND, implementation_path)
    observed_paths = {implementation_key: implementation_sha256}
    governed_manifest = hashlib.sha256(
        f"{implementation_key}:{implementation_sha256}\n".encode("utf-8")
    ).hexdigest()
    return {
        alignment_path: {
            "schema_version": "strixnova.project-implementation-alignment.v1",
            "alignment_model_id": TEST_ALIGNMENT_ID,
            "revision": {
                "revision_id": TEST_ALIGNMENT_REVISION_ID,
                "status": "confirmed",
                "supersedes_revision_id": None,
                "confirmed_by_owner_id": TEST_OWNER_ID,
                "confirmed_on": "2026-08-26",
            },
            "domain_model_ref": {
                "model_id": TEST_DOMAIN_MODEL_ID,
                "revision_id": TEST_DOMAIN_REVISION_ID,
            },
            "architecture_ref": {
                "architecture_id": TEST_ARCHITECTURE_ID,
                "revision_id": TEST_ARCHITECTURE_REVISION_ID,
            },
            "code_snapshot": {
                "repositories": [{"repository_id": FRONTEND, "base_commit": "0" * 40, "worktree_state": "dirty"}],
                "governed_source_manifest_sha256": governed_manifest,
                "observed_on": "2026-08-26",
            },
            "observation_scopes": [
                {
                    "scope_id": observation_scope_id,
                    "repository_id": FRONTEND,
                    "root": implementation_path,
                    "languages": ["python"],
                    "required_relation_kinds": ["source_import"],
                    "configurations": ["default"],
                    "exclusions": [],
                    "provider_options": {
                        "python_package_name": package_name,
                    },
                }
            ],
            "observation_coverage": {
                "contract_version": "strixnova.project-implementation-observation.v1",
                "overall_status": "complete",
                "source_manifest_sha256": _canonical_hash(observed_paths),
                "observation_snapshot_sha256": "0" * 64,
                "observed_paths": observed_paths,
                "records": [
                    {
                        "scope_id": observation_scope_id,
                        "repository_id": FRONTEND,
                        "language_id": "python",
                        "provider_id": "strixnova.python-static.v1",
                        "provider_version": "1",
                        "status": "complete",
                        "execution_mode": "builtin_static",
                        "configurations": ["default"],
                        "required_relation_kinds": ["source_import"],
                        "supported_relation_kinds": ["source_import"],
                        "observed_relation_kinds": [],
                        "source_file_count": 1,
                        "relation_count": 0,
                        "limitations": [],
                        "gaps": [],
                    }
                ],
                "provider_receipts": [
                    {
                        "scope_id": observation_scope_id,
                        "repository_id": FRONTEND,
                        "language_id": "python",
                        "provider_id": "strixnova.python-static.v1",
                        "provider_version": "1",
                        "execution_mode": "builtin_static",
                        "status": "complete",
                        "result_sha256": "0" * 64,
                    }
                ],
            },
            "artifact_paths": artifact_paths,
            "unresolved_items": [],
        },
        artifact_paths["source_ownership"]: {
            "schema_version": "strixnova.implementation-source-ownership.v1",
            **binding,
            "governed_source_scopes": [
                {
                    "scope_id": observation_scope_id,
                    "repository_id": FRONTEND,
                    "root": implementation_path,
                    "included_path_patterns": ["."],
                    "included_node_kinds": ["测试实现文件"],
                    "exclusion_policy": "隔离测试不隐式排除实现文件。",
                }
            ],
            "records": [
                {
                    "scope_id": observation_scope_id,
                    "repository_id": FRONTEND,
                    "path": implementation_path,
                    "sha256": implementation_sha256,
                    "language_id": "python",
                    "node_kind": "source_file",
                    "disposition": "owned",
                    "target_module_id": TEST_MODULE_ID,
                    "implementation_stage_id": TEST_STAGE_ID,
                    "current_status": "aligned",
                    "deviation_ids": [],
                    "rationale": "隔离测试实现归属测试应用模块。",
                }
            ],
        },
        artifact_paths["actual_dependencies"]: {
            "schema_version": "strixnova.implementation-actual-dependencies.v1",
            **binding,
            "observation_contract_version": "strixnova.project-implementation-observation.v1",
            "records": [],
        },
        artifact_paths["target_responsibilities"]: {
            "schema_version": "strixnova.implementation-target-responsibilities.v1",
            **binding,
            "records": [
                {
                    "target_kind": kind,
                    "target_id": target_id,
                    "status": "implemented",
                    "satisfied": ["隔离测试公开行为已建立。"],
                    "missing": [],
                    "evidence": evidence,
                    "deviation_ids": [],
                    "resolution_plan": [],
                }
                for kind, target_id in responsibilities
            ],
        },
        artifact_paths["deviations"]: {
            "schema_version": "strixnova.implementation-deviations.v1",
            **binding,
            "deviations": [],
        },
    }


def _domain_facts(*, full: bool) -> list[dict]:
    context = {
        "fact_id": TEST_CONTEXT_FACT_ID,
        "status": "confirmed",
        "title": "测试事项上下文",
        "kind": "bounded_context",
        "product_capability_ids": [TEST_CAPABILITY_ID],
        "scope_fact_ids": [],
        "dependency_fact_ids": [],
        "content": {
            "responsibility": "负责验证事项级工程治理。",
            "decisions": ["决定测试事项的确定性状态。"],
            "excluded_responsibilities": ["不决定项目产品语义。"],
        },
    }
    if not full:
        return [context]
    return [
        {
            "fact_id": TEST_TERM_FACT_ID,
            "status": "confirmed",
            "title": "建设事项",
            "kind": "term",
            "product_capability_ids": [TEST_CAPABILITY_ID],
            "scope_fact_ids": [TEST_CONTEXT_FACT_ID],
            "dependency_fact_ids": [],
            "content": {
                "term": "建设事项",
                "definition": "一次需要闭环管理的软件工程建设活动。",
            },
        },
        context,
        {
            "fact_id": TEST_INVARIANT_FACT_ID,
            "status": "confirmed",
            "title": "三个确认点",
            "kind": "domain_invariant",
            "product_capability_ids": [TEST_CAPABILITY_ID],
            "scope_fact_ids": [TEST_CONTEXT_FACT_ID],
            "dependency_fact_ids": [TEST_TERM_FACT_ID],
            "content": {
                "statement": "正式事项保持方向、方案和实际结果三个确认点。",
                "protected_fact_ids": [TEST_TERM_FACT_ID, TEST_CONTEXT_FACT_ID],
            },
        },
    ]


def _write_authorities(
    project: Path,
    *,
    full_domain: bool,
    implementation_path: str,
    verification_path: str | None,
    ddd_status: str,
) -> dict[str, str]:
    implementation_file = project / implementation_path
    if not implementation_file.exists():
        implementation_file.parent.mkdir(parents=True, exist_ok=True)
        implementation_file.write_text("VALUE = 1\n", encoding="utf-8")
    if verification_path is not None:
        verification_file = project / verification_path
        if not verification_file.exists():
            verification_file.parent.mkdir(parents=True, exist_ok=True)
            verification_file.write_text(
                "def test_placeholder():\n    assert True\n",
                encoding="utf-8",
            )
    product_path = "docs/product/definition.yaml"
    policy_path = "docs/engineering/policy.yaml"
    architecture_path = "docs/architecture/model.yaml"
    alignment_path = "docs/engineering/alignment.yaml"
    domain_facts = _domain_facts(full=full_domain)
    domain_documents, model_path, source_path = _domain_documents(
        domain_facts=domain_facts
    )
    values: dict[str, dict] = {
        product_path: _product_document(),
        policy_path: _policy_document(ddd_status=ddd_status),
        **domain_documents,
        **_architecture_documents(
            architecture_path,
            domain_fact_ids=[item["fact_id"] for item in domain_facts],
        ),
        **_alignment_documents(
            alignment_path,
            implementation_path=implementation_path,
            implementation_sha256=hashlib.sha256(
                implementation_file.read_bytes()
            ).hexdigest(),
            verification_path=verification_path,
        ),
    }
    for relative_path, value in values.items():
        _write_yaml(project, relative_path, value)
    return {
        "product_path": product_path,
        "model_id": TEST_DOMAIN_MODEL_ID,
        "model_revision_id": TEST_DOMAIN_REVISION_ID,
        "term_fact_id": TEST_TERM_FACT_ID,
        "context_fact_id": TEST_CONTEXT_FACT_ID,
        "invariant_fact_id": TEST_INVARIANT_FACT_ID,
        "alignment_id": TEST_ALIGNMENT_ID,
        "alignment_revision_id": TEST_ALIGNMENT_REVISION_ID,
        "model_path": model_path,
        "source_path": source_path,
        "architecture_path": architecture_path,
        "alignment_path": alignment_path,
        "policy_path": policy_path,
        "module_id": TEST_MODULE_ID,
    }


def portable_project_baseline(
    project_root: Path,
    *,
    baseline_id: str,
    artifacts: list[dict],
) -> dict:
    """Return a narrow baseline and write its independent test authorities."""

    del artifacts
    identities = _write_authorities(
        project_root,
        full_domain=False,
        implementation_path="src.py",
        verification_path=None,
        ddd_status="not_assessed",
    )
    baseline = {
        "schema_version": "strixnova.project-engineering-baseline.v1",
        "baseline_id": _stable_id("BASELINE", baseline_id),
        "project": {
            "project_id": "PROJECT-1111111111111111",
            "title": "隔离测试项目",
            "owner_id": TEST_OWNER_ID,
        },
        "authority_refs": {
            "product_definition": {
                "path": identities["product_path"],
                "product_id": TEST_PRODUCT_ID,
                "revision_id": TEST_PRODUCT_REVISION_ID,
                "status": {"revision_status": "confirmed", "adoption_status": "current"},
            },
            "domain_model": {
                "path": identities["model_path"],
                "model_id": TEST_DOMAIN_MODEL_ID,
                "revision_id": TEST_DOMAIN_REVISION_ID,
                "status": {"revision_status": "confirmed", "adoption_status": "current"},
            },
            "target_architecture": {
                "path": identities["architecture_path"],
                "architecture_id": TEST_ARCHITECTURE_ID,
                "revision_id": TEST_ARCHITECTURE_REVISION_ID,
                "status": {"revision_status": "confirmed", "adoption_status": "current"},
            },
            "engineering_policy": {
                "path": identities["policy_path"],
                "policy_id": TEST_POLICY_ID,
                "revision_id": TEST_POLICY_REVISION_ID,
                "status": {"revision_status": "confirmed", "adoption_status": "current"},
            },
            "implementation_alignment": {
                "path": identities["alignment_path"],
                "alignment_model_id": TEST_ALIGNMENT_ID,
                "revision_id": TEST_ALIGNMENT_REVISION_ID,
                "status": {"revision_status": "confirmed", "adoption_status": "current"},
            },
        },
        "current_architecture_stage_id": TEST_STAGE_ID,
        "code_version": {"repositories": [{"repository_id": FRONTEND, "base_commit": "0" * 40, "worktree_state": "dirty"}]},
        "review_state": {
            "required": True,
            "reasons": ["隔离测试基线尚未绑定最终提交。"],
            "affected_authority_kinds": ["implementation_alignment", "code_version"],
        },
    }
    for reference in baseline["authority_refs"].values():
        reference["repository_id"] = FRONTEND
        reference["ref"] = None
    configure_repository(project_root, project_id=baseline["project"]["project_id"], repository_id=FRONTEND)
    return baseline


def adopt_portable_ddd(
    project: Path,
    baseline: dict,
    *,
    implementation_path: str = "src.py",
    verification_path: str | None = None,
) -> dict[str, str]:
    """Replace the test authorities with a complete adopted DDD model."""

    identities = _write_authorities(
        project,
        full_domain=True,
        implementation_path=implementation_path,
        verification_path=verification_path,
        ddd_status="adopted",
    )
    baseline["authority_refs"]["domain_model"]["path"] = identities["model_path"]
    baseline["authority_refs"]["target_architecture"]["path"] = identities[
        "architecture_path"
    ]
    baseline["authority_refs"]["engineering_policy"]["path"] = identities[
        "policy_path"
    ]
    baseline["authority_refs"]["implementation_alignment"]["path"] = identities[
        "alignment_path"
    ]
    return identities


__all__ = [
    "TEST_ALIGNMENT_ID",
    "TEST_ALIGNMENT_REVISION_ID",
    "TEST_CONTEXT_FACT_ID",
    "TEST_DOMAIN_MODEL_ID",
    "TEST_DOMAIN_REVISION_ID",
    "TEST_INVARIANT_FACT_ID",
    "TEST_MODULE_ID",
    "TEST_TERM_FACT_ID",
    "adopt_portable_ddd",
    "portable_project_baseline",
]
