# Prepared input and selected material

Use these product interfaces to carry mechanical fields. They do not choose
semantic outcomes, grant authority, or replace reading the actual implementation.
The Python interface is `LocalHostAdapter.prepare_input`, `preview_input` and
`apply_input`; a caller can keep the returned context directly without shell JSON.

Run examples from the management project root. Keep transport files in ignored
`.strixnova/artifacts/agent-inputs/` so they cannot become unplanned source changes.
The program creates needed parent directories and refuses to overwrite files; use
a new name for a new round, or an ordinary scratch directory outside the project.

## Prepare once, submit judgments

```text
strixnova action prepare --work-item-id <ID> --output .strixnova/artifacts/agent-inputs/action-context.json
strixnova action inspect --source .strixnova/artifacts/agent-inputs/action-context.json --pointer /checklist --readable
strixnova action preview --context .strixnova/artifacts/agent-inputs/action-context.json --input @.strixnova/artifacts/agent-inputs/answers.json --output .strixnova/artifacts/agent-inputs/input-preview.json
strixnova action apply --context .strixnova/artifacts/agent-inputs/action-context.json --input @.strixnova/artifacts/agent-inputs/answers.json
```

The program captures the exact action, WorkItem version, confirmation fingerprint
and required identities. Inspect the prepared contract and checklist. Submit only
new root `fields` and per-item `answers`; do not copy the complete template back.
The existing command route and validators are used automatically. Reuse the returned
`next`. `prepared_input_stale` requires reviewing a newly prepared context; do not
reattach an old judgment to a new binding. Saved contexts are disposable transport
snapshots, not a second authority, approval receipt, or proof of actual reading.

Each ActualResult checklist row contains fixed identity, its source, input schema
and pending fields. Missing answers remain missing. Supply effect, outcome, status,
reason, evidence, deviations and limitations explicitly. For equivalent judgments,
`groups` may contain `items` listing exact checklist IDs and a shared `values`
object; the program expands only those selected items. It never fills omitted rows
with `realized`, `satisfied` or `supported`.

Select result evidence using the prepared `evidence_catalog`, or typed references
such as `{"kind":"receipt","key":"VR-..."}` and
`{"kind":"delivered_outcomes","key":0}`. The program serializes the wire reference.
Planned sources such as `direction` or `SRC-*` do not become actual result evidence.
Availability and identity do not prove a reference supports a claim.

`preview` is optional read-only preflight. It reports independent schema errors and
unavailable result references; structurally complete results also use the same
result checks as submission. It cannot prove semantic correctness or guarantee a
later write: apply rechecks currentness and the normal effect/authorization gates.
Read the saved preview before interpreting `ok`; it is not owner acceptance.

## User messages and confirmation

When the caller already has the original user message, pass it directly through
`user_message` in the Python API. For an existing source file supplied by the user
or host, add `--user-message-file` to `action preview` and `action apply` (also
supported by `confirm` and `authority`). Submit the explicit `agent_decision`
separately. One message can be expanded into a complete authority decision bundle;
each selected authority still needs its own interpretation and scope.

Preserve original whitespace, line endings, punctuation and conditions. Do not
have the model write a purported original-message file, summarize the reply, or
label an arbitrary file as authenticated owner input. The CLI cannot retrieve a
chat message. If no original source is available, disclose that host limitation;
it does not permit inferred consent. The normal later-message, exact-candidate
and owner-explanation requirements remain in force.

## Read a selected scope without moving cursors

```text
strixnova action records --work-item-id <ID> --record engineering.plan --record engineering.execution_context --output .strixnova/artifacts/agent-inputs/selected-material.json
strixnova action inspect --source .strixnova/artifacts/agent-inputs/selected-material.json --pointer /records --readable
```

Choose available references based on the current question. The program assembles
only those references, rechecks their version and bytes, and saves UTF-8 material
outside the transcript. Inspection bounds output and exposes `unexpanded` pointers.
`complete=false` means the selected display still omits bodies. Read needed bodies
from the saved material; do not treat an index or truncated host view as full context.
The ASCII machine transport and canonical hashes remain unchanged.

## Batch presentation and explicit revisions

With already authored, authorized candidates ready, use `action authorities` with
the frozen `--context` and an ordered, explicit repeated `--kind` list. The program
retains each normal presentation event and version. It stops before an unavailable
candidate, review, or owner decision and reports the completed prefix. Read that
report before continuing; registration does not mean the owner saw or understood it.

For a revised direction or assessment, inspect `revision_bases`. Submit a `revision`
with explicit `kind`, `keep_rest: true` and JSON-pointer `changes` using `add`,
`replace` or `remove`. This is the Agent's explicit decision that unchanged content
remains applicable. The program retains the exact base, increments assessment
revision and carries the current accepted direction binding. It emits a complete
candidate for normal validation and fresh confirmation; it never inherits owner
acceptance. Existing alignment preparation/writes still own mechanical YAML
metadata updates; do not hand-edit confirmation metadata.

`alignment prepare --output .strixnova/artifacts/agent-inputs/alignment-context.json` saves its binding. Use
`alignment inspect --prepared .strixnova/artifacts/agent-inputs/alignment-context.json` and
`alignment write-candidate --prepared .strixnova/artifacts/agent-inputs/alignment-context.json --input @.strixnova/artifacts/agent-inputs/decisions.json`
without copying `preparation_ref`, WorkItem ID or version. External capture still
requires `--authorize-external`; use its `--output` to save the updated context.
Never substitute a latest reference when applying decisions about an older one.

## Verification facts and exact test identities

For `assess_verification_change`, prepare with `--receipt-id` selecting a listed
pending receipt. The program carries command and receipt identity and supplies
`verification_observations`: captured changed, unchanged and uncaptured paths,
execution-time changes, recorded limitations and dependency evidence. Outside
captured scope remains unknown. Decide relevance, assertion sufficiency, external
dependency effects and retest necessity explicitly; exit zero or equal captured
bytes cannot supply `needs_retest: false` for you.

Use `action cases --context .strixnova/artifacts/agent-inputs/action-context.json --command-id <ID> --report .strixnova/artifacts/agent-inputs/collection.json --output .strixnova/artifacts/agent-inputs/case-preflight.json`
to inspect an existing test report. Root and exact collected node IDs are checked
together; unmatched bindings are reported without fuzzy replacement or changing
the approved command. No collection command runs here. If a report is unavailable,
collection needs separate explicit execution authorization because pytest collection
can execute code. A caller-provided report is preparation material, not a verified
execution receipt or proof that its assertions satisfy the intended behavior.

Use `alignment inspect --prepared .strixnova/artifacts/agent-inputs/alignment-context.json --output .strixnova/artifacts/agent-inputs/alignment-material.json` to assemble the selected preparation without copying cursors. Inspect the saved `/items` with `action inspect`; this does not prove the items were reviewed.
