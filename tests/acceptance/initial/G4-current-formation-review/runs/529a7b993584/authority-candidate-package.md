# 预约申请工具 — 完整长期权威候选包

> [!IMPORTANT]
> 本文件是**候选草稿**，不是已接受的权威。所有内容需要负责人逐类审阅并明确决定后，才能由公开程序写入确认元数据。本文不调用任何确认命令，不实施业务代码，不提交 Git。

---

## 一、稳定身份与修订

| 权威类别 | 稳定身份 | 当前已确认修订 | 候选新修订 | 状态 |
|---|---|---|---|---|
| 产品定义 | `PRODUCT-1111111111111111` | `REVISION-1111111111111111` | `REVISION-2222222222222222` | `draft` |
| 领域模型 | `MODEL-1111111111111111` | `MODELREV-1111111111111111` | `MODELREV-2222222222222222` | `draft` |
| 目标架构 | `ARCH-1111111111111111` | `ARCHREV-1111111111111111` | `ARCHREV-2222222222222222` | `draft` |
| 工程政策 | `POLICY-1111111111111111` | `POLICYREV-1111111111111111` | `POLICYREV-2222222222222222` | `draft` |
| 实现对齐 | `ALIGNMODEL-1111111111111111` | `ALIGNREV-2222222222222222` | *待上游确认后形成* | `draft` |

产品身份 `PRODUCT-1111111111111111`、项目身份 `PROJECT-1111111111111111`、仓库身份 `REPO-1111111111111111` 和负责人身份 `OWNER-1111111111111111` 保持不变。

---

## 二、产品定义候选 `REVISION-2222222222222222`

### 2.1 继承与变化概述

| 项 | 旧修订含义 | 候选变化 | 下游处置 |
|---|---|---|---|
| 标题 | 预约区间小组件 | → **预约申请工具** | 领域、架构、基线标题同步 |
| 目的 | 整数分钟区间校验与时长计算 | → 提供预约申请的区间校验、成员撤回和负责人周报 | 领域增加申请生命周期、周报读取 |
| 主要用户 | 仅"调用组件的业务开发者" | → 增加"申请成员"和"负责人" | 领域增加三类参与者和决定权 |
| 问题 | 仅非法时间顺序 | → 增加"无法撤回待审核申请"和"无法查看周汇总" | 领域增加相应场景 |
| 预期结果 | 仅时长或 ValueError | → 增加"成员成功撤回"和"负责人读取周报" | 领域增加结果事实 |
| 产品能力 | 仅区间校验 | → 增加"撤回待审核申请"和"读取周报" | 领域增加能力事实和场景闭包 |
| 非目标 | 不增加日期/界面/持久化/远程服务 | → 修订为更精确的排除列表 | 领域边界调整 |
| 约束 | 保持函数签名 | → 增加身份信任、并发安全、审计完整性 | 领域增加规则和不变量 |
| 成功判断 | 仅区间校验 | → 增加撤回和周报的验收条件 | 每条追溯对应结果 |
| 交付阶段 | 仅隔离测试阶段 | → 两个阶段：核心申请域 + 周报能力 | 架构阶段同步 |

### 2.2 完整候选正文

```yaml
schema_version: strixnova.project-product-definition.v1
product_id: PRODUCT-1111111111111111
revision:
  revision_id: REVISION-2222222222222222
  status: draft
  supersedes_revision_id: REVISION-1111111111111111
  confirmed_by_owner_id: null
  confirmed_on: null
title: 预约申请工具
purpose: >-
  提供预约申请的区间校验、成员撤回待审核申请和负责人查看每周汇总的本地终端工具。
product_owner:
  owner_id: OWNER-1111111111111111
  display_name: 项目负责人
primary_users:
  - user_id: USER-1111111111111111
    title: 调用组件的业务开发者
    description: 在登记预约申请前取得合法的区间时长或明确拒绝。
  - user_id: USER-2222222222222222
    title: 申请成员
    description: 提交并管理本人的预约申请，可撤回仍处于待审核状态的申请。
  - user_id: USER-3333333333333333
    title: 负责人
    description: 审批预约申请并查看每周汇总报告。
problems:
  - problem_id: PROBLEM-1111111111111111
    user_ids: [USER-1111111111111111]
    statement: 不合法的时间顺序不能作为有效预约区间继续使用。
  - problem_id: PROBLEM-2222222222222222
    user_ids: [USER-2222222222222222]
    statement: 成员无法撤回仍待审核的预约申请，只能等审批人处理。
  - problem_id: PROBLEM-3333333333333333
    user_ids: [USER-3333333333333333]
    statement: 负责人无法快速了解本周预约申请的整体状态。
desired_outcomes:
  - outcome_id: OUTCOME-1111111111111111
    statement: 合法区间返回原有时长，不合法顺序得到 ValueError。
  - outcome_id: OUTCOME-2222222222222222
    statement: 成员可撤回本人待审核的申请，操作有审计记录。
  - outcome_id: OUTCOME-3333333333333333
    statement: 负责人能按自然周查看当前状态的汇总，不含成员私人联系方式。
capabilities:
  - capability_id: CAPABILITY-1111111111111111
    title: 预约区间校验
    description: 通过 duration(start, end) 校验整数刻度顺序并返回时长。
    outcome_ids: [OUTCOME-1111111111111111]
  - capability_id: CAPABILITY-2222222222222222
    title: 撤回待审核申请
    description: 申请成员撤回本人仍处于待审核状态的预约申请。
    outcome_ids: [OUTCOME-2222222222222222]
  - capability_id: CAPABILITY-3333333333333333
    title: 读取周报
    description: 负责人按本地已指定的自然周统计预约申请的当前状态分布。
    outcome_ids: [OUTCOME-3333333333333333]
non_goals:
  - non_goal_id: NONGOAL-1111111111111111
    statement: 不增加日期转换或时区处理。
  - non_goal_id: NONGOAL-2222222222222222
    statement: 不实现网页或网络服务界面；界面限定为本地终端交互。
  - non_goal_id: NONGOAL-3333333333333333
    statement: 不实现自动发送周报。
  - non_goal_id: NONGOAL-4444444444444444
    statement: 不实现缴费功能。
  - non_goal_id: NONGOAL-5555555555555555
    statement: 不实现已批准预约的取消（已批准预约由审批人另行处理，不在本轮范围）。
  - non_goal_id: NONGOAL-6666666666666666
    statement: 周报不含成员私人联系方式。
constraints:
  - constraint_id: CONSTRAINT-AAAAAAAAAAAAAAAA
    statement: 保持 duration 函数签名和合法区间的既有返回行为。
  - constraint_id: CONSTRAINT-BBBBBBBBBBBBBBBB
    statement: >-
      身份来自可信宿主会话，不信任传入角色或所有者字段。
      一名成员只能操作本人申请。
  - constraint_id: CONSTRAINT-CCCCCCCCCCCCCCCC
    statement: >-
      撤回与审批并发时只允许一个版本成功；响应丢失后可查询实际状态。
  - constraint_id: CONSTRAINT-DDDDDDDDDDDDDDDD
    statement: >-
      审计保留操作者、原状态、新状态和操作身份；重复撤回返回相同结果且不重复记审计。
  - constraint_id: CONSTRAINT-EEEEEEEEEEEEEEEE
    statement: >-
      两个产品单元（成员服务与运营汇总）必须共用申请身份、状态含义和决定权，不能各自定义。
success_criteria:
  - criterion_id: CRITERION-1111111111111111
    statement: 合法区间仍返回 end-start；结束不晚于开始时稳定拒绝。
    outcome_ids: [OUTCOME-1111111111111111]
  - criterion_id: CRITERION-2222222222222222
    statement: >-
      成员撤回本人待审核申请后，该申请状态变为已撤回，且审计记录完整。
      对非待审核状态的申请尝试撤回被拒绝。
      对他人申请的撤回被拒绝。
    outcome_ids: [OUTCOME-2222222222222222]
  - criterion_id: CRITERION-3333333333333333
    statement: >-
      负责人读取周报后，得到按指定自然周的申请状态分布统计，
      不包含成员私人联系方式，不包含本人不可见的数据。
    outcome_ids: [OUTCOME-3333333333333333]
delivery_stages:
  - stage_id: STAGE-1111111111111111
    title: 核心申请域与撤回
    commitment: current_target
    description: >-
      覆盖区间校验（保持不变）、申请生命周期、成员撤回和审计。
      本地终端交互。
  - stage_id: STAGE-2222222222222222
    title: 负责人周报
    commitment: current_target
    description: >-
      负责人通过本地终端读取按自然周统计的申请状态分布。
      可在核心域稳定后独立交付。
unresolved_decisions: []
```

---

## 三、领域模型候选 `MODELREV-2222222222222222`

### 3.1 继承与变化概述

| 项 | 旧修订含义 | 候选变化 | 理由 |
|---|---|---|---|
| 模型标题 | 预约区间领域 | → **预约申请领域** | 领域对象从纯区间扩展为申请实体 |
| 产品定义引用 | `REVISION-1111111111111111` | → `REVISION-2222222222222222` | 产品定义变化 |
| 现行事实 | 2 条（上下文 + 不变量） | → 完整闭包（见下方来源正文） | 新能力需要完整领域解释 |
| 旧事实 FACT-2222222222222222 | 预约区间校验上下文 | 被替代为新的限界上下文 | 责任范围扩大 |
| 旧事实 FACT-3333333333333333 | 合法区间必须有正时长 | 保留（身份和含义不变） | 区间校验规则不受影响 |

### 3.2 根文件候选

```yaml
schema_version: strixnova.project-domain-model.v1
model_id: MODEL-1111111111111111
revision:
  revision_id: MODELREV-2222222222222222
  status: draft
  supersedes_revision_id: MODELREV-1111111111111111
  confirmed_by_owner_id: null
  confirmed_on: null
product_definition_ref:
  product_id: PRODUCT-1111111111111111
  revision_id: REVISION-2222222222222222
title: 预约申请领域
purpose: >-
  定义预约申请的区间校验、申请生命周期、撤回行为、审计、
  身份信任和周报读取的业务含义与规则。
root_collection_paths:
  - docs/domain/collections/core.yaml
unresolved_decisions: []
```

### 3.3 集合路由候选

```yaml
schema_version: strixnova.project-domain-collection.v1
model_id: MODEL-1111111111111111
model_revision_id: MODELREV-2222222222222222
collection_id: COLL-1111111111111111
title: 预约申请核心事实
routing_summary: 参与者、决定权、实体、生命周期、规则、场景和上下文边界。
child_collection_paths: []
sources:
  - source_id: SRC-1111111111111111
    title: 预约申请核心事实
    routing_summary: 产品能力涉及的全部规范业务事实。
    path: docs/domain/sources/core.yaml
```

### 3.4 来源文件候选（完整事实闭包）

> [!NOTE]
> 以下事实列表中，旧事实 `FACT-2222222222222222` 被替代（`superseded`），旧事实 `FACT-3333333333333333` 保留。新事实使用新身份。

```yaml
schema_version: strixnova.project-domain-source.v1
model_id: MODEL-1111111111111111
model_revision_id: MODELREV-2222222222222222
source_id: SRC-1111111111111111
scope_fact_ids: [FACT-A000000000000001]
facts:
  # ── 旧事实：被替代 ──────────────────────────────
  - fact_id: FACT-2222222222222222
    status: draft
    title: 预约区间校验上下文（已替代）
    kind: bounded_context
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: []
    dependency_fact_ids: []
    lineage:
      - relation: superseded_by
        target_fact_id: FACT-A000000000000001
    retirement_reason: >-
      责任范围从纯区间校验扩展为预约申请域；
      由 FACT-A000000000000001 替代。

  # ── 旧事实：保留 ──────────────────────────────
  - fact_id: FACT-3333333333333333
    status: draft
    title: 合法区间必须有正时长
    kind: domain_invariant
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: [FACT-A000000000000001]
    content:
      statement: end 必须严格大于 start；合法时长为 end-start，不合法顺序抛出 ValueError。
      protected_fact_ids: [FACT-A000000000000001]

  # ── 限界上下文 ──────────────────────────────
  - fact_id: FACT-A000000000000001
    status: draft
    title: 预约申请域
    kind: bounded_context
    product_capability_ids:
      - CAPABILITY-1111111111111111
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: []
    dependency_fact_ids: []
    content:
      responsibility: >-
        管理预约申请的区间校验、生命周期状态、成员撤回、
        审计记录和负责人周报读取。
      decisions:
        - 申请身份、状态含义和决定权在所有单元中统一定义。
        - 身份来自可信宿主会话，不信任传入角色或所有者字段。
        - 只允许待审核状态撤回。
        - 撤回与审批并发时只允许一个版本成功。
      excluded_responsibilities:
        - 不负责已批准预约的取消。
        - 不负责缴费。
        - 不负责自动发送周报。
        - 不负责日期转换或时区处理。

  # ── 参与者 ──────────────────────────────
  - fact_id: FACT-A000000000000002
    status: draft
    title: 申请成员
    kind: actor
    product_capability_ids:
      - CAPABILITY-1111111111111111
      - CAPABILITY-2222222222222222
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      role: 提交预约申请，管理本人申请，包括撤回待审核申请。
      responsibilities:
        - 提交预约申请。
        - 撤回本人待审核申请。
        - 查询本人申请的实际状态。
      not_responsible_for:
        - 撤回他人申请。
        - 审批任何申请。
        - 撤回非待审核状态的申请。

  - fact_id: FACT-A000000000000003
    status: draft
    title: 负责人
    kind: actor
    product_capability_ids:
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      role: 审批预约申请并查看运营汇总。
      responsibilities:
        - 审批或拒绝待审核申请。
        - 读取按自然周统计的预约申请周报。
      not_responsible_for:
        - 提交预约申请。
        - 代成员撤回申请。

  - fact_id: FACT-A000000000000004
    status: draft
    title: 调用组件的业务开发者
    kind: actor
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      role: 在登记预约申请前取得合法的区间时长或明确拒绝。
      responsibilities:
        - 调用区间校验获取时长或错误。
      not_responsible_for:
        - 管理申请生命周期。
        - 撤回或审批申请。

  # ── 决定权 ──────────────────────────────
  - fact_id: FACT-A000000000000005
    status: draft
    title: 申请审批决定权
    kind: decision_authority
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000002
      - FACT-A000000000000003
    content:
      decision: 决定一份待审核申请是批准还是拒绝。
      authority_actor_fact_id: FACT-A000000000000003
      candidate_provider_actor_fact_ids: [FACT-A000000000000002]
      non_authority_actor_fact_ids: [FACT-A000000000000002]

  - fact_id: FACT-A000000000000006
    status: draft
    title: 申请撤回决定权
    kind: decision_authority
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000002
    content:
      decision: 决定撤回一份本人的待审核申请。
      authority_actor_fact_id: FACT-A000000000000002
      candidate_provider_actor_fact_ids: []
      non_authority_actor_fact_ids: [FACT-A000000000000003]

  # ── 术语 ──────────────────────────────
  - fact_id: FACT-A000000000000007
    status: draft
    title: 术语-预约申请
    kind: term
    product_capability_ids:
      - CAPABILITY-1111111111111111
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      term: 预约申请
      definition: >-
        成员提交的对特定时间区间的预约请求，具有独立身份和生命周期状态。
        不同于已生效预约：申请需经审批后才产生预约。

  - fact_id: FACT-A000000000000008
    status: draft
    title: 术语-已生效预约
    kind: term
    product_capability_ids:
      - CAPABILITY-2222222222222222
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: [FACT-A000000000000007]
    content:
      term: 已生效预约
      definition: >-
        预约申请经负责人批准后产生的预约记录。
        本轮不实现已生效预约的取消；取消已生效预约由审批人另行处理。

  # ── 值对象 ──────────────────────────────
  - fact_id: FACT-A000000000000009
    status: draft
    title: 预约区间
    kind: value_object
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      meaning: 由开始刻度和结束刻度组成的整数分钟区间，表示预约申请的时间范围。
      components:
        - name: start
          meaning: 开始整数分钟刻度。
        - name: end
          meaning: 结束整数分钟刻度，必须严格大于 start。
      invariants:
        - end 严格大于 start。

  - fact_id: FACT-A00000000000000A
    status: draft
    title: 审计条目
    kind: value_object
    product_capability_ids:
      - CAPABILITY-2222222222222222
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      meaning: 一次状态变更操作的不可变记录。
      components:
        - name: operator_id
          meaning: 执行操作的成员身份（来自可信宿主会话）。
        - name: original_status
          meaning: 操作前的申请状态。
        - name: new_status
          meaning: 操作后的申请状态。
        - name: operation_identity
          meaning: 操作身份（如撤回、审批、拒绝）。
      invariants:
        - 每条审计条目创建后不可修改。

  # ── 领域实体 ──────────────────────────────
  - fact_id: FACT-A00000000000000B
    status: draft
    title: 预约申请
    kind: domain_entity
    product_capability_ids:
      - CAPABILITY-1111111111111111
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000009
      - FACT-A000000000000002
    content:
      identity: >-
        每份预约申请有全局唯一的申请标识，该标识在所有单元中统一使用。
      responsibilities:
        - 持有预约区间、申请成员身份、当前状态和审计历史。
        - 执行状态转换规则。
      lifecycle_fact_id: FACT-A00000000000000C

  # ── 生命周期 ──────────────────────────────
  - fact_id: FACT-A00000000000000C
    status: draft
    title: 预约申请生命周期
    kind: lifecycle
    product_capability_ids:
      - CAPABILITY-2222222222222222
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000B
    content:
      subject_fact_id: FACT-A00000000000000B
      states:
        - state: 待审核
          meaning: 申请已提交，等待负责人审批决定。
        - state: 已批准
          meaning: 负责人已批准该申请，产生已生效预约。
        - state: 已拒绝
          meaning: 负责人已拒绝该申请。
        - state: 已撤回
          meaning: 申请成员已主动撤回该待审核申请。
      transitions:
        - from_state: 待审核
          to_state: 已批准
          trigger: 负责人批准该申请。
          guards: [申请仍处于待审核状态]
          resulting_event_fact_ids: [FACT-A00000000000000D]
        - from_state: 待审核
          to_state: 已拒绝
          trigger: 负责人拒绝该申请。
          guards: [申请仍处于待审核状态]
          resulting_event_fact_ids: [FACT-A00000000000000D]
        - from_state: 待审核
          to_state: 已撤回
          trigger: 申请成员撤回本人申请。
          guards:
            - 操作者是申请的提交成员。
            - 申请仍处于待审核状态。
          resulting_event_fact_ids: [FACT-A00000000000000D]

  # ── 领域事件 ──────────────────────────────
  - fact_id: FACT-A00000000000000D
    status: draft
    title: 申请状态变更事件
    kind: domain_event
    product_capability_ids:
      - CAPABILITY-2222222222222222
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000B
      - FACT-A00000000000000A
    content:
      meaning: 一份预约申请的状态发生了变更。
      occurs_when: 预约申请经历任何合法状态转换。
      subject_fact_ids: [FACT-A00000000000000B]
      information:
        - 申请标识。
        - 原状态。
        - 新状态。
        - 操作者身份。
        - 操作身份。

  # ── 领域规则 ──────────────────────────────
  - fact_id: FACT-A00000000000000E
    status: draft
    title: 只允许操作本人申请
    kind: domain_rule
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000002
      - FACT-A00000000000000B
    content:
      statement: 一名成员只能操作本人提交的预约申请，不能操作他人申请。
      applies_when: 成员尝试对预约申请执行撤回操作时。

  - fact_id: FACT-A00000000000000F
    status: draft
    title: 只允许待审核状态撤回
    kind: domain_rule
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000B
      - FACT-A00000000000000C
    content:
      statement: 只有处于待审核状态的申请才允许撤回；其他状态的撤回请求被拒绝。
      applies_when: 成员尝试撤回一份预约申请时。

  - fact_id: FACT-A000000000000010
    status: draft
    title: 重复撤回幂等规则
    kind: domain_rule
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000B
      - FACT-A00000000000000C
      - FACT-A00000000000000A
    content:
      statement: >-
        对已处于已撤回状态的申请再次撤回，返回相同结果（已撤回），
        且不重复记录审计条目。
      applies_when: 成员对已撤回的本人申请再次执行撤回操作时。

  - fact_id: FACT-A000000000000011
    status: draft
    title: 身份信任规则
    kind: domain_rule
    product_capability_ids:
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000002
      - FACT-A000000000000003
    content:
      statement: >-
        操作者身份来自可信宿主会话，不信任请求中传入的角色或所有者字段。
      applies_when: 任何涉及身份判断的操作执行时。

  - fact_id: FACT-A000000000000012
    status: draft
    title: 周报仅负责人可读
    kind: domain_rule
    product_capability_ids: [CAPABILITY-3333333333333333]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000003
    content:
      statement: 周报仅负责人可读，不向申请成员或其他角色公开。
      applies_when: 任何主体尝试读取周报时。

  # ── 领域不变量 ──────────────────────────────
  - fact_id: FACT-A000000000000013
    status: draft
    title: 并发安全不变量
    kind: domain_invariant
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000B
      - FACT-A00000000000000C
    content:
      statement: >-
        撤回与审批并发时，只允许一个版本成功。
        一份申请在同一时刻只能有一个合法的状态转换生效。
      protected_fact_ids:
        - FACT-A00000000000000B
        - FACT-A00000000000000C

  - fact_id: FACT-A000000000000014
    status: draft
    title: 审计完整性不变量
    kind: domain_invariant
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000A
      - FACT-A00000000000000B
    content:
      statement: >-
        每次成功的状态变更都恰好产生一条审计条目，
        包含操作者、原状态、新状态和操作身份。
        幂等重复操作不额外产生审计条目。
      protected_fact_ids:
        - FACT-A00000000000000A
        - FACT-A00000000000000B

  - fact_id: FACT-A000000000000015
    status: draft
    title: 统一申请身份不变量
    kind: domain_invariant
    product_capability_ids:
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A00000000000000B
    content:
      statement: >-
        成员服务与运营汇总两个单元使用统一的申请身份、状态含义和决定权，
        不能各自定义独立的申请模型。
      protected_fact_ids:
        - FACT-A00000000000000B

  # ── 领域中的产品能力 ──────────────────────────
  - fact_id: FACT-A000000000000016
    status: draft
    title: 领域-预约区间校验
    kind: product_capability
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000004
      - FACT-A000000000000009
    content:
      definition: 对给定整数分钟区间校验顺序并返回时长或拒绝。
      primary_actor_fact_ids: [FACT-A000000000000004]
      supporting_actor_fact_ids: []
      scenario_requirements:
        - scenario_type: normal
          applicability: required
          reason: 必须说明合法区间返回时长的正常路径。
        - scenario_type: blocking
          applicability: required
          reason: 必须说明不合法顺序被拒绝。
        - scenario_type: correction
          applicability: not_applicable
          reason: 纯函数校验无中间状态可纠正，调用方传入新参数重试。
        - scenario_type: cancellation
          applicability: not_applicable
          reason: 纯函数不持有状态，没有取消含义。

  - fact_id: FACT-A000000000000017
    status: draft
    title: 领域-撤回待审核申请
    kind: product_capability
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000002
      - FACT-A000000000000003
      - FACT-A00000000000000B
    content:
      definition: 申请成员撤回本人仍处于待审核状态的预约申请。
      primary_actor_fact_ids: [FACT-A000000000000002]
      supporting_actor_fact_ids: []
      scenario_requirements:
        - scenario_type: normal
          applicability: required
          reason: 必须说明成功撤回待审核申请的完整路径。
        - scenario_type: blocking
          applicability: required
          reason: 必须说明何时阻断撤回（非本人、非待审核、并发冲突）。
        - scenario_type: correction
          applicability: required
          reason: 必须说明响应丢失后如何通过查询确认实际状态。
        - scenario_type: cancellation
          applicability: not_applicable
          reason: 撤回本身就是取消操作，没有对撤回的取消。

  - fact_id: FACT-A000000000000018
    status: draft
    title: 领域-读取周报
    kind: product_capability
    product_capability_ids: [CAPABILITY-3333333333333333]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000003
      - FACT-A00000000000000B
    content:
      definition: 负责人按本地已指定的自然周统计预约申请的当前状态分布。
      primary_actor_fact_ids: [FACT-A000000000000003]
      supporting_actor_fact_ids: []
      scenario_requirements:
        - scenario_type: normal
          applicability: required
          reason: 必须说明负责人成功读取周报的路径。
        - scenario_type: blocking
          applicability: required
          reason: 必须说明非负责人被拒绝读取周报。
        - scenario_type: correction
          applicability: not_applicable
          reason: 周报是只读统计，没有需要纠正的中间状态。
        - scenario_type: cancellation
          applicability: not_applicable
          reason: 读取操作没有持久副作用，没有取消含义。

  # ── 领域场景 ──────────────────────────────
  - fact_id: FACT-A000000000000019
    status: draft
    title: 正常-区间校验
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000016
      - FACT-A000000000000004
      - FACT-A000000000000009
    content:
      scenario_type: normal
      capability_fact_id: FACT-A000000000000016
      actor_fact_ids: [FACT-A000000000000004]
      preconditions:
        - 调用方持有两个整数分钟刻度。
      trigger: 调用 duration(start, end)。
      steps:
        - 校验 end 是否严格大于 start。
        - 计算 end - start 作为时长。
      outcome: 返回整数时长。
      postconditions:
        - 无状态变更，纯函数行为保持不变。

  - fact_id: FACT-A00000000000001A
    status: draft
    title: 阻断-区间校验
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-1111111111111111]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000016
      - FACT-A000000000000004
    content:
      scenario_type: blocking
      capability_fact_id: FACT-A000000000000016
      actor_fact_ids: [FACT-A000000000000004]
      preconditions:
        - 调用方持有两个整数分钟刻度。
      trigger: 调用 duration(start, end)，其中 end <= start。
      steps:
        - 校验 end 是否严格大于 start，结果为否。
      outcome: 抛出 ValueError，不返回时长。
      postconditions:
        - 无状态变更。

  - fact_id: FACT-A00000000000001B
    status: draft
    title: 正常-撤回待审核申请
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000017
      - FACT-A000000000000002
      - FACT-A00000000000000B
      - FACT-A00000000000000C
      - FACT-A00000000000000A
    content:
      scenario_type: normal
      capability_fact_id: FACT-A000000000000017
      actor_fact_ids: [FACT-A000000000000002]
      preconditions:
        - 成员已通过可信宿主会话认证。
        - 该成员有一份本人提交的待审核预约申请。
      trigger: 成员请求撤回指定申请。
      steps:
        - 从可信宿主会话获取操作者身份。
        - 校验申请归属于操作者本人。
        - 校验申请当前处于待审核状态。
        - 使用乐观并发控制尝试将状态从待审核转为已撤回。
        - 记录一条审计条目（操作者、待审核→已撤回、撤回）。
      outcome: 申请状态变为已撤回，操作成功。
      postconditions:
        - 该申请不可再被审批或再次撤回（幂等重复除外）。
        - 审计记录完整保留。

  - fact_id: FACT-A00000000000001C
    status: draft
    title: 阻断-撤回待审核申请
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000017
      - FACT-A000000000000002
      - FACT-A00000000000000E
      - FACT-A00000000000000F
      - FACT-A000000000000013
    content:
      scenario_type: blocking
      capability_fact_id: FACT-A000000000000017
      actor_fact_ids: [FACT-A000000000000002]
      preconditions:
        - 成员已通过可信宿主会话认证。
      trigger: 成员请求撤回一份申请，但该申请不满足撤回条件。
      steps:
        - 校验归属：若申请不属于操作者本人，拒绝。
        - 校验状态：若申请不处于待审核状态，拒绝。
        - 校验并发：若撤回与审批并发冲突，只让一个成功，另一个拒绝。
      outcome: 撤回被拒绝，申请状态不变。
      postconditions:
        - 不产生审计条目。
        - 申请保持原状态。

  - fact_id: FACT-A00000000000001D
    status: draft
    title: 纠正-撤回待审核申请
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-2222222222222222]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000017
      - FACT-A000000000000002
      - FACT-A000000000000010
    content:
      scenario_type: correction
      capability_fact_id: FACT-A000000000000017
      actor_fact_ids: [FACT-A000000000000002]
      preconditions:
        - 成员之前发起过撤回请求但未收到明确响应。
      trigger: 成员再次发起撤回或查询申请状态。
      steps:
        - 查询该申请的实际当前状态。
        - 若已处于已撤回状态（之前的撤回实际成功），返回已撤回结果，不重复记审计。
        - 若仍处于待审核状态（之前的撤回实际未成功），按正常流程执行撤回。
        - 若已被审批或拒绝（并发竞争失败），返回当前实际状态。
      outcome: 成员确认了申请的实际状态。
      postconditions:
        - 系统状态与审计始终一致，不因重试产生不一致。

  - fact_id: FACT-A00000000000001E
    status: draft
    title: 正常-读取周报
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-3333333333333333]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000018
      - FACT-A000000000000003
      - FACT-A00000000000000B
    content:
      scenario_type: normal
      capability_fact_id: FACT-A000000000000018
      actor_fact_ids: [FACT-A000000000000003]
      preconditions:
        - 操作者已通过可信宿主会话认证为负责人。
      trigger: 负责人请求读取某自然周的周报。
      steps:
        - 确认操作者为负责人。
        - 按本地已指定的自然周边界确定统计范围。
        - 统计该周内预约申请的当前状态分布。
        - 排除成员私人联系方式。
      outcome: 返回该自然周的申请状态分布统计。
      postconditions:
        - 无状态变更，只读操作。

  - fact_id: FACT-A00000000000001F
    status: draft
    title: 阻断-读取周报
    kind: domain_scenario
    product_capability_ids: [CAPABILITY-3333333333333333]
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids:
      - FACT-A000000000000018
      - FACT-A000000000000002
      - FACT-A000000000000012
    content:
      scenario_type: blocking
      capability_fact_id: FACT-A000000000000018
      actor_fact_ids: [FACT-A000000000000002]
      preconditions:
        - 操作者已通过可信宿主会话认证，但身份为申请成员而非负责人。
      trigger: 非负责人尝试读取周报。
      steps:
        - 校验操作者身份不是负责人。
      outcome: 拒绝读取，不返回任何周报数据。
      postconditions:
        - 无状态变更，无数据泄露。

  # ── 外部系统 ──────────────────────────────
  - fact_id: FACT-A000000000000020
    status: draft
    title: 可信宿主会话
    kind: external_system
    product_capability_ids:
      - CAPABILITY-2222222222222222
      - CAPABILITY-3333333333333333
    scope_fact_ids: [FACT-A000000000000001]
    dependency_fact_ids: []
    content:
      responsibility: 提供已认证的操作者身份。
      provides_facts:
        - 操作者的唯一身份标识。
        - 操作者的角色（成员或负责人）。
      does_not_decide:
        - 不决定申请的审批结果。
        - 不决定周报的统计范围。
```

---

## 四、目标架构候选 `ARCHREV-2222222222222222`

### 4.1 继承与变化概述

| 项 | 旧修订含义 | 候选变化 | 理由 |
|---|---|---|---|
| 模块 | 单一区间校验模块 | → 四个模块（申请域、成员服务、运营汇总、终端适配） | 新能力需要领域层、应用层和适配层分离 |
| 关系 | 无 | → 成员服务和运营汇总依赖申请域；终端适配依赖两个应用模块 | 保证领域统一 |
| 约束 | 无 | → 身份信任约束、并发安全约束、本地终端约束 | 落实产品约束 |
| 阶段 | 单一阶段 | → 两个阶段 | 匹配产品交付阶段 |

### 4.2 根文件候选

```yaml
schema_version: strixnova.project-architecture-description.v1
architecture_id: ARCH-1111111111111111
revision:
  revision_id: ARCHREV-2222222222222222
  status: draft
  supersedes_revision_id: ARCHREV-1111111111111111
  confirmed_by_owner_id: null
  confirmed_on: null
domain_model_ref:
  model_id: MODEL-1111111111111111
  revision_id: MODELREV-2222222222222222
title: 预约申请工具架构
purpose: >-
  定义申请域、成员服务、运营汇总和终端适配的责任、依赖和阶段。
artifact_paths:
  modules: docs/architecture/architecture-modules.yaml
  relationships: docs/architecture/architecture-relationships.yaml
  constraints: docs/architecture/architecture-constraints.yaml
  domain_fact_dispositions: docs/architecture/architecture-domain-facts.yaml
  implementation_stages: docs/architecture/architecture-stages.yaml
unresolved_decisions: []
```

### 4.3 模块目录候选

```yaml
schema_version: strixnova.architecture-modules.v1
architecture_id: ARCH-1111111111111111
architecture_revision_id: ARCHREV-2222222222222222
modules:
  - module_id: MODULE-A000000000000001
    title: 申请域
    layer: domain
    responsibility: >-
      承载预约申请实体、生命周期状态转换、区间校验、领域规则、
      不变量和审计条目的完整领域逻辑。
    not_responsible_for:
      - 不负责终端展示。
      - 不负责统计报表生成。
      - 不负责宿主会话管理。
    public_interface:
      interface_id: INTERFACE-A000000000000001
      title: 申请域接口
      operations:
        - name: 校验区间
          meaning: 校验整数分钟区间的顺序并返回时长或拒绝。
        - name: 创建申请
          meaning: 从合法区间创建一份待审核预约申请。
        - name: 撤回申请
          meaning: 尝试将待审核申请状态转为已撤回。
        - name: 审批申请
          meaning: 尝试将待审核申请状态转为已批准或已拒绝。
        - name: 查询申请状态
          meaning: 返回指定申请的当前状态。

  - module_id: MODULE-A000000000000002
    title: 成员服务
    layer: application
    responsibility: >-
      协调成员的撤回操作，执行身份校验和归属校验，
      调用申请域完成状态转换。
    not_responsible_for:
      - 不负责定义申请生命周期规则。
      - 不负责终端展示。
      - 不负责周报统计。
    public_interface:
      interface_id: INTERFACE-A000000000000002
      title: 成员服务接口
      operations:
        - name: 撤回本人申请
          meaning: 接收可信身份和申请标识，协调撤回流程并返回结果。
        - name: 查询本人申请
          meaning: 接收可信身份和申请标识，返回该申请的当前状态。

  - module_id: MODULE-A000000000000003
    title: 运营汇总
    layer: query
    responsibility: >-
      按自然周统计预约申请的当前状态分布，
      生成不含成员私人联系方式的周报。
    not_responsible_for:
      - 不负责修改申请状态。
      - 不负责定义申请身份或状态含义。
      - 不负责终端展示。
    public_interface:
      interface_id: INTERFACE-A000000000000003
      title: 运营汇总接口
      operations:
        - name: 读取周报
          meaning: >-
            接收可信身份和自然周参数，返回该周申请状态分布统计。

  - module_id: MODULE-A000000000000004
    title: 终端适配
    layer: adapter
    responsibility: >-
      提供本地终端命令行交互界面，将用户输入转化为
      成员服务或运营汇总调用，将结果格式化输出。
    not_responsible_for:
      - 不负责领域规则。
      - 不负责网页或网络服务。
      - 不负责持久化决策。
    public_interface:
      interface_id: INTERFACE-A000000000000004
      title: 终端适配接口
      operations:
        - name: 处理终端命令
          meaning: 解析命令行输入，路由到对应的应用服务。
```

### 4.4 关系目录候选

```yaml
schema_version: strixnova.architecture-relationships.v1
architecture_id: ARCH-1111111111111111
architecture_revision_id: ARCHREV-2222222222222222
default_relationship_policy: forbidden
relationships:
  - relationship_id: RELATION-A000000000000001
    from_module_id: MODULE-A000000000000002
    to_module_id: MODULE-A000000000000001
    mode: direct
    mediator_module_id: null
    contract: 成员服务通过申请域公开接口执行撤回和查询，不绕过领域规则。
    reason: 成员服务是应用协调层，领域规则集中在申请域。

  - relationship_id: RELATION-A000000000000002
    from_module_id: MODULE-A000000000000003
    to_module_id: MODULE-A000000000000001
    mode: read_only_projection
    mediator_module_id: null
    contract: 运营汇总只读取申请域的申请状态数据用于统计，不修改任何申请状态。
    reason: 周报是只读统计，必须使用统一的申请身份和状态含义。

  - relationship_id: RELATION-A000000000000003
    from_module_id: MODULE-A000000000000004
    to_module_id: MODULE-A000000000000002
    mode: direct
    mediator_module_id: null
    contract: 终端适配将成员操作路由到成员服务接口。
    reason: 终端层不直接调用领域，通过应用层协调。

  - relationship_id: RELATION-A000000000000004
    from_module_id: MODULE-A000000000000004
    to_module_id: MODULE-A000000000000003
    mode: direct
    mediator_module_id: null
    contract: 终端适配将负责人周报请求路由到运营汇总接口。
    reason: 终端层不直接调用领域，通过查询层获取统计结果。
```

### 4.5 约束目录候选

```yaml
schema_version: strixnova.architecture-constraints.v1
architecture_id: ARCH-1111111111111111
architecture_revision_id: ARCHREV-2222222222222222
constraints:
  - constraint_id: CONSTRAINT-A000000000000001
    title: 身份来源约束
    statement: >-
      操作者身份只从可信宿主会话获取，任何模块不得信任请求中
      传入的角色或所有者字段。
    applies_to_module_ids:
      - MODULE-A000000000000002
      - MODULE-A000000000000003
      - MODULE-A000000000000004
    verification_methods:
      - method_type: behavior_acceptance
        description: 验证使用传入角色字段的操作被拒绝。

  - constraint_id: CONSTRAINT-A000000000000002
    title: 并发安全约束
    statement: >-
      对同一申请的并发状态转换只允许一个版本成功。
    applies_to_module_ids:
      - MODULE-A000000000000001
    verification_methods:
      - method_type: behavior_acceptance
        description: 验证并发撤回与审批只有一个成功。

  - constraint_id: CONSTRAINT-A000000000000003
    title: 本地终端约束
    statement: >-
      界面限定为本地终端交互，不增加网页或网络服务。
    applies_to_module_ids:
      - MODULE-A000000000000004
    verification_methods:
      - method_type: manual_review
        description: 审查实现不包含 HTTP 服务或网页资源。
```

### 4.6 领域事实处置目录候选

```yaml
schema_version: strixnova.architecture-domain-fact-dispositions.v1
architecture_id: ARCH-1111111111111111
architecture_revision_id: ARCHREV-2222222222222222
domain_model_ref:
  model_id: MODEL-1111111111111111
  revision_id: MODELREV-2222222222222222
dispositions:
  # FACT-2222222222222222 被替代，不再出现在现行处置中

  - domain_fact_id: FACT-3333333333333333
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 区间正时长不变量由申请域承载。

  - domain_fact_id: FACT-A000000000000001
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 限界上下文是整体边界声明，由全部模块共同体现。

  - domain_fact_id: FACT-A000000000000002
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 申请成员是外部参与者角色，不需独立实现模块。

  - domain_fact_id: FACT-A000000000000003
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 负责人是外部参与者角色，不需独立实现模块。

  - domain_fact_id: FACT-A000000000000004
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 业务开发者是外部调用方，不需独立实现模块。

  - domain_fact_id: FACT-A000000000000005
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: []
    rationale: 审批决定权规则由申请域承载，成员服务协调触发。

  - domain_fact_id: FACT-A000000000000006
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: []
    rationale: 撤回决定权规则由申请域承载，成员服务协调触发。

  - domain_fact_id: FACT-A000000000000007
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 术语定义用于统一理解，不需独立实现模块。

  - domain_fact_id: FACT-A000000000000008
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 术语定义用于统一理解，不需独立实现模块。

  - domain_fact_id: FACT-A000000000000009
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 预约区间值对象由申请域承载。

  - domain_fact_id: FACT-A00000000000000A
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 审计条目值对象由申请域承载。

  - domain_fact_id: FACT-A00000000000000B
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 预约申请实体由申请域承载。

  - domain_fact_id: FACT-A00000000000000C
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 预约申请生命周期由申请域承载。

  - domain_fact_id: FACT-A00000000000000D
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 申请状态变更事件由申请域产生。

  - domain_fact_id: FACT-A00000000000000E
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: [CONSTRAINT-A000000000000001]
    rationale: 只操作本人申请规则由申请域执行，成员服务提供身份。

  - domain_fact_id: FACT-A00000000000000F
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 只允许待审核状态撤回规则由申请域执行。

  - domain_fact_id: FACT-A000000000000010
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 幂等撤回规则由申请域执行。

  - domain_fact_id: FACT-A000000000000011
    disposition_type: architecture_constraint
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: [CONSTRAINT-A000000000000001]
    rationale: 身份信任规则作为全局约束适用于所有接收身份的模块。

  - domain_fact_id: FACT-A000000000000012
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000003
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: [CONSTRAINT-A000000000000001]
    rationale: 周报访问控制由运营汇总模块执行。

  - domain_fact_id: FACT-A000000000000013
    disposition_type: architecture_constraint
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: [CONSTRAINT-A000000000000002]
    rationale: 并发安全不变量作为全局约束由申请域并发机制保证。

  - domain_fact_id: FACT-A000000000000014
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 审计完整性不变量由申请域承载。

  - domain_fact_id: FACT-A000000000000015
    disposition_type: module_relationship
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids:
      - RELATION-A000000000000001
      - RELATION-A000000000000002
    constraint_ids: []
    rationale: >-
      统一申请身份不变量通过成员服务和运营汇总都依赖申请域的关系保证。

  - domain_fact_id: FACT-A000000000000016
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 领域产品能力-区间校验由申请域承载。

  - domain_fact_id: FACT-A000000000000017
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: []
    rationale: 领域产品能力-撤回由申请域承载，成员服务协调。

  - domain_fact_id: FACT-A000000000000018
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000003
    collaborator_module_ids: []
    relationship_ids: [RELATION-A000000000000002]
    constraint_ids: []
    rationale: 领域产品能力-读取周报由运营汇总承载。

  - domain_fact_id: FACT-A000000000000019
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 正常区间校验场景由申请域承载。

  - domain_fact_id: FACT-A00000000000001A
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: 阻断区间校验场景由申请域承载。

  - domain_fact_id: FACT-A00000000000001B
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: []
    rationale: 正常撤回场景由申请域执行，成员服务协调。

  - domain_fact_id: FACT-A00000000000001C
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: []
    rationale: 阻断撤回场景由申请域执行，成员服务协调。

  - domain_fact_id: FACT-A00000000000001D
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000001
    collaborator_module_ids: [MODULE-A000000000000002]
    relationship_ids: [RELATION-A000000000000001]
    constraint_ids: []
    rationale: 纠正撤回场景由申请域执行，成员服务协调。

  - domain_fact_id: FACT-A00000000000001E
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000003
    collaborator_module_ids: []
    relationship_ids: [RELATION-A000000000000002]
    constraint_ids: []
    rationale: 正常读取周报场景由运营汇总承载。

  - domain_fact_id: FACT-A00000000000001F
    disposition_type: primary_module
    primary_module_id: MODULE-A000000000000003
    collaborator_module_ids: []
    relationship_ids: [RELATION-A000000000000002]
    constraint_ids: [CONSTRAINT-A000000000000001]
    rationale: 阻断读取周报场景由运营汇总承载，身份约束全局适用。

  - domain_fact_id: FACT-A000000000000020
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: [CONSTRAINT-A000000000000001]
    rationale: >-
      可信宿主会话是外部系统，本项目不实现它，只通过身份约束信任其提供的身份。
```

### 4.7 实施阶段目录候选

```yaml
schema_version: strixnova.architecture-implementation-stages.v1
architecture_id: ARCH-1111111111111111
architecture_revision_id: ARCHREV-2222222222222222
stages:
  - stage_id: ARCHSTAGE-A000000000000001
    order: 1
    title: 核心申请域与撤回
    scope: current_product_stage
    prerequisite_stage_ids: []
    module_ids:
      - MODULE-A000000000000001
      - MODULE-A000000000000002
      - MODULE-A000000000000004
    entry_conditions:
      - 产品、领域和目标架构已确认。
    completion_conditions:
      - 申请域规则和撤回场景通过真实终端验证。
      - 区间校验既有行为不受影响。

  - stage_id: ARCHSTAGE-A000000000000002
    order: 2
    title: 负责人周报
    scope: current_product_stage
    prerequisite_stage_ids: [ARCHSTAGE-A000000000000001]
    module_ids:
      - MODULE-A000000000000003
    entry_conditions:
      - 核心申请域与撤回已完成。
      - 申请身份和状态含义已统一。
    completion_conditions:
      - 负责人能通过终端读取按自然周统计的周报。
```

---

## 五、工程政策候选 `POLICYREV-2222222222222222`

### 5.1 继承与变化概述

| 项 | 旧修订含义 | 候选变化 | 理由 |
|---|---|---|---|
| 方法采用 | DDD 不采用 | → DDD 有条件采用 | 申请生命周期和领域规则需要领域建模 |
| 政策陈述 | 面向纯函数小组件 | → 增加身份信任、并发安全、审计保全 | 新产品约束 |
| 允许程序 | 仅 python | → 增加 git 和 strixnova | 仓库交付需要 |

### 5.2 完整候选正文

```yaml
schema_version: strixnova.project-engineering-policy.v1
policy_id: POLICY-1111111111111111
revision:
  revision_id: POLICYREV-2222222222222222
  status: draft
  supersedes_revision_id: POLICYREV-1111111111111111
  confirmed_by_owner_id: null
  confirmed_on: null
product_definition_ref:
  product_id: PRODUCT-1111111111111111
  revision_id: REVISION-2222222222222222
base_profile_ref:
  profile_id: strixnova-general-software-engineering
  profile_version: '2026-08-23'
method_adoptions:
  - method_id: ddd
    status: conditional
    reason: >-
      申请生命周期、状态转换规则、决定权和审计需要显式领域建模；
      区间校验保持纯函数不需要完整 DDD 仪式。
    conditions:
      - 限于预约申请实体及其生命周期和关联规则。
    adopted_technique_ids: []
policy_statements:
  quality:
    - 结构、语义和效果证据分开报告。
    - 审计记录的完整性是质量要求的一部分。
  testing:
    - 以真实断言检查函数行为；开发反馈与正式验证记录分别说明。
    - 并发场景需要明确的验证方案，不能仅靠单线程单元测试。
  security:
    - 身份来自可信宿主会话，不信任传入角色或所有者字段。
    - 周报不含成员私人联系方式。
  release:
    - 只验证本地交付。
    - 界面限定为本地终端交互，不增加网页或网络服务。
  operations:
    - 外部操作必须有真实回执。
  maintenance:
    - 新接口接管后删除旧机制。
    - 申请身份和状态含义在所有单元中统一，不各自定义。
  compatibility:
    - 保持 duration 函数签名和合法区间的既有返回行为。
project_sources: []
rule_extensions: []
rule_tailoring: []
verification_command_policy:
  allowed_programs:
    - program: python
      purpose: 在本工程运行已声明的 pytest 验证。
      argument_policy: exact_plan_only
    - program: git
      purpose: 执行明确批准的本地版本管理操作。
      argument_policy: exact_plan_only
    - program: strixnova
      purpose: 执行已确认方案中的 Strixnova 验证。
      argument_policy: exact_plan_only
  forbidden_agent_program_names:
    - agy
    - aider
    - claude
    - codex
    - cursor
    - gemini
    - opencode
    - windsurf
  wrapper_policy: forbidden_unless_exactly_approved
  working_directory_policy: project_or_authorized_worktree_only
  plan_binding_required: true
delivery_gates:
  result_acceptance_before_commit: true
  local_integration_only: true
  external_execution_requires_external_receipt: true
  remote_operations_in_scope: false
evidence_requirements:
  separate_structure_semantics_confirmation_effect_and_conformance: true
  unrun_items_visible: true
  semantic_correctness_machine_proven: false
  external_conformance_without_external_evidence: false
unresolved_decisions: []
```

---

## 六、实现对齐

> [!NOTE]
> 实现对齐不在本候选包中取得确认。上游四类权威确认后，将形成绑定新修订的实现对齐草稿，以当时真实代码如实记录未实现、部分实现和偏离。目前已知：
> - `src.py` 中的 `duration()` 函数将保留并由申请域模块承载，行为不变。
> - `request_projection.py` 是预置待审源码样本，其固定 label 与业务含义存在偏离（已在前次只读澄清中确认），不构成领域权威。
> - 新模块（成员服务、运营汇总、终端适配）尚未实现。

---

## 七、受影响的事项方向

本轮需要两个独立可交付的建设事项（Story），共享上游权威：

| 事项 | 标题 | 独立交付价值 | 依赖 |
|---|---|---|---|
| 事项 A | 撤回待审核申请 | 成员可通过终端撤回本人待审核申请，并发安全，审计完整 | 无前置事项 |
| 事项 B | 负责人周报 | 负责人可通过终端读取自然周统计 | 依赖事项 A 建立的申请域 |

两个事项的方向都以上述候选产品定义、领域模型和目标架构为上游。事项 B 在事项 A 的核心申请域稳定后独立交付。

---

## 八、PRD（只读组合）

### 预约申请工具 — 产品需求文档

**来源修订：** 产品定义 `REVISION-2222222222222222`（draft）、领域模型 `MODELREV-2222222222222222`（draft）

> [!IMPORTANT]
> 本 PRD 是上述候选修订的只读组合视图，不具有独立的确认或修改权力。任何含义变更必须回到对应的权威候选。

#### 1. 目的与受众

**目的：** 将现有预约区间小组件扩展为预约申请工具，使成员能撤回自己的待审核申请，负责人能查看每周汇总。

**受众：**
- **调用组件的业务开发者** — 在登记预约申请前取得合法的区间时长或明确拒绝。
- **申请成员** — 提交并管理本人的预约申请，可撤回仍处于待审核状态的申请。
- **负责人** — 审批预约申请并查看每周汇总报告。

#### 2. 问题与预期结果

| 问题 | 受影响用户 | 预期结果 |
|---|---|---|
| 不合法时间顺序不能作为有效区间 | 业务开发者 | 合法区间返回时长，不合法顺序得到 ValueError |
| 成员无法撤回待审核申请 | 申请成员 | 成员可撤回本人待审核申请，有审计记录 |
| 负责人无法快速了解每周状态 | 负责人 | 按自然周查看状态汇总，不含私人联系方式 |

#### 3. 产品能力

**能力 1：预约区间校验（保持不变）**
- 通过 `duration(start, end)` 校验整数刻度顺序并返回时长。
- 正常路径：合法区间返回 end-start。
- 阻断路径：end ≤ start 时抛出 ValueError。

**能力 2：撤回待审核申请**
- 申请成员撤回本人仍处于待审核状态的预约申请。
- 正常路径：成员认证 → 校验归属 → 校验状态 → 乐观并发撤回 → 审计记录。
- 阻断路径：非本人 / 非待审核 / 并发冲突时拒绝，不产生审计。
- 纠正路径：响应丢失后查询实际状态确认结果；重复撤回幂等返回。

**能力 3：读取周报**
- 负责人按本地已指定的自然周统计申请当前状态分布。
- 正常路径：负责人认证 → 统计 → 返回结果（不含私人联系方式）。
- 阻断路径：非负责人被拒绝，不返回任何数据。

#### 4. 关键业务规则

1. **身份信任：** 身份来自可信宿主会话，不信任传入角色或所有者字段。
2. **本人操作：** 一名成员只能操作本人申请。
3. **状态限制：** 只允许待审核状态撤回。
4. **幂等性：** 重复撤回返回相同结果且不重复记审计。
5. **并发安全：** 撤回与审批并发时只允许一个版本成功。
6. **可查询：** 响应丢失后可查询实际状态。
7. **审计完整：** 保留操作者、原状态、新状态和操作身份。
8. **统一模型：** 两个单元共用申请身份、状态含义和决定权。

#### 5. 排除项

- 不增加日期转换或时区处理。
- 不实现网页或网络服务；界面限定为本地终端交互。
- 不实现自动发送周报。
- 不实现缴费。
- 不实现已批准预约的取消。
- 周报不含成员私人联系方式。

#### 6. 约束

- 保持 `duration` 函数签名和合法区间的既有返回行为。
- 身份信任、并发安全和审计完整性是硬约束。
- 两个单元（成员服务与运营汇总）共用申请模型。

#### 7. 成功判断

| 判断 | 验收要求 |
|---|---|
| 区间校验 | 合法区间返回 end-start；end ≤ start 时稳定拒绝 |
| 撤回 | 本人待审核申请成功撤回，审计完整；非本人/非待审核被拒绝 |
| 周报 | 负责人读取指定自然周状态分布；不含私人联系方式；非负责人被拒绝 |

#### 8. 交付阶段

| 阶段 | 内容 | 承诺 |
|---|---|---|
| 核心申请域与撤回 | 区间校验（不变）+ 申请生命周期 + 撤回 + 审计 + 终端交互 | 当前目标 |
| 负责人周报 | 按自然周的状态分布统计 + 终端交互 | 当前目标（可独立交付） |

#### 9. 术语

- **预约申请：** 成员提交的预约请求，有独立身份和生命周期（待审核→已批准/已拒绝/已撤回），不等于已生效预约。
- **已生效预约：** 申请经批准后产生的记录，本轮不实现其取消。
- **周报：** 按自然周统计的申请状态分布，仅负责人可读。

---

## 九、候选包限制说明

1. **全部四类上游候选均为 `draft` 状态**，尚未请求确认。实现对齐待上游确认后形成。
2. **不含任何确认元数据** — 确认由负责人决定后通过公开程序写入。
3. **不实施业务代码，不提交 Git** — AGENTS.md 限制当前只允许起草和解释文档。
4. **DDD 方法采用为"有条件"** — 仅限申请实体及其关联规则；区间校验纯函数保持现状。具体技术标识待确认后从基础治理档案选取。
5. **`request_projection.py` 的偏离** — 前次只读澄清已确认该文件的固定 label 与业务含义存在偏离。它是预置样本，不构成领域权威，候选中不引用它作为业务来源。
6. **`allowed_programs` 中的 `python`** — 使用稳定程序身份而非绝对路径；每次工程方案仍固定真实执行路径。

---

## 十、等待你的决定

本候选包已完整展示产品定义、领域模型、目标架构和工程政策的全部修订内容、旧含义对照和下游处置。你可以：

- **逐类审阅**并指出需要修改的具体项。
- **整体接受或退回**全部四类上游候选。
- **部分接受**某些类别并退回其他。

任何接受决定将通过 `strixnova authority` 公开命令提交；当前不调用该命令。
