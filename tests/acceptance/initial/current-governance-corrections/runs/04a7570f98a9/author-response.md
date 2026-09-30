收到诊断反馈。四类候选中三类有结构/引用/身份问题需要修正：

1. **product_definition** — 通过 ✓
2. **domain_model** — 领域来源 facts[0] 有非法字段（lineage, retirement_reason）和缺少必填字段（content）
3. **target_architecture** — 17 个未声明新增身份、4 个未声明删除身份、修订号不匹配（planned ARCHREV-3333 vs actual ARCHREV-2222）、status 仍为 draft
4. **engineering_policy** — DDD 采用缺少四个必要技术

开始读取必要合约和当前候选文件：
发现了问题。`facts[0]`（FACT-2222222222222222）状态为 `draft` 但使用了 `lineage` 和 `retirement_reason` 字段——按合约，这些字段只允许在 `superseded` 或 `retired` 状态下使用，活动事实不允许。且 `draft` 事实必须有 `content` 字段。解决方案：将状态改为 `superseded`。

但合约说"活动事实的状态必须与根文件的 revision.status 完全一致"——`superseded` 不是活动事实，所以不受此限制。现在读取架构文件和工程政策：
现在我清楚了所有四个问题。让我逐一修正：

**1. 领域来源 facts[0]**：FACT-2222222222222222 状态 `draft` 但有 `lineage` 和 `retirement_reason`（只允许 `superseded`/`retired`）且缺少 `content`。修改状态为 `superseded`。

**2. 架构**：revision_id 要改为 ARCHREV-3333333333333333，status 改为 ready_for_confirmation。分文件的 revision_id 也要同步。domain_model_ref 也需要更新到 MODELREV-3333333333333333。还要在 authority_change_set 中声明所有新增和删除的身份。

**3. 工程政策**：DDD adopted_technique_ids 为空，需要添加四个必要技术。product_definition_ref 也需指向 REVISION-3333333333333333。

开始修正文件：
同时更新领域来源的 model_revision_id 以匹配新修订号：
现在更新领域模型根文件的修订号和状态：
合约说活动事实的状态必须与根文件的 revision.status 完全一致。将所有活动事实的 status 从 `draft` 改为 `ready_for_confirmation`：
验证领域来源文件的状态更新结果：
好的，FACT-2222222222222222 保持 `superseded`，其余活动事实都是 `ready_for_confirmation`。同时更新领域集合的修订号：
现在修正架构——修订号、状态，以及 domain_model_ref：
更新架构分文件的 revision_id——modules、relationships、constraints、domain-facts、stages：
现在修正工程政策——DDD adopted_technique_ids 和 product_definition_ref：
更新工程政策的 product_definition_ref 和 revision：
现在需要收集架构分文件中的所有身份。让我列出架构中的所有身份，以便在 authority_change_set 中精确声明新增和删除：
与诊断中列出的 17 个 undeclared_additions 完全一致。还有 4 个 undeclared_removals（基线中的旧身份）：MODULE-1111111111111111, INTERFACE-1111111111111111, CONSTRAINT-1111111111111111, ARCHSTAGE-1111111111111111。

同样需要收集领域模型中的身份变化。让我构建完整的修订评估（revision 3），精确包含所有四类权威的所有身份操作：
领域有 34 个事实 ID。基线中原有的 fact_ids：FACT-2222222222222222（被替代→superseded）和 FACT-3333333333333333（保留）。其余 FACT-A* 都是新增。

现在构建修正的评估 payload（revision 3），包含所有四类权威的完整精确身份操作：
当前动作是 `confirm_engineering_plan`（方案确认），而不是 `revise_engineering_plan`。需要先触发 replan，才能提交新的评估。让我先查看当前状态：
当前是 `awaiting_plan_confirmation`，版本 10。需要先通过 `request_changes` 将方案退回，然后才能提交修正的评估。诊断发现了候选结构问题，负责人的消息（诊断反馈）实际是对当前方案的退回：
状态回到 `needs_engineering_assessment`，版本 11。现在可以提交修正的评估了。也保留了工作区分支：
两类错误：
1. `change_id` 格式无效——模式是 `^AUTHOP-[0-9A-F]{16}$`，需要16位十六进制，而我的脚本只生成了3位（AUTHOP-001 等）。
2. `operation: remove` 不是有效值，必须是 `add`、`modify`、`rename`、`retire`。架构旧身份的移除应该用 `retire`。

修正后重试：
change_id 格式还是无效。出错的序号是 9,10,11...——这些是 index 从 0 开始的第 10、11 等项。pattern 要求 `^AUTHOP-[0-9A-F]{16}$`——必须是大写十六进制。让我检查第 10 项的 change_id：
格式看起来正确——都是16位大写十六进制。问题可能出在 PowerShell 的 ConvertTo-Json 输出中 hex 字母变成了小写！让我验证：
大写是正确的。让我直接检查被拒绝的输出中生成的实际 change_id——用 scratch 文件保存再查看：
格式是正确的。那在实际提交时出了什么问题？被拒绝的序号从 index 9 开始。注意：错误中列的索引是 9,10,11...14, 25...30, 41...46, 57...62, 73。这些间隔都是从第 10 个、第 26 个等开始——可能和 PowerShell 的 `$hex` 变量作用域有关，导致在 function 内部 `$script:n` 不递增。

让我用完全不同的方法——预先将完整 payload 写入 JSON 文件，确保所有 change_id 正确：
只找到 1 个 change_id——ConvertTo-Json -Compress 把 changes 数组内嵌了。让我验证总变更数：
74 个变更，格式都正确。让我提交：
同样的错误。被拒的索引模式是 9,10,11,12,13,14, 25,26,27,28,29,30, 41,42,43,44,45,46, 57,58,59,60,61,62, 73——每 16 项中的最后 6 项。这些是 change_id 包含字母 A-F 的。模式 `^AUTHOP-[0-9A-F]{16}$` 应该允许大写字母。但可能实际的正则不含 A-F？

让我检查原始成功提交中使用的 change_id 格式——评估 v2 的四个变更用的是 `AUTHOP-001` 到 `AUTHOP-004`——不对，v2 也成功了。等等，评估的原始 change_set_id 用的是 `AUTHCHANGE-DEC6155000000001`，但 change_id 要求可能不同。

让我从合约中读取精确的 change_id 格式：
合约 JSON 深度不够。让我查看 authority-authoring.md 中有没有 change_id 的格式说明：
AUTHOP 没有在参考文档中出现。让我检查 engineering-assessment.md 中 change_id 的格式：
让我直接用 Python 查看原始 JSON 中被拒的实际值：
模式很清楚了！所有被拒绝的 change_id 都包含字母 A-F。这意味着正则实际只允许 `[0-9]`，不允许字母！pattern 可能是 `^AUTHOP-[0-9]{16}$`。让我使用纯数字 change_id：
现在所有 change_id 都是纯数字。提交：
change_id 格式错误解决了！现在的错误完全不同——"authority_change_set 声明了 domain_fact_changes 未登记的领域 Fact 变化"。这意味着领域事实变化需要登记在一个独立的 `domain_fact_changes` 字段中，而不仅仅在 `changes` 里。

让我读取 authority_change_set 的合约中关于 domain_fact_changes 的定义：
`domain_fact_changes` 是评估的顶层字段，独立于 `method_applications`。需要在评估 payload 中添加这个字段。让我检查合约 schema 中 domain_fact_changes 的结构：
合约信息需要重新读取。让我从 `strixnova next` 重新获取完整的 engineering-assessment schema 中 domain_fact_changes 字段：
路径太深了。让我直接查看 engineering-assessment.md 中 domain_fact_changes 的说明：
让我搜索 domain_fact_changes 的具体 JSON 结构：
现在清楚了！`domain_fact_changes` 是评估顶层字段，需要为每个新增/修改/保留的领域事实创建一条条目，格式如上所示。每条需要 `disposition`（retain/add/update/retire）、`target_ref`（含 model_id, fact_id, observed_commit）、`source_path`、`reason`、`evidence_refs`、`lineage`。

这是一个大工作量。让我用 Python 脚本构建：
提交修正的评估：
两个问题：
1. FACT-2222222222222222 在 authority_change_set 中用 `modify` 但 domain_fact_changes 中用 `retire` → 需要统一为 `retire`
2. 所有 domain_fact_changes 的 source_path 缺少一致的计划文件操作 → 需要在 `operations` 中为 `docs/domain/sources/core.yaml` 添加一个 modify 操作
进展！change_id 和 domain_fact_changes 错误已解决。新错误：新增的 operations[16-22] 缺少 `evidence_refs` 和 `implements` 字段，且未被 implementation_slices 覆盖。

修复：为新操作添加缺失字段，并将它们归入 SLICE-001（权威候选修订切片）：
等等，SLICE-001 之前可能已经有 operation_indices。让我检查一下 SLICE-001 原来的值并包含它们：
SLICE-001 之前没有 operation_indices（它的 ops 只是我刚加的 16-22）。那原来的 operations[0-15] 归属在哪些 slices？可能 SLICE-002 和 SLICE-003 之前有值但被我的脚本影响了。让我从原始 payload 检查：
原始 payload 也没有 operation_indices。那么原始提交成功时 16 个 operations 是怎么被 slices 覆盖的？可能原来提交成功时每个 slice 用了不同的字段来引用 operations。

让我检查原始 SLICE-001 的完整结构：
原来是 `operation_refs` 不是 `operation_indices`！修正：
现在重新提交：
`implements` 不能为空。每个 operation 需要至少一个 implements 引用。修正：
**评估 v3 提交成功！** 状态 `awaiting_plan_confirmation`，版本 12，新指纹 `sha256:886cc7bb...`。

现在展示修订差异和当前方案给负责人：
## 评估修订 v3 已提交成功

**当前状态**：`awaiting_plan_confirmation`，版本 12，等待负责人确认。

### 诊断反馈修正摘要

根据您提供的四项候选结构诊断，所有问题已修正并通过校验：

| 权威类型 | 诊断问题 | 修正措施 |
|---------|---------|---------|
| **领域模型** | facts[0] 非法字段 `lineage`/`retirement_reason`、缺 `content` | 状态从 `draft` 改为 `superseded`（退役事实允许这些字段，不需要 content） |
| **目标架构** | 17 undeclared additions, 4 undeclared removals, revision mismatch | 修订号→`ARCHREV-3333333333333333`，状态→`ready_for_confirmation`，变更集中 17 add + 4 retire 精确声明 |
| **工程政策** | DDD 缺少 4 个必要技术 | 添加 `bounded_context`, `context_map`, `domain_invariant_trace`, `ubiquitous_language` |
| **评估结构** | 领域事实变化未用 `domain_fact_changes` 字段 | 新增 34 条 domain_fact_changes 精确对应领域来源 |

额外修正：change_id 格式（纯数字 16 位）、`operations` 补全 `evidence_refs`/`implements` 字段并归入 SLICE-001。

详细差异见 [engineering-plan-WI-DEC61550.md](file:///C:/Users/%E6%9F%B3%E5%B7%9E%E5%B1%80/.gemini/antigravity-cli/brain/7e0d32aa-b9b5-42cd-8ed1-02a5b11a9f06/engineering-plan-WI-DEC61550.md)。等待您的审阅。
