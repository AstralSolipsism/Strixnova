# Replanning and integration submissions

Read only the section matching `CurrentAction.input_kind`.

## Repeated failure after a correction

When the same material failure returns after a targeted correction, stop that
retry sequence before adding another exception or workaround. Read the controlling
rule, the current execution material and the original observed result. Distinguish
a product defect, a wrong plan, an acceptance-driver defect, an Agent output error,
and an environment block; keep the cause unknown when evidence does not settle it.
For each proposed step, state what observable behavior it will prove or change.
Remove redundant copying or checking of program-owned facts instead of adding
formatting exceptions to make a semantic review pass.

A repair already inside the confirmed operations and meaning can continue in the
current slice without another product decision. If new facts invalidate planned
operations, dependencies, verification or scope, use the existing replan route.
Do not weaken the source rule or ask the owner to choose whether it should still
be followed. Only a real change to an upstream decision goes to that decision's
owner. A `review_subject_changed` error requires affected-content re-evaluation,
not merely a replacement identity on the same old conclusion.

Use the already stated investigation/validation budget. If it is exhausted, retain
the original failure, attempted correction, remaining cause and next responsible
actor; stop the blocked scenario and continue unaffected authorized work. Do not
rebuild unrelated fixtures, expand the acceptance scope, add more reviewers, or
repeat successful tests merely to obtain a green total. Recheck corrected findings
against current content; keep unresolved findings visible through existing review,
plan and result records, without a new ledger or confirmation point.

## Replan

When new facts invalidate the confirmed plan, submit:

```json
{"schema_version":"strixnova.replan-request.v1","reasons":["specific changed fact"]}
```

If only engineering facts changed, keep `assessment_id`, increase
`assessment_revision`, and retain the current `direction_ref`. If goal, scope,
tradeoffs, acceptance, or WorkItem relations changed, first submit the complete
revised direction and obtain direction confirmation, then bind that new version
in the revised assessment.

When `CurrentAction.action_type=revise_direction`, the program has already
proved that the stored product-context binding is stale by version, reference,
or coverage. Read the listed old direction and current product context, revise
only the affected decisions, and submit the normal complete direction payload.
Do not ask the user to repeat decisions whose evidence and meaning remain
valid; the revised complete card still uses the existing direction confirmation
point.

修改任何内容前，先判断究竟是哪一层事实失效：

- 产品目的、范围或成功含义变化，退回方向或产品定义；
- 术语、决定权、规则、不变量或场景含义变化，退回领域模型；
- 目标责任、依赖方向或领域事实承载变化，退回目标架构；
- 上游含义仍正确，只是操作、实施切片、风险或验证不完整，只形成新的
  EngineeringAssessment（工程评估）修订；
- 当前实现问题可在已确认操作和含义内修复时，在当前 ImplementationSlice（实施切片）内修复并复验；
  新事实使方案失效时，停止该切片，完成重新规划后才允许执行依赖它的后续切片。

已经采用的上游权威变化时，重做 `authority_change_set`（权威变更集）、下游处置、
`semantic_review`（语义复核）、受影响的 `implementation_slices`（实施切片）和
`owner_view`（负责人视图）。依据和含义仍然有效的决定继续复用，不要重新开始形式化追问。

## Target advance

Inspect the native Git diff between the investigation commit and target commit.
Submit only the semantic judgment:

```json
{
  "schema_version": "strixnova.target-advance-assessment.v1",
  "semantic_impact": "affected|unaffected",
  "reason": "..."
}
```

## Git conflict

After resolving native Git content conflicts, state what must be retested:

```json
{
  "user_visible_result_changed": false,
  "confirmed_direction_or_plan_changed": false,
  "reason": "...",
  "retest_command_ids": ["VC-001"]
}
```

`retest_command_ids` lists only plan commands actually affected by the conflict
resolution. It may be empty even when the plan has commands if none of them is
applicable to this conflict. Explain that judgment in `reason`; Strixnova still
binds the resolution to the exact user-accepted file snapshot and does not infer
semantic command relevance itself.

Do not use an unrelated command, failed result, or `not_run` to unlock merge.


## Resume a recorded effect

For `input_kind=resume_external_effect`, read `pending_effect` and use its
original repository, execution location and CurrentAction `intent`:

| Intent | Continuation |
|---|---|
| `verify` | Use the original `command_id` and `mode=run` through [verification.md](verification.md) to recover the existing receipt; do not rerun it in a separate shell. |
| `delivery` | Follow the current input contract and [delivery.md](delivery.md) for the recorded Git or file effect. |
| `cancel` | Follow the recorded cancellation decision and [confirmation-and-cancel.md](confirmation-and-cancel.md); do not infer a new discard decision. |

Settle running or unknown effects before cancellation. If execution is unclosed,
use [history-and-upgrade.md](history-and-upgrade.md#resolve-an-unclosed-execution)
to establish the actual stop state first. Partial cancellation preserves
already-integrated content and undelivered work; it does not undo an integration.
A changed overall result follows the existing re-presentation and acceptance route.


## Replan after partial integration

Before completion, a new overall plan may require another change in an
already-integrated repository. Preserve its earlier contribution and prepare a
new work area under the new plan, with a new result acceptance. A retained native
merge conflict keeps its target checkout as the execution location: read
`repository_deliveries[].git.conflict_resolution` and use that entry's `repository`
for replanned implementation. Other repositories retain their own work areas.
