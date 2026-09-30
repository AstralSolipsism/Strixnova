---
name: strixnova
description: >-
  引导具有命令执行能力的 Coding Agent（智能编码代理）使用 Strixnova完成本地单项目软件工程治理，包括项目状态、长期权威、建设事项、验证、本地交付和外部活动。仅当用户明确要求使用 Strixnova、启动 Strixnova管理的 WorkItem（建设事项）或继续已有本地 WorkItem（建设事项）时使用；不要因为已经安装就介入普通编码。
---

# Strixnova

Strixnova records engineering decisions and checks their bindings, state, Git
facts and execution evidence. The Agent investigates, forms project-specific
meaning, implements the authorized work and explains results; the owner makes
product and acceptance decisions. This bundled Skill guides that work without
granting authority or managing the Agent's host, identity or session.

## Operating rules

- For generating, reviewing, or correcting a reading document, read its specific
  guide before writing or judging it: [prd-authoring.md](references/prd-authoring.md),
  [spec-authoring.md](references/spec-authoring.md), or
  [domain-documentation.md](references/domain-documentation.md), together with
  [artifact-documentation.md](references/artifact-documentation.md). This applies
  to existing documents too; their headings and source catalogs cannot replace
  reading the underlying content.
- Before a code review, read [code-review.md](references/code-review.md); before
  judging cross-unit architecture or draft consistency, read
  [cross-artifact-review.md](references/cross-artifact-review.md); before reviewing
  interface, permission, uniqueness or retry rules, read
  [behavior-contracts.md](references/behavior-contracts.md). This includes informal
  read-only questions without a WorkItem. Read only the applicable method; it does
  not require creating an item, a formal review record or a new confirmation.
- Investigate and choose tools autonomously. Ordinary search, scratch work and
  subagents remain Agent internals; they do not need a WorkItem or Strixnova log.
- Use the current public input contract for commands and payloads. Copy returned
  identities and references exactly. Do not inspect installed package internals
  or tests to guess a field, or substitute code and examples for project decisions.
- Keep one direction, engineering plan and actual-result acceptance per WorkItem,
  including a result spanning several repositories. Subsequent repository delivery
  reuses the unchanged overall acceptance; changed results use the existing
  revision and acceptance route.
- Follow the confirmed plan, current slice and CurrentAction. Accept the actual
  result before local Git commits; Strixnova does not push, create remote resources
  or manage CI. Do not use Strixnova to manage itself unless explicitly requested.
- A0–A4 describe assurance depth within this lifecycle. Project methods come from
  the engineering policy; names of files, documents or activities do not adopt a
  method, choose assurance or authorize more work.

## Keep the owner oriented

Use Chinese and the project's vocabulary. Explain an unfamiliar term when it
helps the decision; preserve exact command and field names in technical detail.

- Lead with the answer, recommendation or observed result, then the supporting
  facts. Keep the depth requested for an explanation, alternatives or inventory.
- In progress updates and after an interruption, use current facts to explain
  what changed, what remains and who acts next. Reuse valid decisions and continue
  authorized Agent work. Ask at real user gates, not before every routine step.
- Rank and group long explanations. About five visible items per group is a
  reading aid, not a limit on analysis, complete candidates, independent decisions
  or material risks. Number steps when the owner actually needs to perform them.
- Answer mid-work questions and continue the original objective unless the owner
  changes it. Carry real limitations and follow-up commitments through their
  existing records; do not add unrelated improvements or invent a next task.
- Separate observed failures, established causes, unknowns and the next diagnostic
  action. Revisit assumptions after repeated failure. Give time ranges only with
  an evidential basis and stated assumptions; otherwise name the next checkpoint.

Before presenting a material conclusion, check its source, object, conditions,
and exact supported scope. Separate what the material establishes from an
inference whose premises still need checking. Missing measurements do not support
promises about speed, capacity, cost or negligible impact; a scoped measurement
can support a scoped conclusion. Do not turn drafts into adopted commitments,
missing information into a proven violation, or a proposed stronger rule into
an existing requirement. Investigate available facts first. If they cannot be
obtained, identify the specific unknown and its effect on the conclusion; do not
fill it with a plausible story. When evidence does establish a defect, state it
clearly instead of adding unsupported uncertainty. These are reasoning checks,
not a mandatory owner-facing template or a new confirmation gate.

Check a proposed definite conclusion with a counterexample: could a different
outcome still satisfy every supplied fact? If yes, the stronger conclusion is
not established; state the missing premise without inventing it as true. If the
facts rule out that alternative, state the supported conclusion clearly. Apply
the same boundary to headings, comparison tables, recommendations and the final
summary: a later caveat does not repair an earlier categorical assertion.
For option comparisons, names such as filtered/full do not establish speed,
manageable volume, visible-row scope, trusted permissions or consistency. Mark
those dimensions unknown unless sources establish them; adding "usually" is
not project evidence. Recommendations may state conditional tradeoffs, with the
conditions visible, while preserving the actual requested scope.
Explain the functional distinction the user asked about even when measurements
are unavailable. Unknown implementation properties do not erase that distinction
or authorize narrowing the request; separate conceptual options from unverified
claims about this project's implementation.

For example, when supported by the receipts: “校验修改已完成，回归中仍有一项
失败，原因尚未确认。我会先检查该失败；当前无需你操作。”
Stop when the requested work is complete. Follow host communication requirements
and explicit user preferences without repeating the same update.
When the owner explicitly ends an analysis without requesting further work,
the whole reply is one short acknowledgement, for example “好的，本次分析结束。”
Do not add a summary, future invitation, availability offer or next task. If the
owner also asks to continue implementation, follow that request instead of treating
the end of discussion as cancellation of the authorized work.

## Choose the public route

For a request to start or manage identifiable work, run `strixnova intake`
from the user's original request before asking the owner to resolve its
business meaning. Unknown terms, permissions, product boundaries, or an
`unadopted_project` status do not postpone intake. Intake records the request;
it does not accept a direction, adopt authority, or authorize implementation.
Resolve those gaps in the returned direction action. This priority also applies
when the discovery or artifact-formation references are needed.

Pre-intake discovery is for a wish with no identifiable concrete matter, or an
explicit request only to explore or discuss without starting managed work.

| Current request | Route and relevant guidance |
|---|---|
| Inspect project status or distinguish first adoption from an adopted project | `strixnova status` reads the immutable integrated version. Use `--working-tree` only for the independently accepted, uncommitted authority candidate before coding. It does not adopt that candidate. |
| Inspect declared repository bindings or repository-qualified content | `strixnova context`; this initializes no WorkItem and adopts no declaration. |
| Prepare review inputs for changes or named modules | `strixnova context contract review`, then `strixnova context review`; read [code-review.md](references/code-review.md). This supplies versioned facts and gaps, without running a reviewer or creating a WorkItem. |
| Read past work, including completed or cancelled items | `strixnova history` and the recorded-work section of [history-and-upgrade.md](references/history-and-upgrade.md). No CurrentAction is needed. |
| Inspect or carry an explicit deferred promise | `strixnova status --follow-ups` or `project.follow_ups`; read [follow-ups.md](references/follow-ups.md). |
| First installation or explicitly requested Strixnova maintenance | Follow the offline bundle for installation or `strixnova upgrade` for maintenance; read the matching section of [history-and-upgrade.md](references/history-and-upgrade.md). Use the exact runtime entry; copied Skill files do not prove host loading. |
| Start a concrete, user-requested managed matter | `strixnova intake`, then the returned next action. |
| Find an active item after reconnecting, or read its current action and records | `strixnova next`. |
| Submit work, confirm, deliver, verify or cancel | `strixnova submit`, `strixnova confirm`, `strixnova delivery`, `strixnova verify` or `strixnova cancel`, as selected by CurrentAction and its input contract. |
| Author, review or confirm planned long-term authority candidates | `strixnova authority`; follow the input-kind routes below. The program writes confirmation metadata. |
| Observe and update implementation alignment | `strixnova alignment` and [implementation-alignment-workflow.md](references/implementation-alignment-workflow.md), only when the confirmed slice owns or continues the operation. |
| Record external delivery, release, deployment, rollback or operations work | `strixnova activity` and the external-activity section of [delivery.md](references/delivery.md). External tools perform the activity; this is not a CurrentAction input. |

Do not run project status before every WorkItem action. Alignment cache collection
is separate maintenance: `strixnova alignment gc` requires an explicit owner
request and acceptance of the exact dry-run fingerprint.

## Keep context small

1. After reconnecting, use `strixnova next` to find the active item; focus it with
   `--work-item-id` to read CurrentAction.
2. Inspect `input_kind`, `intent`, `input_contract_ref`, `work_item_version` and
   available `record_refs`. Before a write, read its exact input contract.
3. Request only records needed for the current decision. Batch known independent
   records with repeated `--record`; wait for a routing response before selecting
   records that depend on it.
4. After a write, use the returned `next` object. Re-read when facts changed or a
   typed conflict requires reconciliation, not merely to obtain the same state.
5. Follow [engineering-assessment.md](references/engineering-assessment.md) for
   conditional governance, domain and architecture reads. Once the required
   impacts, operations, verification choices and material unknowns can be stated,
   submit; record remaining uncertainty rather than exploring the whole project.

If a material failure repeats after a targeted correction, read the repeated-failure
section of [replanning.md](references/replanning.md) before another attempt. Recheck
the plan assumption and proof boundary, then continue only the supported next step.

When CurrentAction lists `engineering.execution_context`, read that record before
starting or resuming implementation, assessing a verification change, or revising
the plan. It joins the original direction, current slice, exact commands,
plan-wide verification targets, bound assessment material, unresolved findings,
and project rules selected through recorded ownership. Slice records expose the
same material in `execution_context`; do not fetch both copies. Use the existing
bounded child reads to obtain the applicable bodies. Read `gaps` and
`project_rules.gaps` as well: unavailable or unbound material is an investigation
gap, not permission to ignore a constraint. The program preserves original text
and source versions; do not retype it as evidence. Determine semantic relevance
and inspect the actual implementation yourself. Reading this material does not
constitute a review or authorize a write.
`project_rules.basis_kind` distinguishes integrated rules from
`confirmed_execution_candidate`. The latter is available only after all planned
upstream decisions are recorded for this plan and their current file bytes still
match the confirmed content. A changed confirmed candidate is rejected; an
unconfirmed working-tree file cannot replace the integrated rules. Open findings
include the final authority review bound to the same plan, not just its earlier
planning review.

Focused `next` reads default to a complete 4096-byte JSON envelope. Small values
are in `records`; large values are in `record_pages`, with `entries` containing
exact child `ref` values and small inline `value` fields. An omitted value is not
an absent requirement. Read needed children through the same `--record` option;
copy references rather than guessing names. This also applies to input contracts
and their schema children. Use single quotes around refs containing `#` or `$`.
For example, read `--record 'engineering.plan#/actual_result_requirements'`
when its parent is available. Follow `next_cursor` with `--cursor` and one
unchanged `--record`; `unexpanded_refs` identify children whose bodies are not
included, and `reading.unread_refs` identify batch records still to request.
Bind later child reads using `--expected-version` and `--expected-sha256` from
`record_sources[ref].source_sha256`; a changed source requires a fresh read.
String pages contain `text` in Unicode code-point order; concatenate them only
along the returned cursor chain. `reading.complete=false` is not evidence that
all required material was read. Obtain every applicable rule, required field and
constraint before forming a write. `--max-output-bytes` changes the whole-envelope
budget (512–1048576), not the number of business records. Do not increase it past
the host's capacity or use shell filtering to reconstruct truncated JSON. If a
write response is truncated, re-read `next` and its exact records (or `history`
for earlier receipts); never repeat the write just to recover its output.

A focused item includes its declared and incoming relations. Declare a relation
only when the user or known project facts identify a real target; do not search
all history to invent one. When trace evidence is needed, `engineering.trace.current`
contains adopted relations and `engineering.trace.audit` also retains historical
dispositions. Both remain readable with `strixnova next --record` after the
item no longer has a current action.

The normal WorkItem write shape is:

```text
strixnova <submit|confirm|delivery|verify|cancel> --work-item-id <ID> --version <work_item_version> --input @payload.json
```

Omit `--project-dir` in the project root; supply it when operating elsewhere.
On Windows PowerShell, use a system-temporary UTF-8 file for non-ASCII JSON and
remove it after the call:

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

Use `@-` only when the caller writes raw UTF-8 bytes; `$OutputEncoding` alone
does not guarantee that on Windows PowerShell. ASCII JSON with `\uXXXX` escapes
is also safe. Parse structured CLI output as JSON.

## Follow the public input contract

Before `intake` there is no CurrentAction; use the request and the formation
routes below. After intake, the returned input contract determines payload
fields and state transitions. References supply the reasoning and procedures.
Read the matching section, reusing already-read guidance while it remains current.

| `input_kind` or operation | Read |
|---|---|
| `direction` | [direction.md](references/direction.md) |
| `engineering_assessment` | [engineering-assessment.md](references/engineering-assessment.md); [engineering-methods.md](references/engineering-methods.md) only for its actual method/impact intersection |
| `project_authority_candidate` | The applicable authority section and preparation procedure in [authority-authoring.md](references/authority-authoring.md) |
| `project_authority_review_submission` | The final-candidate review procedure in [cross-artifact-review.md](references/cross-artifact-review.md); submit through `strixnova authority` |
| `project_authority_confirmation_bundle` | Long-term authority confirmation in [confirmation-and-cancel.md](references/confirmation-and-cancel.md); submit through `strixnova authority` |
| `replan`, `target_advance_assessment`, `conflict_resolution` | Matching section of [replanning.md](references/replanning.md) |
| `resume_external_effect` | [Resume a recorded effect](references/replanning.md#resume-a-recorded-effect), which routes `verify`, `delivery` and `cancel` separately |
| `verification`, `verification_assessment`, `conflict_retest`, `implementation_slice_completion` | [verification.md](references/verification.md) |
| `begin_implementation`, `actual_result`, `commit_and_integrate`, `integrate`, `complete_merge`, `cleanup` | Matching section of [delivery.md](references/delivery.md) |
| `direction_confirmation`, `engineering_plan_confirmation`, `actual_result_confirmation`, `cancellation_decision` | Matching section of [confirmation-and-cancel.md](references/confirmation-and-cancel.md) |

Select additional methods by the actual work:

- Read [product-discovery.md](references/product-discovery.md) for an unclear
  product premise, requested brainstorming or challenge, or external evidence
  that could change the product decision. Skip it for a clear bounded request
  or a purely technical question. Only pre-intake discovery may end without a
  WorkItem; discovery for an identifiable managed request happens after intake.
- Read [artifact-formation.md](references/artifact-formation.md) when delivery
  span is unclear, a PRD/SPEC or similar artifact is requested, a durable
  cross-unit choice is emerging, or an upstream correction affects downstream
  work. Use discovery before intake only when no concrete managed matter can
  yet be identified; unresolved business details belong to direction formation.
- Read [behavior-examples.md](references/behavior-examples.md) for an observable
  behavior change or a plan containing examples.
- Read [code-review.md](references/code-review.md) for requested or plan-required
  code review. Writing alone does not require code review or test guidance.
- Read [ux-design.md](references/ux-design.md) for requested interaction work or an
  unresolved interaction that changes the direction or plan.
- Read [behavior-contracts.md](references/behavior-contracts.md) for a material
  interface, permission, concurrency, compatibility or recovery decision.
- Read [implementation-practices.md](references/implementation-practices.md) when
  choosing an implementation/test boundary or doing requested test-first work.

## Use the bundled long-term authority methods

For requested authority work, first identify create, update or review in
[authority-authoring.md](references/authority-authoring.md), then read only the
sections for the actual authority and phase. Use
[domain-modeling-and-alignment.md](references/domain-modeling-and-alignment.md)
when forming or checking product/domain meaning, responsibility or alignment.
These are parts of the same Skill, not separately installed tools.

| Current writing or review need | Additional reference |
|---|---|
| Typed domain facts | [domain-fact-contracts.md](references/domain-fact-contracts.md) |
| Architecture modules, relations, constraints, fact dispositions or stages | [architecture-artifact-contracts.md](references/architecture-artifact-contracts.md) |
| Alignment source ownership, dependencies, responsibilities or deviations | [implementation-alignment-artifact-contracts.md](references/implementation-alignment-artifact-contracts.md) |
| Policy method adoption, sources, rule tailoring or verification policy | [engineering-policy-contracts.md](references/engineering-policy-contracts.md) |
| Cross-artifact consistency, slice readiness or owner presentation | [cross-artifact-review.md](references/cross-artifact-review.md) |
| A readable document from an exact domain model | [domain-documentation.md](references/domain-documentation.md) |

Use each artifact's public version, fields and identities. Current source,
execution evidence and method-adoption sources have distinct owners; preserve
those boundaries when forming the content.

## Start a WorkItem

After the user asks Strixnova to manage a concrete matter, create it from the
request without a shadow interview:

```json
{"title":"short title","request":"the user's request without invented scope"}
```

Submit with `strixnova intake --input @payload.json`, then follow `next`.
Direction formation investigates facts and resolves material choices after
intake. A vague wish that cannot identify a concrete matter can remain in
product discovery, including a decision to park or reject it.

When `project.direction_context` is listed, read its complete compact catalog,
select relevant capabilities and disposition every guardrail. Explain their
meaning in plain language; the Agent carries internal references.

## User confirmations

An ordinary WorkItem has three gates: direction, engineering plan and actual
result. A first adoption or material revision of product, domain, architecture
or engineering policy has its separate authority decision.

Use [confirmation-and-cancel.md](references/confirmation-and-cancel.md) for the
complete presentation, later user reply, interpretation and command binding.
The Agent preserves the full reply and submits it through the public command;
the program writes confirmation metadata. Questions and explanations do not
accept a candidate. Follow the current authority review and confirmation steps
before implementation; an alignment draft is adopted only after actual-result
acceptance.

On `authority_conflict`, reconcile the latest CurrentAction and facts. For other
typed errors, correct the stated input or project condition within the authorized
scope. Preserve evidence and report unresolved ambiguity instead of bypassing a guard.
