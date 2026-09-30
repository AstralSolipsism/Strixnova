from __future__ import annotations

from tests.support.project_context import FRONTEND

from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

from click.testing import CliRunner
from jsonschema import Draft202012Validator
import pytest
import yaml

import strixnova.implementation_alignment_preparation as alignment_module
from strixnova.application_coordinator import ApplicationCoordinator
from strixnova.cli import main
from strixnova.implementation_alignment_preparation import (
    ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
    ALIGNMENT_INSPECTION_RESULT_SCHEMA,
    ALIGNMENT_PREPARATION_PACKET_SCHEMA,
    ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
    ImplementationAlignmentPreparation,
    ImplementationAlignmentPreparationError,
)
from strixnova.implementation_alignment_artifacts import (
    GC_RESULT_SCHEMA,
    ImplementationAlignmentArtifactStore,
    MANIFEST_LAYOUT_SCHEMA,
    MAX_CHUNK_BYTES,
    PAGE_TARGET_BYTES,
)
from strixnova.project_implementation_alignment import (
    ProjectImplementationAlignment,
)
from strixnova.project_architecture_description import ProjectArchitectureDescription
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.project_baseline import (
    TEST_ALIGNMENT_ID,
    TEST_ALIGNMENT_REVISION_ID,
    portable_project_baseline,
)


def _current(project: Path) -> dict:
    paths = [
        "docs/implementation-alignment/model.yaml",
        "docs/implementation-alignment/source-ownership.yaml",
        "docs/implementation-alignment/actual-dependencies.yaml",
        "docs/implementation-alignment/target-responsibilities.yaml",
        "docs/implementation-alignment/deviations.yaml",
        "docs/engineering/baseline.yaml",
    ]
    operations = [
        {
            "action": "modify",
            "path": path,
            "long_lived_artifact": (
                {
                    "artifact_id": "ALIGNMODEL-1111111111111111",
                    "artifact_type": "domain_alignment",
                }
                if index == 0
                else None
            ),
        }
        for index, path in enumerate(paths)
    ]
    return {
        "work_item_id": "WI-ALIGNMENT-001",
        "version": 7,
        "status": "implementing",
        "data": {
            "engineering": {
                "plan": {
                    "plan_id": "PLAN-ALIGNMENT-001",
                    "operations": operations,
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "operation_refs": [
                                f"operations[{index}]"
                                for index in range(len(operations))
                            ],
                            "continued_operation_refs": [],
                            "depends_on": [],
                            "verification_command_ids": [],
                        }
                    ],
                    "external_observation_provider_plans": [],
                },
                "plan_confirmation": {"accepted": True},
            },
            "git": {"worktree_path": str(project)},
            "verifications": [],
            "implementation_slice_completions": [],
        },
    }


def _git(project: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _complete_project(project: Path) -> tuple[dict, dict]:
    (project / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    _git(project, "add", "src.py")
    _git(project, "commit", "-m", "initial evidence")
    baseline = portable_project_baseline(
        project,
        baseline_id="alignment-preparation",
        artifacts=[],
    )
    baseline["code_version"]["repositories"][0]["base_commit"] = _git(
        project, "rev-parse", "HEAD"
    )
    baseline_path = project / "docs/engineering/baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    current = _current(project)
    alignment_path = baseline["authority_refs"]["implementation_alignment"][
        "path"
    ]
    alignment = yaml.safe_load((project / alignment_path).read_text(encoding="utf-8"))
    planned_paths = [
        alignment_path,
        *alignment["artifact_paths"].values(),
        "docs/engineering/baseline.yaml",
    ]
    operations = [
        {
            "action": "modify",
            "path": path,
            **(
                {
                    "long_lived_artifact": {
                        "artifact_id": TEST_ALIGNMENT_ID,
                        "artifact_type": "domain_alignment",
                    }
                }
                if index == 0
                else {}
            ),
        }
        for index, path in enumerate(planned_paths)
    ]
    plan = current["data"]["engineering"]["plan"]
    plan["operations"] = operations
    plan["implementation_slices"][0]["operation_refs"] = [
        f"operations[{index}]" for index in range(len(operations))
    ]
    return current, baseline


def _persist_current_authority(project: Path, current: dict) -> dict:
    """Seed a canonical Authority store for an application-boundary fixture."""

    authority = WorkflowAuthority(project)
    created = authority.create(
        title="Prepare implementation alignment",
        raw_request="Exercise the installed alignment application entry.",
    )
    seeded = deepcopy(current)
    seeded["work_item_id"] = created["work_item_id"]
    with sqlite3.connect(authority.database_path) as connection:
        connection.create_function("strixnova_write_contract", 0, lambda: 1)
        connection.execute(
            """
            UPDATE work_items
            SET status = ?, version = ?, data_json = ?
            WHERE work_item_id = ?
            """,
            (
                seeded["status"],
                seeded["version"],
                json.dumps(seeded["data"], ensure_ascii=False),
                seeded["work_item_id"],
            ),
        )
    return authority.get(seeded["work_item_id"])


def _scope(
    scope_id: str,
    root: str,
    language: str,
    relation_kinds: list[str],
    **provider_options: object,
) -> dict[str, object]:
    return {
        "scope_id": scope_id,
        "root": root,
        "languages": [language],
        "required_relation_kinds": relation_kinds,
        "configurations": ["default"],
        "exclusions": [],
        "provider_options": provider_options,
    }


def _first_alignment_request(
    project: Path,
    baseline: dict,
    scopes: list[dict[str, object]],
    *,
    revision_id: str,
) -> dict[str, object]:
    alignment_relative = baseline["authority_refs"]["implementation_alignment"][
        "path"
    ]
    alignment_path = project / alignment_relative
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    artifact_paths = alignment["artifact_paths"]
    alignment_path.unlink()
    for relative in artifact_paths.values():
        (project / relative).unlink()
    return {
        "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
        "alignment_revision_id": revision_id,
        "supersedes_revision_id": None,
        "observation_scopes": scopes,
        "governed_source_scopes": [
            {
                "scope_id": scope["scope_id"],
                "root": scope["root"],
                "included_path_patterns": ["*", "**/*"],
                "included_node_kinds": ["source_file", "build_manifest"],
                "exclusion_policy": "The test scope has no implicit exclusions.",
            }
            for scope in scopes
        ],
        "artifact_paths": artifact_paths,
    }


def test_single_module_and_root_sources_prepare_without_layout_changes(tmp_path: Path) -> None:
    current, baseline = _complete_project(tmp_path)
    ref = baseline["authority_refs"]["target_architecture"]
    architecture_path = tmp_path / ref["path"]
    architecture = yaml.safe_load(architecture_path.read_text(encoding="utf-8"))
    for kind in ("modules", "relationships", "constraints", "implementation_stages"):
        path = tmp_path / architecture["artifact_paths"][kind]
        body = yaml.safe_load(path.read_text(encoding="utf-8"))
        if kind == "modules":
            body["modules"] = body["modules"][:1]
            module_id = body["modules"][0]["module_id"]
        elif kind == "relationships":
            body["relationships"] = []
        elif kind == "constraints":
            for constraint in body["constraints"]:
                constraint["applies_to_module_ids"] = [module_id]
        else:
            for stage in body["stages"]:
                stage["module_ids"] = [module_id]
        path.write_text(yaml.safe_dump(body, allow_unicode=True, sort_keys=False), encoding="utf-8")
    loaded = ProjectArchitectureDescription(tmp_path, ref["path"]).load()
    assert len(loaded["modules"]) == 1
    assert loaded["relationships"] == []
    original_source = (tmp_path / "src.py").read_bytes()
    request = _first_alignment_request(
        tmp_path, baseline,
        [_scope("OBSCOPE-1212121212121212", ".", "python", ["source_import"])],
        revision_id="ALIGNREV-2222222222222222",
    )
    request["governed_source_scopes"][0]["included_path_patterns"] = ["src.py"]
    module = ImplementationAlignmentPreparation(tmp_path)
    prepared = module.prepare(current, request)
    packet = module._load_preparation(prepared["preparation_ref"])
    scoped_path = baseline["authority_refs"]["implementation_alignment"]["repository_id"] + ":src.py"
    assert scoped_path in packet["observation"]["observed_paths"]
    assert (tmp_path / "src.py").read_bytes() == original_source
    assert alignment_module._governed_hashes(tmp_path, request["governed_source_scopes"]) == {
        "src.py": packet["observation"]["observed_paths"][scoped_path],
    }


def test_binding_requires_one_current_alignment_operation(tmp_path: Path) -> None:
    module = ImplementationAlignmentPreparation(tmp_path)
    binding = module._binding(_current(tmp_path))

    assert binding["alignment_path"] == (
        "docs/implementation-alignment/model.yaml"
    )
    assert binding["alignment_model_id"] == "ALIGNMODEL-1111111111111111"
    assert binding["slice_id"] == "SLICE-001"
    assert binding["work_item_version"] == 7

    stale = _current(tmp_path)
    stale["status"] = "awaiting_actual_result"
    with pytest.raises(ImplementationAlignmentPreparationError) as captured:
        module._binding(stale)
    assert captured.value.code == "alignment_current_action_mismatch"


def test_preparation_store_is_content_addressed_without_mutable_pointer(
    tmp_path: Path,
) -> None:
    module = ImplementationAlignmentPreparation(tmp_path)
    packet = {
        "schema_version": ALIGNMENT_PREPARATION_PACKET_SCHEMA,
        "binding": {},
    }

    first = module._store_json("preparations", packet)
    second = module._store_json("preparations", packet)

    assert first == second
    assert first["path"].endswith(first["content_sha256"] + ".json")
    assert module._load_preparation(first) == packet
    manifest = json.loads(
        tmp_path.joinpath(*Path(first["path"]).parts).read_text(encoding="utf-8")
    )
    assert manifest["artifact_layout_schema"] == MANIFEST_LAYOUT_SCHEMA
    assert manifest["component_refs"] == {}
    artifact_root = tmp_path / ".strixnova" / "artifacts" / (
        "implementation-alignment"
    )
    assert not (artifact_root / "current").exists()
    assert not (artifact_root / "current.json").exists()

    substituted = dict(first)
    substituted["artifact_id"] = "ALIGNPREP-FFFFFFFFFFFFFFFF"
    with pytest.raises(ImplementationAlignmentPreparationError) as identity:
        module._load_preparation(substituted)
    assert identity.value.code == "alignment_preparation_ref_invalid"

    stored = tmp_path.joinpath(*Path(first["path"]).parts)
    stored.write_text("{}", encoding="utf-8")
    with pytest.raises(ImplementationAlignmentPreparationError) as captured:
        module._load_preparation(first)
    assert captured.value.code == "alignment_preparation_changed"


def test_large_preparation_is_a_small_manifest_with_deduplicated_pages(
    tmp_path: Path,
) -> None:
    module = ImplementationAlignmentPreparation(tmp_path)
    decisions = [
        {
            "decision_ref": f"ALIGNDECISION-{index:016X}",
            "kind": "source_record",
            "required": True,
            "facts": {
                "scope_id": "OBSCOPE-1111111111111111",
                "path": f"src/package_{index // 100}/file_{index}.ts",
                "sha256": f"{index:064x}",
                "previous": None,
            },
            "required_value_fields": ["rationale"],
        }
        for index in range(4000)
    ]
    packet = {
        "schema_version": ALIGNMENT_PREPARATION_PACKET_SCHEMA,
        "binding": {},
        "target_file_bindings": {},
        "decision_catalog": decisions,
        "observation": {
            "nodes": [
                {
                    "node_id": f"NODE-{index:016X}",
                    "path": f"src/file_{index}.ts",
                }
                for index in range(4000)
            ],
            "relations": [],
            "observed_paths": {
                f"src/file_{index}.ts": f"{index:064x}"
                for index in range(4000)
            },
        },
    }

    first = module._store_json("preparations", packet)
    manifest_path = tmp_path.joinpath(*Path(first["path"]).parts)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    component_root = (
        tmp_path
        / ".strixnova"
        / "artifacts"
        / "implementation-alignment"
        / "components"
    )
    components = list(component_root.glob("*.json"))
    before_count = len(components)
    second = module._store_json("preparations", packet)

    assert first == second
    assert len(manifest_path.read_bytes()) < PAGE_TARGET_BYTES
    assert set(manifest["component_refs"]) == {
        "decision_catalog",
        "observation",
    }
    assert max(path.stat().st_size for path in components) <= MAX_CHUNK_BYTES
    assert len(list(component_root.glob("*.json"))) == before_count
    assert module._load_preparation(first) == packet


def test_alignment_cli_group_routes_small_structured_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    def prepare(self, work_item_id, request, *, expected_version):
        calls.append(("prepare", request))
        return {"work_item_id": work_item_id, "version": expected_version}

    def capture(
        self,
        work_item_id,
        preparation_ref,
        *,
        authorize_external,
        expected_version,
    ):
        calls.append(("capture", authorize_external))
        return {"work_item_id": work_item_id, "version": expected_version}

    def inspect(
        self,
        work_item_id,
        preparation_ref,
        *,
        cursor,
        limit,
        expected_version,
    ):
        calls.append(("inspect", (cursor, limit, preparation_ref["content_sha256"])))
        return {"work_item_id": work_item_id, "version": expected_version}

    def write(self, work_item_id, payload, *, expected_version):
        calls.append(("write", payload["schema_version"]))
        return {"work_item_id": work_item_id, "version": expected_version}

    def garbage_collect(
        self,
        *,
        apply,
        expected_orphan_set_sha256,
    ):
        calls.append(("gc", (apply, expected_orphan_set_sha256)))
        return {"mode": "dry_run"}

    monkeypatch.setattr(
        ApplicationCoordinator,
        "prepare_implementation_alignment",
        prepare,
    )
    monkeypatch.setattr(
        ApplicationCoordinator,
        "inspect_implementation_alignment",
        inspect,
    )
    monkeypatch.setattr(
        ApplicationCoordinator,
        "capture_external_implementation_alignment",
        capture,
    )
    monkeypatch.setattr(
        ApplicationCoordinator,
        "write_implementation_alignment_candidate",
        write,
    )
    monkeypatch.setattr(
        ApplicationCoordinator,
        "garbage_collect_implementation_alignment",
        garbage_collect,
    )
    runner = CliRunner()
    common = [
        "--project-dir",
        str(tmp_path),
        "--work-item-id",
        "WI-ALIGNMENT-001",
        "--version",
        "7",
    ]
    prepared = runner.invoke(main, ["alignment", "prepare", *common])
    inspected = runner.invoke(
        main,
        [
            "alignment",
            "inspect",
            *common,
            "--limit",
            "25",
            "--input",
            json.dumps({"preparation_ref": {"content_sha256": "b" * 64}}),
        ],
    )
    captured = runner.invoke(
        main,
        [
            "alignment",
            "capture-external",
            *common,
            "--authorize-external",
            "--input",
            json.dumps({"preparation_ref": {"content_sha256": "a" * 64}}),
        ],
    )
    written = runner.invoke(
        main,
        [
            "alignment",
            "write-candidate",
            *common,
            "--input",
            json.dumps(
                {
                    "schema_version": (
                        "strixnova.implementation-alignment-candidate-decisions.v1"
                    )
                }
            ),
        ],
    )
    collected = runner.invoke(
        main,
        [
            "alignment",
            "gc",
            "--project-dir",
            str(tmp_path),
            "--dry-run",
        ],
    )

    assert (
        prepared.exit_code
        == inspected.exit_code
        == captured.exit_code
        == written.exit_code
        == collected.exit_code
        == 0
    )
    assert calls == [
        ("prepare", None),
        ("inspect", (None, 25, "b" * 64)),
        ("capture", True),
        (
            "write",
            "strixnova.implementation-alignment-candidate-decisions.v1",
        ),
        ("gc", (False, None)),
    ]
    for result in (prepared, inspected, captured, written, collected):
        assert len(result.output.strip().splitlines()) == 1
        assert json.loads(result.output)["ok"] is True
        result.output.encode("ascii")


def test_alignment_prepare_cli_reads_the_canonical_authority_store(
    tmp_path: Path,
) -> None:
    current, baseline = _complete_project(tmp_path)
    current = _persist_current_authority(tmp_path, current)
    alignment = yaml.safe_load(
        (
            tmp_path
            / baseline["authority_refs"]["implementation_alignment"]["path"]
        ).read_text(encoding="utf-8")
    )
    request = {
        "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
        "alignment_revision_id": "ALIGNREV-ABCDABCDABCDABCD",
        "supersedes_revision_id": alignment["revision"]["revision_id"],
    }
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "alignment",
            "prepare",
            "--project-dir",
            str(tmp_path),
            "--work-item-id",
            current["work_item_id"],
            "--version",
            str(current["version"]),
            "--input",
            json.dumps(request),
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["alignment"]["schema_version"] == (
        "strixnova.implementation-alignment-prepare-result.v1"
    )
    assert payload["alignment"]["preparation_ref"]["artifact_kind"] == (
        "preparations"
    )
    assert payload["alignment"]["draft_candidate_write_available"] is True
    assert "packet_path" not in payload["alignment"]
    assert len(result.output.strip().splitlines()) == 1
    result.output.encode("ascii")

    inspected = runner.invoke(
        main,
        [
            "alignment",
            "inspect",
            "--project-dir",
            str(tmp_path),
            "--work-item-id",
            current["work_item_id"],
            "--version",
            str(current["version"]),
            "--limit",
            "2",
            "--input",
            json.dumps(
                {"preparation_ref": payload["alignment"]["preparation_ref"]}
            ),
        ],
    )

    assert inspected.exit_code == 0, inspected.output
    inspection = json.loads(inspected.output)["alignment"]
    assert inspection["schema_version"] == ALIGNMENT_INSPECTION_RESULT_SCHEMA
    assert inspection["returned_count"] == 2
    assert inspection["next_cursor"].startswith("ALIGNCURSOR-")
    serialized = json.dumps(inspection, sort_keys=True)
    assert "component_refs" not in serialized
    assert "list_segments" not in serialized
    assert "map_pages" not in serialized


def test_alignment_inspection_pages_every_logical_record_without_layout_leak(
    tmp_path: Path,
) -> None:
    current, _baseline = _complete_project(tmp_path)
    module = ImplementationAlignmentPreparation(tmp_path)
    prepared = module.prepare(
        current,
        {
            "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
            "alignment_revision_id": "ALIGNREV-ACDCACDCACDCACDC",
            "supersedes_revision_id": TEST_ALIGNMENT_REVISION_ID,
        },
    )

    cursor = None
    records: list[dict] = []
    while True:
        page = module.inspect(
            current,
            prepared["preparation_ref"],
            cursor=cursor,
            limit=3,
        )
        records.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            assert len(records) == page["item_count"]
            break

    kinds = {record["record_kind"] for record in records}
    assert "preparation_summary" in kinds
    assert "engineering_baseline_context" in kinds
    assert "domain_model_context" in kinds
    assert "architecture_model_context" in kinds
    assert "semantic_decision" in kinds
    serialized = json.dumps(records, sort_keys=True)
    assert "component_refs" not in serialized
    assert "list_segments" not in serialized
    assert "map_pages" not in serialized

    wrong_cursor = module._inspection_cursor("f" * 64, 3)
    with pytest.raises(ImplementationAlignmentPreparationError) as captured:
        module.inspect(
            current,
            prepared["preparation_ref"],
            cursor=wrong_cursor,
            limit=3,
        )
    assert captured.value.code == "alignment_inspection_cursor_invalid"


def test_alignment_gc_requires_exact_preview_and_deletes_only_orphan_components(
    tmp_path: Path,
) -> None:
    store = ImplementationAlignmentArtifactStore(tmp_path)
    preparation_ref = store.store_packet(
        "preparations",
        {
            "schema_version": ALIGNMENT_PREPARATION_PACKET_SCHEMA,
            "binding": {},
            "decision_catalog": [{"decision_ref": "ALIGNDECISION-AAAAAAAAAAAAAAAA"}],
        },
    )
    orphan_ref = store._store_value({"orphan": True})
    preparation_path = tmp_path.joinpath(*Path(preparation_ref["path"]).parts)
    orphan_path = tmp_path.joinpath(*Path(orphan_ref["path"]).parts)
    transactions = (
        tmp_path
        / ".strixnova"
        / "artifacts"
        / "implementation-alignment"
        / "transactions"
    )
    transactions.mkdir(parents=True)
    transaction_marker = transactions / "must-remain.txt"
    transaction_marker.write_text("active", encoding="utf-8")

    module = ImplementationAlignmentPreparation(tmp_path)
    preview = module.garbage_collect_artifacts(apply=False)

    assert preview["schema_version"] == GC_RESULT_SCHEMA
    assert preview["mode"] == "dry_run"
    assert preview["orphan_component_count"] == 1
    assert preview["deleted_component_count"] == 0
    assert preview["transactions_touched"] is False
    assert orphan_path.is_file()
    assert preparation_path.is_file()
    assert transaction_marker.is_file()

    with pytest.raises(ImplementationAlignmentPreparationError) as stale_preview:
        module.garbage_collect_artifacts(
            apply=True,
            expected_orphan_set_sha256="0" * 64,
        )
    assert stale_preview.value.code == "alignment_gc_preview_required"
    assert orphan_path.is_file()

    applied = module.garbage_collect_artifacts(
        apply=True,
        expected_orphan_set_sha256=preview["orphan_set_sha256"],
    )

    assert applied["mode"] == "apply"
    assert applied["deleted_component_count"] == 1
    assert not orphan_path.exists()
    assert preparation_path.is_file()
    assert transaction_marker.is_file()
    assert applied["preparations_deleted"] == 0
    assert applied["captures_deleted"] == 0


def test_alignment_cli_writes_a_schema_valid_nonempty_decision(
    tmp_path: Path,
) -> None:
    current, baseline = _complete_project(tmp_path)
    current = _persist_current_authority(tmp_path, current)
    alignment = yaml.safe_load(
        (
            tmp_path
            / baseline["authority_refs"]["implementation_alignment"]["path"]
        ).read_text(encoding="utf-8")
    )
    runner = CliRunner()
    common = [
        "--project-dir",
        str(tmp_path),
        "--work-item-id",
        current["work_item_id"],
        "--version",
        str(current["version"]),
    ]
    prepared = runner.invoke(
        main,
        [
            "alignment",
            "prepare",
            *common,
            "--input",
            json.dumps(
                {
                    "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
                    "alignment_revision_id": "ALIGNREV-BCDEBCDEBCDEBCDE",
                    "supersedes_revision_id": alignment["revision"][
                        "revision_id"
                    ],
                }
            ),
        ],
    )
    assert prepared.exit_code == 0, prepared.output
    preparation_ref = json.loads(prepared.output)["alignment"]["preparation_ref"]
    module = ImplementationAlignmentPreparation(tmp_path)
    packet = module._load_preparation(preparation_ref)
    assert all(
        "previous" not in item["facts"]
        and "previous_record_ref" in item["facts"]
        for item in packet["decision_catalog"]
    )
    inspected_decisions: list[dict] = []
    cursor = None
    while True:
        inspection = module.inspect(
            current,
            preparation_ref,
            cursor=cursor,
            limit=25,
        )
        inspected_decisions.extend(
            record["value"]
            for record in inspection["items"]
            if record["record_kind"] == "semantic_decision"
        )
        cursor = inspection["next_cursor"]
        if cursor is None:
            break
    catalog_item = next(
        item
        for item in inspected_decisions
        if item["kind"] == "source_record"
        and item["required"] is False
        and isinstance(item["facts"].get("previous"), dict)
    )
    previous = catalog_item["facts"]["previous"]
    payload = {
        "schema_version": ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
        "preparation_ref": preparation_ref,
        "decisions": [
            {
                "decision_ref": catalog_item["decision_ref"],
                "value": {
                    field: deepcopy(previous[field])
                    for field in catalog_item["required_value_fields"]
                },
            }
        ],
        "deviations": [],
        "unresolved_items": [],
    }
    schema = json.loads(
        files("strixnova.resources")
        .joinpath("implementation-alignment-candidate-decisions-v1.schema.json")
        .read_text(encoding="utf-8")
    )
    assert list(Draft202012Validator(schema).iter_errors(payload)) == []

    written = runner.invoke(
        main,
        [
            "alignment",
            "write-candidate",
            *common,
            "--input",
            json.dumps(payload),
        ],
    )

    assert written.exit_code == 0, written.output
    result = json.loads(written.output)["alignment"]
    assert result["candidate_valid"] is True
    assert result["candidate_status"] == "draft"


@pytest.mark.parametrize("ambient_git_override", [False, True])
def test_prepare_and_write_candidate_form_a_valid_recoverable_draft(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ambient_git_override: bool,
) -> None:
    current, baseline = _complete_project(tmp_path)
    alignment_path = tmp_path / baseline["authority_refs"][
        "implementation_alignment"
    ]["path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    request = {
        "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
        "alignment_revision_id": "ALIGNREV-2222222222222222",
        "supersedes_revision_id": TEST_ALIGNMENT_REVISION_ID,
    }
    module = ImplementationAlignmentPreparation(tmp_path)

    prepared = module.prepare(current, request)
    packet = module._load_preparation(prepared["preparation_ref"])
    assert all(
        re.fullmatch(r"ALIGNDECISION-[0-9A-F]{16}", item["decision_ref"])
        for item in packet["decision_catalog"]
    )
    before_version = current["version"]
    before_status = current["status"]
    if ambient_git_override:
        # Observation is already bound to the declared repositories. Ambient
        # Git routing must not replace that binding during candidate writing.
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "unrelated-git-directory"))
    result = module.write_candidate(
        current,
        {
            "schema_version": ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
            "preparation_ref": prepared["preparation_ref"],
            "decisions": [],
            "deviations": [],
            "unresolved_items": [],
        },
    )

    assert result["candidate_valid"] is True
    assert result["complete_alignment"] is True
    assert result["candidate_status"] == "draft"
    assert result["semantic_content_machine_proven"] is False
    assert current["version"] == before_version
    assert current["status"] == before_status
    written = ProjectImplementationAlignment(
        tmp_path,
        baseline["authority_refs"]["implementation_alignment"]["path"],
        domain_model_path=baseline["authority_refs"]["domain_model"]["path"],
        architecture_description_path=baseline["authority_refs"][
            "target_architecture"
        ]["path"],
    ).load()
    assert written["revision"]["revision_id"] == "ALIGNREV-2222222222222222"
    assert written["revision"]["status"] == "draft"
    updated_baseline = yaml.safe_load(
        (tmp_path / "docs/engineering/baseline.yaml").read_text(
            encoding="utf-8"
        )
    )
    alignment_ref = updated_baseline["authority_refs"][
        "implementation_alignment"
    ]
    assert alignment_ref["status"] == {
        "revision_status": "draft",
        "adoption_status": "under_review",
    }

    continued = module.prepare(current)
    continued_result = module.write_candidate(
        current,
        {
            "schema_version": ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
            "preparation_ref": continued["preparation_ref"],
            "decisions": [],
            "deviations": [],
            "unresolved_items": [],
        },
    )
    continued_alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    assert continued_result["candidate_status"] == "draft"
    assert continued_alignment["revision"] == written["revision"]
    assert current["version"] == before_version
    assert current["status"] == before_status


def test_write_candidate_rolls_back_every_document_when_final_review_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    current, baseline = _complete_project(tmp_path)
    alignment_relative = baseline["authority_refs"]["implementation_alignment"][
        "path"
    ]
    alignment = yaml.safe_load(
        (tmp_path / alignment_relative).read_text(encoding="utf-8")
    )
    request = {
        "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
        "alignment_revision_id": "ALIGNREV-3333333333333333",
        "supersedes_revision_id": TEST_ALIGNMENT_REVISION_ID,
    }
    module = ImplementationAlignmentPreparation(tmp_path)
    prepared = module.prepare(current, request)
    paths = [
        alignment_relative,
        *alignment["artifact_paths"].values(),
        "docs/engineering/baseline.yaml",
    ]
    original = {path: (tmp_path / path).read_bytes() for path in paths}

    def fail_final_review(self):
        raise ValueError("forced final review failure")

    monkeypatch.setattr(ProjectImplementationAlignment, "load", fail_final_review)
    with pytest.raises(ImplementationAlignmentPreparationError) as captured:
        module.write_candidate(
            current,
            {
                "schema_version": ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
                "preparation_ref": prepared["preparation_ref"],
                "decisions": [],
                "deviations": [],
                "unresolved_items": [],
            },
        )

    assert captured.value.code == "alignment_candidate_write_failed"
    assert {path: (tmp_path / path).read_bytes() for path in paths} == original


def test_write_candidate_rejects_and_preserves_a_post_prepare_target_edit(
    tmp_path: Path,
) -> None:
    current, _baseline = _complete_project(tmp_path)
    module = ImplementationAlignmentPreparation(tmp_path)
    prepared = module.prepare(
        current,
        {
            "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
            "alignment_revision_id": "ALIGNREV-7777777777777777",
            "supersedes_revision_id": TEST_ALIGNMENT_REVISION_ID,
        },
    )
    baseline_path = tmp_path / "docs/engineering/baseline.yaml"
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    marker = "负责人在 prepare 之后形成的有效复核记录。"
    baseline["review_state"]["reasons"].append(marker)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ImplementationAlignmentPreparationError) as captured:
        module.write_candidate(
            current,
            {
                "schema_version": ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
                "preparation_ref": prepared["preparation_ref"],
                "decisions": [],
                "deviations": [],
                "unresolved_items": [],
            },
        )

    assert captured.value.code == "alignment_preparation_stale"
    after = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    assert marker in after["review_state"]["reasons"]


def test_write_candidate_rolls_back_when_work_item_changes_during_write(
    tmp_path: Path,
) -> None:
    current, baseline = _complete_project(tmp_path)
    module = ImplementationAlignmentPreparation(tmp_path)
    prepared = module.prepare(
        current,
        {
            "schema_version": ALIGNMENT_PREPARATION_REQUEST_SCHEMA,
            "alignment_revision_id": "ALIGNREV-8888888888888888",
            "supersedes_revision_id": TEST_ALIGNMENT_REVISION_ID,
        },
    )
    alignment = yaml.safe_load(
        (
            tmp_path
            / baseline["authority_refs"]["implementation_alignment"]["path"]
        ).read_text(encoding="utf-8")
    )
    paths = [
        baseline["authority_refs"]["implementation_alignment"]["path"],
        *alignment["artifact_paths"].values(),
        "docs/engineering/baseline.yaml",
    ]
    before = {path: (tmp_path / path).read_bytes() for path in paths}
    changed = deepcopy(current)
    changed["version"] += 1

    with pytest.raises(ImplementationAlignmentPreparationError) as captured:
        module.write_candidate(
            current,
            {
                "schema_version": ALIGNMENT_CANDIDATE_DECISIONS_SCHEMA,
                "preparation_ref": prepared["preparation_ref"],
                "decisions": [],
                "deviations": [],
                "unresolved_items": [],
            },
            current_binding_check=lambda: changed,
        )

    assert captured.value.code == "alignment_preparation_stale"
    assert {path: (tmp_path / path).read_bytes() for path in paths} == before


def test_external_capture_requires_both_authorization_and_a_confirmed_plan(
    tmp_path: Path,
) -> None:
    current = _current(tmp_path)
    module = ImplementationAlignmentPreparation(tmp_path)
    preparation_ref = module._store_json(
        "preparations",
            {
                "schema_version": ALIGNMENT_PREPARATION_PACKET_SCHEMA,
                "binding": module._binding(current),
                "target_file_bindings": {},
            },
    )

    with pytest.raises(ImplementationAlignmentPreparationError) as denied:
        module.capture_external(
            current,
            preparation_ref,
            authorize_external=False,
        )
    assert denied.value.code == "external_observation_not_authorized"

    with pytest.raises(ImplementationAlignmentPreparationError) as unplanned:
        module.capture_external(
            current,
            preparation_ref,
            authorize_external=True,
        )
    assert unplanned.value.code == "external_observation_not_planned"


def test_preparation_requires_agent_acknowledgement_for_every_semantic_removal() -> None:
    dependency = {
        "scope_id": "OBSCOPE-1111111111111111",
        "provider_id": "strixnova.python-static.v1",
        "source_node_id": "NODE-1111111111111111",
        "target_node_id": "NODE-2222222222222222",
        "relation_kind": "source_import",
        "resolution_status": "resolved_internal",
        "conditions": [],
        "classification": "allowed_direct",
        "deviation_ids": [],
    }
    documents = {
        "source": {
            "governed_source_scopes": [],
            "records": [
                {
                    "path": "removed.py",
                    "current_status": "aligned",
                    "deviation_ids": [],
                }
            ],
        },
        "dependencies": {"records": [dependency]},
        "responsibilities": {"records": []},
    }

    catalog = ImplementationAlignmentPreparation._required_decisions(
        documents,
        {"nodes": [], "relations": []},
        {},
        {"modules": [], "relationships": [], "constraints": []},
    )

    assert [(item["kind"], item["required"]) for item in catalog] == [
        ("remove_source_record", True),
        ("remove_dependency_record", True),
    ]


def test_prepare_exposes_honest_mixed_language_coverage(
    tmp_path: Path,
) -> None:
    current, baseline = _complete_project(tmp_path)
    files = {
        "rust/Cargo.toml": '[package]\nname = "demo"\nversion = "0.1.0"\n',
        "rust/src/lib.rs": "pub fn evaluate() {}\n",
        "go/go.mod": "module example.com/demo\n\ngo 1.22\n",
        "go/main.go": "package main\nfunc main() {}\n",
        "ts/package.json": '{"name":"demo"}\n',
        "ts/index.ts": "export const value = 1;\n",
        "cs/App.csproj": '<Project Sdk="Microsoft.NET.Sdk" />\n',
        "cs/Program.cs": "namespace Demo;\n",
        "cpp/CMakeLists.txt": "add_executable(app main.cpp)\n",
        "cpp/main.cpp": "int main() { return 0; }\n",
        "unknown/model.xyz": "opaque\n",
    }
    for relative, content in files.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(tmp_path, "add", *files)
    _git(tmp_path, "commit", "-m", "add mixed language sources")
    scopes = [
        _scope(
            "OBSCOPE-1111111111111111",
            "rust",
            "rust",
            ["module_reference", "package_dependency"],
        ),
        _scope(
            "OBSCOPE-2222222222222222",
            "go",
            "go",
            ["package_import", "module_dependency"],
        ),
        _scope(
            "OBSCOPE-3333333333333333",
            "ts",
            "typescript",
            ["source_import", "package_dependency"],
        ),
        _scope(
            "OBSCOPE-4444444444444444",
            "cs",
            "csharp",
            ["namespace_reference", "package_dependency"],
        ),
        _scope(
            "OBSCOPE-5555555555555555",
            "cpp",
            "cpp",
            ["source_include", "build_target_dependency"],
        ),
        _scope(
            "OBSCOPE-6666666666666666",
            "unknown",
            "examplelang",
            ["source_import"],
        ),
    ]
    request = _first_alignment_request(
        tmp_path,
        baseline,
        scopes,
        revision_id="ALIGNREV-4444444444444444",
    )
    module = ImplementationAlignmentPreparation(tmp_path)

    prepared = module.prepare(current, request)
    packet = module._load_preparation(prepared["preparation_ref"])
    statuses = {
        item["language_id"]: item["status"]
        for item in packet["observation"]["coverage"]
    }

    assert statuses == {
        "rust": "complete",
        "go": "complete",
        "typescript": "complete",
        "csharp": "partial",
        "cpp": "partial",
        "examplelang": "unavailable",
    }
    assert prepared["observation_coverage_status"] == "unavailable"
    assert prepared["external_capture_available"] is False
    assert prepared["external_capture_required"] is False
    assert prepared["draft_candidate_write_available"] is True
    assert prepared["required_decision_count"] > 0


def test_planned_external_provider_can_complete_an_unknown_language_scope(
    tmp_path: Path,
) -> None:
    current, baseline = _complete_project(tmp_path)
    source = tmp_path / "kotlin/Main.kt"
    source.parent.mkdir(parents=True)
    source.write_text("fun main() = Unit\n", encoding="utf-8")
    provider = tmp_path / "provider.py"
    provider.write_text(
        "import hashlib, json, sys\n"
        "from pathlib import Path\n"
        "request = json.load(sys.stdin)\n"
        "paths = request['expected_source_paths']\n"
        "result = {\n"
        "  'schema_version': request['requested_output_schema_version'],\n"
        "  'scope_id': request['scope']['scope_id'],\n"
        "  'language_id': request['language_id'],\n"
        "  'provider_id': request['provider_id'],\n"
        "  'provider_version': request['provider_version'],\n"
        "  'status': 'complete',\n"
        "  'supported_relation_kinds': ['source_import'],\n"
        "  'nodes': [{'node_key': p, 'node_kind': 'source_file', 'path': p, "
        "'external_name': None, 'display_name': p} for p in paths],\n"
        "  'relations': [],\n"
        "  'observed_paths': {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() "
        "for p in paths},\n"
        "  'limitations': [], 'gaps': []}\n"
        "json.dump(result, sys.stdout, separators=(',', ':'))\n",
        encoding="utf-8",
    )
    _git(tmp_path, "add", "kotlin/Main.kt", "provider.py")
    _git(tmp_path, "commit", "-m", "add Kotlin source and provider")
    scopes = [
        _scope(
            "OBSCOPE-BBBBBBBBBBBBBBBB",
            "kotlin",
            "kotlin",
            ["source_import"],
        )
    ]
    request = _first_alignment_request(
        tmp_path,
        baseline,
        scopes,
        revision_id="ALIGNREV-5555555555555555",
    )
    plan = current["data"]["engineering"]["plan"]
    plan["external_observation_provider_plans"] = [
        {
            "provider_plan_id": "OBSPROVPLAN-1111111111111111",
            "scope_id": "OBSCOPE-BBBBBBBBBBBBBBBB",
            "language_id": "kotlin",
            "provider_id": "example.kotlin-provider.v1",
            "provider_version": "1.0.0",
            "command": [sys.executable, str(provider)],
            "materials": [
                {
                    "role": "executable",
                    "path": str(Path(sys.executable).resolve()),
                    "sha256": hashlib.sha256(
                        Path(sys.executable).resolve().read_bytes()
                    ).hexdigest(),
                    "command_argument_index": 0,
                },
                {
                    "role": "entry_script",
                    "path": str(provider.resolve()),
                    "sha256": hashlib.sha256(
                        provider.resolve().read_bytes()
                    ).hexdigest(),
                    "command_argument_index": 1,
                },
            ],
            "source_globs": ["*.kt", "**/*.kt"],
            "process_policy": {
                "policy_id": "PROCESSPOLICY-1111111111111111",
                "purpose": "Test exact Kotlin implementation observation.",
                "forbidden_program_names": [],
            },
            "limits": {
                "timeout_seconds": 5,
                "cleanup_timeout_seconds": 1,
                "max_input_bytes": 1048576,
                "max_output_bytes": 1048576,
            },
        }
    ]
    module = ImplementationAlignmentPreparation(tmp_path)

    prepared = module.prepare(current, request)
    captured = module.capture_external(
        current,
        prepared["preparation_ref"],
        authorize_external=True,
    )
    packet = module._load_preparation(captured["preparation_ref"])

    assert prepared["external_capture_available"] is True
    assert prepared["external_capture_required"] is True
    assert captured["observation_coverage_status"] == "complete"
    assert packet["observation"]["coverage"][0]["execution_mode"] == (
        "authorized_tool"
    )
    assert packet["observation"]["provider_receipts"][0]["policy_id"] == (
        "PROCESSPOLICY-1111111111111111"
    )
    assert len(
        packet["observation"]["provider_receipts"][0]["material_receipts"]
    ) == 2

    marker = tmp_path / "changed-provider-ran"
    provider.write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )
    rejected = module.capture_external(
        current,
        prepared["preparation_ref"],
        authorize_external=True,
    )
    rejected_packet = module._load_preparation(rejected["preparation_ref"])
    rejected_coverage = rejected_packet["observation"]["coverage"][0]
    assert rejected_coverage["execution_mode"] == "not_run"
    assert rejected_coverage["gaps"][0]["code"] == "provider_material_changed"
    assert not marker.exists()
