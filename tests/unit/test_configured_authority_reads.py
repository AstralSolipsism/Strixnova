from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import strixnova.git_project_reader as reader_module
from strixnova.project_authority_consistency import ProjectAuthorityConsistency, ProjectAuthorityConsistencyError
from tests.support.project_baseline import portable_project_baseline
from tests.support.project_configuration import configure_repository
from tests.support.project_context import git, tree_bytes


def test_configured_authority_chain_keeps_a_bounded_shared_reader(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "src.py").write_text("value = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(tmp_path, baseline_id="bounded reads", artifacts=[])
    path = tmp_path / "docs/engineering/baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    configure_repository(tmp_path, integration_ref="main")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "fixed authority fixture")
    commit = git(tmp_path, "rev-parse", "HEAD")
    commands = []
    original = reader_module.run_process

    def counted(command, **kwargs):
        commands.append(tuple(command[1:]))
        return original(command, **kwargs)

    monkeypatch.setattr(reader_module, "run_process", counted)
    checker = ProjectAuthorityConsistency(tmp_path, observed_ref=commit)
    result = checker.load()
    assert result["structurally_consistent"] is True
    assert all(item["observed_commit"] == commit for item in result["authority_content_refs"].values())
    assert len(commands) <= 16, commands
    assert not any("show" in command for command in commands)


def test_historical_unknown_contract_is_rejected_without_writes(tmp_path: Path) -> None:
    (tmp_path / "src.py").write_text("value = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(tmp_path, baseline_id="historical locator", artifacts=[])
    baseline["schema_version"] = "strixnova.project-engineering-baseline.v999"
    for reference in baseline["authority_refs"].values():
        reference.pop("repository_id")
        reference.pop("ref")
    path = tmp_path / "docs/engineering/baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    config = tmp_path / "strixnova-project.yaml"
    config.write_text("schema_version: strixnova.project-config.v999\nengineering_baseline_path: docs/engineering/baseline.yaml\ndefault_integration_ref: main\n", encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "historical unqualified locator")
    commit = git(tmp_path, "rev-parse", "HEAD")
    config.write_text("invalid current configuration\n", encoding="utf-8")
    path.write_text("invalid current baseline\n", encoding="utf-8")
    before = tree_bytes(tmp_path)
    with pytest.raises(ProjectAuthorityConsistencyError) as rejected:
        ProjectAuthorityConsistency(tmp_path, observed_ref=commit).load()
    assert any("strixnova.project-config.v1" in issue for issue in rejected.value.issues)
    assert tree_bytes(tmp_path) == before
