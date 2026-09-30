# 工程评估提交（中文审阅映射）

多成员项目在当前 v8 评估中声明 `repository_scope`：包含当前 `project_id` 和 `repositories`。每个所需仓库记录 `repository_id`、`role`（`modify` 或 `read`）、自己的 `investigation_ref`；修改仓库指定本地 `target_ref`，只读依赖的目标为空。无关成员可以不绑定；可确认方案所需的仓库必须可定位，正式方案须有各自不可变提交。外部依赖只可读取。

操作、来源、验证命令、带路径的 ADR 与领域事实变更、外部观察计划均按仓库身份限定；内部路径仍相对于各自仓库。仅在可选范围唯一时允许省略身份，程序在同一当前合同内补齐；没有声明的新项目保持未绑定身份，沿用首次建项流程，不伪造过去的归属。

多修改仓库的 `delivery_plan.repository_order` 必须恰好列出每个修改仓库一次。切片继续使用事项内唯一身份和操作引用，编译结果提供所涉及仓库。方向、方案和实际结果仍各有一个整体决定；需要提前独立交付的目标另立可独立接受的事项。

呈现整体结果前完成各计划仓库工作区及声明输入的验证；本地交付按已确认仓库顺序和 CurrentAction 继续，整体接受原则见主 Skill。

当前方案须逐项处置本方向的验收、约束和本轮风险。命令方式从 `verification_commands[].covers` 派生，一条命令可覆盖多项；其余每项目标在 `verification_reviews` 中只填一次。例如：

验收包含行为例子时，应对每个 `direction.example:DIREX-*` 安排核验，父验收结果从全部子例子派生。原生用例 `case_report` 绑定及显式替代方式见[行为例子与核验](behavior-examples.zh-CN.md)；只覆盖父验收不能代替子例子安排。

```json
{"target_ref":"direction.acceptance:DIRACC-0123456789ABCDEF","method":"agent_review","reason":"对照已确认业务规则审阅新说明。","evidence_refs":["SRC-001"]}
```

方式为 `agent_review`、`existing_evidence` 或 `not_verified`。审阅与复用必须引用已知依据，Agent 解释旧证据为什么仍适用；未核验安排须说明原因和后果，未修订方案前不能改称已获支持。遗漏在方案确认前被阻断。没有命令时仍写整体 `verification_not_required_reason`，但它不能代替逐项安排；语义审阅不必制造工具回执。计划提供派生的 `verification_targets`，绑定当次方案修订，不成为第二份可编辑目标清单。这些选择沿用已有确认点。

仅在 `CurrentAction.input_kind=engineering_assessment` 时读取本文件。`strixnova submit --input` 的载荷就是评估对象本身，不再套一层 `assessment`。使用合适工具调查；能够说明真实影响、计划操作、验证选择和重要未知后就停止。剩余不确定性放入 `unknowns_and_limitations`，不能为了“感觉完整”而遍历整个仓库。

实际影响需要跨产物审阅时，再使用后文 `semantic_review` 部分。每次评估读取必需核心，其余部分按所述影响条件选用；示例说明载荷结构，不是项目默认内容。

精确结构始终以 CurrentAction 返回的 `input_contract_ref` 为准；本文件示例只解释常见字段含义。示例与公开合同时若有差异，遵循合同并报告随包说明过期。

已确认 DirectionDecision 是目标、范围、非目标、约束、取舍和验收的唯一来源，评估不得重写。读取 CurrentAction 列出的记录，`direction_version` 取自已接受的 `direction_confirmation`，不是后来前进的 WorkItem 版本。

首次提交前明确检查五条边界：

1. 只要要修改或交付任何仓库文件，`change_context.formal_implementation=true`。false 只适用于明确受管但不交付仓库的结果，不是普通 Agent 调查模式。
2. 选择 change kind 前运行 `strixnova status`。调查提交没有已采用项目配置或工程基线，且事项会修改/交付仓库文件时，必须使用 `change_context.change_kind=create_project`，一次声明六个权威路径，并一起计划项目配置、工程基线和五类长期权威。只有不交付仓库的真实 A0 可保持未采用。
   Agent 调查并复用已有项目资料，负责人决定含义与重大取舍，不填写模板。内容须完整，深度与项目规模相称。后续事项复用有效权威，只更新受影响部分；PRD、SPEC 是按需形成的阅读产物，不是每次重新接入的要求。
3. 正式实施的 `investigation_ref` 指向配置仓库的真实不可变提交；`repository_scope` 另行绑定各所需仓库自己的调查提交，不得虚构调查标签。
4. 普通项目证据只使用 `direction` 或 `source_references` 中已声明的 `reference_id`。已采用项目还可使用 `project.engineering` 返回的精确 `baseline_refs`。不得把 `direction_confirmation`、裸路径或临时描述当 evidence ref。
5. `architecture`、`interface` 或 `data` 为 affected/unknown 时，必须有真实方案取舍、设计决定和 ADR 候选决定。

## 按需读取项目事实

先选择不可变 Git 调查提交，只读取 CurrentAction 列出的记录。现有正式项目先读 `project.engineering`，确定每种方法的 adopted/conditional 状态和已采用技术 ID。真正的新项目没有已采用 ProjectEngineeringBaseline，也不能虚构。

只有项目级治理缺口或标准边界实质影响本次评估时，才读可选的
`project.engineering.assurance`；它是下游证据，不是第六项长期权威，也不替代直接调查。只有方法采用与当前影响共同要求领域证据时，按以下顺序读取：

1. `project.domain.catalog`：Model 和根 Collection 路由元数据；
2. 沿已选 Collection 返回的精确 `record_ref` 逐层读取直接子级和 Source 选择；
3. 读取已选 Source 的精确 `record_ref` 获取 Fact 路由；
4. 读取 `project.domain.closure:<FACT-ID,...>` 获取显式依赖、上下文端点、范围不变量和全局事实；
5. 对每个确实需要的规范正文，读取 Source 返回的完整 Fact `record_ref`，不能缩成裸 Fact ID；
6. 只有受影响边界或实现主张需要时，才读 `project.architecture` 与 `project.domain.alignment`。

同一步已经知道且都必需的引用，在一次 `strixnova next` 中重复 `--record` 批量读取；只有下一层选择依赖当前路由结果时才顺序读取。Collection 标题和层级是项目文档组织，不得按名称推成 subdomain 或 bounded context。目录故意不含 Fact 正文；不要加载无关 Source、产物、ADR 或全部历史 WorkItem。

## 必需核心

```json
{
  "schema_version": "strixnova.engineering-assessment.v1",
  "assessment_id": "EA-...",
  "assessment_revision": 1,
  "direction_ref": {
    "work_item_id": "WI-...",
    "direction_version": 3
  },
  "investigation_ref": "<immutable Git commit; working_tree only for non-delivery>",
  "change_context": {
    "change_kind": "modify_existing|add_capability|create_project|exploration",
    "formal_implementation": true
  },
  "impact_scope": {
    "affected": [{
      "dimension": "testing",
      "reason": "...",
      "evidence_refs": ["SRC-001"]
    }],
    "unknown": [],
    "unaffected": ["user_behavior", "product_scope"]
  },
  "requested_assurance": {"band": "A0|A1|A2|A3|A4", "reason": "..."},
  "owner_view": {
    "schema_version": "strixnova.owner-view.v1",
    "decision_support": {
      "current_problem": "...",
      "why_it_matters": "...",
      "impact": "...",
      "recommendation": "...",
      "alternatives": ["..."],
      "no_action_consequence": "...",
      "next_step": "...",
      "necessary_questions": []
    },
    "engineering_context": {
      "product_and_domain_change": "...",
      "architecture_responsibilities": "...",
      "implementation_order": "...",
      "highest_impact_risks": "...",
      "verification_and_observation": "...",
      "uncertainties": "..."
    },
    "current_decision": "...",
    "semantic_content_machine_proven": false
  }
}
```

新项目第一次正式仓库交付必须使用 `create_project`，并在 `change_context` 增加六个路径：`project_engineering_baseline_path`、`project_product_definition_path`、`project_domain_model_path`、`project_architecture_description_path`、`project_engineering_policy_path`、`project_implementation_alignment_path`。每个正式项目都建立五类独立权威；DDD 采用是单独工程政策决定，不控制领域或实现对齐是否存在。

现有项目由不可变 `investigation_ref` 让程序定位并验证项目配置与工程基线。除非语义主张实际引用其正文，不把这些确定性绑定重复包装为 SourceReference。引用证据放在顶层 `source_references`；行边界可省略，但出现时必须成对：

```json
{
  "source_references": [{
    "reference_id": "SRC-001",
    "path": "relative/path.py",
    "observed_ref": "<investigation commit>",
    "epistemic_status": "observed|inferred|unknown",
    "line_start": 1,
    "line_end": 10
  }]
}
```

十二个维度必须在 `affected`、`unknown`、`unaffected` 中恰好各出现一次；
`impact_scope.unaffected` 只保存维度名称：

```text
user_behavior product_scope domain architecture interface data
security_privacy quality_performance operations_deployment
compatibility_migration testing documentation_support
```

affected/unknown 项需要具体理由和非空证据；unaffected 只列名称。每个 unknown 维度还需要：

```json
{
  "unknowns_and_limitations": [{
    "statement": "...", "impact": "...", "handling": "...",
    "evidence_refs": ["SRC-001"]
  }]
}
```

## 只添加真实可选事实

省略的列表规范化为空，省略的 `delivery_plan` 规范化为 null；不得添加占位。常见结构：

```json
{
  "risk_assessments": [{
    "statement": "...", "likelihood": "low|medium|high",
    "consequence": "low|medium|high|critical",
    "reversibility": "easy|moderate|difficult|irreversible",
    "uncertainty": "low|medium|high",
    "external_assurance_required": false,
    "mitigation": "...", "evidence_refs": ["SRC-001"]
  }],
  "alternatives_and_tradeoffs": [{
    "option": "...", "disposition": "selected|rejected|deferred",
    "reason": "...", "tradeoffs": "...", "evidence_refs": ["SRC-001"]
  }],
  "design_decisions": [{
    "statement": "...", "rationale": "...", "evidence_refs": ["SRC-001"]
  }]
}
```

只有 adopted/conditional 方法与 affected/unknown 影响相交，或正在创建项目时，才读 [engineering-methods.md](engineering-methods.zh-CN.md)。否则省略 `method_applications`。随包 DDD 规则只与 `domain`、`architecture`、`interface`、`data` 相交，关键词不能激活。

通用治理档案要求具体工程事实：正式变更需要 requirement、acceptance、constraint、operation、delivery；`quality_performance` 还需要 impact、risk、verification；`testing` 需要 verification；`architecture`、`interface`、`data` 需要真实 selected/rejected/deferred 选项、design decision 和 ADR candidate；`security_privacy` 需要 risk、design、verification、delivery；`operations_deployment` 或 `compatibility_migration` 需要 delivery、risk、verification。只写证据支持的内容。

文件操作顶层字段为 `operations`：

```json
{
  "operations": [{
    "action": "create|modify|delete|move",
    "path": "relative/path.py",
    "reason": "...",
    "evidence_refs": ["SRC-001"],
    "implements": ["direction.requirement:DIRREQ-0123456789ABCDEF"]
  }]
}
```

`implements` 非空，只指向当前 `direction.requirement:DIRREQ-*` 或 `design_decisions[n]`；move 还需 `to_path`。日常工作流绝不能把旧数组位置转换为稳定引用。动作必须与 `investigation_ref` 的 Git 事实一致。仅真实长期工程文件使用 `long_lived_artifact`；核心身份前缀为 `PRODUCT-`、`MODEL-`、`ARCH-`、`POLICY-`、`ALIGNMODEL-` 加 16 位大写十六进制，例如
`{"artifact_id":"ARCH-1111111111111111","artifact_type":"architecture"}`。现有项目身份、种类和路径必须匹配工程基线索引；修改、移动、删除已索引权威还要计划工程基线更新。ProjectDomainModel Collection/Source 不是独立 baseline artifact；它们用 `domain_fact_changes`，不加 `long_lived_artifact`。

确需语言或构建工具补足 ImplementationAlignment 观察时，在顶层提交
`external_observation_provider_plans`。内置观察足够时不添加；不得只因后缀或语言名添加。每项计划在工程方案确认时就绑定 argv，以及每个可执行文件、入口脚本、provider 配置和支撑文件的 SHA-256 身份，再绑定受管源码 glob、进程政策和有限资源：

```json
{
  "external_observation_provider_plans": [{
    "provider_plan_id": "OBSPROVPLAN-1111111111111111",
    "scope_id": "OBSCOPE-1111111111111111",
    "language_id": "cpp",
    "provider_id": "project.clang-observer.v1",
    "provider_version": "1.0.0",
    "command": ["tools/observe-cpp.exe", "--format", "strixnova-v1"],
    "materials": [{
      "role": "executable",
      "path": "tools/observe-cpp.exe",
      "sha256": "<已确认文件字节的 64 位小写十六进制>",
      "command_argument_index": 0
    }],
    "source_globs": ["*.c", "*.cpp", "*.h", "*.hpp", "**/*.cpp"],
    "process_policy": {
      "policy_id": "PROCESSPOLICY-1111111111111111",
      "purpose": "观察已配置 C++ 实现关系。",
      "forbidden_program_names": ["codex", "claude"]
    },
    "limits": {
      "timeout_seconds": 300,
      "cleanup_timeout_seconds": 10,
      "max_input_bytes": 4194304,
      "max_output_bytes": 16777216
    }
  }]
}
```

argv、路径和材料散列都必须有项目依据。解释器与其入口脚本要分别绑定；provider 自行读取的配置或支撑文件使用 `command_argument_index: null`。Strixnova 会在进程启动前解析每个已绑定命令参数并重新计算全部材料散列；材料缺失、被替换或字节变化会形成 `not_run` 的失败观察并进入回执。不得调用 Agent、不透明 shell/命令包装器或内联运行时代码；语言运行时可执行固定 provider 入口。glob 必须留在受管范围。`max_input_bytes` 最高 64 MiB，`max_output_bytes` 最高 256 MiB，项目应尽量使用更低的实际上限。程序原样投影到
`strixnova.engineering-plan.v1`；之后 `strixnova alignment capture-external` 只能授权，不能替换或扩展。

`domain_fact_changes` 是评估顶层字段，独立记录项目领域权威变化，不属于 DDD 或其他方法。项目不采用命名方法仍可维护领域模型；方法应用也可只读 `domain_fact_refs` 而不改 Fact。

## 权威变化、语义复核和实施切片

建立或修订产品、领域、架构、工程政策或实现对齐前读 [authority-authoring.md](authority-authoring.zh-CN.md)。修改已采用产品、领域、目标架构或实现对齐时，评估顶层必须提交 `authority_change_set`，绑定不可变调查提交中的四类现行基线，列出真实变化候选和全部必需下游处置。任何下游处置仍阻断时，方案不能确认。首次建立完整权威不能用差异记录代替完整建模。

`target_ref` 是长期权威内真实新增/修改/退役/更名的稳定内容身份，不是候选修订号或说明。修改、退役、更名必须指向调查提交中同类现有身份；新增和 replacement_ref 必须是同类未使用身份。

四层核心链使用精确修订绑定：产品变化必须产生新领域、架构、实现对齐候选；领域变化必须产生新架构和实现对齐候选；架构变化必须产生新实现对齐候选。仅绑定变化也必须记录，不能用 `unchanged` 指向旧修订。

`product_scope`、`domain`、`architecture` 为 affected/unknown，或存在 authority change set 时，读 [cross-artifact-review.md](cross-artifact-review.zh-CN.md)，提交恰好覆盖八个视角的 `semantic_review`。未闭合 high/critical、需负责人决定或仍未解决的高影响问题会阻止确认；`semantic_content_machine_proven=false`。

每项正式实施必须有一个或多个顶层 `implementation_slices`。每个切片有稳定 `SLICE-nnn`、目的、`implements`、独占 `operation_refs`、只指向前序切片的 `depends_on`、双向 `parallel_safe_with`、可观察完成条件、独占 `verification_command_refs` 和恢复说明。每项操作/命令只属于一个切片。只有整份评估都没有适用命令时才填 `verification_not_required_reason`。

长期权威候选起草、最终八视角复核和负责人确认先于切片实施证据。唯一跨切片例外是同一 ImplementationAlignment 草稿的“编码前诚实快照、编码后最终刷新”：最终刷新切片可用 `continued_operation_refs` 精确引用祖先切片的对齐根操作，但只允许同一对齐权威路径，且全方案只有一个。普通源码、测试、文档、产品、领域、架构、工程政策和工程基线不能用该例外。

呈现方案前核对实际写入事务：最终实现对齐刷新同时写根文件、四份底账和基线，最终刷新
切片必须有全部六条路径的合法安排，基线不能靠延续取得权限。若拆分只为形成前后快照，
没有独立工程价值，优先在同一实施切片完成这些写入。先完成对齐及文档写入，再运行该切片
最后的正式验证和后置判断，避免切片已结束而仍有写入未完成。

```json
{
  "implementation_slices": [{
    "schema_version": "strixnova.implementation-slice.v1",
    "slice_id": "SLICE-001",
    "purpose": "完成一个可独立观察的建设增量。",
    "implements": ["direction.acceptance:DIRACC-0123456789ABCDEF"],
    "operation_refs": ["operations[0]"],
    "depends_on": [],
    "parallel_safe_with": [],
    "completion_criteria": ["公开行为达到已确认验收要求。"],
    "verification_command_refs": ["verification_commands[0]"],
    "rollback_or_recovery": "失败时保留未提交改动并修正当前切片。"
  }]
}
```

`owner_view.decision_support` 用普通语言说明当前问题、重要性、影响、推荐、替代项、不处理后果、下一步和最多五个必要问题；`engineering_context` 保留产品/领域变化、架构责任、实施顺序、最高影响风险、验证/可观察效果和未知。程序只校验结构、非空和问题数量。

只有真实长期决定才用 `adr_plans=create|update`。架构、接口或数据受影响但不需要 ADR 时：

```json
{"adr_plans":[{"disposition":"not_required","reason":"project-specific reason","evidence_refs":["SRC-001"]}]}
```

## 选择最小验证集

真实接口、权限、并发、兼容或恢复风险需要精确行为合同时，再读
[风险行为合同](behavior-contracts.zh-CN.md)。只选择适用专题，不将简单变更扩大为无关标准清单。

实现或测试边界本身需要设计时，读[实施与测试方法](implementation-practices.zh-CN.md)。
它补充 Agent 推理方法，不增加评估输入结构，也不登记新的工程方法采用。

正式验证命令是最终证据义务，不是所有开发反馈命令清单。更广套件已覆盖同一断言时不要再提交嵌套 S1/S2/S3/S4；只有证明不同验收或风险时保留额外定向命令。用户可见行为至少有一条通过真实 CLI/API 等公开入口的维护测试与最终验收，不只测内部类。

```json
{
  "verification_commands": [{
    "argv": [".venv/Scripts/python.exe", "-m", "pytest", "tests/unit", "-q"],
    "cwd": ".",
    "run_kind": "targeted_test",
    "covers": [
      "direction.acceptance:DIRACC-0123456789ABCDEF",
      "risk_assessments[0]"
    ],
    "reason": "..."
  }]
}
```

`run_kind` 只能是 `targeted_test`、`integration_test`、`acceptance_test`、`typecheck`、`build`、`lint`、`manual_check`、`full_regression`。argv 来自真实项目事实，不按后缀猜工具，也不因 AssuranceBand 自动加全量回归。`covers` 只指向当前 `direction.acceptance:DIRACC-*`、`direction.constraint:DIRCON-*` 或 `risk_assessments[n]`。无适用命令时省略列表并写具体 `verification_not_required_reason`。

纯叙述文档没有现有构建、链接或可执行示例检查时，不虚构关键词/正则/路径存在测试；语义准确性由 Agent 复核并由用户接受。机器消费文件或已有工具适用时，运行最低有效层的真实解析、构建、链接或示例。

正式交付结构：

```json
{
  "delivery_plan": {
    "expected_outcome": "...",
    "rollback_or_recovery": "...",
    "limitations": [],
    "evidence_refs": ["SRC-001"]
  }
}
```
