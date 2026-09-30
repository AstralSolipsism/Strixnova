# Strixnova 正式 Skill 中文审阅映射

> 本文件只供审阅，不作为可安装 Skill，也不进入 Agent 上下文。正式运行说明来自随包 Strixnova Skill。

Strixnova 记录工程决定并核对绑定、状态、Git 事实和执行证据。Agent 调查、形成项目含义、
实施已授权工作并解释结果；负责人作出产品和接受决定。Skill 提供指引，不授予权限，
也不管理 Agent 的宿主、身份或会话。

## 工作原则

- 生成、审阅或修正阅读文档前，读取对应的[PRD 方法](references/prd-authoring.zh-CN.md)、
  [SPEC 方法](references/spec-authoring.zh-CN.md)或[领域文档](references/domain-documentation.zh-CN.md)，
  并同时读取[共同文档规则](references/artifact-documentation.zh-CN.md)。已有文档同样适用，
  标题和来源目录不能代替原文内容。
- 代码审阅前读取 [code-review.md](references/code-review.zh-CN.md)；判断跨单元架构或草稿
  一致性前读取 [cross-artifact-review.md](references/cross-artifact-review.zh-CN.md)；审阅接口、
  权限、唯一性或重试规则前读取 [behavior-contracts.md](references/behavior-contracts.zh-CN.md)。
  没有 WorkItem 的非正式只读问题也适用。只读相关方法，不因此创建事项、正式审查记录或新确认点。
- 自主调查和选择工具。普通搜索、临时笔记和子代理属于 Agent 内部工作，不需要创建
  WorkItem 或向 Strixnova 逐项记录。
- 命令和载荷使用当前公开输入合同，返回的身份及引用原样携带。不读安装包内部实现或
  测试猜字段，也不用源码或示例替代项目决定。
- 一个 WorkItem 跨仓库时仍有一个整体方向、工程方案和实际结果接受；后续仓库交付沿用
  未变化的整体接受。结果改变时，走原有修订与接受流程。
- 按已确认方案、当前切片和 CurrentAction 执行。实际结果接受后才做本地 Git 提交；
  不通过 Strixnova 推送、创建远程资源或管理 CI。除非明确要求，不用 Strixnova 管理自身。
- A0–A4 表示同一生命周期内的保障深度。方法采用来自工程政策，文件、文档或活动名称
  不决定采用何种方法、保障强度或新增工作授权。

## 让负责人容易跟上当前工作

使用中文和项目术语；陌生术语在有助于决定时解释，技术细节保留精确命令和字段名。

- 先给答案、推荐或观察结果，再说明依据。用户要求解释、备选或完整清单时保留相应深度。
- 进度更新和中断恢复时，用当前事实说明变化、剩余工作和下一执行者。复用有效决定，
  继续已授权工作；在真实用户关口提问，不逐步请示。
- 长说明按重要性排序、分组；每组约五项只是阅读建议，不限制分析、完整候选、独立决定
  或重要风险。负责人确需执行多步操作时才使用编号。
- 回答中途问题后继续原目标，除非负责人改变目标。限制与真实后续承诺进入原有记录，
  不追加无关改进或制造下一任务。
- 区分失败事实、已证实原因、未知和下一诊断动作；重复失败时重新检查假设。耗时范围
  须有依据并说明前提，否则给出下一检查点。

已有回执支持时，可以说：“校验修改已完成，回归中仍有一项失败，原因尚未确认。
我会先检查该失败；当前无需你操作。”请求完成后结束，遵守宿主要求与用户明确偏好，
同一更新不重复播报。

## 选择公开入口

| 当前请求 | 入口与资料 |
|---|---|
| 查询状态或区分首次采用与已有项目 | `strixnova status` 默认读取不可变集成版本。独立接受未提交权威候选后、编码前，才用 `--working-tree` 核对候选；它不采用文件。 |
| 查询明确仓库绑定与仓库限定内容 | `strixnova context`，不创建 WorkItem，也不采用声明。 |
| 查询历史，包括已完成和取消事项 | `strixnova history` 与[历史查询](references/history-and-upgrade.zh-CN.md)对应部分，不需要 CurrentAction。 |
| 查询或承接明确延期承诺 | `strixnova status --follow-ups` 或 `project.follow_ups`，读[延期跟进](references/follow-ups.zh-CN.md)。 |
| 首次安装或明确要求 Strixnova 自身维护 | 安装按离线包说明，维护使用 `strixnova upgrade`；只读[历史与自身维护](references/history-and-upgrade.zh-CN.md)对应部分。使用精确程序入口，Skill 文件复制不证明宿主加载。 |
| 为改动或指定模块准备审阅资料 | 先读 `strixnova context contract review`，再用 `strixnova context review`；读取[代码审查](references/code-review.zh-CN.md)。只提供版本化事实与缺口，不执行审阅者或创建 WorkItem。 |
| 开始用户明确要求管理的具体事项 | `strixnova intake`，随后按返回的下一动作继续。 |
| 重连后查找活动事项，读取当前动作或记录 | `strixnova next`。 |
| 提交、确认、交付、验证或取消 | 由 CurrentAction 和输入合同选择 `strixnova submit`、`strixnova confirm`、`strixnova delivery`、`strixnova verify` 或 `strixnova cancel`。 |
| 起草、复核或确认方案内长期权威候选 | `strixnova authority`，按下方输入种类路由；确认元数据由程序写入。 |
| 观察与更新实现对齐 | `strixnova alignment` 与[实现对齐工作流](references/implementation-alignment-workflow.zh-CN.md)，当前已确认切片必须拥有或延续相应操作。 |
| 记录外部交付、发布、部署、回滚或运维 | `strixnova activity` 与[交付规程](references/delivery.zh-CN.md)的外部活动部分。外部工具实际执行，不作为 CurrentAction 输入。 |

不在每个事项动作前查询项目状态。`strixnova alignment gc` 是单独的缓存维护，需要负责人
明确请求并接受该次 dry-run 的精确指纹。

## 保持上下文最小

1. 重连后用 `strixnova next` 查找活动事项，再用 `--work-item-id` 聚焦读取 CurrentAction。
2. 检查 `input_kind`、`intent`、`input_contract_ref`、`work_item_version` 和可用
   `record_refs`，写入前读取精确输入合同。
3. 只请求当前判断所需记录；用重复的 `--record` 批量读取已知且独立的记录。依赖本轮
   路由结果的记录等结果返回后再选。
4. 写入后使用返回的 `next`。只有事实改变或明确冲突需要核对时才重新读取相同状态。
5. 按[工程评估](references/engineering-assessment.zh-CN.md)选择适用的治理、领域和架构
   资料。影响、操作、核验与重要未知能明确说明后就提交，其余不确定性如实记录。

重要失败在针对性修正后重现时，先读[重新规划](references/replanning.zh-CN.md)的重复失败
章节，核对方案假设及证明边界，再继续有依据的下一步。

CurrentAction 列出 `engineering.execution_context` 时，在开始或恢复实施、评估验证后变化、
修订方案前读取它。该记录组合原始方向、当前切片、精确命令、方案级核验目标、精确绑定的
评估材料、未闭合发现和按已登记归属选出的项目规则。切片记录的 `execution_context` 提供
同一材料，不重复取得两份。沿既有有界子项读取取得适用正文，同时读取 `gaps` 和
`project_rules.gaps`；缺失或未绑定材料表示需要调查，不能据此忽略约束。程序保全原文和
来源版本，不要再抄写一份作为证据。语义相关性和实际实现仍由 Agent 调查；读过材料不表示
完成审阅，也不产生写入授权。
`project_rules.basis_kind` 区分集成版本规则与 `confirmed_execution_candidate`。
只有计划中的全部上游决定已与本方案绑定、且当前文件字节仍匹配确认内容时，才能采用后者。
已确认候选被改写会拒绝；普通未确认工作树文件不能替换集成规则。未闭合发现同时包含绑定
同一方案的最终权威审阅，不能只承接前期方案审阅。

聚焦事项包含已声明和被引用关系。只有用户或已知事实指向真实目标时才声明关系，
不扫描全部历史制造关联。需要追溯证据时，`engineering.trace.current` 表示已采用关系，
`engineering.trace.audit` 另含历史处置；即使事项没有当前动作，仍可通过
`strixnova next --record` 读取。

聚焦 `next` 默认返回不超过 4096 字节的完整 JSON。小值在 `records`；大值在
`record_pages`，其 `entries` 给出精确子引用 `ref`，能容纳的小值直接放在 `value`。
省略正文不表示不存在要求。通过同一 `--record` 读取必要子项，复制引用而不猜字段名；
输入合同及其 Schema 子项采用相同方式。含 `#` 或 `$` 的引用使用单引号。例如父记录可用时，
可读 `--record 'engineering.plan#/actual_result_requirements'`。
用原 `--record` 和 `--cursor` 跟随 `next_cursor`，每次续读一个记录；
`unexpanded_refs` 表示正文尚未展开的子项，`reading.unread_refs` 表示批量请求中仍须读取的记录。
后续子项读取用 `--expected-version` 和 `--expected-sha256`，后者取自
`record_sources[ref].source_sha256`；来源变化时重新读取。字符串页在 `text` 中，
按 Unicode 码点顺序沿原游标链拼接。`reading.complete=false` 不证明必需材料已读全。
形成写入前，须取得全部适用规则、必填字段和约束。`--max-output-bytes` 调整整个响应预算
（512–1048576），不代表业务记录条数；不要超过宿主容量，也不要用 Shell 筛选拼凑截断 JSON。
写命令响应被截断时，重读 `next` 及其精确记录，过去回执用 `history`；不能为了找回输出重复写入。

普通事项写入形式：

```text
strixnova <submit|confirm|delivery|verify|cancel> --work-item-id <ID> --version <work_item_version> --input @payload.json
```

项目根目录可省略 `--project-dir`，其他位置须传入。Windows PowerShell 的非 ASCII JSON
使用系统临时 UTF-8 文件，并在调用后移除：

```powershell
$strixnovaInput = [IO.Path]::GetTempFileName()
try {
  $payload | ConvertTo-Json -Depth 100 -Compress |
    Set-Content -LiteralPath $strixnovaInput -Encoding UTF8
  strixnova intake --input "@$strixnovaInput"
} finally {
  Remove-Item -LiteralPath $strixnovaInput -ErrorAction Stop
}
```

只有调用方写入原始 UTF-8 字节时才用 `@-`；Windows PowerShell 中单独设置
`$OutputEncoding` 不能保证这一点。带 `\uXXXX` 转义的 ASCII JSON 也可使用。
结构化 CLI 输出按 JSON 解析。

## 按公开输入合同继续

提出重要结论前，核对来源、对象、成立条件和证据实际支持的范围。区分材料已经证明的事实，
与前提仍待核实的推断。缺少测量不能承诺速度、容量、成本或影响很小；有范围明确的测量，
则应给出相同范围的结论。草稿不等于已采用承诺，资料缺失不等于已证实违规，更严格的建议
不等于原有要求。先调查可取得的事实；无法取得时，指出具体未知及其怎样影响判断，不编造
合理故事。证据已足以证明问题时，也应明确指出，不额外制造不确定性。这些是内部判断步骤，
不是必须展示给负责人的固定表格，也不新增确认点。负责人明确结束分析且未要求继续工作时，
整个答复只保留一句简短确认，例如“好的，本次分析结束。”不追加总结、未来邀请、随时可用
的客套语或新任务。若负责人同时要求继续实施，则执行该请求，不把结束讨论当成取消已授权工作。

提出确定结论前做反例检查：是否仍存在一种不同结果，能够满足全部已给事实？若有，较强结论
尚未成立，应指出缺少的前提，不能把该前提编造成真；若事实已经排除替代情况，就明确指出
有依据的结论。标题、对比表、建议和总结都须遵守同一证据边界，后面的保留说明不能修复
前面的确定性断言。比较方案时，筛选/全量等名称不能证明速度、规模可控、仅限可见行、可信
权限或一致性；没有来源支持的维度应写明未知，加上“通常”也不等于项目证据。建议可以说明
有条件的利弊，但须保留条件及实际请求范围。
缺少测量也应解释用户所问的功能区别。实现属性未知不代表概念没有区别，也不授权缩小原请求；
把概念选项与尚未验证的本项目实现主张分开。

`intake` 之前没有 CurrentAction，按请求和下方形成路径处理；创建后，返回的输入合同
决定载荷与状态迁移。参考资料补充推理和操作步骤。只读取对应章节，已读且仍有效的指引
可以复用。

| `input_kind` 或操作 | 阅读资料 |
|---|---|
| `direction` | [方向](references/direction.zh-CN.md) |
| `engineering_assessment` | [工程评估](references/engineering-assessment.zh-CN.md)；确有方法与影响交集时再读[工程方法](references/engineering-methods.zh-CN.md) |
| `project_authority_candidate` | [长期权威起草](references/authority-authoring.zh-CN.md)中本类权威与准备过程 |
| `project_authority_review_submission` | [跨产物复核](references/cross-artifact-review.zh-CN.md)的最终候选步骤，通过 `strixnova authority` 提交 |
| `project_authority_confirmation_bundle` | [确认规程](references/confirmation-and-cancel.zh-CN.md)的长期权威部分，通过 `strixnova authority` 提交 |
| `replan`、`target_advance_assessment`、`conflict_resolution` | [重规划](references/replanning.zh-CN.md)对应部分 |
| `resume_external_effect` | [恢复已记录副作用](references/replanning.zh-CN.md#恢复已记录副作用)，分别处理 `verify`、`delivery`、`cancel` |
| `verification`、`verification_assessment`、`conflict_retest`、`implementation_slice_completion` | [验证](references/verification.zh-CN.md) |
| `begin_implementation`、`actual_result`、`commit_and_integrate`、`integrate`、`complete_merge`、`cleanup` | [交付](references/delivery.zh-CN.md)对应部分 |
| `direction_confirmation`、`engineering_plan_confirmation`、`actual_result_confirmation`、`cancellation_decision` | [确认与取消](references/confirmation-and-cancel.zh-CN.md)对应部分 |

其他方法按实际工作选择：

- 产品前提不清、用户要求构思或压测，或外部证据会改变产品决定时，读
  [产品发现](references/product-discovery.zh-CN.md)。明确有界请求、纯技术问题可跳过；
  产品发现可以不产生 WorkItem。
- 交付跨度不清、请求 PRD/SPEC 等产物、出现持久跨单元决定或上游纠正时，读
  [产物形成](references/artifact-formation.zh-CN.md)。只有产品前提仍不清时才先做发现。
- 可观察行为改变或方案已有例子时，读[行为例子](references/behavior-examples.zh-CN.md)。
- 用户请求或方案要求代码审查时，读[代码审查](references/code-review.zh-CN.md)。
  纯写作不加载代码审查或测试资料。
- 请求交互工作或未决交互影响方向、方案时，读[UX](references/ux-design.zh-CN.md)。
- 接口、权限、并发、兼容或恢复有实质决定时，读[行为合同](references/behavior-contracts.zh-CN.md)。
- 选择实施或测试边界、执行已请求的测试先行工作时，读[实施实践](references/implementation-practices.zh-CN.md)。

## 长期权威资料

先按[起草资料](references/authority-authoring.zh-CN.md)判断首次建立、修订或审查，
再读当前权威和阶段。形成或检查产品、领域、责任和对齐含义时使用
[领域建模与对齐](references/domain-modeling-and-alignment.zh-CN.md)。这些是同一 Skill 的资料，
不需要另装工具。

| 当前需要 | 补充资料 |
|---|---|
| 类型化领域事实 | [领域事实合同](references/domain-fact-contracts.zh-CN.md) |
| 架构模块、关系、约束、事实处置或阶段 | [架构合同](references/architecture-artifact-contracts.zh-CN.md) |
| 源码归属、依赖、责任或偏离 | [实现对齐合同](references/implementation-alignment-artifact-contracts.zh-CN.md) |
| 方法采用、来源、规则裁剪或验证政策 | [工程政策合同](references/engineering-policy-contracts.zh-CN.md) |
| 跨产物一致性、切片就绪或负责人展示 | [跨产物审阅](references/cross-artifact-review.zh-CN.md) |
| 精确领域模型的阅读文档 | [领域文档](references/domain-documentation.zh-CN.md) |

使用每个产物的公开版本、字段和身份。当前源码、执行证据与方法采用来源分别归属，
起草时保持这些边界。

## 创建事项

用户明确要求管理具体事项后，直接从请求创建，不先做影子访谈：

```json
{"title":"short title","request":"the user's request without invented scope"}
```

通过 `strixnova intake --input @payload.json` 提交并跟随 `next`。调查和实质澄清在方向阶段
完成；尚不能识别具体事项的愿望可以停留在发现阶段，也可以搁置或否定。

出现 `project.direction_context` 时，读取完整紧凑目录、选择相关能力并逐项处置护栏。
向用户解释含义，内部引用由 Agent 携带。

## 用户确认

普通事项有方向、工程方案、实际结果三个关口。产品、领域、架构或工程政策首次采用和
实质修订有各自独立的权威决定。

按[确认规程](references/confirmation-and-cancel.zh-CN.md)完成展示、后续答复解释和命令绑定。
Agent 保留完整原话并经公开命令提交，程序写确认元数据；提问和解释不构成接受。
实施前完成当前权威复核与确认步骤，实现对齐草稿只在实际结果接受后采用。

出现 `authority_conflict` 时核对最新 CurrentAction 和事实。其他明确错误在授权范围内修正
对应输入或项目条件；保留证据并报告无法消除的歧义，不绕过门禁。
