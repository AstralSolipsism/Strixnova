from __future__ import annotations

import json
from click.testing import CliRunner
from jsonschema import Draft202012Validator

from strixnova.cli import main
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.project_context import tree_bytes
from tests.support.review_context import request, review_project


def test_contract_and_read_only_review_use_public_cli(tmp_path, monkeypatch):
    contract_result = CliRunner().invoke(main, ["context", "contract", "review"])
    assert contract_result.exit_code == 0, contract_result.output
    contract = json.loads(contract_result.output)["contract"]
    Draft202012Validator.check_schema(contract)
    basis = review_project(tmp_path)
    value = request(basis, mode="modules")
    Draft202012Validator(contract).validate(value)
    before = tree_bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("standalone review constructed WorkItem state")

    monkeypatch.setattr(WorkflowAuthority, "__init__", forbidden)
    for output_format in ("json", "markdown"):
        result = CliRunner().invoke(main, ["context", "review", "--project-dir", str(tmp_path), "--input", "@-", "--format", output_format], input=json.dumps(value))
        assert result.exit_code == 0, result.output
        if output_format == "json":
            context = json.loads(result.output)["context"]
            assert context["architecture"]["constraints"]
            assert context["writes_performed"] is False
        else:
            assert "测试职责分离" in result.output
            assert "VALUE = 1" in result.output
            assert "不表示已完成审阅" in result.output
    assert tree_bytes(tmp_path) == before


def test_cli_rejects_bad_target_without_creating_state(tmp_path):
    basis = review_project(tmp_path)
    value = request(basis)
    value["repositories"][0]["ref"] = "missing-ref"
    result = CliRunner().invoke(main, ["context", "review", "--project-dir", str(tmp_path), "--input", "@-"], input=json.dumps(value))
    assert result.exit_code == 1
    assert json.loads(result.output)["ok"] is False
    assert not (tmp_path / ".strixnova").exists()
