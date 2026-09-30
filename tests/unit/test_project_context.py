from __future__ import annotations

import base64
from copy import deepcopy
from pathlib import Path
import os
import subprocess

from jsonschema import Draft202012Validator
import pytest

from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.project_context import ProjectContextError, ProjectContextResolver, project_context_contract
from tests.support.project_context import (
    BACKEND, EXTERNAL, FRONTEND, OTHER_PROJECT, PROJECT,
    git, inspect_request, read_request, repository, tree_bytes,
)


def test_non_git_entry_resolves_separate_repositories_without_project_writes(tmp_path: Path) -> None:
    entry = tmp_path / "entry"
    entry.mkdir()
    repository(tmp_path / "frontend", b"front\n")
    repository(tmp_path / "backend", b"back\n")
    value = inspect_request({FRONTEND: "../frontend", BACKEND: "../backend"})
    original_input = deepcopy(value)
    before = tree_bytes(tmp_path)

    result = ProjectContextResolver(entry).resolve(value)

    assert result.project_id == PROJECT
    assert result.management_root == entry / "management-not-created"
    assert {item.repository_id: item.availability for item in result.repositories} == {
        FRONTEND: "available", BACKEND: "available",
    }
    assert result.view()["declaration_adopted"] is False
    assert result.view()["writes_performed"] is False
    assert value == original_input
    assert tree_bytes(tmp_path) == before
    assert not (entry / ".git").exists()
    assert not result.management_root.exists()
    assert not (entry / ".strixnova").exists()


def test_same_path_in_two_repositories_retains_identity_and_exact_content(tmp_path: Path) -> None:
    first = repository(tmp_path / "frontend", b"first\n")
    second = repository(tmp_path / "backend", b"second\n")
    resolver = ProjectContextResolver(tmp_path)
    bindings = {FRONTEND: "frontend", BACKEND: "backend"}

    front = resolver.read(read_request(bindings, FRONTEND, ref=first))
    back = resolver.read(read_request(bindings, BACKEND, ref=second))

    assert base64.b64decode(front["content_base64"]) == b"first\n"
    assert base64.b64decode(back["content_base64"]) == b"second\n"
    assert front["repository_id"] == FRONTEND
    assert back["repository_id"] == BACKEND
    assert front["sha256"] != back["sha256"]
    assert front["observed_commit"] == first
    assert back["observed_commit"] == second


def test_binding_digest_includes_the_resolved_base_of_relative_paths(tmp_path: Path) -> None:
    repository(tmp_path / "first" / "repo")
    repository(tmp_path / "second" / "repo")
    request = inspect_request({FRONTEND: "repo"})
    first = ProjectContextResolver(tmp_path / "first").resolve(request)
    second = ProjectContextResolver(tmp_path / "second").resolve(request)
    assert first.declaration_sha256 == second.declaration_sha256
    assert first.bindings_sha256 != second.bindings_sha256
    assert first.repository(FRONTEND).checkout_path != second.repository(FRONTEND).checkout_path


def test_missing_or_unbound_other_member_does_not_block_available_read(tmp_path: Path) -> None:
    repository(tmp_path / "frontend")
    resolver = ProjectContextResolver(tmp_path)
    request = inspect_request({FRONTEND: "frontend"})
    context = resolver.resolve(request)
    assert context.repositories[1].availability == "not_bound"
    assert base64.b64decode(resolver.read(read_request({FRONTEND: "frontend"}))["content_base64"]) == b"sample\n"
    with pytest.raises(ProjectContextError) as caught:
        context.repository(BACKEND)
    assert caught.value.code == "repository_not_bound"

    request["bindings"]["repositories"].append({"repository_id": BACKEND, "path": "absent"})
    missing = resolver.resolve(request)
    assert missing.repositories[1].availability == "missing"
    with pytest.raises(ProjectContextError) as caught:
        missing.repository(BACKEND)
    assert caught.value.code == "repository_checkout_missing"


def test_repository_subdirectory_is_not_accepted_as_an_independent_root(tmp_path: Path) -> None:
    root = tmp_path / "frontend"
    repository(root)
    (root / "sub").mkdir()
    result = ProjectContextResolver(tmp_path).resolve(inspect_request({FRONTEND: "frontend/sub"}))
    assert result.repositories[0].availability == "invalid"
    assert result.repositories[0].issue_code == "git_repository_mismatch"


def test_regular_file_binding_is_invalid_without_blocking_another_member(tmp_path: Path) -> None:
    repository(tmp_path / "repo")
    (tmp_path / "plain-file").write_text("not a repository", encoding="utf-8")
    context = ProjectContextResolver(tmp_path).resolve(
        inspect_request({FRONTEND: "repo", BACKEND: "plain-file"})
    )
    assert context.repository(FRONTEND).availability == "available"
    assert context.repositories[1].issue_code == "repository_binding_not_directory"


def test_external_dependency_can_be_read_but_is_not_a_modification_scope(tmp_path: Path) -> None:
    repository(tmp_path / "shared", b"contract\n")
    request = inspect_request({})
    request["declaration"]["external_repositories"] = [
        {"repository_id": EXTERNAL, "owner_project_id": OTHER_PROJECT, "purpose": "共享认证"}
    ]
    request["bindings"]["repositories"] = [{"repository_id": EXTERNAL, "path": "shared"}]
    resolver = ProjectContextResolver(tmp_path)
    context = resolver.resolve(request)
    assert context.repository(EXTERNAL).membership == "external_dependency"
    with pytest.raises(ProjectContextError) as caught:
        context.repository(EXTERNAL, for_modification=True)
    assert caught.value.code == "repository_not_owned_by_project"
    request["schema_version"] = "strixnova.project-context-read.v1"
    request["reference"] = {"repository_id": EXTERNAL, "path": "same.txt"}
    assert base64.b64decode(resolver.read(request)["content_base64"]) == b"contract\n"


@pytest.mark.parametrize("change,code", [
    (lambda value: value.update(extra=True), "project_context_input_invalid"),
    (lambda value: value["bindings"].update(project_id=OTHER_PROJECT), "project_binding_identity_mismatch"),
    (lambda value: value["declaration"]["repositories"][0].update(owner_project_id=OTHER_PROJECT), "repository_owner_mismatch"),
    (lambda value: value["declaration"]["repositories"].append(deepcopy(value["declaration"]["repositories"][0])), "project_repository_duplicate"),
    (lambda value: value["bindings"]["repositories"].append({"repository_id": EXTERNAL, "path": "missing"}), "project_binding_repository_unknown"),
    (lambda value: value["bindings"]["repositories"].extend([{"repository_id": FRONTEND, "path": "a"}, {"repository_id": FRONTEND, "path": "b"}]), "project_binding_duplicate"),
])
def test_invalid_declarations_are_rejected_without_creating_state(tmp_path: Path, change, code: str) -> None:
    request = inspect_request({})
    change(request)
    with pytest.raises(ProjectContextError) as caught:
        ProjectContextResolver(tmp_path).resolve(request)
    assert caught.value.code == code
    assert list(tmp_path.iterdir()) == []


def test_two_identities_bound_to_same_git_repository_are_both_conflicts(tmp_path: Path) -> None:
    repository(tmp_path / "repo")
    context = ProjectContextResolver(tmp_path).resolve(inspect_request({FRONTEND: "repo", BACKEND: "repo"}))
    assert [item.availability for item in context.repositories] == ["conflict", "conflict"]
    for identifier in (FRONTEND, BACKEND):
        with pytest.raises(ProjectContextError) as caught:
            context.repository(identifier)
        assert caught.value.code == "repository_binding_conflict"


def test_linked_worktree_keeps_repository_identity_and_detects_alias_collision(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repository(root)
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "-b", "feature", str(linked))
    resolver = ProjectContextResolver(tmp_path)
    context = resolver.resolve(inspect_request({FRONTEND: "linked"}))
    selected = context.repository(FRONTEND)
    assert selected.scope.repository_id == FRONTEND
    assert selected.scope.git_common_dir == (root / ".git").resolve()
    result = resolver.read(read_request({FRONTEND: "linked"}, ref="feature"))
    assert base64.b64decode(result["content_base64"]) == b"sample\n"
    collision = resolver.resolve(inspect_request({FRONTEND: "repo", BACKEND: "linked"}))
    assert all(item.availability == "conflict" for item in collision.repositories)


def test_unborn_repository_is_a_valid_binding_without_inventing_a_commit(tmp_path: Path) -> None:
    repository(tmp_path / "repo", commit=False)
    resolver = ProjectContextResolver(tmp_path)
    context = resolver.resolve(inspect_request({FRONTEND: "repo"}))
    assert context.repository(FRONTEND).availability == "available"
    result = resolver.read(read_request({FRONTEND: "repo"}))
    assert result["scope"] == "working_tree"
    assert result["observed_commit"] is None
    with pytest.raises(GitProjectReaderError) as caught:
        resolver.read(read_request({FRONTEND: "repo"}, ref="HEAD"))
    assert caught.value.code == "git_ref_not_found"


@pytest.mark.parametrize("path", ["../same.txt", "/same.txt", ".git/config", ".STRIXNOVA/data", "C:/data.txt", "sub\\same.txt", "."])
def test_repository_paths_cannot_escape_the_selected_scope(tmp_path: Path, path: str) -> None:
    repository(tmp_path / "repo")
    request = read_request({FRONTEND: "repo"})
    request["reference"]["path"] = path
    with pytest.raises(GitProjectReaderError) as caught:
        ProjectContextResolver(tmp_path).read(request)
    assert caught.value.code == "repository_path_invalid"


def test_content_windows_preserve_utf8_bytes_and_detect_worktree_changes(tmp_path: Path) -> None:
    data = "前后端内容\n".encode("utf-8")
    root = tmp_path / "repo"
    commit = repository(root, data)
    resolver = ProjectContextResolver(tmp_path)
    request = read_request({FRONTEND: "repo"}, ref=commit)
    request["limit"] = 4
    chunks = []
    while True:
        page = resolver.read(request)
        chunks.append(base64.b64decode(page["content_base64"]))
        if page["next_offset"] is None:
            break
        request["offset"] = page["next_offset"]
        request["expected_sha256"] = page["sha256"]
    assert b"".join(chunks) == data
    first = resolver.read(read_request({FRONTEND: "repo"}))
    (root / "same.txt").write_bytes(b"changed\n")
    changed = read_request({FRONTEND: "repo"})
    changed["expected_sha256"] = first["sha256"]
    with pytest.raises(GitProjectReaderError) as caught:
        resolver.read(changed)
    assert caught.value.code == "repository_content_changed"
    assert base64.b64decode(resolver.read(read_request({FRONTEND: "repo"}, ref=commit))["content_base64"]) == data


def test_inherited_git_directory_selectors_cannot_redirect_repository_reads(tmp_path: Path, monkeypatch) -> None:
    repository(tmp_path / "front", b"front\n")
    repository(tmp_path / "back", b"back\n")
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "back" / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(tmp_path / "front"))
    before = tree_bytes(tmp_path)
    result = ProjectContextResolver(tmp_path).read(read_request({FRONTEND: "front"}, ref="HEAD"))
    assert base64.b64decode(result["content_base64"]) == b"front\n"
    assert tree_bytes(tmp_path) == before


def test_link_in_binding_is_rejected_even_before_parent_traversal(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repository(root)
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(root, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            pytest.skip("host does not permit creating a directory symlink")
        environment = dict(os.environ)
        environment["STRIXNOVA_TEST_LINK_PATH"] = str(alias)
        environment["STRIXNOVA_TEST_LINK_TARGET"] = str(root)
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
             "New-Item -ItemType Junction -Path $env:STRIXNOVA_TEST_LINK_PATH "
             "-Target $env:STRIXNOVA_TEST_LINK_TARGET -ErrorAction Stop | Out-Null"],
            env=environment, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            pytest.skip("host does not permit creating a directory link or junction")
    request = inspect_request({FRONTEND: "alias/../repo"})
    result = ProjectContextResolver(tmp_path).resolve(request)
    assert result.repositories[0].availability == "invalid"
    assert result.repositories[0].issue_code == "project_binding_link_forbidden"


def test_reference_from_another_repository_is_not_used_as_a_fallback(tmp_path: Path) -> None:
    repository(tmp_path / "front", b"front\n")
    backend_commit = repository(tmp_path / "back", b"back\n")
    with pytest.raises(GitProjectReaderError) as caught:
        ProjectContextResolver(tmp_path).read(
            read_request({FRONTEND: "front", BACKEND: "back"}, ref=backend_commit)
        )
    assert caught.value.code == "git_ref_not_found"


def test_outer_repository_cannot_claim_files_in_a_nested_repository(tmp_path: Path) -> None:
    outer = tmp_path / "outer"
    repository(outer, b"outer\n")
    repository(outer / "nested", b"nested\n")
    bindings = {FRONTEND: "outer", BACKEND: "outer/nested"}
    resolver = ProjectContextResolver(tmp_path)
    outer_request = read_request(bindings, FRONTEND)
    outer_request["reference"]["path"] = "nested/same.txt"
    with pytest.raises(GitProjectReaderError) as caught:
        resolver.read(outer_request)
    assert caught.value.code == "repository_content_crosses_worktree"
    result = resolver.read(read_request(bindings, BACKEND))
    assert result["repository_id"] == BACKEND
    assert base64.b64decode(result["content_base64"]) == b"nested\n"


def test_scope_and_management_inputs_are_not_silently_reinterpreted(tmp_path: Path) -> None:
    (tmp_path / "file").write_text("not a directory", encoding="utf-8")
    value = inspect_request({})
    value["bindings"]["management_root"] = "file"
    with pytest.raises(ProjectContextError) as caught:
        ProjectContextResolver(tmp_path).resolve(value)
    assert caught.value.code == "project_management_root_invalid"
    with pytest.raises(GitProjectReaderError) as caught:
        GitProjectReader(tmp_path).content_window("file")
    assert caught.value.code == "repository_scope_required"


@pytest.mark.parametrize("action", ["inspect", "read"])
def test_public_context_contract_is_self_contained(action: str) -> None:
    contract = project_context_contract(action)
    Draft202012Validator.check_schema(contract)
    payload = inspect_request({}) if action == "inspect" else read_request({})
    Draft202012Validator(contract).validate(payload)
    payload["bindings"]["project_id"] = "not-an-id"
    assert list(Draft202012Validator(contract).iter_errors(payload))


@pytest.mark.parametrize("recorded_identity", [FRONTEND, None])
def test_execution_aliases_preserve_the_physical_binding_and_original_record(tmp_path: Path, recorded_identity) -> None:
    import yaml
    from tests.support.project_configuration import configuration_document
    root = tmp_path / "repo"
    before_declaration = repository(root)
    (root / "strixnova-project.yaml").write_text(yaml.safe_dump(configuration_document(integration_ref="main")), encoding="utf-8")
    git(root, "add", "strixnova-project.yaml")
    git(root, "commit", "-m", "explicit project declaration")
    worktree = tmp_path / "worktree"
    git(root, "worktree", "add", "-b", "change", str(worktree))
    resolver = ProjectContextResolver(root)
    area = {"repository_id": recorded_identity, "git": {"repository": str(root), "worktree_path": str(worktree)}}
    before = deepcopy(area)
    with resolver.operation():
        context = resolver.configured(use_execution_bindings=False)
        with resolver.execution_readers(context, [area]):
            assert resolver.configured().repository(FRONTEND).checkout_path == worktree
            assert resolver.configured(use_execution_bindings=False).repository(FRONTEND).checkout_path == root
            assert ProjectContextResolver(worktree).configured(observed_ref=before_declaration) is None
            explicit = {
                "schema_version": "strixnova.project-bindings.v1", "project_id": PROJECT,
                "configuration": {"repository_id": FRONTEND, "path": "strixnova-project.yaml"},
                "management_root": str(root), "repositories": [{"repository_id": FRONTEND, "path": str(worktree)}],
            }
            with pytest.raises(ProjectContextError) as missing:
                ProjectContextResolver(worktree).configured(bindings=explicit, observed_ref=before_declaration)
            assert missing.value.code == "project_configuration_missing"
    assert area == before
