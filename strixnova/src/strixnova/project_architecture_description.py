"""Read one complete second-version target architecture authority."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Mapping, Sequence
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
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


ARCHITECTURE_DESCRIPTION_SCHEMA = (
    "strixnova.project-architecture-description.v1"
)
_ARTIFACT_SCHEMAS = {
    "modules": "strixnova.architecture-modules.v1",
    "relationships": "strixnova.architecture-relationships.v1",
    "constraints": "strixnova.architecture-constraints.v1",
    "domain_fact_dispositions": (
        "strixnova.architecture-domain-fact-dispositions.v1"
    ),
    "implementation_stages": "strixnova.architecture-implementation-stages.v1",
}
_SCHEMA_BRANCHES = {
    ARCHITECTURE_DESCRIPTION_SCHEMA: 0,
    "strixnova.architecture-modules.v1": 1,
    "strixnova.architecture-relationships.v1": 2,
    "strixnova.architecture-constraints.v1": 3,
    "strixnova.architecture-domain-fact-dispositions.v1": 4,
    "strixnova.architecture-implementation-stages.v1": 5,
}
_FORBIDDEN_TARGET_KEYS = frozenset(
    {
        "paths",
        "path",
        "source_path",
        "source_paths",
        "test_path",
        "test_paths",
        "implementation_path",
        "implementation_paths",
        "verification_paths",
        "evidence",
        "current_module",
        "current_modules",
    }
)


class ProjectArchitectureDescriptionError(ValueError):
    """The project target architecture is structurally invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目目标架构无效")


def _schema() -> dict[str, Any]:
    resource = files("strixnova.resources").joinpath(
        "project-architecture-description-v1.schema.json"
    )
    return json.loads(resource.read_text(encoding="utf-8"))


def _schema_issues(value: Any, label: str) -> list[str]:
    errors = sorted(
        Draft202012Validator(
            _schema(),
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    issues: list[str] = []
    for error in errors:
        branch_index = (
            _SCHEMA_BRANCHES.get(error.instance.get("schema_version"))
            if isinstance(error.instance, Mapping)
            else None
        )
        for relevant_error in one_of_branch_errors(error, branch_index):
            location = ".".join(
                str(item) for item in relevant_error.absolute_path
            )
            suffix = f".{location}" if location else ""
            message = schema_error_message(relevant_error)
            issues.append(f"{label}{suffix} 不符合当前 v1 结构合同：{message}")
    return issues


def _walk(value: Any) -> list[tuple[str | None, Any]]:
    result: list[tuple[str | None, Any]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            result.append((str(key), child))
            result.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            result.append((None, child))
            result.extend(_walk(child))
    return result


class ProjectArchitectureDescription:
    """Validate and expose one exact target-architecture revision."""

    def __init__(
        self,
        project_dir: str | Path,
        description_path: str,
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
            self.description_path = repository_relative_path(
                description_path,
                "architecture_description_path",
            )
        except GitProjectReaderError as error:
            raise ProjectArchitectureDescriptionError([str(error)]) from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit
        self._cache: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        """Return the complete structurally validated target architecture."""

        if self._cache is not None:
            return deepcopy(self._cache)
        try:
            model = self.reader.load_yaml(
                self.description_path,
                "项目目标架构",
            )
        except GitProjectReaderError as error:
            raise ProjectArchitectureDescriptionError([str(error)]) from error
        if not isinstance(model, Mapping):
            raise ProjectArchitectureDescriptionError(
                ["项目目标架构必须是对象"]
            )
        if model.get("schema_version") != ARCHITECTURE_DESCRIPTION_SCHEMA:
            raise ProjectArchitectureDescriptionError(
                ["项目目标架构必须使用当前 v1 结构合同"]
            )
        issues = _schema_issues(model, "项目目标架构")
        artifacts: dict[str, dict[str, Any]] = {}
        artifact_paths = model.get("artifact_paths", {})
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
                raw_path = artifact_paths.get(name)
                try:
                    path = repository_relative_path(
                        raw_path,
                        f"artifact_paths.{name}",
                    )
                    value = self.reader.load_yaml(path, f"目标架构产物 {name}")
                except GitProjectReaderError as error:
                    issues.append(str(error))
                    continue
                if not isinstance(value, Mapping):
                    issues.append(f"目标架构产物 {name} 必须是对象")
                    continue
                if value.get("schema_version") != expected_schema:
                    issues.append(
                        f"目标架构产物 {name}.schema_version 必须是 "
                        f"{expected_schema}"
                    )
                    continue
                artifact_issues = _schema_issues(
                    value,
                    f"目标架构产物 {name}",
                )
                issues.extend(artifact_issues)
                if artifact_issues:
                    continue
                artifacts[name] = deepcopy(dict(value))
        if len(artifacts) == len(_ARTIFACT_SCHEMAS):
            self._validate_bindings(model, artifacts, issues)
            self._validate_graph(artifacts, issues)
            self._validate_no_current_implementation(model, artifacts, issues)
        if issues:
            raise ProjectArchitectureDescriptionError(issues)

        result = deepcopy(dict(model))
        result.update(
            {
                "modules": deepcopy(artifacts["modules"]["modules"]),
                "relationships": deepcopy(
                    artifacts["relationships"]["relationships"]
                ),
                "default_relationship_policy": artifacts["relationships"][
                    "default_relationship_policy"
                ],
                "constraints": deepcopy(
                    artifacts["constraints"]["constraints"]
                ),
                "domain_fact_dispositions": deepcopy(
                    artifacts["domain_fact_dispositions"]["dispositions"]
                ),
                "implementation_stages": deepcopy(
                    artifacts["implementation_stages"]["stages"]
                ),
                "_manifest_path": self.description_path,
                "_observed_commit": self.observed_commit,
                "semantic_content_machine_proven": False,
            }
        )
        self._cache = result
        return deepcopy(result)

    def decision_catalog(self) -> dict[str, Any]:
        """Return deterministic relationship and responsibility decisions."""

        architecture = self.load()
        allowed = [
            item
            for item in architecture["relationships"]
            if item["mode"] in {"direct", "read_only_projection"}
        ]
        mediated = [
            item
            for item in architecture["relationships"]
            if item["mode"] == "through_module"
        ]
        forbidden = [
            item
            for item in architecture["relationships"]
            if item["mode"] == "forbidden"
        ]
        return {
            "schema_version": "strixnova.architecture-decision-catalog.v1",
            "architecture_id": architecture["architecture_id"],
            "architecture_revision_id": architecture["revision"]["revision_id"],
            "observed_commit": architecture["_observed_commit"],
            "default_relationship_policy": architecture[
                "default_relationship_policy"
            ],
            "module_ids": [item["module_id"] for item in architecture["modules"]],
            "responsibility_ids": {
                "modules": [
                    item["module_id"] for item in architecture["modules"]
                ],
                "relationships": [
                    item["relationship_id"]
                    for item in architecture["relationships"]
                ],
                "constraints": [
                    item["constraint_id"] for item in architecture["constraints"]
                ],
            },
            "allowed_relationships": deepcopy(allowed),
            "mediated_relationships": deepcopy(mediated),
            "forbidden_relationships": deepcopy(forbidden),
            "direct_dependency_graph_acyclic": True,
            "semantic_content_machine_proven": False,
        }

    def select_modules(self, module_ids: Sequence[str]) -> dict[str, Any]:
        """Return explicit responsibility links and the definitions they require."""

        architecture = self.load()
        selected = set(str(item) for item in module_ids)
        known = {item["module_id"] for item in architecture["modules"]}
        unknown = sorted(selected - known)
        if unknown:
            raise ProjectArchitectureDescriptionError(
                ["未知目标架构模块：" + ", ".join(unknown)]
            )
        relationships = [
            item for item in architecture["relationships"]
            if item["from_module_id"] in selected
            or item["to_module_id"] in selected
            or item.get("mediator_module_id") in selected
        ]
        referenced = set(selected)
        for relationship in relationships:
            referenced.update((relationship["from_module_id"], relationship["to_module_id"]))
            if relationship.get("mediator_module_id"):
                referenced.add(relationship["mediator_module_id"])
        return {
            "schema_version": "strixnova.architecture-selection.v1",
            "architecture_id": architecture["architecture_id"],
            "architecture_revision_id": architecture["revision"]["revision_id"],
            "observed_commit": architecture["_observed_commit"],
            "selected_module_ids": sorted(selected),
            "referenced_module_ids": sorted(referenced - selected),
            "default_relationship_policy": architecture["default_relationship_policy"],
            "modules": [
                deepcopy(item)
                for item in architecture["modules"]
                if item["module_id"] in referenced
            ],
            "relationships": deepcopy(relationships),
            "constraints": [
                deepcopy(item)
                for item in architecture["constraints"]
                if not item["applies_to_module_ids"]
                or set(item["applies_to_module_ids"]) & selected
            ],
            "domain_fact_dispositions": [
                deepcopy(item) for item in architecture["domain_fact_dispositions"]
                if item.get("primary_module_id") in selected
                or set(item.get("collaborator_module_ids", [])) & selected
                or set(item.get("relationship_ids", [])) & {value["relationship_id"] for value in relationships}
            ],
            "semantic_content_machine_proven": False,
        }

    @staticmethod
    def _validate_bindings(
        model: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        architecture_id = model["architecture_id"]
        revision_id = model["revision"]["revision_id"]
        for name, artifact in artifacts.items():
            if artifact.get("architecture_id") != architecture_id:
                issues.append(f"目标架构产物 {name} 绑定了其他架构")
            if artifact.get("architecture_revision_id") != revision_id:
                issues.append(f"目标架构产物 {name} 绑定了其他架构修订")
        dispositions = artifacts["domain_fact_dispositions"]
        if dispositions.get("domain_model_ref") != model["domain_model_ref"]:
            issues.append("领域事实处置绑定了其他领域模型修订")

    @staticmethod
    def _validate_graph(
        artifacts: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        modules = artifacts["modules"]["modules"]
        module_ids = [item["module_id"] for item in modules]
        interface_ids = [
            item["public_interface"]["interface_id"] for item in modules
        ]
        if len(module_ids) != len(set(module_ids)):
            issues.append("目标架构模块身份重复")
        if len(interface_ids) != len(set(interface_ids)):
            issues.append("目标架构稳定接口身份重复")
        known_modules = set(module_ids)
        for module in modules:
            operations = [
                item["name"]
                for item in module["public_interface"]["operations"]
            ]
            if len(operations) != len(set(operations)):
                issues.append(f"目标模块 {module['module_id']} 的操作名称重复")

        relationships = artifacts["relationships"]["relationships"]
        relationship_ids = [item["relationship_id"] for item in relationships]
        if len(relationship_ids) != len(set(relationship_ids)):
            issues.append("目标架构关系身份重复")
        direct_edges: set[tuple[str, str]] = set()
        forbidden_edges: set[tuple[str, str]] = set()
        for item in relationships:
            start = item["from_module_id"]
            end = item["to_module_id"]
            mediator = item["mediator_module_id"]
            if start not in known_modules or end not in known_modules:
                issues.append(f"目标架构关系引用未知模块：{item['relationship_id']}")
            if start == end:
                issues.append(f"目标架构关系不得指向自身：{item['relationship_id']}")
            if mediator is not None and (
                mediator not in known_modules or mediator in {start, end}
            ):
                issues.append(f"目标架构关系中介无效：{item['relationship_id']}")
            pair = (start, end)
            if item["mode"] in {"direct", "read_only_projection"}:
                direct_edges.add(pair)
            elif item["mode"] == "forbidden":
                forbidden_edges.add(pair)
        if direct_edges & forbidden_edges:
            issues.append("同一目标架构关系不能同时允许和禁止")
        for item in relationships:
            if item["mode"] != "through_module":
                continue
            mediator = item["mediator_module_id"]
            if (
                (item["from_module_id"], mediator) not in direct_edges
                or (mediator, item["to_module_id"]) not in direct_edges
            ):
                issues.append(
                    f"中介关系缺少声明的直接协作边：{item['relationship_id']}"
                )
        if not ProjectArchitectureDescription._acyclic(
            known_modules,
            direct_edges,
        ):
            issues.append("目标架构直接依赖图存在循环")

        constraints = artifacts["constraints"]["constraints"]
        constraint_ids = [item["constraint_id"] for item in constraints]
        if len(constraint_ids) != len(set(constraint_ids)):
            issues.append("目标架构约束身份重复")
        known_constraints = set(constraint_ids)
        for item in constraints:
            if not set(item["applies_to_module_ids"]) <= known_modules:
                issues.append(f"架构约束引用未知模块：{item['constraint_id']}")

        known_relationships = set(relationship_ids)
        dispositions = artifacts["domain_fact_dispositions"]["dispositions"]
        fact_ids = [item["domain_fact_id"] for item in dispositions]
        if len(fact_ids) != len(set(fact_ids)):
            issues.append("领域事实架构处置重复")
        for item in dispositions:
            primary = item["primary_module_id"]
            collaborators = set(item["collaborator_module_ids"])
            if item["disposition_type"] == "unallocated":
                issues.append(f"领域事实尚未分配：{item['domain_fact_id']}")
            if primary is not None and (
                primary not in known_modules or primary in collaborators
            ):
                issues.append(f"领域事实主要承载模块无效：{item['domain_fact_id']}")
            if not collaborators <= known_modules:
                issues.append(f"领域事实协作模块无效：{item['domain_fact_id']}")
            if not set(item["relationship_ids"]) <= known_relationships:
                issues.append(f"领域事实关系引用无效：{item['domain_fact_id']}")
            if not set(item["constraint_ids"]) <= known_constraints:
                issues.append(f"领域事实约束引用无效：{item['domain_fact_id']}")

        stages = artifacts["implementation_stages"]["stages"]
        if [item["order"] for item in stages] != list(range(1, len(stages) + 1)):
            issues.append("目标架构实施阶段顺序不连续")
        stage_ids = {item["stage_id"] for item in stages}
        order_by_id = {item["stage_id"]: item["order"] for item in stages}
        covered: set[str] = set()
        for item in stages:
            prerequisites = set(item["prerequisite_stage_ids"])
            if not prerequisites <= stage_ids:
                issues.append(f"实施阶段引用未知前置阶段：{item['stage_id']}")
            if any(
                order_by_id.get(identifier, item["order"]) >= item["order"]
                for identifier in prerequisites
            ):
                issues.append(f"实施阶段前置顺序无效：{item['stage_id']}")
            if not set(item["module_ids"]) <= known_modules:
                issues.append(f"实施阶段引用未知模块：{item['stage_id']}")
            covered.update(item["module_ids"])
        if covered != known_modules:
            issues.append("目标架构实施阶段没有覆盖全部模块")

    @staticmethod
    def _acyclic(
        module_ids: set[str],
        edges: set[tuple[str, str]],
    ) -> bool:
        graph: dict[str, set[str]] = defaultdict(set)
        indegree = {identifier: 0 for identifier in module_ids}
        for start, end in edges:
            if end not in graph[start]:
                graph[start].add(end)
                indegree[end] += 1
        queue = deque(sorted(key for key, value in indegree.items() if value == 0))
        visited = 0
        while queue:
            identifier = queue.popleft()
            visited += 1
            for target in sorted(graph[identifier]):
                indegree[target] -= 1
                if indegree[target] == 0:
                    queue.append(target)
        return visited == len(module_ids)

    @staticmethod
    def _validate_no_current_implementation(
        model: Mapping[str, Any],
        artifacts: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        for label, value in [("目标架构", model), *artifacts.items()]:
            for key, child in _walk(value):
                if key in _FORBIDDEN_TARGET_KEYS:
                    issues.append(f"{label} 包含当前实现字段：{key}")
                if isinstance(child, str) and (
                    "strixnova/src/" in child
                    or "tests/" in child
                    or child.endswith(".py")
                ):
                    issues.append(f"{label} 包含当前实现路径")


__all__ = [
    "ARCHITECTURE_DESCRIPTION_SCHEMA",
    "ProjectArchitectureDescription",
    "ProjectArchitectureDescriptionError",
]
