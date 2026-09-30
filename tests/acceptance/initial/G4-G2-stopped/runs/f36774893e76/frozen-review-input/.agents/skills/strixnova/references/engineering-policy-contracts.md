# 工程政策精确结构合同

只在建立或修订 `strixnova.project-engineering-policy.v1`（项目工程政策第一版）时读取。
根文件示例见长期权威起草资料；本文件补齐容易被自然语言误译的嵌套字段、枚举和边界。
工程政策回答“怎样建设和证明”，不得保存当前代码完成度，也不得替产品、领域或架构作决定。

## 一、产品归属与复核基点

`product_definition_ref`（产品定义引用）中的 `product_id`（产品标识）说明政策属于哪个稳定
产品，必须始终与项目当前产品身份一致；`revision_id`（修订标识）用于追溯，记录政策最近一次语义确认时所依据的产品修订，不要求随每次产品修订机械滚动。
同一稳定产品发布新产品修订时不必复制政策；智能编码代理仍须在工程评估中判断政策是否受影响，只有政策陈述、方法采用、
项目来源、扩展或裁剪发生实质变化时，才形成新的政策候选并请求独立确认。不得修改已确认
政策文件中的产品修订引用来伪造“已复核”。

## 二、工程方法采用

`method_adoptions`（工程方法采用）至少一项。每项字段只有：

- `method_id`（方法标识）；
- `status`（采用状态）；
- `reason`（采用判断理由）；
- `conditions`（条件）；
- `adopted_technique_ids`（已采用技术标识）。

状态只能是 `adopted`（已采用）、`conditional`（有条件采用）、
`not_adopted`（不采用）或 `not_assessed`（尚未评估）。采用或有条件采用时，技术标识必须来自
随包基础治理档案中该方法的公开技术清单，并包含其必要技术；不采用或尚未评估时不要伪造技术采用。

```yaml
method_adoptions:
  - method_id: ddd
    status: not_assessed
    reason: 尚未形成项目采用判断，不伪造结论。
    conditions: []
    adopted_technique_ids: []
```

## 三、政策陈述

`policy_statements`（政策陈述）必须同时且只能包含 `quality`（质量）、
`testing`（测试）、`security`（安全）、`release`（发布）、`operations`（运行）、
`maintenance`（维护）和 `compatibility`（兼容）七个列表。列表可以为空，但正式候选应按真实影响
明确适用规则和不适用边界，不用一条笼统陈述代替全部主题。

## 四、项目工程方法来源

`project_sources`（项目工程方法来源）可以为空。只有项目自身采用的工程标准、方法说明、
规范或政策资料才进入这里；当前源码、测试、提交和运行结果分别属于实现对齐或建设事项证据，
不能为了证明“调查过代码”而伪装成工程方法来源。

每项来源只能包含：

- `source_id`（来源标识）；
- `title`（来源标题）；
- `path`（仓库内普通相对路径，使用正斜杠）；
- `status`（来源状态）；
- `usage`（本项目怎样使用该来源）。

状态只能是 `current`（当前）、`superseded`（已被取代）或 `retired`（已退役）。路径必须真实存在；
若需要固定某个外部版本，在仓库内研究或采用说明中记录精确提交和链接，再由这里引用该文件。
不得使用 `kind`（来源类型简写）、`reference`（外部引用简写）或
`purpose`（用途简写）替代正式字段。

```yaml
project_sources:
  - source_id: SOURCE-PROJECT-METHOD-001
    title: 项目工程方法采用说明
    path: docs/engineering/method-adoption.md
    status: current
    usage: 只作为工程方法与裁剪依据，不定义产品、领域或目标架构含义。
```

没有真实项目方法资料时直接使用：

```yaml
project_sources: []
```

## 五、项目规则扩展

`rule_extensions`（项目规则扩展）可以为空。只有随包基础规则确实没有表达项目特有约束时才新增，
不得复制基础规则或把一次工程方案写成长效规则。每项字段只有：

- `rule_id`（规则标识）；
- `topic`（主题）；
- `source_ids`（来源标识，至少一项）；
- `always_for_formal_implementation`（是否对所有正式实施生效）；
- `impact_dimensions`（影响维度）；
- `minimum_assurance`（最低保障等级）；
- `required_information_kinds`（必要信息种类）；
- `strixnova_interpretation`（Strixnova解释）；
- `evidence_expectations`（证据要求）。

最低保障等级只能是 `A0`（零级保障）、`A1`（一级保障）、`A2`（二级保障）、
`A3`（三级保障）或 `A4`（四级保障）。影响维度只能从以下集合选择：

- `user_behavior`（用户行为）、`product_scope`（产品范围）、`domain`（领域）、
  `architecture`（架构）、`interface`（接口）、`data`（数据）；
- `security_privacy`（安全与隐私）、`quality_performance`（质量与性能）、
  `operations_deployment`（运行与部署）、`compatibility_migration`（兼容与迁移）、
  `testing`（测试）、`documentation_support`（文档与支持）。

必要信息种类只能从以下集合选择：`requirement`（需求）、`acceptance`（验收）、
`constraint`（约束）、`impact`（影响）、`risk`（风险）、`option`（选项）、
`design`（设计）、`operation`（操作）、`verification`（验证）、`delivery`（交付）、
`adr_candidate`（架构决定候选）或 `unknown`（未知）。

来源标识必须来自随包基础来源或本文件 `project_sources`（项目工程方法来源），不能悬空。

## 六、基础规则裁剪

`rule_tailoring`（基础规则裁剪）可以为空。每项字段只有：

- `rule_id`（随包基础规则标识）；
- `disposition`（处置）；
- `minimum_assurance`（最低保障等级或空值）；
- `reason`（理由）；
- `owner_confirmed`（负责人已确认），只能为 `true`（是）。

处置只能是 `retained`（保留）、`strengthened`（强化）或
`project_not_applicable`（本项目不适用）。只有强化时才能声明最低保障等级，而且不得低于基础规则；
保留或不适用时最低保障等级必须为空值。工程政策候选未经负责人接受时，不得把
`owner_confirmed`（负责人已确认）猜成 `true`（是）；首次候选通常保持空裁剪列表。

## 七、验证命令政策

`verification_command_policy`（验证命令政策）必须且只能包含：

- `allowed_programs`（允许程序，至少一项）；
- `forbidden_agent_program_names`（禁止的智能编码代理程序名，至少一项）；
- `wrapper_policy`（包装程序政策）；
- `working_directory_policy`（工作目录政策）；
- `plan_binding_required`（必须绑定工程方案）。

每项允许程序只包含 `program`（程序）、`purpose`（用途）和
`argument_policy`（参数政策）。参数政策只能是 `exact_plan_only`（只允许工程方案中的精确参数）。
包装程序政策只能是 `forbidden_unless_exactly_approved`（除非精确批准否则禁止），
工作目录政策只能是 `project_or_authorized_worktree_only`（仅项目或已授权工作区），
方案绑定必须为 `true`（是）。

禁止程序至少包含 `codex`、`claude`、`gemini`、`aider`、`opencode`、`cursor` 和 `windsurf`。
这些是验证命令不得递归启动的 Agent 程序名，不限制当前宿主是谁。

长期允许程序使用稳定程序身份或仓库内稳定相对路径，不写一次性环境的绝对路径；
每次工程方案仍固定真实执行路径、全部参数和工作目录。

```yaml
verification_command_policy:
  allowed_programs:
    - program: strixnova
      purpose: 执行已确认方案中的Strixnova验证。
      argument_policy: exact_plan_only
    - program: python
      purpose: 执行已确认方案中的项目测试或本地验收。
      argument_policy: exact_plan_only
    - program: git
      purpose: 执行明确批准的本地版本管理操作。
      argument_policy: exact_plan_only
  forbidden_agent_program_names: [codex, claude, gemini, aider, opencode, cursor, windsurf]
  wrapper_policy: forbidden_unless_exactly_approved
  working_directory_policy: project_or_authorized_worktree_only
  plan_binding_required: true
```

## 八、交付关口与证据边界

`delivery_gates`（交付关口）必须且只能包含：

- `result_acceptance_before_commit`（提交前接受实际结果）为 `true`（是）；
- `local_integration_only`（只允许本地集成）为 `true`（是）；
- `external_execution_requires_external_receipt`（外部执行必须有外部回执）为 `true`（是）；
- `remote_operations_in_scope`（远程操作在范围内）为 `false`（否）。

`evidence_requirements`（证据要求）必须且只能包含：

- `separate_structure_semantics_confirmation_effect_and_conformance`
  （分开结构、语义、确认、效果和符合性）为 `true`（是）；
- `unrun_items_visible`（未运行项必须可见）为 `true`（是）；
- `semantic_correctness_machine_proven`（语义正确性由机器证明）为 `false`（否）；
- `external_conformance_without_external_evidence`（没有外部证据仍可声明外部符合）为
  `false`（否）。

## 九、未决决定

`unresolved_decisions`（未决决定）每项只能包含 `decision_id`（决定标识）、
`statement`（问题陈述）和 `impact`（影响）。决定标识使用
`DECISION-`（决定标识前缀）加十六位大写十六进制字符。已确认工程政策不能保留未决决定。

## 校验失败时怎样纠正

字段级错误会定位到具体列表序号，并指出缺少字段、不允许字段、非法类型或允许集合。
若错误发生在已经接受的政策修订，不能原地改写；应形成直接承接该已确认修订的新政策候选，
说明这次只纠正结构还是同时改变政策含义，再由项目负责人接受精确候选。
