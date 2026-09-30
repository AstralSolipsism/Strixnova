# 交付与外部活动治理

形成结果时优先使用 [prepared-input.md](prepared-input.zh-CN.md)：程序枚举必要身份、固定
审阅对象；Agent 补充语义判断，检查完整组装结果后，沿既有交付路由提交。下文保留正式
输入字段说明，无须把整个骨架手工抄回。

读取当前计划 `verification_targets`。命令保留实际回执状态；每个非命令目标及需要断言审阅的自动行为例子都提交一项 `verification_review_results`，字段为 `target_ref`、`outcome`、`rationale`、`evidence_refs`。结果为 `supported`、`not_supported` 或 `not_verified`；支持结论属于 Agent 判断，遗漏会被拒绝，未核验或未获支持必须保留实际结果限制。计划的 `not_verified` 不能直接改称支持。

有例子时按[行为例子与核验](behavior-examples.zh-CN.md)说明期望、实际原生用例结果、断言充分性和缺口；父验收从例子派生结果，无需再提交父项审阅。

`target_verification` 是程序派生摘要，`command_evidence_passed` 与 `agent_supported` 表达不同证据，都不证明语义。当前方案缺少 `verification_targets` 时必须先修正方案，不能补造覆盖，也不能把缺失字段当作空目标集合。结果有明确的未来承诺，或方向承接了精确旧问题时，读 [延期跟进](follow-ups.zh-CN.md)。没有跟进承诺的普通证明边界继续用文字说明；原有实际结果确认点解释剩余差距和接受范围。

只有当前输入种类明确要求交付时才使用 `delivery` intent（意图）。

## 目录

- [开始实施](#开始实施)
- [呈现实际结果](#呈现实际结果)
- [治理外部活动](#治理外部活动)
- [实际结果确认后](#实际结果确认后)

## 开始实施

```json
{
  "target_ref": "main",
  "merge_strategy": "no_ff"
}
```

`worktree_path`（工作树路径）是可选字段。本产品不记录或管理智能编码代理的
运行、会话、身份、凭证、租约或写权。如果目标版本已经推进，Strixnova
会暂停并要求调用它的智能编码代理提交语义影响候选；程序不会复制或解释
Git（版本管理系统）差异。

在返回的工作区中使用正常编码工具实施。不要询问 Strixnova 应读写哪些文件或使用什么工具。

选择模块或测试边界、以回归测试修复行为，或实施测试先行工作时，再读
[实施与测试方法](implementation-practices.zh-CN.md)。纯说明文字及不涉及这些选择的机械
修改可以跳过这份附加资料。

当 CurrentAction（当前动作）给出
`engineering.plan.implementation_slice:<SLICE-ID>`（工程方案当前实施切片引用）时，
读取该精确记录，只实施它拥有的操作，并以它的完成条件判断本步是否结束。只运行分配给
该切片的验证命令。每个回执完成运行后代码变化判断，再读取返回的下一动作：它会聚焦下一个
前置条件已经满足的切片、要求重新规划，或要求提交 ActualResult（实际结果）。这只是程序按
已确认依赖关系控制先后顺序，不是 Agent（智能编码代理）调度；Strixnova永远不会
启动或管理智能编码代理。

## 呈现实际结果

形成结果时，通过有界 `next --record` 读取方案与输入合同。可用的 `engineering.plan`
父记录允许精确子项读取，例如 `engineering.plan#/verification_targets`、
`engineering.plan#/actual_result_requirements`、`engineering.plan#/applicable_rules`、
`engineering.plan#/method_applications` 和 `engineering.plan#/authority_change_set`。
其他所需材料从返回目录发现，沿分页及未展开的 Schema 引用取得适用条件；目录或被宿主
截断的工具输出不等于完整合同。

全部计划验证回执都有当前运行后判断后，先通过 `strixnova next --record` 读取
`engineering.review_subject`，再复核实际实现与证据。将其中的 `subject_ref` 随结论保留。
该对象绑定当前方案、原始方向、已有证据、声明的仓库输入和已采用规则依据，不证明所选
范围穷尽或审阅正确；不重抄文件清单或原文。提交时将返回身份填入 `review_subject_ref`：

```json
{
  "schema_version": "strixnova.actual-result.v1",
  "review_subject_ref": "review-subject:<returned SHA-256>",
  "semantic_content_machine_proven": false,
  "effect_summary": "...",
  "delivered_outcomes": ["..."],
  "deviations": [],
  "limitations": [],
  "verification_receipt_ids": ["VR-..."],
  "long_lived_refs": [],
  "domain_fact_change_results": [{
    "target_ref": {
      "schema_version": "strixnova.domain-fact-reference.v1",
      "authority_kind": "project_domain_model",
      "model_id": "MODEL-0123456789ABCDEF",
      "fact_id": "FACT-0123456789ABCDEF",
      "observed_commit": "0123456789abcdef0123456789abcdef01234567"
    },
    "outcome": "realized",
    "evidence_refs": ["VR-..."],
    "limitations": []
  }],
  "method_application_results": [{
    "method_id": "ddd",
    "use_results": [{
      "use_id": "DDD-USE-001",
      "status": "realized",
      "outcome": "The planned DDD use was actually completed.",
      "evidence_refs": ["VR-..."]
    }],
    "deviations": []
  }],
  "governance_rule_results": [{
    "rule_id": "STRIXNOVA-GOV-REQ-001",
    "status": "satisfied",
    "evidence_refs": ["VR-..."],
    "gaps": [],
    "remediation_actions": [],
    "limitations": []
  }]
}
```

提交前，以 `engineering.plan.operations`（工程方案文件操作）为唯一已确认的路径范围。
当前实施切片记录中的 `resolved_operations`（已解析文件操作）已经把操作引用和具体路径
放在一起；不要仅凭 `operations[n]`（文件操作序号）猜路径。

返回 `review_subject_changed` 表示被审阅内容或依据已变化。重新取得当前对象，并复核
受影响实现和证据；不能只给旧结论替换新身份。保留原发现及实际处置，只有方案本身失效时
才沿既有 replan 路径处理。新提交使用当前 `strixnova.actual-result.v1` 公开合同。

如果提交实际结果时返回 `unplanned_repository_change`（计划外仓库改动），先区分两种情况：

- 文件确实是误改：只恢复误改内容，重新运行受影响验证；
- 文件是实现已确认责任所必需：不要删除合理分层，也不要把偏差藏进实际结果。使用同一个
  `strixnova submit`（Strixnova提交）入口提交
  `strixnova.replan-request.v1`（重新规划请求第一版），说明具体新增路径及原因。进入
  `revise_engineering_plan`（修订工程方案）后读取原工程评估，形成包含该路径的完整新修订，
  再经方案确认、实施和验证回到实际结果。

```json
{
  "schema_version": "strixnova.replan-request.v1",
  "reasons": ["src/domain.py 是实现已确认领域责任所需，但不在当前已确认文件操作中。"]
}
```

如实说明观察到的行为、负面结果、偏离和未知，不夸大。每个已计划长期产物必须按实际情况携带
`artifact_id`、`artifact_type`、`path` 和 `introduced`、`updated`、`realized` 或
`removed` 关系。未变化文件不能作为长期结果引用；改为引用评估来源或已交付结果。

新项目以调查提交为比较基点，五类首次建立的长期权威在实际结果中都使用
`introduced`（本事项引入）。即使实施期间先建立了诚实的空实现对齐、随后又在同一
WorkItem（建设事项）内把它刷新为实施后修订，最终唯一的
`domain_alignment`（实现对齐）条目仍使用稳定的 `alignment_model_id`（实现对齐模型标识）
作为 `artifact_id`（产物标识），关系仍是 `introduced`（本事项引入）；不得改用修订标识，
不得重复报告同一路径，也不得误写成 `updated`（已更新）。只有调查提交中已经存在该稳定
产物、而本事项修改它时，关系才是 `updated`（已更新）。

从 CurrentAction 指定的 `engineering.plan` 读取已确认方案顶层
`actual_result_requirements` 及每个方法应用自己的同名要求。顶层提供精确 Fact
`target_ref` 和计划处置；方法应用提供 `method_id` 与 `use_ids`。把这些身份分别复制到对应结果数组；方案不提供或猜测 outcome、evidence 或 limitations。

每个已应用方法的每个 `use_ids` 都对应一条
`method_application_results[].use_results`。只有引用真实回执 ID、
`delivered_outcomes[n]`、`artifact:<artifact_id>` 或其他允许的实际结果证据时才能写
`realized`。方案未实现时写 `not_realized`，同时披露方法偏离和用户可见限制。仅考虑但未应用的方法不生成假结果。每个顶层 `domain_fact_changes` 要求都有独立顶层结果，以
`realized`、`deferred` 或 `deviated` 报告并引用真实证据；非 realized 结果必须有限制。已实现 Fact 变化必须匹配最终规范 Source/tombstone。完整对齐刷新通过
`domain_alignment` 长期引用报告，并匹配最终完整对齐权威及修订。

方案顶层每个 `applicable_rules` 条目都必须有一条 `governance_rule_results`。
`satisfied` 需要真实证据且无开放缺口；`partially_satisfied`、`not_satisfied`、
`unknown` 同时保留缺口与具体纠偏行动。这是内部工程结果，不证明语义正确或外部认证。

按照 [cross-artifact-review.md](cross-artifact-review.zh-CN.md)
（跨产物审查与负责人展示规程）的关注顺序展示结果：目的、产品与领域变化、架构责任、
实际实施顺序、最高影响风险、真实验证与可观察效果、剩余未知，以及当前唯一决定。把方案中
面向未来的 `owner_view`（负责人视图）改写为带真实回执和限制的实际结果说明，不能原样复制。

Strixnova 比较调查提交与最终工作树的稳定身份，因此同一 Source 中计划 Fact 旁边的兄弟 Fact 被计划外修改时会拒绝。首次整模型采用由 adoption change 和长期权威覆盖，不把每个既有 Fact 展开成 `add`。这只证明哪些记录变化，不证明领域含义正确。

A0 不使用假回执，并明确说明没有实施。

## 治理外部活动

`strixnova activity`（Strixnova外部活动命令）治理交付、发布、部署、回滚、
观测和运行维护活动的计划、授权状态与真实外部回执。它是绑定建设事项的项目级
生命周期，不是 `CurrentAction`（当前动作）的输入，也不会执行外部活动。

只按以下顺序推进：

1. 建设事项的完整工程方案已经确认后，形成活动计划并调用
   `strixnova activity`（Strixnova外部活动命令）的 `plan`（计划）动作。
2. 建设事项的实际结果已经由项目负责人确认，且负责人已有授权明确覆盖该外部活动时，
   使用最新的建设事项版本和活动版本调用 `authorize`（授权）动作。沿用仍有效的
   明确授权，不重复请求；本地结果接受本身不授权发布或部署。授权不等于已经执行。
3. 由计划中指定的外部工程工具和责任方实际执行。Strixnova不得调用、
   模拟或替代发布、部署、监控等外部系统。
4. 外部系统开始后，先记录一份 `started`（已开始）回执；随后只能再记录
   `completed`（已完成）、`failed`（已失败）或 `canceled`（已取消）
   之一。执行前取消按下方规则处理。没有真实回执时保持现有状态，不得补写成功。

完整计划请求示例：

<!-- strixnova-example:activity-plan -->
```json
{
  "action": "plan",
  "work_item_id": "WI-20260827-EXAMPLE",
  "work_item_version": 7,
  "plan": {
    "schema_version": "strixnova.delivery-activity-plan.v1",
    "activity_kind": "deployment",
    "target_environment": {
      "environment_id": "production-cn",
      "description": "中国区生产环境"
    },
    "objective": "把已接受的本地交付版本部署到中国区生产环境",
    "responsible_party": "项目发布负责人",
    "external_system": {
      "system_id": "deploy-platform-cn",
      "name": "项目既有部署平台",
      "execution_owner": "项目发布负责人",
      "receipt_channel": "部署平台生成的不可变运行记录"
    },
    "preconditions": [
      "建设事项工程方案已经确认",
      "目标环境和回滚版本已经核对"
    ],
    "success_criteria": [
      "部署平台报告目标版本完成",
      "计划中的生产后检查通过"
    ],
    "stop_conditions": [
      "目标版本与已接受结果不一致",
      "生产后检查出现阻断性失败"
    ],
    "rollback_or_recovery": "停止继续放量，并由部署平台恢复到已记录的上一稳定版本",
    "evidence_requirements": [
      "部署运行标识和最终状态",
      "目标版本、执行时间与生产后检查结果"
    ]
  }
}
```
<!-- /strixnova-example -->

计划建立后，用返回的 `activity_id`（活动标识）和 `version`（活动版本）推进：

```json
{"action":"authorize","activity_id":"DA-20260827-EXAMPLE","activity_version":1,"work_item_version":12}
```

完整外部回执请求示例。以下展示开始回执；终态回执保持同一外部系统身份，使用
新的回执标识，并把事件改为三个允许终态之一：

<!-- strixnova-example:activity-receipt -->
```json
{
  "action": "record",
  "activity_id": "DA-20260827-EXAMPLE",
  "activity_version": 2,
  "receipt": {
    "schema_version": "strixnova.delivery-activity-receipt.v1",
    "receipt_id": "DEPLOY-RUN-20260827-001-START",
    "event_kind": "started",
    "external_system_id": "deploy-platform-cn",
    "observed_at": "2026-08-27T10:30:00Z",
    "source": "部署平台不可变运行记录",
    "request_summary": "部署已接受的目标版本到中国区生产环境",
    "result_summary": "部署平台已创建运行并开始执行",
    "raw_evidence_refs": ["deploy-run:20260827-001"],
    "limitations": ["此回执只证明已经开始，不证明部署完成或产品行为正确"],
    "irreversible_effects": [],
    "follow_up_responsibilities": ["项目发布负责人持续观察并记录最终状态"]
  }
}
```
<!-- /strixnova-example -->

只有仍处于 `planned`（已计划且未授权）状态的活动，才能不依赖外部回执调用
`cancel`（取消计划）动作：

```json
{"action":"cancel","activity_id":"DA-20260827-EXAMPLE","activity_version":1,"canceled_by":"项目发布负责人","reason":"目标环境已经变更，需要重新形成计划"}
```

使用 `get`（读取单项）查看一个活动，使用 `list`（列出活动）查看全部活动，
也可以在 `list`（列出活动）中提供 `work_item_id`（建设事项标识）进行筛选。
活动进入 `authorized`（已授权）后，如果外部系统确认活动在开始执行前取消，
使用 `action=record` 提交 `event_kind=canceled` 的真实回执，直接结束活动，
无需先记录 `started`。沿用上方回执结构，保留计划中的外部系统身份、来源、
原始证据引用和剩余影响；已记录的授权与历史保持原样。
运行中取消也使用真实取消回执。只有取消意图或执行情况未知时，先核对外部事实，
保持现有状态；不能用缺少开始回执推断尚未执行。

## 实际结果确认后

正式建设事项只按以下顺序推进：

1. 重新读取 CurrentAction（当前动作），再读取其中的
   `delivery.authority_adoption`（交付阶段权威采用记录）。
2. 需要采用时，先确认
   `accepted_candidate_snapshot_verified=true`（已接受候选快照已核验）。如果
   `blocking_issues`（阻断问题）提示“已接受实际结果之后发生正文变化”，误改只能恢复为
   已接受时的精确内容；有意变化必须重新规划、重新验证并形成新的实际结果。不得修改
   `authority_candidate_snapshot`（候选权威正文快照）来迁就当前工作树。
3. 调用 `delivery --input @-`（交付命令从标准输入读取载荷），载荷为 `{}`（空对象）。
   如果 `required=false`（不需要采用），程序不修改长期权威；如果需要定档，程序只允许
   机械确认精确 ImplementationAlignment（实现对齐）候选并更新工程基线。智能编码代理
   不得手工执行 `authority_updates`（权威更新）或 `baseline_update`（工程基线更新）。
4. ActualResult（实际结果）确认不能采用 ProductDefinition（产品定义）、
   DomainModel（领域模型）、TargetArchitecture（目标架构）或 EngineeringPolicy（工程政策）。
   这些上游权威必须在实施前通过独立长期权威决定成为 `confirmed`（已确认）且已被基线采用；
   否则 `blocking_issues`（阻断问题）会明确指出缺失决定，必须回到正确入口，不能补写元数据。
5. 程序完成机械定档时返回 `authority_adoption_finalized`（权威采用已定档）和新的
   WorkItem（建设事项）版本。重新读取 CurrentAction（当前动作）及采用记录；确认
   `ready_for_atomic_commits=true`（可以形成原子提交）后，
   才在 WorkItem（建设事项）隔离工作区内形成只包含已接受实际结果的聚焦本地
   Git（版本管理系统）原子提交；不得混入无关文件或推送远程。
6. 使用新版本再次调用 `delivery --input @-`（交付命令从标准输入读取载荷）。程序会读取
   结果提交并继续本地合入。如果返回 `authority_adoption_not_finalized`（权威采用尚未定档），
   只按阻断原因恢复已接受正文、重新规划或回到独立权威确认；不得绕过门禁或把草稿候选
   提交到集成分支。
7. 本地合入产生真实集成提交后，程序会从该不可变提交重新计算
   `authority_candidate_snapshot`（权威候选正文快照），并把通过证明写入合入回执。
   冲突解决、换行转换或其他合入效果只要改变已接受正文，就不得记录合入完成；不能沿用
   提交前的 `accepted_candidate_snapshot_verified`（已接受候选快照已核验）结论。

Strixnova随后核对结果提交、合入记录的本地目标，并安全清理分支或工作树。
发生 Git（版本管理系统）冲突时，使用原生 Git（版本管理系统）解决，提交冲突判断，
运行当前动作列出的复测；需要时完成合并提交，再次调用 `delivery`（交付命令）。

对于 `integrate`（本地合入）、`complete_merge`（完成合并）或 `cleanup`（清理），
除非当前动作明确要求使用实施开始时已经记录的合入策略，否则传入 `{}`（空对象）。
对于 `resume_external_effect`（恢复外部副作用），只有 CurrentAction（当前动作）的
`intent=delivery`（意图为交付）时才传入 `{}`（空对象）；当
`intent=cancel`（意图为取消）时，遵循当前公开输入合同和
[confirmation-and-cancel.md](confirmation-and-cancel.zh-CN.md)（确认与取消规程）。


遇到 `resume_external_effect` 时，按[恢复已记录副作用](replanning.zh-CN.md#恢复已记录副作用)处理。只有精确内容和原定档事实重新核对后才可沿用既有定档。


长期产物 `long_lived_refs` 按 `repository_id` 和内部 `path` 定位；同名文件分别核对。仅在计划能唯一确定仓库时省略身份。

```json
{"repository_id":"REPO-7777777777777777","artifact_id":"ADR-0042","artifact_type":"adr","path":"docs/adr/ADR-0042.md","relation":"introduced"}
```
