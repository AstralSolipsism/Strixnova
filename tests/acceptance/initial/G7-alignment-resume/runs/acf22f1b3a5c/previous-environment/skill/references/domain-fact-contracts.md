# 领域事实第二版精确结构合同

只在起草、修订或纠正 `strixnova.project-domain-source.v1`（项目领域来源第二版）
时读取。这里公开的是机器会执行的精确结构，不替智能编码代理判断项目语义，也不替
项目负责人确认内容。

## 每项现行事实的共同外壳

每项现行事实只能包含以下八个字段，不允许增加说明性字段：

```yaml
fact_id: FACT-2222222222222222
status: draft
title: 仓库管理员
kind: actor
product_capability_ids: [CAPABILITY-1111111111111111]
scope_fact_ids: []
dependency_fact_ids: []
content:
  role: 查看低库存结果并决定后续补货安排。
  responsibilities: [维护库存快照与补货阈值，处理低库存提醒。]
  not_responsible_for: [代替系统逐项执行阈值计算。]
```

- `fact_id`（事实标识）必须符合 `FACT-`（事实标识前缀）加十六位大写十六进制字符。
- `status`（事实状态）只能是 `candidate`（候选）、`draft`（草稿）、
  `ready_for_confirmation`（待确认）或 `confirmed`（已确认）。
  完整模型内每条活动事实的状态还必须与根文件的 `revision.status` 完全一致，不能独立选择。
  根文件不接受 `candidate`；起草未确认模型时，根修订和活动事实都用 `draft`。
- `product_capability_ids`（产品能力标识列表）至少一项，指向产品定义中的正式能力标识。
- `scope_fact_ids`（作用域事实标识列表）和 `dependency_fact_ids`（依赖事实标识列表）
  可以为空；所有非空引用必须指向同一模型内存在的事实。
- `content`（类型化内容）只能使用下表为当前 `kind`（事实类型）规定的字段。

## 十四种现行事实类型

| `kind`（事实类型） | `content`（类型化内容）精确字段 |
|---|---|
| `actor`（参与者） | `role`（角色，文本）；`responsibilities`（责任，至少一条文本）；`not_responsible_for`（不负责事项，至少一条文本） |
| `product_capability`（领域中的产品能力） | `definition`（定义，文本）；`primary_actor_fact_ids`（主要参与者事实标识，至少一项）；`supporting_actor_fact_ids`（支持参与者事实标识，可为空）；`scenario_requirements`（场景要求，恰好四项） |
| `domain_scenario`（领域场景） | `scenario_type`（场景类型）；`capability_fact_id`（领域产品能力事实标识）；`actor_fact_ids`（参与者事实标识，至少一项）；`preconditions`（前置条件，可为空）；`trigger`（触发）；`steps`（步骤，至少一项）；`outcome`（结果）；`postconditions`（后置条件，可为空） |
| `domain_entity`（领域实体） | `identity`（身份规则，文本）；`responsibilities`（责任，至少一条文本）；`lifecycle_fact_id`（生命周期事实标识，或空值） |
| `value_object`（值对象） | `meaning`（含义，文本）；`components`（组成，至少一项）；`invariants`（不变量，至少一条文本） |
| `lifecycle`（生命周期） | `subject_fact_id`（主体事实标识）；`states`（状态，至少两项）；`transitions`（转换，至少一项） |
| `domain_event`（领域事件） | `meaning`（含义，文本）；`occurs_when`（发生条件，文本）；`subject_fact_ids`（主体事实标识，至少一项）；`information`（携带信息，至少一条文本） |
| `domain_rule`（领域规则） | `statement`（规则陈述，文本）；`applies_when`（适用条件，文本） |
| `domain_invariant`（领域不变量） | `statement`（不变量陈述，文本）；`protected_fact_ids`（受保护事实标识，至少一项） |
| `decision_authority`（决定权） | `decision`（决定内容，文本）；`authority_actor_fact_id`（最终决定参与者事实标识）；`candidate_provider_actor_fact_ids`（候选提供者事实标识，可为空）；`non_authority_actor_fact_ids`（非决定者事实标识，可为空） |
| `bounded_context`（限界上下文） | `responsibility`（责任，文本）；`decisions`（本边界作出的决定，至少一条文本）；`excluded_responsibilities`（明确排除的责任，至少一条文本） |
| `context_relationship`（上下文关系） | `from_context_fact_id`（来源上下文事实标识）；`to_context_fact_id`（目标上下文事实标识）；`relationship_type`（关系类型，文本）；`contract`（交互合同，文本） |
| `external_system`（外部系统） | `responsibility`（外部责任，文本）；`provides_facts`（提供的事实，至少一条文本）；`does_not_decide`（不得决定的内容，至少一条文本） |
| `term`（术语） | `term`（术语原文，文本）；`definition`（单一含义，文本） |

不得使用 `entity`（实体简写）、`scenario`（场景简写）、`event`（事件简写）、
`rule`（规则简写）、`invariant`（不变量简写）或 `domain_boundary`（领域边界简写）。
领域边界使用 `bounded_context`（限界上下文）；文件系统、外部服务或人工外部组织使用
独立的 `external_system`（外部系统）事实。

## 嵌套对象的精确形状

`scenario_requirements`（场景要求）必须恰好四项，并分别说明
`normal`（正常）、`blocking`（阻断）、`correction`（纠正）和
`cancellation`（取消）：

```yaml
scenario_requirements:
  - scenario_type: normal
    applicability: required
    reason: 必须说明正常完成路径。
  - scenario_type: blocking
    applicability: required
    reason: 必须说明何时阻断错误结果。
  - scenario_type: correction
    applicability: required
    reason: 必须说明如何纠正后重试。
  - scenario_type: cancellation
    applicability: not_applicable
    reason: 当前能力没有需要领域处理的取消状态。
```

`applicability`（适用性）只能是 `required`（必须有场景）或
`not_applicable`（明确不适用）；`reason`（适用性理由）必须是非空文本。声明为必须时，
同一能力和同一场景类型必须恰好存在
一个 `domain_scenario`（领域场景）事实；声明不适用时不得另写该场景正文。
失败和恢复不是额外枚举值：失败条件写入 `blocking`（阻断）场景，修正与恢复写入
`correction`（纠正）场景。

`components`（值组成）的每项只能包含 `name`（组成名称）和 `meaning`（组成含义）：

```yaml
- name: quantity
  meaning: 快照时点的离散物品数量。
```

`states`（生命周期状态）的每项只能包含 `state`（状态名称）和 `meaning`（状态含义）：

```yaml
- state: 已验证
  meaning: 完整快照的全部不变量已经成立。
```

`transitions`（生命周期转换）的每项只能包含 `from_state`（来源状态）、
`to_state`（目标状态）、`trigger`（触发条件）、`guards`（守卫条件）和
`resulting_event_fact_ids`（产生的领域事件事实标识）：

```yaml
- from_state: 已读取
  to_state: 已验证
  trigger: 完整快照校验完成。
  guards: [所有库存项均有效]
  resulting_event_fact_ids: []
```

`guards`（守卫条件）和 `resulting_event_fact_ids`（产生的领域事件事实标识）可以为空。
`lifecycle_fact_id`（生命周期事实标识）只能指向 `lifecycle`（生命周期）；
`subject_fact_id`（生命周期主体事实标识）只能指向 `domain_entity`（领域实体）或
`product_capability`（领域中的产品能力）；事件引用必须指向 `domain_event`（领域事件）。
`context_relationship`（上下文关系）的两端都必须指向 `bounded_context`（限界上下文），
不能把 `external_system`（外部系统）事实填入任一端。外部依赖可以用真实职责说明及
`dependency_fact_ids`（依赖事实标识）表达；不要为了通过类型校验把外部系统改成内部上下文。

## 产品能力与场景必须形成闭包

产品定义里的 `CAPABILITY-...`（产品能力标识）只负责把领域事实归属到产品承诺；它不替代
领域内的 `product_capability`（领域中的产品能力）事实。每项需要场景解释的产品能力应有：

1. 一个 `product_capability`（领域中的产品能力）事实，声明主要和支持参与者及四类场景要求；
2. 每个标记为 `required`（必须有场景）的要求恰好对应一个
   `domain_scenario`（领域场景）事实；
3. 场景的 `capability_fact_id`（领域产品能力事实标识）指回该能力事实，
   `actor_fact_ids`（参与者事实标识）只指向 `actor`（参与者）事实。

决定权不要塞进参与者的 `content`（类型化内容）中，应建独立
`decision_authority`（决定权）事实。外部系统不要塞进
`bounded_context`（限界上下文）的内容中，应建独立 `external_system`（外部系统）事实。

## 退役事实

`superseded`（已被替代）或 `retired`（已退役）事实不再含 `content`（类型化内容），
只能包含共同外壳中的前七项字段，再加：

- `lineage`（演进谱系）：每项只有 `relation`（关系）和
  `target_fact_id`（目标事实标识）；关系只能是 `superseded_by`（被替代为）、
  `split_into`（拆分为）或 `merged_into`（合并为）。
- `retirement_reason`（退役原因）：非空文本。

`superseded`（已被替代）至少一项谱系；`retired`（已退役）谱系必须为空。

## 校验失败时怎样纠正

单个 YAML 通过 JSON Schema，只证明该文件的局部结构。完整候选还须经已有权威读取/校验
入口核对根与来源的身份、修订及状态一致性、跨事实类型引用和能力场景闭包。
分别报告局部结构与完整候选校验结果；后者未运行或未通过时，不能宣称材料已经可被正式读取
或采用。根据公开的实际错误修正当前草稿，不通过删掉真实未决项或降低领域要求来取得通过。

公开错误会定位到 `facts.<序号>.<字段>`（事实序号与字段），并列出缺少字段、
不允许字段、非法类型或允许集合。只纠正结构时不要改变事实含义；若结构纠正迫使含义、
事实拆分、关系或范围变化，原负责人接受立即失效，必须形成新摘要并重新展示。不得读取
安装包源码、内部测试或未公开结构来猜字段。
