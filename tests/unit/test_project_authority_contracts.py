from __future__ import annotations

from tests.support.project_context import FRONTEND

import hashlib
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from strixnova.git_project_reader import GitProjectReader
from strixnova.implementation_observation import observe_implementation
from strixnova.project_architecture_description import (
    ARCHITECTURE_DESCRIPTION_SCHEMA,
    ProjectArchitectureDescription,
    ProjectArchitectureDescriptionError,
)
from strixnova.project_domain_model import (
    DOMAIN_COLLECTION_SCHEMA,
    DOMAIN_MODEL_SCHEMA,
    DOMAIN_YAML_SOURCE_SCHEMA,
    ProjectDomainModel,
    ProjectDomainModelError,
)
from strixnova.project_implementation_alignment import (
    ProjectImplementationAlignment,
    ProjectImplementationAlignmentError,
    normalized_observed_relations,
)


PROJECT_ROOT = Path(__file__).parents[2]
DOMAIN_MODEL_PATH = "docs/domain/model.yaml"
ARCHITECTURE_PATH = "docs/architecture/model.yaml"
ALIGNMENT_PATH = "docs/implementation-alignment/model.yaml"




def test_domain_runtime_reads_the_current_formal_authority() -> None:
    model = ProjectDomainModel(PROJECT_ROOT, DOMAIN_MODEL_PATH)

    catalog = model.catalog()

    assert DOMAIN_MODEL_SCHEMA == "strixnova.project-domain-model.v1"
    assert DOMAIN_COLLECTION_SCHEMA == "strixnova.project-domain-collection.v1"
    assert DOMAIN_YAML_SOURCE_SCHEMA == "strixnova.project-domain-source.v1"
    assert catalog["schema_version"] == "strixnova.project-domain-catalog.v1"
    assert catalog["revision"]["status"] == "draft"
    assert catalog["counts"] == {
        "collections": 6,
        "sources": 17,
        "active_facts": 284,
        "tombstones": 0,
    }
    assert catalog["semantic_content_machine_proven"] is False


def test_domain_runtime_routes_progressively_and_returns_typed_fact_closure() -> None:
    model = ProjectDomainModel(PROJECT_ROOT, DOMAIN_MODEL_PATH)
    routing = model.routing_catalog()

    assert routing["schema_version"] == "strixnova.project-domain-routing-catalog.v1"
    assert len(routing["root_collections"]) == 6
    assert "facts" not in routing
    assert routing["fact_bodies_included"] is False

    collection = model.collection_catalog(
        routing["root_collections"][0]["collection_id"]
    )
    assert collection["sources"]
    source = model.source_catalog(collection["sources"][0]["source_id"])
    assert source["facts"]
    assert all("content" not in fact for fact in source["facts"])

    catalog = model.catalog()
    selected = next(
        fact for fact in catalog["facts"] if fact["dependency_fact_ids"]
    )
    closure = model.required_closure([selected["fact_id"]])
    assert closure["schema_version"] == "strixnova.domain-fact-closure.v1"
    assert closure["bodies_loaded"] is True
    assert selected["fact_id"] in closure["fact_ids"]
    assert set(selected["dependency_fact_ids"]) <= set(closure["fact_ids"])
    assert {fact["fact_id"] for fact in closure["facts"]} == set(
        closure["fact_ids"]
    )


def test_domain_runtime_rejects_an_unknown_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "domain.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "strixnova.project-domain-model.v999",
                "model_id": "MODEL-2F8356E6752B4CC6",
                "title": "旧领域模型",
                "facts": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectDomainModelError) as raised:
        ProjectDomainModel(tmp_path, "domain.yaml").catalog()

    assert any("当前 v1" in issue for issue in raised.value.issues)


def test_architecture_runtime_reads_and_validates_the_complete_target() -> None:
    architecture = ProjectArchitectureDescription(
        PROJECT_ROOT,
        ARCHITECTURE_PATH,
    )

    loaded = architecture.load()
    decisions = architecture.decision_catalog()

    assert ARCHITECTURE_DESCRIPTION_SCHEMA == (
        "strixnova.project-architecture-description.v1"
    )
    assert loaded["revision"]["status"] == "draft"
    assert loaded["revision"]["supersedes_revision_id"] is None
    assert len(loaded["modules"]) == 21
    assert len(loaded["relationships"]) == 83
    assert len(loaded["constraints"]) == 33
    assert len(loaded["domain_fact_dispositions"]) == 284
    assert loaded["semantic_content_machine_proven"] is False
    assert decisions["default_relationship_policy"] == "forbidden"
    assert decisions["direct_dependency_graph_acyclic"] is True
    assert set(decisions["module_ids"]) == {
        module["module_id"] for module in loaded["modules"]
    }


def test_architecture_runtime_rejects_an_unknown_contract(
    tmp_path: Path,
) -> None:
    path = tmp_path / "architecture.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": "strixnova.project-architecture-description.v999",
                "architecture_id": "ARCH-963827FB26C94363",
                "title": "无效架构合同",
                "principles": ["示例原则"],
                "adr_directory": "docs/adr",
                "modules": [],
                "module_relationships": [],
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ProjectArchitectureDescriptionError) as raised:
        ProjectArchitectureDescription(tmp_path, "architecture.yaml").load()

    assert any("当前 v1" in issue for issue in raised.value.issues)


def test_architecture_runtime_reports_exact_subordinate_field_errors(
    tmp_path: Path,
) -> None:
    architecture_dir = tmp_path / "docs" / "architecture"
    shutil.copytree(PROJECT_ROOT / "docs" / "architecture", architecture_dir)
    modules_path = architecture_dir / "modules.yaml"
    modules = yaml.safe_load(modules_path.read_text(encoding="utf-8"))
    first_module = modules["modules"][0]
    first_module["responsibilities"] = first_module.pop("responsibility")
    modules_path.write_text(
        yaml.safe_dump(modules, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectArchitectureDescriptionError) as raised:
        ProjectArchitectureDescription(
            tmp_path,
            ARCHITECTURE_PATH,
        ).load()

    issues = raised.value.issues
    assert any(
        "目标架构产物 modules.modules.0" in issue
        and "缺少必填字段：responsibility" in issue
        for issue in issues
    )
    assert any(
        "目标架构产物 modules.modules.0" in issue
        and "包含不允许字段：responsibilities" in issue
        for issue in issues
    )
    assert all("not valid under any" not in issue for issue in issues)


def test_alignment_runtime_reports_exact_subordinate_field_errors(tmp_path: Path) -> None:
    from tests.support.implementation_alignment import isolated_alignment

    reader = isolated_alignment(tmp_path)
    model = yaml.safe_load((tmp_path / reader.alignment_path).read_text(encoding="utf-8"))
    ownership_path = tmp_path / model["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["source_path"] = ownership["records"][0].pop("path")
    ownership_path.write_text(yaml.safe_dump(ownership, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProjectImplementationAlignmentError) as raised:
        reader.load()
    issues = raised.value.issues
    assert any("实现对齐产物 source_ownership.records.0" in issue and "缺少必填字段：path" in issue for issue in issues)
    assert any("实现对齐产物 source_ownership.records.0" in issue and "包含不允许字段：source_path" in issue for issue in issues)
    assert all("not valid under any" not in issue for issue in issues)



def test_alignment_runtime_rejects_empty_sources_claimed_as_complete(
    tmp_path: Path,
) -> None:
    from tests.support.implementation_alignment import isolated_alignment

    reader = isolated_alignment(tmp_path)
    model_path = tmp_path / reader.alignment_path
    model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    scope_id = model["observation_scopes"][0]["scope_id"]
    model["observation_scopes"][0].update(
        {
            "root": "src",
            "languages": ["python"],
            "provider_options": {"python_package_name": "src"},
        }
    )
    model["observation_coverage"]["records"][0].update(
        {
            "scope_id": scope_id,
            "source_file_count": 0,
            "relation_count": 0,
            "observed_relation_kinds": [],
            "limitations": [],
            "gaps": [],
            "status": "complete",
        }
    )
    model_path.write_text(
        yaml.safe_dump(model, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    ownership_path = tmp_path / model["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["governed_source_scopes"][0].update(
        {
            "root": "src",
            "included_path_patterns": ["*.py", "**/*.py"],
        }
    )
    ownership["records"] = []
    ownership_path.write_text(
        yaml.safe_dump(ownership, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    dependencies_path = tmp_path / model["artifact_paths"]["actual_dependencies"]
    dependencies = yaml.safe_load(
        dependencies_path.read_text(encoding="utf-8")
    )
    dependencies["records"] = []
    dependencies_path.write_text(
        yaml.safe_dump(dependencies, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectImplementationAlignmentError) as captured:
        reader.load()

    assert any(
        "完整观察覆盖必须包含实际源码" in issue
        for issue in captured.value.issues
    )


def test_python_observation_rejects_a_src_container_instead_of_hiding_internal_edges(
    tmp_path: Path,
) -> None:
    subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    package = tmp_path / "src" / "inventory_alert"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "domain.py").write_text(
        "def evaluate():\n    return []\n",
        encoding="utf-8",
    )
    (package / "__main__.py").write_text(
        "from inventory_alert.domain import evaluate\n",
        encoding="utf-8",
    )

    observed = observe_implementation(
        tmp_path,
        [
            {
                "scope_id": "OBSCOPE-1111111111111111",
                "root": "src",
                "languages": ["python"],
                "required_relation_kinds": ["source_import"],
                "configurations": ["default"],
                "exclusions": [],
                "provider_options": {"python_package_name": "src"},
            }
        ],
    )

    assert observed["overall_coverage_status"] == "failed"
    gap = observed["coverage"][0]["gaps"][0]
    assert gap["code"] == "python_source_container_ambiguous"
    assert "src/inventory_alert" in gap["message"]


def test_alignment_drift_scans_the_declared_project_package(tmp_path: Path) -> None:
    from copy import deepcopy
    from strixnova.implementation_observation import observe_project_implementation
    from strixnova.project_content_snapshot import repository_path_key
    from tests.support.project_baseline import portable_project_baseline, adopt_portable_ddd, TEST_MODULE_ID, TEST_STAGE_ID
    from tests.support.project_context import repository, git

    tmp_path = tmp_path / "project"
    repository(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src/__init__.py").write_text("from src.domain import evaluate\n", encoding="utf-8")
    (tmp_path / "src/domain.py").write_text("def evaluate():\n    return []\n", encoding="utf-8")
    baseline = portable_project_baseline(tmp_path, baseline_id="declared-package", artifacts=[])
    identities = adopt_portable_ddd(tmp_path, baseline, implementation_path="src/__init__.py")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "fixed package inputs")
    reader = GitProjectReader(tmp_path)
    reader.bind_repository_identity(FRONTEND)
    readers = {FRONTEND: reader}
    model_path = tmp_path / identities["alignment_path"]
    model = yaml.safe_load(model_path.read_text(encoding="utf-8"))
    scope = model["observation_scopes"][0]
    scope["root"] = "src"
    scope["provider_options"] = {"python_package_name": "src"}
    observation = observe_project_implementation(readers, [scope])
    hashes = observation["observed_paths"]
    model["code_snapshot"] = {
        "repositories": [{"repository_id": FRONTEND, "base_commit": git(tmp_path, "rev-parse", "HEAD"), "worktree_state": "dirty"}],
        "observed_on": "2026-09-28",
        "governed_source_manifest_sha256": hashlib.sha256("".join(f"{key}:{digest}\n" for key, digest in sorted(hashes.items())).encode()).hexdigest(),
    }
    model["observation_coverage"] = {
        "contract_version": observation["schema_version"], "overall_status": observation["overall_coverage_status"],
        "source_manifest_sha256": observation["source_manifest_sha256"], "observation_snapshot_sha256": observation["observation_snapshot_sha256"],
        "observed_paths": hashes, "records": observation["coverage"], "provider_receipts": observation["provider_receipts"],
    }
    ownership_path = tmp_path / model["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["governed_source_scopes"][0].update(root="src", included_path_patterns=["*.py", "**/*.py"])
    record = ownership["records"][0]
    ownership["records"] = [{**deepcopy(record), "path": path, "sha256": hashes[repository_path_key(FRONTEND, path)]} for path in ("src/__init__.py", "src/domain.py")]
    dependencies_path = tmp_path / model["artifact_paths"]["actual_dependencies"]
    dependencies = yaml.safe_load(dependencies_path.read_text(encoding="utf-8"))
    relations = normalized_observed_relations(observation)
    assert len(relations) == 1
    dependencies["records"] = [{**relations[0], "source_module_id": TEST_MODULE_ID, "target_module_id": TEST_MODULE_ID, "classification": "internal_same_module", "target_relationship_id": None, "deviation_ids": [], "rationale": "同一模块内部导入"}]
    for destination, value in ((model_path, model), (ownership_path, ownership), (dependencies_path, dependencies)):
        destination.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    result = ProjectImplementationAlignment(tmp_path, identities["alignment_path"], domain_model_path=identities["model_path"], architecture_description_path=identities["architecture_path"], shared_reader=reader, repository_readers=readers).drift()
    assert result["passed"] is True, result["failures"]
    assert result["counts"]["classified_relations"] == 1
