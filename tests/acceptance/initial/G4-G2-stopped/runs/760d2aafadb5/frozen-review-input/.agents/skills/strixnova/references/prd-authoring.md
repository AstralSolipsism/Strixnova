# Form, explain, review, and update product requirements

Read this when a PRD or product-level requirements need substantive authoring
or a readable view. Use [artifact-documentation.md](artifact-documentation.md)
for shared source, preservation, review, and update rules. Use product discovery
only while a decisive product premise is unclear; do not restart it because a
document has been requested. A clear single change can stay in the normal
direction route.

## Identify the work the request needs

Investigate existing product/domain authorities, relevant architecture or ADRs,
supplied notes, and the previous reading view. Distinguish the user's intent:

- **Form requirements:** develop incomplete product understanding and prepare
  the corresponding existing candidates. A PRD may explain those candidates
  before confirmation, with their actual source/status explicit.
- **Organize existing content:** write or refresh a PRD from the applicable
  exact sources without changing their meaning.
- **Review:** assess the existing PRD against its sources and intended use;
  report findings and leave files unchanged unless editing is also requested.

Infer the operation from the request and evidence. Ask only when the distinction
would change the authorized work. Do not ask the owner to choose a workflow or
supply facts you can inspect.

## Develop only the decisions the product still needs

Start with the existing understanding. Name the product's actual concerns and
the next decision the document must support: whether to proceed, what to include,
or whether architecture/engineering planning can start. A small internal tool
and a product with several actors, external contracts, or costly failures need
different depth. Effort, page count, and how professional a template looks do
not determine adequacy.

Use the following lenses where they change that decision:

- **People, problem, and outcome.** Connect the affected situation, current
  alternative, cost or missed result, and desired change. Reuse discovery
  conclusions; reopen one only when new evidence or an owner correction matters.
- **Journeys and capabilities.** For interaction-heavy work, obtain a concrete
  session: who starts, in what state, which important actions or handoffs occur,
  when value arrives, and what state remains. For APIs, libraries, or a single
  operator, a capability and its observable result may be clearer. Derive from
  real inputs or explicitly proposed examples; do not invent persona biographies
  or present imagined user research as fact.
- **Behavior and completion.** Describe the actor/system capability, triggering
  conditions, result, and at least one observable consequence for each material
  requirement. Examine the alternate, denied, empty, failure, and recovery paths
  that would change scope or acceptance. Distinguish required behavior from a
  particular technical implementation.
- **Quality and constraints.** Turn applicable reliability, privacy, security,
  accessibility, performance, cost, operational, or integration concerns into
  decision-bearing bounds. Find thresholds in evidence or obtain the owner's
  decision; preserve an unknown rather than inventing a plausible number.
- **Scope and tradeoffs.** State the first deliverable's coherent value, explicit
  exclusions, dependencies, and the consequence of excluding or deferring work.
  Explain what was given up. Do not quietly shrink a difficult requirement into
  a later phase to make the draft look ready.
- **Success and uncertainty.** Separate demonstrable acceptance from outcomes
  that require later real usage or measurement. Record assumptions, contrary
  evidence, open decisions, and conditions for revisiting them. Use a balancing
  measure when optimizing one result could damage another important outcome;
  avoid adding metrics solely because the template has a slot.

Investigate before each necessary question. Discuss the one unresolved choice
most likely to change the product or downstream design, with a reasoned
recommendation and consequences. After a correction, reassess the affected
conclusions. Keep the existing limit of five high-impact unknowns in view per
formation pass, but never call a complex product ready because a question quota
was exhausted. Resolved decisions can expose a further necessary pass.

## Put meaning into the existing owners

Product purpose, people, problems, outcomes, capabilities, exclusions, product
constraints, and success criteria belong to ProjectProductDefinition. Domain
terms, roles, rules, states, and business scenarios belong to ProjectDomainModel.
Durable cross-unit choices belong to ProjectArchitectureDescription or an ADR.
A named change's scope and acceptance belong to DirectionDecision; technical
execution belongs to EngineeringAssessment and EngineeringPlan. Use their
actual input contracts, not fields inferred from this writing guidance.

If a reading draft exposes a missing decision, return it to that owner. Where
the requested formation permits candidate files, prepare the real source
candidate and bind the reading expression to it. If the current scope permits
discussion only, keep a clearly sourced discussion draft and its questions;
do not invent formal IDs or adopt it. Confirming a PRD paragraph never substitutes
for the corresponding existing authority decision.

## Compose the PRD and its coverage

Organize the body around the product's coherent purpose and behavior. A useful
default is purpose and audience, important flows or capability groups, concrete
requirements, applicable quality bounds, scope/tradeoffs, success, and remaining
decisions. Adapt the order and depth; omit irrelevant sections with judgment.
Use the domain's existing vocabulary throughout. Keep technical details in their
own source and cite them when they constrain the product.

Bind the exact product revision and the domain/architecture/ADR material actually
used. Account for every item of the selected product definition's users,
problems, outcomes, capabilities, non-goals, constraints, success criteria,
delivery stages, and unresolved decisions. A deliberately narrower view states
its scope and accounts for excluded items instead of silently calling itself
complete. Include relevant domain/architecture references without claiming a
machine has identified all semantically relevant facts. Preserve stable source
IDs; do not create a second FR numbering system with independent identity.

## Judge whether this PRD serves its next decision

Review the complete result, including any referenced detail necessary to read it:

- Can the owner make the actual scope/tradeoff decision, with real alternatives
  and consequences visible?
- Do the capabilities and priorities serve the stated problem and outcome?
- Can a downstream reader determine what satisfying each material requirement
  means, including applicable failure behavior and quality bounds?
- Are exclusions, unconfirmed assumptions, and blocking questions explicit?
- Did all important supplied claims survive, or receive an explicit disposition?
- Do product, domain, architecture, and any existing direction agree on roles,
  terminology, boundaries, and promises?
- Is the level of detail useful for this product and its next consumer?

Report actionable findings with their effect and source, not a count of populated
headings. Resolve what the evidence and existing authorization permit. Escalate
decisions that would change product meaning; retain honest nonblocking unknowns
with a revisit condition. Reuse the existing cross-artifact review when forming
formal candidates. A request for review alone never authorizes rewriting them.

Finish when the owner can decide and downstream planning can proceed without
inventing a key product decision, or explain the precise reason it cannot yet
proceed. Discovery can also end in postponement or rejection. Supply the actual
reading artifact when requested and possible; a description of how you would
write a PRD is not its delivery. Use the shared update rules for later changes.
