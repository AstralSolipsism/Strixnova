# Implement behavior through maintainable interfaces and tests

Read this when choosing a module or test boundary, fixing behavior with a
regression test, or implementing test-first work. Skip it for prose-only work
and mechanical edits whose existing plan and tests already settle these choices.
Work within the current plan and implementation slice. The feedback section
below distinguishes ordinary implementation from selected test-first work.

If the plan contains behavior examples, also use
[behavior-examples.md](behavior-examples.md) to bind native tests and review
their assertions. Keep the expected behavior independent of today's test output.

## Find the behavior and the responsibility that owns it

Use the confirmed direction, applicable project standards, architecture and
current plan. Inspect the implementation and its callers before choosing a
change. Preserve the project's vocabulary and established interfaces. A local
implementation decision belongs in the plan; a material product or architecture
change returns to its existing owner. Do not silently weaken acceptance.

Choose a boundary that hides a coherent responsibility. Consider everything a
caller must know: inputs, failure behavior, ordering, configuration and effects,
not just the number of public methods. If removing a wrapper would remove only
indirection, it may add no value; if it would force callers to repeat the same
business coordination, it may own useful work. Do not turn that question into a
rule that every wrapper is bad, or add an abstraction solely to resemble a
pattern. A wider interface can be justified by real independent caller needs.

Keep effects and their policy at a deliberate boundary. Reuse the project's
existing ports and adapters where they fit. Extract a seam only when a real
variation, difficult dependency or invariant needs it; do not create a shadow
architecture, rename the domain, or dictate the Agent's code-analysis tools.

## Choose what the test must observe

Identify the smallest stable interface that exposes the behavior at risk, and
the independent basis for its expected result: a confirmed example, requirement,
invariant or worked case. Exercise the actual behavior, not a copied version of
the production calculation. A literal expected value is useful when it represents
a real promise; a current revision ID or file count is not automatically one.
When testing a binding, compare it with its owning source instead of scattering
the current value through unrelated tests. Preserve deliberate public contracts,
such as the exact installed resource set, when those are the behavior under test.

Prefer observable results and effects over private method names, collaborator
call order or implementation-shaped mocks. Check that a behavior-preserving
refactor could change internal structure without breaking unrelated tests. A
focused helper or protocol test is still useful when it protects a distinct
invariant; do not expose internals merely to make them easy to assert against.

Use real cheap in-process components. For time, randomness or external systems,
choose a controlled dependency that reproduces the relevant behavior. An isolated
real database can prove different things from a fake; neither substitutes for
the other automatically. Do not make network calls, use live accounts or install
tools just to satisfy a testing pattern. State the limitation of each substitute,
and keep a cross-boundary check where the plan needs evidence beyond it.

## Use feedback one behavior at a time

For a reproducible defect, first demonstrate the wrong observable result. When
test-first work is requested or selected by the project and plan, add one focused
behavior test and run it before the repair. Verify that it fails for the intended
reason; an import failure, unavailable tool or broken fixture is not that proof.
Implement enough to satisfy that behavior, then consider the next material case.
Do not write a speculative suite for interfaces that have not been understood.

An internal feedback step is not another WorkItem or ImplementationSlice. Stay
within the current slice's paths, dependencies and allowed effects; a necessary
change outside the plan uses the existing replanning route. Select applicable
normal, denial, repeated-action, boundary and failure cases from the requirement
and risk, rather than applying every category to every change.

Once behavior is protected, simplify where doing so improves the actual design.
Run the affected checks after a refactor. Replace tests that only freeze retired
internals after their useful behavior is covered; retain independent cases.
Do not convert a failing requirement test into a weaker expectation to get green.

## Keep development feedback and delivery evidence distinct

Use [engineering-assessment.md](engineering-assessment.md#select-a-minimal-verification-set)
to select final verification obligations and [verification.md](verification.md)
to run and assess their receipts. A deliberate failing development test is useful
feedback, not a passed final receipt. Do not pre-run a final suite outside its
recorded execution, duplicate broad suites under new labels, or retain every
internal command as a formal obligation. Report the feedback actually obtained
and material limits; if no failing test was observed, do not claim it was.

A requirement linked to a test is a declared relationship. The Agent must still
judge whether the assertion exercises that requirement. Strixnova validates the
existing references, versions, state and receipts; it does not certify test
adequacy, module quality or TDD compliance. Do not add confirmations for routine
test choices that are already covered by the authorized plan.
