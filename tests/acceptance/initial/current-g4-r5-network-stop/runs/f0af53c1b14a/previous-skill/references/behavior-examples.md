# Behavior examples and their verification

Read this when forming a direction that changes behavior observed by users or
external callers, or when the current plan contains behavior examples. Use the
existing direction, plan, verification and result records for their storage,
execution evidence and acceptance.

## Establish the expected behavior before choosing tests

For each acceptance criterion in strixnova.direction-decision.v1, write a
behavior object. Use applicability required with examples for observable
behavior changes. Use not_applicable with a specific reason for pure prose or a
mechanical change that preserves behavior. Use undetermined with a reason only
in a blocked draft; it cannot enter direction confirmation. The Agent decides
applicability and sufficiency; the program checks structure and references.

Derive expectations from the request and its actual requirement or constraint,
before inspecting which tests happen to pass. Cover the happy path and relevant
denial, boundary or recovery examples without inventing scope. For example:

~~~json
{
  "applicability": "required",
  "examples": [{
    "example_id": "DIREX-0123456789ABCDEF",
    "title": "Insufficient stock leaves inventory unchanged",
    "given": ["Available stock is 2 units"],
    "when": "A caller reserves 3 units",
    "then": ["The request is rejected", "Available stock remains 2 units"],
    "basis_refs": ["direction.requirement:DIRREQ-0123456789ABCDEF"]
  }]
}
~~~

Store this under its owning acceptance criterion's behavior field. An example
may reference that acceptance's own requirements and current direction
constraints, not unrelated requirements or arbitrary test files. Create a
random DIREX- identity with 16 uppercase hexadecimal characters, scoped to the
WorkItem. Preserve it for clarification, replace it when meaning changes, and
never revive a retired identity. Explain examples with everyday language in the
existing direction card; users need not maintain identifiers or test syntax.

## Give every example a concrete verification arrangement

The strixnova.engineering-assessment.v1 assessment arranges each
direction.example:DIREX-* target. Use a command with a case_report binding for
automatic execution, or the existing verification_reviews alternatives:
agent_review, existing_evidence or not_verified. Explain limitations and prior
evidence applicability. A parent acceptance with examples derives its result
from those examples; covering only the parent cannot bypass a missing child.

For an actual pytest command, add this case_report configuration alongside
argv, cwd, run_kind, reason and covers:

~~~json
{
  "adapter": "pytest",
  "test_root": ".",
  "input_paths": ["inventory.py", "tests/test_inventory.py", "pytest.ini"],
  "bindings": [{
    "example_ref": "direction.example:DIREX-0123456789ABCDEF",
    "test_ids": ["tests/test_inventory.py::test_insufficient_stock"]
  }]
}
~~~

Use native pytest node IDs relative to test_root, including the exact
parameterized suffix when applicable. Confirm IDs from the real project or
targeted collection; do not substitute display labels, wildcards or guessed
names. test_root and input_paths are relative to the execution repository, not
the command's cwd. List actual source, tests, fixtures and configuration needed
by the selected behavior as individual input files, including the bound test
file. Directories, globs, paths outside the repository, `.git` and `.strixnova` are
not input files. Do not snapshot disposable output or mutable test data.

This is a declared input scope, not automatic discovery of all dependencies.
The Agent must identify omitted dependencies and changes outside that scope.
The strixnova.engineering-plan.v1 compiler adds example_fingerprints; never
author them or duplicate the example text in the assessment. A report can bind
multiple examples and native cases in one planned command. Do not create a
full-suite run, folder or report for each example.

## Run and review different kinds of evidence separately

During implementation, use the smallest feedback test needed. If test-first
work is appropriate, observe the intended behavioral failure before fixing it;
a skipped scaffold or import error is not that failure. Reuse the planned final
command once the implementation is ready.

`strixnova verify` injects the bundled pytest reporter only into that child
process. The target environment must already provide pytest; Strixnova neither
installs its test framework nor modifies project configuration. pytest and
pytest-xdist are the initial adapter scope; another framework requires its own
adapter before Strixnova can claim native case execution evidence.

The strixnova.test-case-report.v1 report records native cases and their phases,
framework and Python versions, run identity and reporter identity. The
strixnova.test-case-evidence.v1 receipt binds it to the current plan, example
content and actual declared input bytes, including uncommitted changes.
A passed command does not turn skipped, xfailed, xpassed, deselected,
not_collected, not_run, failed or error cases into passed examples.
Missing/invalid reports and changed inputs remain explicit gaps. Changes to a
declared input after execution require a fresh run; the original receipt remains
history. Changes to behavior itself return to direction revision.

For every automatic example, submit an assertion-adequacy review through the
existing verification_review_results in the actual result, as well as results
for non-command arrangements. Use target_ref, outcome, rationale and
evidence_refs. Outcomes are supported, not_supported or not_verified. Review
whether the assertions exercise the promised outcome and relevant side effects,
using real source/receipt references. Passing a native test ID alone is not that
review. assertion_review_required in the plan makes this obligation visible.

The program derives target_verification from those reviews and actual receipt
facts. Its command_result, report_status, tests and assertion_review remain
separate. Unsupported or incomplete examples need visible result limitations.
semantic_content_machine_proven stays false. Present the existing result card
as: expected example, actual observation, reviewed adequacy, remaining gap.

One report per command lives beside its stdout/stderr under
.strixnova/artifacts/<WorkItem-ID>/<receipt-ID>.cases.json. Read the returned
output:<receipt-ID>:cases reference through strixnova history, with ordinary
paging, availability and hash checks. Do not manufacture or hand-edit reports.
New assessments and replans use the current direction contract. Recorded
work retains its actual evidence and limitations; it is never retroactively
labelled example-verified.
