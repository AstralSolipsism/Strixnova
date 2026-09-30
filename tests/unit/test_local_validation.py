from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import stat
import sys
import threading

import pytest

from scripts import local_validation as validation
from strixnova.process_supervisor import ProcessExecutionError, ProcessResult


def _run(store: validation.LocalValidation, *, fail: bool = False, **options) -> dict:
    script = (
        "import os,sys; from pathlib import Path; "
        "Path(os.environ['STRIXNOVA_VALIDATION_WORK'],'scratch.txt').write_text('temporary'); "
        "Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'],'observed.txt').write_text('retained'); "
        "print('validated'); sys.exit(" + ("3" if fail else "0") + ")"
    )
    return store.execute(lambda work, evidence: [sys.executable, "-I", "-B", "-c", script], label="fixture", **options)


def test_success_removes_work_and_preserves_explicit_evidence(tmp_path: Path) -> None:
    result = _run(validation.LocalValidation(tmp_path))
    directory = Path(result["result_path"]).parent
    assert result["status"] == "passed"
    assert result["workspace_removed"] is True
    assert not (directory / "work").exists()
    assert (directory / "evidence/observed.txt").read_text() == "retained"
    assert (directory / "stdout.log").read_text().strip() == "validated"
    assert json.loads((directory / "result.json").read_text())["process_settled"] is True


def test_failure_survives_until_the_retention_deadline(tmp_path: Path) -> None:
    store = validation.LocalValidation(tmp_path)
    result = _run(store, fail=True)
    directory = Path(result["result_path"]).parent
    assert result["status"] == "failed" and result["exit_code"] == 3
    assert (directory / "work/scratch.txt").is_file()
    finished = datetime.fromisoformat(result["finished_at"])
    assert store.clean(now=finished + timedelta(days=6))["removed"] == []
    assert directory.is_dir()
    cleaned = store.clean(now=finished + timedelta(days=8))
    assert cleaned["removed"] == [result["run_id"]]
    assert not directory.exists()


def test_success_reports_rotate_but_pinned_evidence_and_kept_work_remain(tmp_path: Path) -> None:
    store = validation.LocalValidation(tmp_path)
    pinned = _run(store, pin_evidence=True)
    kept = _run(store, keep_workspace=True)
    ordinary = [_run(store) for _ in range(5)]
    failed = _run(store, fail=True)
    present = {path.name for path in store.base.iterdir() if path.is_dir()}
    assert present == {pinned["run_id"], kept["run_id"], failed["run_id"], *(item["run_id"] for item in ordinary[-3:])}
    assert not (Path(pinned["result_path"]).parent / "work").exists()
    assert (Path(kept["result_path"]).parent / "work/scratch.txt").is_file()
    assert store.clean(release=kept["run_id"])["removed"] == [kept["run_id"]]
    assert not Path(kept["result_path"]).exists()


@pytest.mark.parametrize("fail", [False, True])
def test_release_workspace_preserves_and_pins_evidence_without_touching_other_runs(tmp_path, fail):
    store = validation.LocalValidation(tmp_path)
    result = _run(store, fail=fail, keep_workspace=True)
    other = _run(store, keep_workspace=True)
    directory = Path(result["result_path"]).parent
    preserved = {p.relative_to(directory): p.read_bytes() for p in directory.rglob("*")
                 if p.is_file() and "work" not in p.relative_to(directory).parts
                 and p.name not in {"result.json", ".lock"}}
    outcome = store.clean(release_workspace=result["run_id"])
    assert outcome["workspaces_removed"] == [result["run_id"]]
    assert outcome["removed"] == outcome["errors"] == []
    assert not (directory / "work").exists()
    assert all((directory / p).read_bytes() == content for p, content in preserved.items())
    record = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    assert record["pin_evidence"] and record["workspace_removed"] and not record["keep_workspace"]
    store.clean(now=datetime.now(timezone.utc) + timedelta(days=30))
    assert directory.is_dir()
    assert (Path(other["result_path"]).parent / "work/scratch.txt").is_file()


def test_release_workspace_rejects_unsettled_processes_and_combined_release(tmp_path):
    store = validation.LocalValidation(tmp_path)
    result = _run(store, keep_workspace=True)
    record_path = Path(result["result_path"])
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record.update(status="interrupted", process_settled=False)
    record_path.write_text(json.dumps(record), encoding="utf-8")
    outcome = store.clean(release_workspace=result["run_id"])
    assert outcome["errors"] and (record_path.parent / "work").exists()
    with pytest.raises(ValueError):
        store.clean(release=result["run_id"], release_workspace=result["run_id"])


def test_workspace_release_reports_failure_without_unpinning_or_losing_receipts(tmp_path, monkeypatch):
    store = validation.LocalValidation(tmp_path)
    result = _run(store, keep_workspace=True, pin_evidence=True)
    record = Path(result["result_path"])
    original = record.read_bytes()
    def fail(*args):
        raise PermissionError("fixture locked directory")
    monkeypatch.setattr(validation, "remove_tree", fail)
    outcome = store.clean(release_workspace=result["run_id"])
    assert outcome["errors"] and outcome["removed"] == outcome["workspaces_removed"] == []
    assert record.read_bytes() == original
    assert (record.parent / "evidence/observed.txt").is_file()


def test_running_and_unverified_runs_are_never_removed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = validation.LocalValidation(tmp_path)
    started, finish = threading.Event(), threading.Event()

    def running(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        return ProcessResult("fixture", 0, b"", b"", 0)

    monkeypatch.setattr(validation, "run_process", running)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run, store)
        assert started.wait(5)
        directory = next(path for path in store.base.iterdir() if path.is_dir())
        try:
            cleaned = store.clean(release=directory.name, now=datetime.now(timezone.utc) + timedelta(days=30))
            assert cleaned["removed"] == []
            assert cleaned["retained"] == [directory.name]
            assert cleaned["errors"] and directory.exists()
        finally:
            finish.set()
        assert future.result(timeout=5)["status"] == "passed"

    def interrupted(*args, **kwargs):
        raise ProcessExecutionError("cleanup_failed", "unverified descendants", command_name="fixture")

    monkeypatch.setattr(validation, "run_process", interrupted)
    result = _run(store)
    cleaned = store.clean(release=result["run_id"], now=datetime.now(timezone.utc) + timedelta(days=30))
    assert result["status"] == "interrupted"
    assert result["process_settled"] is False
    assert result["run_id"] in cleaned["retained"]
    assert Path(result["result_path"]).is_file()


def test_unknown_or_wrong_owner_directories_are_reported_and_preserved(tmp_path: Path) -> None:
    store = validation.LocalValidation(tmp_path)
    result = _run(store)
    directory = Path(result["result_path"]).parent
    record = json.loads((directory / "result.json").read_text())
    record["repository"] = str(tmp_path / "someone-else")
    (directory / "result.json").write_text(json.dumps(record))
    unknown = store.base / "notes"
    unknown.mkdir()
    (unknown / "keep.txt").write_text("unowned")
    cleaned = store.clean(now=datetime.now(timezone.utc) + timedelta(days=30))
    assert cleaned["removed"] == []
    assert {error["run_id"] for error in cleaned["errors"]} == {directory.name, "notes"}
    assert (unknown / "keep.txt").read_text() == "unowned"


@pytest.mark.parametrize("kind", ["boundary", "parent_escape", "outside"])
def test_removal_rejects_targets_outside_the_owned_child(tmp_path: Path, kind: str) -> None:
    owned, outside = tmp_path / "owned", tmp_path / "outside"
    owned.mkdir()
    outside.mkdir()
    (outside / "keep.txt").write_text("protected")
    target = {"boundary": owned, "parent_escape": owned / "../outside", "outside": outside}[kind]
    with pytest.raises(ValueError):
        validation.remove_tree(target, owned)
    assert (outside / "keep.txt").read_text() == "protected"


def test_cleanup_does_not_follow_directory_links(tmp_path: Path) -> None:
    owned, outside = tmp_path / "owned", tmp_path / "outside"
    work = owned / "work"
    work.mkdir(parents=True)
    outside.mkdir()
    sentinel = outside / "keep.txt"
    sentinel.write_text("protected")
    link = work / "linked"
    if os.name == "nt":
        linked = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], capture_output=True)
        if linked.returncode:
            pytest.skip("Junction creation unavailable")
    else:
        link.symlink_to(outside, target_is_directory=True)
    try:
        validation.remove_tree(work, owned)
        assert not work.exists()
        assert sentinel.read_text() == "protected"
    finally:
        if link.exists() or link.is_symlink():
            if os.name == "nt":
                os.rmdir(link)
            else:
                link.unlink()


def test_success_reports_a_cleanup_failure_without_discarding_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = validation.LocalValidation(tmp_path)
    original = validation.remove_tree

    def blocked(path, boundary):
        if path.name == "work":
            raise PermissionError("still held")
        return original(path, boundary)

    monkeypatch.setattr(validation, "remove_tree", blocked)
    result = _run(store)
    assert result["status"] == "passed"
    assert result["workspace_removed"] is False
    assert "still held" in result["cleanup_error"]
    assert store.clean()["errors"]
    assert (Path(result["result_path"]).parent / "evidence/observed.txt").is_file()


@pytest.mark.parametrize("option", ["--basetemp", "--junitxml", "--junit-xml"])
def test_pytest_output_overrides_are_rejected_before_allocating_work(option: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(validation, "LocalValidation", lambda root: pytest.fail("invalid output override must not allocate a workspace"))
    with pytest.raises(SystemExit) as caught:
        validation.main(["test", "--", option, str(tmp_path / "outside")])
    assert caught.value.code == 2
    assert not (tmp_path / "outside").exists()


def test_explicit_release_does_not_remove_another_expired_run(tmp_path: Path) -> None:
    store = validation.LocalValidation(tmp_path)
    first = _run(store, fail=True)
    second = _run(store, fail=True)
    now = datetime.now(timezone.utc) + timedelta(days=30)
    assert store.clean(release=first["run_id"], now=now)["removed"] == [first["run_id"]]
    assert Path(second["result_path"]).is_file()


def test_readonly_work_files_are_reclaimed(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    path = work / "readonly.txt"
    path.write_text("temporary")
    path.chmod(stat.S_IREAD)
    validation.remove_tree(work, tmp_path)
    assert not work.exists()


def test_relative_executable_is_resolved_from_repository(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repository = tmp_path / "repository"
    repository.mkdir()
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.chdir(caller)
    observed = []

    def capture(command, **kwargs):
        observed.append((command, kwargs["cwd"]))
        return ProcessResult("tool", 0, b"", b"", 0)

    monkeypatch.setattr(validation, "run_process", capture)
    result = validation.LocalValidation(repository).execute(lambda work, evidence: ["bin/tool.exe", "check"], label="fixture")
    assert result["status"] == "passed"
    assert observed == [([str(repository / "bin/tool.exe"), "check"], repository)]


@pytest.mark.parametrize("corruption", ["array", "timestamp", "keep_flag"])
def test_malformed_run_records_are_reported_without_deletion(tmp_path: Path, corruption: str) -> None:
    store = validation.LocalValidation(tmp_path)
    result = _run(store, keep_workspace=True)
    path = Path(result["result_path"])
    record = json.loads(path.read_text())
    if corruption == "array":
        record = []
    elif corruption == "timestamp":
        record["finished_at"] = 1
    else:
        record["keep_workspace"] = "false"
    path.write_text(json.dumps(record))
    outcome = store.clean(now=datetime.now(timezone.utc) + timedelta(days=30))
    assert outcome["errors"] and outcome["removed"] == []
    assert (path.parent / "work/scratch.txt").is_file()
