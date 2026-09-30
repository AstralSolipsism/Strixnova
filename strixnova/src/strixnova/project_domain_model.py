"""Read one typed second-version project domain authority."""

from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
import re
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
    repository_relative_path,
)
from strixnova.schema_error_reporting import (
    one_of_branch_errors,
    schema_error_message,
)


DOMAIN_MODEL_SCHEMA = "strixnova.project-domain-model.v1"
DOMAIN_COLLECTION_SCHEMA = "strixnova.project-domain-collection.v1"
DOMAIN_YAML_SOURCE_SCHEMA = "strixnova.project-domain-source.v1"
DOMAIN_FACT_REFERENCE_SCHEMA = "strixnova.domain-fact-reference.v1"

ACTIVE_FACT_STATUSES = frozenset(
    {"candidate", "draft", "ready_for_confirmation", "confirmed"}
)
TOMBSTONE_FACT_STATUSES = frozenset({"superseded", "retired"})
LINEAGE_RELATIONS = frozenset(
    {"superseded_by", "split_into", "merged_into"}
)

_MODEL_ID = re.compile(r"MODEL-[0-9A-F]{16}")
_FACT_ID = re.compile(r"FACT-[0-9A-F]{16}")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")


class ProjectDomainModelError(ValueError):
    """The project domain model is missing or structurally invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目领域模型无效")


def _schema(name: str) -> dict[str, Any]:
    resource = files("strixnova.resources").joinpath(name)
    return json.loads(resource.read_text(encoding="utf-8"))


def _schema_issues(
    name: str,
    value: Any,
    label: str,
) -> list[str]:
    errors = sorted(
        Draft202012Validator(
            _schema(name),
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    issues: list[str] = []
    for error in errors:
        expected_branch: int | None = None
        if (
            error.validator == "oneOf"
            and isinstance(error.instance, Mapping)
            and error.context
        ):
            status = error.instance.get("status")
            expected_branch = (
                0
                if status in ACTIVE_FACT_STATUSES
                else 1 if status in TOMBSTONE_FACT_STATUSES else None
            )
        relevant_errors = one_of_branch_errors(error, expected_branch)
        for relevant_error in relevant_errors:
            location = ".".join(
                str(item) for item in relevant_error.absolute_path
            )
            suffix = f".{location}" if location else ""
            message = schema_error_message(relevant_error)
            issues.append(f"{label}{suffix} 不符合当前 v1 结构合同：{message}")
    return issues


def _identity(
    value: Any,
    pattern: re.Pattern[str],
    path: str,
    issues: list[str],
) -> str:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        issues.append(f"{path} 身份无效")
        return ""
    return value


def validate_domain_fact_reference(value: Any) -> dict[str, str]:
    """Validate one immutable fact reference without resolving its target."""

    issues: list[str] = []
    required = {
        "schema_version",
        "authority_kind",
        "model_id",
        "fact_id",
        "observed_commit",
    }
    if not isinstance(value, Mapping):
        raise ProjectDomainModelError(["领域事实引用必须是对象"])
    missing = sorted(required - set(value))
    extra = sorted(set(value) - required)
    if missing:
        issues.append("领域事实引用缺少字段：" + ", ".join(missing))
    if extra:
        issues.append("领域事实引用包含未知字段：" + ", ".join(extra))
    if value.get("schema_version") != DOMAIN_FACT_REFERENCE_SCHEMA:
        issues.append(
            "领域事实引用结构版本必须是 " + DOMAIN_FACT_REFERENCE_SCHEMA
        )
    if value.get("authority_kind") != "project_domain_model":
        issues.append("领域事实引用的权威种类必须是项目领域模型")
    model_id = _identity(value.get("model_id"), _MODEL_ID, "model_id", issues)
    fact_id = _identity(value.get("fact_id"), _FACT_ID, "fact_id", issues)
    observed_commit = value.get("observed_commit")
    if (
        not isinstance(observed_commit, str)
        or _COMMIT.fullmatch(observed_commit) is None
    ):
        issues.append("领域事实引用必须绑定不可变版本提交")
        observed_commit = ""
    if issues:
        raise ProjectDomainModelError(issues)
    return {
        "schema_version": DOMAIN_FACT_REFERENCE_SCHEMA,
        "authority_kind": "project_domain_model",
        "model_id": model_id,
        "fact_id": fact_id,
        "observed_commit": observed_commit,
    }


def _fact_references(fact: Mapping[str, Any]) -> list[str]:
    references = list(fact.get("scope_fact_ids", []))
    references.extend(fact.get("dependency_fact_ids", []))
    if fact.get("status") in TOMBSTONE_FACT_STATUSES:
        references.extend(
            item["target_fact_id"] for item in fact.get("lineage", [])
        )
        return references

    content = fact.get("content", {})
    kind = fact.get("kind")
    if kind == "product_capability":
        references.extend(content.get("primary_actor_fact_ids", []))
        references.extend(content.get("supporting_actor_fact_ids", []))
    elif kind == "domain_scenario":
        references.append(content.get("capability_fact_id"))
        references.extend(content.get("actor_fact_ids", []))
    elif kind == "domain_entity" and content.get("lifecycle_fact_id"):
        references.append(content["lifecycle_fact_id"])
    elif kind == "lifecycle":
        references.append(content.get("subject_fact_id"))
        for transition in content.get("transitions", []):
            references.extend(transition.get("resulting_event_fact_ids", []))
    elif kind == "domain_event":
        references.extend(content.get("subject_fact_ids", []))
    elif kind == "domain_invariant":
        references.extend(content.get("protected_fact_ids", []))
    elif kind == "decision_authority":
        references.append(content.get("authority_actor_fact_id"))
        references.extend(content.get("candidate_provider_actor_fact_ids", []))
        references.extend(content.get("non_authority_actor_fact_ids", []))
    elif kind == "context_relationship":
        references.append(content.get("from_context_fact_id"))
        references.append(content.get("to_context_fact_id"))
    return [item for item in references if isinstance(item, str) and item]


class ProjectDomainModel:
    """Validate and progressively expose one exact domain-model revision."""

    def __init__(
        self,
        project_dir: str | Path,
        model_path: str,
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
    ) -> None:
        try:
            self.reader = project_reader_for_scope(
                project_dir,
                observed_ref=observed_ref,
                shared_reader=shared_reader,
            )
            self.model_path = repository_relative_path(
                model_path,
                "domain_model_path",
            )
        except GitProjectReaderError as error:
            raise ProjectDomainModelError([str(error)]) from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit
        self._manifest_cache: dict[str, Any] | None = None
        self._routing_cache: dict[str, Any] | None = None
        self._scan_cache: dict[str, Any] | None = None

    def catalog(self) -> dict[str, Any]:
        """Return the complete validated catalog for deterministic governance."""

        scanned = self._scan()
        manifest = scanned["manifest"]
        return {
            "schema_version": "strixnova.project-domain-catalog.v1",
            "authority_kind": "project_domain_model",
            "model_id": manifest["model_id"],
            "revision": deepcopy(manifest["revision"]),
            "product_definition_ref": deepcopy(
                manifest["product_definition_ref"]
            ),
            "title": manifest["title"],
            "purpose": manifest["purpose"],
            "model_path": self.model_path,
            "observed_commit": self.observed_commit,
            "collections": deepcopy(scanned["collections"]),
            "sources": deepcopy(scanned["sources"]),
            "facts": deepcopy(scanned["active_facts"]),
            "retired_facts": deepcopy(scanned["tombstones"]),
            "counts": {
                "collections": len(scanned["collections"]),
                "sources": len(scanned["sources"]),
                "active_facts": len(scanned["active_facts"]),
                "tombstones": len(scanned["tombstones"]),
            },
            "semantic_content_machine_proven": False,
        }

    def routing_catalog(self) -> dict[str, Any]:
        """Return collection routing without loading source fact bodies."""

        manifest = self._manifest()
        routing = self._routing_index()
        roots = [
            self._collection_brief(routing["collections_by_path"][path])
            for path in manifest["root_collection_paths"]
        ]
        return {
            "schema_version": "strixnova.project-domain-routing-catalog.v1",
            "authority_kind": "project_domain_model",
            "model_id": manifest["model_id"],
            "model_revision_id": manifest["revision"]["revision_id"],
            "revision_status": manifest["revision"]["status"],
            "title": manifest["title"],
            "purpose": manifest["purpose"],
            "model_path": self.model_path,
            "observed_commit": self.observed_commit,
            "root_collections": roots,
            "routing_counts": {
                "root_collections": len(roots),
                "collections": len(routing["collections"]),
                "sources": len(routing["source_routes"]),
                "facts": None,
            },
            "fact_bodies_included": False,
            "semantic_content_machine_proven": False,
        }

    def collection_catalog(
        self,
        collection_id: str,
        *,
        parent_collection_id: str | None = None,
        collection_path: str | None = None,
    ) -> dict[str, Any]:
        """Return one collection and its immediate routing choices."""

        routing = self._routing_index()
        collection = routing["collections_by_id"].get(str(collection_id))
        if collection is None:
            raise ProjectDomainModelError(
                [f"未知领域集合：{collection_id}"]
            )
        if collection_path is not None:
            normalized = self._path(collection_path, "collection_path")
            if collection["_path"] != normalized:
                raise ProjectDomainModelError(
                    ["领域集合身份与路径不一致"]
                )
        if (
            parent_collection_id is not None
            and collection["_parent_collection_id"]
            != str(parent_collection_id)
        ):
            raise ProjectDomainModelError(["领域集合父级身份不一致"])
        children = [
            routing["collections_by_path"][path]
            for path in collection["child_collection_paths"]
        ]
        return {
            "schema_version": "strixnova.project-domain-collection-catalog.v1",
            "model_id": self._manifest()["model_id"],
            "model_revision_id": self._manifest()["revision"]["revision_id"],
            "observed_commit": self.observed_commit,
            "collection": self._collection_brief(collection),
            "child_collections": [
                self._collection_brief(item) for item in children
            ],
            "sources": [
                self._source_route_brief(item)
                for item in routing["source_routes"]
                if item["_collection_id"] == collection["collection_id"]
            ],
            "fact_bodies_included": False,
        }

    def source_catalog(
        self,
        source_id: str,
        *,
        collection_path: str | None = None,
    ) -> dict[str, Any]:
        """Return fact routing metadata for one selected source."""

        routing = self._routing_index()
        route = routing["source_routes_by_id"].get(str(source_id))
        if route is None:
            raise ProjectDomainModelError([f"未知领域来源：{source_id}"])
        if collection_path is not None:
            normalized = self._path(collection_path, "collection_path")
            if route["_collection_path"] != normalized:
                raise ProjectDomainModelError(["领域来源不属于指定集合"])
        source = self._load_source(route)
        return {
            "schema_version": "strixnova.project-domain-source-catalog.v1",
            "model_id": source["model_id"],
            "model_revision_id": source["model_revision_id"],
            "observed_commit": self.observed_commit,
            "source": self._source_route_brief(route),
            "scope_fact_ids": deepcopy(source["scope_fact_ids"]),
            "facts": [self._fact_brief(item) for item in source["facts"]],
            "fact_bodies_included": False,
        }

    def fact_body(
        self,
        fact_id: str,
        *,
        source_id: str | None = None,
        collection_id: str | None = None,
        collection_path: str | None = None,
        source_path: str | None = None,
    ) -> dict[str, Any]:
        """Return one canonical typed fact body."""

        identifier = str(fact_id)
        scanned = self._scan()
        record = scanned["fact_records"].get(identifier)
        if record is None:
            raise ProjectDomainModelError([f"未知领域事实：{identifier}"])
        route = record["route"]
        checks = {
            "source_id": (source_id, route["source_id"]),
            "collection_id": (collection_id, route["_collection_id"]),
            "collection_path": (collection_path, route["_collection_path"]),
            "source_path": (source_path, route["path"]),
        }
        for label, (provided, expected) in checks.items():
            if provided is not None and str(provided) != expected:
                raise ProjectDomainModelError(
                    [f"领域事实的 {label} 与规范来源不一致"]
                )
        result = deepcopy(record["fact"])
        result.update(
            {
                "_model_id": scanned["manifest"]["model_id"],
                "_model_revision_id": scanned["manifest"]["revision"][
                    "revision_id"
                ],
                "_collection_id": route["_collection_id"],
                "_source_id": route["source_id"],
                "_source_path": route["path"],
                "_observed_commit": self.observed_commit,
            }
        )
        return result

    def required_closure(
        self,
        selected_fact_ids: Sequence[str],
    ) -> dict[str, Any]:
        """Return selected facts and all explicitly referenced facts."""

        scanned = self._scan()
        known = scanned["fact_records"]
        queue = deque(str(item) for item in selected_fact_ids)
        selected = set(queue)
        unknown = sorted(selected - set(known))
        if unknown:
            raise ProjectDomainModelError(
                ["未知领域事实：" + ", ".join(unknown)]
            )
        while queue:
            identifier = queue.popleft()
            for reference in _fact_references(known[identifier]["fact"]):
                if reference not in known:
                    raise ProjectDomainModelError(
                        [f"领域事实 {identifier} 引用未知事实 {reference}"]
                    )
                if reference not in selected:
                    selected.add(reference)
                    queue.append(reference)
        ordered_ids = [
            identifier
            for identifier in scanned["fact_order"]
            if identifier in selected
        ]
        return {
            "schema_version": "strixnova.domain-fact-closure.v1",
            "model_id": scanned["manifest"]["model_id"],
            "model_revision_id": scanned["manifest"]["revision"][
                "revision_id"
            ],
            "observed_commit": self.observed_commit,
            "selected_fact_ids": list(dict.fromkeys(str(item) for item in selected_fact_ids)),
            "fact_ids": ordered_ids,
            "facts": [
                deepcopy(known[identifier]["fact"])
                for identifier in ordered_ids
            ],
            "bodies_loaded": True,
            "semantic_content_machine_proven": False,
        }

    def fact_reference(self, fact_id: str) -> dict[str, str]:
        if self.observed_commit is None:
            raise ProjectDomainModelError(
                ["正式领域事实引用必须从不可变版本提交读取"]
            )
        scanned = self._scan()
        if fact_id not in scanned["fact_records"]:
            raise ProjectDomainModelError([f"未知领域事实：{fact_id}"])
        return {
            "schema_version": DOMAIN_FACT_REFERENCE_SCHEMA,
            "authority_kind": "project_domain_model",
            "model_id": scanned["manifest"]["model_id"],
            "fact_id": fact_id,
            "observed_commit": self.observed_commit,
        }

    def resolve_reference(self, value: Any) -> dict[str, Any]:
        reference = validate_domain_fact_reference(value)
        if self.observed_commit is None:
            raise ProjectDomainModelError(
                ["解析正式领域事实引用必须选择不可变版本提交"]
            )
        scanned = self._scan()
        issues: list[str] = []
        if reference["model_id"] != scanned["manifest"]["model_id"]:
            issues.append("领域事实引用指向其他项目领域模型")
        if reference["observed_commit"] != self.observed_commit:
            issues.append("领域事实引用版本与当前读取版本不一致")
        record = scanned["fact_records"].get(reference["fact_id"])
        if record is None:
            issues.append("领域事实引用的事实不存在")
        if issues:
            raise ProjectDomainModelError(issues)
        assert record is not None
        return {
            "reference": reference,
            "status": record["fact"]["status"],
            "fact": deepcopy(record["fact"]),
            "semantic_content_machine_proven": False,
        }

    def _path(self, value: Any, label: str) -> str:
        try:
            return repository_relative_path(value, label)
        except GitProjectReaderError as error:
            raise ProjectDomainModelError([str(error)]) from error

    def _manifest(self) -> dict[str, Any]:
        if self._manifest_cache is not None:
            return self._manifest_cache
        try:
            value = self.reader.load_yaml(self.model_path, "项目领域模型")
        except GitProjectReaderError as error:
            raise ProjectDomainModelError([str(error)]) from error
        if not isinstance(value, Mapping):
            raise ProjectDomainModelError(["项目领域模型必须是对象"])
        if value.get("schema_version") != DOMAIN_MODEL_SCHEMA:
            raise ProjectDomainModelError(
                ["项目领域模型必须使用当前 v1 结构合同"]
            )
        issues = _schema_issues(
            "project-domain-model-v1.schema.json",
            value,
            "项目领域模型",
        )
        for index, path in enumerate(value.get("root_collection_paths", [])):
            try:
                repository_relative_path(path, f"root_collection_paths[{index}]")
            except GitProjectReaderError as error:
                issues.append(str(error))
        if issues:
            raise ProjectDomainModelError(issues)
        self._manifest_cache = deepcopy(dict(value))
        self.reader.prefetch(self._manifest_cache["root_collection_paths"])
        return self._manifest_cache

    def _routing_index(self) -> dict[str, Any]:
        if self._routing_cache is not None:
            return self._routing_cache
        manifest = self._manifest()
        revision_id = manifest["revision"]["revision_id"]
        queue = deque(
            (path, None) for path in manifest["root_collection_paths"]
        )
        collections: list[dict[str, Any]] = []
        collections_by_id: dict[str, dict[str, Any]] = {}
        collections_by_path: dict[str, dict[str, Any]] = {}
        source_routes: list[dict[str, Any]] = []
        source_routes_by_id: dict[str, dict[str, Any]] = {}
        source_paths: set[str] = set()
        issues: list[str] = []
        while queue:
            raw_path, parent_id = queue.popleft()
            path = self._path(raw_path, "collection_path")
            if path in collections_by_path:
                issues.append(f"领域集合路径重复或成环：{path}")
                continue
            try:
                value = self.reader.load_yaml(path, "领域集合")
            except GitProjectReaderError as error:
                issues.append(str(error))
                continue
            if not isinstance(value, Mapping):
                issues.append(f"领域集合必须是对象：{path}")
                continue
            if value.get("schema_version") != DOMAIN_COLLECTION_SCHEMA:
                issues.append(f"领域集合必须使用当前 v1 结构合同：{path}")
                continue
            issues.extend(
                _schema_issues(
                    "project-domain-collection-v1.schema.json",
                    value,
                    f"领域集合 {path}",
                )
            )
            collection = deepcopy(dict(value))
            collection_id = collection.get("collection_id", "")
            if collection.get("model_id") != manifest["model_id"]:
                issues.append(f"领域集合绑定了其他模型：{path}")
            if collection.get("model_revision_id") != revision_id:
                issues.append(f"领域集合绑定了其他模型修订：{path}")
            if collection_id in collections_by_id:
                issues.append(f"领域集合身份重复：{collection_id}")
            collection["_path"] = path
            collection["_parent_collection_id"] = parent_id
            collections.append(collection)
            collections_by_id[collection_id] = collection
            collections_by_path[path] = collection
            for child_path in collection.get("child_collection_paths", []):
                queue.append((child_path, collection_id))
            for raw_route in collection.get("sources", []):
                route = deepcopy(dict(raw_route))
                source_id = route.get("source_id", "")
                source_path = self._path(route.get("path"), "source_path")
                route["path"] = source_path
                route["_collection_id"] = collection_id
                route["_collection_path"] = path
                if source_id in source_routes_by_id:
                    issues.append(f"领域来源身份重复：{source_id}")
                if source_path in source_paths:
                    issues.append(f"领域来源路径重复：{source_path}")
                source_routes.append(route)
                source_routes_by_id[source_id] = route
                source_paths.add(source_path)
        if issues:
            raise ProjectDomainModelError(issues)
        self._routing_cache = {
            "collections": collections,
            "collections_by_id": collections_by_id,
            "collections_by_path": collections_by_path,
            "source_routes": source_routes,
            "source_routes_by_id": source_routes_by_id,
        }
        return self._routing_cache

    def _load_source(self, route: Mapping[str, Any]) -> dict[str, Any]:
        path = route["path"]
        try:
            value = self.reader.load_yaml(path, "领域来源")
        except GitProjectReaderError as error:
            raise ProjectDomainModelError([str(error)]) from error
        if not isinstance(value, Mapping):
            raise ProjectDomainModelError([f"领域来源必须是对象：{path}"])
        if value.get("schema_version") != DOMAIN_YAML_SOURCE_SCHEMA:
            raise ProjectDomainModelError(
                [f"领域来源必须使用当前 v1 结构合同：{path}"]
            )
        issues = _schema_issues(
            "project-domain-source-v1.schema.json",
            value,
            f"领域来源 {path}",
        )
        manifest = self._manifest()
        if value.get("model_id") != manifest["model_id"]:
            issues.append(f"领域来源绑定了其他模型：{path}")
        if value.get("model_revision_id") != manifest["revision"]["revision_id"]:
            issues.append(f"领域来源绑定了其他模型修订：{path}")
        if value.get("source_id") != route["source_id"]:
            issues.append(f"领域来源身份与路由不一致：{path}")
        if issues:
            raise ProjectDomainModelError(issues)
        return deepcopy(dict(value))

    def _scan(self) -> dict[str, Any]:
        if self._scan_cache is not None:
            return self._scan_cache
        manifest = self._manifest()
        routing = self._routing_index()
        self.reader.prefetch(
            [route["path"] for route in routing["source_routes"]]
        )
        sources: list[dict[str, Any]] = []
        active_facts: list[dict[str, Any]] = []
        tombstones: list[dict[str, Any]] = []
        fact_records: dict[str, dict[str, Any]] = {}
        fact_order: list[str] = []
        issues: list[str] = []
        for route in routing["source_routes"]:
            try:
                source = self._load_source(route)
            except ProjectDomainModelError as error:
                issues.extend(error.issues)
                continue
            sources.append(source)
            for fact in source["facts"]:
                identifier = fact["fact_id"]
                if identifier in fact_records:
                    issues.append(f"领域事实身份重复：{identifier}")
                    continue
                copied = deepcopy(fact)
                fact_records[identifier] = {
                    "fact": copied,
                    "route": route,
                }
                fact_order.append(identifier)
                if copied["status"] in ACTIVE_FACT_STATUSES:
                    active_facts.append(copied)
                else:
                    tombstones.append(copied)
        expected_status = manifest["revision"]["status"]
        for fact in active_facts:
            if fact["status"] != expected_status:
                issues.append(
                    f"活跃领域事实 {fact['fact_id']} 状态与模型修订不一致"
                )
        active_ids = {fact["fact_id"] for fact in active_facts}
        for source in sources:
            unknown_scope = sorted(set(source["scope_fact_ids"]) - active_ids)
            if unknown_scope:
                issues.append(
                    f"领域来源 {source['source_id']} 引用未知活跃范围："
                    + ", ".join(unknown_scope)
                )
        known_ids = set(fact_records)
        for identifier, record in fact_records.items():
            for reference in _fact_references(record["fact"]):
                if reference not in known_ids:
                    issues.append(
                        f"领域事实 {identifier} 引用未知事实 {reference}"
                    )
        self._check_lineage_cycles(fact_records, issues)
        self._check_typed_references(fact_records, issues)
        self._check_scenario_closure(active_facts, issues)
        if issues:
            raise ProjectDomainModelError(issues)
        self._scan_cache = {
            "manifest": manifest,
            "collections": [
                self._collection_brief(item)
                for item in routing["collections"]
            ],
            "sources": [
                self._source_route_brief(item)
                for item in routing["source_routes"]
            ],
            "active_facts": active_facts,
            "tombstones": tombstones,
            "fact_records": fact_records,
            "fact_order": fact_order,
        }
        return self._scan_cache

    @staticmethod
    def _check_lineage_cycles(
        records: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        """Reject only mechanically impossible self-links and lineage cycles."""

        graph: dict[str, list[str]] = {}
        for identifier, record in records.items():
            fact = record["fact"]
            if fact["status"] not in TOMBSTONE_FACT_STATUSES:
                continue
            targets = [
                item["target_fact_id"] for item in fact.get("lineage", [])
            ]
            if identifier in targets:
                issues.append(f"领域事实谱系不得自指：{identifier}")
            graph[identifier] = [target for target in targets if target in records]

        state: dict[str, int] = {}
        stack: list[str] = []
        positions: dict[str, int] = {}

        def visit(identifier: str) -> None:
            state[identifier] = 1
            positions[identifier] = len(stack)
            stack.append(identifier)
            for target in graph.get(identifier, []):
                if target == identifier or target not in graph:
                    continue
                target_state = state.get(target, 0)
                if target_state == 0:
                    visit(target)
                elif target_state == 1:
                    cycle = stack[positions[target] :] + [target]
                    issues.append("领域事实谱系形成循环：" + " -> ".join(cycle))
            stack.pop()
            positions.pop(identifier, None)
            state[identifier] = 2

        for identifier in graph:
            if state.get(identifier, 0) == 0:
                visit(identifier)

    @staticmethod
    def _check_typed_references(
        records: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        kinds = {
            identifier: record["fact"]["kind"]
            for identifier, record in records.items()
        }

        def require(identifier: str, reference: Any, allowed: set[str]) -> None:
            if not isinstance(reference, str) or reference not in kinds:
                return
            if kinds[reference] not in allowed:
                issues.append(
                    f"领域事实 {identifier} 对 {reference} 的类型引用无效"
                )

        for identifier, record in records.items():
            fact = record["fact"]
            if fact["status"] in TOMBSTONE_FACT_STATUSES:
                continue
            content = fact["content"]
            kind = fact["kind"]
            if kind == "product_capability":
                for reference in content["primary_actor_fact_ids"]:
                    require(identifier, reference, {"actor"})
                for reference in content["supporting_actor_fact_ids"]:
                    require(identifier, reference, {"actor"})
            elif kind == "domain_scenario":
                require(
                    identifier,
                    content["capability_fact_id"],
                    {"product_capability"},
                )
                for reference in content["actor_fact_ids"]:
                    require(identifier, reference, {"actor"})
            elif kind == "domain_entity" and content["lifecycle_fact_id"]:
                require(identifier, content["lifecycle_fact_id"], {"lifecycle"})
            elif kind == "lifecycle":
                require(
                    identifier,
                    content["subject_fact_id"],
                    {"domain_entity", "product_capability"},
                )
                for transition in content["transitions"]:
                    for reference in transition["resulting_event_fact_ids"]:
                        require(identifier, reference, {"domain_event"})
            elif kind == "decision_authority":
                require(
                    identifier,
                    content["authority_actor_fact_id"],
                    {"actor"},
                )
            elif kind == "context_relationship":
                require(
                    identifier,
                    content["from_context_fact_id"],
                    {"bounded_context"},
                )
                require(
                    identifier,
                    content["to_context_fact_id"],
                    {"bounded_context"},
                )

    @staticmethod
    def _check_scenario_closure(
        active_facts: Sequence[Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        scenarios: dict[tuple[str, str], int] = {}
        for fact in active_facts:
            if fact["kind"] != "domain_scenario":
                continue
            key = (
                fact["content"]["capability_fact_id"],
                fact["content"]["scenario_type"],
            )
            scenarios[key] = scenarios.get(key, 0) + 1
        for fact in active_facts:
            if fact["kind"] != "product_capability":
                continue
            for requirement in fact["content"]["scenario_requirements"]:
                key = (fact["fact_id"], requirement["scenario_type"])
                count = scenarios.get(key, 0)
                if requirement["applicability"] == "required" and count != 1:
                    issues.append(
                        f"产品能力 {fact['fact_id']} 的"
                        f"{requirement['scenario_type']}场景必须恰好一个"
                    )
                if requirement["applicability"] == "not_applicable" and count:
                    issues.append(
                        f"产品能力 {fact['fact_id']} 声明不适用的场景仍有正文"
                    )

    @staticmethod
    def _collection_brief(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "collection_id": value["collection_id"],
            "title": value["title"],
            "routing_summary": value["routing_summary"],
            "path": value["_path"],
            "parent_collection_id": value["_parent_collection_id"],
            "child_collection_count": len(value["child_collection_paths"]),
            "source_count": len(value["sources"]),
        }

    @staticmethod
    def _source_route_brief(value: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "source_id": value["source_id"],
            "title": value["title"],
            "routing_summary": value["routing_summary"],
            "path": value["path"],
            "collection_id": value["_collection_id"],
            "collection_path": value["_collection_path"],
        }

    @staticmethod
    def _fact_brief(value: Mapping[str, Any]) -> dict[str, Any]:
        result = {
            "fact_id": value["fact_id"],
            "status": value["status"],
            "title": value["title"],
            "kind": value["kind"],
            "product_capability_ids": deepcopy(
                value["product_capability_ids"]
            ),
            "scope_fact_ids": deepcopy(value["scope_fact_ids"]),
            "dependency_fact_ids": deepcopy(value["dependency_fact_ids"]),
        }
        if value["status"] in TOMBSTONE_FACT_STATUSES:
            result["lineage"] = deepcopy(value["lineage"])
            result["retirement_reason"] = value["retirement_reason"]
        return result


__all__ = [
    "ACTIVE_FACT_STATUSES",
    "DOMAIN_COLLECTION_SCHEMA",
    "DOMAIN_FACT_REFERENCE_SCHEMA",
    "DOMAIN_MODEL_SCHEMA",
    "DOMAIN_YAML_SOURCE_SCHEMA",
    "LINEAGE_RELATIONS",
    "ProjectDomainModel",
    "ProjectDomainModelError",
    "TOMBSTONE_FACT_STATUSES",
    "validate_domain_fact_reference",
]
