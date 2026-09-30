from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

import strixnova.project_implementation_alignment as alignment_module
from strixnova.git_project_reader import GitProjectReader
from strixnova.project_content_snapshot import repository_path_key
from tests.support.project_context import FRONTEND
from strixnova.project_implementation_alignment import (
    ProjectImplementationAlignment, ProjectImplementationAlignmentError,
)
from tests.support.implementation_alignment import isolated_alignment


def test_target_responsibility_evidence_paths_are_checked(tmp_path: Path) -> None:
    alignment = isolated_alignment(tmp_path)
    (tmp_path / "src.py").unlink()

    with pytest.raises(ProjectImplementationAlignmentError) as rejected:
        alignment.load()

    assert any("目标责任证据路径不存在" in issue for issue in rejected.value.issues)


@pytest.mark.parametrize("change", ["none", "unrelated", "comment", "source", "deleted"])
def test_daily_drift_reuses_only_unchanged_authorized_external_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str,
) -> None:
    alignment = isolated_alignment(tmp_path, recorded_external=True)
    # The saved snapshot is valid before the independent file change occurs.
    alignment.load()

    def unexpected_observation(*args, **kwargs):
        pytest.fail("A saved receipt must not silently authorize a new provider run")

    monkeypatch.setattr(alignment_module, "observe_project_implementation", unexpected_observation)
    if change == "unrelated":
        (tmp_path / "README.md").write_text("Unrelated documentation\n", encoding="utf-8")
    elif change == "comment":
        (tmp_path / "src.py").write_bytes(b"# Same behavior, changed file identity\nVALUE = 1\n")
    elif change == "source":
        (tmp_path / "src.py").write_bytes(b"VALUE = 2\n")
    elif change == "deleted":
        (tmp_path / "src.py").unlink()

    result = alignment.drift()

    assert result["passed"] is (change in {"none", "unrelated"}), result["failures"]
    assert result["semantic_content_machine_proven"] is False
    if change in {"none", "unrelated"}:
        assert result["counts"]["observation_evidence_mode"] == "recorded_exact_source_replay"
    elif change in {"source", "comment"}:
        assert any("观察过的源码已变化" in issue for issue in result["failures"])
    else:
        assert any("观察过的源码集合已不完整" in issue for issue in result["failures"])


def test_daily_drift_detects_new_dependency_in_a_fixed_project(tmp_path: Path) -> None:
    alignment = isolated_alignment(tmp_path)
    assert alignment.drift()["passed"] is True
    (tmp_path / "src.py").write_bytes(b"import json\nVALUE = json.loads('2')\n")

    result = alignment.drift()

    assert result["passed"] is False
    assert "实际实现关系变化后对齐底账尚未复核" in result["failures"]


def test_external_observation_path_normalization_keeps_controlled_diagnostics(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    source = tmp_path / "src" / "App.cs"
    source.parent.mkdir()
    source.write_bytes(b"class App {}\n")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    normalized = {repository_path_key(FRONTEND, "src/App.cs"): digest}
    manifest = hashlib.sha256(json.dumps(
        normalized, sort_keys=True, separators=(",", ":")
    ).encode()).hexdigest()
    reader = GitProjectReader(tmp_path)
    reader.bind_repository_identity(FRONTEND)
    alignment = ProjectImplementationAlignment(
        tmp_path, "alignment.yaml", domain_model_path="domain.yaml",
        architecture_description_path="architecture.yaml",
        shared_reader=reader, repository_readers={FRONTEND: reader},
    )
    issues = alignment._recorded_observation_source_issues({
        "observation_coverage": {
            "observed_paths": {FRONTEND + ": src/App.cs ": digest},
            "source_manifest_sha256": manifest,
        }
    })
    assert issues
    assert all(isinstance(issue, str) for issue in issues)
    assert any("源码清单散列" in issue for issue in issues)



def test_package_endpoint_ownership_resolves_only_one_module() -> None:
    relation = {
        "target_path": "src/pkg",
        "target_node_kind": "package",
    }
    ownership = {
        "src/pkg/a.go": {
            "disposition": "owned",
            "target_module_id": "MODULE-1111111111111111",
        },
        "src/pkg/b.go": {
            "disposition": "owned",
            "target_module_id": "MODULE-1111111111111111",
        },
    }

    assert ProjectImplementationAlignment._owned_endpoint_module(
        relation,
        "target",
        ownership,
    ) == "MODULE-1111111111111111"

    ownership["src/pkg/b.go"]["target_module_id"] = (
        "MODULE-2222222222222222"
    )
    assert ProjectImplementationAlignment._owned_endpoint_module(
        relation,
        "target",
        ownership,
    ) is None
