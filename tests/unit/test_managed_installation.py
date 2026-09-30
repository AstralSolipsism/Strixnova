from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor
import threading
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from strixnova.storage_formats import AUTHORITY_FORMAT


def test_pip_environment_cannot_redirect_installation_outside_the_managed_venv(monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.managed_installation import _environment

    for name in ("PIP_TARGET", "PIP_PREFIX", "PIP_ROOT", "PIP_PYTHON", "PIP_LOG", "PIP_REQUIRE_VIRTUALENV"):
        monkeypatch.setenv(name, "unrelated-location")
    environment = _environment()
    assert {key for key in environment if key.upper().startswith("PIP_")} == {
        "PIP_NO_INPUT", "PIP_DISABLE_PIP_VERSION_CHECK", "PIP_CONFIG_FILE",
    }


@pytest.mark.parametrize("requirements", [
    "-r outside.txt\n", "--find-links https://example.invalid/wheels\n",
    "demo @ https://example.invalid/demo.whl --hash=sha256:" + "a" * 64 + "\n",
    "../outside.whl --hash=sha256:" + "a" * 64 + "\n",
])
def test_target_dependency_contract_cannot_read_outside_files_or_fetch_urls(requirements: str) -> None:
    from strixnova.runtime_identity import RuntimeIdentityError, runtime_identity, validate_compatibility
    from importlib.resources import files

    contract = json.loads(files("strixnova.resources").joinpath("runtime-compatibility-v1.json").read_text(encoding="utf-8"))
    contract["dependency_lock"] = {"requirements": requirements, "sha256": hashlib.sha256(requirements.encode()).hexdigest()}
    with pytest.raises(RuntimeIdentityError) as caught:
        validate_compatibility(contract)
    assert caught.value.code == "runtime_compatibility_invalid"


def test_two_preparations_cannot_modify_one_environment_concurrently(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.managed_installation import ManagedInstallation
    from strixnova.project_maintenance import MaintenanceError

    project = tmp_path / "project"
    project.mkdir()
    manager = ManagedInstallation(tmp_path / "installation", project)
    wheel = tmp_path / "fixture.whl"
    _wheel(wheel)
    target = manager.inspect(wheel)
    entered, release = threading.Event(), threading.Event()
    venv_calls = []

    def run(command, **kwargs):
        if "venv" in command:
            venv_calls.append(command)
            entered.set()
            assert release.wait(5)

    monkeypatch.setattr(manager, "_run", run)
    monkeypatch.setattr(manager, "probe", lambda path: {key: target[key] for key in ("version", "build_sha256", "skill_sha256")} | {"authority_format": AUTHORITY_FORMAT})
    with ThreadPoolExecutor(max_workers=1) as pool:
        first = pool.submit(manager.prepare, target)
        assert entered.wait(5)
        try:
            with pytest.raises(MaintenanceError) as caught:
                manager.prepare(target)
            assert caught.value.code == "installation_busy"
        finally:
            release.set()
        assert first.result(timeout=5)["state"] == "ready"
    assert len(venv_calls) == 1


def test_installation_space_accounts_for_expanded_wheel_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    manager = ManagedInstallation(tmp_path / "installation", project)
    wheel = tmp_path / "compressed.whl"
    _wheel(wheel)
    with ZipFile(wheel, "a", compression=ZIP_DEFLATED) as archive:
        archive.writestr("strixnova/data.bin", b"x" * (32 * 1024 * 1024))
    target = manager.inspect(wheel)
    monkeypatch.setattr("strixnova.managed_installation.shutil.disk_usage", lambda path: SimpleNamespace(free=160 * 1024 * 1024))
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: pytest.fail("insufficient space must fail before creating a venv"))
    with pytest.raises(ManagedInstallationError) as caught:
        manager.prepare(target)
    assert caught.value.code == "installation_space_insufficient"


def _wheel(path: Path, *, unsafe: bool = False, entry_points: str = "[console_scripts]\nstrixnova = strixnova.cli:main\n") -> None:
    """A parsing fixture only; never installed or claimed as delivery evidence."""
    requirements = "# No dependencies in this archive parsing fixture.\n"
    contract = {
        "schema_version": "strixnova.runtime-compatibility.v1", "python": "3.12",
        "formats": {"authority": AUTHORITY_FORMAT, "delivery_activities": 1, "evidence": 1},
        "dependency_lock": {"sha256": hashlib.sha256(requirements.encode()).hexdigest(), "requirements": requirements},
    }
    with ZipFile(path, "w") as archive:
        archive.writestr("strixnova/__init__.py", "__version__ = '0.1.0.dev1'\n")
        archive.writestr("strixnova/resources/runtime-compatibility-v1.json", json.dumps(contract))
        archive.writestr("strixnova/resources/agent-skill/strixnova/SKILL.md", "Fixture guidance.\n")
        archive.writestr("strixnova-0.1.0.dev1.dist-info/METADATA", "Metadata-Version: 2.3\nName: strixnova\nVersion: 0.1.0.dev1\nRequires-Python: >=3.12,<3.13\n")
        archive.writestr("strixnova-0.1.0.dev1.dist-info/WHEEL", "Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n")
        archive.writestr("strixnova-0.1.0.dev1.dist-info/entry_points.txt", entry_points)
        if unsafe:
            archive.writestr("../outside.txt", "must never be extracted")


def test_target_wheel_inspection_binds_program_skill_and_formats_without_installing(tmp_path: Path) -> None:
    from strixnova.managed_installation import ManagedInstallation

    project = tmp_path / "project"
    project.mkdir()
    root = tmp_path / "installation"
    wheel = tmp_path / "strixnova-0.1.0.dev1-py3-none-any.whl"
    _wheel(wheel)
    target = ManagedInstallation(root, project).inspect(wheel)
    assert target["version"] == "0.1.0.dev1"
    assert target["formats"]["authority"] == AUTHORITY_FORMAT
    assert target["build_sha256"] != target["skill_sha256"]
    assert not root.exists()


def test_actual_interpreter_probe_uses_the_same_package_and_skill_identity_protocol(tmp_path: Path, installed_python: Path) -> None:
    from strixnova.managed_installation import ManagedInstallation
    from strixnova.runtime_identity import runtime_identity

    project = tmp_path / "project"
    project.mkdir()
    runtime = ManagedInstallation(tmp_path / "installation", project).probe(str(installed_python))
    expected = runtime_identity()
    assert runtime["build_sha256"] == expected["build_sha256"]
    assert runtime["skill_sha256"] == expected["skill_sha256"]
    assert runtime["authority_format"] == expected["formats"]["authority"]


def test_wheel_paths_cannot_escape_the_package(tmp_path: Path) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    wheel = tmp_path / "unsafe.whl"
    _wheel(wheel, unsafe=True)
    with pytest.raises(ManagedInstallationError) as blocked:
        ManagedInstallation(tmp_path / "installation", project).inspect(wheel)
    assert blocked.value.code == "invalid_upgrade_wheel"
    assert not (tmp_path / "outside.txt").exists()


def test_prepare_rejects_a_changed_wheel_before_creating_installation_files(tmp_path: Path) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    root = tmp_path / "installation"
    manager = ManagedInstallation(root, project)
    wheel = tmp_path / "fixture.whl"
    _wheel(wheel)
    target = manager.inspect(wheel)
    with wheel.open("ab") as output:
        output.write(b"changed container bytes")
    with pytest.raises(ManagedInstallationError) as blocked:
        manager.prepare(target)
    assert blocked.value.code == "installation_target_changed"
    assert not root.exists()


def test_combined_precheck_binds_the_target_and_source_without_creating_an_installation(tmp_path: Path, installed_python: Path) -> None:
    from strixnova.runtime_upgrade import RuntimeUpgrade
    from strixnova.workflow_authority import WorkflowAuthority

    project = tmp_path / "project"
    project.mkdir()
    WorkflowAuthority(project).create(title="现有项目", raw_request="保留已有事实")
    wheel = tmp_path / "fixture.whl"
    _wheel(wheel)
    request = {"installation_root": str(tmp_path / "installation"), "target_wheel": str(wheel), "source_python": str(installed_python), "builder_python": sys.executable, "wheelhouse": None}
    plan = RuntimeUpgrade(project).check(installation=request)
    assert plan["installation"]["target"]["version"] == "0.1.0.dev1"
    assert plan["installation"]["source_runtime"]["authority_format"] == AUTHORITY_FORMAT
    assert all(plan["target_formats"][kind] == version for kind, version in plan["source_formats"].items())
    assert not (tmp_path / "installation").exists()


@pytest.mark.parametrize("entry_points", ["[other]\na=b\n", "[console_scripts]\nother=a:b\n", "[console_scripts]\nstrixnova=a:b\n[console_scripts]\nstrixnova=c:d\n"])
def test_invalid_wheel_entrypoint_configuration_is_a_typed_rejection(tmp_path: Path, entry_points: str) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    wheel = tmp_path / "fixture.whl"
    _wheel(wheel, entry_points=entry_points)
    with pytest.raises(ManagedInstallationError) as caught:
        ManagedInstallation(tmp_path / "installation", project).inspect(wheel)
    assert caught.value.code == "invalid_upgrade_wheel"


def test_incomplete_active_selection_is_rejected_at_its_read_boundary(tmp_path: Path) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    manager = ManagedInstallation(tmp_path / "installation", project)
    manager._validate_root(create=True)
    (manager.root / "active.json").write_text(json.dumps({"schema_version": "strixnova.runtime-selection.v1", "project": str(project)}), encoding="utf-8")
    with pytest.raises(ManagedInstallationError) as caught:
        manager.run(["--help"])
    assert caught.value.code == "installation_selection_invalid"


@pytest.mark.parametrize("inline", [False, True])
@pytest.mark.parametrize("relative", [False, True])
def test_run_uses_the_validated_project_after_changing_child_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inline: bool, relative: bool,
) -> None:
    from strixnova.managed_installation import ManagedInstallation

    project = tmp_path / "project with spaces"
    nested = project / project.name
    nested.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    manager = ManagedInstallation(tmp_path / "installation", project)
    runtime = {"python_path": sys.executable, "entrypoint": sys.executable, "authority_format": AUTHORITY_FORMAT, "activity_format": 1}
    monkeypatch.setattr(manager, "active", lambda: {"runtime": runtime})
    monkeypatch.setattr(manager, "probe", lambda path: runtime)
    value = project.name if relative else str(project)
    option = ["--project-dir=" + value] if inline else ["--project-dir", value]
    # Exercise a real child process, with a sentinel showing which project
    # received the operation. Installation identity is outside this test.
    script = (
        "import argparse; from pathlib import Path; "
        "parser = argparse.ArgumentParser(); parser.add_argument('--project-dir'); "
        "project = Path(parser.parse_args().project_dir).resolve(); "
        "(project / 'executed.txt').write_text('executed', encoding='utf-8')"
    )
    arguments = ["-I", "-B", "-c", script, *option]
    original_arguments = list(arguments)

    result = manager.run(arguments)

    assert result.exit_code == 0, result.stderr_text()
    assert (project / "executed.txt").read_text(encoding="utf-8") == "executed"
    assert not (nested / "executed.txt").exists()
    assert arguments == original_arguments


@pytest.mark.parametrize("inline", [False, True])
def test_run_rejects_another_project_before_starting_the_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, inline: bool,
) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(tmp_path)
    manager = ManagedInstallation(tmp_path / "installation", project)
    runtime = {"python_path": sys.executable, "entrypoint": sys.executable, "authority_format": AUTHORITY_FORMAT, "activity_format": 1}
    monkeypatch.setattr(manager, "active", lambda: {"runtime": runtime})
    monkeypatch.setattr(manager, "probe", lambda path: runtime)
    monkeypatch.setattr(manager, "_run", lambda *args, **kwargs: pytest.fail("project mismatch must not start the command"))
    option = ["--project-dir=other"] if inline else ["--project-dir", "other"]

    with pytest.raises(ManagedInstallationError) as caught:
        manager.run(["intake", *option])

    assert caught.value.code == "installation_project_mismatch"
    assert list(other.iterdir()) == []


def test_installation_directory_io_failure_is_typed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError

    project = tmp_path / "project"
    project.mkdir()
    manager = ManagedInstallation(tmp_path / "installation", project)
    wheel = tmp_path / "fixture.whl"
    _wheel(wheel)
    target = manager.inspect(wheel)
    blocked = manager.root / "versions" / target["wheel_sha256"]
    original = Path.mkdir
    def denied(path, *args, **kwargs):
        if path == blocked:
            raise PermissionError("read-only installation location")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "mkdir", denied)
    with pytest.raises(ManagedInstallationError) as caught:
        manager.prepare(target)
    assert caught.value.code == "installation_io_failed"
