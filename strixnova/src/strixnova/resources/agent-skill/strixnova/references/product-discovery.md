# Discover and test a product idea

Read this reference only when a product or feature idea is not yet clear enough
to form a requirement, a long-term-authority candidate, or a named WorkItem;
when a named matter's product premise is still too uncertain for a safe
direction;
when the user asks to brainstorm or challenge an idea; or when a current
external fact could materially change the product decision. Skip it for a
clear, bounded request, an already confirmed direction whose product premise
remains valid, or a purely technical implementation question.

## First decide whether discovery is needed

This method does not override the intake route. If the user has asked to start
an identifiable managed result, record that request with `strixnova intake`
before asking discovery questions. The request can be concrete while its
business meaning, scope or authorization boundaries still need clarification;
resolve these within the returned direction action. Only an unformed wish or
an explicit discussion-only request stays outside a WorkItem.

Before asking the owner anything, inspect the user's original words, adopted
authorities, relevant project material, necessary code, and evidence already
available. Then ask:

- Can the affected person or situation, real problem, desired change, decisive
  boundary, and success signal already be stated without inventing a product
  decision?
- Is there an untested claim whose failure would reverse the recommendation?
- Would a current market, regulatory, competitor, user-behaviour, or technical
  fact change the decision?

If the first answer is yes and the other two are no, stop discovery and form
the appropriate existing product, domain, architecture, or direction candidate.
Do not run a checklist merely because this file was loaded.

Otherwise identify the single load-bearing gap. Choose the one action below
most likely to reduce it. Actions may be skipped, combined, repeated, or used
in a different order; they are not stages.

## Keep one useful conversation loop

For each turn:

1. State the current understanding and the one gap that changes the decision.
2. Investigate anything the project, code, tools, or accessible evidence can
   answer without the owner.
3. Choose one discovery action and do as much of it as possible before asking.
4. If an owner decision remains, ask one substantial question. Offer the best
   current recommendation, its visible effect, and the consequence of leaving
   it unresolved.
5. Treat the owner's correction as new evidence: revise every affected
   conclusion rather than defending or quietly preserving the old framing.
6. Stop as soon as an existing candidate can be formed without downstream work
   guessing a key decision, or an honest non-build outcome has been reached.

Do not ask the owner to choose a Strixnova mode, fill a template, repeat facts
that can be investigated, or answer a batch interview. Keep at most five real
high-impact unknowns in view and discuss only one at a time.

## Action 1: frame the problem

Use this when the request is mainly a preferred feature, technology, or
solution and the underlying change is unclear.

Establish only what is material:

- who or what situation is affected, and when the problem appears;
- what they do today, including doing nothing;
- the concrete friction, cost, risk, or missed result;
- the change they actually want to observe; and
- the boundary that would make a different product necessary.

Distinguish user, buyer, and payer only when those roles differ in a way that
changes value, constraints, or adoption. Rewrite solution language as a
problem hypothesis, not as an accepted requirement. Prefer specific examples
and recent behaviour over abstract audience labels.

End this action when the problem can be stated in one falsifiable sentence, or
when another action is clearly more important.

## Action 2: expand genuinely different options

Use this when the first solution has been treated as inevitable or when no
real tradeoff is visible. Generate a small set of options that differ in at
least one decision-bearing dimension: affected audience, value mechanism,
scope, operational burden, reversibility, or validation method. Include
preserving the current situation when it is a real alternative.

For each option explain:

- what it changes for the affected person;
- which assumption it relies on;
- what it deliberately leaves out; and
- what observation would distinguish it from the others.

Do not produce cosmetic variants. Stop expanding when another option would not
change a decision; compare the smallest meaningful set and recommend one when
the evidence supports a recommendation.

## Action 3: stress-test the load-bearing assumption

Use this when the idea depends on a claim that decides whether it is worth
building. Name that claim before testing secondary details.

Separate support, contradiction, and unknowns. Seek the strongest plausible
counter-case, concrete failure scenarios, and the cheapest observation or
experiment that could disprove the claim. Ask what would have to be true for
the idea to work and what evidence would cause it to be stopped.

Valid outcomes are:

- **strengthened** — the central claim survives and its limits are clearer;
- **rejected or parked** — current facts or evidence defeat the claim;
- **clarified** — uncertainty is reduced but no build decision is yet justified;
- **experiment needed** — only real-world observation can decide.

Do not soften a negative result into a feature backlog. If the owner rejects or
parks the idea, do not create a new DirectionDecision, WorkItem, or delivery
duty from it. If a managed request already has a WorkItem, preserve its record
and follow the existing stop or cancellation contract for the actual owner
decision; do not erase the intake or continue implementation.

## Action 4: investigate decision-changing evidence

Use this only when an external fact would materially change the product
decision. Start with the decision to be made, not a broad research topic.

- Treat model knowledge as a source of hypotheses, never as proof of a current
  external fact.
- Prefer primary and authoritative sources. Record the source, publication
  date, relevant event date when different, jurisdiction or population, and
  the exact scope supported.
- Distinguish project facts, owner decisions, assumptions, sourced claims, and
  Agent inferences.
- Compare material disagreement instead of averaging it away. State what the
  evidence cannot prove and when it will become stale.
- If access is unavailable, preserve a visible unknown. If only an experiment
  can answer, recommend the smallest safe experiment and its stop condition.

Research serves the current decision. Stop when additional sources are
unlikely to change it; do not build an unbounded report.

## Action 5: synthesize the product understanding

Use this when enough information exists to form an existing authority
candidate, or when a familiar expression will help the owner review it.

A compact Product Brief lens may cover:

- affected people or situations;
- problem and current alternative;
- desired result and value mechanism;
- scope, non-goals, constraints, and decisive tradeoffs;
- load-bearing assumptions and evidence status; and
- success signals and the recommended next decision.

A customer-facing PRFAQ lens may test whether the same idea can explain:

- whose problem changes and why it matters now;
- what experience or result becomes possible;
- why current alternatives are insufficient;
- the hardest trust, adoption, cost, or operational questions; and
- what remains uncertain or deliberately excluded.

Use these as lenses, not separate editable truths. Durable product facts go to
ProjectProductDefinition; domain meaning goes to ProjectDomainModel;
cross-unit durable choices go to ProjectArchitectureDescription or an ADR;
and one concrete change goes to DirectionDecision and WorkItem. PRD, SPEC,
Product Brief, PRFAQ, Architecture Spine, Epic, and Story remain formation
guides or read-only projections bound to exact existing revisions.

## Finish with an explicit outcome

End discovery with one of these plain conclusions:

- ready to form a named existing candidate, with remaining assumptions stated;
- parked pending a named owner decision, source, or real experiment;
- rejected because a stated load-bearing assumption failed; or
- clearer, but with no current build content to hand off.

The last three outcomes do not require a WorkItem. By default, keep the
conclusion in the conversation. Create non-authoritative working material only
when cross-session continuity, multi-person review, or a substantial evidence
set genuinely needs it and the managed project's own documentation policy
allows it. Such material must be visibly non-authoritative, remain outside
`.strixnova`, omit full conversation transcripts, avoid copying facts already
owned by current authorities, and never act as recovery state or bypass a
confirmation.

When a concrete matter can be named, return to the main Skill. Use
`artifact-formation.md` only if delivery span, familiar projections, or a
durable cross-unit choice still needs separate formation guidance. Use the
public Strixnova contract for every subsequent command and payload.
