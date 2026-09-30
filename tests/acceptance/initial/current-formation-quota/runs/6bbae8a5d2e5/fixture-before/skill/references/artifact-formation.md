# Form artifacts for the current decision

Read this reference only when a request is materially vague, its delivery span
is uncertain, the user asks for a familiar planning artifact, a cross-unit
architecture choice is emerging, or a discovered upstream error may invalidate
downstream work. For a clear single-WorkItem request, use the ordinary
direction and engineering-assessment guidance without loading this file.
When the product or feature idea itself is not yet clear enough to name a
concrete matter, use `product-discovery.md` first; return here only if delivery
span, a familiar projection, or a durable cross-unit choice still needs work.

Use the current `CurrentAction.input_contract_ref` for payload shape. This
reference helps choose formation depth, delivery span and readable artifacts.

## Start from evidence, then find the missing decision

Use the user's words as evidence of intent, not as a complete specification and
not as text to expand mechanically. Before asking a question:

1. inspect the currently adopted product, domain, architecture, engineering
   policy, implementation alignment, relevant project documents, and code only
   to the depth needed for this decision;
2. separate facts the project can answer from choices only the project owner
   can make;
3. identify the earliest unresolved choice that would materially change the
   goal, boundary, tradeoff, success condition, or downstream authority; and
4. either form the existing candidate immediately or ask one decision question
   with a recommendation, user-visible effect, and consequence of no action.

Do not ask the owner for file locations, framework details, domain terms, test
commands, or current behavior that the Agent can investigate. Do not keep
exploring after downstream work can proceed without inventing a key decision.

## Judge three independent axes

Do not compress planning into one small-to-large scale. Explain each applicable
axis from current project facts.

| Axis | Question | Evidence | Existing destination |
|---|---|---|---|
| Formation depth | Would downstream work still have to invent the customer, problem, boundary, major tradeoff, or success condition? | User intent, adopted authorities, project evidence, unresolved decisions | Conversation, a long-term-authority candidate, or a DirectionDecision candidate |
| Delivery span | What is the smallest number of results that can each deliver value and be accepted independently? | Independent value, shared decisions, ordering dependencies, cross-unit coordination | One WorkItem, related WorkItems, or project-level authority formation |
| Assurance depth | How much investigation, review, and verification does each result require? | Impact, risk, reversibility, uncertainty, and project policy | EngineeringAssessment and AssuranceBand |

File count, lines of code, expected sessions, artifact names, and activity names
may inform investigation but do not decide any axis. A one-file irreversible
data change can remain one WorkItem with deep assurance. A broad mechanical,
recoverable edit can span several WorkItems without requiring the highest
assurance.

## Choose the interaction pace inside the same contract

Use fast drafting when the goal, boundary, applicable product guardrails, and
acceptance are already clear. Investigate, state any material assumptions, form
the existing candidate, and present only a real remaining decision. Do not
manufacture questions. In an adopted project, reuse valid authorities and update
only affected content; create PRD, SPEC or other reading artifacts only when needed.

A project's first formal repository delivery still requires complete foundational
authorities. Follow the first-adoption boundary in
[engineering-assessment.md](engineering-assessment.md). The Agent investigates and
reuses existing material, with depth proportional to the project; the owner makes
substantive decisions rather than filling in templates.

Use guided elaboration when the customer, problem, desired result, boundary,
major tradeoff, or success condition is still consequentially unclear. Work
from upstream choices to downstream choices, one decision at a time. Keep no
more than five genuinely high-impact unresolved questions in one formation
pass. Reassess after each owner correction and stop when the same existing
candidate can be formed safely.

These are interaction paces, not modes. Both end in the same long-term
authority, DirectionDecision, EngineeringAssessment, and confirmation
contracts. Never ask the user to choose a Strixnova planning mode.

## Choose the delivery span by independently acceptable results

- Use one WorkItem when the requested outcome can be accepted as one coherent
  result, even if its implementation has several dependent steps or high risk.
- Recommend multiple WorkItems when each result has independent user value and
  acceptance, can be delivered separately, and does not require the other
  results to be called complete. Declare an existing WorkItemRelation only when
  the target and project-specific relationship are already real.
- Form or revise project-level authorities before WorkItem implementation when
  several results depend on one unresolved product decision or a cross-unit
  architecture choice that must remain consistent.

A Story is one independently acceptable WorkItem candidate. An
ImplementationSlice is an internal step within one confirmed WorkItem plan.
Do not use internal implementation steps as extra Stories. Existing WorkItem
relations provide traceability only; they do not create Epic acceptance,
portfolio progress, scheduling, or Agent orchestration.

## Map familiar artifacts to the existing authorities

Use familiar names to help thinking or reading, never to create another
editable truth.

| Familiar expression | Form the meaning in | Boundary |
|---|---|---|
| Product Brief or PRFAQ | ProjectProductDefinition and ProjectDomainModel candidates | Optional discovery lenses; durable facts go to the owning authority |
| PRD | A read-only composition of exact product, domain, and necessary architecture revisions | Record source revisions; change meaning by revising those authorities first |
| SPEC | A read-only composition of the DirectionDecision and relevant EngineeringPlan | No independent state, confirmation, or write authority |
| Architecture Spine | ProjectArchitectureDescription or an ADR candidate | Keep only cross-unit choices with a real durable tradeoff; leave local reversible choices in the plan |
| Story | One independently acceptable WorkItem candidate | Not an ImplementationSlice |
| Epic or Initiative | No first-class Strixnova object in the current product | Use known WorkItem relations only for traceability; do not claim aggregate acceptance or scheduling |

For substantive PRD formation, organization, review, or updating, read
[prd-authoring.md](prd-authoring.md). For the equivalent change-specification
work, read [spec-authoring.md](spec-authoring.md). Each uses the shared
[artifact-documentation.md](artifact-documentation.md) source and update rules.
Read only the specialized guide the current request needs. A requested reading
artifact must actually be written when authorized and supported by sources;
this mapping table alone is not its delivery. Candidate reading expressions
must name their real source and status before the existing owner decision.

The built-in artifact-formation guidance may use selected SDD
(specification-driven development) writing techniques. That use is not evidence
that the managed project adopted SDD or any other EngineeringMethod. Record a
method adoption only in ProjectEngineeringPolicy when the project's own needs
justify that durable decision.

## Route the common difficult cases

| Situation | Recommended formation | Avoid |
|---|---|---|
| Clear, bounded change | Investigate and form one WorkItem direction directly; apply the first-adoption boundary if needed | Unneeded PRD, rebuilding valid authorities, or ceremonial questions |
| Vague desire with no identifiable change | First establish the user, problem, desired result, and decisive boundary; create a WorkItem once a concrete matter can be named | Writing Agent guesses as requirements |
| Concrete but incomplete request | Create the requested WorkItem, then close only material direction gaps inside its direction stage | A shadow interview before `intake` |
| One high-risk result | Keep one WorkItem when acceptance is coherent; deepen assurance in EngineeringAssessment | Splitting solely because risk is high or reducing assurance because the diff is small |
| Several independently valuable results | Explain the shared goal and propose related WorkItems with separate acceptance | Calling ImplementationSlices user-valued Stories |
| Cross-unit architecture conflict | Form the required target-architecture or ADR candidate before dependent implementation | Letting each WorkItem invent a different durable choice |
| Upstream meaning proves wrong | Revise the owning product, domain, or architecture authority and use AuthorityChangeSet to disposition every downstream effect | Patching only a PRD, SPEC, Story, OwnerView, or implementation plan |

## Review the formed result

Before presenting a candidate, check that:

- every durable statement has one owning existing authority;
- a read-only projection identifies the exact source revisions and cannot be
  edited as a competing truth;
- the recommended delivery span follows independently acceptable results, not
  file count, effort, risk, or internal implementation steps;
- assurance is chosen separately for each WorkItem from impact and policy;
- requirements, scenarios, acceptance, architecture choices, WorkItems, and
  ImplementationSlices do not omit or contradict one another;
- an owner correction has invalidated and re-formed every affected downstream
  candidate; and
- the user-facing explanation states what is known, the real gap, the
  recommendation and reason, its effect, the consequence of no action, and the
  next existing Strixnova action without exposing internal IDs as meaning.

This review remains Agent judgment. Strixnova can validate the existing
structures, references, versions, states, and declared evidence boundaries; it
does not prove the natural-language semantics correct.
