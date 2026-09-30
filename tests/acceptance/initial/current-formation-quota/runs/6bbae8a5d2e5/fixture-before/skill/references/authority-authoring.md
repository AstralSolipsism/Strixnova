# 长期权威起草资料包

建立、修订或审查长期权威时，先判断意图，再只读当前权威与阶段对应的小节。首次完整建模
需要五类结构；局部修订不要求重读全部示例。

## 阅读索引

| 当前工作 | 阅读位置 |
|---|---|
| 判断首次建立、修订或只读审查 | 先判断本次意图、唯一顺序 |
| 起草一个权威 | 五类正式结构中对应的小节，以及该小节链接的精确合同 |
| 准备候选定位、复核与采用 | 先建立候选定位入口，再复核并采用 |
| 修改已采用的权威 | 修订现行权威时怎样写变更集 |
| 结束当前起草 | 起草完成前的覆盖检查中适用的条目 |

下文使用虚构的库存预警业务示范结构：仓库管理员根据库存快照识别低库存项。示例身份、
数值、路径与陈述均需依据受管项目填写，不是其默认产品目标；片段未展示的业务事实仍须
按实际范围建模。Agent 负责起草与提交，确认元数据由程序经公开命令写入。

## 先判断本次意图

| 意图 | 何时使用 | 必须做什么 | 不得做什么 |
|---|---|---|---|
| `create`（首次建立） | 项目尚未采用完整长期权威 | 依次形成产品、领域、目标架构、工程政策和实现对齐的完整首版候选 | 不得从现有代码反推产品目的，也不得用差异变更集绕过完整建模 |
| `update`（修订现行权威） | 已存在精确已确认修订，且本次决定会改变其中内容 | 固定当前四类核心权威基线，形成完整新修订和 `authority_change_set`（长期权威变更集），逐层说明下游处置 | 不得原地覆盖已确认修订，不得让草稿被下游采用 |
| `review`（只读审查） | 只检查内容是否完整、对齐或存在权威倒置 | 读取精确修订，形成 `semantic_review`（跨产物语义审查）和纠正建议 | 不得把审查意见写成正式事实，不得替项目负责人确认 |

若用户只说“完善领域模型”，先用项目状态区分首次建立还是修订；这属于可调查事实，
不要反问用户。只有仍会改变产品范围、领域含义或重大架构取舍的决定才询问用户。

## 唯一顺序

```text
产品定义 → 领域模型 → 目标架构 → 实现对齐 → 当前代码与证据
             ↘ 工程政策约束工程做法与证据，不定义领域含义
```

上游未确认时，下游只能保持草稿。现有代码、测试、外部模板和智能编码代理建议都只是
证据，不能反向成为产品、领域或架构权威。

## 五类正式结构

结构版本必须使用当前公开合同中的精确值。以下是起草检查表；字段名是机器合同，
字段内容必须由智能编码代理依据项目事实写成自然中文。

### 一、产品定义

- 合同：`strixnova.project-product-definition.v1`（项目产品定义第一版）。
- 根文件必须包含：产品稳定身份、修订、标题、目的、负责人、主要用户、问题、预期结果、
  产品能力、非目标、约束、成功判断、交付阶段和未决决定。
- 每项产品能力必须追溯至少一项预期结果；每项成功判断也必须追溯预期结果。
- `confirmed`（已确认）或 `ready_for_confirmation`（待确认）的修订不得保留未决决定。
- 这里只回答“为什么建设、为谁建设、承诺什么、明确不做什么”。不得写模块、接口、
  数据库、源码路径或测试命令。

最小完整根结构示例：

```yaml
schema_version: strixnova.project-product-definition.v1
product_id: PRODUCT-1111111111111111
revision:
  revision_id: REVISION-1111111111111111
  status: draft
  supersedes_revision_id: null
  confirmed_by_owner_id: null
  confirmed_on: null
title: 库存预警
purpose: 帮助仓库管理员从完整库存快照中识别低于补货阈值的物品。
product_owner:
  owner_id: OWNER-1111111111111111
  display_name: 项目负责人
primary_users:
  - user_id: USER-1111111111111111
    title: 仓库管理员
    description: 根据库存和补货阈值决定哪些物品需要补货的人。
problems:
  - problem_id: PROBLEM-1111111111111111
    user_ids: [USER-1111111111111111]
    statement: 手工逐项比较库存与补货阈值容易遗漏需要补货的物品。
desired_outcomes:
  - outcome_id: OUTCOME-1111111111111111
    statement: 仓库管理员能从一次完整库存快照中取得需要补货的物品清单。
capabilities:
  - capability_id: CAPABILITY-1111111111111111
    title: 识别低库存物品
    description: 对每项物品比较当前库存与补货阈值，并按输入顺序列出低库存项。
    outcome_ids: [OUTCOME-1111111111111111]
non_goals:
  - non_goal_id: NONGOAL-1111111111111111
    statement: 本次只提示低库存，不自动下单或修改库存。
constraints:
  - constraint_id: CONSTRAINT-1111111111111111
    statement: 输入快照无效时报告错误，不以部分读取结果生成正常清单。
success_criteria:
  - criterion_id: CRITERION-1111111111111111
    statement: 对有效快照完整列出低于阈值的物品，等于阈值的物品不进入清单。
    outcome_ids: [OUTCOME-1111111111111111]
delivery_stages:
  - stage_id: STAGE-1111111111111111
    title: 本地库存快照预警
    commitment: current_target
    description: 先支持本地快照的完整校验和低库存清单输出。
unresolved_decisions: []
```

### 二、领域模型

- 根合同：`strixnova.project-domain-model.v1`（项目领域模型第一版）。
- 分卷合同：`strixnova.project-domain-collection.v1`（领域集合第一版）和
  `strixnova.project-domain-source.v1`（领域来源第一版）。
- 根文件固定模型身份、修订、精确产品修订、用途、根集合路径和未决决定。
- 集合只负责阅读路由；来源保存规范事实正文。集合标题或目录名不能自动成为领域边界。
- 每项现行事实必须有稳定身份、状态、类型、产品能力归属、作用域、显式依赖和类型化内容。
- 完整领域内容至少覆盖参与者与决定权、术语、值对象、有身份对象、生命周期、事件、
  规则、不变量、正常／阻断／纠正／取消／恢复／失败场景、领域边界与外部系统。
- 这里只回答“产品范围内哪些业务含义必须成立”。不得写源码路径、当前完成度或验证回执。
- 每个 `kind`（事实类型）的允许值、`content`（类型化内容）必填字段、嵌套结构和
  类型引用见 [domain-fact-contracts.md](domain-fact-contracts.md)
  （领域事实精确结构合同）。首次完整建模必须在写来源文件前读取；不得根据自然语言
  类型名称猜字段。

最小根文件与路由示例：

```yaml
# docs/domain/model.yaml
schema_version: strixnova.project-domain-model.v1
model_id: MODEL-2222222222222222
revision:
  revision_id: MODELREV-2222222222222222
  status: draft
  supersedes_revision_id: null
  confirmed_by_owner_id: null
  confirmed_on: null
product_definition_ref:
  product_id: PRODUCT-1111111111111111
  revision_id: REVISION-1111111111111111
title: 库存预警领域模型
purpose: 解释库存快照、补货阈值、低库存判断和无效输入的业务含义。
root_collection_paths: [docs/domain/collections/core.yaml]
unresolved_decisions: []
---
# docs/domain/collections/core.yaml
schema_version: strixnova.project-domain-collection.v1
model_id: MODEL-2222222222222222
model_revision_id: MODELREV-2222222222222222
collection_id: COLL-2222222222222222
title: 核心业务事实
routing_summary: 需要理解参与者、对象、规则和场景时读取。
child_collection_paths: []
sources:
  - source_id: SRC-2222222222222222
    title: 核心事实
    routing_summary: 产品能力涉及的规范业务事实。
    path: docs/domain/sources/core.yaml
```

来源文件不能只放一条“系统应当工作”的概括句。最小样例只展示一个事实的结构；正式模型
必须按领域事实精确结构合同继续补齐上述类型和场景闭包：

```yaml
schema_version: strixnova.project-domain-source.v1
model_id: MODEL-2222222222222222
model_revision_id: MODELREV-2222222222222222
source_id: SRC-2222222222222222
scope_fact_ids: []
facts:
  - fact_id: FACT-2222222222222222
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

### 三、目标架构

- 合同：`strixnova.project-architecture-description.v1`（项目目标架构第一版）。
- 根文件固定架构身份、修订、精确领域修订和五个从属目录路径。
- 从属目录必须完整提供模块、关系、全局约束、每项现行领域事实处置和实施阶段。
- 每个模块必须说明责任、不负责事项和稳定接口；每条依赖必须有方向且不得成环。
- 每项现行领域事实必须且只能有一个有效处置，不能用“共同负责”隐藏归属不清。
- 这里只回答“未来应由谁、以什么边界承载领域事实”。不得记录当前源码布局或完成度。
- 五份从属文件的精确结构版本、字段、枚举和嵌套形状见
  [architecture-artifact-contracts.md](architecture-artifact-contracts.md)
  （目标架构从属产物精确结构合同）。首次建立目标架构时必须在写这些文件前读取，
  不得把自然语言中的“责任”“接口”或“关系”自行翻译成未公开字段。

最小根结构示例：

```yaml
schema_version: strixnova.project-architecture-description.v1
architecture_id: ARCH-3333333333333333
revision:
  revision_id: ARCHREV-3333333333333333
  status: draft
  supersedes_revision_id: null
  confirmed_by_owner_id: null
  confirmed_on: null
domain_model_ref:
  model_id: MODEL-2222222222222222
  revision_id: MODELREV-2222222222222222
title: 库存预警目标架构
purpose: 定义承载已确认领域事实的稳定责任与依赖方向。
artifact_paths:
  modules: docs/architecture/modules.yaml
  relationships: docs/architecture/relationships.yaml
  constraints: docs/architecture/constraints.yaml
  domain_fact_dispositions: docs/architecture/domain-fact-dispositions.yaml
  implementation_stages: docs/architecture/implementation-stages.yaml
unresolved_decisions: []
```

### 四、项目工程政策

- 合同：`strixnova.project-engineering-policy.v1`（项目工程政策第一版）。
- 必须绑定精确产品修订和 Strixnova基础治理配置。
- 必须明确方法采用状态、质量／测试／安全／发布／运行／维护／兼容政策、项目来源、规则扩展、
  规则裁剪、允许的验证程序、交付关口、证据边界和未决决定。
- 工程方法只有项目明确采用后才生效；外部库只是来源，不会自动成为项目权威。
- 工程政策规定“怎样建设和证明”，不得重新定义产品能力、领域含义或架构责任。
- 长期 `allowed_programs`（允许程序）应声明稳定程序身份或仓库内稳定相对路径，
  不得写入一次性虚拟环境、临时验收目录、某个智能编码代理安装目录或其他预期会消失的
  主机绝对路径。每次执行的精确路径、参数和工作目录仍由已确认工程方案固定，不由长期政策猜写。
- 嵌套的工程方法采用、项目来源、规则扩展、规则裁剪、验证程序、交付关口和证据字段见
  [engineering-policy-contracts.md](engineering-policy-contracts.md)
  （工程政策精确结构合同）。`project_sources`（项目工程方法来源）不是代码观察底账；
  当前源码、测试和提交证据应进入实现对齐或建设事项证据，没有项目方法资料时使用空列表。

最小根结构示例：

```yaml
schema_version: strixnova.project-engineering-policy.v1
policy_id: POLICY-4444444444444444
revision:
  revision_id: POLICYREV-4444444444444444
  status: draft
  supersedes_revision_id: null
  confirmed_by_owner_id: null
  confirmed_on: null
product_definition_ref:
  product_id: PRODUCT-1111111111111111
  revision_id: REVISION-1111111111111111
base_profile_ref:
  profile_id: strixnova-general-software-engineering
  profile_version: "2026-08-23"
method_adoptions:
  - method_id: ddd
    status: not_assessed
    reason: 尚未形成采用判断，不伪造结论。
    conditions: []
    adopted_technique_ids: []
policy_statements:
  quality: [真实效果与未运行项必须分开报告]
  testing: [按真实影响选择最低有效验证]
  security: [安全影响不能由普通功能测试替代]
  release: [远程发布由外部工具执行]
  operations: [运行事实必须来自真实外部回执]
  maintenance: [输入格式或阈值规则变化时说明受影响行为与恢复方式。]
  compatibility: [兼容要求必须来自真实项目约束]
project_sources: []
rule_extensions: []
rule_tailoring: []
verification_command_policy:
  allowed_programs:
    - program: git
      purpose: 执行明确批准的本地版本管理操作。
      argument_policy: exact_plan_only
  forbidden_agent_program_names: [agy, codex, claude, gemini, aider, opencode, cursor, windsurf]
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

### 五、实现对齐

- 合同：`strixnova.project-implementation-alignment.v1`（项目实现对齐第一版）。
- 根文件绑定精确领域修订、架构修订和不可变代码观察版本，并定位四份完整底账。
- 根文件显式记录语言无关观察范围、能力、覆盖与提供者回执；四份底账分别记录受管源码唯一归属、实际实现关系、目标责任实现程度和偏差。
- 这里可以记录当前文件、散列、证据、完成度和限制，但不能反向改写产品、领域或目标架构。
- 上游修订变化后，旧实现对齐立即待复核；必须完整重做受影响底账，不能只改一条结论。
- 四份底账的精确结构版本、字段、枚举、覆盖要求和示例见
  [implementation-alignment-artifact-contracts.md](implementation-alignment-artifact-contracts.md)
  （实现对齐从属产物精确结构合同）。首次建立或重做实现对齐时必须先读取，
  不得根据“源码归属”“完成情况”等自然语言自行猜写字段。

最小根结构示例：

```yaml
schema_version: strixnova.project-implementation-alignment.v1
alignment_model_id: ALIGNMODEL-5555555555555555
revision:
  revision_id: ALIGNREV-5555555555555555
  status: draft
  supersedes_revision_id: null
  confirmed_by_owner_id: null
  confirmed_on: null
domain_model_ref:
  model_id: MODEL-2222222222222222
  revision_id: MODELREV-2222222222222222
architecture_ref:
  architecture_id: ARCH-3333333333333333
  revision_id: ARCHREV-3333333333333333
code_snapshot:
  repositories:
  - repository_id: REPO-7777777777777777
    base_commit: 0123456789abcdef0123456789abcdef01234567
    worktree_state: clean
  governed_source_manifest_sha256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
  observed_on: "2026-08-27"
observation_scopes:
- scope_id: OBSCOPE-5555555555555555
  repository_id: REPO-7777777777777777
  root: src/inventory_alert
  languages: [python]
  required_relation_kinds: [source_import]
  configurations: [default]
  exclusions: ['**/__pycache__/**']
  provider_options:
    python_package_name: inventory_alert
observation_coverage:
  contract_version: strixnova.project-implementation-observation.v1
  overall_status: complete
  source_manifest_sha256: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
  observation_snapshot_sha256: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  observed_paths:
    REPO-7777777777777777:src/inventory_alert/__init__.py: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    REPO-7777777777777777:src/inventory_alert/domain.py: bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    REPO-7777777777777777:src/inventory_alert/service.py: cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc
  records:
  - scope_id: OBSCOPE-5555555555555555
    repository_id: REPO-7777777777777777
    language_id: python
    provider_id: strixnova.python-static.v1
    provider_version: '1'
    status: complete
    execution_mode: builtin_static
    configurations: [default]
    required_relation_kinds: [source_import]
    supported_relation_kinds: [source_import]
    observed_relation_kinds: [source_import]
    source_file_count: 3
    relation_count: 2
    limitations: []
    gaps: []
  provider_receipts:
  - scope_id: OBSCOPE-5555555555555555
    repository_id: REPO-7777777777777777
    language_id: python
    provider_id: strixnova.python-static.v1
    provider_version: '1'
    execution_mode: builtin_static
    status: complete
    result_sha256: dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd
artifact_paths:
  source_ownership: docs/implementation-alignment/source-ownership.yaml
  actual_dependencies: docs/implementation-alignment/actual-dependencies.yaml
  target_responsibilities: docs/implementation-alignment/target-responsibilities.yaml
  deviations: docs/implementation-alignment/deviations.yaml
unresolved_items: []
```

每个观察范围必须对应真实项目边界。Python 可使用仓库根 `.` 观察同层脚本和子包，也可选择
实际软件包根并配置 `python_package_name`。普通 `src` 容器不能被误当成同名包；按真实包与
语言边界选择范围，具体规则见实现对齐精确合同，不为满足观察器而搬动源码。
Rust、Go、TypeScript、C#、C++ 及其他语言同样要声明必需关系和配置。若内置适配器报告
部分覆盖，必须保留限制，或按工程政策授权语言/构建工具提供者补足；不得把部分结果改写为
完整，也不得为了得到空底账缩小范围。

## 先建立候选定位入口，再复核并采用

五类内容完整以前，产品、领域、目标架构和工程政策先保持 `draft`（草稿）；准备交给
负责人决定时改为 `ready_for_confirmation`（待确认）。实现对齐始终保持 `draft`（草稿），
不得混入上游语义确认。项目采用入口只能按已确认工程方案中的精确路径创建，不能猜写。

首次建立项目时，四类上游候选起草完成后、运行 `alignment prepare`（对齐准备）或读取完整
`authority`（权威）复核包以前，就必须在实施工作树中创建已列入方案的 `strixnova-project.yaml`
和项目工程基线。此时它们只是候选定位入口，不表示任何权威已经采用。基线对四类上游的
`revision_status` 如实填写候选的 `draft` 或 `ready_for_confirmation`，`adoption_status`
均为 `under_review`；实现对齐引用使用方案的身份和首次准备请求的修订，状态保持
`draft/under_review`，即使其正文还需由对齐准备及候选写入形成。`review_state.required`
为 `true`，列明仍待接受或完成的种类；不能预填 `confirmed/current` 以满足读取条件。
下面的完整基线示例展示这一确认前状态。路径或身份尚未由方案确定时先纠正方案，不猜写。

候选定位入口齐备后，按[实现对齐规程](implementation-alignment-workflow.md)准备、检查并
写出真实对齐草稿，再读取完整权威复核包。上游确认由程序机械更新对应状态；不要等到确认
以后才首次创建基线，也不要把未确认候选拿去当普通已采用基线使用。

独立决定不等于强制拆成五轮对话。新项目的五类候选若已经同时完整、引用闭合且没有需要
先决定上游才能起草下游的未知，应在一条回复中展示一份完整候选包，逐类列明修订标识、
内容摘要、影响、限制和独立接受范围，并在回复后等待一次负责人决定。负责人可以在同一条
后续消息中逐类明确接受；智能编码代理仍须把四项上游决定分别归属到各自精确修订，不能把
整包接受解释为合并成一份权威。只有某一类尚不完整、被退回或会改变其他候选时，才单独展开
该类。实现对齐不在这个候选包中取得确认，只在实际结果接受后由程序机械定档。

已有项目只为本轮内容实际变化的权威形成新修订和接受范围。明确保持不变的产品、领域、架构、
工程政策或实现对齐继续引用当前已确认修订，只在权威变更集的下游处置中说明为什么无需修订；
不得为了凑齐五类而复制无变化正文、制造候选卡或增加负责人确认。若已确认工程方案把“不变”
权威错误列为候选，必须在实施前重规划，不能静默省略，也不能按错误方案制造空修订。

判断“是否变化”必须包含正式引用，而不只比较正文语句：精确上游绑定发生变化也属于实际变化。
产品修订会使绑定它的领域修订需要更新，领域修订会使目标架构和实现对齐需要更新，架构修订
也会使实现对齐需要更新。此类候选的正文责任可以保持不变，但必须明确说明只是更新精确绑定，
不能把它叫作空修订，也不能继续沿用已经绑定旧上游的修订。

上游产品、领域或目标架构一旦实质变化，旧实现对齐就不再属于“保持不变”。编码前先形成绑定新上游修订的实现对齐草稿，用当前代码快照如实记录目标尚未实现、部分实现或偏离，并让工作树候选基线绑定这份草稿。它保持未确认，实施后使用真实文件散列、依赖和责任结果刷新同一候选；只有实际结果被接受后，应用协调器才机械定档。不得为了暂时通过结构检查继续绑定旧实现对齐，也不得在编码前伪造未来已实现状态。

1. 按 CurrentAction（当前动作）给出的依赖顺序，对本轮实际变化的每类上游权威运行
   `strixnova authority --work-item-id <事项> --authority-kind <种类> --version <版本>`
   （Strixnova长期权威候选读取命令），逐类记录独立展示。每次展示会前进事项版本，所以每次
   使用命令返回的下一动作和新版本；不要提前向负责人请求确认。
   起草动作已有唯一 `authority_kind` 时可以省略 `--authority-kind`，程序沿用当前种类；
   此时仍不传 `--input`，也不创建空 JSON 来试探命令。候选正文须先达到
   `ready_for_confirmation`；没有种类参数不再意味着跳过登记直接读取复核包。
2. 全部展示完成、CurrentAction 进入 `review_project_authority_candidates`（复核长期权威
   候选）后，运行一次不带 `--authority-kind` 和 `--input` 的同一命令，读取完整候选复核包。
   按 [cross-artifact-review.md](cross-artifact-review.md)（跨产物审查规程）逐项读取真实治理
   文件，形成绑定包内精确 `reviewed_refs`（已审查引用）的八视角复核，再用一次
   `strixnova.project-authority-review-submission.v1` 输入提交。这个动作只记录 Agent（智能编码
   代理）复核，不是负责人确认；候选正文变化后必须重做。
3. CurrentAction 进入 `confirm_project_authority_candidates` 后，按
   [长期权威确认规程](confirmation-and-cancel.md#long-term-authority-candidates)展示完整候选包、
   复核结论和逐类接受范围，结束回复并等待新消息。允许自然语言逐类决定或明确接受整包，
   不要求固定接受句、退回前缀或内部字段。
4. 收到负责人原文后，只运行一次同一 `authority`（长期权威决定）命令，并通过
   `--input`（输入）提交按 CurrentAction（当前动作）顺序排列的完整 `decisions`（决定）数组。
   数组中的每一项分别包含权威种类、由 Agent 从当前挑战机械复制的对应指纹、完整负责人原文，
   以及解释该候选决定的 `agent_decision`；
   指纹不是负责人需要理解的决定内容。不得逐类多次提交，也不得漏项、
   调换顺序或把一类接受扩大到另一类。程序先原子复核整包，再按依赖顺序写入
   `confirmed`（已确认）、负责人身份和决定日期，并把各项决定与确认后的正文散列写入
   WorkItem（建设事项）。任一项失效时整包不落账并恢复文件。
5. 核对先前创建的唯一项目配置和 `strixnova.project-engineering-baseline.v1`（项目工程基线
   第一版）：四类已接受上游应已由程序机械更新为已确认、当前采用，实现对齐仍绑定草稿，
   保留当前授权架构阶段、代码观察版本和真实待复核状态。不要重建基线或手工补签确认。
6. 在写业务代码前运行 `strixnova status --working-tree`（Strixnova工作树候选检查命令）。
   后续实际结果提交时，程序会反查每类变化的上游权威是否存在同一精确正文的独立负责人决定；
   只手工写成 `confirmed`（已确认）或事后改正文都会被拒绝。

候选起草、最终复核和确认是切片实施前的治理阶段。Agent 可以按方案把这些权威操作拆入多个
有依赖的治理切片；程序会在任何切片产生实施证据前，只允许完整候选包实际声明的治理路径先
形成。该许可不完成任何切片，不允许普通业务路径提前出现，也不改变操作的唯一切片归属。
确认完成后仍按原切片依赖顺序实施、验证和记录文件快照。

先用 `strixnova context contract configuration` 读取当前配置合同，明确项目身份、配置所属仓库、
成员及基线位置。已有仓库沿用原身份；新仓库按已确认范围一次分配稳定身份，不从目录名推导。
`default_integration_ref` 只选择配置仓库的本地集成版本。单成员示例如下：

```yaml
# strixnova-project.yaml
schema_version: strixnova.project-config.v1
project_id: PROJECT-6666666666666666
repository_id: REPO-7777777777777777
repositories:
  - repository_id: REPO-7777777777777777
    owner_project_id: PROJECT-6666666666666666
    purpose: 当前项目源码与工程材料
engineering_baseline:
  repository_id: REPO-7777777777777777
  path: docs/engineering/baseline.yaml
  ref: null
default_integration_ref: main
```

配置与长期权威可以跨成员仓库读取。本机分离位置用 `strixnova context contract bindings` 的
合同显式提供，并通过 `--project-bindings` 传入 JSON 文件；绑定只定位已声明身份。
基线引用中的同仓库 null 版本继承包含它的读取版本，跨仓库采用引用必须给出精确提交，
不能把各仓库最新分支拼成已采用组合。

旧工作树配置不会自动转换，原不可变历史按原合同解释。多仓库方案的范围、验证输入和交付
顺序见工程评估规程，当前文件只说明配置与权威的定位关系。

旧配置 v2 与基线 v3 的离线定位转换由既有 `upgrade check/apply/recover` 承接：预检固定
原项目、仓库身份及精确目标，应用复用维护、备份与恢复；没有事项库时不会初始化事项。
转换保持原管理位置和业务历史，受影响依据继续需要复核，不自动采用权威或恢复旧确认。
既有运行升级的授权与停止证据规则保持，见[历史与运行升级](history-and-upgrade.md)。

首次确认前的项目工程基线最小完整结构如下。身份、路径、阶段、提交和复核原因必须替换为
当前候选及已确认方案的真实值，不得照抄示例；确认后由程序更新相应上游状态：

`current_architecture_stage_id`（当前架构阶段标识）表示已确认工程方案本次授权实施的最高阶段，
不是“已经完成到哪里”的事后统计。不能机械选择第一阶段：若同一已确认方案按顺序实施阶段一
和阶段二，写业务代码前的基线就应指向阶段二；若方案只授权阶段一，则不得提前指向阶段二。
已有项目推进阶段时，工程评估必须把项目工程基线修改列入正式操作，并以目标架构中的前置关系
证明阶段连续，不能靠重标源码所属阶段消除未来阶段报告。

```yaml
# docs/engineering/baseline.yaml
schema_version: strixnova.project-engineering-baseline.v1
baseline_id: BASELINE-6666666666666666
project:
  project_id: PROJECT-6666666666666666
    title: 库存预警
  owner_id: OWNER-1111111111111111
authority_refs:
  product_definition:
    repository_id: REPO-7777777777777777
    ref: null
    path: docs/product/product-definition.yaml
    product_id: PRODUCT-1111111111111111
    revision_id: REVISION-1111111111111111
    status: {revision_status: ready_for_confirmation, adoption_status: under_review}
  domain_model:
    repository_id: REPO-7777777777777777
    ref: null
    path: docs/domain/model.yaml
    model_id: MODEL-2222222222222222
    revision_id: MODELREV-2222222222222222
    status: {revision_status: ready_for_confirmation, adoption_status: under_review}
  target_architecture:
    repository_id: REPO-7777777777777777
    ref: null
    path: docs/architecture/architecture.yaml
    architecture_id: ARCH-3333333333333333
    revision_id: ARCHREV-3333333333333333
    status: {revision_status: ready_for_confirmation, adoption_status: under_review}
  engineering_policy:
    repository_id: REPO-7777777777777777
    ref: null
    path: docs/engineering/policy.yaml
    policy_id: POLICY-4444444444444444
    revision_id: POLICYREV-4444444444444444
    status: {revision_status: ready_for_confirmation, adoption_status: under_review}
  implementation_alignment:
    repository_id: REPO-7777777777777777
    ref: null
    path: docs/implementation-alignment/alignment.yaml
    alignment_model_id: ALIGNMODEL-5555555555555555
    revision_id: ALIGNREV-5555555555555555
    status: {revision_status: draft, adoption_status: under_review}
current_architecture_stage_id: ARCHSTAGE-3333333333333333
code_version:
  repositories:
  - repository_id: REPO-7777777777777777
    base_commit: 0123456789abcdef0123456789abcdef01234567
    worktree_state: dirty
review_state:
  required: true
  reasons: [首次上游候选尚未接受，当前实现仍有已公开偏差，完成实施后必须刷新实现对齐。]
  affected_authority_kinds: [product_definition, domain_model, target_architecture, engineering_policy, implementation_alignment, code_version]
```

候选检查通过至少应同时看到：`authority_scope`（权威读取范围）为
`working_tree_candidate`（工作树候选）、`candidate_only`（仅为候选）为 `true`（是）、
`baseline_id`（基线标识）非空、五类权威均非空且
`structurally_consistent`（结构一致）为 `true`（是）。

该命令只读取当前工作树并执行结构、身份、版本、引用、状态和覆盖检查。它不写入采用状态，
不证明内容语义正确，也不改变默认 `strixnova status`（Strixnova项目状态命令）仍只读取不可变
本地集成版本的规则。在实际结果确认、提交和本地合入前，默认项目状态仍可能诚实显示旧版本
或“尚未采用”；不得把工作树候选检查结果冒充正式已集成状态。

## 修订现行权威时怎样写变更集

`authority_change_set`（长期权威变更集）属于当前 WorkItem（建设事项）的工程评估，
不是第六份长期权威。它只适用于已经存在完整正式权威后的修订。

必须做到：

1. `base_authorities`（基线权威）精确列出当前采用的产品、领域、目标架构和实现对齐
   四个身份、修订、路径、状态及不可变调查提交；
2. `candidate_authorities`（候选权威）只列本轮实际修订者，使用新修订身份，精确承接旧修订，
   且明确尚未采用；
3. `changes`（具体变化）用新增、修改、退役或重命名说明变化，不让负责人从全文差异猜；
4. 任何上游变化都必须对每一层下游声明修订、保持不变或阻断，并说明理由；
5. 存在阻断处置时不能把正式实施方案提交确认；
6. `semantic_content_machine_proven`（语义内容由机器证明）必须明确为 `false`（否）。

这里的“旧修订”是当前已确认或已采用的正式修订，不是讨论中被退回、取消或从未接受的
中间草稿。纠正未接受草稿后形成的新候选，`supersedes_revision_id`（被取代修订标识）
必须仍直接指向最后一个正式修订；不得把失败草稿串进正式继承链。

程序能拒绝过期基线、重复身份、悬空引用、漏掉的下游处置和草稿冒充已采用；程序不能
判断变化含义是否正确，也不会按标题自动把差异合入正式权威。

## 起草完成前的覆盖检查

- 产品定义：用户、问题、结果、能力、非目标、约束、成功判断和当前交付阶段是否闭合？
- 领域模型：每项产品能力是否都有参与者、决定权、对象、规则、不变量和完整场景解释？
- 目标架构：每项现行领域事实是否有唯一处置，模块责任和依赖是否闭合？
- 工程政策：项目采用的方法、规则裁剪、验证和证据边界是否明确？
- 实现对齐：当前行为归属、实际依赖、目标责任、偏差和证据是否完整？
- 权威顺序：有没有把代码、测试、模板、历史事项或审查建议反向写成上游事实？

结构校验失败时，直接按公开错误指出的精确字段纠正。语义未知时不要试错填值；按
[cross-artifact-review.md](cross-artifact-review.md)（跨产物审查规程）集中整理，最多询问
少量真正会改变方向的决定。


实现对齐的仓库限定观察字段与路径索引见
[实现对齐精确合同](implementation-alignment-artifact-contracts.md#根文件与观察合同)。
