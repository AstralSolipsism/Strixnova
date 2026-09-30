# Review code against its standards and intended behavior

Read this for a requested code review, a requested comparison with a
specification, or a code review required by the current plan or project policy.
For a formal authority or plan review, also use the applicable procedure in
[cross-artifact-review.md](cross-artifact-review.md). An informal read-only code
review can finish without a WorkItem or that additional procedure.

## Establish the actual comparison and sources

When the user has authorized Strixnova context use and the project has recorded
authorities, read `strixnova context contract review`, then use
`strixnova context review --project-dir <project> --input @<request.json>`.
Use `mode: changes` for an explicit comparison or `mode: modules` with the
returned module identities for a focused review without a diff. Each selected
repository needs its own `ref` (`null` means the working tree); change mode also
needs `base_ref`. `basis_ref` selects the authority basis, otherwise the project's
configured integration ref applies. Existing explicit repository bindings apply.

This query creates no WorkItem and does not execute a reviewer. It follows
recorded ownership and explicit relationships; the Agent still investigates
semantic relevance and missing dependencies. Treat `sources`, `gaps`,
`omitted_files`, partial content windows and `recorded_observation_current` as
part of the result. Keep adopted constraints, candidates, recorded observations
and current code distinct. `status: available` does not mean review passed.
Missing material permits a limited review; identity/version conflicts require
correct input. Never initialize governance, refresh alignment, or install another
reviewer merely to obtain this context. `--format markdown` renders the same
facts when a reviewer needs a background document; it is not another authority.

Resolve the intended base from the request and existing project facts, then
identify the exact target: a commit, branch result or current working tree. For
working-tree review, include the relevant staged and unstaged changes and new
files; comparing only committed HEAD would omit part of the requested work.
Respect ownership of unrelated changes. Inspect enough surrounding code and
callers to assess effects beyond the changed lines. Separate newly introduced
problems from pre-existing issues unless the change makes one newly reachable.

Read the actual requirements and applicable project standards. Prefer the owning
confirmed direction, plan and authorities; a SPEC reading view must match those
sources. For an informal review, supplied requirements can be used as such,
without invented authority IDs or confirmation status. If the required source is
missing or contradictory, report that limitation and assess only what is known.
Ask only when the unresolved comparison or product choice changes the conclusion.

Review authorization does not authorize repairs, formatting, dependency installs,
source adoption or Git delivery. Respect a request to avoid running tests. If
commands are allowed, use applicable existing tools and keep their effects within
scope; distinguish tool results from checks that were not run. Do not write a
report file unless requested or required by the current project workflow.

## Check standards and design

Use the project's actual rules as the basis for a violation. Tool-enforced
formatting and type rules can be reported from the real tool result. For module
responsibility, dependency direction, error handling or maintainability, the
Agent must inspect the code and explain the consequence. A style preference or
code smell is a design judgment, not an adopted rule or an automatic defect.

Look for changed behavior that spreads coordination across callers, bypasses an
owned interface, adds unused generality, duplicates policy, or makes tests depend
on private structure. Follow a concern far enough to show a real problem. Do not
require an abstraction, rename or rewrite merely to match an external method.
Read [implementation-practices.md](implementation-practices.md) only when a
module or test-boundary judgment needs its additional guidance.

## Check the specified behavior and its evidence

Keep the finding no broader than the path and conditions actually inspected.
A visible entry bypassing its required service proves that local routing defect;
it does not by itself prove that an unseen repository accepts the write or that
every caller can exploit it. Full code-path evidence can establish a static
consequence without running a test; an execution trace establishes what happened
for its actual identity, input and environment. Say which evidence supports the
finding. Missing ownership or stale dependency observations are specific gaps,
not a demonstrated forbidden edge: identify both endpoints and the applicable
rule before declaring that violation. Keep a justified finding even when its
downstream effects remain unverified, and keep a verified effect within its scope.

For each material changed requirement, trace its conditions and promised result
to the implementation and the relevant assertions or observed execution. Check
applicable boundary, denial, repeat, failure and recovery paths. Identify missing,
partial, contradictory or unrequested behavior with a concrete example. A function
name, matching keyword, valid reference or successful command exit is not enough
to establish that the requirement is fulfilled.

Check whether a test would distinguish the promised behavior from the suspected
wrong behavior. Several requirements listed in a command's covers field do not
prove that its assertions test all of them. Missing tests are a separate finding
from a demonstrated implementation error; explain the material untested risk
instead of demanding a case for every line. Distinguish observable acceptance
from business outcomes that still need later usage or measurement.

After a correction, use the new code and its still-applicable sources. Recheck
the affected finding and relevant interactions; do not carry an old accusation
forward after it is fixed, or mark it resolved merely because files changed.

## Report findings and use the existing correction route

Keep standards/design findings separate from specification findings, including
when one Agent performs both passes. A sound implementation can violate a project
rule, and conventional code can implement the wrong requirement. State the exact
scope and include for each material finding its location, rule or requirement,
observable consequence, evidence, and useful correction. Use the existing finding
identity when continuing a formal review. Do not force a problem count or disguise
uncertainty as a violation; a review may legitimately find no actionable issues.

If independent review is appropriate and the host permits it, the Agent may
delegate under the host's normal rules. This is still Agent evidence, not human
expert review or Strixnova-managed orchestration. Do not create a reviewer registry,
parallel checklist authority, quality score or additional user confirmation.

Carry applicable findings and limitations into the existing semantic review,
plan, or actual result using that record's real input contract. A defect in the
implementation is repaired there; a product or architecture decision returns to
its owner. Do not lower the specification to accommodate code. Strixnova checks
the declared references, current versions and unresolved blocking state, not
whether the Agent's judgment is correct or every possible defect was found.
