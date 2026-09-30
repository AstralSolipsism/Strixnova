"""Complete project implementation alignment and deterministic drift checks."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path, PurePosixPath
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
    repository_relative_path,
    repository_scope_root,
)
from strixnova.implementation_observation import (
    ExternalObservationProvider,
    IMPLEMENTATION_OBSERVATION_SCHEMA,
    ImplementationObservationError,
    external_observation_providers_from_plans,
    observe_project_implementation,
)
from strixnova.project_content_snapshot import repository_path_key, split_repository_path_key
from strixnova.project_architecture_description import (
    ProjectArchitectureDescription,
    ProjectArchitectureDescriptionError,
)
from strixnova.project_domain_model import (
    ProjectDomainModel,
    ProjectDomainModelError,
)
from strixnova.schema_error_reporting import (
    one_of_branch_errors,
    schema_error_message,
)


PROJECT_IMPLEMENTATION_ALIGNMENT_SCHEMA = "strixnova.project-implementation-alignment.v1"
ALIGNMENT_REVIEW_STATUS_SCHEMA = "strixnova.alignment-review-status.v1"
PASSING_DEPENDENCY_CLASSIFICATIONS = frozenset(
    {
        "internal_same_module",
        "allowed_direct",
        "allowed_read_only",
        "external_observed",
    }
)
_ARTIFACT_SCHEMAS = {
    "source_ownership": "strixnova.implementation-source-ownership.v1",
    "actual_dependencies": "strixnova.implementation-actual-dependencies.v1",
    "target_responsibilities": (
        "strixnova.implementation-target-responsibilities.v1"
    ),
    "deviations": "strixnova.implementation-deviations.v1",
}
_SCHEMA_BRANCHES = {
    PROJECT_IMPLEMENTATION_ALIGNMENT_SCHEMA: 0,
    "strixnova.implementation-source-ownership.v1": 1,
    "strixnova.implementation-actual-dependencies.v1": 2,
    "strixnova.implementation-target-responsibilities.v1": 3,
    "strixnova.implementation-deviations.v1": 4,
}
_CLASSIFICATION_FOR_MODE = {
    "direct": "allowed_direct",
    "read_only_projection": "allowed_read_only",
    "through_module": "requires_mediator_but_direct",
    "forbidden": "forbidden",
}
_IMPLEMENTATION_PRIORITY = {
    "unknown": 5,
    "drifted": 4,
    "not_implemented": 3,
    "partially_implemented": 2,
    "implemented": 1,
}


class ProjectImplementationAlignmentError(ValueError):
    """The implementation alignment or deterministic snapshot is invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目实现对齐无效")


def _schema() -> dict[str, Any]:
    resource = files("strixnova.resources").joinpath("project-implementation-alignment-v1.schema.json")
    return json.loads(resource.read_text(encoding="utf-8"))


def _schema_issues(value: Mapping[str, Any], label: str) -> list[str]:
    errors = sorted(
        Draft202012Validator(
            _schema(),
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    issues: list[str] = []
    for error in errors:
        branch_index = _SCHEMA_BRANCHES.get(value.get("schema_version"))
        for relevant_error in one_of_branch_errors(error, branch_index):
            path = ".".join(
                str(item) for item in relevant_error.absolute_path
            )
            location = f".{path}" if path else ""
            issues.append(
                f"{label}{location} 不符合当前结构合同："
                + schema_error_message(relevant_error)
            )
    return issues


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def normalized_observed_relations(
    observation: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project every observed relation without assigning architecture meaning."""

    nodes = {
        item["node_id"]: item for item in observation.get("nodes", [])
    }
    grouped: dict[
        tuple[
            str,
            str,
            str,
            str,
            str | None,
            str | None,
            str,
            str,
            str | None,
            str | None,
            str,
            str,
            tuple[str, ...],
        ],
        set[str],
    ] = {}
    issues: list[str] = []
    for relation in observation.get("relations", []):
        source = nodes.get(relation.get("source_node_id"))
        target = nodes.get(relation.get("target_node_id"))
        if not isinstance(source, Mapping) or not isinstance(target, Mapping):
            issues.append(
                "实现观察关系引用了不存在的节点："
                f"{relation.get('relation_id')}"
            )
            continue
        source_path = source.get("path")
        target_path = target.get("path")
        key = (
            str(relation["scope_id"]),
            str(relation["provider_id"]),
            str(source["node_id"]),
            str(source["node_kind"]),
            str(source_path) if isinstance(source_path, str) else None,
            (
                str(source.get("external_name"))
                if isinstance(source.get("external_name"), str)
                else None
            ),
            str(target["node_id"]),
            str(target["node_kind"]),
            str(target_path) if isinstance(target_path, str) else None,
            (
                str(target.get("external_name"))
                if isinstance(target.get("external_name"), str)
                else None
            ),
            str(relation["relation_kind"]),
            str(relation["resolution_status"]),
            tuple(str(item) for item in relation.get("conditions", [])),
        )
        grouped.setdefault(key, set()).add(str(relation["observed_name"]))
    if issues:
        raise ProjectImplementationAlignmentError(issues)
    result = [
        {
            "scope_id": scope_id,
            "provider_id": provider_id,
            "source_node_id": source_node_id,
            "source_node_kind": source_node_kind,
            "source_path": source_path,
            "source_external_name": source_external_name,
            "target_node_id": target_node_id,
            "target_node_kind": target_node_kind,
            "target_path": target_path,
            "target_external_name": target_external_name,
            "observed_names": sorted(grouped[key]),
            "relation_kind": relation_kind,
            "resolution_status": resolution_status,
            "conditions": list(conditions),
        }
        for key in sorted(
            grouped,
            key=lambda value: tuple(
                "" if item is None else item for item in value
            ),
        )
        for (
            scope_id,
            provider_id,
            source_node_id,
            source_node_kind,
            source_path,
            source_external_name,
            target_node_id,
            target_node_kind,
            target_path,
            target_external_name,
            relation_kind,
            resolution_status,
            conditions,
        ) in [key]
    ]
    if observation.get("schema_version") == "strixnova.project-implementation-observation.v1":
        repositories = {scope["scope_id"]: scope["repository_id"] for scope in observation["scopes"]}
        for entry in result:
            entry["repository_id"] = repositories[entry["scope_id"]]
    return result


def _scope_contains_path(scope: Mapping[str, Any], path: str) -> bool:
    root = PurePosixPath(str(scope["root"]))
    candidate = PurePosixPath(path)
    if candidate != root and root not in candidate.parents:
        return False
    relative = candidate.relative_to(root)
    patterns = scope.get("included_path_patterns", ["**/*"])
    return any(
        relative.as_posix() == str(pattern)
        or relative.match(str(pattern))
        for pattern in patterns
    )


class ProjectImplementationAlignment:
    """Deep interface for complete alignment, derived fact state, and drift."""

    @staticmethod
    def observe_normalized_snapshot(
        project_dir: str | Path,
        observation_scopes: Sequence[Mapping[str, Any]],
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
        external_providers: Sequence[ExternalObservationProvider] = (),
        external_execution_authorized: bool = False,
    ) -> dict[str, Any]:
        """Delegate one exact observation through the alignment Interface."""

        return observe_implementation(
            project_dir,
            observation_scopes,
            observed_ref=observed_ref,
            shared_reader=shared_reader,
            external_providers=external_providers,
            external_execution_authorized=external_execution_authorized,
        )

    @staticmethod
    def observe_candidate_snapshot(
        project_dir: str | Path,
        observation_scopes: Sequence[Mapping[str, Any]],
        *,
        external_provider_plans: Sequence[Mapping[str, Any]] = (),
        external_execution_authorized: bool = False,
    ) -> dict[str, Any]:
        """Return normalized facts without exposing process-policy objects."""

        providers = external_observation_providers_from_plans(
            external_provider_plans
        )
        return ProjectImplementationAlignment.observe_normalized_snapshot(
            project_dir,
            observation_scopes,
            external_providers=providers,
            external_execution_authorized=external_execution_authorized,
        )

    @staticmethod
    def is_behavior_path(
        alignment: Mapping[str, Any],
        path: str,
        *, repository_id: str | None = None,
    ) -> bool:
        """Return whether one repository path belongs to the recorded behavior scope."""

        if path in {
            str(item["path"])
            for item in alignment.get("source_ownership", [])
            if repository_id is None or item.get("repository_id") in {None, repository_id}
        }:
            return True
        return any(
            _scope_contains_path(scope, path)
            for scope in alignment.get("governed_source_scopes", [])
            if repository_id is None or scope.get("repository_id") in {None, repository_id}
        )

    @staticmethod
    def _owned_endpoint_module(
        record: Mapping[str, Any],
        endpoint: str,
        ownership: Mapping[str, Mapping[str, Any]],
    ) -> str | None:
        path = record.get(f"{endpoint}_path")
        if not isinstance(path, str):
            return None
        exact = ownership.get(path)
        if exact is not None and exact.get("disposition") == "owned":
            return str(exact["target_module_id"])
        if record.get(f"{endpoint}_node_kind") != "package":
            return None
        root = PurePosixPath(path)
        direct_modules = {
            str(item["target_module_id"])
            for owned_path, item in ownership.items()
            if item.get("disposition") == "owned"
            and PurePosixPath(owned_path).parent == root
        }
        if len(direct_modules) == 1:
            return next(iter(direct_modules))
        descendant_modules = {
            str(item["target_module_id"])
            for owned_path, item in ownership.items()
            if item.get("disposition") == "owned"
            and root in PurePosixPath(owned_path).parents
        }
        if len(descendant_modules) == 1:
            return next(iter(descendant_modules))
        return None

    @classmethod
    def engineering_candidate_code_facts(
        cls,
        project_dir: str | Path,
        candidate: Mapping[str, Any],
        *,
        repository_readers: Mapping[str | None, GitProjectReader] | None = None,
        configuration_reader: GitProjectReader | None = None,
    ) -> dict[str, Any]:
        """Read code facts for governance without deciding candidate meaning."""

        project = Path(project_dir).expanduser().resolve()

        def reader_for(
            reference: Any,
            label: str,
            repository_id: str | None = None,
            *,
            configuration: bool = False,
        ) -> tuple[GitProjectReader | None, str | None, list[str]]:
            if not isinstance(reference, str) or not reference.strip():
                return None, None, [f"{label} 必须是非空字符串"]
            selected = reference.strip()
            try:
                base = configuration_reader if configuration else (repository_readers or {}).get(repository_id)
                if repository_readers is not None and not configuration and base is None:
                    return None, None, [f"{label} 未绑定仓库范围"]
                if base is not None and selected == base.observed_commit:
                    return base, base.observed_commit, []
                root = base.project if base is not None else project
                if selected == "working_tree":
                    reader = GitProjectReader(root)
                else:
                    reader = GitProjectReader(root, observed_ref=selected)
                if base is not None and base.repository_id is not None:
                    reader.bind_repository(base.repository_scope(base.repository_id))
                if selected == "working_tree":
                    return reader, selected, []
                return reader, reader.observed_commit, []
            except GitProjectReaderError as error:
                return None, None, [str(error)]

        investigation_reader, resolved_investigation, investigation_issues = (
            reader_for(candidate.get("investigation_ref"), "investigation_ref", configuration=True)
        )
        immutable = (
            resolved_investigation is not None
            and resolved_investigation != "working_tree"
        )
        source_facts: list[dict[str, Any]] = []
        raw_sources = candidate.get("source_references")
        if isinstance(raw_sources, list):
            for index, raw_source in enumerate(raw_sources):
                fact: dict[str, Any] = {
                    "index": index,
                    "requested_path": None,
                    "normalized_path": None,
                    "requested_ref": None,
                    "resolved_ref": None,
                    "exists": False,
                    "line_count": None,
                    "issues": [],
                }
                if not isinstance(raw_source, Mapping):
                    source_facts.append(fact)
                    continue
                fact["requested_path"] = raw_source.get("path")
                fact["requested_ref"] = raw_source.get("observed_ref")
                source_reader, resolved_source, source_issues = reader_for(
                    raw_source.get("observed_ref"),
                    f"source_references[{index}].observed_ref",
                    raw_source.get("repository_id"),
                )
                fact["repository_id"] = raw_source.get("repository_id")
                fact["resolved_ref"] = resolved_source
                fact["issues"].extend(source_issues)
                try:
                    normalized_path = repository_relative_path(
                        raw_source.get("path"),
                        f"source_references[{index}].path",
                    )
                except GitProjectReaderError as error:
                    fact["issues"].append(str(error))
                    source_facts.append(fact)
                    continue
                fact["normalized_path"] = normalized_path
                if source_reader is not None:
                    fact["exists"] = source_reader.exists(normalized_path)
                    if fact["exists"]:
                        try:
                            content = source_reader.read_bytes(
                                normalized_path,
                                f"工程评估来源 {index}",
                            )
                        except GitProjectReaderError as error:
                            fact["issues"].append(str(error))
                        else:
                            fact["line_count"] = len(content.splitlines())
                source_facts.append(fact)

        operation_paths: dict[str, dict[str, Any]] = {}
        raw_operations = candidate.get("operations")
        if immutable and isinstance(raw_operations, list):
            for index, operation in enumerate(raw_operations):
                if not isinstance(operation, Mapping):
                    continue
                for field in ("path", "to_path"):
                    if field not in operation:
                        continue
                    key = f"operations[{index}].{field}"
                    fact = {
                        "requested_path": operation.get(field),
                        "repository_id": operation.get("repository_id"),
                        "normalized_path": None,
                        "exists": None,
                        "issues": [],
                    }
                    try:
                        normalized_path = repository_relative_path(
                            operation.get(field),
                            key,
                        )
                    except GitProjectReaderError as error:
                        fact["issues"].append(str(error))
                    else:
                        fact["normalized_path"] = normalized_path
                        operation_reader = ((repository_readers or {}).get(operation.get("repository_id"))
                                            if repository_readers is not None else investigation_reader)
                        if operation_reader is not None:
                            fact["exists"] = operation_reader.exists(
                                normalized_path
                            )
                            fact["observed_commit"] = operation_reader.observed_commit
                    operation_paths[key] = fact

        return {
            "schema_version": "strixnova.engineering-candidate-code-facts.v1",
            "investigation": {
                "requested_ref": candidate.get("investigation_ref"),
                "resolved_ref": resolved_investigation,
                "immutable": immutable,
                "issues": investigation_issues,
            },
            "source_references": source_facts,
            "operation_paths": operation_paths,
            "semantic_content_machine_proven": False,
        }

    def __init__(
        self,
        project_dir: str | Path,
        alignment_path: str,
        *,
        domain_model_path: str,
        architecture_description_path: str,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
        domain_reader: ProjectDomainModel | None = None,
        architecture_reader: ProjectArchitectureDescription | None = None,
        repository_readers: Mapping[str | None, GitProjectReader] | None = None,
    ) -> None:
        try:
            self.reader = project_reader_for_scope(
                project_dir,
                observed_ref=observed_ref,
                shared_reader=shared_reader,
            )
            self.alignment_path = repository_relative_path(
                alignment_path,
                "implementation_alignment_path",
            )
            self.domain_model_path = repository_relative_path(
                domain_model_path,
                "domain_model_path",
            )
            self.architecture_description_path = repository_relative_path(
                architecture_description_path,
                "architecture_description_path",
            )
        except GitProjectReaderError as error:
            raise ProjectImplementationAlignmentError([str(error)]) from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit
        self.repository_readers = dict(repository_readers or {self.reader.repository_id: self.reader})
        self.domain_model = domain_reader or ProjectDomainModel(
            self.project,
            self.domain_model_path,
            shared_reader=self.reader,
        )
        self.architecture = architecture_reader or ProjectArchitectureDescription(
            self.project,
            self.architecture_description_path,
            shared_reader=self.reader,
        )
        self._cache: dict[str, Any] | None = None

    @staticmethod
    def _path_key(alignment: Mapping[str, Any], record: Mapping[str, Any]) -> str:
        return repository_path_key(record.get('repository_id'), record['path'])

    def _repository_reader(self, identifier: str | None) -> GitProjectReader:
        if identifier not in self.repository_readers:
            raise ProjectImplementationAlignmentError([f"Required observation repository is unavailable: {identifier}"])
        return self.repository_readers[identifier]

    def load(self) -> dict[str, Any]:
        """Return one complete structurally valid alignment revision."""

        if self._cache is not None:
            return deepcopy(self._cache)
        try:
            model = self.reader.load_yaml(
                self.alignment_path,
                "项目实现对齐",
            )
        except GitProjectReaderError as error:
            raise ProjectImplementationAlignmentError([str(error)]) from error
        if not isinstance(model, Mapping):
            raise ProjectImplementationAlignmentError(["项目实现对齐必须是对象"])
        if model.get("schema_version") != PROJECT_IMPLEMENTATION_ALIGNMENT_SCHEMA:
            raise ProjectImplementationAlignmentError(
                ["项目实现对齐必须使用当前仓库限定的多语言观察合同"]
            )
        issues = _schema_issues(model, "项目实现对齐")
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_paths = model.get("artifact_paths")
        if isinstance(artifact_paths, Mapping):
            try:
                self.reader.prefetch(
                    [
                        repository_relative_path(
                            artifact_paths.get(name),
                            f"artifact_paths.{name}",
                        )
                        for name in _ARTIFACT_SCHEMAS
                    ]
                )
            except GitProjectReaderError as error:
                issues.append(str(error))
            for name, expected_schema in _ARTIFACT_SCHEMAS.items():
                try:
                    path = repository_relative_path(
                        artifact_paths.get(name),
                        f"artifact_paths.{name}",
                    )
                    value = self.reader.load_yaml(path, f"实现对齐产物 {name}")
                except GitProjectReaderError as error:
                    issues.append(str(error))
                    continue
                if not isinstance(value, Mapping):
                    issues.append(f"实现对齐产物 {name} 必须是对象")
                    continue
                if value.get("schema_version") != expected_schema:
                    issues.append(
                        f"实现对齐产物 {name}.schema_version 必须是 "
                        f"{expected_schema}"
                    )
                    continue
                artifact_issues = _schema_issues(
                    value,
                    f"实现对齐产物 {name}",
                )
                issues.extend(artifact_issues)
                if artifact_issues:
                    continue
                artifacts[name] = deepcopy(dict(value))
        if len(artifacts) == len(_ARTIFACT_SCHEMAS):
            self._validate_bindings(model, artifacts, issues)
            self._validate_authority_chain(model, issues)
            self._validate_coverage(model, artifacts, issues)
        if issues:
            raise ProjectImplementationAlignmentError(issues)

        result = deepcopy(dict(model))
        result.update(
            {
                "source_ownership": deepcopy(
                    artifacts["source_ownership"]["records"]
                ),
                "governed_source_scopes": deepcopy(
                    artifacts["source_ownership"]["governed_source_scopes"]
                ),
                "actual_dependencies": deepcopy(
                    artifacts["actual_dependencies"]["records"]
                ),
                "target_responsibilities": deepcopy(
                    artifacts["target_responsibilities"]["records"]
                ),
                "deviations": deepcopy(artifacts["deviations"]["deviations"]),
                "domain_fact_implementation": self._derive_fact_implementation(
                    artifacts
                ),
                "_manifest_path": self.alignment_path,
                "_observed_commit": self.observed_commit,
                "semantic_content_machine_proven": False,
            }
        )
        self._cache = result
        return deepcopy(result)

    def drift(
        self,
        *,
        mode: str = "daily",
        current_stage_id: str | None = None,
        external_providers: Sequence[ExternalObservationProvider] = (),
        external_execution_authorized: bool = False,
    ) -> dict[str, Any]:
        """Compare ledgers with one repeatable, explicitly authorized snapshot."""

        if mode not in {"daily", "stage"}:
            raise ProjectImplementationAlignmentError(
                ["漂移检查模式必须是 daily 或 stage"]
            )
        alignment = self.load()
        failures: list[str] = []
        counts: dict[str, Any] = {}
        hashes, manifest = self._governed_source_manifest(alignment)
        recorded_hashes = {
            self._path_key(alignment, item): item["sha256"]
            for item in alignment["source_ownership"]
        }
        if hashes != recorded_hashes:
            missing = sorted(set(hashes) - set(recorded_hashes))
            stale = sorted(set(recorded_hashes) - set(hashes))
            changed = sorted(
                path
                for path in set(hashes) & set(recorded_hashes)
                if hashes[path] != recorded_hashes[path]
            )
            if missing:
                failures.append("存在未归属受管实现文件：" + ", ".join(missing))
            if stale:
                failures.append("归属底账包含已不存在受管实现文件：" + ", ".join(stale))
            if changed:
                failures.append("受管实现文件变化后对齐未复核：" + ", ".join(changed))
        if (
            alignment["code_snapshot"]["governed_source_manifest_sha256"]
            != manifest
        ):
            failures.append("受管实现文件清单散列与当前快照不一致")
        try:
            for component in alignment["code_snapshot"]["repositories"]:
                component_reader = self._repository_reader(component["repository_id"])
                tip = component_reader.observed_commit or component_reader.resolve_commit("HEAD")
                if not component_reader.is_ancestor(component["base_commit"], tip):
                    failures.append(f"Repository observation base is not an ancestor: {component['repository_id']}")
        except (GitProjectReaderError, ProjectImplementationAlignmentError) as error:
            failures.append(str(error))

        # The reviewed base commit is an ancestry anchor. Current validity is
        # decided by exact governed files plus either repeatable observation or
        # an exact-source replay of a previously authorized external receipt.
        recorded_external_keys = {
            (item["scope_id"], item["language_id"])
            for item in alignment["observation_coverage"]["records"]
            if item["execution_mode"] == "authorized_tool"
        }
        supplied_provider_keys = {
            (item.scope_id, item.language_id) for item in external_providers
        }
        observation: dict[str, Any] | None = None
        reused_recorded_observation = bool(recorded_external_keys) and not (
            external_providers
        )
        if reused_recorded_observation:
            failures.extend(
                self._recorded_observation_source_issues(alignment)
            )
        elif recorded_external_keys - supplied_provider_keys:
            missing_providers = sorted(
                recorded_external_keys - supplied_provider_keys
            )
            failures.append(
                "重新执行实现观察时缺少已记录的外部提供者："
                + ", ".join(
                    f"{scope_id}/{language_id}"
                    for scope_id, language_id in missing_providers
                )
            )
        else:
            try:
                observation = observe_project_implementation(self.repository_readers, alignment["observation_scopes"], external_providers=external_providers, external_execution_authorized=external_execution_authorized)
            except ImplementationObservationError as error:
                failures.extend(error.issues)
        if observation is not None:
            current_coverage = {
                "contract_version": observation["schema_version"],
                "overall_status": observation["overall_coverage_status"],
                "source_manifest_sha256": observation[
                    "source_manifest_sha256"
                ],
                "observation_snapshot_sha256": observation[
                    "observation_snapshot_sha256"
                ],
                "observed_paths": observation["observed_paths"],
                "records": observation["coverage"],
                "provider_receipts": observation["provider_receipts"],
            }
            if current_coverage != alignment["observation_coverage"]:
                failures.append(
                    "实现观察范围、能力、覆盖或关系结果变化后对齐尚未复核"
                )
            if observation["overall_coverage_status"] != "complete":
                incomplete = [
                    f"{item['scope_id']}/{item['language_id']}={item['status']}"
                    for item in observation["coverage"]
                    if item["status"] != "complete"
                ]
                failures.append(
                    "实现观察未达到完整覆盖：" + ", ".join(incomplete)
                )
            scanned = normalized_observed_relations(observation)
            projection_fields = (
                "scope_id",
                "provider_id",
                "source_node_id",
                "source_node_kind",
                "source_path",
                "source_external_name",
                "target_node_id",
                "target_node_kind",
                "target_path",
                "target_external_name",
                "observed_names",
                "relation_kind",
                "resolution_status",
                "conditions",
            )
            projection_fields += ("repository_id",)
            scanned_projection = [
                {field: item[field] for field in projection_fields}
                for item in scanned
            ]
            recorded_projection = sorted(
                (
                    {field: item[field] for field in projection_fields}
                    for item in alignment["actual_dependencies"]
                ),
                key=lambda item: (
                    item["scope_id"],
                    item["provider_id"],
                    item["source_node_id"],
                    item["target_node_id"],
                    item["relation_kind"],
                    item["resolution_status"],
                    tuple(item["conditions"]),
                ),
            )
            if scanned_projection != recorded_projection:
                failures.append("实际实现关系变化后对齐底账尚未复核")
            counts["observation_coverage_status"] = observation[
                "overall_coverage_status"
            ]
            counts["observed_nodes"] = len(observation["nodes"])
            counts["observed_relations"] = len(observation["relations"])
            counts["observation_gaps"] = sum(
                len(item["gaps"]) for item in observation["coverage"]
            )
        elif reused_recorded_observation:
            recorded_coverage = alignment["observation_coverage"]
            counts["observation_coverage_status"] = recorded_coverage[
                "overall_status"
            ]
            counts["observed_relations"] = sum(
                item["relation_count"] for item in recorded_coverage["records"]
            )
            counts["observation_gaps"] = sum(
                len(item["gaps"]) for item in recorded_coverage["records"]
            )
            counts["observation_evidence_mode"] = (
                "recorded_exact_source_replay"
            )
        failures.extend(self._dependency_classification_issues(alignment))
        if current_stage_id is not None:
            failures.extend(
                self._implementation_stage_issues(
                    alignment,
                    current_stage_id,
                )
            )

        counts["governed_source_files"] = len(hashes)
        counts["owned_source_files"] = sum(
            item["disposition"] == "owned"
            for item in alignment["source_ownership"]
        )
        counts["excluded_source_files"] = sum(
            item["disposition"] == "excluded"
            for item in alignment["source_ownership"]
        )
        classifications = Counter(
            item["classification"] for item in alignment["actual_dependencies"]
        )
        counts["classified_relations"] = len(alignment["actual_dependencies"])
        counts["relation_classifications"] = dict(sorted(classifications.items()))
        counts["relation_violations"] = sum(
            count
            for classification, count in classifications.items()
            if classification not in PASSING_DEPENDENCY_CLASSIFICATIONS
        )
        counts["target_responsibilities"] = len(
            alignment["target_responsibilities"]
        )
        counts["target_responsibility_statuses"] = dict(
            sorted(
                Counter(
                    item["status"]
                    for item in alignment["target_responsibilities"]
                ).items()
            )
        )
        counts["deviations"] = len(alignment["deviations"])
        if mode == "stage":
            self._stage_failures(alignment, failures)
        return {
            "schema_version": "strixnova.architecture-gate-result.v1",
            "mode": mode,
            "passed": not failures,
            "counts": counts,
            "failures": sorted(set(failures)),
            "semantic_content_machine_proven": False,
        }

    def review_status_at(self, target_ref: str) -> dict[str, Any]:
        """Report deterministic staleness without claiming semantic review."""

        if self.observed_commit is None:
            raise ProjectImplementationAlignmentError(
                ["对齐时效判断必须从不可变 Git 提交读取"]
            )
        try:
            changed_paths = self.reader.changed_paths_between(target_ref)
        except GitProjectReaderError as error:
            raise ProjectImplementationAlignmentError([str(error)]) from error
        alignment = self.load()
        governed_paths = {
            item["path"] for item in alignment["source_ownership"]
        } | {
            self.alignment_path,
            self.domain_model_path,
            self.architecture_description_path,
            *alignment["artifact_paths"].values(),
        }
        relevant = sorted(set(changed_paths) & governed_paths)
        return {
            "schema_version": ALIGNMENT_REVIEW_STATUS_SCHEMA,
            "alignment_model_id": alignment["alignment_model_id"],
            "alignment_revision_id": alignment["revision"]["revision_id"],
            "observed_commit": self.observed_commit,
            "target_commit": self.reader.resolve_commit(target_ref),
            "changed_paths": changed_paths,
            "relevant_changed_paths": relevant,
            "review_status": "needs_review" if relevant else "evidence_current",
            "semantic_correctness_proven": False,
        }

    def _validate_bindings(
        self,
        model: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        model_id = model.get("alignment_model_id")
        revision_id = (model.get("revision") or {}).get("revision_id")
        for name, artifact in artifacts.items():
            if artifact.get("alignment_model_id") != model_id:
                issues.append(f"实现对齐产物 {name} 稳定身份与根文件不一致")
            if artifact.get("alignment_revision_id") != revision_id:
                issues.append(f"实现对齐产物 {name} 修订身份与根文件不一致")
        revision = model.get("revision") or {}
        if revision.get("status") == "confirmed" and model.get("unresolved_items"):
            issues.append("已确认实现对齐不得保留未决事项")
        responsibilities = artifacts.get("target_responsibilities", {}).get(
            "records", []
        )
        for record in responsibilities:
            for evidence in record.get("evidence", []):
                if evidence.get("kind") not in {"source", "test", "artifact"}:
                    continue
                try:
                    path = repository_relative_path(
                        evidence.get("ref"),
                        "target_responsibilities.evidence.ref",
                    )
                except GitProjectReaderError as error:
                    issues.append(str(error))
                    continue
                if not self.reader.exists(path):
                    issues.append(
                        "目标责任证据路径不存在："
                        f"{record.get('target_id')} -> {path}"
                    )

    def _validate_authority_chain(
        self,
        model: Mapping[str, Any],
        issues: list[str],
    ) -> None:
        try:
            domain = self.domain_model.catalog()
            architecture = self.architecture.load()
        except (ProjectDomainModelError, ProjectArchitectureDescriptionError) as error:
            issues.extend(error.issues)
            return
        expected_domain = {
            "model_id": domain["model_id"],
            "revision_id": domain["revision"]["revision_id"],
        }
        expected_architecture = {
            "architecture_id": architecture["architecture_id"],
            "revision_id": architecture["revision"]["revision_id"],
        }
        if model.get("domain_model_ref") != expected_domain:
            issues.append("实现对齐绑定的领域模型不是所读取的精确修订")
        if model.get("architecture_ref") != expected_architecture:
            issues.append("实现对齐绑定的目标架构不是所读取的精确修订")
        if (model.get("revision") or {}).get("status") in {
            "ready_for_confirmation",
            "confirmed",
        }:
            if domain["revision"]["status"] != "confirmed":
                issues.append("实现对齐进入确认阶段前领域模型必须已确认")
            if architecture["revision"]["status"] != "confirmed":
                issues.append("实现对齐进入确认阶段前目标架构必须已确认")

    def _validate_coverage(
        self,
        model: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        architecture = self.architecture.load()
        module_ids = {item["module_id"] for item in architecture["modules"]}
        stages = {
            item["stage_id"]: item
            for item in architecture["implementation_stages"]
        }
        observation_scopes = {
            item["scope_id"]: item for item in model["observation_scopes"]
        }
        if len(observation_scopes) != len(model["observation_scopes"]):
            issues.append("实现观察范围身份不得重复")
        governed_scopes = {
            item["scope_id"]: item
            for item in artifacts["source_ownership"][
                "governed_source_scopes"
            ]
        }
        if len(governed_scopes) != len(
            artifacts["source_ownership"]["governed_source_scopes"]
        ):
            issues.append("受管实现范围身份不得重复")
        if set(governed_scopes) != set(observation_scopes):
            issues.append("受管实现范围必须与观察计划范围身份完全一致")

        expected_coverage = {
            (scope["scope_id"], language)
            for scope in model["observation_scopes"]
            for language in scope["languages"]
        }
        coverage_records = model["observation_coverage"]["records"]
        actual_coverage = {
            (item["scope_id"], item["language_id"])
            for item in coverage_records
        }
        if len(actual_coverage) != len(coverage_records):
            issues.append("观察覆盖记录不得重复")
        if actual_coverage != expected_coverage:
            issues.append("观察覆盖记录必须恰好覆盖每个范围与声明语言")
        receipts = model["observation_coverage"]["provider_receipts"]
        receipt_keys = {
            (item["scope_id"], item["language_id"]) for item in receipts
        }
        if len(receipt_keys) != len(receipts):
            issues.append("实现观察提供者回执不得重复")
        if receipt_keys != expected_coverage:
            issues.append("实现观察提供者回执必须恰好覆盖每个范围与声明语言")
        observed_paths = model["observation_coverage"].get(
            "observed_paths", {}
        )
        if not isinstance(observed_paths, Mapping):
            observed_paths = {}
        normalized_observed_paths: dict[str, str] = {}
        for raw_path, digest in observed_paths.items():
            try:
                identifier, path = split_repository_path_key(raw_path)
            except (GitProjectReaderError, ValueError) as error:
                issues.append(str(error))
                continue
            normalized_observed_paths[raw_path] = digest
            if not any((scope.get('repository_id') == identifier and (PurePosixPath(path) == PurePosixPath(scope['root']) or PurePosixPath(scope['root']) in PurePosixPath(path).parents) for scope in observation_scopes.values())):
                issues.append(f"实现观察路径不属于任何声明范围：{path}")
        if model["observation_coverage"]["source_manifest_sha256"] != (
            _canonical_hash(normalized_observed_paths)
        ):
            issues.append("实现观察源码清单散列与记录路径不一致")
        statuses = [item["status"] for item in coverage_records]
        for item in coverage_records:
            required = set(item["required_relation_kinds"])
            supported = set(item["supported_relation_kinds"])
            if not required <= supported and item["status"] == "complete":
                issues.append(
                    "完整观察覆盖不得缺少必需关系种类："
                    f"{item['scope_id']}/{item['language_id']}"
                )
            if item["status"] == "complete" and (
                item["source_file_count"] == 0
                or item["limitations"]
                or item["gaps"]
            ):
                issues.append(
                    "完整观察覆盖必须包含实际源码且没有限制或缺口："
                    f"{item['scope_id']}/{item['language_id']}"
                )
        receipts_by_key = {
            (item["scope_id"], item["language_id"]): item
            for item in receipts
        }
        for item in coverage_records:
            receipt = receipts_by_key.get(
                (item["scope_id"], item["language_id"])
            )
            if receipt is None:
                continue
            for field in (
                "provider_id",
                "provider_version",
                "execution_mode",
                "status",
            ):
                if receipt[field] != item[field]:
                    issues.append(
                        "观察覆盖与提供者回执身份不一致："
                        f"{item['scope_id']}/{item['language_id']}/{field}"
                    )
        if statuses:
            expected_status = max(
                statuses,
                key={
                    "complete": 0,
                    "partial": 1,
                    "unavailable": 2,
                    "failed": 3,
                }.__getitem__,
            )
            if model["observation_coverage"]["overall_status"] != expected_status:
                issues.append("总体观察覆盖状态必须等于各范围最保守状态")
        revision_status = model["revision"]["status"]
        if revision_status in {"ready_for_confirmation", "confirmed"}:
            if model["unresolved_items"]:
                issues.append("实现对齐进入确认阶段前不得保留未决事项")
            if model["observation_coverage"]["overall_status"] != "complete":
                issues.append("实现对齐进入确认阶段前观察覆盖必须完整")
            if any(item["gaps"] for item in coverage_records):
                issues.append("实现对齐进入确认阶段前不得保留观察缺口")

        ownership = artifacts["source_ownership"]["records"]
        ownership_paths = [self._path_key(model, item) for item in ownership]
        if len(ownership_paths) != len(set(ownership_paths)):
            issues.append("受管实现文件归属路径不得重复")
        for record in ownership:
            try:
                repository_relative_path(record["path"], "source_ownership.path")
            except GitProjectReaderError as error:
                issues.append(str(error))
            scope = governed_scopes.get(record["scope_id"])
            if scope is not None and scope.get('repository_id') != record.get('repository_id'):
                issues.append(f"Source ownership repository does not match its scope: {record['path']}")
            if scope is None:
                issues.append(
                    f"受管实现文件引用未知观察范围：{record['path']}"
                )
            elif not _scope_contains_path(scope, record["path"]):
                issues.append(
                    f"受管实现文件不在声明范围或包含模式内：{record['path']}"
                )
            if record["disposition"] == "owned":
                if record["target_module_id"] not in module_ids:
                    issues.append(
                        f"受管实现文件引用未知目标模块：{record['path']}"
                    )
                stage = stages.get(record["implementation_stage_id"])
                if stage is None:
                    issues.append(
                        f"受管实现文件引用未知实施阶段：{record['path']}"
                    )
                elif record["target_module_id"] not in stage["module_ids"]:
                    issues.append(
                        "受管实现文件实施阶段不包含其目标模块："
                        + record["path"]
                    )
            if (
                record["current_status"] == "unknown"
                and not record["deviation_ids"]
            ):
                issues.append(
                    "未知受管实现文件状态必须引用具体偏离和解决计划："
                    + record["path"]
                )

        dependency_keys: set[tuple[Any, ...]] = set()
        for record in artifacts["actual_dependencies"]["records"]:
            if observation_scopes.get(record['scope_id'], {}).get('repository_id') != record.get('repository_id'):
                issues.append("Dependency repository does not match its observation scope")
            dependency_key = (
                record["scope_id"],
                record["provider_id"],
                record["source_node_id"],
                record["target_node_id"],
                record["relation_kind"],
                record["resolution_status"],
                tuple(record["conditions"]),
            )
            if dependency_key in dependency_keys:
                issues.append(
                    "实际实现关系节点边不得重复："
                    f"{record['source_node_id']} -> {record['target_node_id']}"
                )
            dependency_keys.add(dependency_key)
            if record["scope_id"] not in observation_scopes:
                issues.append(
                    "实现关系引用未知观察范围："
                    f"{record['source_path']} -> {record['target_path']}"
                )
            if record["source_external_name"] is not None:
                issues.append(
                    "实现关系来源必须是范围内实现节点："
                    + record["source_path"]
                )
            resolution = record["resolution_status"]
            if resolution == "resolved_internal":
                if (
                    record["target_path"] is None
                    or record["target_module_id"] is None
                    or record["target_external_name"] is not None
                ):
                    issues.append(
                        "已解析内部关系必须具有内部目标路径和模块："
                        f"{record['source_path']} -> {record['target_path']}"
                    )
            elif resolution == "external":
                if (
                    record["target_path"] is not None
                    or record["target_module_id"] is not None
                    or record["target_external_name"] is None
                    or record["classification"] != "external_observed"
                ):
                    issues.append(
                        "外部关系必须保留外部目标且不得伪造内部归属："
                        + record["source_path"]
                    )
            elif record["classification"] not in {
                "unresolved_observation",
                "ambiguous_observation",
            }:
                issues.append(
                    "未解析或歧义关系必须使用保守观察分类："
                    + record["source_path"]
                )
            passing = (
                record["classification"]
                in PASSING_DEPENDENCY_CLASSIFICATIONS
            )
            target_label = (
                record["target_path"] or record["target_external_name"]
            )
            if passing and record["deviation_ids"]:
                issues.append(
                    "符合目标关系的实现关系不得虚挂偏离："
                    f"{record['source_path']} -> {target_label}"
                )
            if not passing and not record["deviation_ids"]:
                issues.append(
                    "偏离、未解析或歧义实现关系必须引用具体偏离："
                    f"{record['source_path']} -> {target_label}"
                )

        expected_targets = {
            ("module", item["module_id"]) for item in architecture["modules"]
        } | {
            ("relationship", item["relationship_id"])
            for item in architecture["relationships"]
        } | {
            ("constraint", item["constraint_id"])
            for item in architecture["constraints"]
        }
        responsibilities = artifacts["target_responsibilities"]["records"]
        actual_targets = {
            (item["target_kind"], item["target_id"])
            for item in responsibilities
        }
        if len(actual_targets) != len(responsibilities):
            issues.append("目标责任底账不得重复")
        if actual_targets != expected_targets:
            issues.append("目标责任底账必须恰好覆盖全部模块、关系和约束")

        deviations = {
            item["deviation_id"]
            for item in artifacts["deviations"]["deviations"]
        }
        referenced: set[str] = set()
        for collection_name, records_name in (
            ("source_ownership", "records"),
            ("actual_dependencies", "records"),
            ("target_responsibilities", "records"),
        ):
            for record in artifacts[collection_name][records_name]:
                referenced.update(record["deviation_ids"])
        if referenced != deviations:
            missing = sorted(referenced - deviations)
            unused = sorted(deviations - referenced)
            if missing:
                issues.append("底账引用了未定义偏离：" + ", ".join(missing))
            if unused:
                issues.append("偏离没有被任何底账使用：" + ", ".join(unused))

    def _derive_fact_implementation(
        self,
        artifacts: Mapping[str, Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        architecture = self.architecture.load()
        responsibility_by_id = {
            item["target_id"]: item
            for item in artifacts["target_responsibilities"]["records"]
        }
        result: list[dict[str, Any]] = []
        for disposition in architecture["domain_fact_dispositions"]:
            disposition_type = disposition["disposition_type"]
            if disposition_type == "no_independent_implementation":
                status = "no_independent_implementation"
                target_ids: list[str] = []
            elif disposition_type == "primary_module":
                target_ids = [disposition["primary_module_id"]]
                status = max(
                    (responsibility_by_id[item]["status"] for item in target_ids),
                    key=_IMPLEMENTATION_PRIORITY.__getitem__,
                )
            elif disposition_type == "module_relationship":
                target_ids = list(disposition["relationship_ids"])
                status = max(
                    (responsibility_by_id[item]["status"] for item in target_ids),
                    key=_IMPLEMENTATION_PRIORITY.__getitem__,
                )
            elif disposition_type == "architecture_constraint":
                target_ids = list(disposition["constraint_ids"])
                status = max(
                    (responsibility_by_id[item]["status"] for item in target_ids),
                    key=_IMPLEMENTATION_PRIORITY.__getitem__,
                )
            else:
                raise ProjectImplementationAlignmentError(
                    [f"未知领域事实架构处置：{disposition_type}"]
                )
            result.append(
                {
                    "domain_fact_id": disposition["domain_fact_id"],
                    "implementation_status": status,
                    "derived_from_target_ids": target_ids,
                    "manually_asserted": False,
                }
            )
        return result

    def _governed_source_manifest(
        self,
        alignment: Mapping[str, Any],
    ) -> tuple[dict[str, str], str]:
        groups: dict[str | None, set[str]] = {}
        for scope in alignment["governed_source_scopes"]:
            identifier = scope.get('repository_id')
            reader = self._repository_reader(identifier)
            root = repository_scope_root(
                scope["root"],
                "governed_source_scopes.root",
            )
            groups.setdefault(identifier, set()).update(
                path
                for path in reader.tracked_paths(root)
                if _scope_contains_path(scope, path)
                and "__pycache__" not in PurePosixPath(path).parts
            )
        hashes = {}
        for identifier, paths in groups.items():
            reader = self._repository_reader(identifier)
            hashes.update({repository_path_key(identifier, path): hashlib.sha256(content).hexdigest() for path, content in reader.iter_canonical_files(sorted(paths), "受管实现文件")})
        content = "".join(
            f"{path}:{digest}\n" for path, digest in sorted(hashes.items())
        )
        return hashes, hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _recorded_observation_source_issues(
        self,
        alignment: Mapping[str, Any],
    ) -> list[str]:
        recorded = alignment["observation_coverage"]["observed_paths"]
        current: dict[str, str] = {}
        issues: list[str] = []
        for key, expected_hash in sorted(recorded.items()):
            try:
                identifier, path = split_repository_path_key(key)
                current[key] = hashlib.sha256(self._repository_reader(identifier).read_canonical_bytes(path, "Recorded repository observation source")).hexdigest()
            except (GitProjectReaderError, ValueError) as error:
                issues.append(str(error))
                continue
            if current[key] != expected_hash:
                issues.append(f"外部提供者观察过的源码已变化，必须重新授权观察：{key}")
        if set(current) != set(recorded):
            issues.append("外部提供者观察过的源码集合已不完整")
        if _canonical_hash(current) != alignment["observation_coverage"]["source_manifest_sha256"]:
            issues.append("已记录外部观察源码清单散列与当前精确源码不一致")
        return issues

    def _dependency_classification_issues(
        self,
        alignment: Mapping[str, Any],
    ) -> list[str]:
        issues: list[str] = []
        architecture = self.architecture.load()
        relationships = {
            (item["from_module_id"], item["to_module_id"]): item
            for item in architecture["relationships"]
        }
        for record in alignment["actual_dependencies"]:
            ownership = {item["path"]: item for item in alignment["source_ownership"] if item.get("repository_id") == record.get("repository_id")}
            target_label = (
                record["target_path"] or record["target_external_name"]
            )
            source_module = self._owned_endpoint_module(
                record,
                "source",
                ownership,
            )
            if source_module is None:
                issues.append(
                    "实现关系来源没有唯一目标模块归属："
                    f"{record['source_path']} -> {target_label}"
                )
                continue
            if record["source_module_id"] != source_module:
                issues.append(
                    "实现关系记录的来源模块与文件归属不一致："
                    f"{record['source_path']} -> {target_label}"
                )
                continue
            resolution = record["resolution_status"]
            if resolution == "external":
                if (
                    record["classification"] != "external_observed"
                    or record["target_module_id"] is not None
                    or record["target_relationship_id"] is not None
                ):
                    issues.append(
                        "外部实现关系分类与观察状态不一致："
                        f"{record['source_path']} -> {target_label}"
                    )
                continue
            if resolution in {"unresolved", "ambiguous"}:
                expected = (
                    "unresolved_observation"
                    if resolution == "unresolved"
                    else "ambiguous_observation"
                )
                if (
                    record["classification"] != expected
                    or record["target_module_id"] is not None
                    or record["target_relationship_id"] is not None
                ):
                    issues.append(
                        "未解析或歧义实现关系没有保持保守分类："
                        f"{record['source_path']} -> {target_label}"
                    )
                continue
            target_module = self._owned_endpoint_module(
                record,
                "target",
                ownership,
            )
            if target_module is None:
                issues.append(
                    "内部实现关系目标没有唯一目标模块归属："
                    f"{record['source_path']} -> {target_label}"
                )
                continue
            if record["target_module_id"] != target_module:
                issues.append(
                    "实现关系记录的目标模块与文件归属不一致："
                    f"{record['source_path']} -> {target_label}"
                )
                continue
            if source_module == target_module:
                expected_classification = "internal_same_module"
                expected_relationship_id = None
            else:
                relationship = relationships.get((source_module, target_module))
                if relationship is None:
                    expected_classification = "undeclared"
                    expected_relationship_id = None
                else:
                    expected_classification = _CLASSIFICATION_FOR_MODE[
                        relationship["mode"]
                    ]
                    expected_relationship_id = relationship["relationship_id"]
            if (
                record["classification"] != expected_classification
                or record["target_relationship_id"] != expected_relationship_id
            ):
                issues.append(
                    "内部实现关系分类与目标架构不一致："
                    f"{record['source_path']} -> {target_label}"
                )
        return issues

    def _implementation_stage_issues(
        self,
        alignment: Mapping[str, Any],
        current_stage_id: str,
    ) -> list[str]:
        architecture = self.architecture.load()
        stages = {
            item["stage_id"]: item
            for item in architecture["implementation_stages"]
        }
        current = stages.get(current_stage_id)
        if current is None:
            return ["当前实施阶段不属于目标架构"]
        issues: list[str] = []
        for record in alignment["source_ownership"]:
            if record["disposition"] != "owned":
                continue
            assigned = stages[record["implementation_stage_id"]]
            if assigned["order"] > current["order"] and not record[
                "deviation_ids"
            ]:
                issues.append(
                    "未来阶段受管实现文件已存在但没有记录提前实现偏离："
                    + record["path"]
                )
        return issues

    @staticmethod
    def _stage_failures(
        alignment: Mapping[str, Any],
        failures: list[str],
    ) -> None:
        if alignment["revision"]["status"] != "confirmed":
            failures.append(
                "阶段完成门要求实现对齐为已确认，当前为 "
                + alignment["revision"]["status"]
            )
        if alignment["observation_coverage"]["overall_status"] != "complete":
            failures.append(
                "阶段完成门要求实现观察完整，当前为 "
                + alignment["observation_coverage"]["overall_status"]
            )
        non_aligned = [
            item["path"]
            for item in alignment["source_ownership"]
            if item["disposition"] == "owned"
            and item["current_status"] != "aligned"
        ]
        if non_aligned:
            failures.append(
                f"阶段完成门仍有 {len(non_aligned)} 个受管实现文件未对齐"
            )
        violations = [
            item
            for item in alignment["actual_dependencies"]
            if item["classification"] not in PASSING_DEPENDENCY_CLASSIFICATIONS
        ]
        if violations:
            failures.append(
                f"阶段完成门仍有 {len(violations)} 条实际实现关系偏离"
            )
        incomplete = [
            item
            for item in alignment["target_responsibilities"]
            if item["status"] != "implemented"
        ]
        if incomplete:
            failures.append(
                f"阶段完成门仍有 {len(incomplete)} 项目标责任未实现"
            )
        if alignment["deviations"]:
            failures.append(
                f"阶段完成门仍有 {len(alignment['deviations'])} 项已知偏离未关闭"
            )


__all__ = [
    "ALIGNMENT_REVIEW_STATUS_SCHEMA",
    "PASSING_DEPENDENCY_CLASSIFICATIONS",
    "PROJECT_IMPLEMENTATION_ALIGNMENT_SCHEMA",
    "ProjectImplementationAlignment",
    "ProjectImplementationAlignmentError",
    "normalized_observed_relations",
]
