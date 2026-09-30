# Form and maintain a readable specification for a change

Read this for substantive specification writing, review, or an existing
DirectionDecision/EngineeringPlan reading view. Apply
[artifact-documentation.md](artifact-documentation.md) for shared source,
preservation, review, and update rules. Ordinary direction formation uses its
current input contract.

## Establish the actual specification basis

Read the selected WorkItem, its applicable direction and plan, their actual
confirmation status, and the precise upstream sources they reference. Bind
WorkItem identity, direction version and candidate fingerprint, and, when a plan
exists, its identity and confirmation/candidate binding. Bind the relevant
assessment identity/revision and upstream product/domain/architecture/policy
sources when they carry included decisions. Do not substitute the mutable
WorkItem version for these meaning-bearing bindings: slice completion, test
receipts, or delivery progress can change without changing a specification.

An absent or unconfirmed plan cannot be described as accepted technical design.
A direction-only view can explain the agreed behavior and explicitly leave
engineering planning pending. For a proposal not yet represented in a direction,
use the existing formation route; explain a sourced proposal as such without
inventing a WorkItem, a confirmation, or stable requirement IDs.

Read the old SPEC as a reading aid, not as an authority overriding the current
direction. Check for replacement, replanning, and cancelled or historical work.
Do not claim a historical direction or superseded plan is current merely because
the SPEC file exists.

## Make the behavioral contract clear

Explain why this change is needed, who or what observes the result, the in-scope
capabilities, design-bearing constraints, explicit non-goals, and observable
acceptance. Preserve the owning direction's stable requirement, constraint, and
acceptance identities and their requirement_refs. The coverage index can carry
internal IDs while the body uses meaningful names.

When the owning direction contains behavior examples, preserve their identities,
given/when/then and basis_refs in the reading view. Follow
[behavior-examples.md](behavior-examples.md) for their confirmed source and test
links; never invent an extra example only in the specification.

For each requirement connect its triggering conditions, observable behavior,
result, and applicable acceptance. Concrete Given/When/Then scenarios are useful
when they clarify interaction or a boundary; they are a writing form, not a new
executable specification language. Cover the actual denial, error, empty,
concurrency, or recovery cases that affect this change. Do not manufacture cases
or numerical thresholds to fill a template. If the existing direction lacks an
important decision or sufficient acceptance, report it and route the correction
to that direction rather than silently enriching its reading view.

Separate what the system must do from how the plan intends to do it. Summarize
the chosen design, relevant alternatives and tradeoffs, interfaces, dependencies,
verification approach, and recovery arrangement only as far as needed to explain
the change. Reference detailed operations, commands, and other plan-owned
material without reproducing the full engineering payload. Long-lived technical
decisions retain their architecture/ADR source.

## Preserve scope and expose coverage gaps

Account for all direction requirements, constraints, and acceptance items. Each
must be represented in the body or explicitly referenced at an identified source
location; a reading view cannot silently drop an obligation. Account for the
plan's decisions, operations, slices, verification commands, and recovery
arrangements as either explained or intentionally left in the referenced plan's
execution detail. Explain that disposition; do not pretend omission proves
irrelevance.

Review separately:

1. **Requirement quality:** can the behavior and its acceptance be understood and
   checked? Are scope, uncertainties, and material exceptional cases explicit?
2. **Cross-artifact consistency:** do direction, plan, operations/slices, and
   verification cover each other without contradictions, orphan work, or missing
   obligations? Map using explicit identities where available. A valid reference
   is not evidence that the associated test is sufficient.
3. **Implementation comparison, only when requested:** inspect actual code and
   evidence against the specified scope. Distinguish missing, partial,
   contradictory, or unrequested behavior, citing the requirement and observed
   evidence. Source inspection and passing tests do not prove every acceptance
   condition; do not turn the SPEC into a second actual-result ledger.

In a review-only request, report findings without editing any file. If gaps
require changing direction or plan, use the existing correction/replanning
route. Never weaken a requirement to make code appear conformant, add tasks to a
parallel tracker, or mark runtime work complete by editing the document.

For a requested code-to-specification comparison, use
[code-review.md](code-review.md) to establish the actual code scope and distinguish
standards findings from requirement findings. Do not load it for writing alone.

## Update and hand off

Compare the actual direction and plan bindings with the previous view. Describe
requirements added, revised, retired, or unchanged using the owning contract's
identity semantics. Reordering or wording changes do not independently create
new requirement identities. A proposal to split, replace, or merge meaning is
resolved in the source, including retirement and new IDs, before the reading
view presents it as current.

Update affected behavior, acceptance, design explanations, and coverage together;
check cross-section references and retire obsolete promises from current prose.
If only expression changed, preserve every source and runtime fact. If a source
changed while writing, reconcile before claiming the result current. If only
unrelated progress changed, retain the specification basis and report any status
context separately.

Deliver the actual SPEC with its exact basis, coverage, material gaps, and what
the next existing engineering step may rely on. An incomplete candidate may be
reviewable while still blocking implementation; make that distinction clear.
Use the ordinary confirmation explanation for the owning direction or plan,
without an additional SPEC confirmation.
