"""Explicit checks of this repository's recorded engineering materials.

These compare current repository state with accepted evidence; they are not
Strixnova behavior regression tests and are outside the default testpaths.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator
import yaml

from strixnova.git_project_reader import GitProjectReader
from strixnova.implementation_observation import observe_project_implementation
from strixnova.project_context import ProjectContextResolver
from strixnova.project_content_snapshot import repository_path_key
from strixnova.project_implementation_alignment import (
    normalized_observed_relations,
)


PROJECT_ROOT = Path(__file__).parents[2]
ALIGNMENT_ROOT = PROJECT_ROOT / "docs" / "implementation-alignment"
ARCHITECTURE_ROOT = PROJECT_ROOT / "docs" / "architecture"
DOMAIN_ROOT = PROJECT_ROOT / "docs" / "domain"
IMPLEMENTATION_ROOT = PROJECT_ROOT / "strixnova" / "src" / "strixnova"


def _repository_id() -> str:
    return yaml.safe_load((PROJECT_ROOT / "strixnova-project.yaml").read_text(encoding="utf-8"))["repository_id"]


def _schema() -> dict:
    return json.loads(
        (
            ALIGNMENT_ROOT
            / "contracts"
            / "project-implementation-alignment-v1.schema.json"
        ).read_text(encoding="utf-8")
    )


def _alignment() -> tuple[dict, dict[str, dict]]:
    model = yaml.safe_load(
        (ALIGNMENT_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    artifacts = {
        name: yaml.safe_load(
            (PROJECT_ROOT / relative_path).read_text(encoding="utf-8")
        )
        for name, relative_path in model["artifact_paths"].items()
    }
    return model, artifacts


def _architecture() -> tuple[dict, dict[str, dict]]:
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


def _scope_contains_path(scope: dict, path: str) -> bool:
    root = Path(scope["root"])
    candidate = Path(path)
    try:
        relative = candidate.relative_to(root)
    except ValueError:
        return False
    return any(
        relative.match(pattern) or relative.as_posix() == pattern
        for pattern in scope["included_path_patterns"]
    )


def _governed_files(scopes: list[dict]) -> list[Path]:
    paths: set[Path] = set()
    for scope in scopes:
        root = PROJECT_ROOT / scope["root"]
        paths.update(
            path
            for path in root.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and _scope_contains_path(scope, _repository_path(path))
        )
    return sorted(paths, key=lambda path: path.as_posix())


def _repository_path(path: Path) -> str:
    return path.relative_to(PROJECT_ROOT).as_posix()


def _governed_manifest(files: list[Path]) -> tuple[dict[str, str], str]:
    reader = GitProjectReader(PROJECT_ROOT)
    hashes = {
        relative_path: hashlib.sha256(
            reader.read_canonical_bytes(relative_path, "受管实现文件")
        ).hexdigest()
        for path in files
        for relative_path in [_repository_path(path)]
    }
    content = "".join(
        f"{repository_path_key(_repository_id(), path)}:{digest}\n" for path, digest in sorted(hashes.items())
    )
    return hashes, hashlib.sha256(content.encode("utf-8")).hexdigest()




def test_repository_alignment_artifacts_match_the_contract() -> None:
    model, artifacts = _alignment()
    validator = Draft202012Validator(_schema())
    assert not list(validator.iter_errors(model))
    for name, artifact in artifacts.items():
        assert not list(validator.iter_errors(artifact)), name
        assert artifact["alignment_model_id"] == model["alignment_model_id"]
        assert artifact["alignment_revision_id"] == model["revision"][
            "revision_id"
        ]


def test_alignment_is_bound_to_exact_authorities_and_an_ancestor_observation() -> None:
    model, _ = _alignment()
    domain = yaml.safe_load(
        (DOMAIN_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    architecture, _ = _architecture()
    assert model["domain_model_ref"] == {
        "model_id": domain["model_id"],
        "revision_id": domain["revision"]["revision_id"],
    }
    assert model["architecture_ref"] == {
        "architecture_id": architecture["architecture_id"],
        "revision_id": architecture["revision"]["revision_id"],
    }

    head = subprocess.run(
        ["git", "-c", "safe.directory="+PROJECT_ROOT.as_posix(), "rev-parse", "HEAD"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()
    ancestry = subprocess.run(
        [
            "git",
            "-c",
            "safe.directory="+PROJECT_ROOT.as_posix(),
            "merge-base",
            "--is-ancestor",
            model["code_snapshot"]["repositories"][0]["base_commit"],
            head,
        ],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    assert ancestry.returncode == 0
    assert model["code_snapshot"]["repositories"][0]["worktree_state"] in {"clean", "dirty"}


def test_source_ownership_covers_every_governed_file_once_with_current_hashes() -> None:
    model, artifacts = _alignment()
    ownership = artifacts["source_ownership"]["records"]
    paths = [item["path"] for item in ownership]
    assert len(paths) == len(set(paths))
    assert all(row["repository_id"] == _repository_id() for row in ownership)

    files = _governed_files(artifacts["source_ownership"]["governed_source_scopes"])
    hashes, manifest = _governed_manifest(files)
    assert set(paths) == set(hashes)
    assert {
        item["path"]: item["sha256"] for item in ownership
    } == hashes
    assert model["code_snapshot"]["governed_source_manifest_sha256"] == manifest

    architecture, architecture_artifacts = _architecture()
    del architecture
    module_ids = {
        item["module_id"]
        for item in architecture_artifacts["modules"]["modules"]
    }
    stage_ids = {
        item["stage_id"]
        for item in architecture_artifacts["implementation_stages"]["stages"]
    }
    for record in ownership:
        if record["disposition"] == "owned":
            assert record["target_module_id"] in module_ids
            assert record["implementation_stage_id"] in stage_ids
        else:
            assert record["node_kind"] == "package_metadata"
            assert record["current_status"] == "not_applicable"


def test_actual_dependency_ledger_exactly_matches_the_normalized_observation() -> None:
    model, artifacts = _alignment()
    recorded = artifacts["actual_dependencies"]["records"]
    context = ProjectContextResolver(PROJECT_ROOT).configured()
    observation = observe_project_implementation({_repository_id(): context.configuration_reader}, model["observation_scopes"])
    scanned = normalized_observed_relations(observation)
    expected = {
        (
            item["scope_id"],
            item["provider_id"],
            item["source_node_id"],
            item["target_node_id"],
            item["relation_kind"],
            item["resolution_status"],
            tuple(item["conditions"]),
        ): tuple(item["observed_names"])
        for item in scanned
    }
    actual = {
        (
            item["scope_id"],
            item["provider_id"],
            item["source_node_id"],
            item["target_node_id"],
            item["relation_kind"],
            item["resolution_status"],
            tuple(item["conditions"]),
        ): tuple(item["observed_names"])
        for item in recorded
    }
    assert actual == expected
    assert model["observation_coverage"] == {
        "contract_version": observation["schema_version"],
        "overall_status": observation["overall_coverage_status"],
        "source_manifest_sha256": observation["source_manifest_sha256"],
        "observation_snapshot_sha256": observation[
            "observation_snapshot_sha256"
        ],
        "observed_paths": observation["observed_paths"],
        "records": observation["coverage"],
        "provider_receipts": observation["provider_receipts"],
    }


def test_dependency_classifications_follow_target_relationships() -> None:
    _, artifacts = _alignment()
    _, architecture_artifacts = _architecture()
    ownership = {
        item["path"]: item
        for item in artifacts["source_ownership"]["records"]
    }
    relationships = {
        (item["from_module_id"], item["to_module_id"]): item
        for item in architecture_artifacts["relationships"]["relationships"]
    }
    classification_for_mode = {
        "direct": "allowed_direct",
        "read_only_projection": "allowed_read_only",
        "through_module": "requires_mediator_but_direct",
        "forbidden": "forbidden",
    }
    for record in artifacts["actual_dependencies"]["records"]:
        source = ownership[record["source_path"]]
        assert source["disposition"] == "owned"
        source_module = source["target_module_id"]
        assert record["source_module_id"] == source_module
        if record["resolution_status"] == "external":
            assert record["target_path"] is None
            assert record["target_external_name"]
            assert record["target_module_id"] is None
            assert record["classification"] == "external_observed"
            assert record["target_relationship_id"] is None
            continue
        assert record["resolution_status"] == "resolved_internal"
        target = ownership[record["target_path"]]
        assert target["disposition"] == "owned"
        target_module = target["target_module_id"]
        assert record["target_module_id"] == target_module
        if source_module == target_module:
            assert record["classification"] == "internal_same_module"
            assert record["target_relationship_id"] is None
            continue
        relationship = relationships.get((source_module, target_module))
        if relationship is None:
            assert record["classification"] == "undeclared"
            assert record["target_relationship_id"] is None
        else:
            assert record["classification"] == classification_for_mode[
                relationship["mode"]
            ]
            assert (
                record["target_relationship_id"]
                == relationship["relationship_id"]
            )








def test_target_responsibility_ledger_covers_every_architecture_target_once() -> None:
    _, artifacts = _alignment()
    _, architecture_artifacts = _architecture()
    expected = {
        ("module", item["module_id"])
        for item in architecture_artifacts["modules"]["modules"]
    }
    expected.update(
        ("relationship", item["relationship_id"])
        for item in architecture_artifacts["relationships"]["relationships"]
    )
    expected.update(
        ("constraint", item["constraint_id"])
        for item in architecture_artifacts["constraints"]["constraints"]
    )
    records = artifacts["target_responsibilities"]["records"]
    actual = {(item["target_kind"], item["target_id"]) for item in records}
    assert len(actual) == len(records)
    assert actual == expected
    assert not any(item["status"] == "unknown" for item in records)


def test_every_deviation_reference_is_defined_and_every_deviation_is_used() -> None:
    _, artifacts = _alignment()
    deviations = {
        item["deviation_id"]
        for item in artifacts["deviations"]["deviations"]
    }
    referenced: set[str] = set()
    for record in artifacts["source_ownership"]["records"]:
        referenced.update(record["deviation_ids"])
    for record in artifacts["actual_dependencies"]["records"]:
        referenced.update(record["deviation_ids"])
    for record in artifacts["target_responsibilities"]["records"]:
        referenced.update(record["deviation_ids"])
    assert referenced == deviations


def test_all_domain_fact_implementation_states_are_derivable_from_architecture() -> None:
    _, artifacts = _alignment()
    _, architecture_artifacts = _architecture()
    responsibility_status = {
        item["target_id"]: item["status"]
        for item in artifacts["target_responsibilities"]["records"]
    }
    priority = {
        "unknown": 5,
        "drifted": 4,
        "not_implemented": 3,
        "partially_implemented": 2,
        "implemented": 1,
    }
    derived: dict[str, str] = {}
    for disposition in architecture_artifacts["domain_fact_dispositions"][
        "dispositions"
    ]:
        disposition_type = disposition["disposition_type"]
        if disposition_type == "no_independent_implementation":
            derived[disposition["domain_fact_id"]] = (
                "no_independent_implementation"
            )
            continue
        if disposition_type == "primary_module":
            target_ids = [disposition["primary_module_id"]]
        elif disposition_type == "module_relationship":
            target_ids = disposition["relationship_ids"]
        elif disposition_type == "architecture_constraint":
            target_ids = disposition["constraint_ids"]
        else:
            raise AssertionError(disposition["domain_fact_id"])
        statuses = [responsibility_status[target_id] for target_id in target_ids]
        derived[disposition["domain_fact_id"]] = max(
            statuses,
            key=priority.__getitem__,
        )
    assert set(derived) == set(
        item["domain_fact_id"]
        for item in architecture_artifacts["domain_fact_dispositions"][
            "dispositions"
        ]
    )


def test_alignment_cannot_be_confirmable_before_target_authorities() -> None:
    model, _ = _alignment()
    domain = yaml.safe_load(
        (DOMAIN_ROOT / "model.yaml").read_text(encoding="utf-8")
    )
    architecture, _ = _architecture()
    if model["revision"]["status"] in {
        "ready_for_confirmation",
        "confirmed",
    }:
        assert domain["revision"]["status"] == "confirmed"
        assert architecture["revision"]["status"] == "confirmed"
        assert not model["unresolved_items"]
    else:
        assert model["revision"]["status"] == "draft"
