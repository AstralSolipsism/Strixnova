# Installed implementation-alignment workflow

Use this workflow only while the current WorkItem is in `implementing` and the
focused confirmed EngineeringPlan slice owns or continues exactly one
`domain_alignment` operation. The slice must also plan the alignment root,
its four subordinate ledgers, and the project engineering baseline. This
workflow observes implementation facts and writes a recoverable draft. It
does not confirm or adopt an authority, change the WorkItem version or state,
or prove semantic correctness.

Finish the intended code and alignment writes before the focused slice's last
formal verification and its post-run assessment. Alignment describes the actual
implementation supported by applicable evidence; it is not a second progress
ledger for awaiting a final verification receipt. Record development evidence
honestly, keep final receipt status in the existing verification records, and do
not mark implementation incomplete merely because its final receipt is pending.
The last assessment can close the slice, so it is too late then to prepare a
still-needed alignment write. A real remaining implementation gap still blocks
completion; do not hide it or invent a retest flag to reopen a completed slice.

## Public interface

The installed review and write interface has four commands:

```text
strixnova alignment prepare
strixnova alignment inspect
strixnova alignment capture-external
strixnova alignment write-candidate
```

`strixnova alignment gc` is a separate owner-directed cache-maintenance command;
it is not part of the review/write sequence and does not use WorkItem binding
arguments.

Use the common binding arguments on every call:

```text
--work-item-id <ID> --version <current-version>
```

Omit `--project-dir` in the project root. Add it only when operating elsewhere.
Use a temporary UTF-8 `@file` for non-ASCII input, as described in the main
Skill. Parse the one-line stdout object and use the value under `alignment`.
Never inspect installed Strixnova source or tests to reconstruct a contract.

## 1. Prepare a content-addressed observation packet

For an existing confirmed alignment, send only a new revision identity and the
exact current revision it supersedes:

```json
{
  "schema_version": "strixnova.implementation-alignment-preparation-request.v1",
  "alignment_revision_id": "ALIGNREV-<16 uppercase hex>",
  "supersedes_revision_id": "ALIGNREV-<current 16 uppercase hex>"
}
```

Do not repeat existing observation scopes, governed source scopes, or artifact
paths. Strixnova reads and preserves them. If the existing alignment is already
a draft, omit `--input`; Strixnova continues that exact draft. A confirmed or
otherwise non-draft revision requires the minimal request above.

Only the first alignment for a project needs the three additional fields
below. Their exact nested structures come from
`strixnova.project-implementation-alignment.v1`:

```json
{
  "schema_version": "strixnova.implementation-alignment-preparation-request.v1",
  "alignment_revision_id": "ALIGNREV-<16 uppercase hex>",
  "supersedes_revision_id": null,
  "observation_scopes": [],
  "governed_source_scopes": [],
  "artifact_paths": {
    "source_ownership": "<planned relative path>",
    "actual_dependencies": "<planned relative path>",
    "target_responsibilities": "<planned relative path>",
    "deviations": "<planned relative path>"
  }
}
```

The arrays are shown only as structural placeholders; a real first request
must contain at least one valid observation scope and governed source scope.

Run:

```text
strixnova alignment prepare --work-item-id <ID> --version <N> --input @request.json
```

The result returns:

- `preparation_ref`: the immutable content-and-path binding for later calls;
- required and optional decision counts;
- observation coverage and whether planned external capture is available or
  required;
- `semantic_content_machine_proven: false`.

If `external_capture_required` is true, keep the reference but perform section 2
before inspecting it; inspect only the updated preparation returned by capture.
Otherwise put the complete returned reference in `inspection.json`:

```json
{"preparation_ref":{}}
```

Run the logical inspection interface:

```text
strixnova alignment inspect --work-item-id <ID> --version <N> \
  --input @inspection.json
```

Review the returned `items` in order. Context records contain the frozen
binding, authority identities, architecture modules/relationships/constraints,
existing alignment context, governed scopes, observation coverage and provider
receipts. Every `semantic_decision` record contains one exact decision contract.
When `next_cursor` is not null, repeat the same command with
`--cursor <next_cursor>` until it becomes null. Treat the cursor as opaque and
do not skip pages. The default page is bounded; use `--limit` only to make it
smaller or, when context permits, up to the public maximum. Do not read or edit
`.strixnova/artifacts/implementation-alignment`; its content-addressed manifests,
components and paging are private implementation details.

## 2. Capture a planned external provider only when needed

Built-in static providers run during `prepare`. Rust, Go, TypeScript and other
built-in-supported scopes may therefore already be complete. C#, C++, an
unknown language, or a configuration that needs a compiler-specific analyzer
can remain `partial`, `unavailable`, or `failed` unless the confirmed
EngineeringPlan contains an exact external provider plan.

When `external_capture_required` is true, and only when the confirmed plan
contains that provider, submit the unchanged preparation reference:

```json
{"preparation_ref":{"schema_version":"strixnova.implementation-alignment-preparation-ref.v1","artifact_kind":"preparations","artifact_id":"ALIGNPREP-<16 uppercase hex>","path":"<returned path>","content_sha256":"<returned sha256>"}}
```

Run:

```text
strixnova alignment capture-external --work-item-id <ID> --version <N> \
  --authorize-external --input @capture.json
```

The flag authorizes this call only. The CLI deliberately accepts no provider
argv, executable, material hash, timeout, glob, or process policy. The argv and
SHA-256 identity of every executable, entry script, config, and supporting file
must already be in the owner-confirmed EngineeringPlan. Strixnova rechecks those
bytes immediately before process start and records them in the receipt. Use only
the updated `preparation_ref` returned by this command, put it in
`inspection.json`, and inspect from the first page. An old cursor is not valid
for the updated preparation.

Do not invent an external provider merely to turn incomplete coverage into
`complete`. Honest incomplete coverage remains usable evidence for a draft.

## 3. Supply only semantic decisions and write the draft

For each inspection item whose `record_kind` is `semantic_decision`, use its
`value` as the decision-catalog entry:

- supply every item with `required: true`;
- omit an optional item when its `facts.previous` semantics remain correct;
- supply an optional item only when changing those semantics;
- use the exact `decision_ref` and exactly the fields listed in
  `required_value_fields`;
- base meaning on code, project documents, user discussion, and engineering
  judgment—not on filenames alone;
- for a `remove_*` item, explicitly set `accepted: true` and provide a
  non-empty `rationale`.

Strixnova fills observed identities, paths, hashes, relation facts, authority
references, receipts, code version, and revision binding. Do not repeat or
alter those mechanical facts in a decision value.

Submit one payload:

```json
{
  "schema_version": "strixnova.implementation-alignment-candidate-decisions.v1",
  "preparation_ref": {},
  "decisions": [
    {
      "decision_ref": "ALIGNDECISION-<16 uppercase hex>",
      "value": {}
    }
  ],
  "deviations": [],
  "unresolved_items": []
}
```

The empty objects above are placeholders. Copy the complete returned
`preparation_ref`; each decision value must exactly match its catalog fields.
Use the formal v4 deviation and unresolved-item structures when either list is
non-empty.

Run:

```text
strixnova alignment write-candidate --work-item-id <ID> --version <N> \
  --input @candidate.json
```

Strixnova rechecks the WorkItem, confirmed plan, focused slice, worktree, packet
hash, governed file set and bytes, and the existence plus byte hash of all six
candidate targets captured by `prepare`. Every governed source file must match
exactly one governed scope. It then journals the alignment root, four ledgers,
and baseline as one recoverable file transaction and validates the complete
candidate. A failed final validation restores every previous file. A process
crash or power interruption before commit is recovered from the durable journal
on the next alignment entry; a concurrent third-party edit is never guessed or
overwritten.

Interpret the result narrowly:

- `candidate_valid: true` proves that the written draft passes deterministic
  contracts and cross-file checks;
- `complete_alignment: true` additionally means observation coverage is
  complete, owned source is aligned, dependencies are passing, target
  responsibilities are implemented, and no deviation or unresolved item
  remains;
- `candidate_status: draft` means it is neither confirmed nor adopted;
- `semantic_content_machine_proven: false` always means the program has not
  proven the Agent's domain or architecture judgment.

Continue with the existing verification and actual-result workflow. Do not
call `strixnova confirm` merely because the candidate is valid. Implementation
alignment adoption remains bound to the independently accepted actual result.

## Recovery and stop conditions

- On `alignment_preparation_stale`, discard the old packet and run `prepare`
  against the current WorkItem and worktree.
- On `alignment_governed_scope_ambiguous`, make governed source scopes disjoint;
  do not rely on list order to choose ownership.
- On `alignment_transaction_recovery_failed`, stop. Preserve the transaction
  directory and resolve the reported file conflict before retrying.
- On `alignment_candidate_paths_unplanned`, do not broaden the write. Replan so
  the focused slice explicitly owns all six candidate paths.
- On `alignment_revision_request_required`, create the minimal new-revision
  request; do not edit confirmation metadata.
- On `external_observation_not_planned`, keep honest incomplete coverage or
  replan the provider. Do not pass an ad hoc command.
- On a semantic decision error, inspect the same preparation again and correct
  only the listed decision.
- Stop and request a real project decision when code and documents do not
  resolve ownership, architectural classification, responsibility status,
  deviation acceptance, or a material unknown.

Preparation, capture, and component files are immutable and deduplicated. Never
delete their directories manually. When the project owner explicitly asks to
reclaim local cache space, first run:

```text
strixnova alignment gc --dry-run
```

This only reports components unreachable from every retained preparation and
capture manifest. It never removes preparations, captures, transactions, or
long-lived authorities. If the owner accepts that exact preview, submit its
`orphan_set_sha256` without alteration:

```text
strixnova alignment gc --apply \
  --expected-orphan-set-sha256 <orphan_set_sha256>
```

Any changed orphan set is rejected and requires a new dry run. Do not invoke
either maintenance mode during ordinary alignment work unless the owner asked
for cache maintenance.


Use [implementation-alignment-artifact-contracts.md](implementation-alignment-artifact-contracts.md)
for repository-qualified observation fields and indexes. The baseline layout is
in [authority-authoring.md](authority-authoring.md); do not reconstruct either
contract from an older observation.
