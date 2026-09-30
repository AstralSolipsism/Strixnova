# Direction submission

Read this file only for `CurrentAction.input_kind=direction`. Use the user's
vocabulary and do not invent scope merely to satisfy a field.

Read `CurrentAction.input_contract_ref` through `strixnova next --record` before
submitting. That returned public contract is authoritative for payload shape.
This reference only explains how to form the semantic content.

Read `project.direction_context` in the same step when it is listed by the
CurrentAction. It is a compact, complete projection of the currently adopted
product purpose, current stage, capability catalog, non-goals, and constraints.
It is not a recommendation or relevance ranking. The program does not decide
which capability matters to this request.

## Clarify proportionally before submission

The user's initial wish is evidence, but it is not automatically a complete
direction. Clarify only what is needed to make the direction safe to confirm:

1. Separate discoverable project facts from user decisions. Inspect code,
   project rules, and existing behavior yourself when they can answer the
   question; do not ask the user to identify files, architecture, tests, DDD
   terms, or implementation details the Agent can determine.
2. Identify only unresolved decisions that could materially change the goal,
   scope, non-goals, constraints, acceptance, or key tradeoffs. Do not ask for
   details that belong to the later engineering assessment.
3. Ask one decision question at a time. Lead with the recommended answer and
   explain the user-visible effect or tradeoff in plain language. Resolve
   upstream choices before asking questions that depend on them.
4. If the wish is already safe and sufficiently specific, ask no ceremonial
   questions. Stop as soon as the six direction groups can be stated honestly;
   do not traverse every possible branch or try to understand the whole
   project first.
5. Keep clarification in the normal host conversation. Do not create a second
   Strixnova discussion state or submit every conversational turn. Submit the
   resulting direction once it is ready; if a material decision remains open,
   submit `ready_for_confirmation=false` with concrete blockers. Never place a
   recommended answer into a confirmation-ready direction before the user has
   answered.

Keep the recommended choice and its consequence next to the one unresolved
question. Reuse answers whose basis still holds; expose changed assumptions
when they really require a new decision. For example, if only export scope is
unresolved: “建议先导出当前筛选结果，这样文件与眼前列表一致；导出全部数据会包含
未显示记录。你希望导出当前结果还是全部数据？” Do not append questions about
file locations or implementation details you can investigate yourself. This
clarification still does not accept the complete direction formed afterwards.

## Bind the direction to current product decisions

For an adopted project, the Agent must:

1. select at least one actually relevant `capability_ref` from the complete
   catalog;
2. cover every returned guardrail exactly once with `applies`,
   `not_applicable`, or `reconsider`, and write a project-specific reason;
3. record only assumptions that materially support this direction, together
   with the fact that would require reconsideration; and
4. copy the current `context_ref` exactly.

The program checks only freshness, identity, reference existence, uniqueness,
and complete guardrail coverage. It does not judge whether a capability is
semantically relevant, whether a reason is persuasive, or whether an assumption
is wise. If the product context changes, the old direction becomes stale and
must be re-formed from the new context before assessment, implementation, or
result acceptance. `CurrentAction.action_type=revise_direction` is the
deterministic recovery path: read the old direction, its downstream plan, and
the new complete `project.direction_context`; explain only what changed and
reuse user decisions whose basis is still intact. Submitting the revised
direction atomically records the exact invalidation facts with the replacement
candidate, then uses the ordinary direction confirmation point. It does not add
another user gate.

`reconsider` does not cancel an existing product decision. The existing
guardrail remains binding until a new ProductDefinition candidate is assessed,
independently confirmed, and adopted. An assessment following `reconsider`
must mark `product_scope` affected or unknown and plan that product candidate.

For a project with no adopted ProductDefinition, use `context_ref: null` and
empty capability and guardrail lists. Do not invent product references.

Before the direction confirmation gate, present one plain-language card that
covers the goal, in-scope and out-of-scope results, acceptance, important
constraints and tradeoffs, plus any unresolved blocker. This is proportional
guided clarification, not a mandatory exhaustive interview.

## Give each direction item a stable identity

Create a new random identifier when a requirement, constraint, acceptance
criterion or behavior example first appears: `DIRREQ-`, `DIRCON-`, `DIRACC-`
or `DIREX-`, followed by 16
uppercase hexadecimal characters. The identifier is not a content hash and is
not derived from the array position.

When revising an already confirmed direction, compare meaning rather than
wording or order:

- retain the existing identifier for a reorder or wording clarification that
  does not change meaning;
- use a new identifier when meaning is replaced, split, or merged;
- never restore an identifier that left a later confirmed direction; and
- list every applicable `DIRREQ-*` in each acceptance criterion's
  `requirement_refs`, with every current requirement covered by at least one
  acceptance criterion.

Explain retained, retired, and replacement meanings to the user in ordinary
language as part of the complete direction revision. Do not ask the user to
manage raw identifiers. The program checks identifier format, uniqueness,
reference closure, coverage, and non-revival; it does not decide semantic
sameness or whether the acceptance criteria are sufficient. Confirmation still
covers the complete direction revision, and its new `direction_version` still
invalidates every older assessment, plan, implementation record, and
verification result.

Do not show the user raw `context_ref`, capability identifiers, decision
identifiers, or hashes as if they carried meaning. Explain the selected product
capabilities, the treatment of each guardrail, and material assumptions in
ordinary language. Internal references are carried mechanically in the payload.

Each acceptance criterion requires a `behavior` disposition. For observable
behavior changes use `required` with concrete examples; read
[behavior-examples.md](behavior-examples.md) for their scope, basis and later
verification. Pure prose or behavior-preserving mechanical changes may use
`applicability=not_applicable` with a specific `reason`. Use
`undetermined` with a reason only in a blocked draft, never a ready direction.
Include the examples in the existing direction card and confirmation.

```json
{
  "direction": {
    "schema_version": "strixnova.direction-decision.v1",
    "decision_context": {
      "context_ref": null,
      "capability_refs": [],
      "guardrail_dispositions": [],
      "assumptions": []
    },
    "goal": "Reject reservations when stock is insufficient.",
    "scope": [
      {
        "requirement_id": "DIRREQ-0123456789ABCDEF",
        "statement": "Reject insufficient-stock requests without changing stock."
      }
    ],
    "non_goals": [],
    "constraints": [
      {
        "constraint_id": "DIRCON-0123456789ABCDEF",
        "statement": "Stock cannot become negative."
      }
    ],
    "acceptance": [
      {
        "acceptance_id": "DIRACC-0123456789ABCDEF",
        "statement": "An insufficient-stock rejection leaves stock unchanged.",
        "requirement_refs": ["DIRREQ-0123456789ABCDEF"],
        "behavior": {
          "applicability": "required",
          "examples": [{
            "example_id": "DIREX-0123456789ABCDEF",
            "title": "Reject a reservation beyond available stock",
            "given": ["Available stock is 2 units"],
            "when": "A caller reserves 3 units",
            "then": ["The request is rejected", "Available stock remains 2 units"],
            "basis_refs": ["direction.requirement:DIRREQ-0123456789ABCDEF"]
          }]
        }
      }
    ],
    "tradeoffs": [],
    "work_item_relations": []
  },
  "ready_for_confirmation": true,
  "blockers": []
}
```

Set `ready_for_confirmation` false and include concrete blockers when the
direction is not safe to confirm. `work_item_relations` is optional. Include it
only when the user or already-known project facts identify a real target; do
not scan all Authority history to guess one. Types are:

- `related_to`: meaningful general relation only when no specific type fits;
- `part_of`: source is part of the target larger WorkItem;
- `depends_on`: source needs an outcome already delivered by target;
- `follows_up`: source continues or improves target afterward;
- `supersedes`: source direction or solution replaces target's older one.

Every relation needs a project-specific reason. Relations are trace facts only;
they do not inherit tests, block, schedule, lock, merge, or resolve conflicts.
