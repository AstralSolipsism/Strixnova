# Make a risky interaction or interface precise enough to implement

Read this when an actual API, data, permission, concurrency, compatibility or
recovery risk needs more detail than the normal direction or plan provides.
Use only the relevant sections. A small local computation or wording change
does not need a new contract document or a tour of every risk category.

Start from the real caller, current interface and owning requirements. Reuse
the project's schema, API description, tests and terminology. Record missing
decisions in the existing plan/review. Technical detail is useful when it changes
implementation, verification or a decision the owner must make.

## Describe an observable operation

Identify the actor, input, preconditions, result and persistent effects. Distinguish
an invalid input, absent resource, forbidden action, business rejection, conflict
and unavailable dependency where the existing interface distinguishes them.
State which effects are absent or retained on each outcome. Respect documented
error precedence and information-disclosure rules instead of choosing new ones
silently. An HTTP status or exception type alone is not a complete behavior.

For reads, cover relevant filtering, ordering, pagination and snapshot/freshness
semantics. For writes, identify the resource or operation identity and the point
at which success is known. A caller that times out may be uncertain whether the
effect committed; describe reconciliation using the actual supported interface.

## Resolve the boundaries that can change the outcome

| Relevant risk | Decisions and evidence to make explicit |
| --- | --- |
| Permission | Where caller identity comes from, which component enforces the rule, affected resource scope, denial effects and permissible disclosure. A hidden control or client-provided role is not proof of trusted authorization. |
| Retry and duplication | Whether repeating the operation is safe, how the same attempt is identified, what happens when the same key carries different input, and how the caller discovers an uncertain result. Do not add retries around a non-idempotent effect by assumption. |
| Concurrent change | What may change between read and write, the version/condition or other existing coordination mechanism, conflict behavior, preserved work and retry/review path. A last-write policy is a product choice when it can discard user intent. |
| Multi-step or external effect | Commit boundaries, partial outcomes, compensation or reconciliation, observable progress and an operator path for cases that cannot be automatically repaired. A local rollback cannot undo an already sent external action. |
| Data and compatibility | Accepted old/new representations, missing versus null/default behavior, valid transitions and the actual caller versions that must coexist. Specify migration or fallback only when this change needs it. |
| Recovery and retention | What can be restored, from which evidence/version, who may perform it and what is permanently lost. Avoid promising recovery merely because a backup or undo button exists. |

Leave an inapplicable row out. Reuse an existing policy when it settles the
choice. If a consequential choice remains unknown, explain its concrete effect
and request that decision; do not fill it with an arbitrary timeout, retention
period, security level, compatibility window or success-rate target.

## Connect the contract to verification

Check a proposed correction against both a request the contract must allow and
one it must reject. For identity, uniqueness and retry rules, first state the
actual namespace (for example identity, interface, resource and key), then check
request-content equality within that namespace. Equal text in two independent
namespaces is not automatically a collision. Conversely, an explicitly global
uniqueness rule cannot be silently changed to per-user uniqueness. Preserve valid
requests and documented rejection conditions together. If a stronger constraint
is useful, label it as a proposed contract change for its owner, not as a required
implementation fix. Do not invent that choice when the adopted contract settles it.

For each material promise, choose an observation that would distinguish it from
the suspected wrong behavior. Useful examples include a denied request leaving
the resource unchanged, an identical retry producing one effect, a stale write
preserving another actor's update, or a partial external action being reported
without a false rollback claim. Derive expectations from requirements and the
actual interface, not the implementation's own calculation.

An in-process fake can exercise a caller's reaction to a conflict; it does not
prove the real service performs the atomic version check. Keep the required
integration or operational evidence visible, and do not treat a mock, prototype,
schema validator or green unit suite as security or concurrency certification.
Use [implementation-practices.md](implementation-practices.md) only if choosing
the test boundary requires its additional detail.

Review the actual contract and implementation together when requested. A test
that lists several requirement IDs may assert only one promise. Report the
specific uncovered condition or contradictory effect, allow valid independent
designs, and avoid generating findings merely because a preferred pattern is
absent. A correction to accepted product behavior returns to its owner; a local
implementation defect is repaired within the current authorized work.
