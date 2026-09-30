from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from click.testing import CliRunner
from jsonschema import Draft202012Validator
import pytest

from strixnova.cli import main
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.project_context import (
    BACKEND, FRONTEND, inspect_request, read_request, repository, tree_bytes,
)


def invoke(entry: Path, action: str, value: dict):
    return CliRunner().invoke(
        main, ["context", action, "--project-dir", str(entry), "--input", "@-"],
        input=json.dumps(value, ensure_ascii=False),
    )


def test_public_context_inspection_and_content_read_do_not_construct_authority(
    tmp_path: Path, monkeypatch,
) -> None:
    entry = tmp_path / "entry"
    entry.mkdir()
    repository(tmp_path / "front", "前端\n".encode("utf-8"))
    repository(tmp_path / "back", b"backend\n")
    # Existing damaged state must neither be opened nor rewritten by bootstrap reads.
    state = entry / ".strixnova"
    state.mkdir()
    (state / "authority.sqlite3").write_bytes(b"not a database")
    before = tree_bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("bootstrap query constructed a WorkflowAuthority")

    monkeypatch.setattr(WorkflowAuthority, "__init__", forbidden)
    bindings = {FRONTEND: "../front", BACKEND: "../back"}
    inspection = invoke(entry, "inspect", inspect_request(bindings))
    assert inspection.exit_code == 0, inspection.output
    context = json.loads(inspection.output)["context"]
    assert all(item["availability"] == "available" for item in context["repositories"])
    assert context["declaration_adopted"] is False
    result = invoke(entry, "read", read_request(bindings, ref="HEAD"))
    assert result.exit_code == 0, result.output
    content = json.loads(result.output)["content"]
    assert base64.b64decode(content["content_base64"]) == "前端\n".encode("utf-8")
    assert content["scope"] == "git_commit"
    assert content["writes_performed"] is False
    assert tree_bytes(tmp_path) == before
    assert not (entry / "management-not-created").exists()


@pytest.mark.parametrize("action", ["inspect", "read"])
def test_context_contract_is_discoverable_without_a_project(action: str) -> None:
    result = CliRunner().invoke(main, ["context", "contract", action])
    assert result.exit_code == 0, result.output
    contract = json.loads(result.output)["contract"]
    Draft202012Validator.check_schema(contract)
    assert contract["$id"] == f"strixnova.project-context-{action}.v1"


def test_context_cli_reports_stable_unavailable_and_changed_content_errors(tmp_path: Path) -> None:
    repository(tmp_path / "front", b"one\n")
    missing = invoke(tmp_path, "read", read_request({FRONTEND: "front", BACKEND: "absent"}, BACKEND))
    assert missing.exit_code == 1
    assert json.loads(missing.output)["error"]["code"] == "repository_checkout_missing"
    request = read_request({FRONTEND: "front"})
    first = invoke(tmp_path, "read", request)
    assert first.exit_code == 0, first.output
    request["expected_sha256"] = json.loads(first.output)["content"]["sha256"]
    (tmp_path / "front" / "same.txt").write_bytes(b"two\n")
    changed = invoke(tmp_path, "read", request)
    assert changed.exit_code == 1
    assert json.loads(changed.output)["error"]["code"] == "repository_content_changed"
    assert not (tmp_path / ".strixnova").exists()


def test_source_cli_subprocess_accepts_utf8_stdin_and_preserves_project_files(tmp_path: Path) -> None:
    entry = tmp_path / "entry"
    entry.mkdir()
    content = "跨仓库字节\n".encode("utf-8")
    repository(tmp_path / "front", content)
    request = read_request({FRONTEND: "../front"}, ref="HEAD")
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "strixnova" / "src")
    before = tree_bytes(tmp_path)

    result = subprocess.run(
        [sys.executable, "-X", "utf8", "-c", "from strixnova.cli import main; main()",
         "context", "read", "--project-dir", str(entry), "--input", "@-"],
        cwd=entry, env=environment,
        input=b"\xef\xbb\xbf" + json.dumps(request, ensure_ascii=False).encode("utf-8"),
        capture_output=True, timeout=60,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    response = json.loads(result.stdout)
    assert response["ok"] is True
    assert base64.b64decode(response["content"]["content_base64"]) == content
    assert response["content"]["declaration_adopted"] is False
    assert tree_bytes(tmp_path) == before
    assert not (entry / ".strixnova").exists()


@pytest.mark.parametrize("field,value", [("offset", True), ("limit", 0), ("limit", 1048577)])
def test_context_cli_rejects_invalid_window_before_access(tmp_path: Path, field: str, value) -> None:
    request = read_request({})
    request[field] = value
    result = invoke(tmp_path, "read", request)
    assert result.exit_code == 1
    assert json.loads(result.output)["error"]["code"] == "project_context_input_invalid"
    assert list(tmp_path.iterdir()) == []
