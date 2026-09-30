"""Bounded one-shot subprocess execution with no shell or session protocol."""

from __future__ import annotations

import ctypes
from dataclasses import dataclass
import math
import os
from pathlib import Path
import signal
import subprocess
import tempfile
import time
from typing import Callable, Mapping, Sequence


_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_FORBIDDEN_AGENT_PROGRAM_NAMES = frozenset(
    {
        "aider",
        "claude",
        "codex",
        "cursor",
        "gemini",
        "opencode",
        "windsurf",
    }
)
_COMMAND_WRAPPER_PROGRAM_NAMES = frozenset(
    {
        "bash",
        "cmd",
        "env",
        "fish",
        "node",
        "perl",
        "powershell",
        "pwsh",
        "python",
        "python3",
        "ruby",
        "sh",
        "wsl",
        "zsh",
    }
)


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_longlong),
        ("per_job_user_time_limit", ctypes.c_longlong),
        ("limit_flags", ctypes.c_uint32),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", ctypes.c_uint32),
        ("affinity", ctypes.c_size_t),
        ("priority_class", ctypes.c_uint32),
        ("scheduling_class", ctypes.c_uint32),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("read_operation_count", ctypes.c_uint64),
        ("write_operation_count", ctypes.c_uint64),
        ("other_operation_count", ctypes.c_uint64),
        ("read_transfer_count", ctypes.c_uint64),
        ("write_transfer_count", ctypes.c_uint64),
        ("other_transfer_count", ctypes.c_uint64),
    ]


class _ProcessEntry(ctypes.Structure):
    _fields_ = [
        ("size", ctypes.c_uint32),
        ("usage", ctypes.c_uint32),
        ("process_id", ctypes.c_uint32),
        ("default_heap_id", ctypes.c_size_t),
        ("module_id", ctypes.c_uint32),
        ("thread_count", ctypes.c_uint32),
        ("parent_process_id", ctypes.c_uint32),
        ("base_priority", ctypes.c_long),
        ("flags", ctypes.c_uint32),
        ("executable", ctypes.c_wchar * 260),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limit_information", _JobObjectBasicLimitInformation),
        ("io_info", _IoCounters),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


class _WindowsJob:
    def __init__(self, handle: int) -> None:
        self.handle = handle

    @classmethod
    def create(cls) -> "_WindowsJob | None":
        if os.name != "nt":
            return None
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p]
        kernel32.CreateJobObjectW.restype = ctypes.c_void_p
        kernel32.SetInformationJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.c_uint32,
        ]
        kernel32.SetInformationJobObject.restype = ctypes.c_int
        handle = kernel32.CreateJobObjectW(None, None)
        if not handle:
            return None
        information = _JobObjectExtendedLimitInformation()
        information.basic_limit_information.limit_flags = (
            _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        )
        if not kernel32.SetInformationJobObject(
            handle,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            kernel32.CloseHandle(handle)
            return None
        return cls(int(handle))

    def assign(self, process: subprocess.Popen[bytes]) -> bool:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.AssignProcessToJobObject.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        kernel32.AssignProcessToJobObject.restype = ctypes.c_int
        return bool(kernel32.AssignProcessToJobObject(self.handle, int(process._handle)))  # type: ignore[attr-defined]

    def close(self) -> None:
        if not self.handle:
            return
        handle, self.handle = self.handle, 0
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle(handle)


MAX_PROCESS_INPUT_BYTES = 64 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 256 * 1024 * 1024


@dataclass(frozen=True)
class ProcessLimits:
    timeout_seconds: float = 60.0
    cleanup_timeout_seconds: float = 10.0
    max_input_bytes: int = 1024 * 1024
    max_output_bytes: int = 16 * 1024 * 1024

    def __post_init__(self) -> None:
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if (
            not math.isfinite(self.cleanup_timeout_seconds)
            or self.cleanup_timeout_seconds <= 0
        ):
            raise ValueError("cleanup_timeout_seconds must be positive")
        if type(self.max_output_bytes) is not int or not (
            0 < self.max_output_bytes <= MAX_PROCESS_OUTPUT_BYTES
        ):
            raise ValueError(
                "max_output_bytes must be an integer between 1 and "
                f"{MAX_PROCESS_OUTPUT_BYTES}"
            )
        if type(self.max_input_bytes) is not int or not (
            0 < self.max_input_bytes <= MAX_PROCESS_INPUT_BYTES
        ):
            raise ValueError(
                "max_input_bytes must be an integer between 1 and "
                f"{MAX_PROCESS_INPUT_BYTES}"
            )


@dataclass(frozen=True)
class ProcessPolicy:
    """One exact caller-owned allow decision for a bounded process."""

    policy_id: str
    purpose: str
    allowed_commands: tuple[tuple[str, ...], ...]
    forbidden_program_names: frozenset[str] = _FORBIDDEN_AGENT_PROGRAM_NAMES

    def __post_init__(self) -> None:
        if not self.policy_id.strip() or not self.purpose.strip():
            raise ValueError("process policy identity and purpose are required")
        if not self.allowed_commands:
            raise ValueError("process policy must allow at least one exact command")
        for command in self.allowed_commands:
            if not command or any(not item for item in command):
                raise ValueError("allowed process commands must be non-empty")

    @classmethod
    def exact(
        cls,
        policy_id: str,
        purpose: str,
        command: Sequence[str],
        *,
        forbidden_program_names: Sequence[str] = (),
    ) -> "ProcessPolicy":
        forbidden = {
            name.strip().casefold()
            for name in forbidden_program_names
            if name.strip()
        }
        return cls(
            policy_id=policy_id,
            purpose=purpose,
            allowed_commands=(tuple(command),),
            forbidden_program_names=frozenset(
                {*_FORBIDDEN_AGENT_PROGRAM_NAMES, *forbidden}
            ),
        )

    def validate(self, command: Sequence[str]) -> None:
        selected = tuple(command)
        if selected not in self.allowed_commands:
            raise ProcessExecutionError(
                "policy_denied",
                "外部程序请求不在调用方精确允许范围内",
                command_name=(Path(command[0]).name if command else ""),
            )
        name = Path(selected[0]).name.casefold()
        identities = {name, Path(name).stem.casefold()}
        if identities & self.forbidden_program_names:
            raise ProcessExecutionError(
                "forbidden_agent_program",
                "受限进程监督禁止启动智能编码代理程序",
                command_name=Path(selected[0]).name,
            )
        if identities & _COMMAND_WRAPPER_PROGRAM_NAMES:
            for token in selected[1:]:
                token_name = Path(token.strip().strip('"')).name.casefold()
                token_identities = {
                    token_name,
                    Path(token_name).stem.casefold(),
                }
                if token_identities & self.forbidden_program_names:
                    raise ProcessExecutionError(
                        "forbidden_agent_wrapper",
                        "受限进程监督禁止通过包装参数启动智能编码代理程序",
                        command_name=Path(selected[0]).name,
                    )

    def forbids_program(self, program: str) -> bool:
        name = Path(program).name.casefold()
        return bool(
            {name, Path(name).stem.casefold()}
            & self.forbidden_program_names
        )


@dataclass(frozen=True)
class ProcessResult:
    command_name: str
    exit_code: int
    stdout: bytes
    stderr: bytes
    duration_seconds: float

    def stdout_text(self, encoding: str = "utf-8") -> str:
        return self.stdout.decode(encoding, errors="replace")

    def stderr_text(self, encoding: str = "utf-8") -> str:
        return self.stderr.decode(encoding, errors="replace")


class ProcessExecutionError(RuntimeError):
    def __init__(
        self,
        reason: str,
        message: str,
        *,
        command_name: str,
        partial_result: ProcessResult | None = None,
    ) -> None:
        super().__init__(message)
        self.reason = reason
        self.command_name = command_name
        self.partial_result = partial_result


def _creation_flags() -> int:
    if os.name != "nt":
        return 0
    return (
        getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
    )


def _process_snapshot() -> dict[int, tuple[int, str]]:
    """Return process parentage for enforcement, never for semantic inference."""

    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateToolhelp32Snapshot.argtypes = [
            ctypes.c_uint32,
            ctypes.c_uint32,
        ]
        kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
        kernel32.Process32FirstW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessEntry),
        ]
        kernel32.Process32FirstW.restype = ctypes.c_int
        kernel32.Process32NextW.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(_ProcessEntry),
        ]
        kernel32.Process32NextW.restype = ctypes.c_int
        snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
        invalid_handle = ctypes.c_void_p(-1).value
        if not snapshot or snapshot == invalid_handle:
            return {}
        result: dict[int, tuple[int, str]] = {}
        entry = _ProcessEntry()
        entry.size = ctypes.sizeof(_ProcessEntry)
        try:
            available = bool(kernel32.Process32FirstW(snapshot, ctypes.byref(entry)))
            while available:
                result[int(entry.process_id)] = (
                    int(entry.parent_process_id),
                    str(entry.executable),
                )
                available = bool(
                    kernel32.Process32NextW(snapshot, ctypes.byref(entry))
                )
        finally:
            kernel32.CloseHandle(snapshot)
        return result

    proc = Path("/proc")
    if not proc.is_dir():
        return {}
    result: dict[int, tuple[int, str]] = {}
    for candidate in proc.iterdir():
        if not candidate.name.isdigit():
            continue
        try:
            stat = (candidate / "stat").read_text(encoding="utf-8")
            closing = stat.rfind(")")
            fields = stat[closing + 2 :].split()
            parent = int(fields[1])
            executable = (candidate / "comm").read_text(
                encoding="utf-8"
            ).strip()
            result[int(candidate.name)] = (parent, executable)
        except (OSError, ValueError, IndexError):
            continue
    return result


def _process_creation_time(process_id: int) -> int | None:
    """Distinguish a live parent from an unrelated reuse of its PID."""
    if os.name == "nt":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.GetProcessTimes.argtypes = [ctypes.c_void_p, *([ctypes.POINTER(ctypes.c_uint64)] * 4)]
        kernel32.GetProcessTimes.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        handle = kernel32.OpenProcess(0x1000, False, process_id)
        if not handle:
            return None
        try:
            values = [ctypes.c_uint64() for _ in range(4)]
            if not kernel32.GetProcessTimes(handle, *(ctypes.byref(value) for value in values)):
                return None
            return values[0].value
        finally:
            kernel32.CloseHandle(handle)
    try:
        stat = (Path("/proc") / str(process_id) / "stat").read_text(encoding="utf-8")
        return int(stat[stat.rfind(")") + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def _forbidden_descendant(
    root_process_id: int,
    policy: ProcessPolicy,
    *,
    root_creation_time: int | None = None,
) -> str | None:
    snapshot = _process_snapshot()
    created: dict[int, int | None] = {}
    if root_creation_time is not None:
        created[root_process_id] = root_creation_time
    def creation(process_id: int) -> int | None:
        if process_id not in created:
            created[process_id] = _process_creation_time(process_id)
        return created[process_id]
    descendants = {root_process_id}
    changed = True
    while changed:
        changed = False
        for process_id, (parent_id, _) in snapshot.items():
            if process_id not in descendants and parent_id in descendants:
                descendants.add(process_id)
                changed = True
    for process_id in descendants - {root_process_id}:
        executable = snapshot[process_id][1]
        if policy.forbids_program(executable):
            child = process_id
            visited: set[int] = set()
            unverifiable = False
            while child != root_process_id and child not in visited:
                visited.add(child)
                parent = snapshot[child][0]
                child_created, parent_created = creation(child), creation(parent)
                # Windows retains the original PPID after its creator exits.
                # A newer process reusing that number does not own this child.
                if child_created is None or parent_created is None:
                    unverifiable = True
                elif child_created < parent_created:
                    break
                child = parent
            if child == root_process_id:
                if unverifiable:
                    raise ProcessExecutionError(
                        "process_identity_unverifiable",
                        "候选受限后代的进程身份无法核验，不能认定监督已完成",
                        command_name=executable,
                    )
                return executable
    return None


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    job: _WindowsJob | None,
    timeout: float,
) -> None:
    if job is not None:
        job.close()
    elif os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=timeout)
        return
    except subprocess.TimeoutExpired:
        pass
    if os.name != "nt":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        process.kill()
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raise ProcessExecutionError(
            "cleanup_failed",
            "外部工具进程树无法在限时内清理",
            command_name=Path(process.args[0]).name,
        ) from error


def _read_output(stream, limit: int) -> bytes:
    stream.flush()
    stream.seek(0)
    return stream.read(limit)


def run_process(
    command: Sequence[str],
    *,
    cwd: str | Path,
    policy: ProcessPolicy,
    limits: ProcessLimits | None = None,
    env: Mapping[str, str] | None = None,
    stdin_bytes: bytes | None = None,
    cancellation_requested: Callable[[], bool] | None = None,
) -> ProcessResult:
    """Run one exact argv without a shell under time and output bounds."""

    if not command or any(not isinstance(item, str) or not item for item in command):
        raise ValueError("command must contain non-empty strings")
    policy.validate(command)
    working_directory = Path(cwd).expanduser().resolve()
    if not working_directory.is_dir():
        raise ValueError("cwd must be an existing directory")
    active_limits = limits or ProcessLimits()
    if stdin_bytes is not None and not isinstance(stdin_bytes, bytes):
        raise ValueError("stdin_bytes must be bytes or None")
    if (
        stdin_bytes is not None
        and len(stdin_bytes) > active_limits.max_input_bytes
    ):
        raise ValueError("stdin_bytes exceeds max_input_bytes")
    command_name = Path(command[0]).name
    started = time.monotonic()
    with (
        tempfile.TemporaryFile() as stdin_file,
        tempfile.TemporaryFile() as stdout_file,
        tempfile.TemporaryFile() as stderr_file,
    ):
        if stdin_bytes is not None:
            stdin_file.write(stdin_bytes)
            stdin_file.flush()
            stdin_file.seek(0)
        job = _WindowsJob.create()
        try:
            process = subprocess.Popen(
                list(command),
                cwd=str(working_directory),
                env=dict(env) if env is not None else None,
                stdin=(stdin_file if stdin_bytes is not None else subprocess.DEVNULL),
                stdout=stdout_file,
                stderr=stderr_file,
                shell=False,
                close_fds=True,
                creationflags=_creation_flags(),
                start_new_session=os.name != "nt",
            )
        except OSError as error:
            if job is not None:
                job.close()
            raise ProcessExecutionError(
                "start_failed",
                f"无法启动外部工具：{error}",
                command_name=command_name,
            ) from error
        if job is not None and not job.assign(process):
            job.close()
            job = None

        failure: str | None = None
        forbidden_descendant: str | None = None
        root_creation_time = _process_creation_time(process.pid)
        while process.poll() is None:
            elapsed = time.monotonic() - started
            if cancellation_requested is not None and cancellation_requested():
                failure = "cancelled"
                break
            if elapsed >= active_limits.timeout_seconds:
                failure = "timeout"
                break
            output_size = stdout_file.tell() + stderr_file.tell()
            if output_size > active_limits.max_output_bytes:
                failure = "output_limit"
                break
            try:
                forbidden_descendant = _forbidden_descendant(
                    process.pid,
                    policy,
                    root_creation_time=root_creation_time,
                )
            except ProcessExecutionError as error:
                failure = error.reason
                break
            if forbidden_descendant is not None:
                failure = "forbidden_descendant_program"
                break
            time.sleep(0.01)
        if (
            failure is None
            and stdout_file.tell() + stderr_file.tell()
            > active_limits.max_output_bytes
        ):
            failure = "output_limit"
        if failure is not None:
            if failure == "process_identity_unverifiable" and os.name == "nt" and job is None:
                # Without a native job, PPID-based taskkill could select an
                # unrelated process. Stop only our retained process handle and
                # preserve the uncertainty about unowned descendants.
                process.kill()
                try:
                    process.wait(timeout=active_limits.cleanup_timeout_seconds)
                except subprocess.TimeoutExpired:
                    pass
                failure = "cleanup_failed"
            else:
                _terminate_process_tree(
                    process,
                    job,
                    active_limits.cleanup_timeout_seconds,
                )
            job = None
        elif job is not None:
            job.close()
            job = None
        stdout = _read_output(stdout_file, active_limits.max_output_bytes)
        remaining = max(0, active_limits.max_output_bytes - len(stdout))
        stderr = _read_output(stderr_file, remaining)
        result = ProcessResult(
            command_name=command_name,
            exit_code=int(process.returncode if process.returncode is not None else -1),
            stdout=stdout,
            stderr=stderr,
            duration_seconds=max(0.0, time.monotonic() - started),
        )
        if failure == "timeout":
            raise ProcessExecutionError(
                "timeout",
                "外部工具运行超时，相关进程已经清理",
                command_name=command_name,
                partial_result=result,
            )
        if failure == "output_limit":
            raise ProcessExecutionError(
                "output_limit",
                "外部工具输出超过上限，相关进程已经清理",
                command_name=command_name,
                partial_result=result,
            )
        if failure == "forbidden_descendant_program":
            raise ProcessExecutionError(
                "forbidden_descendant_program",
                "外部工具试图间接启动被禁止的智能编码代理程序，进程树已经清理",
                command_name=(forbidden_descendant or command_name),
                partial_result=result,
            )
        if failure in {"process_identity_unverifiable", "cleanup_failed"}:
            raise ProcessExecutionError(
                failure,
                "进程身份核验未完成，已停止本命令；未证明的后代处置仍需核验"
                if failure == "cleanup_failed"
                else "进程身份核验未完成，本命令及其受管进程已停止",
                command_name=command_name,
                partial_result=result,
            )
        if failure == "cancelled":
            raise ProcessExecutionError(
                "cancelled",
                "外部工具运行已按调用方取消请求停止，相关进程已经清理",
                command_name=command_name,
                partial_result=result,
            )
        return result


__all__ = [
    "MAX_PROCESS_INPUT_BYTES",
    "MAX_PROCESS_OUTPUT_BYTES",
    "ProcessExecutionError",
    "ProcessLimits",
    "ProcessPolicy",
    "ProcessResult",
    "run_process",
]
