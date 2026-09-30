from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path
import subprocess

import pytest
import yaml

from scripts.refresh_engineering_assurance_evidence import refresh


def _git(project: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _candidate(project: Path) -> tuple[Path, dict]:
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Strixnova Tests")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    evidence_path = project / "evidence.txt"
    evidence_path.write_bytes(b"before\r\n")
    assurance_path = project / "docs" / "engineering" / "assurance" / "model.yaml"
    assurance_path.parent.mkdir(parents=True)
    value = {
        "assurance_revision_id": "ASSURANCEREV-1111111111111111",
        "scope": "Agent authored meaning",
        "evidence_base_commit": "0" * 40,
        "evidence": [
            {
                "evidence_id": "EVIDENCE-1111111111111111",
                "evidence_kind": "repository_file",
                "path": "evidence.txt",
                "sha256": "0" * 64,
                "receipt_id": None,
                "claim": "Agent authored claim",
                "limitations": ["Agent authored limitation"],
            }
        ],
        "rule_assessments": [{"status": "partially_satisfied"}],
    }
    assurance_path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(project, "add", ".")
    _git(project, "commit", "-m", "test fixture")
    return assurance_path, value


def test_refresh_changes_only_hashes_and_base_commit(tmp_path: Path) -> None:
    assurance_path, original = _candidate(tmp_path)
    semantic_before = deepcopy(original)
    semantic_before.pop("evidence_base_commit")
    semantic_before["evidence"][0].pop("sha256")

    result = refresh(tmp_path, "ASSURANCEREV-1111111111111111")

    refreshed = yaml.safe_load(assurance_path.read_text(encoding="utf-8"))
    semantic_after = deepcopy(refreshed)
    semantic_after.pop("evidence_base_commit")
    semantic_after["evidence"][0].pop("sha256")
    assert semantic_after == semantic_before
    assert refreshed["evidence_base_commit"] == _git(tmp_path, "rev-parse", "HEAD")
    assert refreshed["evidence"][0]["sha256"] == hashlib.sha256(
        b"before\n"
    ).hexdigest()
    assert result["semantic_fields_changed"] is False


def test_refresh_rejects_an_unexpected_revision(tmp_path: Path) -> None:
    _candidate(tmp_path)

    with pytest.raises(ValueError, match="修订身份"):
        refresh(tmp_path, "ASSURANCEREV-2222222222222222")
