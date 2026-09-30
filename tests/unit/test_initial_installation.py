from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from strixnova.initial_installation import install_initial_runtime
from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError
from strixnova.process_supervisor import ProcessResult
from scripts.offline_install import inspect_bundle
from scripts.build_offline_bundle import build_bundle
from tests.unit.test_managed_installation import _wheel


def test_installer_can_import_without_strixnova_or_third_party_site_packages(tmp_path: Path) -> None:
    source = Path(__file__).parents[2] / "strixnova/src/strixnova"
    archive_path = tmp_path / "stdlib-import-fixture.zip"
    with ZipFile(archive_path, "w") as archive:
        for path in source.rglob("*.py"):
            archive.write(path, "strixnova/" + path.relative_to(source).as_posix())
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-c", "import sys;sys.path.insert(0,sys.argv[1]);import strixnova.initial_installation;assert 'jsonschema' not in sys.modules;print('ready')", str(archive_path)],
        cwd=tmp_path, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ready"


def test_initial_installation_reuses_existing_managed_operations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    wheel = tmp_path / "target.whl"
    _wheel(wheel)
    target = ManagedInstallation.inspect(wheel)
    runtime = {key: target[key] for key in ("version", "build_sha256", "skill_sha256")}
    runtime.update(python_path="fixture-python", entrypoint="fixture-entry", skill_path="fixture-skill")
    calls = []
    monkeypatch.setattr(ManagedInstallation, "prepare", lambda self, target, **kwargs: calls.append(("prepare", kwargs)) or {"runtime": runtime})
    monkeypatch.setattr(ManagedInstallation, "select", lambda self, value, **kwargs: calls.append(("select", kwargs)))
    monkeypatch.setattr(ManagedInstallation, "run", lambda self, args: calls.append(("skill", args)) or ProcessResult("fixture", 0, b'{"ok":true,"install":{"status":"installed"}}', b"", 0))
    result = install_initial_runtime(project, tmp_path / "installation", wheel, tmp_path / "wheels", builder_python=sys.executable, skills_dir=tmp_path / "skills")
    assert [call[0] for call in calls] == ["prepare", "select", "skill"]
    assert calls[0][1]["builder_python"] == sys.executable
    assert calls[1][1]["expected"] is None
    assert calls[2][1] == ["setup-agent", "--skills-dir", str(tmp_path / "skills")]
    assert result["runtime"] == runtime
    assert result["host_loaded_verified"] is False
    assert not (project / ".strixnova/authority.sqlite3").exists()


def test_existing_project_data_requires_explicit_upgrade_before_preparation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    project = tmp_path / "project"
    state = project / ".strixnova/authority.sqlite3"
    state.parent.mkdir(parents=True)
    state.write_bytes(b"existing data")
    wheel = tmp_path / "target.whl"
    _wheel(wheel)
    monkeypatch.setattr(ManagedInstallation, "prepare", lambda *args, **kwargs: pytest.fail("Must not start installation"))
    with pytest.raises(ManagedInstallationError) as error:
        install_initial_runtime(project, tmp_path / "installation", wheel, tmp_path / "wheels", builder_python=sys.executable)
    assert error.value.code == "installation_upgrade_required"
    assert state.read_bytes() == b"existing data"


@pytest.mark.parametrize("same_version", [True, False])
def test_existing_selection_is_not_replaced_by_initial_installation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, same_version: bool) -> None:
    project = tmp_path / "project"
    project.mkdir()
    wheel = tmp_path / "target.whl"
    _wheel(wheel)
    target = ManagedInstallation.inspect(wheel)
    runtime = {key: target[key] for key in ("version", "build_sha256", "skill_sha256")}
    runtime["python_path"] = "original-python"
    if not same_version:
        runtime["build_sha256"] = "different"
    monkeypatch.setattr(ManagedInstallation, "active", lambda self: {"runtime": runtime})
    monkeypatch.setattr(ManagedInstallation, "probe", lambda self, path: runtime)
    monkeypatch.setattr(ManagedInstallation, "prepare", lambda *args, **kwargs: pytest.fail("Existing selection must not be prepared again"))
    if same_version:
        result = install_initial_runtime(project, tmp_path / "installation", wheel, tmp_path / "wheels", builder_python=sys.executable)
        assert result["status"] == "unchanged"
        assert result["runtime"] == runtime
    else:
        with pytest.raises(ManagedInstallationError) as error:
            install_initial_runtime(project, tmp_path / "installation", wheel, tmp_path / "wheels", builder_python=sys.executable)
        assert error.value.code == "installation_upgrade_required"


def _bundle(tmp_path: Path) -> dict:
    (tmp_path / "dependencies").mkdir()
    entries = {"install.py": b"bootstrap", "install.ps1": b"launcher", "README.md": b"instructions", "strixnova.whl": b"target", "dependencies/example.whl": b"dependency"}
    for name, content in entries.items():
        (tmp_path / name).write_bytes(content)
    manifest = {"schema_version": "strixnova.offline-bundle.v1", "version": "0.1.0.dev1", "python": "3.12", "platform": "win-amd64", "strixnova_wheel": "strixnova.whl", "wheelhouse": "dependencies", "files": {name: hashlib.sha256(value).hexdigest() for name, value in entries.items()}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


@pytest.mark.parametrize("change", ["content", "missing", "extra", "escape"])
def test_bundle_validation_rejects_changed_missing_extra_or_escaping_files(tmp_path: Path, change: str) -> None:
    manifest = _bundle(tmp_path)
    assert inspect_bundle(tmp_path) == manifest
    if change == "content":
        (tmp_path / "strixnova.whl").write_bytes(b"different")
    elif change == "missing":
        (tmp_path / "dependencies/example.whl").unlink()
    elif change == "extra":
        (tmp_path / "dependencies/unlisted.whl").write_bytes(b"extra")
    else:
        manifest["files"]["../outside.whl"] = "0" * 64
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError):
        inspect_bundle(tmp_path)


@pytest.mark.parametrize("dependency", ["valid", "missing", "wrong_platform", "changed"])
def test_offline_builder_requires_matching_platform_and_locked_bytes(tmp_path: Path, dependency: str) -> None:
    wheel = tmp_path / "strixnova-0.1.0.dev1-py3-none-any.whl"
    _wheel(wheel)
    with ZipFile(wheel) as archive:
        contents = {name: archive.read(name) for name in archive.namelist()}
    resource = "strixnova/resources/runtime-compatibility-v1.json"
    contract = json.loads(contents[resource])
    body = b"archive selection fixture; never installed"
    requirements = "example==1.0 --hash=sha256:" + hashlib.sha256(body).hexdigest() + "\n"
    contract["dependency_lock"] = {"requirements": requirements, "sha256": hashlib.sha256(requirements.encode()).hexdigest()}
    contents[resource] = json.dumps(contract).encode()
    with ZipFile(wheel, "w") as archive:
        for name, content in contents.items():
            archive.writestr(name, content)
    wheelhouse = tmp_path / "wheels"
    wheelhouse.mkdir()
    if dependency != "missing":
        tag = "cp312-cp312-manylinux_2_17_x86_64" if dependency == "wrong_platform" else "cp312-cp312-win_amd64"
        (wheelhouse / ("example-1.0-" + tag + ".whl")).write_bytes(b"changed" if dependency == "changed" else body)
    destination = tmp_path / "strixnova-0.1.0.dev1-offline"
    if dependency == "valid":
        result = build_bundle(wheel, wheelhouse, destination)
        assert inspect_bundle(destination)["version"] == "0.1.0.dev1"
        assert result["dependency_wheels"] == 1
        assert Path(result["archive_path"]).name == destination.name + ".zip"
    else:
        with pytest.raises(ValueError, match="Missing locked wheels"):
            build_bundle(wheel, wheelhouse, destination)
        assert not destination.exists()
