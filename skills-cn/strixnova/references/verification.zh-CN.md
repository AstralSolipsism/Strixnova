# 验证（中文审阅映射）

判断待处理回执或检查已有收集报告时，按 [prepared-input.md](prepared-input.zh-CN.md) 取得程序提供的精确输入变化事实及测试根/node ID 失配。断言充分性与重测判断仍由 Agent 给出；`action cases` 只读，不执行 pytest 收集。

`verification_status` 汇总已计划命令。逐项目标安排位于计划 `verification_targets`，最终证据另在 `target_verification` 汇总。命令与计划中的 Agent 审阅都要完成；命令状态为 `not_required` 不会消除审阅义务。交付输入说明 `verification_review_results`，语义审阅不制造测试命令，也不声称机器证明。

计划包含例子时读取[行为例子与核验](behavior-examples.zh-CN.md)。自动例子也需要断言充分性审阅；从已确认命令读取 `case_report` 绑定。`verification_status=passed` 本身不证明绑定用例实际运行或断言充分。报告器在 `mode=run` 时提供，不提前生成报告。

上下文还没有命令身份时，读取 CurrentAction 指定的精确
`engineering.plan.verification_commands`。它包含每个已确认 `command_id`、`argv`、`cwd`、`run_kind`、`covers` 和 timeout；不得按列表位置猜 ID，也不凭记忆重建。只执行 Agent 在已确认评估中明确放入的命令。

同一命令出现在不同 ImplementationSlice 时代表不同代码状态，不能合并；必须保留不同 `command_id` 并分别取得回执。只有同一切片内完全相同的命令可归并，全部原始引用仍指向该切片同一 ID。不能为绕过绑定错误而改参数制造假差异。

聚合 `verification_status` 只有四种：

- `not_required`：已确认评估没有适用命令；
- `pending`：仍缺命令回执、事后判断或需要重测；
- `passed`：每个必需命令的最新回执通过；
- `completed_with_issues`：失败、阻断或 not-run 已完成评估。

只由 CurrentAction 决定下一步，不能从其他 boolean 推断就绪。

## 完成没有命令的切片

`input_kind=implementation_slice_completion` 时，不跳到实际结果。先完成聚焦切片的所有计划操作，按完成条件复核，再通过 `strixnova submit` 提交公开
`strixnova.implementation-slice-completion.v1`。Strixnova 会检查累计工作树路径，后续切片或计划外路径仍被拒绝。`semantic_content_machine_proven=false`：记录表示 Agent 完成了工作和复核，不把复核变成机器语义证明。

## 运行命令

出现 `verification_execution_unclosed` 时，进程树尚未确认结束。先读[历史与自身维护](history-and-upgrade.zh-CN.md)，核验并收口对应操作后再重试；不能从该失败推断已有完成的验证回执。

普通验证动作的 `mode: "run"` 执行已确认 argv 并形成回执。若当前为 `resume_external_effect` 且 `intent=verify`，按[恢复规程](replanning.zh-CN.md#恢复已记录副作用)使用同一模式核对已有执行与回执；已经结束的执行不应在其他 shell 中再次启动。

普通计划命令也不要先在 shell 重跑；外部运行没有 Strixnova 回执，随后会被再次执行。实施中只用当前需要的最小反馈命令，不提前手工跑最终 fast/full 矩阵。

```json
{
  "command_id": "VC-001",
  "mode": "run",
  "limitations": []
}
```

```text
strixnova verify --work-item-id <ID> --version <V> --input @payload.json
```

只有在发生冲突的交付仓库执行的命令才增加 `"execution_area":"target"`；其他命令使用各自工作区或只读输入副本。命令运行前不能预言它是否改代码。

运行后 Strixnova 返回回执与下一动作。若下一输入为 `verification_assessment`，检查执行后的 Git 状态。命令若产生不属于任何已确认操作的路径，Strixnova 用
`unplanned_repository_change` 单独报告，不与
`implementation_slice_path_not_ready` 混淆。只清理已经核实为本命令产生的一次性副产物；误改则恢复。真实持久路径若是已确认责任必需内容，不隐藏或删除，提交
`strixnova.replan-request.v1`。Strixnova 不自动删除，也不把计划外路径当作后续切片证据。

```json
{
  "command_id": "VC-001",
  "mode": "assess",
  "receipt_id": "VR-...",
  "code_change_assessment": {
    "changed_after": false,
    "needs_retest": false,
    "rationale": "..."
  }
}
```

正常循环严格是：

```text
verification CurrentAction -> verify mode=run -> receipt
-> inspect post-run Git facts -> verify mode=assess
```

回执后相关代码变化时，把 `needs_retest` 设为 true，待实现稳定后重跑。

有用例证据的命令还会比较声明输入文件的实际字节与执行快照，包括未提交改动。变化会使证据失效并要求重测，不覆盖旧回执或 Agent 的原有事后判断。声明输入范围之外的依赖由 Agent 自行检查；行为变化需要修订方向。

## 无法运行

只有真实环境或授权限制才用 `not_run`：

```json
{
  "command_id": "VC-001",
  "mode": "not_run",
  "not_run_reason": "...",
  "limitations": ["..."],
  "code_change_assessment": {
    "changed_after": false,
    "needs_retest": false,
    "rationale": "..."
  }
}
```

`not_run`、`failed`、`blocked` 是诚实证据，不是成功；其限制必须进入 ActualResult。不得换标签重跑同一宽命令制造“独立覆盖”。


已确认命令的 `repository_id` 选择执行仓库；`input_repository_ids` 声明实际输入仓库并包含执行仓库。verify 请求不另加仓库字段。只读输入按声明版本捕获到隔离副本，不修改依赖仓库；执行后仍须评估回执。

没有后端源码时，在验证命令中声明 `dependency_checks`。命令实际核验后向 stdout 输出下面的证据行；必须替换为真实观察，不能回显预期值伪造证据。服务时效为 1–604800 秒；制品允许 `null`。缺失、不匹配、格式错误或过期不能成为完整通过，HTTP 成功不证明版本或后端源码覆盖。

```json
{
  "dependency_checks": [{
    "dependency_id": "backend-api", "kind": "service",
    "expected_version": "backend-v7",
    "expected_contract_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    "environment": "staging", "max_age_seconds": 300
  }]
}
```

```text
STRIXNOVA_DEPENDENCY_EVIDENCE={"schema_version":"strixnova.dependency-observation.v1","dependency_id":"backend-api","version":"backend-v7","contract_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","environment":"staging","evidence_refs":["deployment:observed-record"]}
```
