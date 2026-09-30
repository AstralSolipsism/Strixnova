# Engineering assessment submission

Read this file only for `CurrentAction.input_kind=engineering_assessment`.
The `strixnova submit --input` payload is the assessment object shown below
itself; do not wrap it in an outer `assessment` property.
Investigate with appropriate tools and stop once actual impacts, planned
operations, verification choices, and material unknowns can be stated. Put
remaining uncertainty in `unknowns_and_limitations`; do not read the whole
repository merely to feel complete. Use the semantic-review section below when
the actual impact requires cross-artifact review.

## Contents

- [Read project facts without loading the whole domain model](#read-project-facts-without-loading-the-whole-domain-model)
- [Required core](#required-core)
- [Add only real optional facts](#add-only-real-optional-facts)
- [Authority changes, review and slices](#规划权威变化语义复核和实施切片)
- [Select a minimal verification set](#select-a-minimal-verification-set)

Read the core for every assessment; use optional sections only when their
stated impact applies. The examples show payload structure, not project defaults.

The examples below explain the intended meaning of common fields. The exact
public structural authority is always the `input_contract_ref` returned by
CurrentAction; if an example and that contract ever differ, follow the
contract and report the packaged guidance as stale.

The confirmed DirectionDecision is the only source for goal, scope, non-goals,
constraints, tradeoffs, and acceptance. Do not restate them. Request the
records listed by CurrentAction and take `direction_version` from the accepted
`direction_confirmation`, not the later WorkItem version.

Before the first submission, check these five boundaries explicitly:

1. Set `change_context.formal_implementation=true` whenever any repository
   file will be changed or delivered. False is only for a deliberately managed
   result with no repository delivery; it is not a mode for ordinary Agent
   investigation.
2. Run `strixnova status` before choosing the change kind. If the investigation
   commit has no adopted project configuration or engineering baseline and the
   WorkItem will change or deliver any repository file, use
   `change_context.change_kind=create_project`. Declare all six authority paths
   and plan the project configuration, engineering baseline, and five long-lived
   authorities together. This is required for a new project's first formal
   repository delivery, not an optional adoption step. Only a genuine A0 result
   with no repository delivery may remain unadopted.
   Investigate and reuse existing project material; the owner decides meaning
   and material tradeoffs rather than filling in templates. Keep the content
   complete and proportional to the project. Later changes reuse valid
   authorities and update only affected content; PRD and SPEC are optional
   reading artifacts, not a recurring adoption requirement.
3. For formal implementation, use a real immutable commit from the configuration
   repository as `investigation_ref`, and bind each selected repository's own
   investigation commit in `repository_scope`. Never invent an investigation label.
4. For ordinary project evidence, use only `direction` or a `reference_id`
   declared in `source_references`. An adopted project may additionally use
   exact `baseline_refs` returned by `project.engineering`. Never use
   `direction_confirmation`, a file path, or a temporary description as an
   evidence ref.
5. If `architecture`, `interface`, or `data` is affected or unknown, include a
   real alternative/tradeoff, design decision, and ADR candidate decision.

## Read project facts without loading the whole domain model

Choose the immutable Git investigation commit first. Use only records listed by
CurrentAction. For an existing formal project, read `project.engineering`
before any domain record to establish each method's adopted or conditional
status and its adopted technique IDs. A true new project has no adopted
ProjectEngineeringBaseline yet and does not invent one for this step. Only when
an already-recorded project-wide governance gap or standards boundary is
material to the current assessment, read the optional
`project.engineering.assurance` matrix; it is downstream evidence, not a sixth
authority or a substitute for direct investigation. Only when
method adoption and the current impact make domain evidence necessary, request
`project.domain.catalog` and continue in this order:

1. `project.domain.catalog` for model and root-Collection routing metadata;
2. the selected Collection's exact returned `record_ref` for its immediate
   children and Source choices, repeating only along that branch;
3. the selected Source's exact returned `record_ref` for its Fact routing
   metadata;
4. `project.domain.closure:<FACT-ID,...>` for explicit dependencies, context
   endpoints, scoped invariants and global facts;
5. the exact Fact `record_ref` returned by the selected Source for each
   canonical body actually needed (do not shorten it to a bare Fact ID);
6. `project.architecture` and `project.domain.alignment` only when the affected
   boundary or implementation claim requires them.

Repeat `--record` within one `strixnova next` invocation for every required
reference already known at that moment. In particular, static CurrentAction
records and multiple selected Fact bodies should be read as one batch. Keep
sequential calls only where the current routing result is needed to choose the
next Collection, Source, or Fact; do not speculate or preload unrelated records.

Collection titles and nesting are project-owned document organization; never
turn them into subdomains or bounded contexts by name. The catalog intentionally
contains no Fact bodies. Do not load unrelated Sources, artifacts, ADR bodies,
or every historical WorkItem. Direct source evidence remains finite evidence,
not a log of every file read.

## Required core

For a configured project with several members, declare `repository_scope` with
the current `project_id` and a `repositories` array. Each entry has
`repository_id`, `role` (`modify` or `read`), `investigation_ref`, and `target_ref`
(a local target branch for modification, null for a read dependency). Include
only repositories needed by this plan. Required repositories must be bound and
their refs resolvable before the plan can be confirmed; unrelated members may
remain unbound. An external dependency can only be read.

Qualify operations, source references, verification commands, located ADR and
domain-fact changes, and external-observer plans with `repository_id`. Internal
paths stay relative to that repository; a move stays within it. A single eligible
repository may be inferred from an omitted field in the same current contract.
A project with no declaration keeps an unbound identity while following the
existing first-project formation flow; do not invent historical ownership.

For several modification repositories, `delivery_plan.repository_order` lists
each one exactly once. Slice IDs and operation references remain unique within
the WorkItem; compiled slices report their repository IDs. Explain one complete
plan and request one overall plan decision. Independent early delivery requires
a separate independently acceptable WorkItem.

Prepare each planned repository work area and its declared verification inputs
before presenting the combined result. Local delivery then follows the confirmed
repository order and CurrentAction; the main Skill defines overall acceptance.

```json
{
  "schema_version": "strixnova.engineering-assessment.v1",
  "assessment_id": "EA-...",
  "assessment_revision": 1,
  "direction_ref": {
    "work_item_id": "WI-...",
    "direction_version": 3
  },
  "investigation_ref": "<immutable Git commit; working_tree only for non-delivery>",
  "change_context": {
    "change_kind": "modify_existing|add_capability|create_project|exploration",
    "formal_implementation": true
  },
  "impact_scope": {
    "affected": [
      {
        "dimension": "testing",
        "reason": "...",
        "evidence_refs": ["SRC-001"]
      }
    ],
    "unknown": [],
    "unaffected": ["user_behavior", "product_scope"]
  },
  "requested_assurance": {"band": "A0|A1|A2|A3|A4", "reason": "..."},
  "owner_view": {
    "schema_version": "strixnova.owner-view.v1",
    "decision_support": {
      "current_problem": "...",
      "why_it_matters": "...",
      "impact": "...",
      "recommendation": "...",
      "alternatives": ["..."],
      "no_action_consequence": "...",
      "next_step": "...",
      "necessary_questions": []
    },
    "engineering_context": {
      "product_and_domain_change": "...",
      "architecture_responsibilities": "...",
      "implementation_order": "...",
      "highest_impact_risks": "...",
      "verification_and_observation": "...",
      "uncertainties": "..."
    },
    "current_decision": "...",
    "semantic_content_machine_proven": false
  }
}
```

For a new project's first formal repository delivery, `create_project` is
required. Add all six required paths to `change_context`:
`project_engineering_baseline_path`, `project_product_definition_path`,
`project_domain_model_path`, `project_architecture_description_path`,
`project_engineering_policy_path`, and
`project_implementation_alignment_path`. Every formal project establishes all
five independent authorities; DDD adoption remains a separate engineering
policy decision and does not control whether the domain or alignment authority
exists.
For an existing formal project, the immutable
`investigation_ref` is sufficient for Strixnova to locate and validate the
project config and engineering baseline at that commit. Do not duplicate those
deterministic bindings as SourceReferences unless a specific semantic claim
actually cites their text. Add cited evidence under the exact outer field
`source_references`; each item has this shape, and line bounds are optional but
must appear together:

```json
{
  "source_references": [{
    "reference_id": "SRC-001",
    "path": "relative/path.py",
    "observed_ref": "<investigation commit>",
    "epistemic_status": "observed|inferred|unknown",
    "line_start": 1,
    "line_end": 10
  }]
}
```

Classify all twelve dimensions exactly once across `affected`, `unknown`, and
`unaffected`:

```text
user_behavior product_scope domain architecture interface data
security_privacy quality_performance operations_deployment
compatibility_migration testing documentation_support
```

`affected` and `unknown` items need a concrete reason and non-empty evidence
refs. `unaffected` contains only names. Every unknown dimension also needs an
`unknowns_and_limitations` item with `statement`, `impact`, `handling`, and
`evidence_refs`.

```json
{
  "unknowns_and_limitations": [{
    "statement": "...", "impact": "...", "handling": "...",
    "evidence_refs": ["SRC-001"]
  }]
}
```

## Add only real optional facts

Omitted list sections normalize to empty; omitted `delivery_plan` normalizes to
null. Never add placeholders. The exact optional item shapes most often needed
are:

```json
{
  "risk_assessments": [{
    "statement": "...", "likelihood": "low|medium|high",
    "consequence": "low|medium|high|critical",
    "reversibility": "easy|moderate|difficult|irreversible",
    "uncertainty": "low|medium|high",
    "external_assurance_required": false,
    "mitigation": "...", "evidence_refs": ["SRC-001"]
  }],
  "alternatives_and_tradeoffs": [{
    "option": "...", "disposition": "selected|rejected|deferred",
    "reason": "...", "tradeoffs": "...", "evidence_refs": ["SRC-001"]
  }],
  "design_decisions": [{
    "statement": "...", "rationale": "...", "evidence_refs": ["SRC-001"]
  }]
}
```

Only when an adopted/conditional project method intersects an affected or
unknown impact, or when creating a project, read
[engineering-methods.md](engineering-methods.md). Otherwise omit
`method_applications`. The shipped DDD rule intersects exactly `domain`,
`architecture`, `interface`, and `data`; request keywords do not activate it.

The shipped base governance profile also requires concrete engineering facts,
not placeholders. A formal change needs requirement, acceptance, constraint,
operation, and delivery facts. A `quality_performance` impact needs impact,
risk, and verification facts; `testing` needs verification facts;
`architecture`, `interface`, or `data` needs a real selected/rejected/deferred
option, a design decision, and an ADR candidate decision; `security_privacy`
needs risk, design, verification, and delivery facts; `operations_deployment`
or `compatibility_migration` needs delivery, risk, and verification facts.
Only add facts that the project evidence actually supports.

Submit file operations under the exact outer field `operations`:

```json
{
  "operations": [{
    "action": "create|modify|delete|move",
    "path": "relative/path.py",
    "reason": "...",
    "evidence_refs": ["SRC-001"],
    "implements": ["direction.requirement:DIRREQ-0123456789ABCDEF"]
  }]
}
```

`implements` is a non-empty array whose entries point to a current
`direction.requirement:DIRREQ-*` or `design_decisions[n]`; move also has
`to_path`. Never translate an old array position into a stable reference in
the daily workflow. Match the action to
`investigation_ref`: create starts absent, modify/delete/move start present,
and a move target starts absent. Add `long_lived_artifact` only for an actual
long-lived engineering file. Core authority identities use the same
stable-random format as their candidate readers: `PRODUCT-`, `MODEL-`, `ARCH-`,
`POLICY-`, or `ALIGNMODEL-`, followed by 16 uppercase hexadecimal characters.
For example, use
`{"artifact_id":"ARCH-1111111111111111","artifact_type":"architecture"}`. The operation
`path` remains the artifact's file path; do not replace the object with a
string or invent a long-lived identity for ordinary source files. For an
existing project, the identity, type, and path must match an artifact already
indexed by ProjectEngineeringBaseline. Modifying, moving, or deleting an
indexed long-lived artifact also requires a planned ProjectEngineeringBaseline
operation so its WorkItem relation, path, or removal can be recorded. A newly
created long-lived artifact is allowed only when the same assessment also
plans the baseline index update.
ProjectDomainModel Collection and Source files are not separate baseline
artifacts: track their canonical Fact changes with `domain_fact_changes` and
omit `long_lived_artifact` from those file operations.

When a planned ImplementationAlignment observation needs a language- or
toolchain-specific analyzer that Strixnova does not provide completely, add one
top-level `external_observation_provider_plans` entry for each exact
observation scope and language. Omit the field's entries when built-in static
observation is sufficient; never add a provider merely from a filename or
language label. The plan is execution authority, so bind the argv and the
SHA-256 identity of every executable, entry script, provider configuration,
and supporting file, plus tracked-source globs, explicit process policy, and
finite limits during engineering-plan confirmation—not later at the CLI:

```json
{
  "external_observation_provider_plans": [{
    "provider_plan_id": "OBSPROVPLAN-1111111111111111",
    "scope_id": "OBSCOPE-1111111111111111",
    "language_id": "cpp",
    "provider_id": "project.clang-observer.v1",
    "provider_version": "1.0.0",
    "command": ["tools/observe-cpp.exe", "--format", "strixnova-v1"],
    "materials": [{
      "role": "executable",
      "path": "tools/observe-cpp.exe",
      "sha256": "<64 lowercase hex from the confirmed file bytes>",
      "command_argument_index": 0
    }],
    "source_globs": ["*.c", "*.cpp", "*.h", "*.hpp", "**/*.cpp"],
    "process_policy": {
      "policy_id": "PROCESSPOLICY-1111111111111111",
      "purpose": "Observe configured C++ implementation relationships.",
      "forbidden_program_names": ["codex", "claude"]
    },
    "limits": {
      "timeout_seconds": 300,
      "cleanup_timeout_seconds": 10,
      "max_input_bytes": 4194304,
      "max_output_bytes": 16777216
    }
  }]
}
```

Use only project-proven argv, paths, and material hashes. Bind an interpreter
and its entry script separately; list a provider-loaded config or supporting
file with `command_argument_index: null`. Strixnova resolves every bound command
argument and re-hashes every material immediately before process start. A
missing, substituted, or changed material becomes a `not_run` failed
observation and is recorded in the receipt. The command must not invoke an Agent,
an opaque shell or command wrapper, or inline runtime code; a language runtime
may execute a fixed provider entrypoint. Globs must stay relative to the
governed scope. `max_input_bytes` cannot exceed 64 MiB and
`max_output_bytes` cannot exceed 256 MiB; choose lower project-specific limits
when possible. Strixnova projects this exact list into
`strixnova.engineering-plan.v1`; the later `strixnova alignment
capture-external` call can authorize it but cannot replace or extend it.

`domain_fact_changes` is a top-level assessment field. It records changes to
the project's formal domain authority independently of `method_applications`.
Do not nest it under DDD or any other engineering method. A project can maintain
its domain model without adopting a named method, while a method application can
read `domain_fact_refs` without changing those Facts.

## 规划权威变化、语义复核和实施切片

建立或修订正式产品、领域、架构、工程政策或实现对齐权威前，先读
[authority-authoring.md](authority-authoring.md)（长期权威起草资料）。修改已经采用的
产品、领域、目标架构或实现对齐时，必须在评估顶层提交 `authority_change_set`
（权威变更集）。它是 WorkItem（建设事项）的候选内容，不是新的长期权威。必须在不可变的
调查提交上绑定四类现行基线，只列出真正变化的候选修订，用新增、修改、退役或更名说明
具体变化，并为每一项必需下游影响给出处置。任何下游处置仍被阻断时，工程方案不能进入
确认。新项目第一次建立完整权威时，不使用这种差异记录绕过完整建模。

每条变化的 `target_ref`（目标引用）写的是该类长期权威内真正被新增、修改、退役或更名的
稳定内容身份，不是候选修订号，也不是随手写的说明文字。修改、退役和更名必须指向调查提交
中已经存在的同类身份；新增必须使用尚不存在但属于该类公开身份空间的新身份；更名的
`replacement_ref`（替换引用）也必须是同类且尚未存在。若程序报告身份种类不匹配或悬空，
应纠正变化对象或重新评估，不得换一个任意字符串绕过。

“下游没有改业务文字”不等于“下游权威不变”。四层核心链使用精确修订绑定：产品变化必须
形成新的领域、架构和实现对齐候选；领域变化必须形成新的架构和实现对齐候选；架构变化必须
形成新的实现对齐候选。只更新上游绑定时，应把它写成真实的绑定变化，不得用 `unchanged`
（不变）继续引用旧修订。编码前的实现对齐候选应如实记录当前缺口并保持草稿，实施后再刷新。

当 `product_scope`（产品范围）、`domain`（领域）或 `architecture`（架构）被列为
`affected`（受影响）或 `unknown`（未知），或者存在权威变更集时，读取
[cross-artifact-review.md](cross-artifact-review.md)（跨产物审查与负责人展示规程），
并在顶层提交一份 `semantic_review`（语义复核）。必须恰好覆盖规程中的八个角度。尚未关闭
的高影响或严重发现、需要负责人决定的发现，以及仍未解决的高影响问题，都会阻止方案确认。
影响程度和文字内容由 Agent（智能编码代理）判断；
`semantic_content_machine_proven`（语义内容由机器证明）必须保持 `false`（否）。

每项正式实施必须包含一个或多个顶层 `implementation_slices`（实施切片）；小改动通常只有
一个。每个切片必须具有稳定的 `SLICE-nnn`（实施切片标识）、可理解目的、上游
`implements`（实现依据）引用、独占的 `operation_refs`（操作引用）、只指向前序切片的
`depends_on`（前置依赖）、双向一致的 `parallel_safe_with`（可安全并行关系）、可观察完成
条件、独占的 `verification_command_refs`（验证命令引用），以及回退或恢复说明。每项操作和
验证命令必须只属于一个切片。单个前置治理切片可以没有验证命令，并靠可观察完成条件与显式
切片完成记录闭合；这不要求、也不允许在仍有其他验证命令的评估中填写顶层无需验证原因。只有
整份评估都没有适用验证命令时，才必须提供具体的
`verification_not_required_reason`（无需验证原因）。

长期权威候选起草、绑定最终正文的八视角复核和负责人确认先于任何切片实施证据。Agent
（智能编码代理）仍可按真实依赖把不同权威操作拆入多个治理切片；为形成一次完整复核和确认包，
这些切片所计划的真实候选治理路径可以先写齐，但这不代表切片已经完成，也不允许普通源码、
测试或其他业务路径提前出现。完整候选包确认后，才按切片依赖、完成记录和验证门推进。

唯一例外是同一 ImplementationAlignment（实现对齐）草稿的“编码前诚实快照、编码后最终刷新”。
若前置切片已经拥有实现对齐根文件及全部支撑文件操作，且后续业务切片必须在真实代码完成后刷新
同一未确认草稿，可在这个唯一最终刷新切片中使用 `continued_operation_refs`（延续操作引用）。
它必须显式包含前置切片的实现对齐根操作，只能再引用同一实现对齐权威的治理路径，只能指向依赖
祖先切片，并且整份方案只能有一个这种刷新切片。普通源码、测试、说明文档、产品、领域、架构、
工程政策或工程基线都不得使用此例外；它们需要独立操作和切片，或者先重新规划。程序会在运行时
再次用完整候选权威路径核验，不能用目录相似或文字说明扩大权限。

在呈现方案前核对实际写入事务：实现对齐的最终刷新会同时写根文件、四份底账和工程基线，
最终刷新切片必须拥有全部六条路径的合法写入安排。基线不能靠延续前置切片操作获得权限。
若切片拆分只为形成前后两个快照、并无独立工程价值，优先让同一实施切片完成这些写入，
避免到最终刷新时再发现范围冲突。计划中还应先完成对齐及文档写入，再运行该切片的最后
正式验证及后置判断；最后回执的后置判断可能结束切片，不能把剩余写入留在它之后。

```json
{
  "implementation_slices": [{
    "schema_version": "strixnova.implementation-slice.v1",
    "slice_id": "SLICE-001",
    "purpose": "完成一个可独立观察的建设增量。",
    "implements": ["direction.acceptance:DIRACC-0123456789ABCDEF"],
    "operation_refs": ["operations[0]"],
    "depends_on": [],
    "parallel_safe_with": [],
    "completion_criteria": ["公开行为达到已确认验收要求。"],
    "verification_command_refs": ["verification_commands[0]"],
    "rollback_or_recovery": "失败时保留未提交改动并修正当前切片。"
  }]
}
```

`owner_view.decision_support`（负责人决策支持）始终先用普通语言说明当前问题、为什么重要、
影响、推荐、替代选择、不处理后果、下一步和最多五个必要问题；`engineering_context` 再保留
产品与领域变化、架构责任、实施顺序、最高影响风险、验证与可观察效果和未知。
这些内容由 Agent（智能编码代理）起草，不是机器计算的语义分数；程序只检查结构、非空和问题数量。

Use `adr_plans=create|update` only for a durable decision. When architecture,
interface, or data is affected/unknown but no ADR is warranted, submit:

```json
{"adr_plans":[{"disposition":"not_required","reason":"project-specific reason","evidence_refs":["SRC-001"]}]}
```

## Select a minimal verification set

Account for every acceptance item and constraint in the current direction, and
every risk in this assessment. When an acceptance has behavior examples, arrange
each `direction.example:DIREX-*` instead of directly arranging its parent;
read [behavior-examples.md](behavior-examples.md) for `case_report` bindings and
explicit alternatives. Parent results are derived from all their examples.
Command-backed arrangements are derived from
`verification_commands[].covers`; one command can cover several targets. For
each remaining target, add exactly one `verification_reviews` entry:

```json
{
  "target_ref": "direction.acceptance:DIRACC-0123456789ABCDEF",
  "method": "agent_review",
  "reason": "Compare the revised explanation with the confirmed business rule.",
  "evidence_refs": ["SRC-001"]
}
```

Use `agent_review`, `existing_evidence`, or `not_verified`. Review and reuse
require known source/decision references; explain why prior evidence still
applies. An explicit unverified arrangement needs its reason and visible
consequences, and cannot later be reported as supported without revising the
plan. A missing arrangement is blocked before plan confirmation. Keep the
whole-assessment `verification_not_required_reason` when there are no commands;
it does not replace the per-target arrangements. No command is needed merely
to turn an Agent's semantic review into a tool receipt. The plan exposes the
derived `verification_targets`; it is bound to that plan revision, not a second
editable target list. Existing approval points cover these choices.

When a real interface, permission, concurrency, compatibility or recovery risk
needs a precise behavior contract, read
[behavior-contracts.md](behavior-contracts.md). Use only the applicable topics;
do not expand a simple change into an unrelated standards checklist.

When the implementation or test boundary itself needs design, use
[implementation-practices.md](implementation-practices.md). It adds Agent
reasoning guidance, not another assessment payload or a new method adoption.

Formal verification commands are final evidence obligations, not a list of
every development feedback command. Do not submit nested S1/S2/S3/S4 commands
when the broader required suite already executes the same assertions. Keep an
extra targeted command only when it proves a distinct acceptance or risk that
the project-required final commands do not adequately identify.

For user-visible behavior, trace at least one maintained test and final
acceptance check through the real public entry point (CLI, API, or equivalent),
not only an internal class import. Use one lowest-layer behavior test and one
cross-boundary test when both prove distinct seams; do not multiply equivalent
assertions.

```json
{
  "verification_commands": [{
    "argv": [".venv/Scripts/python.exe", "-m", "pytest", "tests/unit", "-q"],
    "cwd": ".",
    "run_kind": "targeted_test",
    "covers": [
      "direction.acceptance:DIRACC-0123456789ABCDEF",
      "risk_assessments[0]"
    ],
    "reason": "..."
  }]
}
```

`run_kind` is one of `targeted_test`, `integration_test`, `acceptance_test`,
`typecheck`, `build`, `lint`, `manual_check`, or `full_regression`. Choose argv
from actual project facts; do not infer tools from suffixes or add full
regression because of AssuranceBand. Multiple obligations may share one
command. Every `covers` entry must point to an existing
`direction.acceptance:DIRACC-*`, `direction.constraint:DIRCON-*`,
`direction.example:DIREX-*` (with a native case binding), or
`risk_assessments[n]`; design decisions, operations, and method applications
are not verification targets. If no command applies, omit
`verification_commands` and add a specific `verification_not_required_reason`.

Keep documentation verification proportional to what can really be proved.
For prose-only documentation that changes no machine-consumed configuration,
schema, executable example, generated output, or path behavior, do not invent
keyword, regular-expression, or path-existence commands. If the project has no
existing documentation build, link checker, or executable-example check that
applies, use zero commands and explain that the semantic accuracy is reviewed
by the Agent and accepted by the user rather than machine-proven. When a file
is machine-consumed or an existing documentation tool applies, verify the real
parser, build, link, or example behavior at the lowest effective layer.

For formal delivery, use this exact outer field and shape:

```json
{
  "delivery_plan": {
    "expected_outcome": "...",
    "rollback_or_recovery": "...",
    "limitations": [],
    "evidence_refs": ["SRC-001"]
  }
}
```

A minimal non-delivery A0 contains only the required core, all twelve names in
`impact_scope.unaffected`, and `verification_not_required_reason`. A0 is an
AssuranceBand, not an investigation mode. Do not create a WorkItem for ordinary
Agent searching, scratch notes, or subagent work.

These installed references are the normal submission Interface. Do not read
test fixtures or internal schemas merely to rediscover field names. A typed
rejection may be corrected from its exact message; repeated ambiguity is a
product defect to report, not a reason to scan implementation tests.
