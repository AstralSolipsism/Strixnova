# Confirmation and cancellation

## User confirmation

For each ordinary gate, explain the complete stored candidate: the recommended
change and its effect, current facts, engineering reasoning, material tradeoffs,
risks, unknowns and the decision's authorization boundary. Group detail for this
candidate without a fixed heading template. Keep decision-changing information
visible before the question. Use
[cross-artifact-review.md](cross-artifact-review.md) when explaining an
EngineeringPlan or ActualResult.

Do this before the first acceptance question, including a small repair. A list
of goals, scope, constraints and expected examples is the candidate's contents;
it does not replace an explanation of the decision. Contrast the current
observable outcome with the proposed outcome, connect that difference to the
user's need, and explain the material choice and its consequences. State any
decision-changing uncertainty honestly; if none is known, say so briefly without
inventing risks. Do not wait for the user to say they did not understand before
providing this comparison and reasoning.

A request for more detail gets that detail about the same candidate. Reuse
still-valid decisions and do not add a confirmation of whether the explanation
was understood.

The three ordinary gates have different authorization boundaries:

- Direction: authorizes continued investigation and preparation of the
  complete engineering plan. It does not authorize source changes, Git
  delivery, push, release, or deployment.
- Engineering plan: authorizes local implementation and verification under
  that plan. It does not accept the later actual result or authorize Git
  delivery, push, release, or deployment.
- Actual result: accepts only the displayed implementation and verification
  facts and authorizes the repository's local Git delivery steps. It does not
  authorize remote push, formal release, or deployment. It may mechanically
  confirm the exact ImplementationAlignment candidate and adopt it into the
  engineering baseline, but it cannot substitute for independent acceptance
  of ProductDefinition, DomainModel, TargetArchitecture, or EngineeringPolicy.

End with one natural question about accepting the displayed candidate. Let the
user answer in their own words; do not require a password or rejection prefix.
The Agent interprets the later reply in context and records `agent_decision`:
`decision` is `accept` or `request_changes`, and `reason` explains how that reply
applies to this candidate. Keep these fields, `decision_label`,
`candidate_fingerprint`, schema names and card numbers internal.

If the user says the explanation is unclear or asks a follow-up question,
explain the same candidate again in a more suitable way. Do not call `confirm`
and do not change the candidate, WorkItem version, or confirmation binding.
Only a correction that materially changes the candidate is a rejection and
starts revision. “Agreed, proceed” can accept a complete candidate just shown;
“yes, but change the scope first” does not accept the unchanged candidate.
Record an explicit correction as `request_changes`. If a condition or the reply's
target is unclear, clarify only that uncertainty without submitting a decision.
Do not ask again merely because the user chose different wording or punctuation.

A user's answer to an earlier clarification, recommendation, or tradeoff is
not confirmation of the complete candidate formed afterwards. Never call
`confirm` in the same turn that forms, submits, or presents a candidate. Only
after the user accepts or rejects that exact explanation in a later message,
copy the new user message verbatim and submit it with the fingerprint from the
same current action, together with the Agent's interpretation. The program
checks identity, version, state and record structure; it does not determine user
intent or prove that the explanation was clear, the user understood it, or the
candidate is semantically correct. Preserve unknowns rather than making up consent.

The submission shape below is internal. Do not render it to the user:

```json
{
  "candidate_fingerprint": "sha256:...",
  "user_confirmation": "the user's exact later reply",
  "agent_decision": {
    "decision": "accept",
    "reason": "The later reply explicitly accepts the complete candidate just displayed."
  }
}
```

Copy the internal fingerprint mechanically and preserve the full user message,
including whitespace, punctuation and conditions. Do not fabricate or normalize
it, or submit an earlier reply as a new decision for a different gate or changed
candidate. Repeating one reply within the same complete authority bundle follows
the rule below. The current action determines the gate; historical fixed-text
records keep their original contract and are not reinterpreted as new decisions.

## Long-term authority candidates

Do not manually mark an upstream authority candidate `confirmed`. Follow the
CurrentAction dependency order: record presentation of each exact candidate,
submit the eight-perspective Agent review bound to all five content hashes, and
then explain the review bundle in decision-ready language. Keep this bundle
separate from the three ordinary gates. Ask the owner for the per-authority
decisions in one later message, without exposing fingerprints or schema fields.
An explicit acceptance of the entire displayed package can cover all its
candidates. Interpret each candidate's scope separately; if a decision is missing
or unclear, resolve it before submitting the complete bundle.
Submit the complete ordered `decisions` array once; each entry retains its own
kind, internal fingerprint, full verbatim owner reply and `agent_decision`.
When one message explicitly covers the complete package, preserve that same full
message on each entry with its candidate-specific interpretation. Never extract
an agreeable fragment while dropping a condition or correction.

The program atomically rechecks the bundle, writes confirmation metadata, and
stores the post-confirmation hashes. `authority_candidate_snapshot` and
`accepted_candidate_snapshot_verified` prove only that accepted text was not
substituted. Local integration rechecks the same snapshot at the real Git
commit. None of these checks prove semantic correctness. Mechanical
finalization belongs to ApplicationCoordinator through the public `delivery`
entry point; the Agent must not edit authority status, owner, date, or baseline
references by hand.

## Start cancellation

```json
{"reason":"the user's actual reason"}
```

Strixnova reads local Git to determine whether work remains. Clean empty work is
removed safely. Unmerged work pauses for a user decision.

## Decide retained work

Present all three real choices: preserve it where it is, transfer ownership or
location, or discard it. Then submit one of:

```json
{"decision":"preserve","details":{}}
```

```json
{"decision":"transfer","details":{"destination":"..."}}
```

```json
{
  "decision":"discard",
  "details":{"reason":"..."},
  "confirm_discard":true
}
```

Discard is destructive and requires the user's explicit confirmation. Never
set `confirm_discard` merely because the Agent recommends deletion.


For `resume_external_effect`, follow [Resume a recorded effect](replanning.md#resume-a-recorded-effect)
using the original cancellation intent and recorded decision.
