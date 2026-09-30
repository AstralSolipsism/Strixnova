"""Cross-authority consistency without becoming another project authority."""

from __future__ import annotations

from strixnova.project_repository_scope import prepare_repository_scope, qualify_candidate

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
import hashlib
import json
from pathlib import Path
from typing import Any

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
)

from strixnova.project_implementation_alignment import (
    ProjectImplementationAlignment,
    ProjectImplementationAlignmentError,
)
from strixnova.project_architecture_description import (
    ProjectArchitectureDescription,
    ProjectArchitectureDescriptionError,
)
from strixnova.project_domain_model import (
    LINEAGE_RELATIONS,
    ProjectDomainModel,
    ProjectDomainModelError,
    validate_domain_fact_reference,
)
from strixnova.project_engineering_baseline import (
    AUTHORITY_KINDS,
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.project_context import ProjectContext, ProjectContextError, ProjectContextResolver
from strixnova.project_content_snapshot import review_subject
from strixnova.project_engineering_policy import (
    ProjectEngineeringPolicy,
    ProjectEngineeringPolicyError,
    project_engineering_policy_governed_paths,
)
from strixnova.project_product_definition import (
    ProjectProductDefinition,
    ProjectProductDefinitionError,
    project_direction_context,
    unadopted_project_direction_context,
    validate_direction_context_binding,
)
from strixnova.yaml_metadata_patch import (
    YamlMetadataPatchError,
    render_yaml_value_patches,
)


AUTHORITY_CONSISTENCY_SCHEMA = "strixnova.project-authority-consistency.v1"
AUTHORITY_INVALIDATION_SCHEMA = "strixnova.authority-invalidation-scope.v1"
AUTHORITY_ADOPTION_SCHEMA = "strixnova.authority-adoption.v1"
AUTHORITY_CANDIDATE_SNAPSHOT_SCHEMA = (
    "strixnova.authority-candidate-snapshot.v1"
)
DIRECTION_CONTEXT_RECOVERY_STATES = frozenset(
    {
        "awaiting_direction_confirmation",
        "needs_engineering_assessment",
        "awaiting_plan_confirmation",
        "implementation_ready",
        "exploring",
        "implementing",
        "awaiting_actual_result",
        "replanning_required",
    }
)

_CORE_ARTIFACT_KIND_BY_TYPE = {
    "product_governance": "product_definition",
    "domain_model": "domain_model",
    "architecture": "target_architecture",
    "quality_policy": "engineering_policy",
    "domain_alignment": "implementation_alignment",
}
_AUTHORITY_IDENTITY_FIELD = {
    "product_definition": "product_id",
    "domain_model": "model_id",
    "target_architecture": "architecture_id",
    "engineering_policy": "policy_id",
    "implementation_alignment": "alignment_model_id",
}
_AUTHORITY_RESULT_KEY = {
    "product_definition": "product_definition",
    "domain_model": "domain_catalog",
    "target_architecture": "target_architecture",
    "engineering_policy": "engineering_policy",
    "implementation_alignment": "implementation_alignment",
}
_ACTUAL_RESULT_ADOPTABLE_KINDS = frozenset({"implementation_alignment"})

_DOWNSTREAM = {
    "product_definition": (
        "product_definition",
        "domain_model",
        "target_architecture",
        "engineering_policy",
        "implementation_alignment",
        "code_version",
    ),
    "domain_model": (
        "domain_model",
        "target_architecture",
        "implementation_alignment",
        "code_version",
    ),
    "target_architecture": (
        "target_architecture",
        "implementation_alignment",
        "code_version",
    ),
    "engineering_policy": (
        "engineering_policy",
        "code_version",
    ),
    "implementation_alignment": (
        "implementation_alignment",
    ),
    "code_version": (
        "implementation_alignment",
        "code_version",
    ),
}


class ProjectAuthorityConsistencyError(ValueError):
    """One or more adopted authorities do not form one exact chain."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目权威链不一致")


def direction_context_requires_validation(
    work_item: Mapping[str, Any],
) -> bool:
    """Return whether one item carries a live direction-context binding.

    This is a structural gate only. It identifies states in which an already
    recorded exact binding must still match the current adopted product
    projection; it does not decide whether any product meaning is relevant.
    """

    status = str(work_item.get("status") or "").strip()
    if status not in DIRECTION_CONTEXT_RECOVERY_STATES:
        return False
    data = work_item.get("data")
    data = data if isinstance(data, Mapping) else {}
    if isinstance(data.get("pending_effect"), Mapping):
        return False
    direction = data.get("direction")
    if not isinstance(direction, Mapping):
        return False
    return isinstance(direction.get("decision_context"), Mapping)


def direction_context_invalidation_issues(
    work_item: Mapping[str, Any],
    current_context: Mapping[str, Any],
) -> list[str]:
    """Return mechanically provable stale-binding issues for one WorkItem."""

    if not direction_context_requires_validation(work_item):
        return []
    data = work_item["data"]
    direction = data["direction"]
    binding = direction["decision_context"]
    try:
        validate_direction_context_binding(binding, current_context)
    except ProjectProductDefinitionError as error:
        return list(error.issues or [str(error)])
    return []


def authority_owned_target_refs(
    authority_kind: str,
    value: Mapping[str, Any],
) -> list[str]:
    """Extract only identities defined by one authority's own schema."""

    def item_ids(collection: Any, field: str) -> set[str]:
        return {
            str(item.get(field) or "")
            for item in collection or []
            if isinstance(item, Mapping) and str(item.get(field) or "")
        }

    if authority_kind == "product_definition":
        result = {str(value["product_id"])}
        for collection, field in (
            ("primary_users", "user_id"),
            ("problems", "problem_id"),
            ("desired_outcomes", "outcome_id"),
            ("capabilities", "capability_id"),
            ("non_goals", "non_goal_id"),
            ("constraints", "constraint_id"),
            ("success_criteria", "criterion_id"),
            ("delivery_stages", "stage_id"),
            ("unresolved_decisions", "decision_id"),
        ):
            result.update(item_ids(value.get(collection), field))
        return sorted(result)
    if authority_kind == "domain_model":
        return sorted(
            {
                str(value["model_id"]),
                *item_ids(value.get("facts"), "fact_id"),
            }
        )
    if authority_kind == "target_architecture":
        modules = value.get("modules") or []
        return sorted(
            {
                str(value["architecture_id"]),
                *item_ids(modules, "module_id"),
                *{
                    str(public_interface.get("interface_id") or "")
                    for module in modules
                    if isinstance(module, Mapping)
                    and isinstance(
                        public_interface := module.get("public_interface"),
                        Mapping,
                    )
                    and str(public_interface.get("interface_id") or "")
                },
                *item_ids(value.get("relationships"), "relationship_id"),
                *item_ids(value.get("constraints"), "constraint_id"),
                *item_ids(value.get("implementation_stages"), "stage_id"),
            }
        )
    if authority_kind == "engineering_policy":
        return sorted(
            {
                str(value["policy_id"]),
                *item_ids(value.get("method_adoptions"), "method_id"),
                *item_ids(value.get("rule_extensions"), "rule_id"),
            }
        )
    if authority_kind == "implementation_alignment":
        return sorted(
            {
                str(value["alignment_model_id"]),
                *item_ids(value.get("deviations"), "deviation_id"),
            }
        )
    raise ProjectAuthorityConsistencyError(
        [f"未知项目权威种类：{authority_kind}"]
    )


def _review_input_readers(project_dir: str | Path, work_item: Mapping[str, Any], *, project_context=None, bindings=None) -> dict[str | None, GitProjectReader]:
    """Use recorded work areas and explicitly declared read dependencies."""
    data = work_item.get("data") or {}
    plan = data.get("engineering", {}).get("plan") or {}
    resolver = ProjectContextResolver(project_dir)
    with resolver.operation(bindings):
        context = project_context or resolver.configured(bindings=bindings)
        declared = (plan.get("repository_scope") or {}).get("repositories", [])
        areas = data.get("repository_deliveries") or []
        if not areas and (not declared or any(row["role"] != "read" for row in declared)):
            areas = [{"repository_id": data.get("selected_repository_id"), "git": data.get("git") or {}}]
        readers = {}
        with resolver.execution_readers(context, areas):
            for entry in areas:
                area = entry.get("git") or {}
                integrated = (area.get("integration") or {}).get("integrated_commit")
                root = area.get("repository") if integrated or area.get("conflict_resolution") or work_item.get("status") == "exploring" else area.get("worktree_path")
                root = root or area.get("repository") or project_dir
                readers[entry["repository_id"]] = GitProjectReader(root, observed_ref=integrated)
            for repository in declared:
                if repository["role"] != "read":
                    continue
                if repository["repository_id"] is None:
                    reference = repository["investigation_ref"]
                    root = readers[None].project if None in readers else project_dir
                    readers[None] = GitProjectReader(root, observed_ref=None if reference == "working_tree" else reference)
                    continue
                if context is None:
                    raise ProjectContextError("project_repository_unbound", "审阅的只读依赖需要明确仓库绑定")
                selected = context.repository(repository["repository_id"])
                reference = repository["investigation_ref"]
                readers[repository["repository_id"]] = GitProjectReader.for_repository(selected.scope, observed_ref=None if reference == "working_tree" else reference)
        return readers


class ProjectAuthorityConsistency:
    """Validate exact references and project readiness across authorities.

    This object is a deterministic checker. It neither stores project meaning
    nor upgrades structural consistency into a semantic correctness claim.
    """

    @classmethod
    def review_subject_for(cls, project_dir: str | Path, work_item: Mapping[str, Any], *, project_context=None, bindings=None) -> dict[str, Any]:
        """Bind declared implementation inputs and the exact adopted rule basis."""
        readers = _review_input_readers(project_dir, work_item, project_context=project_context, bindings=bindings)
        resolver = ProjectContextResolver(project_dir)
        live = resolver.configured(bindings=bindings, use_execution_bindings=False)
        authority_basis = {}
        if live is not None:
            plan = (work_item.get("data") or {}).get("engineering", {}).get("plan") or {}
            reference = (live.configuration or {}).get("default_integration_ref") or plan.get("investigation_ref")
            if reference and reference != "working_tree":
                context = resolver.configured(bindings=bindings, observed_ref=reference, use_execution_bindings=False)
                if context is not None:
                    basis = cls(project_dir, shared_context=context).review_basis()
                    authority_basis = {"configuration_commit": context.configuration_reader.observed_commit, "sources": basis["sources"], "gaps": basis["gaps"]}
                    for source in basis["sources"].values():
                        identifier = source["repository_id"]
                        if identifier not in readers:
                            repository = context.repository(identifier)
                            readers[identifier] = GitProjectReader.for_repository(repository.scope, observed_ref=source["observed_commit"])
        return review_subject(work_item, readers, authority_basis=authority_basis, canonical_unbound=work_item.get("status") != "exploring")

    def __init__(
        self,
        project_dir: str | Path,
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
        shared_context: ProjectContext | None = None,
        shared_baseline: ProjectEngineeringBaseline | None = None,
    ) -> None:
        try:
            if shared_baseline is not None and any(value is not None for value in (observed_ref, shared_reader, shared_context)):
                raise ProjectAuthorityConsistencyError(["已选基线不能同时重选项目内容范围"])
            self.baseline_reader = shared_baseline or ProjectEngineeringBaseline(
                project_dir,
                observed_ref=observed_ref,
                shared_reader=shared_reader,
                shared_context=shared_context,
            )
            self.reader = self.baseline_reader.reader
        except (GitProjectReaderError, ProjectEngineeringBaselineError) as error:
            issues = getattr(error, "issues", [str(error)])
            raise ProjectAuthorityConsistencyError(issues) from error
        self.project = self.baseline_reader.project
        self.observed_commit = self.baseline_reader.observed_commit
        self._cache: dict[str, Any] | None = None
        self._authority_content_refs: dict[str, dict[str, Any]] = {}
        self._authority_readers: dict[str, GitProjectReader] = {}
        self._alignment_reader: ProjectImplementationAlignment | None = None
        self._alignment_stage: str | None = None
        self._review_basis_cache: dict[str, Any] | None = None
        self._review_loaders: dict[str, Any] = {}
        self._review_gaps: list[dict[str, Any]] = []

    def _read_authorities(self, baseline: Mapping[str, Any], *, allow_incomplete: bool = False) -> tuple[dict[str, Any], ProjectImplementationAlignment | None]:
        refs = baseline["authority_refs"]
        context = self.baseline_reader.context
        readers: dict[str, GitProjectReader] = {}
        for kind, reference in refs.items():
            if allow_incomplete and context is not None:
                repository = next((item for item in context.repositories if item.repository_id == reference.get("repository_id")), None)
                if repository is not None and repository.availability in {"missing", "not_bound"}:
                    self._review_gaps.append({"code": repository.issue_code, "authority_kind": kind, "message": "所需权威仓库当前不可读取"})
                    continue
            try:
                readers[kind] = context.authority_reader(reference, parent_reader=self.reader) if context is not None else self.reader
            except (ProjectContextError, GitProjectReaderError) as error:
                failure = ProjectAuthorityConsistencyError([str(error)])
                failure.code = error.code
                raise failure from error
        batches: dict[int, tuple[GitProjectReader, list[str]]] = {}
        for kind, reader in readers.items():
            batches.setdefault(id(reader), (reader, []))[1].append(refs[kind]["path"])
        if not allow_incomplete:
            for reader, paths in batches.values():
                reader.prefetch(paths)
        self._authority_readers = readers
        loaders: dict[str, Any] = {}
        for kind, constructor in (
            ("product_definition", ProjectProductDefinition),
            ("domain_model", ProjectDomainModel),
            ("target_architecture", ProjectArchitectureDescription),
            ("engineering_policy", ProjectEngineeringPolicy),
        ):
            if kind in readers:
                source = readers[kind]
                loaders[kind] = constructor(source.project, refs[kind]["path"], shared_reader=source)
        alignment_source = readers.get("implementation_alignment")
        code_readers = {alignment_source.repository_id: alignment_source} if alignment_source is not None else {}
        if context is not None and alignment_source is not None:
            for repository in context.repositories:
                if repository.scope is None or repository.availability != "available":
                    continue
                if context.configuration_reader.observed_commit is not None and repository.repository_id != alignment_source.repository_id and (context.content_versions is None or repository.repository_id not in context.content_versions):
                    # A historical carrier commit cannot select a different
                    # repository's current checkout as historical source proof.
                    continue
                version = (context.content_versions or {}).get(repository.repository_id)
                if repository.repository_id == alignment_source.repository_id and context.content_versions is None:
                    version = alignment_source.observed_commit
                if repository.repository_id == alignment_source.repository_id and version == alignment_source.observed_commit:
                    continue
                code_readers[repository.repository_id] = GitProjectReader.for_repository(repository.scope, observed_ref=version)
        alignment_reader = None
        if alignment_source is not None and all(kind in loaders for kind in ("domain_model", "target_architecture")):
            alignment_reader = ProjectImplementationAlignment(
                alignment_source.project, refs["implementation_alignment"]["path"],
                domain_model_path=refs["domain_model"]["path"],
                architecture_description_path=refs["target_architecture"]["path"],
                shared_reader=alignment_source, domain_reader=loaders["domain_model"],
                architecture_reader=loaders["target_architecture"], repository_readers=code_readers,
            )
            loaders["implementation_alignment"] = alignment_reader
        elif allow_incomplete and alignment_source is not None:
            self._review_gaps.append({"code": "alignment_dependencies_unavailable", "authority_kind": "implementation_alignment", "message": "实现对齐所依赖的领域或架构不可读取"})
        self._authority_content_refs = {
            kind: {
                "repository_id": reader.repository_id, "path": refs[kind]["path"],
                "observed_commit": reader.observed_commit,
                "scope": "git_commit" if reader.observed_commit is not None else "working_tree",
            }
            for kind, reader in readers.items()
        }
        self._alignment_reader = alignment_reader
        self._alignment_stage = baseline["current_architecture_stage_id"]
        self._review_loaders = loaders
        values: dict[str, Any] = {}
        for kind, loader in loaders.items():
            try:
                values[kind] = loader.catalog() if kind == "domain_model" else loader.load()
            except (ProjectProductDefinitionError, ProjectDomainModelError, ProjectArchitectureDescriptionError,
                    ProjectEngineeringPolicyError, ProjectImplementationAlignmentError, GitProjectReaderError) as error:
                if not allow_incomplete:
                    raise
                self._review_gaps.append({"code": "authority_material_unavailable", "authority_kind": kind, "message": str(error)})
        return values, alignment_reader

    def review_basis(self) -> dict[str, Any]:
        """Read usable declared authorities, without observing code or deciding readiness."""

        if self._review_basis_cache is not None:
            return deepcopy(self._review_basis_cache)
        baseline = self.baseline_reader.load(required=False, allow_candidate_refs=True)
        if baseline is None:
            return {"baseline": None, "authorities": {}, "sources": {}, "gaps": [{"code": "baseline_missing", "message": "项目尚无工程基线"}], "semantic_content_machine_proven": False}
        self._review_gaps = []
        values, _ = self._read_authorities(baseline, allow_incomplete=True)
        issues: list[str] = []
        self._check_available_bindings(baseline, values, issues)
        self._check_available_chain(values, issues)
        if issues:
            raise ProjectAuthorityConsistencyError(issues)
        sources: dict[str, Any] = {}
        governed_paths = self._authority_paths({"baseline": baseline, **values})
        for kind in values:
            reference = baseline["authority_refs"][kind]
            reader = self._authority_readers[kind]
            paths = governed_paths[kind]
            sources[kind] = {
                **self._authority_content_refs[kind],
                "revision_id": reference["revision_id"],
                "status": deepcopy(reference["status"]),
                "files": [{"path": path, "sha256": hashlib.sha256(reader.read_canonical_bytes(path)).hexdigest()} for path in sorted(set(paths))],
            }
            if kind == "domain_model":
                by_path = {item["path"]: item for item in sources[kind]["files"]}
                for route in values[kind]["sources"]:
                    catalog = self._review_loaders[kind].source_catalog(route["source_id"], collection_path=route["collection_path"])
                    by_path[route["path"]]["fact_ids"] = [item["fact_id"] for item in catalog["facts"]]
        result = {
            "baseline": deepcopy(baseline), "authorities": values,
            "sources": sources, "gaps": deepcopy(self._review_gaps),
            "semantic_content_machine_proven": False,
        }
        self._review_basis_cache = result
        return deepcopy(result)

    def select_review_materials(self, module_ids: Sequence[str]) -> dict[str, Any]:
        """Expand recorded architecture links and their explicit domain references."""

        basis = self.review_basis()
        values = basis["authorities"]
        if "target_architecture" not in values:
            return {"architecture": None, "domain_facts": None, "gaps": []}
        try:
            selected = self._review_loaders["target_architecture"].select_modules(module_ids)
        except ProjectArchitectureDescriptionError as error:
            raise ProjectAuthorityConsistencyError(error.issues) from error
        fact_ids = [item["domain_fact_id"] for item in selected["domain_fact_dispositions"]]
        domain = None
        gaps: list[dict[str, Any]] = []
        if fact_ids and "domain_model" in values:
            try:
                domain = self._review_loaders["domain_model"].required_closure(fact_ids)
                domain["references"] = [self._review_loaders["domain_model"].fact_reference(identifier) for identifier in domain["fact_ids"]]
            except ProjectDomainModelError as error:
                gaps.append({"code": "domain_closure_unavailable", "message": str(error)})
        return {"architecture": selected, "domain_facts": domain, "gaps": gaps}

    def review_policy_materials(self) -> dict[str, Any] | None:
        """Expose the same versioned rules for execution and independent review.

        Keep rule meanings and evidence expectations intact. This supplies the
        complete policy inventory, not a semantic applicability decision.
        """
        policy = self.review_basis()["authorities"].get("engineering_policy")
        if policy is None:
            return None
        profile = self._review_loaders["engineering_policy"].governance_profile()
        return {
            **{key: deepcopy(policy[key]) for key in (
                "policy_id", "revision", "policy_statements", "evidence_requirements",
                "base_profile_ref", "project_sources", "method_adoptions", "rule_tailoring",
                "verification_command_policy", "delivery_gates",
            )},
            "rules": deepcopy(profile["rules"]),
            "rule_sources": deepcopy(profile["sources"]),
        }

    def execution_materials(self, operations: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Join explicit operation paths to recorded owners and existing rules.

        Unknown ownership remains a gap. Global product/policy material is
        retained even when a new path cannot yet select an architecture module.
        """
        basis = self.review_basis()
        authorities = basis["authorities"]
        alignment = authorities.get("implementation_alignment", {})
        alignment_repository = basis["sources"].get("implementation_alignment", {}).get("repository_id")
        owners = {
            (row.get("repository_id") or alignment_repository, row["path"]): row
            for row in alignment.get("source_ownership", [])
        }
        repositories = {identifier for identifier, _ in owners}
        selected = set()
        reasons = []
        gaps = deepcopy(basis["gaps"])
        seen = set()
        for operation in operations:
            identifier = operation.get("repository_id")
            if identifier is None and len(repositories) == 1:
                identifier = next(iter(repositories))
            for field in ("path", "to_path"):
                path = operation.get(field)
                if not path or (identifier, path) in seen:
                    continue
                seen.add((identifier, path))
                owner = owners.get((identifier, path))
                if owner is not None and owner.get("target_module_id"):
                    selected.add(owner["target_module_id"])
                    reasons.append({"repository_id": identifier, "path": path, "module_id": owner["target_module_id"], "reason": "recorded_source_ownership"})
                else:
                    gaps.append({"code": "source_ownership_unknown", "repository_id": identifier, "path": path, "message": "计划路径没有明确模块归属；相关性由 Agent 调查，不按文件名推断"})
        materials = self.select_review_materials(sorted(selected))
        gaps.extend(materials["gaps"])
        for kind, source in basis["sources"].items():
            if source["status"] != {"revision_status": "confirmed", "adoption_status": "current"}:
                gaps.append({"code": "authority_not_current", "authority_kind": kind, "message": "该材料尚未确认采用，不能冒充现行规则"})
        product = authorities.get("product_definition")
        return {
            **materials,
            "sources": deepcopy(basis["sources"]),
            "product_guardrails": {key: deepcopy(product[key]) for key in ("product_id", "revision", "purpose", "capabilities", "non_goals", "constraints")} if product is not None else None,
            "engineering_policy": self.review_policy_materials(),
            "selection_reasons": reasons,
            "gaps": gaps,
            "semantic_content_machine_proven": False,
        }

    def confirmed_execution_materials(self, operations: Sequence[Mapping[str, Any]], decisions: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """Use already recorded confirmation only for the same current bytes."""
        basis = self.review_basis()
        confirmations = []
        for record in decisions:
            kind = record["authority_kind"]
            candidate = record["candidate"]
            source = basis["sources"].get(kind)
            if source is None:
                raise ProjectAuthorityConsistencyError([f"已确认实施依据缺失：{kind}"])
            paths = {row["path"]: row["sha256"] for row in source["files"]}
            if (
                source["revision_id"] != candidate["revision_id"]
                or sorted(paths) != sorted(candidate["governed_paths"])
                or self._canonical_sha256(paths) != record["confirmed_content_sha256"]
                or source["status"] != {"revision_status": "confirmed", "adoption_status": "current"}
            ):
                raise ProjectAuthorityConsistencyError([f"长期权威确认后内容或绑定发生变化，不能作为当前实施依据：{kind}"])
            confirmations.append({"authority_kind": kind, "revision_id": candidate["revision_id"], "confirmed_content_sha256": record["confirmed_content_sha256"]})
        result = self.execution_materials(operations)
        result.update({"basis_kind": "confirmed_execution_candidate", "confirmed_decisions": confirmations})
        return result

    def alignment_drift(self, *, mode: str, external_providers: Sequence[Any] = (), external_execution_authorized: bool = False) -> dict[str, Any]:
        """Review the already selected authority and repository content scopes."""
        if self._alignment_reader is None:
            self.load()
        assert self._alignment_reader is not None
        return self._alignment_reader.drift(mode=mode, current_stage_id=self._alignment_stage, external_providers=external_providers, external_execution_authorized=external_execution_authorized)

    def _scope_metadata(self, baseline: Mapping[str, Any]) -> dict[str, Any]:
        context = self.baseline_reader.context
        configuration_reader = context.configuration_reader if context is not None else self.reader
        assert configuration_reader is not None
        return {
            "observed_repository_id": self.reader.repository_id,
            "authority_content_refs": deepcopy(self._authority_content_refs),
            "baseline_content_ref": {
                "repository_id": self.reader.repository_id,
                "path": baseline["_manifest_path"], "observed_commit": self.observed_commit,
            },
            "configuration_content_ref": {
                "repository_id": configuration_reader.repository_id,
                "path": context.configuration_path if context is not None else "strixnova-project.yaml",
                "observed_commit": configuration_reader.observed_commit,
            },
        }

    def load(self) -> dict[str, Any]:
        """Load and cross-check every authority adopted by the narrow baseline."""

        if self._cache is not None:
            return deepcopy(self._cache)
        try:
            baseline = self.baseline_reader.load(required=True)
            assert baseline is not None
        except ProjectEngineeringBaselineError as error:
            raise ProjectAuthorityConsistencyError(error.issues) from error
        return self._load_baseline(baseline)

    def inspect_baseline_candidate(self, value: Mapping[str, Any]) -> dict[str, Any]:
        """Check explicit candidate metadata without replacing its source file."""

        baseline = self.baseline_reader.validate(
            value, manifest_path=self.baseline_reader.locate().relative_to(self.project).as_posix(),
            allow_candidate_refs=True,
        )
        return {**self._load_baseline(baseline, cache=False), "candidate_only": True, "writes_performed": False}

    def _load_baseline(self, baseline: Mapping[str, Any], *, cache: bool = True) -> dict[str, Any]:
        try:
            values, alignment_reader = self._read_authorities(baseline)
            product, domain, architecture, policy, alignment = (
                values[kind] for kind in AUTHORITY_KINDS
            )
        except (
            ProjectEngineeringBaselineError,
            ProjectProductDefinitionError,
            ProjectDomainModelError,
            ProjectArchitectureDescriptionError,
            ProjectEngineeringPolicyError,
            ProjectImplementationAlignmentError,
        ) as error:
            raise ProjectAuthorityConsistencyError(error.issues) from error

        issues: list[str] = []
        self._check_baseline_bindings(
            baseline,
            product,
            domain,
            architecture,
            policy,
            alignment,
            issues,
        )
        self._check_authority_chain(
            product,
            domain,
            architecture,
            policy,
            alignment,
            issues,
        )
        stage_ids = {
            item["stage_id"] for item in architecture["implementation_stages"]
        }
        if baseline["current_architecture_stage_id"] not in stage_ids:
            issues.append("项目工程基线引用了目标架构中不存在的当前实施阶段")
        if issues:
            raise ProjectAuthorityConsistencyError(issues)

        review = self._review_state(
            baseline,
            alignment,
            alignment_reader,
        )
        result = {
            "schema_version": AUTHORITY_CONSISTENCY_SCHEMA,
            "baseline": deepcopy(baseline),
            "product_definition": deepcopy(product),
            "domain_catalog": deepcopy(domain),
            "target_architecture": deepcopy(architecture),
            "engineering_policy": deepcopy(policy),
            "implementation_alignment": deepcopy(alignment),
            "current_architecture_stage_id": baseline[
                "current_architecture_stage_id"
            ],
            "structurally_consistent": True,
            "review_state": review,
            "ready_for_stage_completion": not review["required"],
            "observed_commit": self.observed_commit,
            **self._scope_metadata(baseline),
            "semantic_content_machine_proven": False,
        }
        if cache:
            self._cache = result
        return deepcopy(result)

    def direction_context(self) -> dict[str, Any]:
        """Return the complete current product context without semantic filtering."""

        authorities = self.load()
        return project_direction_context(
            authorities["product_definition"],
            observed_commit=self._authority_content_refs.get("product_definition", {}).get("observed_commit", self.observed_commit),
        )

    def load_working_tree_candidate(
        self,
        adopted_authorities: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate one candidate authority chain without adopting it.

        When an integrated authority chain exists, it remains the immutable
        comparison base.  During first adoption there is intentionally no such
        commit yet, so the confirmed references in the working-tree baseline
        are the comparison base. Candidate files may carry successor revisions
        at the same governed paths. The baseline may retain its adopted reference
        or explicitly point to an unconfirmed successor marked under review.
        Both remain candidate views subject to the existing acceptance checks.
        """

        try:
            working_baseline = self.baseline_reader.load(
                required=True,
                allow_candidate_refs=True,
            )
            assert working_baseline is not None
            adopted_baseline = (
                adopted_authorities["baseline"]
                if adopted_authorities is not None
                else working_baseline
            )
            values, alignment_reader = self._read_authorities(working_baseline)
            product, domain, architecture, policy, alignment = (
                values[kind] for kind in AUTHORITY_KINDS
            )
        except (
            KeyError,
            ProjectEngineeringBaselineError,
            ProjectProductDefinitionError,
            ProjectDomainModelError,
            ProjectArchitectureDescriptionError,
            ProjectEngineeringPolicyError,
            ProjectImplementationAlignmentError,
        ) as error:
            issues = getattr(error, "issues", [str(error)])
            raise ProjectAuthorityConsistencyError(issues) from error

        issues: list[str] = []
        candidate_by_kind = {
            "product_definition": product,
            "domain_model": domain,
            "target_architecture": architecture,
            "engineering_policy": policy,
            "implementation_alignment": alignment,
        }
        if adopted_authorities is None:
            self._check_candidate_against_baseline(
                working_baseline,
                candidate_by_kind,
                issues,
            )
        else:
            self._check_candidate_lineage(
                adopted_authorities,
                candidate_by_kind,
                issues,
            )
            self._check_candidate_baseline(
                adopted_authorities["baseline"],
                working_baseline,
                candidate_by_kind,
                issues,
            )
        self._check_authority_chain(
            product,
            domain,
            architecture,
            policy,
            alignment,
            issues,
        )
        stage_ids = {
            item["stage_id"] for item in architecture["implementation_stages"]
        }
        if working_baseline["current_architecture_stage_id"] not in stage_ids:
            issues.append("工作树目标架构候选缺少当前已采用实施阶段")
        if issues:
            raise ProjectAuthorityConsistencyError(issues)

        review = self._review_state(
            working_baseline,
            alignment,
            alignment_reader,
        )
        changed_kinds = (
            sorted(AUTHORITY_KINDS)
            if adopted_authorities is None
            else [
                kind
                for kind in AUTHORITY_KINDS
                if candidate_by_kind[kind]["revision"]["revision_id"]
                != adopted_authorities[self._authority_result_key(kind)][
                    "revision"
                ]["revision_id"]
            ]
        )
        result = {
            "schema_version": AUTHORITY_CONSISTENCY_SCHEMA,
            "baseline": deepcopy(working_baseline),
            "product_definition": deepcopy(product),
            "domain_catalog": deepcopy(domain),
            "target_architecture": deepcopy(architecture),
            "engineering_policy": deepcopy(policy),
            "implementation_alignment": deepcopy(alignment),
            "current_architecture_stage_id": working_baseline[
                "current_architecture_stage_id"
            ],
            "structurally_consistent": True,
            "review_state": review,
            "ready_for_stage_completion": not review["required"],
            "observed_commit": None,
            **self._scope_metadata(working_baseline),
            "candidate_base_observed_commit": (
                adopted_authorities["observed_commit"]
                if adopted_authorities is not None
                else None
            ),
            "changed_authority_kinds": changed_kinds,
            "candidate_baseline_changed": (
                adopted_authorities is not None
                and self._content_without_observation(working_baseline)
                != self._content_without_observation(
                    adopted_authorities["baseline"]
                )
            ),
            "semantic_content_machine_proven": False,
        }
        self._cache = result
        return deepcopy(result)

    def load_working_tree_candidate_for(self, investigation_ref: str | None) -> dict[str, Any]:
        """Load the current candidate against its exact investigation-time authority."""
        normalized_ref = str(investigation_ref or "").strip()
        adopted_authorities = None
        if normalized_ref and normalized_ref != "working_tree":
            prior_baseline = ProjectEngineeringBaseline(self.project, observed_ref=normalized_ref)
            if prior_baseline.engineering_baseline_exists():
                adopted_authorities = ProjectAuthorityConsistency(self.project, observed_ref=normalized_ref).load()
        return self.load_working_tree_candidate(adopted_authorities)

    def authority_candidate_snapshot(
        self,
        actual_result: Mapping[str, Any],
        *,
        investigation_ref: str | None,
        prior_adoption: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Bind an actual result to the exact candidate content it presents.

        The snapshot is derived by Strixnova before the result confirmation is
        created.  It deliberately normalizes only the revision and baseline
        metadata that the later mechanical adoption record is allowed to set.
        Everything else remains content-addressed by the confirmation.
        """

        long_lived_refs = self._core_long_lived_refs(actual_result)
        if not long_lived_refs:
            candidate_without_refs: dict[str, Any] | None = None
            try:
                candidate_without_refs = self.load_working_tree_candidate_for(
                    investigation_ref
                )
            except ProjectAuthorityConsistencyError:
                if ProjectEngineeringBaseline(
                    self.project
                ).engineering_baseline_exists():
                    raise
            else:
                self._require_candidate_without_deterministic_drift(
                    candidate_without_refs
                )
                changed_without_refs = sorted(
                    candidate_without_refs.get("changed_authority_kinds") or []
                )
                if changed_without_refs:
                    raise ProjectAuthorityConsistencyError(
                        [
                            f"工作树 {kind} 候选发生变化，但实际结果没有报告任何核心权威"
                            for kind in changed_without_refs
                        ]
                    )
            if candidate_without_refs is None:
                return {
                    "schema_version": AUTHORITY_CANDIDATE_SNAPSHOT_SCHEMA,
                    "required": False,
                    "semantic_content_machine_proven": False,
                }
            return self._build_authority_candidate_snapshot(
                candidate_without_refs,
                reported_kinds=set(AUTHORITY_KINDS),
                changed_kinds=set(),
                revision_metadata_mutable_kinds=set(),
                baseline_ref_metadata_mutable_kinds=set(),
                baseline_review_state_mutable=False,
            )

        candidate = self.load_working_tree_candidate_for(investigation_ref)
        self._require_candidate_without_deterministic_drift(candidate)
        baseline = candidate["baseline"]
        reported_kinds = self._reported_core_authority_kinds(
            long_lived_refs,
            baseline,
        )
        changed_kinds = set(candidate.get("changed_authority_kinds") or [])
        missing_changed_kinds = sorted(changed_kinds - reported_kinds)
        if missing_changed_kinds:
            raise ProjectAuthorityConsistencyError(
                [
                    f"工作树 {kind} 候选发生变化，但未包含在实际结果中"
                    for kind in missing_changed_kinds
                ]
            )

        revision_metadata_mutable_kinds: set[str] = set()
        baseline_ref_metadata_mutable_kinds: set[str] = set()
        for kind in reported_kinds:
            authority = candidate[_AUTHORITY_RESULT_KEY[kind]]
            revision = authority["revision"]
            reference = baseline["authority_refs"][kind]
            if (
                kind == "implementation_alignment"
                and (
                    revision.get("status") != "draft"
                    or revision.get("confirmed_by_owner_id") is not None
                    or revision.get("confirmed_on") is not None
                )
            ):
                proof = self.authority_adoption_record(
                    prior_adoption["actual_result"], investigation_ref=investigation_ref,
                    actual_result_confirmed=True, confirmed_on=prior_adoption["confirmed_on"],
                    mechanical_adoption_applied=True,
                ) if prior_adoption is not None else {}
                if proof.get("ready_for_atomic_commits") is not True or proof.get("mechanical_adoption_final_state_verified") is not True:
                    raise ProjectAuthorityConsistencyError(["实现对齐候选只能由当前实际结果接受事件机械定档；已定档内容必须对应本事项可核对的原定档事实"])
            if (
                kind in _ACTUAL_RESULT_ADOPTABLE_KINDS
                and revision.get("status") != "confirmed"
            ):
                revision_metadata_mutable_kinds.add(kind)
            if kind in _ACTUAL_RESULT_ADOPTABLE_KINDS and (
                reference.get("revision_id") != revision.get("revision_id")
                or reference.get("status")
                != {
                    "revision_status": "confirmed",
                    "adoption_status": "current",
                }
            ):
                baseline_ref_metadata_mutable_kinds.add(kind)

        raw_review = baseline["review_state"]
        baseline_review_state_mutable = False
        if raw_review["required"]:
            covered_kinds = reported_kinds | changed_kinds | {"code_version"}
            affected_kinds = set(raw_review["affected_authority_kinds"])
            baseline_review_state_mutable = not (
                affected_kinds - covered_kinds
                or affected_kinds
                - (_ACTUAL_RESULT_ADOPTABLE_KINDS | {"code_version"})
            )

        return self._build_authority_candidate_snapshot(
            candidate,
            reported_kinds=reported_kinds,
            changed_kinds=changed_kinds,
            revision_metadata_mutable_kinds=(
                revision_metadata_mutable_kinds
            ),
            baseline_ref_metadata_mutable_kinds=(
                baseline_ref_metadata_mutable_kinds
            ),
            baseline_review_state_mutable=baseline_review_state_mutable,
        )

    def authority_adoption_record(
        self,
        actual_result: Mapping[str, Any],
        *,
        investigation_ref: str | None,
        actual_result_confirmed: bool,
        confirmed_on: str | None = None,
        mechanical_adoption_applied: bool = False,
    ) -> dict[str, Any]:
        """Project exact metadata edits authorized by one accepted actual result.

        This projection does not decide whether an authority is semantically
        correct. It only turns an already accepted result into the exact
        revision and baseline metadata required before its local commits may be
        integrated.
        """

        long_lived_refs = self._core_long_lived_refs(actual_result)
        if not long_lived_refs:
            snapshot_proof = self.verify_working_tree_candidate_snapshot(
                actual_result,
                investigation_ref=investigation_ref,
            )
            return {
                "schema_version": AUTHORITY_ADOPTION_SCHEMA,
                "required": False,
                "authorized_by_actual_result_confirmation": bool(
                    actual_result_confirmed
                ),
                "semantic_reconfirmation_required": False,
                "ready_for_atomic_commits": True,
                "candidate_base_observed_commit": None,
                "reported_authority_kinds": [],
                "changed_authority_kinds": [],
                "project_owner_id": None,
                "baseline_path": None,
                "authority_updates": [],
                "baseline_update": None,
                "blocking_issues": [],
                "accepted_candidate_snapshot_verified": snapshot_proof[
                    "accepted_candidate_snapshot_verified"
                ],
                "mechanical_adoption_final_state_verified": True,
                "semantic_content_machine_proven": False,
            }

        candidate = self.load_working_tree_candidate_for(investigation_ref)
        baseline = candidate["baseline"]
        owner_id = str(baseline["project"]["owner_id"])
        blocking_issues: list[str] = []
        deterministic_review_reasons = (
            self._deterministic_alignment_review_reasons(candidate)
        )
        if deterministic_review_reasons:
            blocking_issues.extend(
                "实现对齐候选仍有确定性漂移：" + reason
                for reason in deterministic_review_reasons
            )
        effective_date: str | None = None
        if confirmed_on is not None:
            try:
                effective_date = date.fromisoformat(str(confirmed_on)).isoformat()
            except ValueError:
                blocking_issues.append(
                    "实际结果确认事件没有可用的 ISO（国际标准日期格式）日期，不能机械定档"
                )
        try:
            reported_kinds = self._reported_core_authority_kinds(
                long_lived_refs,
                baseline,
            )
        except ProjectAuthorityConsistencyError as error:
            reported_kinds = set()
            blocking_issues.extend(error.issues)

        snapshot_verified = self._accepted_candidate_snapshot_verified(
            actual_result,
            candidate,
            reported_kinds=reported_kinds,
            blocking_issues=blocking_issues,
        )

        changed_kinds = set(candidate.get("changed_authority_kinds") or [])
        for kind in sorted(changed_kinds - reported_kinds):
            blocking_issues.append(
                f"工作树 {kind} 候选发生变化，但未包含在已接受实际结果中"
            )

        snapshot = actual_result.get("authority_candidate_snapshot")
        revision_mutable_kinds = (
            {
                str(kind)
                for kind in snapshot.get(
                    "revision_metadata_mutable_authority_kinds", []
                )
            }
            if isinstance(snapshot, Mapping)
            else set()
        )
        baseline_ref_mutable_kinds = (
            {
                str(kind)
                for kind in snapshot.get(
                    "baseline_ref_metadata_mutable_authority_kinds", []
                )
            }
            if isinstance(snapshot, Mapping)
            else set()
        )
        baseline_review_mutable = bool(
            isinstance(snapshot, Mapping)
            and snapshot.get("baseline_review_state_mutable") is True
        )
        mechanical_mutation_required = bool(
            (revision_mutable_kinds | baseline_ref_mutable_kinds)
            & _ACTUAL_RESULT_ADOPTABLE_KINDS
        ) or baseline_review_mutable

        authority_updates: list[dict[str, Any]] = []
        for kind in sorted(reported_kinds | changed_kinds):
            authority = candidate[_AUTHORITY_RESULT_KEY[kind]]
            revision = authority["revision"]
            reference = baseline["authority_refs"][kind]
            expected_baseline_fields = {
                "revision_id": str(revision["revision_id"]),
                "status": {
                    "revision_status": "confirmed",
                    "adoption_status": "current",
                },
            }
            revision_ready = revision.get("status") == "confirmed"
            baseline_ref_ready = (
                reference.get("revision_id")
                == expected_baseline_fields["revision_id"]
                and reference.get("status")
                == expected_baseline_fields["status"]
            )
            if kind not in _ACTUAL_RESULT_ADOPTABLE_KINDS:
                if not revision_ready or not baseline_ref_ready:
                    blocking_issues.append(
                        f"{kind} 必须先通过独立长期权威决定完成确认和采用；"
                        "普通实际结果确认不能替代"
                    )
                continue
            if not mechanical_adoption_applied:
                if kind in revision_mutable_kinds and (
                    revision.get("status") != "draft"
                    or revision.get("confirmed_by_owner_id") is not None
                    or revision.get("confirmed_on") is not None
                ):
                    blocking_issues.append(
                        "实现对齐在程序机械定档前已被提前修改确认元数据"
                    )
                if kind in baseline_ref_mutable_kinds and baseline_ref_ready:
                    blocking_issues.append(
                        "项目工程基线在程序机械定档前已提前采用实现对齐"
                    )
            if not revision_ready and effective_date is None:
                blocking_issues.append(
                    "实现对齐候选需要机械确认，但实际结果确认事件日期缺失"
                )
            set_revision_fields = (
                {
                    "status": "confirmed",
                    "confirmed_by_owner_id": owner_id,
                    "confirmed_on": effective_date,
                }
                if not revision_ready and effective_date is not None
                else {}
            )
            if not revision_ready or not baseline_ref_ready:
                authority_updates.append(
                    {
                        "authority_kind": kind,
                        "path": str(reference["path"]),
                        "repository_id": reference.get("repository_id"),
                        "revision_id": str(revision["revision_id"]),
                        "set_revision_fields": set_revision_fields,
                        "set_baseline_ref_fields": expected_baseline_fields,
                    }
                )

        raw_review = baseline["review_state"]
        baseline_update: dict[str, Any] | None = None
        if raw_review["required"]:
            covered_kinds = reported_kinds | changed_kinds | {"code_version"}
            affected_kinds = set(raw_review["affected_authority_kinds"])
            uncovered = sorted(affected_kinds - covered_kinds)
            independently_governed = sorted(
                affected_kinds
                - (_ACTUAL_RESULT_ADOPTABLE_KINDS | {"code_version"})
            )
            if independently_governed:
                blocking_issues.append(
                    "工程基线仍有必须独立确认的待复核权威："
                    + "、".join(independently_governed)
                )
            elif uncovered:
                blocking_issues.append(
                    "工程基线仍有不属于本次已接受结果的待复核权威："
                    + "、".join(uncovered)
                )
            else:
                baseline_update = {
                    "path": str(baseline["_manifest_path"]),
                    "set_review_state": {
                        "required": False,
                        "reasons": [],
                        "affected_authority_kinds": [],
                    },
                }

        if (
            not mechanical_adoption_applied
            and baseline_review_mutable
            and raw_review.get("required") is not True
        ):
            blocking_issues.append(
                "项目工程基线复核状态在程序机械定档前已被提前关闭"
            )

        final_state_issues: list[str] = []
        if mechanical_adoption_applied:
            final_state_issues = self._mechanical_adoption_final_state_issues(
                candidate,
                snapshot if isinstance(snapshot, Mapping) else {},
                confirmed_on=effective_date,
            )
            blocking_issues.extend(final_state_issues)
        final_state_verified = (
            not mechanical_mutation_required
            or (
                mechanical_adoption_applied
                and not final_state_issues
            )
        )

        ready = (
            not authority_updates
            and baseline_update is None
            and final_state_verified
        )
        if ready and not blocking_issues:
            try:
                final_candidate = ProjectAuthorityConsistency(
                    self.project
                ).load()
            except ProjectAuthorityConsistencyError as error:
                blocking_issues.extend(error.issues)
            else:
                if final_candidate.get("ready_for_stage_completion") is not True:
                    blocking_issues.extend(
                        "机械定档后项目仍未闭合：" + str(reason)
                        for reason in final_candidate.get("review_state", {}).get(
                            "reasons", []
                        )
                    )
        ready = ready and not blocking_issues and actual_result_confirmed
        if not actual_result_confirmed:
            blocking_issues.append("实际结果尚未由项目负责人接受")

        return {
            "schema_version": AUTHORITY_ADOPTION_SCHEMA,
            "required": True,
            "authorized_by_actual_result_confirmation": bool(
                actual_result_confirmed
            ),
            "semantic_reconfirmation_required": any(
                "独立长期权威" in issue or "必须独立确认" in issue
                for issue in blocking_issues
            ),
            "ready_for_atomic_commits": ready,
            "candidate_base_observed_commit": candidate.get(
                "candidate_base_observed_commit"
            ),
            "reported_authority_kinds": sorted(reported_kinds),
            "changed_authority_kinds": sorted(changed_kinds),
            "project_owner_id": owner_id,
            "baseline_path": str(baseline["_manifest_path"]),
            "baseline_repository_id": self.reader.repository_id,
            "authority_updates": authority_updates,
            "baseline_update": baseline_update,
            "blocking_issues": sorted(set(blocking_issues)),
            "accepted_candidate_snapshot_verified": snapshot_verified,
            "mechanical_adoption_final_state_verified": final_state_verified,
            "semantic_content_machine_proven": False,
        }

    @staticmethod
    def _deterministic_alignment_review_reasons(
        candidate: Mapping[str, Any],
    ) -> list[str]:
        baseline = candidate["baseline"]
        expected_review_reasons = {
            *baseline["review_state"]["reasons"],
            "实现对齐修订尚未确认",
        }
        effective_review = candidate.get(
            "review_state",
            baseline["review_state"],
        )
        return sorted(
            set(effective_review["reasons"]) - expected_review_reasons
        )

    @classmethod
    def _require_candidate_without_deterministic_drift(
        cls,
        candidate: Mapping[str, Any],
    ) -> None:
        reasons = cls._deterministic_alignment_review_reasons(candidate)
        if reasons:
            raise ProjectAuthorityConsistencyError(
                [
                    "实际结果形成前必须先消除实现对齐确定性漂移："
                    + reason
                    for reason in reasons
                ]
            )

    def verify_working_tree_candidate_snapshot(
        self,
        actual_result: Mapping[str, Any],
        *,
        investigation_ref: str | None,
    ) -> dict[str, Any]:
        """Re-prove the authority snapshot before confirmation or commit."""

        snapshot = actual_result.get("authority_candidate_snapshot")
        baseline_exists = ProjectEngineeringBaseline(
            self.project
        ).engineering_baseline_exists()
        if not isinstance(snapshot, Mapping) or snapshot.get("required") is not True:
            if baseline_exists:
                raise ProjectAuthorityConsistencyError(
                    ["实际结果缺少当前项目完整权威链的精确正文快照"]
                )
            return {
                "schema_version": "strixnova.current-authority-snapshot.v1",
                "required": False,
                "accepted_candidate_snapshot_verified": True,
                "semantic_content_machine_proven": False,
            }

        candidate = self.load_working_tree_candidate_for(investigation_ref)
        blockers: list[str] = []
        reported_kinds = {
            str(kind) for kind in snapshot.get("reported_authority_kinds") or []
        }
        verified = self._accepted_candidate_snapshot_verified(
            actual_result,
            candidate,
            reported_kinds=reported_kinds,
            blocking_issues=blockers,
        )
        if not verified:
            raise ProjectAuthorityConsistencyError(
                ["当前项目权威不再等于负责人看到的实际结果快照", *blockers]
            )
        return {
            "schema_version": "strixnova.current-authority-snapshot.v1",
            "required": True,
            "accepted_candidate_snapshot_verified": True,
            "semantic_content_machine_proven": False,
        }

    def verify_integrated_candidate_snapshot(
        self,
        actual_result: Mapping[str, Any],
        *,
        integrated_commit: str,
        confirmed_on: str | None = None,
        repository_id: str | None = None,
    ) -> dict[str, Any]:
        """Re-prove the accepted authority snapshot at the integration commit."""

        snapshot = actual_result.get("authority_candidate_snapshot")
        if not isinstance(snapshot, Mapping) or snapshot.get("required") is not True:
            raise ProjectAuthorityConsistencyError(
                ["实际结果缺少可在本地集成提交复核的完整权威链快照"]
            )
        normalized_commit = str(integrated_commit or "").strip()
        if not normalized_commit:
            raise ProjectAuthorityConsistencyError(
                ["本地合入结果缺少不可变集成提交，无法复核权威快照"]
            )
        context = self.baseline_reader.context
        if repository_id is not None:
            if context is None or (context.content_versions or {}).get(repository_id) != normalized_commit:
                raise ProjectAuthorityConsistencyError(["集成核对必须选择精确仓库内容组合"])
            checker = self
        else:
            checker = ProjectAuthorityConsistency(self.project, observed_ref=normalized_commit)
        candidate = deepcopy(checker.load())
        candidate["candidate_base_observed_commit"] = snapshot.get(
            "candidate_base_observed_commit"
        )
        blockers: list[str] = []
        reported_kinds = {
            str(kind) for kind in snapshot.get("reported_authority_kinds") or []
        }
        verified = checker._accepted_candidate_snapshot_verified(
            actual_result,
            candidate,
            reported_kinds=reported_kinds,
            blocking_issues=blockers,
        )
        if not verified:
            raise ProjectAuthorityConsistencyError(
                [
                    "本地合入后的项目权威不再等于负责人接受的候选快照",
                    *blockers,
                ]
            )
        changed_kinds = set(snapshot.get("changed_authority_kinds") or [])
        mechanically_mutable = bool(
            snapshot.get("revision_metadata_mutable_authority_kinds")
            or snapshot.get("baseline_ref_metadata_mutable_authority_kinds")
            or snapshot.get("baseline_review_state_mutable") is True
        )
        adoption_required = bool(changed_kinds or mechanically_mutable)
        if adoption_required:
            final_state_issues = checker._mechanical_adoption_final_state_issues(
                candidate,
                snapshot,
                confirmed_on=confirmed_on,
            )
            if final_state_issues:
                raise ProjectAuthorityConsistencyError(final_state_issues)
            if candidate.get("ready_for_stage_completion") is not True:
                raise ProjectAuthorityConsistencyError(
                    [
                        "本地合入后的项目权威链尚未闭合",
                        *candidate.get("review_state", {}).get("reasons", []),
                    ]
                )
        return {
            "schema_version": "strixnova.integrated-authority-snapshot.v1",
            "required": True,
            "integrated_commit": normalized_commit,
            "accepted_candidate_snapshot_verified": True,
            "mechanical_adoption_final_state_verified": True,
            "authority_chain_ready_for_stage_completion": bool(
                candidate.get("ready_for_stage_completion") is True
            ),
            "blocking_issues": [],
            "semantic_content_machine_proven": False,
        }

    @staticmethod
    def _mechanical_adoption_final_state_issues(
        candidate: Mapping[str, Any],
        snapshot: Mapping[str, Any],
        *,
        confirmed_on: str | None,
    ) -> list[str]:
        """Require the exact post-adoption metadata, not only normalized bytes."""

        revision_mutable = {
            str(kind)
            for kind in snapshot.get(
                "revision_metadata_mutable_authority_kinds", []
            )
        }
        baseline_mutable = {
            str(kind)
            for kind in snapshot.get(
                "baseline_ref_metadata_mutable_authority_kinds", []
            )
        }
        baseline = candidate["baseline"]
        owner_id = str(baseline["project"]["owner_id"])
        issues: list[str] = []
        for kind in sorted(
            (revision_mutable | baseline_mutable)
            & _ACTUAL_RESULT_ADOPTABLE_KINDS
        ):
            authority = candidate[_AUTHORITY_RESULT_KEY[kind]]
            revision = authority["revision"]
            reference = baseline["authority_refs"][kind]
            if kind in revision_mutable and (
                revision.get("status") != "confirmed"
                or revision.get("confirmed_by_owner_id") != owner_id
                or not confirmed_on
                or revision.get("confirmed_on") != confirmed_on
            ):
                issues.append(
                    f"机械定档最终状态无效：{kind} 未精确绑定当前负责人和实际结果确认日期"
                )
            if kind in baseline_mutable and (
                reference.get("revision_id")
                != revision.get("revision_id")
                or reference.get("status")
                != {
                    "revision_status": "confirmed",
                    "adoption_status": "current",
                }
            ):
                issues.append(
                    f"机械定档最终状态无效：项目工程基线未精确采用 {kind}"
                )
        if snapshot.get("baseline_review_state_mutable") is True and baseline.get(
            "review_state"
        ) != {
            "required": False,
            "reasons": [],
            "affected_authority_kinds": [],
        }:
            issues.append("机械定档最终状态无效：项目工程基线复核状态尚未闭合")
        return issues

    @staticmethod
    def _core_long_lived_refs(
        actual_result: Mapping[str, Any],
    ) -> list[Mapping[str, Any]]:
        return [
            item
            for item in actual_result.get("long_lived_refs") or []
            if isinstance(item, Mapping)
            and str(item.get("artifact_type") or "")
            in _CORE_ARTIFACT_KIND_BY_TYPE
            and str(item.get("relation") or "") != "removed"
        ]

    @staticmethod
    def _reported_core_authority_kinds(
        long_lived_refs: Sequence[Mapping[str, Any]],
        baseline: Mapping[str, Any],
    ) -> set[str]:
        reported_kinds: set[str] = set()
        issues: list[str] = []
        for item in long_lived_refs:
            artifact_type = str(item["artifact_type"])
            kind = _CORE_ARTIFACT_KIND_BY_TYPE[artifact_type]
            reference = baseline["authority_refs"][kind]
            identity_field = _AUTHORITY_IDENTITY_FIELD[kind]
            if (
                str(item.get("path") or "") != str(reference["path"])
                or str(item.get("artifact_id") or "")
                != str(reference[identity_field])
            ):
                issues.append(
                    f"实际结果中的 {artifact_type} 没有指向当前候选基线的精确权威"
                )
                continue
            if kind in reported_kinds:
                issues.append(f"实际结果重复报告项目核心权威：{kind}")
                continue
            reported_kinds.add(kind)
        if issues:
            raise ProjectAuthorityConsistencyError(issues)
        return reported_kinds

    def _accepted_candidate_snapshot_verified(
        self,
        actual_result: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        reported_kinds: set[str],
        blocking_issues: list[str],
    ) -> bool:
        snapshot = actual_result.get("authority_candidate_snapshot")
        if not isinstance(snapshot, Mapping):
            blocking_issues.append("已接受实际结果缺少候选权威正文快照")
            return False
        if (
            snapshot.get("schema_version")
            != AUTHORITY_CANDIDATE_SNAPSHOT_SCHEMA
            or snapshot.get("required") is not True
        ):
            blocking_issues.append("已接受实际结果中的候选权威正文快照无效")
            return False

        try:
            snapshot_reported_kinds = {
                str(item) for item in snapshot["reported_authority_kinds"]
            }
            snapshot_changed_kinds = {
                str(item) for item in snapshot["changed_authority_kinds"]
            }
            revision_mutable_kinds = {
                str(item)
                for item in snapshot[
                    "revision_metadata_mutable_authority_kinds"
                ]
            }
            baseline_ref_mutable_kinds = {
                str(item)
                for item in snapshot[
                    "baseline_ref_metadata_mutable_authority_kinds"
                ]
            }
            baseline_review_mutable = snapshot[
                "baseline_review_state_mutable"
            ]
            if baseline_review_mutable not in {True, False}:
                raise TypeError("baseline_review_state_mutable")
            if snapshot_reported_kinds != reported_kinds:
                raise ValueError("reported_authority_kinds")
            if not revision_mutable_kinds <= snapshot_reported_kinds:
                raise ValueError(
                    "revision_metadata_mutable_authority_kinds"
                )
            if not baseline_ref_mutable_kinds <= snapshot_reported_kinds:
                raise ValueError(
                    "baseline_ref_metadata_mutable_authority_kinds"
                )
            current_snapshot = self._build_authority_candidate_snapshot(
                candidate,
                reported_kinds=snapshot_reported_kinds,
                changed_kinds=snapshot_changed_kinds,
                revision_metadata_mutable_kinds=revision_mutable_kinds,
                baseline_ref_metadata_mutable_kinds=(
                    baseline_ref_mutable_kinds
                ),
                baseline_review_state_mutable=baseline_review_mutable,
            )
        except (KeyError, TypeError, ValueError):
            blocking_issues.append("已接受实际结果中的候选权威正文快照无效")
            return False

        expected_authority_hashes = snapshot.get("authority_content_sha256")
        current_authority_hashes = current_snapshot["authority_content_sha256"]
        if "authority_repositories" in snapshot and snapshot["authority_repositories"] != current_snapshot["authority_repositories"]:
            blocking_issues.append("已接受实际结果之后权威仓库归属发生变化")
        if not isinstance(expected_authority_hashes, Mapping):
            blocking_issues.append("已接受实际结果中的候选权威正文快照无效")
            return False
        for kind in sorted(
            set(expected_authority_hashes) | set(current_authority_hashes)
        ):
            if expected_authority_hashes.get(kind) != current_authority_hashes.get(
                kind
            ):
                blocking_issues.append(
                    f"已接受实际结果之后发生正文变化：{kind}"
                )

        expected_supporting_hashes = snapshot.get("supporting_path_sha256")
        current_supporting_hashes = current_snapshot["supporting_path_sha256"]
        if not isinstance(expected_supporting_hashes, Mapping):
            blocking_issues.append("已接受实际结果中的候选权威正文快照无效")
            return False
        for path in sorted(
            set(expected_supporting_hashes) | set(current_supporting_hashes)
        ):
            if expected_supporting_hashes.get(path) != current_supporting_hashes.get(
                path
            ):
                blocking_issues.append(
                    f"已接受实际结果之后发生正文变化：{path}"
                )

        if snapshot.get("baseline_content_sha256") != current_snapshot.get(
            "baseline_content_sha256"
        ):
            blocking_issues.append(
                "已接受实际结果之后发生正文变化：项目工程基线"
            )
        if snapshot.get("candidate_base_observed_commit") != current_snapshot.get(
            "candidate_base_observed_commit"
        ):
            blocking_issues.append(
                "已接受实际结果之后候选权威的调查基点发生变化"
            )
        return not any(
            issue.startswith("已接受实际结果") for issue in blocking_issues
        )

    def _build_authority_candidate_snapshot(
        self,
        candidate: Mapping[str, Any],
        *,
        reported_kinds: set[str],
        changed_kinds: set[str],
        revision_metadata_mutable_kinds: set[str],
        baseline_ref_metadata_mutable_kinds: set[str],
        baseline_review_state_mutable: bool,
    ) -> dict[str, Any]:
        baseline = candidate["baseline"]
        authority_hashes: dict[str, str] = {}
        supporting_hashes: dict[str, str] = {}
        authority_paths = self._authority_paths(candidate)
        for kind in sorted(reported_kinds):
            root_path = str(baseline["authority_refs"][kind]["path"])
            source = self._authority_readers.get(kind, self.reader)
            normalized_authority = self._read_snapshot_bytes(
                root_path,
                "候选权威根文件",
                reader=source,
            )
            if kind in revision_metadata_mutable_kinds:
                try:
                    normalized_authority = render_yaml_value_patches(
                        normalized_authority,
                        {
                            ("revision", "status"): (
                                "<mechanical-authority-adoption>"
                            ),
                            ("revision", "confirmed_by_owner_id"): (
                                "<mechanical-authority-adoption>"
                            ),
                            ("revision", "confirmed_on"): (
                                "<mechanical-authority-adoption>"
                            ),
                        },
                    )
                except YamlMetadataPatchError as error:
                    raise ProjectAuthorityConsistencyError(
                        [f"候选权威根文件缺少可归一化元数据：{root_path}"]
                    ) from error
            authority_hashes[kind] = hashlib.sha256(
                normalized_authority
            ).hexdigest()
            for path in sorted(authority_paths[kind] - {root_path}):
                key = f"{source.repository_id}:{path}" if source.repository_id is not None else path
                supporting_hashes[key] = hashlib.sha256(
                    self._read_snapshot_bytes(
                        path,
                        "候选权威支撑文件",
                        reader=source,
                    )
                ).hexdigest()

        baseline_path = str(baseline["_manifest_path"])
        normalized_baseline = self._read_snapshot_bytes(
            baseline_path,
            "候选项目工程基线",
        )
        baseline_replacements: dict[tuple[str | int, ...], Any] = {}
        for kind in sorted(baseline_ref_metadata_mutable_kinds):
            prefix = ("authority_refs", kind)
            baseline_replacements.update(
                {
                    (*prefix, "revision_id"): (
                        "<mechanical-authority-adoption>"
                    ),
                    (*prefix, "status", "revision_status"): (
                        "<mechanical-authority-adoption>"
                    ),
                    (*prefix, "status", "adoption_status"): (
                        "<mechanical-authority-adoption>"
                    ),
                }
            )
        if baseline_review_state_mutable:
            baseline_replacements.update(
                {
                    ("review_state", "required"): (
                        "<mechanical-authority-adoption>"
                    ),
                    ("review_state", "reasons"): (
                        "<mechanical-authority-adoption>"
                    ),
                    ("review_state", "affected_authority_kinds"): (
                        "<mechanical-authority-adoption>"
                    ),
                }
            )
        if baseline_replacements:
            try:
                normalized_baseline = render_yaml_value_patches(
                    normalized_baseline,
                    baseline_replacements,
                )
            except YamlMetadataPatchError as error:
                raise ProjectAuthorityConsistencyError(
                    ["候选项目工程基线缺少可归一化采用元数据"]
                ) from error

        return {
            "schema_version": AUTHORITY_CANDIDATE_SNAPSHOT_SCHEMA,
            "required": True,
            "candidate_base_observed_commit": candidate.get(
                "candidate_base_observed_commit"
            ),
            "reported_authority_kinds": sorted(reported_kinds),
            "changed_authority_kinds": sorted(changed_kinds),
            "revision_metadata_mutable_authority_kinds": sorted(
                revision_metadata_mutable_kinds
            ),
            "baseline_ref_metadata_mutable_authority_kinds": sorted(
                baseline_ref_metadata_mutable_kinds
            ),
            "baseline_review_state_mutable": baseline_review_state_mutable,
            "authority_content_sha256": authority_hashes,
            "authority_repositories": {kind: baseline["authority_refs"][kind].get("repository_id") for kind in sorted(reported_kinds)},
            "supporting_path_sha256": supporting_hashes,
            "baseline_content_sha256": hashlib.sha256(
                normalized_baseline
            ).hexdigest(),
            "semantic_content_machine_proven": False,
        }

    def _read_snapshot_bytes(self, path: str, label: str, *, reader: GitProjectReader | None = None) -> bytes:
        try:
            return (reader or self.reader).read_canonical_bytes(path, label)
        except GitProjectReaderError as error:
            raise ProjectAuthorityConsistencyError(
                [f"{label}无法按安全 Git 规范字节读取：{path}", str(error)]
            ) from error

    @staticmethod
    def _canonical_sha256(value: Any) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()

    def governance_context(self) -> dict[str, Any]:
        """Expose deterministic context without copying authority ownership."""

        authorities = self.load()
        policy_ref = authorities["baseline"]["authority_refs"][
            "engineering_policy"
        ]
        policy_reader = self._authority_readers["engineering_policy"]
        profile = ProjectEngineeringPolicy(
            policy_reader.project,
            policy_ref["path"],
            shared_reader=policy_reader,
        ).governance_profile()
        return {
            "schema_version": "strixnova.project-governance-context.v1",
            "baseline_id": authorities["baseline"]["baseline_id"],
            "project": deepcopy(authorities["baseline"]["project"]),
            "authority_refs": deepcopy(
                authorities["baseline"]["authority_refs"]
            ),
            "current_architecture_stage_id": authorities[
                "current_architecture_stage_id"
            ],
            "governance_profile": profile,
            "review_state": deepcopy(authorities["review_state"]),
            "observed_commit": self.observed_commit,
            "semantic_content_machine_proven": False,
        }

    def engineering_governance_context(self) -> dict[str, Any]:
        """Prepare the exact read-only facts accepted by engineering governance."""

        authorities = self.load()
        baseline = authorities["baseline"]
        profile = self.governance_context()["governance_profile"]
        profile["project_engineering_baseline_path"] = baseline[
            "_manifest_path"
        ]
        profile["project_authority_paths"] = {
            "project_product_definition_path": baseline["authority_refs"][
                "product_definition"
            ]["path"],
            "project_domain_model_path": baseline["authority_refs"]["domain_model"][
                "path"
            ],
            "project_architecture_description_path": baseline["authority_refs"][
                "target_architecture"
            ]["path"],
            "project_engineering_policy_path": baseline["authority_refs"][
                "engineering_policy"
            ]["path"],
            "project_implementation_alignment_path": baseline[
                "authority_refs"
            ]["implementation_alignment"]["path"],
        }
        profile["project_authority_repositories"] = {
            kind: reference.get("repository_id")
            for kind, reference in baseline["authority_refs"].items()
        }
        profile["project_baseline_repository_id"] = self.reader.repository_id
        profile["project_authority_content_refs"] = deepcopy(self._authority_content_refs)
        active_fact_ids = {
            str(fact["fact_id"])
            for fact in authorities["domain_catalog"]["facts"]
        }
        fact_locations: dict[str, str] = {}
        for source in authorities["domain_catalog"]["sources"]:
            source_catalog = self.domain_source_catalog(
                str(source["source_id"])
            )
            fact_locations.update(
                {
                    str(fact["fact_id"]): str(source["path"])
                    for fact in source_catalog["facts"]
                    if str(fact["fact_id"]) in active_fact_ids
                }
            )
        artifact_types = {
            "product_definition": "product_governance",
            "domain_model": "domain_model",
            "target_architecture": "architecture",
            "engineering_policy": "quality_policy",
            "implementation_alignment": "domain_alignment",
        }
        identity_fields = {
            "product_definition": "product_id",
            "domain_model": "model_id",
            "target_architecture": "architecture_id",
            "engineering_policy": "policy_id",
            "implementation_alignment": "alignment_model_id",
        }
        authority_values = {
            "product_definition": authorities["product_definition"],
            "domain_model": authorities["domain_catalog"],
            "target_architecture": authorities["target_architecture"],
            "engineering_policy": authorities["engineering_policy"],
            "implementation_alignment": authorities[
                "implementation_alignment"
            ],
        }
        authority_paths = self._authority_paths(authorities)
        return {
            "schema_version": "strixnova.engineering-governance-context.v1",
            "profile": profile,
            "baseline_refs": sorted(
                {
                    "baseline:project",
                    *{
                        "baseline:authority:"
                        + kind
                        + ":"
                        + str(reference[identity_fields[kind]])
                        + ":"
                        + str(reference["revision_id"])
                        + ":"
                        + str(reference["status"]["revision_status"])
                        + ":"
                        + str(reference["status"]["adoption_status"])
                        for kind, reference in baseline["authority_refs"].items()
                        if reference["status"]
                        == {
                            "revision_status": "confirmed",
                            "adoption_status": "current",
                        }
                    },
                    *{
                        "engineering-policy:method:" + str(item["method_id"])
                        for item in authorities["engineering_policy"][
                            "method_adoptions"
                        ]
                    },
                }
            ),
            "domain_model_id": authorities["domain_catalog"]["model_id"],
            "domain_fact_locations": dict(sorted(fact_locations.items())),
            "authority_artifacts": {
                str(reference[identity_fields[kind]]): {
                    "authority_kind": kind,
                    "repository_id": reference.get("repository_id"),
                    "artifact_type": artifact_types[kind],
                    "observed_commit": self._authority_content_refs.get(kind, {}).get("observed_commit"),
                    "path": str(reference["path"]),
                    "revision_id": str(reference["revision_id"]),
                    "revision_status": str(
                        reference["status"]["revision_status"]
                    ),
                    "adoption_status": str(
                        reference["status"]["adoption_status"]
                    ),
                    "governed_paths": sorted(authority_paths[kind]),
                    "target_refs": authority_owned_target_refs(
                        kind,
                        authority_values[kind],
                    ),
                }
                for kind, reference in baseline["authority_refs"].items()
            },
            "observed_commit": self.observed_commit,
            "semantic_content_machine_proven": False,
        }

    @staticmethod
    def authority_governed_paths(
        authorities: Mapping[str, Any],
        authority_kind: str,
    ) -> list[str]:
        """Expose one candidate authority's exact schema-governed paths."""

        if authority_kind not in AUTHORITY_KINDS:
            raise ProjectAuthorityConsistencyError(
                [f"未知项目权威种类：{authority_kind}"]
            )
        return sorted(
            ProjectAuthorityConsistency._authority_paths(authorities)[
                authority_kind
            ]
        )

    def engineering_candidate_context(
        self,
        candidate: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Prepare trusted structural and code facts for one coding-agent candidate."""

        try:
            prepared_scope = prepare_repository_scope(
                self.project, candidate, self.baseline_reader.context,
            )
            repository_candidate = qualify_candidate(candidate, prepared_scope.scope)
        except (ProjectContextError, GitProjectReaderError) as error:
            return {
                "schema_version": "strixnova.engineering-candidate-context.v1",
                "repository_context": {"issues": [str(error)]},
                "code_facts": {"schema_version": "strixnova.engineering-candidate-code-facts.v1"},
                "semantic_content_machine_proven": False,
            }
        domain_references: dict[str, dict[str, Any]] = {}
        applications = candidate.get("method_applications")
        if isinstance(applications, list):
            for application_index, application in enumerate(applications):
                if not isinstance(application, Mapping):
                    continue
                raw_references = application.get("domain_fact_refs")
                if isinstance(raw_references, list):
                    for reference_index, raw_reference in enumerate(
                        raw_references
                    ):
                        path = (
                            f"method_applications[{application_index}]."
                            f"domain_fact_refs[{reference_index}]"
                        )
                        domain_references[path] = self._domain_reference_fact(
                            raw_reference
                        )
        raw_changes = candidate.get("domain_fact_changes")
        if isinstance(raw_changes, list):
            for change_index, raw_change in enumerate(raw_changes):
                if not isinstance(raw_change, Mapping):
                    continue
                path = f"domain_fact_changes[{change_index}].target_ref"
                domain_references[path] = self._domain_reference_fact(
                    raw_change.get("target_ref")
                )
        return {
            "schema_version": "strixnova.engineering-candidate-context.v1",
            "repository_context": prepared_scope.facts(),
            "code_facts": (
                ProjectImplementationAlignment.engineering_candidate_code_facts(
                    self.project,
                    repository_candidate,
                    repository_readers=prepared_scope.readers,
                    configuration_reader=prepared_scope.configuration_reader,
                )
            ),
            "domain_fact_references": domain_references,
            "domain_lineage_relations": sorted(LINEAGE_RELATIONS),
            "semantic_content_machine_proven": False,
        }

    @staticmethod
    def _domain_reference_fact(value: Any) -> dict[str, Any]:
        try:
            normalized = validate_domain_fact_reference(value)
        except ProjectDomainModelError as error:
            return {
                "raw": deepcopy(value),
                "normalized": None,
                "issues": list(error.issues),
            }
        return {
            "raw": deepcopy(value),
            "normalized": normalized,
            "issues": [],
        }

    def domain_routing_catalog(self) -> dict[str, Any]:
        """Read only the adopted domain routing catalog."""

        return self._domain_query("routing_catalog")

    def domain_collection_catalog(
        self,
        collection_id: str,
        *,
        parent_collection_id: str | None = None,
        collection_path: str | None = None,
    ) -> dict[str, Any]:
        """Read one adopted collection and its immediate routing children."""

        return self._domain_query(
            "collection_catalog",
            collection_id,
            parent_collection_id=parent_collection_id,
            collection_path=collection_path,
        )

    def domain_source_catalog(
        self,
        source_id: str,
        *,
        collection_path: str | None = None,
    ) -> dict[str, Any]:
        """Read one adopted source catalog without expanding unrelated facts."""

        return self._domain_query(
            "source_catalog",
            source_id,
            collection_path=collection_path,
        )

    def domain_fact_body(
        self,
        fact_id: str,
        *,
        source_id: str | None = None,
        collection_id: str | None = None,
        collection_path: str | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        """Read exactly one adopted canonical domain fact."""

        return self._domain_query(
            "fact_body",
            fact_id,
            source_id=source_id,
            collection_id=collection_id,
            collection_path=collection_path,
            source_path=source_path,
        )

    def domain_required_closure(
        self,
        fact_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Read the explicit dependency closure for selected adopted facts."""

        return self._domain_query("required_closure", list(fact_ids))

    def _domain_query(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        authorities = self.load()
        domain_ref = authorities["baseline"]["authority_refs"]["domain_model"]
        try:
            source = self._authority_readers["domain_model"]
            reader = ProjectDomainModel(
                source.project,
                domain_ref["path"],
                shared_reader=source,
            )
            result = getattr(reader, operation)(*args, **kwargs)
        except ProjectDomainModelError as error:
            raise ProjectAuthorityConsistencyError(error.issues) from error
        return {**deepcopy(result), "repository_id": source.repository_id}

    def invalidation_scope(
        self,
        *,
        changed_paths: Sequence[str] = (),
        changed_authority_kinds: Sequence[str] = (),
    ) -> dict[str, Any]:
        """Derive which downstream facts require review after known changes."""

        authorities = self.load()
        normalized_paths = sorted({str(path) for path in changed_paths})
        requested_kinds = {str(kind) for kind in changed_authority_kinds}
        unknown = sorted(requested_kinds - set(_DOWNSTREAM))
        if unknown:
            raise ProjectAuthorityConsistencyError(
                ["未知权威种类：" + ", ".join(unknown)]
            )
        owned_paths = self._authority_paths(authorities)
        detected: set[str] = set(requested_kinds)
        unmatched: list[str] = []
        changed_behavior_paths: list[str] = []
        for path in normalized_paths:
            matches = {
                kind for kind, paths in owned_paths.items() if path in paths
            }
            if matches:
                detected.update(matches)
            else:
                detected.add("code_version")
                unmatched.append(path)
                if ProjectImplementationAlignment.is_behavior_path(
                    authorities["implementation_alignment"],
                    path,
                ):
                    changed_behavior_paths.append(path)
        affected = {
            downstream
            for kind in detected
            for downstream in _DOWNSTREAM[kind]
        }
        return {
            "schema_version": AUTHORITY_INVALIDATION_SCHEMA,
            "changed_paths": normalized_paths,
            "directly_changed_authority_kinds": sorted(detected),
            "affected_authority_kinds": sorted(affected),
            "unmatched_paths_treated_as_code": unmatched,
            "changed_behavior_paths": changed_behavior_paths,
            "review_required": bool(affected),
            "semantic_impact_machine_proven": False,
        }

    @staticmethod
    def _check_baseline_bindings(
        baseline: Mapping[str, Any],
        product: Mapping[str, Any],
        domain: Mapping[str, Any],
        architecture: Mapping[str, Any],
        policy: Mapping[str, Any],
        alignment: Mapping[str, Any],
        issues: list[str],
    ) -> None:
        ProjectAuthorityConsistency._check_available_bindings(baseline, {
            "product_definition": product, "domain_model": domain,
            "target_architecture": architecture, "engineering_policy": policy,
            "implementation_alignment": alignment,
        }, issues)

    @staticmethod
    def _check_available_bindings(
        baseline: Mapping[str, Any], values: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        refs = baseline["authority_refs"]
        identity_fields = {
            "product_definition": "product_id",
            "domain_model": "model_id",
            "target_architecture": "architecture_id",
            "engineering_policy": "policy_id",
            "implementation_alignment": "alignment_model_id",
        }
        for kind, value in values.items():
            reference = refs[kind]
            expected = (
                reference[identity_fields[kind]],
                reference["revision_id"],
                reference["status"]["revision_status"],
            )
            actual = (value[identity_fields[kind]], value["revision"]["revision_id"], value["revision"]["status"])
            if actual != expected:
                issues.append(f"项目工程基线中的 {kind} 没有绑定所读取的精确修订")
        owner_id = baseline["project"]["owner_id"]
        product = values.get("product_definition")
        if product is not None and product["product_owner"]["owner_id"] != owner_id:
            issues.append("项目工程基线负责人和产品负责人不一致")
        for kind, authority in values.items():
            revision = authority["revision"]
            confirmer = revision.get("confirmed_by_owner_id")
            if revision["status"] == "confirmed" and confirmer != owner_id:
                issues.append(f"{kind} 的确认负责人不是项目当前负责人")

    @staticmethod
    def _authority_result_key(kind: str) -> str:
        return _AUTHORITY_RESULT_KEY[kind]

    @staticmethod
    def _content_without_observation(
        value: Mapping[str, Any],
    ) -> dict[str, Any]:
        result = deepcopy(dict(value))
        result.pop("_observed_commit", None)
        result.pop("observed_commit", None)
        return result

    @staticmethod
    def _check_candidate_against_baseline(
        baseline: Mapping[str, Any],
        candidate_by_kind: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        identity_fields = {
            "product_definition": "product_id",
            "domain_model": "model_id",
            "target_architecture": "architecture_id",
            "engineering_policy": "policy_id",
            "implementation_alignment": "alignment_model_id",
        }
        owner_id = baseline["project"]["owner_id"]
        for kind in AUTHORITY_KINDS:
            reference = baseline["authority_refs"][kind]
            candidate = candidate_by_kind[kind]
            identity_field = identity_fields[kind]
            if candidate[identity_field] != reference[identity_field]:
                issues.append(f"工作树 {kind} 候选不得更换工程基线权威身份")
                continue
            revision = candidate["revision"]
            if revision["revision_id"] == reference["revision_id"]:
                if revision["status"] != reference["status"]["revision_status"]:
                    issues.append(
                        f"工作树 {kind} 复用基线修订身份时改变了修订状态"
                    )
            elif revision.get("supersedes_revision_id") != reference["revision_id"]:
                issues.append(f"工作树 {kind} 候选没有精确承接工程基线修订")
            if revision["status"] == "confirmed" and (
                revision.get("confirmed_by_owner_id") != owner_id
            ):
                issues.append(f"工作树 {kind} 候选的确认负责人不是项目当前负责人")

    @staticmethod
    def _check_candidate_baseline(
        adopted_baseline: Mapping[str, Any],
        candidate_baseline: Mapping[str, Any],
        candidate_by_kind: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        """Keep a baseline proposal in the candidate layer until integration."""

        if candidate_baseline.get("schema_version") != adopted_baseline.get("schema_version"):
            issues.append("工作树工程基线候选必须使用同一当前合同")
        for field in ("baseline_id", "project", "_manifest_path"):
            if candidate_baseline.get(field) != adopted_baseline.get(field):
                issues.append(f"工作树工程基线候选不得改变已采用 {field}")
        identity_fields = {
            "product_definition": "product_id",
            "domain_model": "model_id",
            "target_architecture": "architecture_id",
            "engineering_policy": "policy_id",
            "implementation_alignment": "alignment_model_id",
        }
        adopted_refs = adopted_baseline["authority_refs"]
        candidate_refs = candidate_baseline["authority_refs"]
        for kind in AUTHORITY_KINDS:
            adopted_ref = adopted_refs[kind]
            candidate_ref = candidate_refs[kind]
            identity_field = identity_fields[kind]
            for field in (identity_field, "path", "repository_id"):
                if candidate_ref.get(field) != adopted_ref.get(field):
                    issues.append(
                        f"工作树工程基线候选不得改变 {kind}.{field}"
                    )
            authority_revision = candidate_by_kind[kind]["revision"]
            allowed_revision_ids = {
                str(adopted_ref["revision_id"]),
                str(authority_revision["revision_id"]),
            }
            if candidate_ref.get("revision_id") not in allowed_revision_ids:
                issues.append(
                    f"工作树工程基线候选的 {kind} 修订既非现行修订也非当前候选"
                )
            expected_revision_status = (
                authority_revision["status"]
                if candidate_ref.get("revision_id")
                == authority_revision["revision_id"]
                else adopted_ref["status"]["revision_status"]
            )
            if (
                candidate_ref.get("status", {}).get("revision_status")
                != expected_revision_status
            ):
                issues.append(
                    f"工作树工程基线候选的 {kind} 修订状态与所指修订不一致"
                )
            allowed_adoption_statuses = {
                adopted_ref["status"]["adoption_status"]
            }
            # Explicit candidate reads may point to an unconfirmed successor.
            # Integrated reads and stage completion retain their acceptance
            # requirements; identities, paths and lineage are still checked.
            if (
                adopted_ref["status"]["adoption_status"] == "current"
                and candidate_ref.get("revision_id")
                == authority_revision["revision_id"]
                and authority_revision["revision_id"]
                != adopted_ref["revision_id"]
                and authority_revision.get("supersedes_revision_id")
                == adopted_ref["revision_id"]
                and authority_revision["status"]
                in {"draft", "ready_for_confirmation"}
            ):
                allowed_adoption_statuses.add("under_review")
            candidate_adoption = candidate_ref.get("status", {}).get(
                "adoption_status"
            )
            if candidate_adoption not in allowed_adoption_statuses:
                issues.append(
                    f"工作树工程基线候选不得改变 {kind} 的采用状态"
                )

    @classmethod
    def _check_candidate_lineage(
        cls,
        adopted_authorities: Mapping[str, Any],
        candidate_by_kind: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        identity_fields = {
            "product_definition": "product_id",
            "domain_model": "model_id",
            "target_architecture": "architecture_id",
            "engineering_policy": "policy_id",
            "implementation_alignment": "alignment_model_id",
        }
        owner_id = adopted_authorities["baseline"]["project"]["owner_id"]
        for kind in AUTHORITY_KINDS:
            adopted = adopted_authorities[cls._authority_result_key(kind)]
            candidate = candidate_by_kind[kind]
            identity_field = identity_fields[kind]
            if candidate[identity_field] != adopted[identity_field]:
                issues.append(f"工作树 {kind} 候选不得更换已采用权威身份")
                continue
            adopted_revision = adopted["revision"]
            candidate_revision = candidate["revision"]
            adopted_revision_id = adopted_revision["revision_id"]
            candidate_revision_id = candidate_revision["revision_id"]
            if candidate_revision_id == adopted_revision_id:
                if cls._content_without_observation(candidate) != (
                    cls._content_without_observation(adopted)
                ):
                    issues.append(
                        f"工作树 {kind} 在复用现行修订身份时改写了权威内容"
                    )
                continue
            if (
                candidate_revision.get("supersedes_revision_id")
                != adopted_revision_id
            ):
                issues.append(
                    f"工作树 {kind} 候选没有精确承接当前已采用修订"
                )
            if candidate_revision["status"] == "confirmed" and (
                candidate_revision.get("confirmed_by_owner_id") != owner_id
            ):
                issues.append(f"工作树 {kind} 候选的确认负责人不是项目当前负责人")

    @staticmethod
    def _check_authority_chain(
        product: Mapping[str, Any],
        domain: Mapping[str, Any],
        architecture: Mapping[str, Any],
        policy: Mapping[str, Any],
        alignment: Mapping[str, Any],
        issues: list[str],
    ) -> None:
        ProjectAuthorityConsistency._check_available_chain({
            "product_definition": product, "domain_model": domain,
            "target_architecture": architecture, "engineering_policy": policy,
            "implementation_alignment": alignment,
        }, issues)

    @staticmethod
    def _check_available_chain(values: Mapping[str, Mapping[str, Any]], issues: list[str]) -> None:
        for source, field, target, identity, message in (
            ("domain_model", "product_definition_ref", "product_definition", "product_id", "领域模型没有绑定当前产品定义的精确修订"),
            ("target_architecture", "domain_model_ref", "domain_model", "model_id", "目标架构没有绑定当前领域模型的精确修订"),
            ("implementation_alignment", "domain_model_ref", "domain_model", "model_id", "实现对齐没有绑定当前领域模型的精确修订"),
            ("implementation_alignment", "architecture_ref", "target_architecture", "architecture_id", "实现对齐没有绑定当前目标架构的精确修订"),
        ):
            if source in values and target in values:
                expected = {identity: values[target][identity], "revision_id": values[target]["revision"]["revision_id"]}
                if values[source][field] != expected:
                    issues.append(message)
        if "engineering_policy" in values and "product_definition" in values:
            if values["engineering_policy"]["product_definition_ref"].get("product_id") != values["product_definition"]["product_id"]:
                issues.append("工程政策不属于当前稳定产品")

    def _review_state(
        self,
        baseline: Mapping[str, Any],
        alignment: Mapping[str, Any],
        alignment_reader: ProjectImplementationAlignment,
    ) -> dict[str, Any]:
        reasons = list(baseline["review_state"]["reasons"])
        affected = set(
            baseline["review_state"]["affected_authority_kinds"]
        )
        context = self.baseline_reader.context
        if context is not None and sum(item.membership == "member" for item in context.repositories) > 1 and alignment.get("schema_version") != "strixnova.project-implementation-alignment.v1":
            reasons.append("多仓库内容组合验证与整体阶段完成判定尚未接管")
            affected.update({"implementation_alignment", "code_version"})
        if alignment["revision"]["status"] != "confirmed":
            reasons.append("实现对齐修订尚未确认")
            affected.add("implementation_alignment")
        code = baseline["code_version"]
        alignment_code = alignment["code_snapshot"]
        alignment_version = {"repositories": alignment_code["repositories"]} if "repositories" in alignment_code else {"base_commit": alignment_code["base_commit"], "worktree_state": alignment_code["worktree_state"]}
        if "repositories" in code and "repositories" not in alignment_version:
            alignment_version = {"repositories": [{"repository_id": baseline["authority_refs"]["implementation_alignment"].get("repository_id"), **alignment_version}]}
        if code != alignment_version:
            reasons.append("项目基线与实现对齐没有引用同一代码观察基点")
            affected.update({"code_version", "implementation_alignment"})
        try:
            drift = alignment_reader.drift(
                mode="daily",
                current_stage_id=baseline["current_architecture_stage_id"],
            )
        except (
            ProjectImplementationAlignmentError,
            GitProjectReaderError,
        ) as error:
            drift_failures = getattr(error, "issues", [str(error)])
        else:
            drift_failures = drift["failures"]
        if drift_failures:
            reasons.extend(
                f"实现对齐确定性漂移：{failure}"
                for failure in drift_failures
            )
            affected.update({"code_version", "implementation_alignment"})
        required = bool(reasons or baseline["review_state"]["required"])
        return {
            "required": required,
            "reasons": sorted(set(reasons)),
            "affected_authority_kinds": sorted(affected),
            "semantic_review_performed": False,
        }

    @staticmethod
    def _authority_paths(
        authorities: Mapping[str, Any],
    ) -> dict[str, set[str]]:
        baseline = authorities["baseline"]
        result = {
            kind: {baseline["authority_refs"][kind]["path"]}
            for kind in AUTHORITY_KINDS
        }
        domain = authorities.get("domain_catalog", authorities.get("domain_model"))
        if domain is not None:
            result["domain_model"].update(item["path"] for item in domain["collections"])
            result["domain_model"].update(item["path"] for item in domain["sources"])
        for kind in ("target_architecture", "implementation_alignment"):
            if kind in authorities:
                result[kind].update(authorities[kind]["artifact_paths"].values())
        policy = authorities.get("engineering_policy")
        if policy is not None:
            result["engineering_policy"].update(
                project_engineering_policy_governed_paths(
                    baseline["authority_refs"]["engineering_policy"]["path"], policy,
                )
            )
        return result


__all__ = [
    "AUTHORITY_ADOPTION_SCHEMA",
    "AUTHORITY_CANDIDATE_SNAPSHOT_SCHEMA",
    "AUTHORITY_CONSISTENCY_SCHEMA",
    "AUTHORITY_INVALIDATION_SCHEMA",
    "DIRECTION_CONTEXT_RECOVERY_STATES",
    "ProjectAuthorityConsistency",
    "ProjectAuthorityConsistencyError",
    "authority_owned_target_refs",
    "direction_context_invalidation_issues",
    "direction_context_requires_validation",
]
