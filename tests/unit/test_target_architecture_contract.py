from __future__ import annotations

from collections import defaultdict, deque
import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml


PROJECT_ROOT = Path(__file__).parents[2]
ARCHITECTURE_ROOT = PROJECT_ROOT / "docs" / "architecture"
DOMAIN_ROOT = PROJECT_ROOT / "docs" / "domain"


def _schema() -> dict:
    return json.loads(
        (
            ARCHITECTURE_ROOT
            / "contracts"
            / "project-architecture-description-v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def _repository_architecture() -> tuple[dict, dict[str, dict]]:
    model = yaml.safe_load(
        (ARCHITECTURE_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    artifacts = {
        name: yaml.safe_load(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        for name, relative_path in model["artifact_paths"].items()
    }
    return model, artifacts


def _active_domain_facts() -> dict[str, dict]:
    model = yaml.safe_load(
        (DOMAIN_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    facts: list[dict] = []
    for collection_path in model["root_collection_paths"]:
        collection = yaml.safe_load(
            (PROJECT_ROOT / collection_path).read_text(encoding="utf-8")
        )
        for route in collection["sources"]:
            source = yaml.safe_load(
                (PROJECT_ROOT / route["path"]).read_text(encoding="utf-8")
            )
            facts.extend(source["facts"])
    return {
        fact["fact_id"]: fact
        for fact in facts
        if fact["status"] == model["revision"]["status"]
    }


def _walk(value: object) -> list[tuple[str | None, object]]:
    items: list[tuple[str | None, object]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            items.append((key, child))
            items.extend(_walk(child))
    elif isinstance(value, list):
        for child in value:
            items.append((None, child))
            items.extend(_walk(child))
    return items


def test_architecture_contract_rejects_current_implementation_paths() -> None:
    validator = Draft202012Validator(_schema())
    catalog = {
        "schema_version": "strixnova.architecture-modules.v1",
        "architecture_id": "ARCH-963827FB26C94363",
        "architecture_revision_id": "ARCHREV-F96952C40C2942E8",
        "modules": [
            {
                "module_id": "MODULE-333FEE8F8A1B491E",
                "title": "命令适配器",
                "layer": "adapter",
                "responsibility": "转换输入输出。",
                "not_responsible_for": ["不判断领域语义。"],
                "public_interface": {
                    "interface_id": "INTERFACE-FBB310E94A6D4B82",
                    "title": "命令交互接口",
                    "operations": [
                        {"name": "转换请求", "meaning": "转换显式请求。"}
                    ],
                },
            }
        ],
    }
    assert not list(validator.iter_errors(catalog))
    catalog["modules"][0]["paths"] = ["strixnova/src/strixnova/cli.py"]
    assert list(validator.iter_errors(catalog))


def test_repository_architecture_artifacts_match_the_contract() -> None:
    model, artifacts = _repository_architecture()
    validator = Draft202012Validator(_schema())
    assert not list(validator.iter_errors(model))
    for name, artifact in artifacts.items():
        assert not list(validator.iter_errors(artifact)), name
        assert artifact["architecture_id"] == model["architecture_id"]
        assert artifact["architecture_revision_id"] == model["revision"][
            "revision_id"
        ]


def test_target_modules_have_unique_stable_interfaces_and_closed_references() -> None:
    _, artifacts = _repository_architecture()
    modules = artifacts["modules"]["modules"]
    module_ids = [item["module_id"] for item in modules]
    interface_ids = [
        item["public_interface"]["interface_id"] for item in modules
    ]
    assert len(module_ids) == len(set(module_ids))
    assert len(interface_ids) == len(set(interface_ids))
    known_modules = set(module_ids)
    for module in modules:
        operations = [
            item["name"] for item in module["public_interface"]["operations"]
        ]
        assert len(operations) == len(set(operations))

    relationships = artifacts["relationships"]["relationships"]
    relationship_ids = [item["relationship_id"] for item in relationships]
    assert len(relationship_ids) == len(set(relationship_ids))
    for relationship in relationships:
        assert relationship["from_module_id"] in known_modules
        assert relationship["to_module_id"] in known_modules
        assert relationship["from_module_id"] != relationship["to_module_id"]
        mediator = relationship["mediator_module_id"]
        if mediator is not None:
            assert mediator in known_modules
            assert mediator not in {
                relationship["from_module_id"],
                relationship["to_module_id"],
            }

    constraints = artifacts["constraints"]["constraints"]
    constraint_ids = [item["constraint_id"] for item in constraints]
    assert len(constraint_ids) == len(set(constraint_ids))
    for constraint in constraints:
        assert set(constraint["applies_to_module_ids"]) <= known_modules


def test_every_mediated_relationship_has_both_declared_direct_legs() -> None:
    _, artifacts = _repository_architecture()
    relationships = artifacts["relationships"]["relationships"]
    direct_edges = {
        (item["from_module_id"], item["to_module_id"])
        for item in relationships
        if item["mode"] in {"direct", "read_only_projection"}
    }
    for relationship in relationships:
        if relationship["mode"] != "through_module":
            continue
        mediator = relationship["mediator_module_id"]
        assert (relationship["from_module_id"], mediator) in direct_edges
        assert (mediator, relationship["to_module_id"]) in direct_edges


def test_target_direct_dependency_graph_is_acyclic_and_default_denied() -> None:
    _, artifacts = _repository_architecture()
    assert (
        artifacts["relationships"]["default_relationship_policy"]
        == "forbidden"
    )
    module_ids = {
        item["module_id"] for item in artifacts["modules"]["modules"]
    }
    graph: dict[str, set[str]] = defaultdict(set)
    indegree = {module_id: 0 for module_id in module_ids}
    allowed_pairs: set[tuple[str, str]] = set()
    forbidden_pairs: set[tuple[str, str]] = set()
    for relationship in artifacts["relationships"]["relationships"]:
        pair = (
            relationship["from_module_id"],
            relationship["to_module_id"],
        )
        if relationship["mode"] in {"direct", "read_only_projection"}:
            allowed_pairs.add(pair)
            if pair[1] not in graph[pair[0]]:
                graph[pair[0]].add(pair[1])
                indegree[pair[1]] += 1
        elif relationship["mode"] == "forbidden":
            forbidden_pairs.add(pair)
    assert not (allowed_pairs & forbidden_pairs)

    ready = deque(sorted(key for key, value in indegree.items() if value == 0))
    visited: list[str] = []
    while ready:
        module_id = ready.popleft()
        visited.append(module_id)
        for target_id in sorted(graph[module_id]):
            indegree[target_id] -= 1
            if indegree[target_id] == 0:
                ready.append(target_id)
    assert set(visited) == module_ids


def test_high_risk_boundaries_are_explicit_in_the_target_graph() -> None:
    _, artifacts = _repository_architecture()
    relationships = artifacts["relationships"]["relationships"]
    direct_targets: dict[str, set[str]] = defaultdict(set)
    forbidden_targets: dict[str, set[str]] = defaultdict(set)
    for item in relationships:
        if item["mode"] in {"direct", "read_only_projection"}:
            direct_targets[item["from_module_id"]].add(item["to_module_id"])
        elif item["mode"] == "forbidden":
            forbidden_targets[item["from_module_id"]].add(
                item["to_module_id"]
            )

    command_adapter = "MODULE-333FEE8F8A1B491E"
    coordinator = "MODULE-159AE7957218470C"
    query = "MODULE-71687954FB1E4DFD"
    maintenance = "MODULE-1CDA1D66DA409B5A"
    assert direct_targets[command_adapter] == {coordinator, query, maintenance}

    baseline = "MODULE-E74F1900EDCA43AE"
    reader = "MODULE-B558AA14F6004AC0"
    engineering = "MODULE-5CEF109E340C469F"
    assert direct_targets[baseline] == {reader, "MODULE-F55E33D530DD42A8"}
    assert engineering in forbidden_targets[baseline]

    verification = "MODULE-A94EF8E733E64205"
    process = "MODULE-6DEF61048B394531"
    policy = "MODULE-8205A05A6F5E48A8"
    assert direct_targets[verification] == {process, reader}
    assert {baseline, policy} <= forbidden_targets[verification]
    assert verification not in direct_targets[engineering]


def test_every_active_domain_fact_has_one_nonempty_architecture_disposition() -> None:
    model, artifacts = _repository_architecture()
    domain_model = yaml.safe_load(
        (DOMAIN_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    assert model["domain_model_ref"] == {
        "model_id": domain_model["model_id"],
        "revision_id": domain_model["revision"]["revision_id"],
    }
    dispositions = artifacts["domain_fact_dispositions"]["dispositions"]
    disposition_ids = [item["domain_fact_id"] for item in dispositions]
    assert len(disposition_ids) == len(set(disposition_ids))
    assert set(disposition_ids) == set(_active_domain_facts())
    assert all(
        item["disposition_type"] != "unallocated" for item in dispositions
    )

    module_ids = {
        item["module_id"] for item in artifacts["modules"]["modules"]
    }
    relationship_ids = {
        item["relationship_id"]
        for item in artifacts["relationships"]["relationships"]
    }
    constraint_ids = {
        item["constraint_id"]
        for item in artifacts["constraints"]["constraints"]
    }
    for disposition in dispositions:
        primary = disposition["primary_module_id"]
        if primary is not None:
            assert primary in module_ids
            assert primary not in disposition["collaborator_module_ids"]
        assert set(disposition["collaborator_module_ids"]) <= module_ids
        assert set(disposition["relationship_ids"]) <= relationship_ids
        assert set(disposition["constraint_ids"]) <= constraint_ids


def test_architecture_stages_are_ordered_and_cover_every_target_module() -> None:
    _, artifacts = _repository_architecture()
    stages = artifacts["implementation_stages"]["stages"]
    assert [item["order"] for item in stages] == list(
        range(1, len(stages) + 1)
    )
    stage_ids = {item["stage_id"] for item in stages}
    order_by_id = {item["stage_id"]: item["order"] for item in stages}
    covered_modules: set[str] = set()
    for stage in stages:
        assert set(stage["prerequisite_stage_ids"]) <= stage_ids
        assert all(
            order_by_id[prerequisite_id] < stage["order"]
            for prerequisite_id in stage["prerequisite_stage_ids"]
        )
        covered_modules.update(stage["module_ids"])
    assert covered_modules == {
        item["module_id"] for item in artifacts["modules"]["modules"]
    }


def test_target_architecture_contains_no_current_paths_or_evidence_fields() -> None:
    _, artifacts = _repository_architecture()
    forbidden_keys = {
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
    for name, artifact in artifacts.items():
        for key, value in _walk(artifact):
            assert key not in forbidden_keys, name
            if isinstance(value, str):
                assert "strixnova/src/" not in value, name
                assert "tests/" not in value, name
                assert not value.endswith(".py"), name


def test_architecture_cannot_be_confirmable_before_domain_confirmation() -> None:
    model, _ = _repository_architecture()
    domain_model = yaml.safe_load(
        (DOMAIN_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    if model["revision"]["status"] in {
        "ready_for_confirmation",
        "confirmed",
    }:
        assert domain_model["revision"]["status"] == "confirmed"
        assert not model["unresolved_decisions"]
    else:
        assert model["revision"]["status"] == "draft"
