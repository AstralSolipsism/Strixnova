from pathlib import Path
import os
import shutil
import sys
import time

import pytest

from strixnova.process_supervisor import (
    ProcessExecutionError,
    ProcessLimits,
    ProcessPolicy,
    run_process,
)


def test_reused_parent_pid_does_not_make_an_older_agent_a_child(monkeypatch):
    from strixnova import process_supervisor as supervisor

    monkeypatch.setattr(supervisor, "_process_snapshot", lambda: {100: (1, "git.exe"), 200: (100, "codex.exe")})
    monkeypatch.setattr(supervisor, "_process_creation_time", lambda pid: {100: 2000, 200: 1000}.get(pid), raising=False)
    policy = supervisor.ProcessPolicy.exact("fixture", "read Git", ["git"])
    assert supervisor._forbidden_descendant(100, policy) is None


def test_creation_time_check_retains_real_forbidden_descendants(monkeypatch):
    from strixnova import process_supervisor as supervisor

    monkeypatch.setattr(supervisor, "_process_snapshot", lambda: {100: (1, "git.exe"), 200: (100, "helper.exe"), 300: (200, "codex.exe")})
    monkeypatch.setattr(supervisor, "_process_creation_time", lambda pid: {100: 1000, 200: 1100, 300: 1200}.get(pid), raising=False)
    policy = supervisor.ProcessPolicy.exact("fixture", "read Git", ["git"])
    assert supervisor._forbidden_descendant(100, policy) == "codex.exe"


def test_exited_intermediate_does_not_silently_clear_supervision(monkeypatch):
    from strixnova import process_supervisor as supervisor

    monkeypatch.setattr(supervisor, "_process_snapshot", lambda: {100: (1, "git.exe"), 200: (100, "helper.exe"), 300: (200, "codex.exe")})
    monkeypatch.setattr(supervisor, "_process_creation_time", lambda pid: {100: 1000, 300: 1200}.get(pid))
    policy = supervisor.ProcessPolicy.exact("fixture", "read Git", ["git"])
    with pytest.raises(ProcessExecutionError) as caught:
        supervisor._forbidden_descendant(100, policy)
    assert caught.value.reason == "process_identity_unverifiable"


def test_unverifiable_supervision_stops_own_command(tmp_path, monkeypatch):
    from strixnova import process_supervisor as supervisor

    def uncertain(*args, **kwargs):
        raise ProcessExecutionError("process_identity_unverifiable", "fixture", command_name="fixture")
    monkeypatch.setattr(supervisor, "_forbidden_descendant", uncertain)
    command = [sys.executable, "-c", "import time; time.sleep(10)"]
    with pytest.raises(ProcessExecutionError) as caught:
        run_process(command, cwd=tmp_path, policy=ProcessPolicy.exact("fixture", "identity uncertainty", command))
    assert caught.value.reason in {"process_identity_unverifiable", "cleanup_failed"}
    assert caught.value.partial_result is not None


def test_output_limit_returns_a_bounded_partial_result(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "print('x' * 2000)"]
    with pytest.raises(ProcessExecutionError) as caught:
        run_process(
            command,
            cwd=tmp_path,
            policy=ProcessPolicy.exact(
                "test.output-limit",
                "exercise_output_bound",
                command,
            ),
            limits=ProcessLimits(
                timeout_seconds=5,
                cleanup_timeout_seconds=2,
                max_output_bytes=128,
            ),
        )

    assert caught.value.reason == "output_limit"
    assert caught.value.partial_result is not None
    assert len(caught.value.partial_result.stdout) <= 128
    assert len(caught.value.partial_result.stderr) == 0


def test_process_policy_rejects_unapproved_and_agent_programs(
    tmp_path: Path,
) -> None:
    approved = [sys.executable, "-c", "print('approved')"]
    policy = ProcessPolicy.exact(
        "test.exact-command",
        "exercise_policy",
        approved,
    )

    with pytest.raises(ProcessExecutionError) as unapproved:
        run_process(
            [sys.executable, "-c", "print('different')"],
            cwd=tmp_path,
            policy=policy,
        )
    assert unapproved.value.reason == "policy_denied"

    with pytest.raises(ProcessExecutionError) as agent:
        run_process(
            ["codex", "exec", "do work"],
            cwd=tmp_path,
            policy=ProcessPolicy.exact(
                "test.agent-denial",
                "exercise_policy",
                ["codex", "exec", "do work"],
            ),
        )
    assert agent.value.reason == "forbidden_agent_program"

    wrapped = [sys.executable, "codex"]
    with pytest.raises(ProcessExecutionError) as wrapper:
        run_process(
            wrapped,
            cwd=tmp_path,
            policy=ProcessPolicy.exact(
                "test.agent-wrapper-denial",
                "exercise_policy",
                wrapped,
            ),
        )
    assert wrapper.value.reason == "forbidden_agent_wrapper"


@pytest.mark.skipif(os.name != "nt", reason="本验收使用 Windows 可执行副本")
def test_process_policy_stops_agent_identity_hidden_behind_a_script(
    tmp_path: Path,
) -> None:
    # Keep the fixture's identity specific to the inner policy. The outer local
    # validation supervisor must not race this test's deliberate rejection.
    copied_agent = tmp_path / "fixture-denied-process.exe"
    shutil.copy2(Path(os.environ["COMSPEC"]), copied_agent)
    code = (
        "import subprocess; "
        f"process=subprocess.Popen([{str(copied_agent)!r}, '/c', "
        "'ping -n 6 127.0.0.1 >nul']); "
        "process.wait()"
    )
    command = [sys.executable, "-c", code]

    with pytest.raises(ProcessExecutionError) as rejected:
        run_process(
            command,
            cwd=tmp_path,
            policy=ProcessPolicy.exact(
                "test.hidden-agent-denial",
                "exercise_process_tree_policy",
                command,
                forbidden_program_names=["fixture-denied-process", "fixture-denied-process.exe"],
            ),
            limits=ProcessLimits(timeout_seconds=10),
        )

    assert rejected.value.reason == "forbidden_descendant_program"
    assert rejected.value.partial_result is not None


def test_cancellation_cleans_the_process_and_returns_partial_result(
    tmp_path: Path,
) -> None:
    command = [sys.executable, "-c", "import time; time.sleep(5)"]
    started = time.monotonic()

    with pytest.raises(ProcessExecutionError) as cancelled:
        run_process(
            command,
            cwd=tmp_path,
            policy=ProcessPolicy.exact(
                "test.cancellation",
                "exercise_cancellation",
                command,
            ),
            cancellation_requested=lambda: time.monotonic() - started > 0.05,
        )

    assert cancelled.value.reason == "cancelled"
    assert cancelled.value.partial_result is not None


def test_bounded_stdin_is_delivered_without_using_a_shell(tmp_path: Path) -> None:
    command = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read()[::-1])",
    ]

    result = run_process(
        command,
        cwd=tmp_path,
        policy=ProcessPolicy.exact(
            "test.stdin",
            "exercise_bounded_stdin",
            command,
        ),
        stdin_bytes=b"abc\x00def",
    )

    assert result.stdout == b"fed\x00cba"


def test_stdin_limit_is_checked_before_process_start(tmp_path: Path) -> None:
    command = [sys.executable, "-c", "raise SystemExit(99)"]

    with pytest.raises(ValueError, match="max_input_bytes"):
        run_process(
            command,
            cwd=tmp_path,
            policy=ProcessPolicy.exact(
                "test.stdin-limit",
                "exercise_input_bound",
                command,
            ),
            limits=ProcessLimits(max_input_bytes=3),
            stdin_bytes=b"four",
        )


def test_process_limits_reject_values_that_disable_the_product_cap() -> None:
    with pytest.raises(ValueError, match="max_input_bytes"):
        ProcessLimits(max_input_bytes=64 * 1024 * 1024 + 1)
    with pytest.raises(ValueError, match="max_output_bytes"):
        ProcessLimits(max_output_bytes=256 * 1024 * 1024 + 1)


@pytest.mark.parametrize(
    ("command", "reason"),
    [
        (["agy", "--version"], "forbidden_agent_program"),
        (["AGY.EXE", "--version"], "forbidden_agent_program"),
        ([sys.executable, "agy"], "forbidden_agent_wrapper"),
        (["powershell.exe", "-Command", "agy.exe", "--version"], "forbidden_agent_wrapper"),
    ],
)
def test_known_antigravity_entry_is_rejected_before_process_start(
    tmp_path: Path, monkeypatch, command: list[str], reason: str,
) -> None:
    def unexpected_start(*args, **kwargs):
        raise AssertionError("agent policy rejection must precede process creation")

    monkeypatch.setattr("strixnova.process_supervisor.subprocess.Popen", unexpected_start)
    with pytest.raises(ProcessExecutionError) as rejected:
        run_process(
            command, cwd=tmp_path,
            policy=ProcessPolicy.exact("test.known-agent-denial", "deny_agent", command),
        )
    assert rejected.value.reason == reason
