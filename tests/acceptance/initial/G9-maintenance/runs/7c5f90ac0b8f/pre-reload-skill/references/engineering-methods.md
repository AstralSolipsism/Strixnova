# Engineering method submissions

Read this reference only when the project baseline says an adopted or
conditional method intersects an affected/unknown impact, or when the WorkItem
creates a project. The shipped DDD rule intersects exactly `domain`,
`architecture`, `interface`, and `data`; request keywords do not activate it.

The ProjectEngineeringPolicy, not folder names, says whether DDD is
`adopted`, `conditional`, `not_adopted`, or `not_assessed`. DDD bodies live in
the independent ProjectDomainModel and implementation claims live in the
independent ProjectImplementationAlignment. The ProjectEngineeringBaseline
only locates the exact adopted revisions. Use the catalog, deterministic
closure, and individual Fact records exposed by CurrentAction; do not load all
Collections or infer a bounded context from a document title.

Collection records already contain the Source identity, title, routing summary,
path, and canonical form. Select one Source from that route before loading its
Fact metadata. Generic Fact `attributes` must stay empty; only
`context_relationship` uses the fixed from/to/type fields. Put project-specific
structures in the canonical Fact content so they are loaded only on demand.

For a relevant adopted/conditional method, submit exactly one application.
Choose `applied` only when concrete techniques, targets, evidence and domain
Fact references are known. Otherwise use `considered_not_applied`. Method choice
does not raise AssuranceBand by itself. Each planned use chooses `stage` from exactly
`requirements`, `domain_analysis`, `design`, `implementation`, `verification`,
or `delivery`.

```json
{
  "domain_fact_changes": [{
    "disposition": "retain",
    "target_ref": {
      "schema_version": "strixnova.domain-fact-reference.v1",
      "authority_kind": "project_domain_model",
      "model_id": "MODEL-0123456789ABCDEF",
      "fact_id": "FACT-0123456789ABCDEF",
      "observed_commit": "0123456789abcdef0123456789abcdef01234567"
    },
    "source_path": "docs/domain/sources/work-items.yaml",
    "reason": "The existing term remains valid for this change.",
    "evidence_refs": ["SRC-001"],
    "lineage": []
  }],
  "method_applications": [
    {
      "method_id": "ddd",
      "decision": "applied",
      "purpose": "Clarify the domain boundary changed by this WorkItem.",
      "evidence_refs": ["SRC-001"],
      "baseline_refs": ["engineering-policy:method:ddd"],
      "domain_fact_refs": [{
        "schema_version": "strixnova.domain-fact-reference.v1",
        "authority_kind": "project_domain_model",
        "model_id": "MODEL-0123456789ABCDEF",
        "fact_id": "FACT-0123456789ABCDEF",
        "observed_commit": "0123456789abcdef0123456789abcdef01234567"
      }],
      "planned_uses": [{
        "use_id": "DDD-USE-001",
        "stage": "domain_analysis",
        "technique_ids": ["ubiquitous_language", "bounded_context"],
        "purpose": "Update affected terms and context ownership.",
        "target_refs": ["impact_scope.affected[0]"],
        "evidence_refs": ["SRC-001"]
      }]
    }
  ]
}
```

For DDD, use only techniques adopted by the project:
`ubiquitous_language`, `bounded_context`, `context_map`, and
`domain_invariant_trace`. Every formal Fact reference binds
`authority_kind`, `model_id`, `fact_id`, and the immutable investigation
commit. `domain_fact_changes` is an assessment-level project-authority change,
not part of any method application. It exists whether or not DDD is adopted or
used. Fact change disposition is `retain`, `add`, `update`, or `retire`.

Rename, move, and meaning-preserving clarification keep the existing Fact ID.
Changing a threshold, cadence, formula, or wording of the same stable business
rule is an `update` and keeps its Fact ID. Semantic replacement means the old
Fact no longer represents the same domain concept or role and a distinct
successor takes its place; replacement, split, and merge allocate new random
IDs and retire the old Fact with `superseded_by`, `split_into`, or
`merged_into` lineage. The
`lineage` field is required on every Fact change: use `[]` for `retain`, `add`,
and `update`; only a `retire` change may contain replacement, split, or merge
entries. A lineage entry has the exact shape
`{"relation":"superseded_by","target_fact_id":"FACT-0123456789ABCDEF"}`;
use `split_into` or `merged_into` only when that is the real relationship. The
program validates identity, location, references, Git facts and structural
closure; it does not write the meaning. Implementation alignment is one complete
versioned authority made of source-ownership, actual-dependency,
target-responsibility, and deviation ledgers. It has no sparse `ALIGN-*` entry
contract. When planned behavior, domain, architecture, or alignment files make
that authority stale, plan explicit operations for the complete alignment
manifest and affected ledger artifacts. Mark the manifest operation as the
existing `domain_alignment` long-lived artifact. The coding agent authors the
reviewed ledger content; Strixnova validates bindings, coverage, exact revisions, and
repeatable drift facts without inventing semantic conclusions.

Use `adoption_change` only when the WorkItem changes the long-lived project
method decision. Then plan the engineering policy as `quality_policy` and plan
the engineering baseline as an ordinary exact-reference update; the baseline is
not itself a catch-all long-lived artifact.
Adopting/conditionally adopting DDD also requires independent domain model and
alignment paths, a Fact add/update, a complete alignment authority create/update,
and the project-adopted DDD techniques. When an existing baseline has no DDD paths yet, declare exactly
one `domain_model` and one `domain_alignment` long-lived artifact operation;
Strixnova takes the planned target paths from those operations instead of asking
for duplicate path fields. A new project must honestly select a status for each shipped
method, including `not_assessed`; it must always create an independent
ProjectArchitectureDescription. Do not create a method-specific workflow, keyword
router, compliance score, code graph, or automatic refactor.
