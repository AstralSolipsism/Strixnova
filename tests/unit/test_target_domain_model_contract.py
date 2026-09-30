from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator
import yaml

from strixnova.project_product_definition import ProjectProductDefinition


PROJECT_ROOT = Path(__file__).parents[2]
CONTRACT_ROOT = PROJECT_ROOT / "docs" / "domain" / "contracts"
DOMAIN_ROOT = PROJECT_ROOT / "docs" / "domain"


def _schema(name: str) -> dict:
    return json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))


def _actor_fact() -> dict:
    return {
        "fact_id": "FACT-39A0D6C1E85F427B",
        "status": "draft",
        "title": "项目负责人",
        "kind": "actor",
        "product_capability_ids": ["CAPABILITY-44EB4FA0B1994587"],
        "scope_fact_ids": [],
        "dependency_fact_ids": [],
        "content": {
            "role": "决定产品目标、领域含义、重大取舍和结果接受。",
            "responsibilities": ["确认精确的长期目标版本。"],
            "not_responsible_for": ["填写可由项目调查取得的事实。"],
        },
    }


def _load_repository_model() -> tuple[dict, list[dict], list[dict]]:
    model = yaml.safe_load((DOMAIN_ROOT / "model.yaml").read_text(encoding="utf-8"))
    collections = []
    sources = []
    pending_paths = list(model["root_collection_paths"])
    visited_paths: set[str] = set()
    while pending_paths:
        relative_path = pending_paths.pop(0)
        assert relative_path not in visited_paths, (
            f"领域 Collection 路由重复或成环：{relative_path}"
        )
        visited_paths.add(relative_path)
        collection = yaml.safe_load(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        collections.append(collection)
        pending_paths.extend(collection["child_collection_paths"])
        for route in collection["sources"]:
            source = yaml.safe_load(
                (PROJECT_ROOT / route["path"]).read_text(encoding="utf-8")
            )
            sources.append({"route": route, "content": source})
    return model, collections, sources


def _references_for_fact(fact: dict) -> list[tuple[str, set[str] | None]]:
    references: list[tuple[str, set[str] | None]] = []
    references.extend(
        (fact_id, None)
        for fact_id in fact.get("scope_fact_ids", [])
    )
    references.extend(
        (fact_id, None)
        for fact_id in fact.get("dependency_fact_ids", [])
    )
    if fact["status"] in {"superseded", "retired"}:
        references.extend(
            (item["target_fact_id"], None)
            for item in fact["lineage"]
        )
        return references

    content = fact["content"]
    kind = fact["kind"]
    if kind == "product_capability":
        references.extend(
            (fact_id, {"actor"})
            for fact_id in content["primary_actor_fact_ids"]
        )
        references.extend(
            (fact_id, {"actor"})
            for fact_id in content["supporting_actor_fact_ids"]
        )
    elif kind == "domain_scenario":
        references.append(
            (content["capability_fact_id"], {"product_capability"})
        )
        references.extend(
            (fact_id, {"actor"})
            for fact_id in content["actor_fact_ids"]
        )
    elif kind == "domain_entity" and content["lifecycle_fact_id"]:
        references.append((content["lifecycle_fact_id"], {"lifecycle"}))
    elif kind == "lifecycle":
        references.append(
            (
                content["subject_fact_id"],
                {"domain_entity", "product_capability"},
            )
        )
        for transition in content["transitions"]:
            references.extend(
                (fact_id, {"domain_event"})
                for fact_id in transition["resulting_event_fact_ids"]
            )
    elif kind == "domain_event":
        references.extend(
            (fact_id, None) for fact_id in content["subject_fact_ids"]
        )
    elif kind == "domain_invariant":
        references.extend(
            (fact_id, None) for fact_id in content["protected_fact_ids"]
        )
    elif kind == "decision_authority":
        references.append(
            (content["authority_actor_fact_id"], {"actor"})
        )
        references.extend(
            (fact_id, {"actor"})
            for fact_id in content["candidate_provider_actor_fact_ids"]
        )
        references.extend(
            (fact_id, {"actor"})
            for fact_id in content["non_authority_actor_fact_ids"]
        )
    elif kind == "context_relationship":
        references.append(
            (content["from_context_fact_id"], {"bounded_context"})
        )
        references.append(
            (content["to_context_fact_id"], {"bounded_context"})
        )
    return references


def _walk_keys(value: object) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(key)
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def test_draft_source_contract_accepts_typed_semantics_only() -> None:
    source_schema = _schema("project-domain-source-v1.schema.json")
    source = {
        "schema_version": "strixnova.project-domain-source.v1",
        "model_id": "MODEL-2F8356E6752B4CC6",
        "model_revision_id": "MODELREV-6271D5CFBB7C4B33",
        "source_id": "SRC-40C8E5B9127A63DF",
        "scope_fact_ids": [],
        "facts": [_actor_fact()],
    }

    validator = Draft202012Validator(source_schema)
    assert not list(validator.iter_errors(source))

    source["facts"][0]["content"]["evidence"] = ["tests/test_actor.py"]
    assert list(validator.iter_errors(source))
    source["facts"][0]["content"].pop("evidence")
    source["facts"][0]["implementation_paths"] = ["src/actor.py"]
    assert list(validator.iter_errors(source))


def test_draft_root_contract_binds_product_revision_and_lifecycle() -> None:
    root_schema = _schema("project-domain-model-v1.schema.json")
    root = {
        "schema_version": "strixnova.project-domain-model.v1",
        "model_id": "MODEL-2F8356E6752B4CC6",
        "revision": {
            "revision_id": "MODELREV-6271D5CFBB7C4B33",
            "status": "draft",
            "supersedes_revision_id": None,
            "confirmed_by_owner_id": None,
            "confirmed_on": None,
        },
        "product_definition_ref": {
            "product_id": "PRODUCT-8312417768A84DE4",
            "revision_id": "REVISION-8B62E6B707A34A9D",
        },
        "title": "Strixnova目标领域模型",
        "purpose": "保存已确认产品范围内必须成立的语义。",
        "root_collection_paths": [
            "docs/domain/collections/core.yaml"
        ],
        "unresolved_decisions": [],
    }

    validator = Draft202012Validator(root_schema)
    assert not list(validator.iter_errors(root))

    root["revision"].update(
        {
            "status": "confirmed",
            "confirmed_by_owner_id": None,
            "confirmed_on": None,
        }
    )
    assert list(validator.iter_errors(root))


def test_draft_collection_contract_keeps_routing_separate_from_semantics() -> None:
    collection_schema = _schema("project-domain-collection-v1.schema.json")
    collection = {
        "schema_version": "strixnova.project-domain-collection.v1",
        "model_id": "MODEL-2F8356E6752B4CC6",
        "model_revision_id": "MODELREV-6271D5CFBB7C4B33",
        "collection_id": "COLL-39B1E7A06D5C842F",
        "title": "参与者与决定权",
        "routing_summary": "需要判断谁负责、谁不得决定时读取。",
        "child_collection_paths": [],
        "sources": [
            {
                "source_id": "SRC-40C8E5B9127A63DF",
                "title": "参与者",
                "routing_summary": "项目负责人、智能编码代理、程序和外部工具。",
                "path": "docs/domain/sources/actors.yaml",
            }
        ],
    }

    validator = Draft202012Validator(collection_schema)
    assert not list(validator.iter_errors(collection))

    collection["sources"][0]["facts"] = ["不得把正文复制进路由目录"]
    assert list(validator.iter_errors(collection))


def test_repository_model_and_collections_match_contracts() -> None:
    model_path = DOMAIN_ROOT / "model.yaml"
    model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    model_validator = Draft202012Validator(
        _schema("project-domain-model-v1.schema.json")
    )
    assert not list(model_validator.iter_errors(model))

    collection_validator = Draft202012Validator(
        _schema("project-domain-collection-v1.schema.json")
    )
    for relative_path in model["root_collection_paths"]:
        collection = yaml.safe_load(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        assert not list(collection_validator.iter_errors(collection))
        assert collection["model_id"] == model["model_id"]
        assert collection["model_revision_id"] == model["revision"][
            "revision_id"
        ]


def test_repository_foundation_sources_match_contract() -> None:
    source_validator = Draft202012Validator(
        _schema("project-domain-source-v1.schema.json")
    )
    for name in (
        "actors.yaml",
        "decision-authorities.yaml",
        "capabilities.yaml",
        "scenarios-authority.yaml",
        "scenarios-governance.yaml",
        "scenarios-delivery.yaml",
        "scenarios-interface.yaml",
        "entities.yaml",
        "value-objects.yaml",
        "lifecycles.yaml",
        "events.yaml",
        "rules.yaml",
        "invariants.yaml",
        "contexts.yaml",
        "context-relationships.yaml",
        "external-systems.yaml",
        "terms.yaml",
    ):
        source = yaml.safe_load(
            (DOMAIN_ROOT / "sources" / name).read_text(encoding="utf-8")
        )
        assert not list(source_validator.iter_errors(source)), name


def test_repository_capabilities_have_all_required_scenarios_and_real_actors() -> None:
    source_names = (
        "actors.yaml",
        "decision-authorities.yaml",
        "capabilities.yaml",
        "scenarios-authority.yaml",
        "scenarios-governance.yaml",
        "scenarios-delivery.yaml",
        "scenarios-interface.yaml",
    )
    facts = []
    for name in source_names:
        source = yaml.safe_load(
            (DOMAIN_ROOT / "sources" / name).read_text(encoding="utf-8")
        )
        facts.extend(source["facts"])
    by_id = {item["fact_id"]: item for item in facts}
    assert len(by_id) == len(facts)

    product = ProjectProductDefinition(
        PROJECT_ROOT,
        "docs/product/definition.yaml",
    ).load()
    product_capability_ids = {
        item["capability_id"] for item in product["capabilities"]
    }
    capability_facts = [
        item for item in facts if item["kind"] == "product_capability"
    ]
    assert {
        item["product_capability_ids"][0] for item in capability_facts
    } == product_capability_ids
    assert all(len(item["product_capability_ids"]) == 1 for item in capability_facts)

    scenarios = [item for item in facts if item["kind"] == "domain_scenario"]
    expected_types = {"normal", "blocking", "correction", "cancellation"}
    for capability in capability_facts:
        requirements = capability["content"]["scenario_requirements"]
        assert {item["scenario_type"] for item in requirements} == expected_types
        assert all(item["applicability"] == "required" for item in requirements)
        matching = [
            item
            for item in scenarios
            if item["content"]["capability_fact_id"]
            == capability["fact_id"]
        ]
        assert {item["content"]["scenario_type"] for item in matching} == (
            expected_types
        )
        assert len(matching) == 4
        for scenario in matching:
            assert all(
                by_id[actor_id]["kind"] == "actor"
                for actor_id in scenario["content"]["actor_fact_ids"]
            )


def test_repository_model_has_one_closed_identity_and_reference_graph() -> None:
    model, collections, routed_sources = _load_repository_model()
    revision_id = model["revision"]["revision_id"]

    collection_ids = [item["collection_id"] for item in collections]
    assert len(collection_ids) == len(set(collection_ids))

    routes = [item["route"] for item in routed_sources]
    route_ids = [item["source_id"] for item in routes]
    route_paths = [item["path"] for item in routes]
    assert len(route_ids) == len(set(route_ids))
    assert len(route_paths) == len(set(route_paths))

    sources = [item["content"] for item in routed_sources]
    for routed in routed_sources:
        route = routed["route"]
        source = routed["content"]
        assert source["source_id"] == route["source_id"]
        assert source["model_id"] == model["model_id"]
        assert source["model_revision_id"] == revision_id
    facts = [fact for source in sources for fact in source["facts"]]
    by_id = {fact["fact_id"]: fact for fact in facts}
    assert len(by_id) == len(facts)

    active_statuses = {
        "candidate",
        "draft",
        "ready_for_confirmation",
        "confirmed",
    }
    active = {
        fact_id: fact
        for fact_id, fact in by_id.items()
        if fact["status"] in active_statuses
    }
    assert all(
        fact["status"] == model["revision"]["status"]
        for fact in active.values()
    )
    for source in sources:
        assert set(source["scope_fact_ids"]) <= set(active)

    for fact in facts:
        for target_id, expected_kinds in _references_for_fact(fact):
            assert target_id in by_id, (
                f"{fact['fact_id']} 引用未知事实 {target_id}"
            )
            if expected_kinds is not None:
                assert by_id[target_id]["kind"] in expected_kinds, (
                    f"{fact['fact_id']} 对 {target_id} 的类型引用错误"
                )

    assert {
        fact["kind"] for fact in active.values()
    } == {
        "actor",
        "product_capability",
        "domain_scenario",
        "domain_entity",
        "value_object",
        "lifecycle",
        "domain_event",
        "domain_rule",
        "domain_invariant",
        "decision_authority",
        "bounded_context",
        "context_relationship",
        "external_system",
        "term",
    }


def test_repository_model_traces_every_active_fact_to_product_capabilities() -> None:
    model, _, routed_sources = _load_repository_model()
    product = ProjectProductDefinition(
        PROJECT_ROOT,
        "docs/product/definition.yaml",
    ).load()
    assert model["product_definition_ref"] == {
        "product_id": product["product_id"],
        "revision_id": product["revision"]["revision_id"],
    }
    capability_ids = {
        item["capability_id"] for item in product["capabilities"]
    }
    facts = [
        fact
        for source in routed_sources
        for fact in source["content"]["facts"]
    ]
    active = [
        fact
        for fact in facts
        if fact["status"] not in {"superseded", "retired"}
    ]
    for fact in active:
        assert fact["product_capability_ids"], fact["fact_id"]
        assert set(fact["product_capability_ids"]) <= capability_ids

    capability_facts = [
        fact for fact in active if fact["kind"] == "product_capability"
    ]
    assert {
        fact["product_capability_ids"][0] for fact in capability_facts
    } == capability_ids
    assert all(
        len(fact["product_capability_ids"]) == 1
        for fact in capability_facts
    )


def test_repository_model_keeps_domain_meaning_free_of_implementation_evidence() -> None:
    _, _, routed_sources = _load_repository_model()
    forbidden_keys = {
        "evidence",
        "evidence_refs",
        "implementation",
        "implementation_path",
        "implementation_paths",
        "source_path",
        "source_paths",
        "test_path",
        "test_paths",
        "current_module",
        "current_modules",
        "database_table",
        "database_tables",
    }
    for routed in routed_sources:
        source = routed["content"]
        for fact in source["facts"]:
            assert not (set(_walk_keys(fact)) & forbidden_keys), (
                fact["fact_id"]
            )




def test_repository_candidate_binds_the_exact_product_candidate() -> None:
    model, _, _ = _load_repository_model()
    product = ProjectProductDefinition(
        PROJECT_ROOT,
        "docs/product/definition.yaml",
    ).load()
    assert model["revision"]["status"] in {
        "draft",
        "ready_for_confirmation",
        "confirmed",
    }
    assert product["revision"]["status"] in {
        "draft",
        "ready_for_confirmation",
        "confirmed",
    }
    assert model["product_definition_ref"] == {
        "product_id": product["product_id"],
        "revision_id": product["revision"]["revision_id"],
    }
    assert not model["unresolved_decisions"]
