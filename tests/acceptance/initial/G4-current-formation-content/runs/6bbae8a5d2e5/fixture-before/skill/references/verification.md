# Verification

`verification_status` summarizes planned commands. Per-target arrangements
live in the plan's `verification_targets`, and their final evidence is summarized
separately in `target_verification`. Complete the planned Agent reviews as well
as the commands; `not_required` for commands does not erase a review obligation.
The delivery input explains `verification_review_results`; do not create a fake
test command or claim machine proof for semantic review.

For a plan containing examples, read [behavior-examples.md](behavior-examples.md).
An automatic example also requires an assertion-adequacy review. Read its
`case_report` binding from the confirmed command; `verification_status=passed`
alone does not prove the bound cases ran or their assertions are sufficient.
The reporter is supplied during `mode=run`; do not pre-generate its report.

When the command identity is not already in context, read the exact
`engineering.plan.verification_commands` record named by CurrentAction. It
contains each confirmed `command_id`, `argv`, `cwd`, `run_kind`, `covers`, and
timeout; never guess an ID from list position or reconstruct one from memory.
Execute only commands the Agent explicitly placed in the confirmed assessment.

同一条命令在不同 ImplementationSlice（实施切片）中出现时，不是可以合并的一次运行：每个
切片代表不同的代码状态，必须保留不同 `command_id`（命令标识）并分别取得当前回执。只有
同一切片内完全相同的命令才可归并；归并后仍须让全部原始引用指向该切片的同一命令标识。
代理按评估中的真实验证时机声明命令，不得为了绕过绑定错误改写参数制造伪差异。

Coverage has one aggregate `verification_status`: `not_required` when the
confirmed assessment has no applicable command, `pending` while a command or
post-run judgment is missing or needs retest, `passed` when every required
latest receipt passed, and `completed_with_issues` for assessed failed,
blocked, or not-run results. CurrentAction alone tells you what to do next; do
not infer readiness from another boolean.

## Complete a slice that has no command

When CurrentAction（当前动作）returns
`input_kind=implementation_slice_completion`（输入种类为实施切片完成记录）, do not
skip directly to the actual result. Finish every planned operation in the focused
slice, review its stated completion criteria, and submit the exact public
`strixnova.implementation-slice-completion.v1`（实施切片完成记录第一版）payload through
`strixnova submit`（Strixnova提交命令）. Strixnovachecks the cumulative working-tree
paths before recording completion, so a later slice path or an unplanned path is
still rejected. Keep `semantic_content_machine_proven=false`（机器未证明语义）: the
record says the Agent（智能编码代理）performed the planned work and review; it does not
turn that review into machine proof.

## Run a command

If execution reports `verification_execution_unclosed`, its process tree was
not confirmed stopped. Read [history-and-upgrade.md](history-and-upgrade.md)
and resolve the exact unclosed operation before retrying; no completed
verification receipt should be inferred from that failure.

For an ordinary verification action, `mode: "run"` executes the confirmed argv
and creates the receipt. For `resume_external_effect` with `intent=verify`, use
[the recovery procedure](replanning.md#resume-a-recorded-effect): the same mode
reconciles the recorded execution and receipt. An already-finished execution
must not be started again in a separate shell.

Do not first rerun a normal planned command in a shell: an external run creates
no Strixnova receipt, so Strixnova would execute it again. During implementation,
use only the smallest development feedback command you actually need; do not
manually pre-run the final fast/full verification matrix.

```json
{
  "command_id": "VC-001",
  "mode": "run",
  "limitations": []
}
```

Submit it with:

```text
strixnova verify --work-item-id <ID> --version <V> --input @payload.json
```

Only a command executing in the repository whose merge conflict is being resolved uses `"execution_area":"target"`; other commands use their recorded work area or captured read-only input. Do not predict whether
the command changes code before it runs.

After the run, Strixnova returns the receipt and a next action. If the next input
kind is `verification_assessment`, inspect Git state after execution and submit:

如果命令产生了不属于任何已确认工程操作的路径，Strixnova会用
`unplanned_repository_change`（计划外仓库改动）单独报告，不再混同为
`implementation_slice_path_not_ready`（实施切片路径尚不可用）。只清理已经核实为该命令
产生的一次性副产物，例如精确列出的缓存文件；误改则恢复。如果某个持久路径确实是实现
已确认责任所必需，不得隐藏或删除它，应提交
`strixnova.replan-request.v1`（重新规划请求第一版）。Strixnova不会自动删除文件，
也不会把计划外路径冒充成已经实施后续切片的证据。

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

The normal loop is exactly:

```text
verification CurrentAction -> verify mode=run -> receipt
-> inspect post-run Git facts -> verify mode=assess
```

If relevant code changed after the receipt, set `needs_retest` true and rerun
after the implementation stabilizes.

For commands with case evidence, Strixnova also compares the declared input files'
actual bytes with their execution snapshot. A change, including an uncommitted
one, makes that evidence stale and requires retesting without overwriting the
old receipt or the Agent's recorded assessment. Inspect dependencies outside
the declared input scope yourself. A behavior change requires direction revision.

## Cannot run

Use `not_run` only for a real environmental or authorization limitation:

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

`not_run`, `failed`, and `blocked` are honest evidence, never success. Carry
their limitations into the actual result. Do not rerun the same broad command
under another label to manufacture independent coverage.


The confirmed command's `repository_id` selects its execution repository; `input_repository_ids` declares actual repository inputs and includes that repository. Do not add repository selection fields to the verify request. Read-only inputs run in captured copies at their declared versions without modifying the dependency checkout. Assess each returned receipt afterwards.

When backend source is unavailable, declare `dependency_checks` in the verification command. After observing the real dependency, that approved command emits the stdout evidence line below. Replace example values with actual observations; never echo expected values as evidence. Service freshness is 1–604800 seconds; artifacts may use `null`. Missing, mismatched, malformed or expired evidence cannot support a complete pass. HTTP success proves neither a version nor backend source coverage.

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
