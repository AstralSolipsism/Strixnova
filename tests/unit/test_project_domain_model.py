from __future__ import annotations

from pathlib import Path
import subprocess

import pytest
import yaml

from strixnova.project_domain_model import (
    DOMAIN_FACT_REFERENCE_SCHEMA,
    ProjectDomainModel,
    ProjectDomainModelError,
    validate_domain_fact_reference,
)


PROJECT_ROOT = Path(__file__).parents[2]
MODEL_ID = "MODEL-ABCDEF0123456789"
REVISION_ID = "MODELREV-ABCDEF0123456789"
FACT_ID = "FACT-ABCDEF0123456789"
OWNER_ID = "OWNER-ABCDEF0123456789"
PRODUCT_ID = "PRODUCT-ABCDEF0123456789"
PRODUCT_REVISION_ID = "REVISION-ABCDEF0123456789"


def _write_yaml(project: Path, relative_path: str, value: object) -> None:
    target = project / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _project(project: Path) -> None:
    _write_yaml(
        project,
        "docs/domain/model.yaml",
        {
            "schema_version": "strixnova.project-domain-model.v1",
            "model_id": MODEL_ID,
            "revision": {
                "revision_id": REVISION_ID,
                "status": "confirmed",
                "supersedes_revision_id": None,
                "confirmed_by_owner_id": OWNER_ID,
                "confirmed_on": "2026-08-26",
            },
            "product_definition_ref": {
                "product_id": PRODUCT_ID,
                "revision_id": PRODUCT_REVISION_ID,
            },
            "title": "测试领域模型",
            "purpose": "验证第二版权威读取。",
            "root_collection_paths": [
                "docs/domain/collections/core.yaml"
            ],
            "unresolved_decisions": [],
        },
    )
    _write_yaml(
        project,
        "docs/domain/collections/core.yaml",
        {
            "schema_version": "strixnova.project-domain-collection.v1",
            "model_id": MODEL_ID,
            "model_revision_id": REVISION_ID,
            "collection_id": "COLL-ABCDEF0123456789",
            "title": "核心",
            "routing_summary": "测试核心事实。",
            "child_collection_paths": [],
            "sources": [
                {
                    "source_id": "SRC-ABCDEF0123456789",
                    "title": "参与者",
                    "routing_summary": "测试参与者。",
                    "path": "docs/domain/sources/actors.yaml",
                }
            ],
        },
    )
    _write_yaml(
        project,
        "docs/domain/sources/actors.yaml",
        {
            "schema_version": "strixnova.project-domain-source.v1",
            "model_id": MODEL_ID,
            "model_revision_id": REVISION_ID,
            "source_id": "SRC-ABCDEF0123456789",
            "scope_fact_ids": [],
            "facts": [
                {
                    "fact_id": FACT_ID,
                    "status": "confirmed",
                    "title": "项目负责人",
                    "kind": "actor",
                    "product_capability_ids": [
                        "CAPABILITY-ABCDEF0123456789"
                    ],
                    "scope_fact_ids": [],
                    "dependency_fact_ids": [],
                    "content": {
                        "role": "确认项目方向。",
                        "responsibilities": ["确认真实决定。"],
                        "not_responsible_for": ["代替程序执行。"],
                    },
                }
            ],
        },
    )


def _git(project: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return completed.stdout.strip()


def _append_tombstones(project: Path, *facts: dict) -> None:
    source_path = project / "docs" / "domain" / "sources" / "actors.yaml"
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    source["facts"].extend(facts)
    _write_yaml(project, "docs/domain/sources/actors.yaml", source)


def _tombstone(
    fact_id: str,
    *,
    status: str = "superseded",
    targets: tuple[str, ...] = (),
) -> dict:
    return {
        "fact_id": fact_id,
        "status": status,
        "title": f"历史事实 {fact_id}",
        "kind": "actor",
        "product_capability_ids": ["CAPABILITY-ABCDEF0123456789"],
        "scope_fact_ids": [],
        "dependency_fact_ids": [],
        "lineage": [
            {"relation": "superseded_by", "target_fact_id": target}
            for target in targets
        ],
        "retirement_reason": "保留明确的历史谱系。",
    }


def test_second_version_model_routes_without_dumping_fact_bodies(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    model = ProjectDomainModel(tmp_path, "docs/domain/model.yaml")

    routing = model.routing_catalog()
    collection = model.collection_catalog("COLL-ABCDEF0123456789")
    source = model.source_catalog("SRC-ABCDEF0123456789")

    assert FACT_ID not in repr(routing)
    assert FACT_ID not in repr(collection)
    assert source["facts"] == [
        {
            "fact_id": FACT_ID,
            "status": "confirmed",
            "title": "项目负责人",
            "kind": "actor",
            "product_capability_ids": ["CAPABILITY-ABCDEF0123456789"],
            "scope_fact_ids": [],
            "dependency_fact_ids": [],
        }
    ]
    assert model.fact_body(FACT_ID)["content"]["role"] == "确认项目方向。"


def test_fact_reference_requires_and_resolves_one_immutable_revision(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "domain authority")

    current = ProjectDomainModel(tmp_path, "docs/domain/model.yaml")
    with pytest.raises(ProjectDomainModelError):
        current.fact_reference(FACT_ID)

    observed = ProjectDomainModel(
        tmp_path,
        "docs/domain/model.yaml",
        observed_ref="HEAD",
    )
    reference = observed.fact_reference(FACT_ID)
    assert reference["schema_version"] == DOMAIN_FACT_REFERENCE_SCHEMA
    assert observed.resolve_reference(reference)["fact"]["fact_id"] == FACT_ID


def test_fact_reference_contract_rejects_unpinned_or_unknown_fields() -> None:
    with pytest.raises(ProjectDomainModelError):
        validate_domain_fact_reference(
            {
                "schema_version": DOMAIN_FACT_REFERENCE_SCHEMA,
                "authority_kind": "project_domain_model",
                "model_id": MODEL_ID,
                "fact_id": FACT_ID,
                "observed_commit": "HEAD",
                "meaning": "程序不得接受引用者补写的语义。",
            }
        )


def test_model_rejects_unknown_internal_fact_references(tmp_path: Path) -> None:
    _project(tmp_path)
    source_path = tmp_path / "docs" / "domain" / "sources" / "actors.yaml"
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    source["facts"][0]["dependency_fact_ids"] = [
        "FACT-0000000000000000"
    ]
    _write_yaml(tmp_path, "docs/domain/sources/actors.yaml", source)

    with pytest.raises(ProjectDomainModelError) as raised:
        ProjectDomainModel(tmp_path, "docs/domain/model.yaml").catalog()

    assert any("引用未知事实" in issue for issue in raised.value.issues)


def test_model_rejects_a_self_referencing_lineage(tmp_path: Path) -> None:
    _project(tmp_path)
    identifier = "FACT-1111111111111111"
    _append_tombstones(tmp_path, _tombstone(identifier, targets=(identifier,)))

    with pytest.raises(ProjectDomainModelError) as raised:
        ProjectDomainModel(tmp_path, "docs/domain/model.yaml").catalog()

    assert raised.value.issues == [f"领域事实谱系不得自指：{identifier}"]


@pytest.mark.parametrize(
    "edges",
    [
        (
            ("FACT-1111111111111111", "FACT-2222222222222222"),
            ("FACT-2222222222222222", "FACT-1111111111111111"),
        ),
        (
            ("FACT-1111111111111111", "FACT-2222222222222222"),
            ("FACT-2222222222222222", "FACT-3333333333333333"),
            ("FACT-3333333333333333", "FACT-1111111111111111"),
        ),
    ],
)
def test_model_rejects_direct_and_indirect_lineage_cycles(
    tmp_path: Path,
    edges: tuple[tuple[str, str], ...],
) -> None:
    _project(tmp_path)
    _append_tombstones(
        tmp_path,
        *(
            _tombstone(identifier, targets=(target,))
            for identifier, target in edges
        ),
    )

    with pytest.raises(ProjectDomainModelError) as raised:
        ProjectDomainModel(tmp_path, "docs/domain/model.yaml").catalog()

    assert any("领域事实谱系形成循环" in issue for issue in raised.value.issues)


def test_model_allows_multigeneration_branching_and_retired_endpoints(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    first = "FACT-1111111111111111"
    second = "FACT-2222222222222222"
    retired = "FACT-3333333333333333"
    branch = "FACT-4444444444444444"
    _append_tombstones(
        tmp_path,
        _tombstone(first, targets=(second,)),
        _tombstone(second, targets=(retired,)),
        _tombstone(retired, status="retired"),
        _tombstone(branch, targets=(retired, FACT_ID)),
    )

    catalog = ProjectDomainModel(tmp_path, "docs/domain/model.yaml").catalog()

    assert catalog["counts"]["tombstones"] == 4


def test_repository_domain_model_loads_with_current_fact_counts() -> None:
    catalog = ProjectDomainModel(
        PROJECT_ROOT,
        "docs/domain/model.yaml",
    ).catalog()

    assert catalog["counts"]["active_facts"] == 284
    assert catalog["counts"]["tombstones"] == 0


def test_domain_fact_schema_error_identifies_the_exact_active_content_field(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    source_path = tmp_path / "docs" / "domain" / "sources" / "actors.yaml"
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    source["facts"][0]["content"]["decision_authority"] = [
        "产品负责人确认领域含义。"
    ]
    _write_yaml(tmp_path, "docs/domain/sources/actors.yaml", source)

    with pytest.raises(ProjectDomainModelError) as raised:
        ProjectDomainModel(tmp_path, "docs/domain/model.yaml").catalog()

    assert raised.value.issues == [
        "领域来源 docs/domain/sources/actors.yaml.facts.0.content "
        "不符合当前 v1 结构合同：包含不允许字段：decision_authority"
    ]


def test_domain_fact_schema_error_lists_exact_allowed_kind_values(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    source_path = tmp_path / "docs" / "domain" / "sources" / "actors.yaml"
    source = yaml.safe_load(source_path.read_text(encoding="utf-8"))
    source["facts"][0]["kind"] = "entity"
    _write_yaml(tmp_path, "docs/domain/sources/actors.yaml", source)

    with pytest.raises(ProjectDomainModelError) as raised:
        ProjectDomainModel(tmp_path, "docs/domain/model.yaml").catalog()

    assert len(raised.value.issues) == 1
    issue = raised.value.issues[0]
    assert ".facts.0.kind 不符合当前 v1 结构合同" in issue
    assert "值 'entity' 不在允许集合中" in issue
    assert "'domain_entity'" in issue
