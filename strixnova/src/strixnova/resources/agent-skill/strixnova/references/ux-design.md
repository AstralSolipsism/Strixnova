# Form and review an experience that can be implemented

Read this for requested interaction design, a UX specification or UX review, or
when an unresolved user interaction materially changes the direction or plan.
Skip it for a mechanical UI edit, a library/API change without such a question,
or implementation already settled by an adequate design. Work from the target
product's actual requirements and existing design system.

## Establish the experience and its sources

Read the relevant confirmed requirements, current product behavior, target
platform, existing designs and applicable design-system rules. Investigate what
the project can answer before asking. Preserve already decided users, vocabulary,
permissions and business states. A screenshot can show appearance; it cannot
establish hidden interactions, authorization or actual user research.

Choose the material question: completing a task, understanding status, recovering
from failure, finding information, or choosing between genuinely different
interactions. Name the actor, their context and input constraints, the trigger,
the desired observable result, and what they need to know before acting. Do not
turn every page into an independent requirement or reopen settled product choices.

If a decision affects product meaning, authority, irreversible behavior or a
durable architectural boundary, return it to its existing owner. For reversible
local choices within the authorized brief, use a reasoned default and continue.
Only present alternatives when their consequences could change the decision.

## Turn a task into a complete interaction

Trace each material requirement through its entry point, relevant information,
available action, feedback and resulting state. Include the route back to work
after an interruption. Every proposed surface must serve a real task; every
important task must have an attainable path. A screen inventory alone is not
evidence that the experience works.

For each consequential action, specify the applicable cases:

- first use, empty data and loading: what is known, what is pending and what the
  person can do meanwhile;
- success: the observable result and the evidence that permits reporting it;
- denial or unavailable action: the actual rule and a useful next step;
- validation or service failure: retained input, actionable explanation and a
  recovery path that does not silently change the request;
- timeout, offline or stale data: what remains uncertain, how state is reconciled,
  and when retry is safe; and
- repeat actions or concurrent changes: which result wins, whether effects can
  duplicate, and how another actor's work is preserved.

Use only cases applicable to the product. Keep business state distinct from
interface state: a disabled button is not server authorization, a spinner is not
an accepted operation, and a timeout does not establish that nothing happened.
Where API, data, permission or recovery decisions determine the experience, read
[behavior-contracts.md](behavior-contracts.md). Do not hide a missing contract
behind reassuring copy or invent successful execution.

Carry the contract's operation identity, input and resolution rules through
the recovery flow. If an operation is unresolved, a local timer or dismissed
message cannot establish its business outcome or authorize a replacement
write. Re-enable actions only under the contract's stated conditions; retain
the information needed to query or safely retry the original operation.

Specify information priority, labels and action wording where they affect the
task. Inherit existing visual tokens, components and platform conventions; record
the behavioral or visual differences that are actually needed. Cover relevant
keyboard operation, focus after transitions, accessible naming, non-color status
signals, feedback announcement, input alternatives and responsive constraints.
Use applicable project accessibility requirements; do not invent certification.

## Use a prototype to settle a question

A prototype is optional. Build one when exercising a flow or comparing layouts
can settle something that prose would leave uncertain. State the question and
use the smallest runnable artifact that answers it. Reuse existing project tools;
do not install a visual service or create persistent infrastructure by default.

Mark simulated services, sample data and unsupported paths explicitly. Make the
relevant state and outcomes inspectable without exposing implementation detail
to ordinary product users. A useful prototype need not implement the whole
product, but a polished success screen cannot stand in for failure and recovery.
Record what was actually exercised, what the observation changed and what still
needs implementation or real user evidence. Do not call an Agent walkthrough a
user interview or usability study.

Before claiming an implemented flow works, exercise its consequential allowed,
denied and recovery paths against the supplied contract. For asynchronous work,
observe actions and effects before and after delayed responses, repeated input,
and any local timeout, navigation or refresh that can discard recovery context.
Check that the prototype's controls and request behavior
agree with the written design. Use a browser or an appropriate executable test
when available; a minimal simulation proves only the behavior it models. If
execution is unavailable, mark the behavior unverified rather than treating
source inspection or a screenshot as an executed check. Searching source text
for state names or handlers is a structural check, not execution of the behavior.
Correct local defects
within the existing brief and repeat the affected path.

## Review and hand off the result

For an existing design, inspect its actual sources and behavior before proposing
changes. Trace the promised tasks through the design and applicable state cases.
Look for misleading success, stranded input, unreachable recovery, conflicting
permissions, inaccessible controls and visual choices that obstruct the task.
Report the location, source, consequence and useful correction of each finding.
Separate missing evidence from a demonstrated defect; allow a sound design to
have no actionable findings. Recheck corrected designs instead of repeating old
accusations. Review-only authorization does not authorize rewriting the design.

Deliver the requested file or artifact, with source/status references, important
flows, meaningful state/action rules, decided tradeoffs and implementation or
verification gaps. Use the project's existing document shape; two fixed design
files, duplicated personas and exhaustive component catalogs are not required.
Clearly distinguish prototype coverage from behavior specified only in writing.

Product behavior belongs to the product definition; roles and business states
belong to the domain; persistent cross-module choices belong to architecture or
an ADR; this change's interaction and implementation arrangements belong to its
direction and plan. A UX reading document or prototype does not independently
confirm these decisions. Carry material findings into the existing review and
correction route. Strixnova checks references, versions and unresolved state;
the Agent remains responsible for judging the experience.
