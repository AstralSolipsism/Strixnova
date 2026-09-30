# Recorded work and Strixnova maintenance

## First installation

Use the matching offline bundle's README and `install.ps1` or `install.py`.
Windows x64, Python 3.12 and Git are prerequisites. The installer verifies the
bundle and creates an isolated managed runtime with its locked dependencies.
It does not install into system Python or change PATH, host settings, plugins,
hooks or model credentials.

Choose an installation root separate from the business project; neither may
contain the other. Each installation root belongs to one project. Use the
returned `runtime.entrypoint`, `runtime.python_path` and `runtime.skill_path`.
An exact retry can reuse the selected runtime. A different selection or existing
unselected project data requires explicit maintenance. Installation does not
create a WorkItem or adopt project authorities.

Copy the Skill only to a specified directory with `--skills-dir`. Replacement
requires `--replace-skill`; keep its backup. Reload the host through its own
mechanism. `host_loaded_verified=false` means copied files have not established
actual loading. Form the business project's authorities from its requirements;
do not copy Strixnova's own engineering documents into that project.

## Read recorded work

Use `strixnova history` independently of `strixnova next`. It reads recorded
facts without applying today's engineering rules, advancing a WorkItem or
initializing an absent database. Active, completed and cancelled work is readable
within the current declared storage contract.

```text
strixnova history --project-dir <project> --query <title-text> --limit 25
strixnova history --project-dir <project> --state completed --state cancelled
strixnova history --project-dir <project> --work-item-id <ID>
strixnova history --project-dir <project> --work-item-id <ID> --record result --record delivery
```

`--query` searches titles literally. `--since` is inclusive and `--until` is
exclusive. An omitted timezone is UTC. `--limit` is 1–100. Continue with the
returned `next_cursor`, the same filters and page size. A changed snapshot
requires a fresh query; do not combine pages from different revisions.

| Record | Meaning |
| --- | --- |
| `request` | Original request and title |
| `result` | Stored result, acceptance, superseded deliveries and cancellation |
| `decisions` | Recorded direction, engineering and owner decisions |
| `candidates` | Presented candidates and their recorded disposition |
| `events` | Original event references |
| `verifications` | Receipt references, including failed and unrun work |
| `delivery` | Local Git delivery and exact commit availability |
| `artifacts` | Long-lived references bound to this result's delivery events |
| `relations` | Declared WorkItem relations |

Use returned `record_ref` values for `event:<sequence>`, `candidate:<sequence>`,
`verification:<receipt-id>` and `artifact:<index>`. Continue paged collections
separately. Read original outputs using `output:<receipt-id>:stdout`,
`output:<receipt-id>:stderr` or `output:<receipt-id>:cases`. `--offset` and
`--bytes` select a bounded range, at most 1 MiB per call. Copy the returned
continuation rather than combining ranges across changed content. Exact bytes
are base64 encoded; display text alone is not an exact copy. Arbitrary file paths
are not accepted by this interface.

Explain what was requested, accepted, delivered and verified, and what evidence
remains available. Keep drafts, rejection, cancellation and superseded results
distinct. Missing files or Git objects do not erase the recorded facts. A hash
mismatch differs from absence. `unanchored` means no execution-time digest
establishes the original bytes; it must not be described as verified evidence.

Candidates and decisions come from their recorded normalized facts. A candidate
event missing those facts is incomplete data. Do not reconstruct a decision from
today's parser, borrow another result's final commit, or substitute a current
working-tree file for the artifact at its recorded commit.

## Upgrade Strixnova itself

The `strixnova upgrade` route maintains the program, bundled Skill and existing
data for one named project. It accepts the current declared data formats and
does not convert unsupported formats. Publishing or deploying the business
application belongs to `strixnova activity`. Maintenance does not require a
WorkItem and must not scan other projects or start a background updater.

The initial Authority, activity and evidence formats are each v1. WorkItem
revisions, format versions, program versions, build hashes and Skill hashes are
different identities. An equal development-version string does not establish
equal program or Skill content.

1. Read `strixnova upgrade runtime` using the exact caller. For an installation
   change, identify the target wheel, local locked dependency wheelhouse, source
   Python and dedicated installation root outside the project.
2. Run `strixnova upgrade check --project-dir <project> --target-wheel <wheel> --installation-root <installation> --source-python <source-python> --builder-python <builder-python> --wheelhouse <wheelhouse>`. Source selection
   may be omitted when the installation already records it. Without installation
   options, the check concerns data under the current caller; it does not prove
   a program upgrade. The check is read-only.
3. Explain the exact project, source/target identities, protected contents,
   maintenance impact and blockers. Continue within existing concrete
   authorization; obtain only a missing material decision. Resolve unclosed
   operations before switching. Never edit format markers to bypass rejection.
4. Save the returned `upgrade` object as UTF-8 JSON and pass it unchanged to
   `strixnova upgrade apply --project-dir <project> --input @plan.json`.
   Maintenance prepares the destination, drains writes, backs up consistent data,
   verifies copies and records each switch. If source facts changed, get a new
   check instead of editing the stale plan.
5. Read the result and, when needed, `strixnova upgrade status --project-dir <project> --upgrade-id <ID>`. Run the selected entry through `strixnova upgrade run --project-dir <project> --installation-root <installation> -- history --work-item-id <ID>`. Load its matching Skill in a fresh or reloaded host
   session. Report `host_reload_required`; matching files alone do not prove
   that a session loaded them.

Do not move a prepared venv. It is created at its final path. Dependencies come
from the target lock and named local wheelhouse. Installation failure preserves
the prior runtime. Maintenance uses `strixnova upgrade validate` to exercise
the actual target entry before reopening the project. Its bounded read trial
cannot authorize business writes. An `aborted` attempt made no target-data
replacement; its own temporary guards may have been removed while preserving
later facts. Inspect the failure and obtain a new check.

## Recover an interrupted attempt

Read status and copy the exact upgrade identity. Use `strixnova upgrade recover --project-dir <project> --upgrade-id <ID> --mode resume` only when `recovery_modes`
offers it. `--mode restore` restores the verified original combination when safe.
Repeated recovery remains bound to the same attempt.

Do not delete maintenance markers, backups, database sidecars or intermediate
files to unblock a command. An exited process does not prove completion. Data
under `.strixnova/artifacts/maintenance/<upgrade-ID>/` protects partial switches
and is not rebuildable cache. Restore must refuse to overwrite new business
facts, evidence or protected-file changes. A locked file, full disk, damaged
database, missing backup or hash mismatch is not permission to initialize an
empty project or to claim that restoring the program restored its data.

## Resolve an unclosed execution

Managed writes and installation preparation record a start. A process that exits
without its end record remains unresolved; a released lock or absent parent does
not prove its descendants stopped. `cleanup_failed` and
`verification_execution_unclosed` require investigation, not a fabricated receipt
or an immediate repeat of the command.

Read `strixnova upgrade operations --project-dir <project>`. Investigate the
exact operation and effects, then read `strixnova upgrade stop-evidence-contract`.
Copy `stop_evidence_scope` from that operation's returned record into genuine
external stop evidence. Submit it through `strixnova upgrade recover-operation --project-dir <project> --operation-id <operation-ID> --input @stop-evidence.json`.

Recovery retains the start and evidence. It does not replay the command,
manufacture a result or accept engineering meaning. The program checks binding
and file integrity; `external_truth_machine_proven` remains false. Insufficient
evidence leaves the operation unresolved. The same rule covers interrupted
venv/pip preparation before a business database exists.

For a WorkItem effect, keep the repository and intent returned by
[Resume a recorded effect](replanning.md#resume-a-recorded-effect). Runtime
maintenance uses the separate route above.
