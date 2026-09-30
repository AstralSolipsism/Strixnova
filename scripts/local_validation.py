"""Owned temporary workspaces for local pytest and one-shot acceptance commands."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
from typing import Iterator
import uuid


ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / "strixnova/src") not in sys.path:
    sys.path.insert(0, str(ROOT / "strixnova/src"))

from strixnova.process_supervisor import (
    ProcessExecutionError, ProcessLimits, ProcessPolicy, run_process,
)


SCHEMA = "strixnova.local-validation.v1"
RUN_ID = re.compile(r"[0-9a-f]{12}")
SUCCESS_REPORTS = 3
FAILURE_DAYS = 7


def _ordinary(path: Path) -> None:
    for entry in (path, *path.parents):
        if entry.is_symlink() or entry.is_junction():
            raise ValueError(f"Validation paths cannot use links: {entry}")


def _write(path: Path, body: bytes) -> None:
    _ordinary(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _json(path: Path, value: dict) -> None:
    _write(path, (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def remove_tree(path: Path, boundary: Path) -> None:
    """Remove an owned child tree, leaving links' external targets untouched."""
    path, boundary = path.absolute(), boundary.absolute()
    if ".." in path.parts or ".." in boundary.parts:
        raise ValueError("Cleanup paths must be normalized")
    if path == boundary or not path.is_relative_to(boundary):
        raise ValueError("Cleanup must stay in an owned child directory")
    _ordinary(path)
    if path.resolve() != path or boundary.resolve() != boundary:
        raise ValueError("Cleanup paths must be canonical")
    if not path.exists():
        return
    if not path.is_dir():
        raise ValueError("Cleanup target must be a directory")
    target = str(path)
    if os.name == "nt":
        target = "\\\\?\\" + target

    def retry_readonly(function, name, error):
        attributes = os.lstat(name)
        if stat.S_ISLNK(attributes.st_mode) or getattr(attributes, "st_file_attributes", 0) & 1024:
            raise error
        if os.name == "nt" and getattr(attributes, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_READONLY:
            os.chmod(name, stat.S_IWRITE)
            function(name)
        else:
            raise error

    shutil.rmtree(target, onexc=retry_readonly)


@contextmanager
def _lock(path: Path, *, blocking: bool = True) -> Iterator[bool]:
    _ordinary(path)
    with path.open("a+b") as stream:
        if not path.stat().st_size:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        acquired = False
        try:
            if os.name == "nt":
                import msvcrt
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                    acquired = True
                except OSError:
                    if blocking:
                        raise
            else:
                import fcntl
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
                    acquired = True
                except BlockingIOError:
                    pass
            yield acquired
        finally:
            if acquired:
                stream.seek(0)
                if os.name == "nt":
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream, fcntl.LOCK_UN)


class LocalValidation:
    def __init__(self, root: Path) -> None:
        self.root = root.absolute()
        _ordinary(self.root)
        self.base = self.root / ".artifacts/validation"
        _ordinary(self.base)
        self.base.mkdir(parents=True, exist_ok=True)

    def _read(self, directory: Path) -> dict:
        _ordinary(directory)
        path = directory / "result.json"
        _ordinary(path)
        if not RUN_ID.fullmatch(directory.name) or path.stat().st_size > 128 * 1024:
            raise ValueError("Unknown validation workspace")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema_version") != SCHEMA or value.get("repository") != str(self.root) or value.get("run_id") != directory.name:
            raise ValueError("Validation workspace ownership does not match")
        if value.get("status") not in {"running", "passed", "failed", "interrupted"} or any(type(value.get(key)) is not bool for key in ("process_settled", "keep_workspace", "pin_evidence")):
            raise ValueError("Validation run state is malformed")
        if value["status"] in {"passed", "failed"}:
            finished = datetime.fromisoformat(value.get("finished_at", ""))
            if finished.tzinfo is None:
                raise ValueError("Validation completion time must include a timezone")
        return value

    def clean(self, *, release: str | None = None, release_workspace: str | None = None,
              now: datetime | None = None, protect: str | None = None) -> dict:
        """Prune completed runs only; active, unknown and interrupted runs stay."""
        now = now or datetime.now(timezone.utc)
        outcome = {"removed": [], "workspaces_removed": [], "retained": [], "errors": []}
        if release is not None and release_workspace is not None:
            raise ValueError("Select either full release or workspace-only release")
        selected_release = release if release is not None else release_workspace
        if selected_release is not None and not RUN_ID.fullmatch(selected_release):
            raise ValueError("Invalid run ID")
        with _lock(self.base / ".lock"):
            records = []
            candidates = [self.base / selected_release] if selected_release is not None else sorted(self.base.iterdir())
            for directory in candidates:
                if directory.name == ".lock":
                    continue
                try:
                    record = self._read(directory)
                    records.append((directory, record))
                except (OSError, ValueError, TypeError) as error:
                    outcome["errors"].append({"run_id": directory.name, "reason": str(error)})
            successful = sorted(
                ((directory.name, record.get("finished_at", "")) for directory, record in records if record.get("status") == "passed" and not record.get("pin_evidence") and not record.get("keep_workspace") and directory.name != protect),
                key=lambda item: item[1], reverse=True,
            )
            protected_success = any(directory.name == protect and record.get("status") == "passed" and not record.get("pin_evidence") and not record.get("keep_workspace") for directory, record in records)
            retained_successes = {name for name, _ in successful[:SUCCESS_REPORTS - protected_success]}
            if protected_success:
                retained_successes.add(protect)
            if selected_release is not None and selected_release not in {directory.name for directory, _ in records}:
                raise ValueError("Owned validation run not found")
            for directory, record in records:
                try:
                    with _lock(directory / ".lock", blocking=False) as acquired:
                        if not acquired or record.get("status") not in {"passed", "failed"} or record.get("process_settled") is not True:
                            outcome["retained"].append(directory.name)
                            if directory.name == selected_release:
                                outcome["errors"].append({"run_id": directory.name, "reason": "Run is active or its process completion is unverified"})
                            continue
                        if directory.name == release:
                            record["keep_workspace"] = False
                            record["pin_evidence"] = False
                        if directory.name == release_workspace:
                            record["keep_workspace"] = False
                            record["pin_evidence"] = True
                        finished = datetime.fromisoformat(record["finished_at"])
                        expired = finished <= now - timedelta(days=FAILURE_DAYS)
                        if not record.get("keep_workspace") and (record["status"] == "passed" or expired or directory.name == selected_release):
                            if (directory / "work").exists():
                                remove_tree(directory / "work", directory)
                                outcome["workspaces_removed"].append(directory.name)
                            record["workspace_removed"] = True
                            record.pop("cleanup_error", None)
                        _json(directory / "result.json", record)
                        remove = directory.name != protect and not record.get("pin_evidence") and not record.get("keep_workspace") and (
                            directory.name == release or (record["status"] == "passed" and directory.name not in retained_successes) or (record["status"] == "failed" and expired)
                        )
                    # The admission lock prevents another cleaner from racing
                    # removal after this run's file lock has been released.
                    if remove:
                        remove_tree(directory, self.base)
                        outcome["removed"].append(directory.name)
                except (OSError, ValueError, KeyError, TypeError) as error:
                    outcome["errors"].append({"run_id": directory.name, "reason": str(error)})
        return outcome

    def execute(self, command_factory, *, label: str, timeout: float = 3600, keep_workspace: bool = False, pin_evidence: bool = False) -> dict:
        limits = ProcessLimits(timeout_seconds=timeout, max_output_bytes=16 * 1024 * 1024)
        if not label.strip():
            raise ValueError("A validation label is required")
        previous_cleanup = self.clean()
        identifier = uuid.uuid4().hex[:12]
        directory = self.base / identifier
        with _lock(self.base / ".lock"):
            directory.mkdir()
            work, evidence = directory / "work", directory / "evidence"
            work.mkdir()
            evidence.mkdir()
            (work / "temp").mkdir()
            command = command_factory(work, evidence)
            if command and ("/" in command[0] or "\\" in command[0]) and not Path(command[0]).is_absolute():
                command = [str((self.root / command[0]).resolve()), *command[1:]]
            record = {
                "schema_version": SCHEMA, "repository": str(self.root), "run_id": identifier,
                "label": label, "command": command, "started_at": datetime.now(timezone.utc).isoformat(),
                "status": "running", "process_settled": False, "keep_workspace": keep_workspace,
                "pin_evidence": pin_evidence, "workspace_removed": False,
            }
            _json(directory / "result.json", record)
            lease = _lock(directory / ".lock")
            lease.__enter__()
        environment = dict(os.environ)
        environment.update({name: str(work / "temp") for name in ("TMP", "TEMP", "TMPDIR", "PYTEST_DEBUG_TEMPROOT")})
        environment.update(PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", STRIXNOVA_VALIDATION_WORK=str(work), STRIXNOVA_VALIDATION_EVIDENCE=str(evidence))
        # A plain temporary project must not discover this development repo.
        # Explicit repositories inside the run keep their own Git identity.
        environment["GIT_CEILING_DIRECTORIES"] = work.as_posix()
        count = int(environment.get("GIT_CONFIG_COUNT", "0"))
        environment.update({f"GIT_CONFIG_KEY_{count}": "safe.directory", f"GIT_CONFIG_VALUE_{count}": self.root.as_posix(), "GIT_CONFIG_COUNT": str(count + 1)})
        original_temp = tempfile.tempdir
        result = None
        print(f"Validation {identifier}: {label}; workspace {work}", flush=True)
        try:
            tempfile.tempdir = str(work / "temp")
            try:
                process_policy = ProcessPolicy.exact("local-validation", label, command)
                # This development wrapper hosts explicitly authorized native
                # Antigravity acceptance. Product calls construct their own
                # policy with the complete agent deny list. Preserve all
                # other existing outer-wrapper restrictions.
                process_policy = replace(process_policy,
                    forbidden_program_names=process_policy.forbidden_program_names - {"agy"})
                result = run_process(command, cwd=self.root, env=environment,
                    policy=process_policy, limits=limits)
                record.update(status="passed" if result.exit_code == 0 else "failed", process_settled=True)
            except ProcessExecutionError as error:
                result = error.partial_result
                record.update(status="failed" if error.reason != "cleanup_failed" else "interrupted", process_settled=error.reason != "cleanup_failed", error=str(error), error_reason=error.reason)
            if result is not None:
                _write(directory / "stdout.log", result.stdout)
                _write(directory / "stderr.log", result.stderr)
                record.update(exit_code=result.exit_code, duration_seconds=result.duration_seconds)
                sys.stdout.write(result.stdout_text().replace("\r\n", "\n"))
                sys.stderr.write(result.stderr_text().replace("\r\n", "\n"))
            else:
                record["exit_code"] = None
        except BaseException as error:
            record.update(status="interrupted", process_settled=False, error=type(error).__name__)
            raise
        finally:
            tempfile.tempdir = original_temp
            record["finished_at"] = datetime.now(timezone.utc).isoformat()
            try:
                if record["status"] == "passed" and not keep_workspace:
                    try:
                        remove_tree(work, directory)
                        record["workspace_removed"] = True
                    except (OSError, ValueError) as error:
                        record["cleanup_error"] = str(error)
                _json(directory / "result.json", record)
                post_cleanup = self.clean(protect=identifier)
            finally:
                lease.__exit__(None, None, None)
        record["previous_cleanup"] = previous_cleanup
        record["post_cleanup"] = post_cleanup
        record["result_path"] = str(directory / "result.json")
        return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    for name in ("test", "run"):
        command = subcommands.add_parser(name)
        command.add_argument("--keep-workspace", action="store_true", help="Keep working files until explicit clean --release")
        command.add_argument("--pin", action="store_true", help="Retain evidence beyond automatic report rotation")
        command.add_argument("--timeout", type=float, default=3600)
        if name == "test":
            command.add_argument("--full", action="store_true")
        else:
            command.add_argument("--label", required=True)
        command.add_argument("arguments", nargs=argparse.REMAINDER)
    clean = subcommands.add_parser("clean")
    releases = clean.add_mutually_exclusive_group()
    releases.add_argument("--release", help="Explicitly remove one completed, retained run and its evidence")
    releases.add_argument("--release-workspace", help="Remove one settled run's work directory and pin its evidence")
    return parser


def main(arguments: list[str] | None = None) -> int:
    parser = _parser()
    options = parser.parse_args(arguments)
    if Path(sys.executable).resolve() != (ROOT / ".venv/Scripts/python.exe").resolve():
        parser.error("Use the repository .venv/Scripts/python.exe")
    if sys.version_info[:2] != (3, 12):
        parser.error("Local validation requires Python 3.12")
    if options.action == "clean":
        result = LocalValidation(ROOT).clean(release=options.release, release_workspace=options.release_workspace)
        print(json.dumps(result, ensure_ascii=False))
        return 1 if result["errors"] else 0
    supplied = options.arguments[1:] if options.arguments[:1] == ["--"] else options.arguments
    if options.action == "test":
        if any(argument == "--" or argument.split("=", 1)[0] in {"--basetemp", "--junitxml", "--junit-xml"} for argument in supplied):
            parser.error("Temporary and report locations are managed by this entry point")
        def command(work, evidence):
            selected = [sys.executable, "-X", "utf8", "-m", "pytest", *supplied]
            if not options.full:
                selected.extend(["-m", "not slow"])
            return [*selected, "-n", "8", "-q", "--dist=loadgroup", "--basetemp", str(work / "pytest"), "--junitxml", str(evidence / "pytest.xml"), "-o", "cache_dir=" + str(work / "pytest-cache")]
        label = "pytest-full" if options.full else "pytest-affected-or-quick"
    else:
        if not supplied:
            parser.error("run requires an explicit one-shot command after --")
        command = lambda work, evidence: supplied
        label = options.label
    result = LocalValidation(ROOT).execute(command, label=label, timeout=options.timeout, keep_workspace=options.keep_workspace, pin_evidence=options.pin)
    cleanup_errors = result["previous_cleanup"]["errors"] + result["post_cleanup"]["errors"]
    if cleanup_errors:
        print(json.dumps({"cleanup_attention": cleanup_errors}, ensure_ascii=False), file=sys.stderr)
    print(json.dumps({key: result.get(key) for key in ("run_id", "status", "exit_code", "workspace_removed", "result_path", "cleanup_error", "error")}, ensure_ascii=False))
    return 0 if result["status"] == "passed" and not result.get("cleanup_error") else 1


if __name__ == "__main__":
    raise SystemExit(main())
