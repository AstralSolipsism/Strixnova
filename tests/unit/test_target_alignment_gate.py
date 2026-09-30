from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
import yaml

from tests.support.implementation_alignment import isolated_alignment, write_yaml


PROJECT_ROOT = Path(__file__).parents[2]
GATE = PROJECT_ROOT / "scripts/check_target_alignment.py"


def _run_gate(project: Path, mode: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT / "strixnova/src")
    return subprocess.run(
        [sys.executable, str(GATE), "--mode", mode, "--project-root", str(project)],
        cwd=project, env=environment, check=False, capture_output=True,
        text=True, encoding="utf-8", errors="replace",
    )


def test_daily_alignment_gate_accepts_fixed_project_and_reports_source_drift(tmp_path: Path) -> None:
    isolated_alignment(tmp_path)
    current = _run_gate(tmp_path, "daily")
    assert current.returncode == 0, current.stdout + current.stderr
    assert json.loads(current.stdout)["passed"] is True
    (tmp_path / "src.py").write_bytes(b"VALUE = 2\n")

    changed = _run_gate(tmp_path, "daily")
    result = json.loads(changed.stdout)

    assert changed.returncode == 1
    assert result["passed"] is False
    assert result["semantic_content_machine_proven"] is False
    assert any("变化后对齐未复核" in issue for issue in result["failures"])


@pytest.mark.parametrize("status", ["confirmed", "draft", "ready_for_confirmation"])
def test_stage_gate_enforces_confirmation_in_a_fixed_project(tmp_path: Path, status: str) -> None:
    alignment = isolated_alignment(tmp_path)
    if status != "confirmed":
        path = tmp_path / alignment.alignment_path
        model = yaml.safe_load(path.read_text(encoding="utf-8"))
        model["revision"].update(status=status, confirmed_by_owner_id=None, confirmed_on=None)
        write_yaml(path, model)
        path = tmp_path / "docs/engineering/baseline.yaml"
        baseline = yaml.safe_load(path.read_text(encoding="utf-8"))
        baseline["authority_refs"]["implementation_alignment"]["status"] = {
            "revision_status": status, "adoption_status": "under_review",
        }
        baseline["review_state"] = {
            "required": True,
            "reasons": ["The fixture alignment is awaiting owner confirmation."],
            "affected_authority_kinds": ["implementation_alignment"],
        }
        write_yaml(path, baseline)

    completed = _run_gate(tmp_path, "stage")
    result = json.loads(completed.stdout)

    assert completed.returncode == (0 if status == "confirmed" else 1), completed.stdout + completed.stderr
    assert result["passed"] is (status == "confirmed")
    if status != "confirmed":
        assert result["failures"] == [f"阶段完成门要求实现对齐为已确认，当前为 {status}"]
