"""Bind declared examples to exact framework results and observed input bytes."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
from typing import Any


REPORT_SCHEMA = "strixnova.test-case-report.v1"
EVIDENCE_SCHEMA = "strixnova.test-case-evidence.v1"
MAX_REPORT_BYTES = 16 * 1024 * 1024
_EXAMPLE_REF = re.compile(r"direction\.example:DIREX-[0-9A-F]{16}")
_SHA = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN = {".git", ".strixnova"}


class TestCaseEvidenceError(ValueError):
    __test__ = False

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _fail(message: str, code: str = "test_case_contract_invalid") -> None:
    raise TestCaseEvidenceError(code, message)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip() or value != value.strip() or len(value) > 4096 or "\x00" in value:
        _fail(f"{field} 必须是规范非空文本")
    return value


def _strings(value: Any, field: str, *, maximum: int = 4096) -> list[str]:
    if not isinstance(value, list) or not value or len(value) > maximum:
        _fail(f"{field} 必须是非空且有界的数组")
    result = [_text(item, field) for item in value]
    if len(result) != len(set(result)):
        _fail(f"{field} 不得重复")
    return result


def relative_path(value: Any, *, directory: bool = False) -> str:
    text = _text(value, "case_report.path")
    path = PurePosixPath(text)
    if (path.is_absolute() or ".." in path.parts or ":" in text or "\\" in text
            or path.as_posix() != text or (path.parts and path.parts[0].casefold() in _FORBIDDEN)
            or (not directory and text == ".")):
        _fail("用例报告的输入和测试根必须是仓库内规范相对路径")
    return text


def normalize_config(
    value: Any, *, examples: Mapping[str, Mapping[str, Any]] | None = None,
    bound: bool = False,
) -> dict[str, Any]:
    required = {"adapter", "test_root", "input_paths", "bindings"}
    allowed = required | ({"example_fingerprints"} if bound else set())
    if not isinstance(value, Mapping) or required - set(value) or set(value) - allowed:
        _fail("case_report 必须包含 adapter、test_root、input_paths、bindings")
    if value["adapter"] != "pytest":
        _fail("当前内置逐用例报告适配器仅支持 pytest", "test_case_adapter_unsupported")
    test_root = relative_path(value["test_root"], directory=True)
    paths = [relative_path(item) for item in _strings(value["input_paths"], "case_report.input_paths")]
    bindings = value["bindings"]
    if not isinstance(bindings, list) or not bindings or len(bindings) > 256:
        _fail("case_report.bindings 必须包含 1 至 256 项")
    normalized = []
    seen: set[str] = set()
    for raw in bindings:
        if not isinstance(raw, Mapping) or set(raw) != {"example_ref", "test_ids"}:
            _fail("每项测试关联只能包含 example_ref 和 test_ids")
        reference = _text(raw["example_ref"], "example_ref")
        if not _EXAMPLE_REF.fullmatch(reference) or reference in seen:
            _fail("行为例子引用无效或重复")
        if examples is not None and reference not in examples:
            _fail(f"测试关联引用未知行为例子：{reference}")
        seen.add(reference)
        tests = _strings(raw["test_ids"], "test_ids", maximum=256)
        for identifier in tests:
            file_part = relative_path(identifier.split("::", 1)[0])
            full_path = (PurePosixPath(test_root) / file_part).as_posix()
            if full_path not in paths:
                _fail(f"测试用例文件未纳入 input_paths：{full_path}")
        normalized.append({"example_ref": reference, "test_ids": tests})
    result = {"adapter": "pytest", "test_root": test_root, "input_paths": sorted(paths), "bindings": normalized}
    if examples is not None:
        result["example_fingerprints"] = {ref: examples[ref]["example_sha256"] for ref in sorted(seen)}
    elif bound:
        fingerprints = value.get("example_fingerprints")
        if not isinstance(fingerprints, Mapping) or set(fingerprints) != seen or any(not isinstance(sha, str) or not _SHA.fullmatch(sha) for sha in fingerprints.values()):
            _fail("运行配置必须绑定全部当前例子的内容指纹")
        result["example_fingerprints"] = dict(fingerprints)
    return result


def merge_configs(first: Mapping[str, Any] | None, second: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if first is None or second is None:
        return deepcopy(dict(first or second)) if first or second else None
    if first["adapter"] != second["adapter"] or first["test_root"] != second["test_root"]:
        _fail("同一验证命令不能使用冲突的报告适配配置")
    merged = deepcopy(dict(first))
    merged["input_paths"] = sorted(set(first["input_paths"]) | set(second["input_paths"]))
    bindings = {item["example_ref"]: list(item["test_ids"]) for item in first["bindings"]}
    for binding in second["bindings"]:
        reference = binding["example_ref"]
        if reference in merged["example_fingerprints"] and merged["example_fingerprints"][reference] != second["example_fingerprints"][reference]:
            _fail("同一命令的例子指纹冲突")
        bindings[reference] = list(dict.fromkeys(bindings.get(reference, []) + binding["test_ids"]))
    merged["example_fingerprints"].update(second["example_fingerprints"])
    merged["bindings"] = [{"example_ref": ref, "test_ids": tests} for ref, tests in bindings.items()]
    return merged


def ordinary_path(root: Path, relative: str) -> Path:
    root = root.absolute()
    target = root / relative
    for item in (target, *target.parents):
        if item.is_symlink() or item.is_junction():
            _fail("用例输入和报告路径不能经过链接", "test_case_path_invalid")
    if not target.resolve().is_relative_to(root.resolve()):
        _fail("用例输入路径越界", "test_case_path_invalid")
    return target


def input_snapshot(root: Path, paths: Sequence[str]) -> dict[str, Any]:
    files = []
    total = 0
    for relative in sorted(paths):
        path = ordinary_path(root, relative_path(relative))
        if not path.is_file():
            _fail(f"声明的受测输入不存在：{relative}", "test_case_input_missing")
        before = path.stat()
        size = before.st_size
        total += size
        if size > 64 * 1024 * 1024 or total > 256 * 1024 * 1024:
            _fail("声明的受测输入超过有界快照限制")
        with path.open("rb") as source:
            sha = hashlib.file_digest(source, "sha256").hexdigest()
        after = path.stat()
        if after.st_size != size or after.st_mtime_ns != before.st_mtime_ns:
            _fail("受测输入在快照期间改变", "test_case_inputs_changed")
        files.append({"path": relative, "sha256": sha, "size_bytes": size})
    return {"files": files, "sha256": digest(files), "scope": "declared_inputs_only"}


def snapshot_matches(root: Path, snapshot: Mapping[str, Any], *, exclude_paths: Sequence[str] = ()) -> bool:
    try:
        if exclude_paths:
            if snapshot.get('sha256') != digest(snapshot['files']):
                return False
            retained = [item for item in snapshot['files'] if item['path'] not in exclude_paths]
            snapshot = {**snapshot, 'files': retained, 'sha256': digest(retained)}
        return input_snapshot(root, [item["path"] for item in snapshot["files"]]) == snapshot
    except (OSError, KeyError, TypeError, TestCaseEvidenceError):
        return False


def receipts_with_freshness(receipts: Sequence[Mapping[str, Any]], root: Path | None, *, exclude_paths: Sequence[str] = ()) -> list[dict[str, Any]]:
    """Annotate a disposable projection; never rewrite the recorded Agent assessment."""
    result = deepcopy(list(receipts))
    if root is not None:
        for receipt in result:
            evidence = receipt.get("case_evidence")
            if isinstance(evidence, Mapping):
                receipt["_case_input_stale"] = evidence.get("status") == "inputs_changed" or not snapshot_matches(root, evidence.get("input_snapshot", {}), exclude_paths=exclude_paths)
    return result


def adapter_path() -> Path:
    return Path(__file__).parent / "resources" / "case-adapters" / "strixnova_builtin_pytest_cases.py"


def adapter_environment(report_path: Path, run_id: str) -> tuple[dict[str, str], str]:
    path = adapter_path()
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    env = dict(os.environ)
    env["STRIXNOVA_CASE_REPORT_PATH"] = str(report_path)
    env["STRIXNOVA_CASE_RUN_ID"] = run_id
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONPATH"] = str(path.parent) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    plugins = [value for value in env.get("PYTEST_PLUGINS", "").split(",") if value]
    env["PYTEST_PLUGINS"] = ",".join(dict.fromkeys([*plugins, path.stem]))
    return env, sha


def report_results(report: Any, *, config: Mapping[str, Any], run_id: str, adapter_sha256: str, execution_root: Path) -> list[dict[str, Any]]:
    fields = {"schema_version", "run_id", "adapter", "adapter_sha256", "framework_version", "python_version", "test_root", "collection_complete", "session_finished", "exit_status", "collected_test_ids", "deselected_test_ids", "collection_errors", "results"}
    if not isinstance(report, Mapping) or set(report) != fields or report.get("schema_version") != REPORT_SCHEMA:
        _fail("用例报告结构无效", "test_case_report_invalid")
    if report["run_id"] != run_id or report["adapter"] != config["adapter"] or report["adapter_sha256"] != adapter_sha256:
        _fail("用例报告不属于本次真实执行或当前适配器", "test_case_report_mismatch")
    declared_root = ordinary_path(execution_root, config["test_root"]).resolve()
    reported_root = _text(report["test_root"], "report.test_root")
    if not Path(reported_root).is_absolute() or os.path.normcase(os.path.normpath(reported_root)) != os.path.normcase(str(declared_root)):
        _fail("用例报告测试根与方案不同", "test_case_report_mismatch")
    _text(report["framework_version"], "framework_version")
    _text(report["python_version"], "python_version")
    if report["collection_complete"] is not True or report["session_finished"] is not True or type(report["exit_status"]) is not int:
        _fail("用例收集或执行未完整结束", "test_case_report_incomplete")
    for field in ("collected_test_ids", "deselected_test_ids", "collection_errors", "results"):
        if not isinstance(report[field], list) or len(report[field]) > 100000:
            _fail(f"用例报告 {field} 无效")
    if any(not isinstance(item, str) for item in report["collection_errors"]):
        _fail("收集错误必须使用明确文本")
    collected = report["collected_test_ids"]
    deselected = report["deselected_test_ids"]
    if any(not isinstance(item, str) or not item for item in [*collected, *deselected]) or len(set(collected)) != len(collected) or set(collected) & set(deselected):
        _fail("用例收集身份重复、无效或状态冲突")
    phases: dict[str, dict[str, Mapping[str, Any]]] = {}
    for row in report["results"]:
        if not isinstance(row, Mapping) or set(row) != {"test_id", "phase", "outcome", "expected_failure"}:
            _fail("用例阶段结果结构无效")
        identifier, phase, outcome = row["test_id"], row["phase"], row["outcome"]
        if not isinstance(identifier, str) or identifier not in collected or not isinstance(phase, str) or phase not in {"setup", "call", "teardown"} or not isinstance(outcome, str) or outcome not in {"passed", "failed", "skipped"} or type(row["expected_failure"]) is not bool:
            _fail("用例阶段结果不属于实际收集或使用未知状态")
        if phase in phases.setdefault(identifier, {}):
            _fail("同一用例阶段存在多个结果，不能用重试覆盖失败")
        phases[identifier][phase] = row

    def status(identifier: str) -> str:
        if identifier in deselected:
            return "deselected"
        if identifier not in collected:
            return "not_collected"
        found = phases.get(identifier, {})
        if any(item["outcome"] == "failed" for key, item in found.items() if key != "call"):
            return "error"
        if any(item["expected_failure"] for item in found.values()):
            return "xpassed" if found.get("call", {}).get("outcome") == "passed" else "xfailed"
        if any(item["outcome"] == "failed" for item in found.values()):
            return "failed"
        if any(item["outcome"] == "skipped" for item in found.values()):
            return "skipped"
        if set(found) != {"setup", "call", "teardown"}:
            return "not_run"
        return "passed"

    result = []
    for binding in config["bindings"]:
        tests = [{"test_id": identifier, "status": status(identifier)} for identifier in binding["test_ids"]]
        passed = not report["collection_errors"] and all(test["status"] == "passed" for test in tests)
        result.append({"example_ref": binding["example_ref"], "example_sha256": config["example_fingerprints"][binding["example_ref"]], "status": "passed" if passed else "with_gaps", "tests": tests})
    return result


def unexecuted_examples(config: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [{
        "example_ref": binding["example_ref"],
        "example_sha256": config["example_fingerprints"][binding["example_ref"]],
        "status": "with_gaps",
        "tests": [{"test_id": identifier, "status": "not_run"} for identifier in binding["test_ids"]],
    } for binding in config["bindings"]]


class CaseExecution:
    """One report owned by one supervised command; no persistent workflow state."""

    def __init__(self, config: Mapping[str, Any], *, execution_root: Path, artifact_root: Path, work_item_id: str, receipt_id: str, plan_id: str) -> None:
        self.config = normalize_config(config, bound=True)
        self.execution_root = execution_root
        self.snapshot = input_snapshot(execution_root, self.config["input_paths"])
        safe_item = "".join(c if c.isalnum() or c in "._-" else "-" for c in work_item_id).strip("-")
        relative = f"{safe_item}/{receipt_id}.cases.json"
        self.report_path = ordinary_path(artifact_root, relative)
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        if self.report_path.exists():
            _fail("本次用例报告位置已经存在，拒绝复用旧报告")
        self.receipt_id, self.plan_id = receipt_id, plan_id
        self.env, self.adapter_sha256 = adapter_environment(self.report_path, receipt_id)

    def finish(self, *, exit_code: int | None) -> dict[str, Any]:
        result = {
            "schema_version": EVIDENCE_SCHEMA,
            "run_id": self.receipt_id,
            "plan_id": self.plan_id,
            "adapter": self.config["adapter"],
            "adapter_sha256": self.adapter_sha256,
            "binding_sha256": digest(self.config),
            "input_snapshot": self.snapshot,
            "status": "report_missing",
            "report_ref": str(self.report_path),
            "report_sha256": None,
            "report_size_bytes": None,
            "example_results": unexecuted_examples(self.config),
            "limitations": [],
        }
        try:
            if self.report_path.is_symlink() or self.report_path.is_junction():
                _fail("用例报告不能是链接", "test_case_path_invalid")
            if not self.report_path.is_file():
                _fail("本次命令没有生成逐用例报告", "test_case_report_missing")
            with self.report_path.open("rb") as source:
                payload = source.read(MAX_REPORT_BYTES + 1)
            if len(payload) > MAX_REPORT_BYTES:
                _fail("用例报告超过大小限制", "test_case_report_invalid")
            result["report_sha256"] = hashlib.sha256(payload).hexdigest()
            result["report_size_bytes"] = len(payload)
            report = json.loads(payload)
            if not isinstance(report, Mapping) or report.get("exit_status") != exit_code:
                _fail("报告退出状态与实际进程结果不同", "test_case_report_mismatch")
            result["example_results"] = report_results(
                report, config=self.config, run_id=self.receipt_id,
                adapter_sha256=self.adapter_sha256, execution_root=self.execution_root,
            )
            result["status"] = "recorded"
        except (OSError, ValueError, TypeError) as error:
            result["status"] = "report_missing" if isinstance(error, TestCaseEvidenceError) and error.code == "test_case_report_missing" else "report_invalid"
            result["limitations"].append(str(error))
        if not snapshot_matches(self.execution_root, self.snapshot):
            result["status"] = "inputs_changed"
            result["limitations"].append("声明的受测输入在执行期间改变；本回执不能证明当前输入。")
        return result


def validate_evidence(value: Any, config: Mapping[str, Any], *, receipt_id: str) -> dict[str, Any]:
    fields = {"schema_version", "run_id", "plan_id", "adapter", "adapter_sha256", "binding_sha256", "input_snapshot", "status", "report_ref", "report_sha256", "report_size_bytes", "example_results", "limitations"}
    if not isinstance(value, Mapping) or set(value) != fields or value.get("schema_version") != EVIDENCE_SCHEMA:
        _fail("逐用例回执结构无效")
    if value["run_id"] != receipt_id or value["binding_sha256"] != digest(config) or value["adapter"] != config["adapter"]:
        _fail("逐用例回执与本次命令或例子关联不一致")
    _text(value["plan_id"], "case_evidence.plan_id")
    _text(value["report_ref"], "case_evidence.report_ref")
    if not isinstance(value["adapter_sha256"], str) or not _SHA.fullmatch(value["adapter_sha256"]):
        _fail("报告适配器身份无效")
    if not isinstance(value["limitations"], list) or any(not isinstance(item, str) or not item.strip() for item in value["limitations"]):
        _fail("报告限制必须是明确文本数组")
    if not isinstance(value["status"], str) or value["status"] not in {"recorded", "report_missing", "report_invalid", "inputs_changed"}:
        _fail("逐用例证据状态无效")
    snapshot = value["input_snapshot"]
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"files", "sha256", "scope"} or snapshot.get("scope") != "declared_inputs_only" or not isinstance(snapshot["files"], list):
        _fail("受测输入快照结构无效")
    paths = []
    for item in snapshot["files"]:
        if not isinstance(item, Mapping) or set(item) != {"path", "sha256", "size_bytes"} or not isinstance(item["sha256"], str) or not _SHA.fullmatch(item["sha256"]) or type(item["size_bytes"]) is not int or item["size_bytes"] < 0:
            _fail("受测输入文件记录无效")
        paths.append(item["path"])
    if paths != config["input_paths"] or snapshot["sha256"] != digest(snapshot["files"]):
        _fail("受测输入快照不匹配声明范围")
    results = value["example_results"]
    if not isinstance(results, list) or len(results) != len(config["bindings"]):
        _fail("逐例结果不完整")
    for row, binding in zip(results, config["bindings"], strict=True):
        if not isinstance(row, Mapping) or set(row) != {"example_ref", "example_sha256", "status", "tests"} or row["example_ref"] != binding["example_ref"] or row["example_sha256"] != config["example_fingerprints"][binding["example_ref"]]:
            _fail("逐例结果身份或版本无效")
        tests = row["tests"]
        if not isinstance(tests, list) or len(tests) != len(binding["test_ids"]):
            _fail("逐例测试结果不完整")
        for test, identifier in zip(tests, binding["test_ids"], strict=True):
            if not isinstance(test, Mapping) or set(test) != {"test_id", "status"} or test["test_id"] != identifier or not isinstance(test["status"], str) or test["status"] not in {"passed", "failed", "error", "skipped", "xfailed", "xpassed", "deselected", "not_collected", "not_run"}:
                _fail("测试结果身份或状态无效")
        if not isinstance(row["status"], str) or row["status"] not in {"passed", "with_gaps"} or (row["status"] == "passed" and not all(test["status"] == "passed" for test in tests)):
            _fail("逐例通过声明与实际测试状态矛盾")
    if value["status"] == "recorded" and (not isinstance(value["report_sha256"], str) or not _SHA.fullmatch(value["report_sha256"]) or type(value["report_size_bytes"]) is not int):
        _fail("已记录报告缺少实际文件指纹")
    return deepcopy(dict(value))


def preflight_case_report(report: Mapping[str, Any], *, config: Mapping[str, Any], execution_root: Path) -> dict[str, Any]:
    """Inspect existing collection facts. Never execute collection or remap IDs.

    This accepts a caller-provided report for preparation, not a new verified
    execution receipt. Normal receipt validation still authenticates each run.
    """
    config = normalize_config(config, bound="example_fingerprints" in config)
    issues = []
    adapter_sha = hashlib.sha256(adapter_path().read_bytes()).hexdigest()
    try:
        report_results(report, config=config, run_id=report.get("run_id"), adapter_sha256=adapter_sha, execution_root=execution_root)
    except TestCaseEvidenceError as error:
        issues.append({"code": error.code, "message": str(error)})
    collected = report.get("collected_test_ids")
    selected = report.get("deselected_test_ids")
    valid = isinstance(collected, list) and all(isinstance(item, str) for item in collected)
    valid = valid and isinstance(selected, list) and all(isinstance(item, str) for item in selected)
    unmatched = []
    if valid:
        for binding in config["bindings"]:
            for identifier in binding["test_ids"]:
                status = "deselected" if identifier in selected else "not_collected" if identifier not in collected else None
                if status:
                    unmatched.append({"example_ref": binding["example_ref"], "test_id": identifier, "status": status})
        issues.extend({"code": "test_case_binding_unmatched", **item} for item in unmatched)
    if report.get("collection_errors"):
        issues.append({"code": "test_case_collection_errors", "errors": report["collection_errors"]})
    return {"ok": not issues, "issues": issues, "declared_test_root": str(ordinary_path(execution_root, config["test_root"]).resolve()),
            "reported_test_root": report.get("test_root"), "collected_test_ids": collected if valid else [],
            "unmatched": unmatched, "source_sha256": digest(report), "source_trust": "caller_provided_report",
            "execution_performed": False, "semantic_content_machine_proven": False}
