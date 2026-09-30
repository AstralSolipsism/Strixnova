from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from strixnova.git_project_reader import GitProjectReader
from strixnova.project_context import (
    ProjectConfigurationError,
    ProjectContextResolver,
    read_project_configuration,
)
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from tests.support.project_context import (
    BACKEND, FRONTEND, git, inspect_request, repository, tree_bytes,
)
from tests.support.project_configuration import configuration_document


def write_configuration(root: Path, baseline_path: str, integration_ref=None, *, repository_id=FRONTEND) -> None:
    (root / "strixnova-project.yaml").write_text(
        yaml.safe_dump(configuration_document(
            baseline_path=baseline_path, integration_ref=integration_ref, repository_id=repository_id,
        )), encoding="utf-8",
    )


def test_missing_configuration_remains_explicitly_unconfigured_without_writes(tmp_path: Path) -> None:
    before = tree_bytes(tmp_path)
    result = read_project_configuration(GitProjectReader(tmp_path))
    assert result["_configuration_explicit"] is False
    assert result["default_integration_ref"] is None
    assert tree_bytes(tmp_path) == before


def test_operation_reuses_selected_context_but_next_operation_reloads(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repository(root)
    write_configuration(root, "docs/first.yaml", "main")
    resolver = ProjectContextResolver(root)
    with resolver.operation():
        first = resolver.configured()
        write_configuration(root, "docs/second.yaml", "main")
        again = ProjectContextResolver(root).configured()
        assert again is first
        assert ProjectEngineeringBaseline(root).context is first
    with resolver.operation():
        second = resolver.configured()
        assert second is not first
        assert second.configuration["engineering_baseline"]["path"] == "docs/second.yaml"


def test_configuration_uses_the_selected_repository_and_commit_without_loading_baseline(
    tmp_path: Path, monkeypatch,
) -> None:
    commits = {}
    for identifier, name in ((FRONTEND, "front"), (BACKEND, "back")):
        root = tmp_path / name
        repository(root)
        write_configuration(root, f"docs/{name}.yaml", "main", repository_id=identifier)
        git(root, "add", "--", "strixnova-project.yaml")
        git(root, "commit", "-m", "configuration")
        commits[identifier] = git(root, "rev-parse", "HEAD")
        write_configuration(root, f"changed/{name}.yaml", repository_id=identifier)

    def forbidden(*args, **kwargs):
        raise AssertionError("configuration parsing loaded downstream baseline")

    monkeypatch.setattr(ProjectEngineeringBaseline, "load", forbidden)
    context = ProjectContextResolver(tmp_path).resolve(
        inspect_request({FRONTEND: "front", BACKEND: "back"})
    )
    before = tree_bytes(tmp_path)
    for identifier, name in ((FRONTEND, "front"), (BACKEND, "back")):
        reader = context.bind_reference({
            "repository_id": identifier,
            "path": "strixnova-project.yaml",
            "ref": commits[identifier],
        })
        baseline = ProjectEngineeringBaseline(reader.project, shared_reader=reader)
        assert baseline.reader is reader
        assert read_project_configuration(reader) == baseline.project_configuration()
        assert baseline.locate() == reader.project / "docs" / f"{name}.yaml"
        assert baseline.observed_commit == commits[identifier]
        assert baseline.project_configuration()["default_integration_ref"] == "main"
    assert tree_bytes(tmp_path) == before


def test_missing_historical_configuration_does_not_read_the_current_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    before_config = repository(root)
    write_configuration(root, "changed/baseline.yaml", "main")
    before = tree_bytes(tmp_path)
    historical = read_project_configuration(GitProjectReader(root, observed_ref=before_config))
    current = read_project_configuration(GitProjectReader(root))
    assert historical["_configuration_explicit"] is False
    assert historical["default_integration_ref"] is None
    assert current["_configuration_explicit"] is True
    assert current["engineering_baseline"]["path"] == "changed/baseline.yaml"
    assert tree_bytes(tmp_path) == before


@pytest.mark.parametrize("change", [
    lambda value: value.update(schema_version="strixnova.project-config.v999"),
    lambda value: value["engineering_baseline"].update(path="../escape.yaml"),
    lambda value: value["engineering_baseline"].update(path=".strixnova/private.yaml"),
    lambda value: value.update(default_integration_ref=" "),
    lambda value: value.update(unknown_location="../other"),
])
def test_invalid_configuration_keeps_existing_baseline_error_and_project_bytes(
    tmp_path: Path, change,
) -> None:
    value = configuration_document()
    change(value)
    (tmp_path / "strixnova-project.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")
    before = tree_bytes(tmp_path)
    with pytest.raises(ProjectConfigurationError) as direct:
        read_project_configuration(GitProjectReader(tmp_path))
    with pytest.raises(ProjectEngineeringBaselineError) as wrapped:
        ProjectEngineeringBaseline(tmp_path).project_configuration()
    assert direct.value.code == "project_configuration_invalid"
    assert direct.value.issues == wrapped.value.issues
    assert tree_bytes(tmp_path) == before


def test_unknown_configuration_is_rejected_in_current_and_immutable_reads(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repository(root)
    path = root / "strixnova-project.yaml"
    path.write_text("schema_version: strixnova.project-config.v999\nengineering_baseline_path: docs/base.yaml\n", encoding="utf-8")
    git(root, "add", "--", "strixnova-project.yaml")
    git(root, "commit", "-m", "historical configuration")
    commit = git(root, "rev-parse", "HEAD")
    before = tree_bytes(tmp_path)
    for observed_ref in (commit, None):
        with pytest.raises(ProjectConfigurationError, match="当前|strixnova.project-config.v1"):
            read_project_configuration(GitProjectReader(root, observed_ref=observed_ref))
    assert tree_bytes(tmp_path) == before
