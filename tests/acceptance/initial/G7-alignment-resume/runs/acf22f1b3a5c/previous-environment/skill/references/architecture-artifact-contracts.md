# 目标架构从属产物第二版精确结构合同

只在起草、修订或纠正 `strixnova.project-architecture-description.v1`
（项目目标架构第二版）及其五份从属文件时读取。根文件只定位这些文件；每份从属文件
有独立且精确的 `schema_version`（结构版本），不能按自然语言文件名猜写。

## 共同身份规则

- `architecture_id`（架构标识）使用 `ARCH-`（架构标识前缀）加十六位大写十六进制字符。
- `architecture_revision_id`（架构修订标识）使用 `ARCHREV-`（架构修订标识前缀）
  加十六位大写十六进制字符，并与根文件当前修订完全一致。
- `module_id`（模块标识）、`interface_id`（接口标识）、
  `relationship_id`（关系标识）、`constraint_id`（约束标识）和
  `stage_id`（阶段标识）分别使用 `MODULE-`（模块标识前缀）、
  `INTERFACE-`（接口标识前缀）、`RELATION-`（关系标识前缀）、
  `CONSTRAINT-`（约束标识前缀）和 `ARCHSTAGE-`（架构阶段标识前缀），
  后接十六位大写十六进制字符。
- 从属文件只描述目标责任，不得出现源码路径、测试路径、当前实现证据或完成度字段。

## 一、模块目录

结构版本只能是 `strixnova.architecture-modules.v1`（目标架构模块目录第二版）。
根字段只有 `schema_version`（结构版本）、`architecture_id`（架构标识）、
`architecture_revision_id`（架构修订标识）和 `modules`（模块列表）。

每个模块只能包含 `module_id`（模块标识）、`title`（标题）、`layer`（层次）、
`responsibility`（单一责任陈述）、`not_responsible_for`（不负责事项）和
`public_interface`（公开接口）。

`layer`（层次）只能是 `adapter`（适配）、`application`（应用）、`domain`（领域）、
`authority`（权威）、`policy`（政策）、`query`（查询）或
`infrastructure`（基础设施）。`not_responsible_for`（不负责事项）至少一条。

`public_interface`（公开接口）只能包含 `interface_id`（接口标识）、`title`（标题）和
`operations`（操作列表）；每项操作只能包含 `name`（操作名称）和 `meaning`（操作含义）。
一个模块只有一个公开接口对象，但该接口可列多个操作。

```yaml
schema_version: strixnova.architecture-modules.v1
architecture_id: ARCH-3333333333333333
architecture_revision_id: ARCHREV-3333333333333333
modules:
  - module_id: MODULE-3333333333333333
    title: 库存领域
    layer: domain
    responsibility: 构造完整库存快照并产生低库存判定结果。
    not_responsible_for: [不读取文件，不打印命令行文本。]
    public_interface:
      interface_id: INTERFACE-3333333333333333
      title: 库存判定接口
      operations:
        - name: 构造完整快照
          meaning: 从已解码值形成完整领域对象或领域错误。
        - name: 识别低库存项
          meaning: 返回按输入顺序排列的完整低库存项序列。
```

不要使用 `responsibilities`（责任列表）、`stable_interfaces`（稳定接口列表）或
`domain_fact_ids`（领域事实标识列表）等自定义字段。领域事实到模块的归属只写在
领域事实处置文件中。

## 二、关系目录

真实没有模块间关系时，`relationships` 可以为空数组，包括单模块架构。仍须保留目录身份和 `default_relationship_policy=forbidden`；不得为了满足结构虚构模块或关系，已存在的真实依赖仍须声明并接受实现对齐检查。

结构版本只能是 `strixnova.architecture-relationships.v1`（目标架构关系目录第二版）。
根字段只有 `schema_version`（结构版本）、`architecture_id`（架构标识）、
`architecture_revision_id`（架构修订标识）、`default_relationship_policy`
（缺省关系政策）和 `relationships`（关系列表）。缺省关系政策必须固定为
`forbidden`（未声明即禁止）。

每条关系只能包含 `relationship_id`（关系标识）、`from_module_id`（来源模块标识）、
`to_module_id`（目标模块标识）、`mode`（关系模式）、`mediator_module_id`
（中介模块标识）、`contract`（交互合同）和 `reason`（采用理由）。

`mode`（关系模式）只能是 `direct`（直接依赖）、`through_module`（经中介模块）、
`read_only_projection`（只读投影）或 `forbidden`（明确禁止）。只有经中介模块时
`mediator_module_id`（中介模块标识）必须非空，其余模式必须为空值。

```yaml
schema_version: strixnova.architecture-relationships.v1
architecture_id: ARCH-3333333333333333
architecture_revision_id: ARCHREV-3333333333333333
default_relationship_policy: forbidden
relationships:
  - relationship_id: RELATION-3333333333333333
    from_module_id: MODULE-4444444444444444
    to_module_id: MODULE-3333333333333333
    mode: direct
    mediator_module_id: null
    contract: 命令行只通过公开领域操作取得完整判定结果。
    reason: 展示职责不得重新实现领域规则。
```

不要使用 `direction`（方向）、`kind`（关系种类）或 `rationale`（理由简写）等字段。
允许依赖边必须显式声明，直接依赖图必须无环；同一方向不能既允许又禁止。

## 三、约束目录

结构版本只能是 `strixnova.architecture-constraints.v1`（目标架构约束目录第二版）。
根字段只有 `schema_version`（结构版本）、`architecture_id`（架构标识）、
`architecture_revision_id`（架构修订标识）和 `constraints`（约束列表）。

每条约束只能包含 `constraint_id`（约束标识）、`title`（标题）、`statement`（约束陈述）、
`applies_to_module_ids`（适用模块标识）和 `verification_methods`（验证方法）。
验证方法至少一项，每项只能包含 `method_type`（方法类型）和 `description`（方法说明）。
方法类型只能是 `automatic_gate`（自动门禁）、`behavior_acceptance`（行为验收）或
`manual_review`（人工审查）。

```yaml
schema_version: strixnova.architecture-constraints.v1
architecture_id: ARCH-3333333333333333
architecture_revision_id: ARCHREV-3333333333333333
constraints:
  - constraint_id: CONSTRAINT-3333333333333333
    title: 本地只读边界
    statement: 目标模块不得写库存、保存跨运行状态或访问网络。
    applies_to_module_ids: [MODULE-3333333333333333]
    verification_methods:
      - method_type: behavior_acceptance
        description: 以真实命令行验收输入不变且没有外部活动。
```

## 四、领域事实处置目录

结构版本只能是 `strixnova.architecture-domain-fact-dispositions.v1`
（目标架构领域事实处置目录第二版）。根字段只有 `schema_version`（结构版本）、
`architecture_id`（架构标识）、`architecture_revision_id`（架构修订标识）、
`domain_model_ref`（领域模型引用）和 `dispositions`（处置列表）。

`domain_model_ref`（领域模型引用）只包含 `model_id`（领域模型标识）和
`revision_id`（领域模型修订标识），必须精确绑定根架构引用的领域修订。

每项处置只能包含 `domain_fact_id`（领域事实标识）、`disposition_type`（处置类型）、
`primary_module_id`（主要模块标识）、`collaborator_module_ids`（协作模块标识）、
`relationship_ids`（关系标识）、`constraint_ids`（约束标识）和 `rationale`（处置理由）。

处置类型只能是 `primary_module`（主要模块承载）、`module_relationship`（模块关系承载）、
`architecture_constraint`（架构约束承载）、`no_independent_implementation`
（不需独立实现）或 `unallocated`（尚未分配）。正式完整候选不得保留尚未分配：

- 主要模块承载时 `primary_module_id`（主要模块标识）必须非空；
- 模块关系承载时 `relationship_ids`（关系标识）至少一项；
- 架构约束承载时 `constraint_ids`（约束标识）至少一项；
- 其他类型的 `primary_module_id`（主要模块标识）必须为空值。

```yaml
schema_version: strixnova.architecture-domain-fact-dispositions.v1
architecture_id: ARCH-3333333333333333
architecture_revision_id: ARCHREV-3333333333333333
domain_model_ref:
  model_id: MODEL-2222222222222222
  revision_id: MODELREV-2222222222222222
dispositions:
  - domain_fact_id: FACT-2222222222222222
    disposition_type: no_independent_implementation
    primary_module_id: null
    collaborator_module_ids: []
    relationship_ids: []
    constraint_ids: []
    rationale: FACT-2222222222222222 表示仓库管理员，属于使用者角色，不需要独立实现模块。
```

每项现行领域事实必须且只能出现一次。协作模块不能重复主要模块，所有引用必须存在。
不要使用 `fact_id`（事实标识简写）、`disposition`（处置简写）或
`target_id`（目标标识简写）等字段。

## 五、实施阶段目录

结构版本只能是 `strixnova.architecture-implementation-stages.v1`
（目标架构实施阶段目录第二版）。根字段只有 `schema_version`（结构版本）、
`architecture_id`（架构标识）、`architecture_revision_id`（架构修订标识）和
`stages`（阶段列表）。

每个阶段只能包含 `stage_id`（阶段标识）、`order`（连续顺序）、`title`（标题）、
`scope`（阶段范围）、`prerequisite_stage_ids`（前置阶段标识）、`module_ids`
（覆盖模块标识）、`entry_conditions`（进入条件）和 `completion_conditions`（完成条件）。

`scope`（阶段范围）只能是 `current_product_stage`（当前产品阶段）或
`future_candidate`（未来候选）。`order`（连续顺序）必须从一开始连续递增；
每个前置阶段必须排在当前阶段之前；全部当前阶段合计必须覆盖所有目标模块。

```yaml
schema_version: strixnova.architecture-implementation-stages.v1
architecture_id: ARCH-3333333333333333
architecture_revision_id: ARCHREV-3333333333333333
stages:
  - stage_id: ARCHSTAGE-3333333333333333
    order: 1
    title: 本地低库存能力
    scope: current_product_stage
    prerequisite_stage_ids: []
    module_ids: [MODULE-3333333333333333]
    entry_conditions: [产品、领域和目标架构已经确认。]
    completion_conditions: [领域规则和公开接口通过真实验证。]
```

不要使用 `sequence`（顺序简写）或 `allowed_transition_state`（过渡状态说明）等自定义字段。

## 校验失败时怎样纠正

若 `schema_version`（结构版本）错误，公开错误会直接给出该文件要求的精确值。版本正确后，
错误会定位到具体列表序号和字段，并列出缺少字段、不允许字段、非法类型或允许集合。
只纠正结构时不得改变责任含义；若结构纠正暴露了责任混合、关系缺失、事实处置变化或阶段
范围变化，旧负责人接受立即失效，必须形成新架构修订、同步实现对齐并重新展示。
