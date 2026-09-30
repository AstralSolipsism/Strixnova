先确认 task-271 终态和公开事项状态：
task-271 已被取消（CANCELED），无实际进程。查看其日志确认是否有输出：
task-271 无输出，已终止。现在核对公开事项状态：
确认：版本仍为32，`present_actual_result` 仍是当前动作。结果尚未登记。task-271 的投递在进程启动后因服务器重启被取消，未到达 Strixnova。

现在重新提交。上轮已修正的 payload 文件（含 `semantic_finding_results`）仍然存在：
Payload 存在。重新投递：
等待完成通知。同时读取 behavior-examples 参考（实际结果需要报告行为例子）以备后续展示：
仍在执行中，等待定时器或任务完成通知。
错误：`semantic_finding_results[0]` 引用了 `"direction"` 作为 evidence_ref，这不被识别为有效的实际证据引用。`evidence_refs` 中只能使用 verification receipt IDs、`delivered_outcomes[n]`、`artifact:<id>` 或其他被接受的引用格式。

修正 semantic_finding_results：`direction` 不是有效的 evidence_ref，需要改用 receipt ID 或 delivered_outcomes 引用：
同时检查其他 evidence_refs 中的 "direction" 和 "SRC-*" 引用——这些可能也是不被接受的格式。让我检查 verification_review_results 中的引用：
存在大量 `"direction"` 和 `"SRC-*"` 引用。这些可能在 verification_review_results 和 governance_rule_results 中是合法的（来自计划的 evidence_refs）——不同于 semantic_finding_results。错误只提到了 `semantic_finding_results[0]`，所以其他地方的可能是合法的。

但为了安全，让我先试提交，看程序是否接受：
`governance_rule_results[0].evidence_refs` 也不接受 `"direction"`。所有 `evidence_refs` 只能使用 receipt IDs、`delivered_outcomes[n]`、`artifact:<id>` 等实际结果中的引用。让我全面清理：
需要全面清理所有 `"direction"` 和 `"SRC-*"` 引用。这些只在计划的 evidence_refs 中有效，但在实际结果的 evidence_refs 中只能引用实际产物（receipt IDs、`delivered_outcomes[n]`、`artifact:<id>`）。

用 `delivered_outcomes[n]` 代替非 receipt 引用：
现在也修复 verification_review_results 中的 "direction" 和 "SRC-*" 引用：
验证一下是否还有残留的 "direction" 或 "SRC-" 引用：
干净了。重新提交：
还有13个 FACT 缺少结果：FACT-2222222222222222, FACT-3333333333333333, FACT-A000000000000001 到 FACT-A00000000000000B。我之前只包含了 FACT-A00000000000000C 到 FACT-A000000000000020，缺了前面的。让我读取完整的 `actual_result_requirements` 中的 domain_fact_changes：
输出被截断了头部。让我提取缺失的 FACT IDs。我缺少：FACT-2222222222222222, FACT-3333333333333333, FACT-A000000000000001 到 FACT-A00000000000000B（共13个）。所有都是 `planned_disposition: "add"`, `observed_commit: "45b1b5cef4bd66ae967994f8373a11f362d20644"`。

直接用 PowerShell 生成缺失的 FACT 条目并追加到 payload：
34个事实条目现在完整了。重新提交：
进步了！前面的 domain fact 和 governance 和 semantic finding 问题全解决了。现在缺 `direction.constraint:DIRCON-A000000000000002` 的审阅结果。这是方向约束"方向确认后需完成产品、领域、架构和工程政策的首次修订并确认，才能开始实施"。

需要在 `verification_review_results` 中添加这个约束的审阅。让我读取完整的 verification targets 看有没有遗漏的约束目标：
缺少 `direction.constraint:DIRCON-A000000000000002`。它在 verification_targets 中但我之前没在结果中看到（被截断了），需要作为 agent_review 添加。

用 PowerShell 直接追加：
又进步了！`long_lived_trace_missing` — 缺少工程政策的长期引用。工程政策 `POLICY-1111111111111111` 需要在 `long_lived_refs` 中声明。类型是 `quality_policy`。
