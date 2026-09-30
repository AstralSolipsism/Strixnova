import hashlib
from pathlib import Path

import pytest
import yaml

from scripts.check_guided_formation_acceptance import check_catalog, GuidedFormationAcceptanceError
from scripts.skill_bundle_manifest import directory_manifest


def fixture_catalog(root: Path):
    (root / "skill").mkdir()
    (root / "skill/SKILL.md").write_bytes(b"instructions\n")
    paths = {"runtime": "app.py", "harness": "driver.py", "fixture": "fixture.json", "evidence": "report.md"}
    dependencies = {}
    for group, path in paths.items():
        content = b"# Result\n" if group == "evidence" else group.encode()
        (root / path).write_bytes(content)
        dependencies[group] = {"status": "recorded", "reason": "Executed declared input",
                               "files": [{"path": path, "sha256": hashlib.sha256(content).hexdigest()}]}
    catalog = {"schema_version": "strixnova.guided-formation-acceptance-catalog.v1",
               "skill_source_root": "skill", "semantic_content_machine_proven": False,
               "cases": [{"case_id": "GF-FIXTURE-DEPENDENCIES", "title": "contract",
                          "verification_kind": "contract_structure", "expected_behavior": "recorded behavior",
                          "must_avoid": "invented result", "dependency_paths": ["SKILL.md"],
                          "execution_dependencies": dependencies,
                          "evidence": {"result": "passed", "path": "report.md", "locator": "# Result",
                                       "dependency_manifest_sha256": directory_manifest(root / "skill")["sha256"],
                                       "full_skill_bundle_manifest_sha256": None, "binding_basis": "Fixed capture"}}]}
    save(root, catalog)
    return catalog, paths


def save(root, value):
    (root / "catalog.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")


def check(root):
    return check_catalog(root, catalog_path="catalog.yaml")


@pytest.mark.parametrize("group", ["runtime", "harness", "fixture", "evidence"])
def test_non_skill_dependency_changes_invalidate_only_the_recorded_scope(tmp_path, group):
    _, paths = fixture_catalog(tmp_path)
    assert check(tmp_path)["acceptance_complete"]
    (tmp_path / "unrelated.md").write_bytes(b"unrelated")
    assert check(tmp_path)["acceptance_complete"]
    with (tmp_path / paths[group]).open("ab") as stream:
        stream.write(b"changed")
    result = check(tmp_path)
    assert not result["acceptance_complete"]
    assert result["stale_evidence_count"] == 1
    assert result["cases"][0]["skill_dependency_state"] == "current"
    assert result["cases"][0]["execution_dependency_states"][group]["state"] == "stale"


def test_missing_execution_binding_is_not_promoted_to_full_current_evidence(tmp_path):
    catalog, _ = fixture_catalog(tmp_path)
    catalog["schema_version"] = "strixnova.guided-formation-acceptance-catalog.v1"
    catalog["cases"][0]["execution_dependencies"] = None
    save(tmp_path, catalog)
    result = check(tmp_path)
    assert result["skill_current_count"] == 1
    assert result["unassessed_evidence_count"] == 1
    assert result["acceptance_complete"] is False


def test_unrecorded_and_explicit_inapplicability_have_distinct_currentness(tmp_path):
    catalog, _ = fixture_catalog(tmp_path)
    dependencies = catalog["cases"][0]["execution_dependencies"]
    dependencies["runtime"] = {"status": "unrecorded", "reason": "Receipt unavailable", "files": []}
    save(tmp_path, catalog)
    assert check(tmp_path)["unassessed_evidence_count"] == 1
    dependencies["runtime"] = {"status": "not_applicable", "reason": "This fixture only validates a source document", "files": []}
    save(tmp_path, catalog)
    assert check(tmp_path)["acceptance_complete"]


@pytest.mark.parametrize("mutation", ["missing", "escape", "duplicate", "no_report", "bad_hash"])
def test_dependency_declarations_cannot_hide_missing_or_invalid_material(tmp_path, mutation):
    catalog, paths = fixture_catalog(tmp_path)
    group = catalog["cases"][0]["execution_dependencies"]["runtime"]
    if mutation == "missing":
        (tmp_path / paths["runtime"]).unlink()
        assert check(tmp_path)["stale_evidence_count"] == 1
        return
    if mutation == "escape":
        group["files"][0]["path"] = "../outside.py"
    elif mutation == "duplicate":
        group["files"].append(dict(group["files"][0]))
    elif mutation == "no_report":
        catalog["cases"][0]["execution_dependencies"]["evidence"]["status"] = "not_applicable"
        catalog["cases"][0]["execution_dependencies"]["evidence"]["files"] = []
    else:
        group["files"][0]["sha256"] = "not-a-digest"
    save(tmp_path, catalog)
    with pytest.raises(GuidedFormationAcceptanceError):
        check(tmp_path)
