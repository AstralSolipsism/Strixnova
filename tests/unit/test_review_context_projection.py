from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
import shutil
import sys

import pytest

from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.project_architecture_description import ProjectArchitectureDescription
from strixnova.project_implementation_alignment import ProjectImplementationAlignment
from strixnova.review_context_projection import ReviewContextError, ReviewContextProjection
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.project_baseline import TEST_MODULE_ID, TEST_READER_MODULE_ID
from tests.support.project_context import FRONTEND, BACKEND, PROJECT, git, repository, tree_bytes
from tests.support.review_context import read_yaml, request, review_project, write_yaml


def test_changes_collect_rules_and_stale_sources_without_creating_state(tmp_path, monkeypatch):
    basis = review_project(tmp_path)
    (tmp_path / "src.py").write_bytes(b"VALUE = 2\n")
    (tmp_path / "new.py").write_bytes(b"NEW = True\n")
    before = tree_bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("review query must not construct state or run observations")

    monkeypatch.setattr(WorkflowAuthority, "__init__", forbidden)
    monkeypatch.setattr(ProjectImplementationAlignment, "drift", forbidden)
    result = ReviewContextProjection(tmp_path).read(request(basis))
    assert result["selected_module_ids"] == [TEST_MODULE_ID]
    assert result["architecture"]["default_relationship_policy"] == "forbidden"
    assert result["architecture"]["constraints"]
    assert result["domain_facts"]["facts"]
    assert result["implementation"]["target_responsibilities"]
    by_path = {item["path"]: item for item in result["files"]}
    assert by_path["src.py"]["text"] == "VALUE = 2\n"
    assert by_path["src.py"]["recorded_observation_current"] is False
    assert by_path["new.py"]["text"] == "NEW = True\n"
    assert {item["code"] for item in result["gaps"]} >= {"source_ownership_unknown", "recorded_observation_stale"}
    assert result["sources"]["target_architecture"]["observed_commit"] == basis
    assert result["product_guardrails"]["non_goals"]
    assert result["review_performed"] is result["writes_performed"] is False
    assert tree_bytes(tmp_path) == before
    assert not (tmp_path / ".strixnova").exists()


def test_module_query_does_not_require_changes_and_has_stable_identity(tmp_path):
    basis = review_project(tmp_path)
    value = request(basis, mode="modules", ref=basis)
    first = ReviewContextProjection(tmp_path).read(value)
    second = ReviewContextProjection(tmp_path).read(value)
    assert first == second
    assert first["changes"] == []
    assert first["files"][0]["path"] == "src.py"
    assert first["files"][0]["ref"] == basis
    assert first["status"] == "available"
    assert first["architecture"]["referenced_module_ids"] == [TEST_READER_MODULE_ID]


def test_review_policy_rules_use_the_requested_basis_and_do_not_mutate_sources(tmp_path):
    from tests.support.review_context import project_with_extended_policy
    basis, rule = project_with_extended_policy(tmp_path)
    policy = read_yaml(tmp_path, "docs/engineering/policy.yaml")
    policy["rule_extensions"][0]["strixnova_interpretation"] = "Unconfirmed replacement"
    write_yaml(tmp_path, "docs/engineering/policy.yaml", policy)
    before = tree_bytes(tmp_path)
    result = ReviewContextProjection(tmp_path).read(request(basis, mode="modules", ref=basis))
    material = result["engineering_policy"]
    assert next(row for row in material["rules"] if row["rule_id"] == rule["rule_id"]) == rule
    assert any(row["source_id"] == "SOURCE-LAYOUT" for row in material["rule_sources"])
    assert material["rule_tailoring"] == policy["rule_tailoring"]
    assert tree_bytes(tmp_path) == before


def test_changes_leave_copied_repository_index_bytes_unchanged(tmp_path):
    original = tmp_path / "original"
    original.mkdir()
    basis = review_project(original)
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)
    (copied / "new.py").write_bytes(b"NEW = True\n")
    before = tree_bytes(copied)

    result = ReviewContextProjection(copied).read(request(basis))

    assert [item["path"] for item in result["changes"]] == ["new.py"]
    assert tree_bytes(copied) == before


@pytest.mark.parametrize("change", ["content", "mode", "rename", "delete", "empty_add", "binary"])
def test_copied_repository_keeps_real_changes_without_refreshing_index(tmp_path, change):
    original = tmp_path / "original"
    original.mkdir()
    basis = review_project(original)
    copied = tmp_path / "copied"
    shutil.copytree(original, copied)
    expected = "src.py"
    if change == "content":
        (copied / "src.py").write_bytes(b"VALUE = 2\n")
    elif change == "mode":
        git(copied, "config", "core.filemode", "false")
        git(copied, "update-index", "--chmod=+x", "src.py")
    elif change == "rename":
        git(copied, "mv", "src.py", "renamed.py")
        expected = "renamed.py"
    elif change == "delete":
        (copied / "src.py").unlink()
        expected = None
    elif change == "empty_add":
        (copied / "empty.py").write_bytes(b"")
        git(copied, "add", "empty.py")
        expected = "empty.py"
    else:
        (copied / "src.py").write_bytes(b"\x00\x01binary\xff")
    before = tree_bytes(copied)

    result = ReviewContextProjection(copied).read(request(basis))

    assert [item["path"] for item in result["changes"]] == [expected]
    if change == "rename":
        assert result["changes"][0]["old_path"] == "src.py"
    assert tree_bytes(copied) == before


def test_missing_policy_keeps_other_usable_materials(tmp_path):
    review_project(tmp_path)
    (tmp_path / "docs/engineering/policy.yaml").unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "-m", "missing policy fixture")
    basis = git(tmp_path, "rev-parse", "HEAD")
    result = ReviewContextProjection(tmp_path).read(request(basis, mode="modules"))
    assert result["architecture"]["modules"]
    assert result["domain_facts"]["facts"]
    assert result["engineering_policy"] is None
    assert any(item.get("authority_kind") == "engineering_policy" for item in result["gaps"])
    assert result["status"] == "partial"


def test_missing_baseline_still_supplies_explicit_changed_code(tmp_path):
    basis = review_project(tmp_path)
    (tmp_path / "docs/engineering/baseline.yaml").unlink()
    git(tmp_path, "add", "-u")
    git(tmp_path, "commit", "-m", "no baseline fixture")
    missing_basis = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "src.py").write_bytes(b"VALUE = 9\n")
    value = request(missing_basis)
    value["repositories"][0]["base_ref"] = basis
    result = ReviewContextProjection(tmp_path).read(value)
    assert result["architecture"] is None
    assert any(item["path"] == "src.py" and item["text"] == "VALUE = 9\n" for item in result["files"])
    assert any(item["code"] == "baseline_missing" for item in result["gaps"])


def test_renames_keep_original_ownership_and_both_paths(tmp_path):
    basis = review_project(tmp_path)
    git(tmp_path, "mv", "src.py", "renamed.py")
    result = ReviewContextProjection(tmp_path).read(request(basis))
    assert result["changes"][0]["status"].startswith("R")
    assert result["changes"][0]["old_path"] == "src.py"
    assert result["changes"][0]["path"] == "renamed.py"
    assert result["selected_module_ids"] == [TEST_MODULE_ID]
    assert {item["path"]: item["state"] for item in result["files"]} == {"src.py": "absent", "renamed.py": "file"}


def test_module_selection_includes_mediated_relationship_and_endpoint_definitions(tmp_path):
    review_project(tmp_path)
    root = read_yaml(tmp_path, "docs/architecture/model.yaml")
    paths = root["artifact_paths"]
    modules = read_yaml(tmp_path, paths["modules"])
    third = deepcopy(modules["modules"][1])
    third["module_id"] = "MODULE-3333333333333333"
    third["public_interface"]["interface_id"] = "INTERFACE-3333333333333333"
    modules["modules"].append(third)
    write_yaml(tmp_path, paths["modules"], modules)
    relationships = read_yaml(tmp_path, paths["relationships"])
    original = relationships["relationships"][0]
    relationships["relationships"].extend([
        {**original, "relationship_id": "RELATION-2222222222222222", "from_module_id": TEST_READER_MODULE_ID, "to_module_id": third["module_id"]},
        {**original, "relationship_id": "RELATION-3333333333333333", "to_module_id": third["module_id"], "mode": "through_module", "mediator_module_id": TEST_READER_MODULE_ID},
    ])
    write_yaml(tmp_path, paths["relationships"], relationships)
    stages = read_yaml(tmp_path, paths["implementation_stages"])
    stages["stages"][0]["module_ids"].append(third["module_id"])
    write_yaml(tmp_path, paths["implementation_stages"], stages)
    selected = ProjectArchitectureDescription(tmp_path, "docs/architecture/model.yaml").select_modules([TEST_READER_MODULE_ID])
    assert any(item["mode"] == "through_module" for item in selected["relationships"])
    assert len(selected["modules"]) == 3
    assert selected["default_relationship_policy"] == "forbidden"


def test_basis_identity_mismatch_is_not_downgraded_to_partial_success(tmp_path):
    review_project(tmp_path)
    baseline = read_yaml(tmp_path, "docs/engineering/baseline.yaml")
    baseline["authority_refs"]["target_architecture"]["architecture_id"] = "ARCH-9999999999999999"
    write_yaml(tmp_path, "docs/engineering/baseline.yaml", baseline)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "wrong identity fixture")
    basis = git(tmp_path, "rev-parse", "HEAD")
    with pytest.raises(ReviewContextError, match="精确修订"):
        ReviewContextProjection(tmp_path).read(request(basis, mode="modules"))


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(mode="anything"),
    lambda value: value["repositories"].append(deepcopy(value["repositories"][0])),
    lambda value: value["repositories"][0].update(ref="no-such-local-commit"),
])
def test_invalid_scopes_are_rejected(tmp_path, mutation):
    basis = review_project(tmp_path)
    value = request(basis)
    mutation(value)
    with pytest.raises(ReviewContextError):
        ReviewContextProjection(tmp_path).read(value)
    assert not (tmp_path / ".strixnova").exists()


def test_content_budget_is_visible_and_keeps_guardrails(tmp_path):
    basis = review_project(tmp_path)
    value = request(basis, mode="modules")
    value["max_content_bytes"] = 1
    result = ReviewContextProjection(tmp_path).read(value)
    assert result["files"][0]["next_offset"] == 1
    assert base64.b64decode(result["files"][0]["content_base64"]) == b"V"
    assert result["product_guardrails"]["constraints"]
    assert result["architecture"]["constraints"]
    assert result["status"] == "partial"


def test_worktree_changes_during_collection_are_rejected(tmp_path, monkeypatch):
    basis = review_project(tmp_path)
    original = GitProjectReader.content_window

    def changed(reader, path, **kwargs):
        result = original(reader, path, **kwargs)
        (tmp_path / "src.py").write_text("VALUE = 77\n", encoding="utf-8")
        return result

    monkeypatch.setattr(GitProjectReader, "content_window", changed)
    with pytest.raises(ReviewContextError) as caught:
        ReviewContextProjection(tmp_path).read(request(basis, mode="modules"))
    assert caught.value.code == "review_content_changed"


def test_cross_repository_same_paths_are_not_assigned_another_repository_owner(tmp_path):
    front, back = tmp_path / "front", tmp_path / "back"
    review_project(front)
    back_base = repository(back)
    (back / "src.py").write_bytes(b"BACK = 1\n")
    configuration = read_yaml(front, "strixnova-project.yaml")
    configuration["repositories"].append({"repository_id": BACKEND, "owner_project_id": PROJECT, "purpose": "backend"})
    write_yaml(front, "strixnova-project.yaml", configuration)
    git(front, "add", ".")
    git(front, "commit", "-m", "two repository declaration")
    basis = git(front, "rev-parse", "HEAD")
    value = request(basis)
    value["bindings"] = {"schema_version": "strixnova.project-bindings.v1", "project_id": PROJECT, "configuration": {"repository_id": FRONTEND, "path": "strixnova-project.yaml"}, "management_root": "unused", "repositories": [{"repository_id": FRONTEND, "path": "front"}, {"repository_id": BACKEND, "path": "back"}]}
    value["repositories"].append({"repository_id": BACKEND, "ref": None, "base_ref": back_base})
    result = ReviewContextProjection(tmp_path).read(value)
    back_file = next(item for item in result["files"] if item["repository_id"] == BACKEND and item["path"] == "src.py")
    assert "recorded_module_id" not in back_file
    assert back_file["text"] == "BACK = 1\n"
    assert any(item["code"] == "source_ownership_unknown" and item["repository_id"] == BACKEND for item in result["gaps"])


def test_worktree_diff_rejects_clean_filter_before_it_can_run(tmp_path):
    basis = review_project(tmp_path)
    script = tmp_path / "filter.py"
    script.write_text("import pathlib, sys\npathlib.Path('FILTER_EXECUTED').write_text('unexpected')\nsys.stdout.write(sys.stdin.read())\n", encoding="utf-8")
    git(tmp_path, "config", "filter.review.clean", f'"{Path(sys.executable).as_posix()}" "{script.as_posix()}"')
    (tmp_path / ".gitattributes").write_bytes(b"src.py filter=review\n")
    (tmp_path / "src.py").write_bytes(b"VALUE = 200\n")
    with pytest.raises(ReviewContextError) as caught:
        ReviewContextProjection(tmp_path).read(request(basis))
    assert caught.value.code == "git_conversion_unsafe"
    assert not (tmp_path / "FILTER_EXECUTED").exists()


def test_global_architecture_constraints_are_always_present(tmp_path):
    review_project(tmp_path)
    model = read_yaml(tmp_path, "docs/architecture/model.yaml")
    path = model["artifact_paths"]["constraints"]
    constraints = read_yaml(tmp_path, path)
    constraints["constraints"][0]["applies_to_module_ids"] = []
    write_yaml(tmp_path, path, constraints)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "global constraint")
    basis = git(tmp_path, "rev-parse", "HEAD")
    result = ReviewContextProjection(tmp_path).read(request(basis, mode="modules"))
    assert result["architecture"]["constraints"][0]["constraint_id"] == "CONSTRAINT-1111111111111111"


def test_domain_source_changes_route_through_canonical_authority_paths(tmp_path):
    basis = review_project(tmp_path)
    source_path = "docs/domain/sources/core.yaml"
    source = read_yaml(tmp_path, source_path)
    source["facts"][0]["content"]["responsibility"] = "A changed responsibility requiring review."
    write_yaml(tmp_path, source_path, source)
    result = ReviewContextProjection(tmp_path).read(request(basis))
    assert source_path in {item["path"] for item in result["sources"]["domain_model"]["files"]}
    assert "docs/domain/collections/core.yaml" in {item["path"] for item in result["sources"]["domain_model"]["files"]}
    assert result["selected_module_ids"] == [TEST_MODULE_ID]
    assert result["domain_facts"]["facts"]
    assert any(item["reason"] == "changed_authority_material" for item in result["selection_reasons"])
    assert not any(item["code"] == "source_ownership_unknown" and item.get("path") == source_path for item in result["gaps"])


def test_module_query_reports_unassigned_files_in_recorded_governed_scope(tmp_path):
    review_project(tmp_path)
    model = read_yaml(tmp_path, "docs/engineering/alignment.yaml")
    model["observation_scopes"][0]["root"] = "."
    ownership = read_yaml(tmp_path, model["artifact_paths"]["source_ownership"])
    ownership["governed_source_scopes"][0]["root"] = "."
    ownership["governed_source_scopes"][0]["included_path_patterns"] = ["*.py"]
    write_yaml(tmp_path, "docs/engineering/alignment.yaml", model)
    write_yaml(tmp_path, model["artifact_paths"]["source_ownership"], ownership)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "recorded source scope")
    basis = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "new.py").write_bytes(b"UNASSIGNED = True\n")
    result = ReviewContextProjection(tmp_path).read(request(basis, mode="modules"))
    assert any(item["path"] == "new.py" for item in result["files"])
    assert any(item["code"] == "source_ownership_unknown" and item.get("path") == "new.py" for item in result["gaps"])
    assert result["status"] == "partial"


def test_unbound_baseline_repository_does_not_hide_available_code(tmp_path):
    review_project(tmp_path)
    configuration = read_yaml(tmp_path, "strixnova-project.yaml")
    configuration["repositories"].append({"repository_id": BACKEND, "owner_project_id": PROJECT, "purpose": "governance"})
    configuration["engineering_baseline"]["repository_id"] = BACKEND
    write_yaml(tmp_path, "strixnova-project.yaml", configuration)
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "baseline in another repository")
    basis = git(tmp_path, "rev-parse", "HEAD")
    (tmp_path / "src.py").write_bytes(b"VALUE = 8\n")
    result = ReviewContextProjection(tmp_path).read(request(basis))
    assert result["files"][0]["text"] == "VALUE = 8\n"
    assert any(item["code"] == "baseline_repository_unavailable" for item in result["gaps"])
    assert result["status"] == "partial"


@pytest.mark.parametrize("code", ["repository_symlink_forbidden", "repository_content_crosses_worktree"])
def test_unsafe_code_path_is_rejected_not_hidden_as_partial_gap(tmp_path, monkeypatch, code):
    basis = review_project(tmp_path)

    def unsafe(*args, **kwargs):
        raise GitProjectReaderError("unsafe target path", code=code)

    monkeypatch.setattr(GitProjectReader, "path_scope_exists", unsafe)
    with pytest.raises(ReviewContextError) as caught:
        ReviewContextProjection(tmp_path).read(request(basis, mode="modules"))
    assert caught.value.code == code
