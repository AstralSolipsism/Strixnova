# Write and maintain a readable view of existing decisions

Read this with the relevant PRD, SPEC, or domain-documentation reference when
the owner needs a readable document. The specialized reference determines the
sources and items it must cover; this file supplies shared writing and update rules.

## Bind the material before explaining it

Inspect the requested scope, existing document policy, and actual source files.
For each source record its path, stable identity, exact revision, and actual
confirmation/adoption status. Distinguish an immutable Git revision from a
working-tree candidate; for an uncommitted source also record its content
fingerprint. Use the existing document's source/index convention where possible.
Keep this metadata and the coverage index in the document, not a separate file.
Use this information to distinguish the view's exact basis from later revisions.

An unconfirmed candidate can be explained before its existing confirmation:
label it as a candidate and bind the source that actually exists. A mixture of
confirmed and candidate sources must show that distinction. Do not label the
whole document approved, current, or ready merely because one source is.
Reading a source file does not prove it is the project's adopted revision.

If an authoritative source is missing, do not fabricate its ID, revision, or
confirmation. In a formation request, use the existing authority/direction
authoring route to prepare the necessary candidate within the authorized scope.
In a reading-only request, explain what can be documented and mark the missing
source. Raw notes can support a discussion draft with explicit provenance, but
that draft cannot be presented as a projection of an authority that does not
exist. Do not create a WorkItem merely to format a reading view.

## Preserve what changes a decision

Read the source bodies before composing or judging the corresponding sections.
A path list, fingerprint, title, or ID catalog locates evidence; it does not
explain a fact's conditions or consequences. Follow collection references and
read long files in bounded ranges until the selected content is covered. Keep
a temporary reading/coverage checklist so interruptions do not turn unread
ranges into assumed coverage. Use available tools for deterministic inventories
and fingerprints; do not invent those values when tooling is unavailable.

For substantial sources, work by coherent sections: read the relevant bodies,
draft their explanation, map the source items to actual anchors, then compare
the prose back to those bodies. Continue through the requested scope before
the final cross-section review. This is working practice, not a new authority
or durable parallel record.

Build a private inventory of the specialized reference's required source items
and the important claims in supplied material. Account for each item in the
document's compact coverage index: represented at an anchor, referenced in an
identified source, or omitted with a reason appropriate to the requested view.
Pending questions and conflicting claims remain visible. Stable IDs come from
the owning source; headings and paragraph order never create new identities.

For each source claim ask whether removing it would change a product decision,
implementation choice, acceptance judgment, or interpretation of a limitation.
If so, preserve it in the body or an explicit source reference. Summaries must
retain exceptions, thresholds, exclusions, rejected alternatives that explain a
tradeoff, and the difference between an observation, an assumption, and a
decision. A long input is a reason to extract carefully, not to silently trim
the difficult parts. Do not duplicate an entire domain or architecture merely
because it is a source.

## Write for the reader's decision

Use the owner's language and the project's established terminology. Explain
the product and its behavior in connected prose; use tables, concrete flows,
or small diagrams when relationships are easier to understand that way.
Choose structure from the actual content, not an obligatory chapter list.
Keep internal identities in source/coverage details unless the reader needs
one to distinguish a requirement. Explain technical choices only to the extent
they affect a decision. Do not turn the body into a field dump, questionnaire,
chat transcript, or list of instructions to the next Agent. Keep the prose
neutral and concrete; avoid promotional claims, decorative headings, stock
conclusions, and conversational approval requests inside the document.

State real tradeoffs, what remains unknown, and what a downstream reader may
rely on. Do not add unsupported capabilities, people, numbers, measurements,
approvals, or claims about implemented behavior. An honest incomplete draft can
be useful; a polished document must not hide a blocking decision.

## Review content and references separately

First review meaning: does the document preserve the sources, expose material
choices, explain observable outcomes, and supply the depth the next decision
needs? Use the specialized quality questions. Record concrete findings with
their source or document location; a finding must explain its effect and the
decision or correction needed. A review-only request produces findings without
editing the document or its sources. Formatting fixes do not authorize changes
to product meaning. Existing Strixnova semantic-review and confirmation
contracts remain the routes for formal candidates; add no document approval.

Compare in both directions: from each required source item to its explanation
or reasoned disposition, and from each consequential document claim back to
supporting source content. Check who may decide, under which conditions, with
what exceptions and observable consequences. A valid reference does not prove
the sentence attached to it is true. An empty source list of pending decisions
does not prove the reading document is complete. Report unread material and
unfinished coverage as limits; reserve a completeness claim for the scope
actually read, accounted for, and semantically compared.

Then check deterministic facts: source identity and revision, actual status,
file existence, resolvable links/anchors, unknown or repeated references, and
whether every required item has a declared disposition. The Agent understands
the material and writes the body; do not introduce keyword/field-based prose
generation, a narrative intermediate model, or a second semantic record.
Re-read sources before
delivery; if they changed during writing, reconcile against the new material
instead of publishing a view as current on the old basis. Temporary checks may
verify these facts; they cannot score prose, infer missing semantics, or prove
that an omission reason or explanation is correct.

## Update from the owning source

Compare the previous bindings with the sources applicable now. Distinguish:

- **Expression change:** improve the reading view while preserving meaning and
  all source files, decisions, and runtime state.
- **Meaning change:** identify the affected owner of the fact, form or revise
  its existing candidate, and use the existing confirmation/change route. A
  changed paragraph is not an accepted upstream revision.
- **Source change:** update the affected sections and coverage, inspect their
  cross-references, and show which requirements or decisions changed. Keep
  stable identities according to the owning contract; retain retired meanings
  only as clearly historical context, never as current obligations.

If the owner corrects a candidate, revise affected conclusions before continuing
the old plan. If sources conflict or a decision is still pending, show the
conflict and its downstream effect rather than choosing silently. An unchanged
source can keep its existing prose; do not rewrite the whole document for a
local correction. Changing status or unrelated execution progress alone is not
proof that specification meaning changed; apply the specialized binding rules.

When the existing request authorizes a complete reading view or its correction,
fill missing source-backed explanations within that scope. Preserve sound
unaffected prose, but do not defer missing chapters to a new WorkItem or ask for
another authorization merely because the omission is substantial. Only a real
change of source meaning or requested scope needs its owning decision route.

Deliver the actual document path and a compact account of its sources, coverage,
material findings, remaining unknowns, and checks performed. Explain readiness
for the next actual decision, not a generic completion badge. When authorized
to write only a projection, verify that source and runtime files were unchanged.
