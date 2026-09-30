from copy import deepcopy
import json
from pathlib import Path
import sys

import pytest

from strixnova.test_case_evidence import TestCaseEvidenceError, normalize_config, report_results
from strixnova.verification_runner import VerificationRunner, normalize_verification_commands
from tests.support.behavior_examples import EXAMPLE_REF, case_config
from tests.support.verification_approval import approved_verification_request, approval_expectations


def run_cases(root: Path, source: str, test_ids, *, args=()):
    (root / "test_behavior.py").write_text(source, encoding="utf-8")
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    command = normalize_verification_commands([{
        "argv": [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args, "test_behavior.py"],
        "cwd": ".", "run_kind": "acceptance_test", "covers": [EXAMPLE_REF], "reason": "Check the confirmed receiver behavior",
        "optional_timeout": 45,
        "case_report": case_config(test_ids, input_paths=["pytest.ini", "test_behavior.py"]),
    }])[0]
    request = approved_verification_request(command, work_item_id="WI-CASES")
    runner = VerificationRunner(root)
    receipt = runner.run(request, **approval_expectations(request), limitations=[])
    return runner, command, receipt


def test_real_pytest_report_covers_exact_parameter_cases_and_detects_later_edits(tmp_path):
    _, command, receipt = run_cases(tmp_path, "import pytest\n@pytest.mark.parametrize('value',[1,2],ids=['one','two'])\ndef test_values(value):\n    assert value > 0\n", ["test_behavior.py::test_values[one]", "test_behavior.py::test_values[two]"])
    evidence = receipt["case_evidence"]
    assert receipt["result"] == "passed", receipt
    assert evidence["status"] == "recorded", evidence
    assert evidence["example_results"][0]["status"] == "passed"
    from importlib.resources import files
    from jsonschema import Draft202012Validator
    resources = files("strixnova.resources")
    report = json.loads(Path(evidence["report_ref"]).read_text(encoding="utf-8"))
    for value, filename in ((evidence, "test-case-evidence-v1.schema.json"), (report, "test-case-report-v1.schema.json")):
        schema = json.loads(resources.joinpath(filename).read_text(encoding="utf-8"))
        Draft202012Validator(schema).validate(value)
    receipt["code_change_assessment"] = {"changed_after": False, "needs_retest": False, "rationale": "Source unchanged"}
    current = VerificationRunner.coverage_status([command], [receipt], work_item_id="WI-CASES", execution_root=tmp_path)
    assert current["case_evidence_by_command"]["VC-001"]["freshness"] == "current"
    (tmp_path / "test_behavior.py").write_text("def test_other():\n    assert False\n", encoding="utf-8")
    stale = VerificationRunner.coverage_status([command], [receipt], work_item_id="WI-CASES", execution_root=tmp_path)
    assert stale["verification_status"] == "pending"
    assert stale["retest_required_command_ids"] == ["VC-001"]


def test_skip_xfail_xpass_and_missing_case_never_count_as_passed(tmp_path):
    source = """import pytest
@pytest.mark.skip(reason='not exercised')
def test_skip(): pass
@pytest.mark.xfail(reason='known issue')
def test_xfail(): assert False
@pytest.mark.xfail(reason='unexpected pass')
def test_xpass(): pass
"""
    _, _, receipt = run_cases(tmp_path, source, [f"test_behavior.py::{name}" for name in ["test_skip", "test_xfail", "test_xpass", "test_absent"]])
    evidence = receipt["case_evidence"]
    assert receipt["result"] == "passed", receipt
    assert evidence["status"] == "recorded", evidence
    assert [row["status"] for row in evidence["example_results"][0]["tests"]] == ["skipped", "xfailed", "xpassed", "not_collected"]
    assert evidence["example_results"][0]["status"] == "with_gaps"


def test_selection_and_teardown_errors_are_observed_separately(tmp_path):
    source = """import pytest
@pytest.fixture
def dirty():
    yield
    raise RuntimeError('cleanup failed')
def test_run(dirty): pass
def test_filtered(): pass
"""
    _, _, receipt = run_cases(tmp_path, source, ["test_behavior.py::test_run", "test_behavior.py::test_filtered"], args=["-k", "test_run"])
    assert receipt["result"] == "failed"
    evidence = receipt["case_evidence"]
    assert evidence["status"] == "recorded", evidence
    assert [row["status"] for row in evidence["example_results"][0]["tests"]] == ["error", "deselected"]


def test_xdist_controller_owns_one_complete_report(tmp_path):
    _, _, receipt = run_cases(tmp_path, "def test_one(): assert 1 == 1\ndef test_two(): assert 2 == 2\n", ["test_behavior.py::test_one", "test_behavior.py::test_two"], args=["-n", "2"])
    evidence = receipt["case_evidence"]
    assert receipt["result"] == "passed", receipt
    assert evidence["status"] == "recorded", evidence
    assert evidence["example_results"][0]["status"] == "passed"
    assert len(list((tmp_path / ".strixnova/artifacts/WI-CASES").glob("*.cases.json"))) == 1


def test_report_from_a_different_run_or_duplicate_phase_is_rejected(tmp_path):
    _, command, receipt = run_cases(tmp_path, "def test_one(): assert True\n", ["test_behavior.py::test_one"])
    evidence = receipt["case_evidence"]
    report = json.loads(Path(evidence["report_ref"]).read_text(encoding="utf-8"))
    kwargs = {"config": command["case_report"], "run_id": receipt["receipt_id"], "adapter_sha256": evidence["adapter_sha256"], "execution_root": tmp_path}
    forged = deepcopy(report)
    forged["run_id"] = "another-run"
    with pytest.raises(TestCaseEvidenceError, match="本次真实执行"):
        report_results(forged, **kwargs)
    report["results"].append(deepcopy(report["results"][0]))
    with pytest.raises(TestCaseEvidenceError, match="多个结果"):
        report_results(report, **kwargs)


@pytest.mark.parametrize("path", ["../outside.py", "/outside.py", "C:/outside.py", ".strixnova/private.py", "a/../b.py"])
def test_case_inputs_cannot_escape_the_declared_workspace(path):
    value = case_config(["test_behavior.py::test_one"])
    value["input_paths"].append(path)
    with pytest.raises(TestCaseEvidenceError):
        normalize_config(value, bound=True)


@pytest.mark.parametrize("case", ["missing_report", "collection_error", "changed_inputs"])
def test_success_claim_requires_a_complete_report_and_unchanged_inputs(tmp_path, case):
    source = "def test_one(): assert True\n"
    args = []
    if case == "missing_report":
        args = ["-p", "no:strixnova_builtin_pytest_cases"]
    elif case == "collection_error":
        source = "import nonexistent_strixnova_case_fixture\n" + source
    else:
        source = "from pathlib import Path\ndef test_one():\n    Path('test_behavior.py').write_text('# input changed during execution\\n')\n    assert True\n"
    _, _, receipt = run_cases(tmp_path, source, ["test_behavior.py::test_one"], args=args)
    evidence = receipt["case_evidence"]
    if case == "collection_error":
        assert receipt["result"] == "failed"
        report = json.loads(Path(evidence["report_ref"]).read_text(encoding="utf-8"))
        assert report["collection_errors"]
        assert evidence["example_results"][0]["status"] == "with_gaps"
    else:
        assert receipt["result"] == "passed"
        assert evidence["status"] == ("report_missing" if case == "missing_report" else "inputs_changed")


def test_xdist_loadgroup_keeps_exact_native_case_identity(tmp_path):
    source = "import pytest\n@pytest.mark.xdist_group('receivers')\ndef test_one(): assert True\n"
    _, _, receipt = run_cases(tmp_path, source, ["test_behavior.py::test_one@receivers"], args=["-n", "2", "--dist=loadgroup"])
    evidence = receipt["case_evidence"]
    assert receipt["result"] == "passed", receipt
    assert evidence["status"] == "recorded", evidence
    assert evidence["example_results"][0]["tests"] == [{"test_id": "test_behavior.py::test_one@receivers", "status": "passed"}]
