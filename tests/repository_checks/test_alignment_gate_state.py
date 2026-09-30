"""Explicit daily/stage checks of the Strixnova repository candidate."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import yaml


PROJECT_ROOT = Path(__file__).parents[2]
GATE = PROJECT_ROOT / "scripts" / "check_target_alignment.py"


def _run_gate(mode: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--mode", mode],
        cwd=PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_daily_alignment_gate_accepts_the_exact_governed_manifest() -> None:
    completed = _run_gate("daily")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    result = json.loads(completed.stdout)
    assert result["passed"] is True
    assert result["semantic_content_machine_proven"] is False
    assert result["counts"]["relation_violations"] == 0
    assert result["counts"]["observation_coverage_status"] == "complete"
    assert result["counts"]["observation_gaps"] == 0


def test_stage_completion_gate_tracks_the_owner_confirmation_state() -> None:
    completed = _run_gate("stage")
    result = json.loads(completed.stdout)
    baseline = yaml.safe_load(
        (PROJECT_ROOT / "docs" / "engineering" / "baseline.yaml").read_text(
            encoding="utf-8"
        )
    )
    alignment = yaml.safe_load(
        (
            PROJECT_ROOT
            / baseline["authority_refs"]["implementation_alignment"]["path"]
        ).read_text(encoding="utf-8")
    )
    responsibility_statuses = result["counts"]["target_responsibility_statuses"]
    remaining_responsibilities = sum(
        count
        for status, count in responsibility_statuses.items()
        if status != "implemented"
    )
    expected_failures: list[str] = []
    if remaining_responsibilities:
        expected_failures.append(
            f"阶段完成门仍有 {remaining_responsibilities} 项目标责任未实现"
        )
    alignment_status = alignment["revision"]["status"]
    if alignment_status != "confirmed":
        assert alignment_status in {"draft", "ready_for_confirmation"}
        expected_failures.append(
            f"阶段完成门要求实现对齐为已确认，当前为 {alignment_status}"
        )
    assert completed.returncode == (1 if expected_failures else 0)
    assert result["passed"] is (not expected_failures)
    assert result["failures"] == expected_failures
    assert not any("实际依赖偏离" in item for item in result["failures"])
