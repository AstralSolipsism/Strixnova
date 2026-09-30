# Explain an exact domain model as a readable document

Read this only when the user asks to organize, review, or update an existing domain model
into a complete, continuously readable document. Apply the shared source,
preservation, writing, review, and update rules in
[artifact-documentation.md](artifact-documentation.md). The view explains the
domain model in continuous prose, with source and coverage details kept alongside
the explanation.

## Read the domain-specific sources

1. Read the confirmed product definition for purpose, users, problems, intended
   outcomes, and the complete product capability inventory.
2. Bind one exact domain-model revision. Traverse its collection catalog, every
   current Fact, explicit dependencies, necessary closure, and historical lineage.
   Do not infer domain meaning from current implementation names.
   Read each fact's actual definition and constraints, not just its catalog
   title. Preserve its kind: an actor, entity, context, rule, event, and value
   object are not interchangeable. Derive lifecycle transitions and decision
   rights from their owning facts rather than familiar engineering patterns.
3. Inspect the project's writing style, document policy, and index. Earlier prose
   can guide expression but cannot override the selected formal domain facts.
4. If implementation gaps need explaining, cite target architecture and actual
   implementation alignment separately from what the domain itself means.

## Organize the domain's meaning

Adapt the chapter order to actual content. A complete view normally explains:

- project purpose, scope, and responsibility boundaries;
- participants, responsibilities, and decision rights;
- product capabilities and their bidirectional domain-capability mapping;
- normal, blocking, correction, and cancellation scenarios for each capability;
- entities, value objects, lifecycles, and domain events;
- rules, invariants, and what they protect;
- bounded contexts, context relationships, and external-system responsibilities;
- ubiquitous language, retired concepts, and evolution lineage;
- sources, full coverage, reverse references, unknowns, and limitations.

Explain relationships before details that depend on them. Preserve each claim's
decision rights, scope, evidence boundary, and uncertainty. Use the owner's
language with explanations of necessary foreign terms. Internal IDs belong in
traceability detail unless needed in the main explanation.

Account for every selected current Fact and the required product/domain mapping,
with explicit lineage handling for retired facts. Keep a reverse index so the
reader can locate each fact without turning the body into fields. On update,
compare the bound revisions, change affected sections, and recheck relationships
and the index. Update the project's document index when applicable. Deterministic
checks can prove references and declared coverage; semantic adequacy remains a
review judgment under the shared documentation rules.
