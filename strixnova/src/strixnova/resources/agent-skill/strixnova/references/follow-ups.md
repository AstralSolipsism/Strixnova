# Carry explicit deferred work into its later result

Read this when a result leaves a real promise for later, a new direction takes
responsibility for an earlier problem, or the owner asks what remains pending.
Use existing WorkItems, result records and confirmations. The program does not
infer promises from prose, schedule Agents, or create a separate issue system.

## Leave an explicit, reviewable disposition

Fix current-scope issues in the current WorkItem. For a remaining limitation,
distinguish a consciously accepted limitation from a promise to act later.
Only these explicit dispositions need `follow_up_items` in the actual result;
ordinary caveats about evidence or scope can remain in `limitations`.

```json
{
  "follow_up_id": "FOLLOWUP-0123456789ABCDEF",
  "limitation_refs": ["limitations[0]"],
  "disposition": "deferred",
  "reason": "The owner chose to measure capacity before the next expansion.",
  "responsible_party": "Project maintainer",
  "due_on": null,
  "review_condition": "Before the next capacity increase",
  "completion_criteria": "Measure the agreed workload and address the original limit."
}
```

A `deferred` entry needs a responsible party, a date or review condition, and
completion criteria. `due_on` uses YYYY-MM-DD; queries compare it with the local
machine's date. Business conditions require Agent investigation and judgment.
Use `accepted_limitation` when the owner accepts the remaining limitation and
ends follow-up; the four scheduling/responsibility fields must then be null.
One limitation cannot have competing dispositions in the same result. Generate
an opaque stable ID, and retain it while revising that unaccepted candidate.
After acceptance, its identity cannot be reused in another result.

Explain the disposition at the existing actual-result confirmation. Before
acceptance it is only a candidate. No additional confirmation point or immediate
child WorkItem is required. A later result never rewrites that original decision.

## Read and take responsibility for existing work

```text
strixnova status --project-dir <project> --follow-ups --limit 25
strixnova status --project-dir <project> --follow-ups --include-closed
strixnova status --project-dir <project> --follow-ups --limit 25 --cursor <next_cursor>
```

This route reads local accepted records without requiring Git adoption or a
CurrentAction. It initializes nothing. Pages contain at most 100 entries and
bind the snapshot, filters, page size and query date. A changed snapshot requires
a new query. `project.follow_ups` is also available as an on-demand record when
forming a direction or assessment. Do not preload the full list for every action.
The view covers explicit accepted records only; it does not invent obligations
from old versions or treat absence of records as proof that no debt exists.

When an authorized WorkItem takes responsibility, its direction uses the existing
`follows_up` relation and adds `follow_up_refs`. Copy the returned reference:

```json
{
  "target_work_item_id": "WI-20260910-EXAMPLE",
  "relation_type": "follows_up",
  "reason": "Address the exact original capacity limit.",
  "follow_up_refs": [{
    "work_item_id": "WI-20260910-EXAMPLE",
    "result_version": 6,
    "follow_up_id": "FOLLOWUP-0123456789ABCDEF"
  }]
}
```

The example identities and versions are illustrative. The original result must
be accepted and the entry still open. A broad relation without precise references
does not claim to resolve its target's limitations. Use the same direction route
to add this responsibility to an existing WorkItem when appropriate.

## Report the precise later outcome

Read the original entry again before presenting the later result. Submit one
`follow_up_results` entry for every precise reference in the confirmed direction:

```json
{
  "follow_up_ref": {
    "work_item_id": "WI-20260910-EXAMPLE",
    "result_version": 6,
    "follow_up_id": "FOLLOWUP-0123456789ABCDEF"
  },
  "expected_version": 7,
  "outcome": "resolved",
  "rationale": "The recorded measurements address the original agreed limit.",
  "evidence_refs": ["delivered_outcomes[0]"],
  "limitation_refs": []
}
```

Copy the entry's current version into `expected_version`. Allowed outcomes are
`resolved`, `partially_resolved`, `still_open`, and `accepted_limitation`.
Resolution needs actual evidence. Every other outcome needs a precise reference
to the remaining result limitation. The program checks references and recorded
versions, not whether the Agent's causal or business judgment is correct.

Only acceptance of this later result changes the derived disposition. A completed
or cancelled child alone never closes the original entry. If another accepted
result intervenes, `follow_up_conflict` or `follow_up_not_open` rejects the stale
candidate before either record changes. Read the updated evidence and use the
existing correction/replanning route to revise and re-present the candidate.
