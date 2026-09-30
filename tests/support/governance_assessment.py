from copy import deepcopy
from pathlib import Path
import sys

from strixnova.engineering_governance import IMPACT_DIMENSIONS
from tests.support.project_baseline import (
    TEST_ALIGNMENT_ID,
    TEST_ARCHITECTURE_ID,
    TEST_DOMAIN_MODEL_ID,
    TEST_POLICY_ID,
    TEST_PRODUCT_ID,
)


DEFAULT_WORK_ITEM_ID = "WI-TEST-001"
DEFAULT_DIRECTION_VERSION = 3


def refresh_single_slice(
    assessment: dict,
    *,
    purpose: str = "完成当前工程方案中的全部文件操作并取得验证证据。",
) -> dict:
    """Keep broad lifecycle fixtures focused on one complete implementation slice."""

    operations = list(assessment.get("operations") or [])
    commands = list(assessment.get("verification_commands") or [])
    if commands:
        constraint = "direction.constraint:DIRCON-2222222222222222"
        if not any(constraint in command.get("covers", []) for command in commands):
            # The fixture's sole constraint is use of the project interpreter;
            # that is observable in this explicitly selected command execution.
            commands[0]["covers"].append(constraint)
    if assessment.get("change_context", {}).get("formal_implementation") is not True:
        assessment.pop("implementation_slices", None)
        return assessment
    assessment["implementation_slices"] = [
        {
            "schema_version": "strixnova.implementation-slice.v1",
            "slice_id": "SLICE-001",
            "purpose": purpose,
            "implements": ["design_decisions[0]"],
            "operation_refs": [
                f"operations[{index}]" for index, _ in enumerate(operations)
            ],
            "depends_on": [],
            "parallel_safe_with": [],
            "completion_criteria": ["计划文件操作全部完成且验证取得当前回执。"],
            "verification_command_refs": [
                f"verification_commands[{index}]"
                for index, _ in enumerate(commands)
            ],
            "rollback_or_recovery": "验证失败时保留未提交改动并修正当前切片。",
        }
    ]
    return assessment


def semantic_review_fixture(*evidence_refs: str) -> dict:
    reviewed = list(evidence_refs) or ["direction"]
    perspectives = (
        "product_to_domain_coverage",
        "terminology_authority_rules_invariants",
        "domain_to_architecture_disposition",
        "plan_and_slice_coverage",
        "orphan_and_authority_inversion",
        "scenario_coverage",
        "nonfunctional_and_risk_coverage",
        "evidence_and_claim_boundaries",
    )
    return {
        "schema_version": "strixnova.semantic-review.v1",
        "review_id": "SEMREVIEW-1111111111111111",
        "reviewed_refs": reviewed,
        "checks": [
            {
                "perspective": perspective,
                "status": "aligned",
                "summary": f"已从 {perspective} 视角完成只读审查，未保留阻断发现。",
                "evidence_refs": reviewed,
                "finding_ids": [],
            }
            for perspective in perspectives
        ],
        "findings": [],
        "question_budget": {
            "maximum_questions": 5,
            "questions_asked": 0,
            "resolved_decision_refs": [],
            "remaining_high_impact_decisions": [],
        },
        "semantic_content_machine_proven": False,
    }


def direction_fixture() -> dict:
    return {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
        "goal": "缩短测试反馈，同时保留必要行为覆盖。",
        "scope": [
            {
                "requirement_id": "DIRREQ-1111111111111111",
                "statement": "优化当前项目的测试结构。",
            }
        ],
        "non_goals": ["不删除具有独立行为价值的测试。"],
        "constraints": [
            {
                "constraint_id": "DIRCON-2222222222222222",
                "statement": "只使用项目 Python 3.12 venv。",
            }
        ],
        "tradeoffs": ["优先减少重复验证，不设置人为耗时门槛。"],
        "acceptance": [
            {
                "acceptance_id": "DIRACC-3333333333333333",
                "statement": "快速与全量套件都报告真实耗时和覆盖。",
                "requirement_refs": ["DIRREQ-1111111111111111"],
                "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
            }
        ],
    }


def bind_assessment_to_work_item(assessment: dict, item: dict) -> dict:
    assessment["direction_ref"] = {
        "work_item_id": item["work_item_id"],
        "direction_version": item["data"]["direction_confirmation"][
            "direction_version"
        ],
    }
    authority_change_set = assessment.get("authority_change_set")
    if isinstance(authority_change_set, dict):
        authority_change_set["work_item_id"] = item["work_item_id"]
    return assessment


def assessment_fixture(
    project: Path,
    *,
    work_item_id: str = DEFAULT_WORK_ITEM_ID,
    direction_version: int = DEFAULT_DIRECTION_VERSION,
) -> dict:
    source = project / "src.py"
    source.write_text("def value():\n    return 1\n", encoding="utf-8")
    assessment = {
        "schema_version": "strixnova.engineering-assessment.v1",
        "assessment_id": "EA-TEST-001",
        "assessment_revision": 1,
        "direction_ref": {
            "work_item_id": work_item_id,
            "direction_version": direction_version,
        },
        "investigation_ref": "working_tree",
        "change_context": {
            "change_kind": "modify_existing",
            "formal_implementation": True,
        },
        "source_references": [
            {
                "reference_id": "SRC-001",
                "path": "src.py",
                "line_start": 1,
                "line_end": 2,
                "observed_ref": "working_tree",
                "epistemic_status": "observed",
            }
        ],
        "impact_scope": {
            "affected": [
                {
                    "dimension": dimension,
                    "reason": f"当前源码证明 {dimension} 会发生实际变化。",
                    "evidence_refs": ["SRC-001"],
                }
                for dimension in ("user_behavior", "testing")
            ],
            "unknown": [],
            "unaffected": [
                dimension
                for dimension in IMPACT_DIMENSIONS
                if dimension not in {"user_behavior", "testing"}
            ],
        },
        "method_applications": [],
        "risk_assessments": [
            {
                "statement": "错误去重可能遗漏必要回归覆盖。",
                "likelihood": "low",
                "consequence": "low",
                "reversibility": "easy",
                "uncertainty": "low",
                "external_assurance_required": False,
                "mitigation": "保留最低有效层行为验证。",
                "evidence_refs": ["SRC-001"],
            }
        ],
        "alternatives_and_tradeoffs": [],
        "design_decisions": [
            {
                "statement": "在最低有效测试层保留一次行为证明。",
                "rationale": "避免重复组合，同时保留独立行为覆盖。",
                "evidence_refs": ["SRC-001"],
            }
        ],
        "operations": [
            {
                "action": "modify",
                "path": "src.py",
                "reason": "修改测试分组并删除重复组合。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
            }
        ],
        "adr_plans": [],
        "verification_commands": [
            {
                "argv": [
                    ".venv/Scripts/python.exe",
                    "-m",
                    "pytest",
                    "tests/unit/test_workflow_authority.py",
                    "-q",
                ],
                "cwd": ".",
                "run_kind": "targeted_test",
                "covers": [
                    "direction.acceptance:DIRACC-3333333333333333",
                    "risk_assessments[0]",
                ],
                "reason": "直接验证本次验收并保护回归风险。",
            }
        ],
        "delivery_plan": {
            "expected_outcome": "用户确认实际结果后形成原子提交并本地合入。",
            "rollback_or_recovery": "未确认前保留未提交改动，确认后由 Git 回退。",
            "limitations": [],
            "evidence_refs": ["direction"],
        },
        "unknowns_and_limitations": [],
        "requested_assurance": {
            "band": "A1",
            "reason": "局部、可逆且具备针对性验证。",
        },
        "owner_view": {
            "schema_version": "strixnova.owner-view.v1",
            "decision_support": {
                "current_problem": "缩短测试反馈，同时保留必要行为覆盖。",
                "why_it_matters": "反馈过慢会增加建设成本，错误去重又可能漏掉回归。",
                "impact": "只调整本事项声明的测试结构，不改变产品和领域行为。",
                "recommendation": "采用单切片调整并运行针对性验证。",
                "alternatives": ["保留现状并接受较慢反馈。"],
                "no_action_consequence": "继续承担当前测试反馈成本。",
                "next_step": "确认方案后执行唯一实施切片。",
                "necessary_questions": [],
            },
            "engineering_context": {
                "product_and_domain_change": "产品范围和领域含义不变。",
                "architecture_responsibilities": "保持现有职责，只调整测试结构。",
                "implementation_order": "用一个实施切片完成源码调整，再执行针对性验证。",
                "highest_impact_risks": "错误去重可能遗漏必要回归覆盖。",
                "verification_and_observation": "运行已列出的针对性测试并保存真实回执。",
                "uncertainties": "没有仍会改变方案方向的未知。",
            },
            "current_decision": "是否接受本工程方案并允许进入实施。",
            "semantic_content_machine_proven": False,
        },
    }
    return refresh_single_slice(assessment)


def new_project_adr_assessment(
    project: Path,
    *,
    adr_id: str = "ADR-0100",
) -> dict:
    assessment = assessment_fixture(project)
    assessment["assessment_id"] = "EA-NEW-PROJECT-ADR"
    assessment["change_context"] = {
        "change_kind": "create_project",
        "formal_implementation": True,
        "project_engineering_baseline_path": "docs/engineering/baseline.yaml",
        "project_product_definition_path": "docs/product/definition.yaml",
        "project_domain_model_path": "docs/domain/model.yaml",
        "project_architecture_description_path": "docs/architecture/model.yaml",
        "project_engineering_policy_path": "docs/engineering/policy.yaml",
        "project_implementation_alignment_path": "docs/engineering/alignment.yaml",
    }
    assessment["risk_assessments"][0].update(
        {
            "statement": "权威引用或 ADR 身份不一致会让后续智能编码代理读取错误事实。",
            "consequence": "high",
            "reversibility": "difficult",
            "mitigation": "同时验证项目配置、精确权威引用和 ADR 元数据。",
        }
    )
    assessment["alternatives_and_tradeoffs"] = [
        {
            "option": "把长期事实复制进 Authority",
            "disposition": "rejected",
            "reason": "Git 已能管理长期文件、历史和合并。",
            "tradeoffs": "避免双份事实，但后续读取必须遵循项目基线。",
            "evidence_refs": ["SRC-001"],
        }
    ]
    assessment["design_decisions"] = [
        {
            "statement": "项目配置定位工程基线，基线精确锚定五类正式权威。",
            "rationale": "产品、领域、架构、政策和实现对齐各自定档并由 Git 追溯。",
            "evidence_refs": ["SRC-001"],
        }
    ]
    adr_path = f"docs/adr/{adr_id}-initial-architecture.md"
    assessment["operations"] = [
        {
            "action": "create",
            "path": "strixnova-project.yaml",
            "reason": "创建项目工程基线定位配置。",
            "evidence_refs": ["direction"],
            "implements": ["design_decisions[0]"],
        },
        {
            "action": "create",
            "path": "docs/engineering/baseline.yaml",
            "reason": "创建可校验的项目工程基线。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
        },
        {
            "action": "create",
            "path": "docs/product/definition.yaml",
            "reason": "创建独立项目产品定义。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": TEST_PRODUCT_ID,
                "artifact_type": "product_governance",
            },
        },
        {
            "action": "create",
            "path": "docs/domain/model.yaml",
            "reason": "创建独立项目领域模型。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": TEST_DOMAIN_MODEL_ID,
                "artifact_type": "domain_model",
            },
        },
        {
            "action": "create",
            "path": "docs/architecture/model.yaml",
            "reason": "创建正式项目目标架构。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": TEST_ARCHITECTURE_ID,
                "artifact_type": "architecture",
            },
        },
        {
            "action": "create",
            "path": "docs/engineering/policy.yaml",
            "reason": "创建项目工程政策并记录方法采用状态。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": TEST_POLICY_ID,
                "artifact_type": "quality_policy",
            },
        },
        {
            "action": "create",
            "path": "docs/engineering/alignment.yaml",
            "reason": "创建完整项目实现对齐权威。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": TEST_ALIGNMENT_ID,
                "artifact_type": "domain_alignment",
            },
        },
        {
            "action": "create",
            "path": adr_path,
            "reason": "创建并索引初始化架构决定。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": adr_id,
                "artifact_type": "adr",
            },
        },
    ]
    for path in (
        "docs/domain/collections/core.yaml",
        "docs/domain/sources/core.yaml",
        "docs/architecture/architecture-modules.yaml",
        "docs/architecture/architecture-relationships.yaml",
        "docs/architecture/architecture-constraints.yaml",
        "docs/architecture/architecture-domain-facts.yaml",
        "docs/architecture/architecture-stages.yaml",
        "docs/engineering/source-ownership.yaml",
        "docs/engineering/actual-dependencies.yaml",
        "docs/engineering/target-responsibilities.yaml",
        "docs/engineering/deviations.yaml",
    ):
        assessment["operations"].append(
            {
                "action": "create",
                "path": path,
                "reason": "创建正式权威的完整从属产物。",
                "evidence_refs": ["SRC-001"],
                "implements": ["design_decisions[0]"],
            }
        )
    assessment["adr_plans"] = [
        {
            "disposition": "create",
            "reason": "首个项目基线及长期存储边界需要形成 ADR。",
            "evidence_refs": ["SRC-001"],
            "artifact_id": adr_id,
            "path": adr_path,
        }
    ]
    affected = {
        "product_scope",
        "domain",
        "architecture",
        "testing",
        "documentation_support",
    }
    assessment["impact_scope"] = {
        "affected": [
            {
                "dimension": dimension,
                "reason": f"新项目初始化会改变 {dimension}。",
                "evidence_refs": ["SRC-001"],
            }
            for dimension in IMPACT_DIMENSIONS
            if dimension in affected
        ],
        "unknown": [],
        "unaffected": [
            dimension
            for dimension in IMPACT_DIMENSIONS
            if dimension not in affected
        ],
    }
    assessment["verification_commands"] = [
        {
            "argv": [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "from strixnova.project_authority_consistency import "
                    "ProjectAuthorityConsistency; "
                    "state=ProjectAuthorityConsistency('.').load(); "
                    "assert state['structurally_consistent']; "
                    "assert len(state['baseline']['authority_refs']) == 5; "
                    f"assert Path('docs/adr/{adr_id}-initial-architecture.md').is_file()"
                ),
            ],
            "cwd": ".",
            "run_kind": "acceptance_test",
            "covers": [
                "direction.acceptance:DIRACC-3333333333333333",
                "risk_assessments[0]",
            ],
            "reason": "直接从未提交工作树验证首个基线和 ADR。",
        }
    ]
    assessment["requested_assurance"] = {
        "band": "A3",
        "reason": "新项目长期架构事实需要较强保障。",
    }
    assessment["method_applications"] = [
        {
            "method_id": "ddd",
            "decision": "considered_not_applied",
            "purpose": "明确记录该隔离测试项目尚未决定采用 DDD。",
            "evidence_refs": ["SRC-001", "direction"],
            "baseline_refs": [],
            "domain_fact_refs": [],
            "planned_uses": [],
            "adoption_change": {
                "from_status": None,
                "to_status": "not_assessed",
                "reason": "初始化事项缺少足够领域事实，不伪造 DDD 采用结论。",
                "conditions": [],
            },
        }
    ]
    assessment["semantic_review"] = semantic_review_fixture("SRC-001")
    assessment["owner_view"]["decision_support"].update(
        {
            "current_problem": "建立新项目首套完整长期权威和初始化架构决定。",
            "why_it_matters": "没有完整权威链，后续建设无法稳定判断目标和责任。",
            "impact": "首次建立产品、领域、架构、政策、实现对齐和工程基线。",
            "recommendation": "一次建立完整权威链并验证精确引用。",
            "alternatives": ["保持非正式项目并暂不进入正式实施。"],
            "no_action_consequence": "后续实现没有可确认的上游目标和架构基线。",
            "next_step": "确认工程方案后按前置治理顺序建立候选。",
            "necessary_questions": [],
        }
    )
    assessment["owner_view"]["engineering_context"].update(
        {
            "product_and_domain_change": "首次形成产品定义与完整领域模型，不使用差异变更集绕过建模。",
            "architecture_responsibilities": "首次形成目标架构及其领域事实处置。",
            "implementation_order": "先建立全部正式权威和从属产物，再执行结构一致性验收。",
            "highest_impact_risks": "权威身份、引用或架构决定不一致会污染后续建设。",
            "verification_and_observation": "从未提交工作树读取完整权威链并验证架构决定存在。",
            "uncertainties": "领域方法采用仍明确保留为未评估，不伪造结论。",
        }
    )
    return refresh_single_slice(
        assessment,
        purpose="一次建立新项目首套完整权威及其从属产物。",
    )


def add_capability_adr_assessment(
    project: Path,
    *,
    baseline: dict,
    observed_commit: str,
    adr_id: str = "ADR-0200",
) -> dict:
    assessment = assessment_fixture(project)
    capability_id = "CAPABILITY-2222222222222222"
    fact_id = "FACT-4444444444444444"
    product_ref = baseline["authority_refs"]["product_definition"]
    domain_ref = baseline["authority_refs"]["domain_model"]
    architecture_ref = baseline["authority_refs"]["target_architecture"]
    policy_ref = baseline["authority_refs"]["engineering_policy"]
    alignment_ref = baseline["authority_refs"]["implementation_alignment"]
    assessment["assessment_id"] = "EA-ADD-PUBLIC-CAPABILITY"
    assessment["change_context"] = {
        "change_kind": "add_capability",
        "formal_implementation": True,
    }
    assessment["source_references"].extend(
        [
            {
                "reference_id": "SRC-PROJECT-CONFIG",
                "path": "strixnova-project.yaml",
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
            {
                "reference_id": "SRC-PROJECT-BASELINE",
                "path": "docs/engineering/baseline.yaml",
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
            {
                "reference_id": "SRC-PRODUCT-AUTHORITY",
                "path": product_ref["path"],
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
            {
                "reference_id": "SRC-DOMAIN-AUTHORITY",
                "path": "docs/domain/sources/core.yaml",
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
            {
                "reference_id": "SRC-ARCHITECTURE-AUTHORITY",
                "path": architecture_ref["path"],
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
            {
                "reference_id": "SRC-POLICY-AUTHORITY",
                "path": policy_ref["path"],
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
            {
                "reference_id": "SRC-ALIGNMENT-AUTHORITY",
                "path": alignment_ref["path"],
                "observed_ref": observed_commit,
                "epistemic_status": "observed",
            },
        ]
    )
    assessment["risk_assessments"][0].update(
        {
            "statement": "公开接口缺少长期决定可能破坏调用方预期。",
            "consequence": "high",
            "reversibility": "difficult",
            "mitigation": "接口说明、基线关系和 ADR 一起验证。",
            "evidence_refs": ["SRC-PROJECT-BASELINE"],
        }
    )
    assessment["alternatives_and_tradeoffs"] = [
        {
            "option": "只新增临时函数，不建立长期接口边界",
            "disposition": "rejected",
            "reason": "公开能力需要让后续调用方获得稳定预期。",
            "tradeoffs": "增加少量长期文档，但降低未来破坏性修改风险。",
            "evidence_refs": ["SRC-001", "SRC-PROJECT-BASELINE"],
        }
    ]
    assessment["design_decisions"] = [
        {
            "statement": "新增最小公开函数，并用接口说明和 ADR 固化边界。",
            "rationale": "实现、公开约定和长期决定保持可追溯。",
            "evidence_refs": ["SRC-001", "SRC-PROJECT-BASELINE"],
        }
    ]
    adr_path = f"docs/adr/{adr_id}-public-capability.md"
    assessment["operations"] = [
        {
            "action": "modify",
            "path": "src.py",
            "reason": "在现有行为根中实现公开读取能力。",
            "evidence_refs": ["SRC-001"],
            "implements": ["design_decisions[0]"],
        },
        {
            "action": "create",
            "path": "docs/public-interface.md",
            "reason": "创建长期公开接口说明。",
            "evidence_refs": ["SRC-PROJECT-BASELINE"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": "IFACE-001",
                "artifact_type": "interface",
            },
        },
        {
            "action": "modify",
            "path": "docs/engineering/baseline.yaml",
            "reason": "更新项目工程基线中的精确权威引用。",
            "evidence_refs": ["SRC-PROJECT-BASELINE"],
            "implements": ["design_decisions[0]"],
        },
        {
            "action": "create",
            "path": adr_path,
            "reason": "创建公开能力架构决定。",
            "evidence_refs": ["SRC-PROJECT-BASELINE"],
            "implements": ["design_decisions[0]"],
            "long_lived_artifact": {
                "artifact_id": adr_id,
                "artifact_type": "adr",
            },
        },
    ]
    authority_operations = (
        (product_ref, "product_id", "product_governance"),
        (domain_ref, "model_id", "domain_model"),
        (architecture_ref, "architecture_id", "architecture"),
        (alignment_ref, "alignment_model_id", "domain_alignment"),
    )
    for reference, identity_field, artifact_type in authority_operations:
        assessment["operations"].append(
            {
                "action": "modify",
                "path": reference["path"],
                "reason": "更新新增能力涉及的正式权威修订。",
                "evidence_refs": ["SRC-PROJECT-BASELINE"],
                "implements": ["design_decisions[0]"],
                "long_lived_artifact": {
                    "artifact_id": reference[identity_field],
                    "artifact_type": artifact_type,
                },
            }
        )
    for path in (
        "docs/domain/collections/core.yaml",
        "docs/domain/sources/core.yaml",
        "docs/architecture/architecture-modules.yaml",
        "docs/architecture/architecture-relationships.yaml",
        "docs/architecture/architecture-constraints.yaml",
        "docs/architecture/architecture-domain-facts.yaml",
        "docs/architecture/architecture-stages.yaml",
        "docs/engineering/source-ownership.yaml",
        "docs/engineering/actual-dependencies.yaml",
        "docs/engineering/target-responsibilities.yaml",
        "docs/engineering/deviations.yaml",
    ):
        assessment["operations"].append(
            {
                "action": "modify",
                "path": path,
                "reason": "同步正式权威修订绑定和完整实现对齐底账。",
                "evidence_refs": ["SRC-PROJECT-BASELINE"],
                "implements": ["design_decisions[0]"],
            }
        )
    assessment["domain_fact_changes"] = [
        {
            "disposition": "add",
            "target_ref": {
                "schema_version": "strixnova.domain-fact-reference.v1",
                "authority_kind": "project_domain_model",
                "model_id": domain_ref["model_id"],
                "fact_id": fact_id,
                "observed_commit": observed_commit,
            },
            "source_path": "docs/domain/sources/core.yaml",
            "reason": "为新增公开读取能力建立正式领域术语。",
            "evidence_refs": [
                "SRC-PRODUCT-AUTHORITY",
                "SRC-DOMAIN-AUTHORITY",
            ],
            "lineage": [],
        }
    ]
    assessment["adr_plans"] = [
        {
            "disposition": "create",
            "reason": "新增公共接口改变长期架构边界。",
            "evidence_refs": ["SRC-PROJECT-BASELINE"],
            "artifact_id": adr_id,
            "path": adr_path,
        }
    ]
    affected = {
        "user_behavior",
        "product_scope",
        "domain",
        "architecture",
        "interface",
        "testing",
        "documentation_support",
    }
    assessment["impact_scope"] = {
        "affected": [
            {
                "dimension": dimension,
                "reason": f"公开能力会改变 {dimension}。",
                "evidence_refs": [
                    "SRC-PROJECT-BASELINE"
                    if dimension in {"architecture", "interface"}
                    else "SRC-001"
                ],
            }
            for dimension in IMPACT_DIMENSIONS
            if dimension in affected
        ],
        "unknown": [],
        "unaffected": [
            dimension
            for dimension in IMPACT_DIMENSIONS
            if dimension not in affected
        ],
    }
    assessment["verification_commands"] = [
        {
            "argv": [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; "
                    "from strixnova.project_authority_consistency import "
                    "ProjectAuthorityConsistency; "
                    "assert 'def read_value' in "
                    "Path('src.py').read_text(); "
                    "state=ProjectAuthorityConsistency('.')."
                    f"load_working_tree_candidate_for('{observed_commit}'); "
                    "assert state['structurally_consistent']; "
                    f"assert any(item['capability_id']=='{capability_id}' "
                    "for item in state['product_definition']['capabilities']); "
                    f"assert Path('docs/adr/{adr_id}-public-capability.md').is_file()"
                ),
            ],
            "cwd": ".",
            "run_kind": "acceptance_test",
            "covers": [
                "direction.acceptance:DIRACC-3333333333333333",
                "risk_assessments[0]",
            ],
            "reason": "跨源码与长期工程文件验证新增公开能力及 ADR。",
        }
    ]
    assessment["requested_assurance"] = {
        "band": "A3",
        "reason": "公共接口和长期架构边界变化要求较强保障。",
    }
    authority_rows = (
        (
            "product_definition",
            product_ref,
            "product_id",
            "REVISION-5555555555555555",
        ),
        (
            "domain_model",
            domain_ref,
            "model_id",
            "MODELREV-2222222222222222",
        ),
        (
            "target_architecture",
            architecture_ref,
            "architecture_id",
            "ARCHREV-3333333333333333",
        ),
        (
            "implementation_alignment",
            alignment_ref,
            "alignment_model_id",
            "ALIGNREV-4444444444444444",
        ),
    )
    assessment["authority_change_set"] = {
        "schema_version": "strixnova.authority-change-set.v1",
        "change_set_id": "AUTHCHANGE-1111111111111111",
        "work_item_id": assessment["direction_ref"]["work_item_id"],
        "base_authorities": [
            {
                "authority_kind": kind,
                "artifact_id": reference[identity_field],
                "revision_id": reference["revision_id"],
                "path": reference["path"],
                "status": "confirmed",
                "observed_commit": observed_commit,
            }
            for kind, reference, identity_field, _candidate_revision in authority_rows
        ],
        "candidate_authorities": [
            {
                "authority_kind": kind,
                "artifact_id": reference[identity_field],
                "revision_id": candidate_revision,
                "path": reference["path"],
                "status": "draft",
                "supersedes_revision_id": reference["revision_id"],
                "adoption_effect": "not_adopted",
            }
            for kind, reference, identity_field, candidate_revision in authority_rows
        ],
        "changes": [
            {
                "change_id": f"AUTHOP-{index:03d}",
                "authority_kind": kind,
                "operation": (
                    "add"
                    if kind in {"product_definition", "domain_model"}
                    else "modify"
                ),
                "target_ref": (
                    capability_id
                    if kind == "product_definition"
                    else fact_id
                    if kind == "domain_model"
                    else reference[identity_field]
                ),
                "summary": "为新增公开读取能力补齐该层长期权威含义。",
                "evidence_refs": ["SRC-PROJECT-BASELINE"],
            }
            for index, (
                kind,
                reference,
                identity_field,
                _candidate_revision,
            ) in enumerate(authority_rows, start=1)
        ],
        "downstream_dispositions": [
            {
                "source_authority_kind": source,
                "target_authority_kind": target,
                "disposition": "revise",
                "reason": "上游新增能力需要在该下游权威中形成精确承载或对齐。",
            }
            for source, targets in (
                (
                    "product_definition",
                    (
                        "domain_model",
                        "target_architecture",
                        "implementation_alignment",
                    ),
                ),
                (
                    "domain_model",
                    ("target_architecture", "implementation_alignment"),
                ),
                ("target_architecture", ("implementation_alignment",)),
            )
            for target in targets
        ],
        "semantic_content_machine_proven": False,
    }
    assessment["semantic_review"] = semantic_review_fixture(
        "SRC-PROJECT-BASELINE",
        "authority_change_set",
    )
    assessment["owner_view"]["decision_support"].update(
        {
            "current_problem": "增加可追溯的公开读取能力。",
            "why_it_matters": "缺少稳定读取会迫使使用者猜测权威和状态。",
            "impact": "产品、领域、架构和实现对齐同步增加对应能力。",
            "recommendation": "按完整权威链修订并通过公开接口验收。",
            "alternatives": ["保留现状并继续依赖人工读取。"],
            "no_action_consequence": "权威查询继续不可稳定追溯。",
            "next_step": "确认方案后先更新权威候选。",
            "necessary_questions": [],
        }
    )
    assessment["owner_view"]["engineering_context"].update(
        {
            "product_and_domain_change": "产品能力和领域事实均新增对应含义，并以权威变更集固定差异。",
            "architecture_responsibilities": "现有目标架构增加明确接口承载并同步实现对齐。",
            "implementation_order": "先更新完整权威候选，再实现接口和验证，最后登记对齐结果。",
            "highest_impact_risks": "公开接口与长期权威不一致会形成新的权威污染。",
            "verification_and_observation": "跨源码、权威结构与架构决定执行一次验收。",
            "uncertainties": "只读语义审查没有遗留高影响决定，但语义未由机器证明。",
        }
    )
    return refresh_single_slice(
        assessment,
        purpose="更新完整长期权威链并实现新增公开读取能力。",
    )


def exploration_assessment(project: Path) -> dict:
    assessment = assessment_fixture(project)
    assessment["assessment_id"] = "EA-EXPLORATION-001"
    assessment["change_context"] = {
        "change_kind": "exploration",
        "formal_implementation": False,
    }
    for optional in (
        "source_references",
        "risk_assessments",
        "alternatives_and_tradeoffs",
        "design_decisions",
        "operations",
        "adr_plans",
        "verification_commands",
        "implementation_slices",
        "delivery_plan",
        "unknowns_and_limitations",
    ):
        assessment.pop(optional, None)
    assessment["impact_scope"] = {
        "affected": [],
        "unknown": [],
        "unaffected": list(IMPACT_DIMENSIONS),
    }
    assessment["verification_not_required_reason"] = (
        "本事项不改变项目文件或行为，没有需要执行的验证命令。"
    )
    assessment["requested_assurance"] = {
        "band": "A0",
        "reason": "只读调查，不形成仓库操作。",
    }
    assessment["owner_view"]["decision_support"].update(
        {
            "current_problem": "完成只读调查并如实报告现状。",
            "why_it_matters": "需要区分已观察事实与尚未确认推断。",
            "impact": "不改变仓库文件、产品范围或领域含义。",
            "recommendation": "保留只读范围并明确报告限制。",
            "alternatives": ["另开正式实施事项处理发现。"],
            "no_action_consequence": "当前未知继续存在且不形成实施结论。",
            "next_step": "审阅调查结果并决定是否另开建设事项。",
            "necessary_questions": [],
        }
    )
    assessment["owner_view"]["engineering_context"].update(
        {
            "product_and_domain_change": "不改变产品范围或领域含义。",
            "architecture_responsibilities": "不改变目标架构责任。",
            "implementation_order": "只读取证据并形成报告，不实施仓库变更。",
            "highest_impact_risks": "不得把调查推断冒充已经实施。",
            "verification_and_observation": "没有适用验证命令，并明确说明原因。",
            "uncertainties": "所有未确认内容保留为调查限制。",
        }
    )
    assessment["owner_view"]["current_decision"] = "是否接受该只读调查结果。"
    assessment["verification_reviews"] = [
        {"target_ref": ref, "method": "agent_review", "reason": "只读调查通过实际来源审阅说明结论，不执行项目代码。", "evidence_refs": ["direction"]}
        for ref in ("direction.acceptance:DIRACC-3333333333333333", "direction.constraint:DIRCON-2222222222222222")
    ]
    return assessment


def clone_assessment(assessment: dict) -> dict:
    return deepcopy(assessment)


def satisfied_governance_rule_results(
    plan: dict,
    evidence_ref: str,
) -> list[dict]:
    """Close every deterministic test-plan rule with one real test receipt."""

    return [
        {
            "rule_id": str(rule["rule_id"]),
            "status": "satisfied",
            "evidence_refs": [evidence_ref],
            "gaps": [],
            "remediation_actions": [],
            "limitations": [],
        }
        for rule in plan.get("applicable_rules") or []
    ]
