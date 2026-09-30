# 实现对齐第四版精确结构合同

只在建立、审查或刷新 `strixnova.project-implementation-alignment.v1` 时读取。
实现对齐记录“精确实现快照相对目标架构的现状”，不是产品、领域或目标架构权威。
观察工具只提供证据；智能编码代理负责结合代码、文档和用户判断形成归属、分类、责任状态与偏离。

## 根文件与观察合同

观察范围与受管范围的 `root` 可以为 `.`，表示仓库根目录；文件路径仍须是普通仓库相对路径。用真实的 `included_path_patterns` 和观察 `exclusions` 限定源码，不把缓存或无关文件纳入。Python 的根目录范围默认按仓库根作为导入搜索根，识别同层脚本及子包；真实包范围仍按其 `python_package_name` 配置。无需搬动源码来满足观察合同。

根文件必须包含 `schema_version`、`alignment_model_id`、`revision`、
`domain_model_ref`、`architecture_ref`、`code_snapshot`、`observation_scopes`、
`observation_coverage`、`artifact_paths` 和 `unresolved_items`。

- `code_snapshot.repositories[]` 每项记录 `repository_id`、`base_commit` 与 `worktree_state`；根级另有 `governed_source_manifest_sha256` 和 `observed_on`。受管清单按仓库限定索引排序，逐行拼接“仓库身份、冒号、内部路径、冒号、Git 规范字节的 SHA-256、LF”后计算摘要。
- 每个 `observation_scopes` 项必须声明 `scope_id`、`root`、`languages`、
  `required_relation_kinds`、`configurations`、`exclusions` 和 `provider_options`。
  范围是项目事实，不是“整仓默认扫描”的暗示。
- `observation_coverage` 必须包含 `contract_version`、`overall_status`、
  `source_manifest_sha256`、`observation_snapshot_sha256`、`observed_paths`、
  `records` 和 `provider_receipts`。每个范围和语言恰好有一条覆盖记录与一条提供者回执；
  `observed_paths` 将每个精确仓库路径绑定到提供者实际读取的规范字节 SHA-256。
- 覆盖记录公开语言、提供者、执行模式、配置、必需/支持/已观察关系种类、源码与关系数量、
  限制和缺口。`complete` 必须实际覆盖源码、支持所有必需关系，并且没有限制或缺口。
- 观察范围、受管范围、源码与依赖记录、覆盖记录和提供者回执均带 `repository_id`。项目级组合使用 `strixnova.project-implementation-observation.v1`，原生提供者保留自己的合同版本。`observed_paths` 和源码清单中的 `REPO-7777777777777777:src/a.py` 是仓库限定索引，不是文件系统路径。历史观察按原合同读取，版本或指纹变化本身不构成新观察。
- 内置静态适配器使用 `builtin_static`；经过调用方精确 `ProcessPolicy` 和本次明确授权的
  外部提供者使用 `authorized_tool`；未运行使用 `not_run`。外部回执还可以记录
  `policy_id`、`command_sha256` 和 `request_sha256`，但不持久化绝对命令为新权威。
- 未支持、未授权、失败、超时、部分覆盖、未解析或歧义必须原样保留并阻断受影响范围完整对齐。
  没有关系只有在完整覆盖已被证明时才可以是真实空结果。
- 已授权外部提供者形成正式记录后，日常门可以在没有可执行提供者配置时核对并回放精确未变的
  `observed_paths`；任一路径、源码集合或散列变化都必须重新授权观察，不能沿用旧回执。

Python、Rust、Go、TypeScript、C# 和 C++ 的内置能力只是基础观察。C#、C++ 以及涉及条件编译、
生成代码、宏、构建图或运行时装配的项目通常需要授权语言/构建工具补足。其他语言通过同一外部
提供者输出合同接入，不修改实现对齐接口，也不建立平行代码图权威。

## 一、受管源码归属底账

结构版本只能是 `strixnova.implementation-source-ownership.v1`。目录根字段为
`schema_version`、`alignment_model_id`、`alignment_revision_id`、
`governed_source_scopes` 和 `records`。

每个受管范围声明 `scope_id`、`root`、`included_path_patterns`、
`included_node_kinds` 和 `exclusion_policy`。每条源码记录必须包含：

- `scope_id`、`path`、真实 `sha256`、`language_id` 和 `node_kind`；
- `disposition`、`target_module_id`、`implementation_stage_id`、`current_status`；
- `deviation_ids` 和 `rationale`。

`owned` 记录必须有唯一模块和阶段；`excluded` 记录的模块与阶段为空且状态为
`not_applicable`。`unknown` 必须引用具体偏离。受管集合中的每个文件恰好出现一次，新增或删除
文件必须先由智能编码代理审查语义归属，刷新器不会自行创造或删除记录。

```yaml
schema_version: strixnova.implementation-source-ownership.v1
alignment_model_id: ALIGNMODEL-5555555555555555
alignment_revision_id: ALIGNREV-5555555555555555
governed_source_scopes:
- scope_id: OBSCOPE-5555555555555555
  repository_id: REPO-7777777777777777
  root: src/inventory
  included_path_patterns: ['*.rs', '**/*.rs', Cargo.toml]
  included_node_kinds: [Rust 源码, Cargo 清单]
  exclusion_policy: 只排除生成目录和第三方内容。
records:
- scope_id: OBSCOPE-5555555555555555
  repository_id: REPO-7777777777777777
  path: src/inventory/lib.rs
  sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  language_id: rust
  node_kind: source_file
  disposition: owned
  target_module_id: MODULE-3333333333333333
  implementation_stage_id: ARCHSTAGE-3333333333333333
  current_status: aligned
  deviation_ids: []
  rationale: 该文件承载库存领域判断。
```

## 二、实际实现关系底账

结构版本只能是 `strixnova.implementation-actual-dependencies.v1`。目录根字段为
`schema_version`、`alignment_model_id`、`alignment_revision_id`、
`observation_contract_version` 和 `records`。

每条关系记录必须包含：

- `scope_id`、`provider_id`、`source_node_id`、`source_node_kind`、
  `source_path`、`source_external_name`、`target_node_id`、`target_node_kind`、
  `target_path`、`target_external_name` 和 `observed_names`；
- `relation_kind`、`resolution_status` 和 `conditions`；
- `source_module_id`、`target_module_id`、`classification` 和
  `target_relationship_id`；
- `deviation_ids` 和 `rationale`。

每一条观察关系都必须入账。稳定节点身份用于区分同路径上的包、项目和构建目标；内部关系使用
`target_path`，外部关系使用 `target_external_name`，二者不能同时伪填。
`resolution_status` 区分 `resolved_internal`、`external`、`unresolved` 和 `ambiguous`。
当前正式架构分类包括 `internal_same_module`、`allowed_direct`、`allowed_read_only`、
`requires_mediator_but_direct`、`forbidden`、`undeclared`、`unowned_endpoint`、
`external_observed`、`unresolved_observation` 和 `ambiguous_observation`；前三类和
`external_observed` 可以不挂偏离。观察结果决定“实际看见什么关系”，智能编码代理根据归属和目标关系决定分类及理由。

```yaml
schema_version: strixnova.implementation-actual-dependencies.v1
alignment_model_id: ALIGNMODEL-5555555555555555
alignment_revision_id: ALIGNREV-5555555555555555
observation_contract_version: strixnova.implementation-observation.v1
records:
- scope_id: OBSCOPE-5555555555555555
  repository_id: REPO-7777777777777777
  provider_id: strixnova.rust-static.v1
  source_node_id: IMPLNODE-1111111111111111
  source_node_kind: source_file
  source_path: src/inventory/lib.rs
  source_external_name: null
  target_node_id: IMPLNODE-2222222222222222
  target_node_kind: source_file
  target_path: src/inventory/domain.rs
  target_external_name: null
  observed_names: [crate::domain]
  relation_kind: module_reference
  resolution_status: resolved_internal
  conditions: []
  source_module_id: MODULE-3333333333333333
  target_module_id: MODULE-3333333333333333
  classification: internal_same_module
  target_relationship_id: null
  deviation_ids: []
  rationale: 两个文件属于同一目标模块。
```

## 三、目标责任实现底账

结构版本只能是 `strixnova.implementation-target-responsibilities.v1`。目录根字段为
`schema_version`、`alignment_model_id`、`alignment_revision_id` 和 `records`。
每个目标模块、关系和约束必须恰好出现一次。每条记录包含：

- `target_kind`、`target_id` 和 `status`；
- `satisfied`、`missing`、`evidence`、`deviation_ids` 和 `resolution_plan`。

每项证据只包含 `kind`、`ref` 和 `claim`。`implemented` 的 `missing` 与
`resolution_plan` 必须为空；其他状态必须明确缺什么、怎样补和用什么证据闭环。

```yaml
schema_version: strixnova.implementation-target-responsibilities.v1
alignment_model_id: ALIGNMODEL-5555555555555555
alignment_revision_id: ALIGNREV-5555555555555555
records:
- target_kind: module
  target_id: MODULE-3333333333333333
  status: partially_implemented
  satisfied: [已形成库存读取。]
  missing: [尚未实现低库存判断。]
  evidence:
  - kind: source
    ref: src/inventory/lib.rs
    claim: 当前源码读取库存记录。
  deviation_ids: [DEVIATION-5555555555555555]
  resolution_plan: [实现独立领域判断并增加边界测试。]
```

## 四、偏离底账

结构版本只能是 `strixnova.implementation-deviations.v1`。目录根字段为
`schema_version`、`alignment_model_id`、`alignment_revision_id` 和 `deviations`。
每项偏离包含 `deviation_id`、`priority`、`kind`、`title`、`statement`、
`affected_paths`、`affected_target_ids`、`required_action` 和 `closure_evidence`。
每项偏离至少被一条源码、关系或责任记录引用，每个引用也必须有定义。

## 完整性检查

1. 根文件与四份底账是否绑定同一稳定身份和修订？
2. 受管文件是否逐个归属并使用 Git 规范字节散列？
3. 每个观察范围是否声明语言、配置、必需关系、提供者能力、覆盖和回执？
4. 部分、失败、未运行、未解析和歧义是否仍然可见，而非空成功？
5. 实际关系是否来自观察，架构分类是否来自人工/智能体语义判断？
6. 目标责任是否恰好覆盖全部模块、关系和约束？
7. 所有偏离是否双向闭合？当前代码是否被错误地用来反向降低上游目标？

结构修正保持原含义。代码证据、归属、分类、责任或偏离发生变化时，按当前修订状态处理：已有 `draft` 继续同一草稿，重新准备观察并刷新候选；已确认或其他非草稿修订使用新的修订身份，承接当前修订，不能沿用旧接受。精确输入见[准备观察](implementation-alignment-workflow.zh-CN.md#1-准备内容寻址观察包)。若变化超出已确认方向、方案或写入范围，先走相应修订流程。
