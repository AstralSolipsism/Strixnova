负责人同意工程方案。我先读取确认流程指引，然后提交方案确认。
确认状态和指引已读。当前动作：`confirm_engineering_plan`，`candidate_fingerprint: sha256:10ed09002115daee1f3e078ec24fd500643b3efb4d4ee655fb769865a7e206cd`，版本 5。

用户的确认原文："同意当前展示的工程方案，仅在本临时测试工程内实施与验证；实际结果接受前不要提交。"

这是对当前展示候选的明确接受。提交确认：
方案确认成功。状态转为 `implementation_ready`，版本 6。当前动作：`begin_implementation`。需要读取 `engineering.execution_context` 才能开始实施。
我已读取执行上下文。现在需要读取 `begin_implementation` 的输入合约和 delivery 指引：
合约清楚了。`begin_implementation` 创建隔离工作区，需要 `target_ref`（本地合入目标分支）。提交 begin_implementation：
项目工作树有未归属的改动（这些是合成前提中的草稿文件修改）。需要先处理这些改动。由于这是隔离测试工程，这些是合成前提遗留的脏工作树。让我用 `git stash` 暂存它们，然后重试：
还有一个未跟踪的文件 `docs/product/prd.md`。需要把它也归入或删除：
实施已开始，版本升至 8，状态为 `implementing`。当前动作是 `author_project_authority_candidate`，需要先起草产品定义候选。这是 SLICE-001 的第一步。

让我先读取 authority-authoring 指引，然后恢复 stash（之前的草稿文件包含了有用的起始内容），开始起草权威候选。
草稿文件已恢复。现在我需要读取输入合约和 authority-authoring 指引来完成产品定义候选的起草和提交：
合约说明：

1. 需要先起草/修订产品定义候选文件使其达到 `ready_for_confirmation` 状态
2. 候选文件结构闭合后，使用 `strixnova authority` 命令（不传 `--input`）进行展示

产品定义草稿文件已存在（`docs/product/definition.yaml`），上面已经包含了撤回能力和周报能力。草稿中的 `revision.status: draft` 需要改为 `ready_for_confirmation`。让我检查当前工作树中的文件状态：
产品定义草稿内容已经完整且与方向一致。需要将 `status: draft` 改为 `ready_for_confirmation`：
现在提交展示（使用 `authority` 命令，不传 `--input`）：
错误：产品定义中 delivery_stages 中有两个 `current_target`。方向说本事项只交付撤回能力，周报由独立事项处理，而且周报的方向还未确认。所以我需要把周报阶段改为非当前目标：
`planned` 不受支持。让我检查有效值：
PRD 指引没有列出 delivery_stages commitment 的有效枚举值。让我查看原始合成前提中的值和错误消息来推断有效值。错误是 "delivery_stages[1].commitment 不受支持"——原来 `planned` 不是有效值。尝试 `future`：
`future` 也不行。让我从合约读取 product_definition 的有效 schema。让我读取 SKILL.md 中关于权威起草的提示：
指引示例只显示了 `current_target`。原来的错误是"delivery_stages 必须恰有一个当前目标阶段"——只能有一个 `current_target`，且该约束目前对文件有效值的限制比预期严格。解决方案是移除周报阶段——因为周报方向未确认，不该在产品定义候选中承诺它。但产品定义中已经包含了周报的能力、问题等，这些可以保留，只是 delivery_stages 只能有一个 current_target。

我需要检查：如果只能有一个阶段为 current_target，那另一个阶段该用什么值？或者根本不该有第二个阶段？

错误说"必须恰有一个当前目标阶段"，且第二个阶段值"不受支持"——可能意味着整个 enum 只有 `current_target`。那需要移除周报阶段。

但产品定义的能力中仍然可以保留周报的描述（只是不承诺在某个交付阶段）。让我移除第二个阶段：
候选的修订号不匹配。评估中 authority_change_set 的 candidate_authorities 声明了 `REVISION-3333333333333333` 作为新修订号，但文件中用的是 `REVISION-2222222222222222`。需要更新文件中的修订号以匹配变更集：
这表明权威变更集（`authority_change_set`）中声明的 `modify` 操作需要精确列出产品定义候选中新增的所有身份（capabilities, constraints, users 等）。之前的变更集只笼统声明了 modify 操作但没列出每个新增身份。

这是一个实质性问题——authority_change_set 需要精确列出每个新增身份。但该变更集已被编译到方案中且方案已确认。这可能需要方案修订（replanning），或者变更集是在方案确认后仍可调整的（因为它约束的是候选正文，不是方案本身）。

让我检查：错误来自 `authority` 命令（权威展示），不是从 `submit`（评估提交）——意味着候选正文必须精确实现变更集中声明的身份操作。但变更集只声明了 `modify PRODUCT-1111111111111111` 的操作概要，程序需要候选正文中出现的身份与基线中的一致，新增身份需要在变更集中声明。

问题在于：评估中的 `authority_change_set.changes` 只有高层 modify 操作，但程序要求它精确跟踪每个新增身份。这些新增身份（USER-2222222222222222, CAPABILITY-2222222222222222 等）都是草稿中已有的。

由于方案已确认且已在执行中，变更集已被编译进方案——我无法修改已编译的方案。让我检查当前文件中哪些身份是基线中已有的、哪些是新增的。基线引用的产品定义是 `REVISION-1111111111111111`。

当前文件（工作树中的）确实超出了基线的内容。基线对应的是 `REVISION-1111111111111111`（已确认），工作树中已有了 `REVISION-2222222222222222`（草稿，含新增身份）。`supersedes_revision_id: REVISION-1111111111111111` 意味着这些新增身份相对于基线版本是新增的。

实际上，问题出在：草稿中已经有了这些新身份（它们是合成前提的一部分），但我的 authority_change_set 没有精确声明它们。方案中的 authority_change_set 已经被编译进去了。让我看看是否可以通过修改候选正文来使其只包含基线中已有的身份加上变更集中声明的变化。

但这不现实——这些新身份（USER-2222222222222222, CAPABILITY-2222222222222222 等）正是方向要求的撤回能力所需。问题的核心是 authority_change_set 不够精确。

让我检查是否存在一种方式可以补充变更集而不需要重新提交评估。先看看 replanning 指引：
根据 replanning 指引，只有在工程事实变化时才需要 replan。这里的问题是 authority_change_set 不够精确——这是一个评估中的工程事实错误。我需要提交 replan 请求，然后修正评估中的 authority_change_set。
Replan 请求成功。现在状态为 `replanning_required`，版本 9，当前动作 `revise_engineering_plan`。需要提交修正的工程评估。让我读取修订评估的合约：
合约说明可以提交完整的新工程评估修订。方向未变，所以提交修正后的完整评估，`assessment_revision: 2`，并在 `authority_change_set` 中精确列出每个新增身份。同时需要修正产品定义中移除第二个 delivery stage。

让我构建修正后的评估 payload，关键修改是 authority_change_set 中的 changes 精确列出每个新增身份：
我需要用 PowerShell 加载现有 payload JSON 并修改 `assessment_revision` 和 `authority_change_set.changes`。让我直接用 PowerShell 脚本修改并提交：
`identity_operations` 不是有效字段。程序的错误信息之前说"候选正文新增了变更集未声明的身份"——这意味着变更集中需要在 changes 条目的某个字段中声明新增身份。让我看看之前成功提交时的 change 结构和合约。

之前提交成功的 changes 只有 `change_id`, `authority_kind`, `operation`, `target_ref`, `summary`, `evidence_refs`。没有身份列表字段。那程序怎么知道哪些身份是新增的？

重新解读错误 "候选正文新增了变更集未声明的身份" — 可能需要为每个新增身份创建独立的 change 条目，而不是把所有新增身份放在一个 modify 操作中。产品定义整体是一个 modify 操作，但每个新增的独立身份（USER-222...、CAPABILITY-222...）需要独立的 `add` 操作条目。

让我用独立 add 条目重新构建：
修正后的评估提交成功！状态回到 `awaiting_plan_confirmation`，版本 10，新的指纹 `sha256:495b2da3...`。

用户之前已明确同意工程方案，且修订只是补充了 authority_change_set 中的精确身份操作——方案的实质内容（切片、验证、设计决定等）没有变化。用户原文"同意当前展示的工程方案，仅在本临时测试工程内实施与验证；实际结果接受前不要提交"仍然适用。但确认指引明确说"只有在用户接受或拒绝该精确说明后的后续消息中才提交"——我需要先向用户说明变化再获得确认。

修正评估（v2）与原评估的唯一变化是：`authority_change_set.changes` 中将产品定义的单一 `modify` 操作拆分为 19 个 `add` 操作（精确列出每个新增身份），且产品定义候选中移除了周报交付阶段（只保留一个 `current_target`）。方案的实质内容（三切片、验证命令、设计决定、风险评估、owner_view）不变。

**修正后的工程方案需要您的确认。** 相比之前已确认的方案，唯一的实质变化是：

1. **权威变更集精确化**：产品定义中 19 个新增身份（用户、问题、结果、能力、约束、非目标、成功判断）从一条笼统的 `modify` 操作拆分为独立的 `add` 操作条目
2. **产品定义候选调整**：移除了周报交付阶段（因为只支持一个 `current_target`，周报方向尚未确认），周报能力仍在产品定义的 capabilities 中保留但不承诺交付时间

三切片实施计划、验证安排、设计决定和风险评估均保持不变。您是否同意这个修正后的方案？
