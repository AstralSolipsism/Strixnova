"""Inspect and manage explicitly selected local Strixnova installation releases."""

from __future__ import annotations

from email.parser import Parser
from contextlib import nullcontext
from functools import wraps
from configparser import ConfigParser, Error as ConfigParserError
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import sys
import uuid
from typing import Any
from zipfile import BadZipFile, ZipFile

from strixnova.storage_formats import AUTHORITY_FORMAT, ACTIVITY_FORMAT
from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance, installation_preparation, project_operation, write_maintenance_json
from strixnova.process_supervisor import ProcessExecutionError, ProcessLimits, ProcessPolicy, ProcessResult, run_process
from strixnova.runtime_identity import COMPATIBILITY_RESOURCE, RuntimeIdentityError, content_identities, file_sha256, locked_dependencies, validate_compatibility


class ManagedInstallationError(MaintenanceError):
    pass


_PROBE = r"""
import hashlib,json,pathlib,sys
import strixnova
from strixnova.workflow_authority import AUTHORITY_SCHEMA_VERSION
from strixnova.storage_formats import ACTIVITY_FORMAT
p=pathlib.Path(strixnova.__file__).resolve().parent
h={f.relative_to(p).as_posix():hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(p.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.suffix!='.pyc'}
b=hashlib.sha256(json.dumps(h,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode('utf-8')).hexdigest()
s=hashlib.sha256(b'strixnova.skill-bundle-content-manifest.v1\n')
prefix='resources/agent-skill/strixnova/'
for name,digest in sorted(h.items()):
    if name.startswith(prefix): s.update(name[len(prefix):].encode('utf-8')+b'\0'+digest.encode('ascii')+b'\n')
exe=pathlib.Path(sys.executable).with_name('strixnova.exe' if sys.platform=='win32' else 'strixnova')
python=pathlib.Path(sys.executable).resolve()
native={str(f.resolve()):hashlib.sha256(f.read_bytes()).hexdigest() for f in [python,exe,python.with_name('pythonw.exe')] if f.is_file()}
print(json.dumps({'schema_version':'strixnova.installed-runtime-probe.v1','version':strixnova.__version__,'python_version':list(sys.version_info[:2]),'python_path':str(python),'python_sha256':native[str(python)],'native_entrypoints':native,'package_path':str(p),'authority_format':int(AUTHORITY_SCHEMA_VERSION),'activity_format':ACTIVITY_FORMAT,'build_sha256':b,'skill_sha256':s.hexdigest(),'skill_path':str(p/'resources/agent-skill/strixnova'),'entrypoint':str(exe.resolve()),'entrypoint_sha256':native.get(str(exe.resolve()))},ensure_ascii=True))
"""


def _environment() -> dict[str, str]:
    result = {key: value for key, value in os.environ.items() if not key.upper().startswith("PIP_")}
    result.pop("PYTHONPATH", None)
    result.pop("PYTHONHOME", None)
    result.update({"PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1", "PIP_NO_INPUT": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_CONFIG_FILE": os.devnull})
    return result


def _installation_write(function):
    @wraps(function)
    def wrapped(self, *args, **kwargs):
        try:
            self._validate_root()
            with ProjectMaintenance(self.project).installation_executor(self.root):
                scope = installation_preparation(self.project) if function.__name__ == "prepare" else nullcontext()
                with scope:
                    return function(self, *args, **kwargs)
        except OSError as error:
            raise ManagedInstallationError("installation_io_failed", "受管安装文件操作失败，保留原程序与已创建的准备记录", details={"operation": function.__name__, "os_error": getattr(error, "winerror", error.errno)}) from error
    return wrapped


def _ordinary_install_path(path: Path, *, directory: bool = False) -> None:
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise ManagedInstallationError("installation_path_unsafe", "安装写入路径及父目录不能通过链接访问")
        if candidate != path and candidate.exists() and not candidate.is_dir():
            raise ManagedInstallationError("installation_path_occupied", "安装写入位置的父路径不是目录")
    if directory and path.exists() and not path.is_dir():
        raise ManagedInstallationError("installation_path_occupied", "安装写入位置不是普通目录")


class ManagedInstallation:
    def __init__(self, installation_root: str | Path, project_dir: str | Path) -> None:
        requested_root = Path(installation_root).expanduser().absolute()
        _ordinary_install_path(requested_root, directory=True)
        self.root = requested_root.resolve()
        self.project = Path(project_dir).expanduser().resolve()
        if self.root == self.project or self.root.is_relative_to(self.project) or self.project.is_relative_to(self.root):
            raise ManagedInstallationError("installation_scope_invalid", "受管安装目录与项目目录必须互不包含")

    @staticmethod
    def inspect(wheel_path: str | Path) -> dict[str, Any]:
        wheel = Path(wheel_path).expanduser().resolve()
        if not wheel.is_file():
            raise ManagedInstallationError("invalid_upgrade_wheel", "目标 wheel 不存在")
        hashes: dict[str, str] = {}
        try:
            with ZipFile(wheel) as archive:
                entries = archive.infolist()
                if len(entries) > 10000 or sum(entry.file_size for entry in entries) > 512 * 1024 * 1024:
                    raise ValueError("archive limits")
                seen = set()
                metadata_names = []
                for entry in entries:
                    name = entry.filename.rstrip("/")
                    relative = PurePosixPath(name)
                    if not name or relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name or relative.as_posix() != name or name.casefold() in seen:
                        raise ValueError("unsafe or duplicate archive name")
                    seen.add(name.casefold())
                    if not (relative.parts[0] == "strixnova" or relative.parts[0].startswith("strixnova-") and relative.parts[0].endswith(".dist-info")):
                        raise ValueError("unexpected wheel root")
                    if entry.is_dir():
                        continue
                    if entry.file_size > 64 * 1024 * 1024:
                        raise ValueError("file limit")
                    if name.endswith(".dist-info/METADATA"):
                        metadata_names.append(name)
                    if name.startswith("strixnova/"):
                        hashes[name[len("strixnova/"):]] = hashlib.sha256(archive.read(entry)).hexdigest()
                if len(metadata_names) != 1:
                    raise ValueError("metadata count")
                metadata = Parser().parsestr(archive.read(metadata_names[0]).decode("utf-8"))
                if str(metadata.get("Name", "")).casefold() != "strixnova" or not metadata.get("Version"):
                    raise ValueError("package identity")
                wheel_metadata = Parser().parsestr(archive.read(metadata_names[0].removesuffix("METADATA") + "WHEEL").decode("utf-8"))
                if wheel_metadata.get("Root-Is-Purelib", "").casefold() != "true" or "py3-none-any" not in wheel_metadata.get_all("Tag", []):
                    raise ValueError("unsupported wheel platform")
                entrypoints = ConfigParser(interpolation=None)
                entrypoints.read_string(archive.read(metadata_names[0].removesuffix("METADATA") + "entry_points.txt").decode("utf-8"))
                if entrypoints.get("console_scripts", "strixnova") != "strixnova.cli:main":
                    raise ValueError("unexpected command entry")
                contract = validate_compatibility(json.loads(archive.read("strixnova/resources/" + COMPATIBILITY_RESOURCE)))
                if "resources/agent-skill/strixnova/SKILL.md" not in hashes or "__init__.py" not in hashes:
                    raise ValueError("required package content")
        except (OSError, BadZipFile, ValueError, KeyError, UnicodeError, RuntimeIdentityError, ConfigParserError) as error:
            raise ManagedInstallationError("invalid_upgrade_wheel", "目标 wheel 的路径、包身份或运行合同无效") from error
        return {
            "schema_version": "strixnova.installation-target.v1", "wheel_path": str(wheel),
            "wheel_sha256": file_sha256(wheel), "version": str(metadata["Version"]),
            **content_identities(hashes), "formats": contract["formats"],
            "dependency_lock_sha256": contract["dependency_lock"]["sha256"],
            "requires_python": str(metadata.get("Requires-Python", "")),
            "unpacked_size_bytes": sum(entry.file_size for entry in entries),
        }

    def _dependency_space(self, wheelhouse: Path | None, requirements: str) -> int:
        expected = locked_dependencies(requirements)
        if not expected:
            return 0
        if wheelhouse is None or not wheelhouse.is_dir():
            raise ManagedInstallationError("installation_wheelhouse_required", "需要明确的本地依赖 wheel 目录")
        found: set[str] = set()
        expanded = 0
        try:
            for wheel in sorted(wheelhouse.glob("*.whl")):
                if wheel.is_symlink() or not wheel.is_file():
                    raise ValueError("nonregular dependency wheel")
                digest = file_sha256(wheel)
                packages = {name for name, hashes in expected.items() if digest in hashes}
                if not packages:
                    continue
                with ZipFile(wheel) as archive:
                    entries = archive.infolist()
                    size = sum(entry.file_size for entry in entries)
                    if len(entries) > 20000 or size > 2 * 1024 ** 3:
                        raise ValueError("dependency expansion limit")
                    expanded += size
                found.update(packages)
        except (OSError, ValueError, BadZipFile) as error:
            raise ManagedInstallationError("installation_dependencies_invalid", "本地依赖 wheel 不是可核验的受限归档") from error
        if found != set(expected):
            raise ManagedInstallationError("installation_dependencies_missing", "本地 wheel 目录缺少锁定依赖", details={"packages": sorted(set(expected) - found)})
        return expanded

    @staticmethod
    def _run(command: list[str], *, cwd: Path, timeout: float = 600, log_root: Path | None = None, check: bool = True) -> ProcessResult:
        environment = _environment()
        run_root = None
        if log_root is not None:
            _ordinary_install_path(log_root, directory=True)
            log_root.mkdir(parents=True, exist_ok=True)
            run_root = log_root / uuid.uuid4().hex
            run_root.mkdir()
            temporary = run_root / "temporary"
            temporary.mkdir()
            environment.update({key: str(temporary) for key in ("TMP", "TEMP", "TMPDIR")})
        try:
            result = run_process(command, cwd=cwd,
                policy=ProcessPolicy.exact("strixnova-managed-installation-v1", "执行明确选择的本地安装或运行检查", command),
                limits=ProcessLimits(timeout_seconds=timeout), env=environment)
        except ProcessExecutionError as error:
            raise ManagedInstallationError("installation_process_blocked", str(error), details={"reason": error.reason}) from error
        if run_root is not None:
            (run_root / "stdout.log").write_bytes(result.stdout)
            (run_root / "stderr.log").write_bytes(result.stderr)
            write_maintenance_json(run_root / "receipt.json", {"command": command, "exit_code": result.exit_code, "duration_seconds": result.duration_seconds, "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(), "stderr_sha256": hashlib.sha256(result.stderr).hexdigest()})
        if check and result.exit_code != 0:
            raise ManagedInstallationError("installation_command_failed", "安装或实际运行检查失败", details={"exit_code": result.exit_code, "stderr": result.stderr_text()[-3000:], "stdout": result.stdout_text()[-1000:]})
        return result

    @staticmethod
    def probe(python_path: str | Path) -> dict[str, Any]:
        python = Path(python_path).expanduser().resolve()
        if not python.is_file():
            raise ManagedInstallationError("installation_python_missing", "指定解释器不存在")
        result = ManagedInstallation._run([str(python), "-I", "-B", "-X", "utf8", "-c", _PROBE], cwd=python.parent, timeout=30)
        try:
            value = json.loads(result.stdout)
            if value["python_version"] != [3, 12] or (value["authority_format"] != AUTHORITY_FORMAT or value["activity_format"] != ACTIVITY_FORMAT) or not value["entrypoint_sha256"]:
                raise ValueError
            if not (Path(value["skill_path"]) / "SKILL.md").is_file():
                raise ValueError
            return value
        except (ValueError, KeyError, TypeError) as error:
            raise ManagedInstallationError("installed_runtime_invalid", "实际程序、Python、原生入口或配套 Skill 不满足受支持运行合同") from error

    def _validate_root(self, *, create: bool = False) -> None:
        _ordinary_install_path(self.root, directory=True)
        for path in (self.root, self.root / "versions", self.root / "active.json", self.root / "owner.json"):
            if path.is_symlink() or path.is_junction():
                raise ManagedInstallationError("installation_path_unsafe", "受管安装位置不能是链接")
        if self.root.exists() and not self.root.is_dir():
            raise ManagedInstallationError("installation_path_occupied", "安装根不是目录")
        owner = self.root / "owner.json"
        if owner.exists():
            try:
                value = json.loads(owner.read_text(encoding="utf-8"))
                if value != {"schema_version": "strixnova.installation-owner.v1", "project": str(self.project)}:
                    raise ValueError
            except (OSError, ValueError, TypeError) as error:
                raise ManagedInstallationError("installation_owner_mismatch", "该安装根不属于当前项目") from error
        elif self.root.exists() and any(self.root.iterdir()):
            raise ManagedInstallationError("installation_path_occupied", "不接管没有所有权记录的非空安装目录")
        elif create:
            self.root.mkdir(parents=True, exist_ok=True)
            with owner.open("x", encoding="utf-8", newline="\n") as output:
                json.dump({"schema_version": "strixnova.installation-owner.v1", "project": str(self.project)}, output, ensure_ascii=False, sort_keys=True)
                output.flush()
                os.fsync(output.fileno())

    def active(self) -> dict[str, Any] | None:
        self._validate_root()
        path = self.root / "active.json"
        if not path.exists():
            return None
        try:
            if path.stat().st_size > 1024 * 1024:
                raise ValueError
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or set(value) != {"schema_version", "project", "upgrade_id", "runtime"} or value["schema_version"] != "strixnova.runtime-selection.v1" or value["project"] != str(self.project):
                raise ValueError
            runtime = value["runtime"]
            if not isinstance(value["upgrade_id"], str) or not value["upgrade_id"] or not isinstance(runtime, dict):
                raise ValueError
            if any(not isinstance(runtime.get(key), str) or not runtime[key] for key in ("python_path", "entrypoint", "build_sha256", "skill_sha256")):
                raise ValueError
            if type(runtime.get("authority_format")) is not int or runtime["authority_format"] != AUTHORITY_FORMAT or type(runtime.get("activity_format")) is not int or runtime["activity_format"] != ACTIVITY_FORMAT:
                raise ValueError
            return value
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ManagedInstallationError("installation_selection_invalid", "当前运行选择损坏") from error

    def plan(
        self, wheel: str | Path, *, source_python: str | Path | None = None,
        builder_python: str | Path | None = None, wheelhouse: str | Path | None = None,
    ) -> dict[str, Any]:
        self._validate_root()
        target = self.inspect(wheel)
        previous = self.active()
        source = self.probe(source_python or (previous["runtime"]["python_path"] if previous else sys.executable))
        if previous and previous["runtime"] != source:
            raise ManagedInstallationError("installation_source_mismatch", "源运行程序必须与当前受管选择一致")
        builder = Path(builder_python or sys.executable).expanduser().resolve()
        if not builder.is_file():
            raise ManagedInstallationError("installation_python_missing", "创建隔离环境的解释器不存在")
        builder_info = self._run([str(builder), "-I", "-B", "-S", "-c", "import json,sys; print(json.dumps(list(sys.version_info[:2])))"], cwd=self.project, timeout=30)
        if json.loads(builder_info.stdout) != [3, 12]:
            raise ManagedInstallationError("installation_python_unsupported", "目标环境必须使用 Python 3.12")
        wheelhouse_path = Path(wheelhouse).expanduser().resolve() if wheelhouse is not None else None
        if wheelhouse_path is not None and not wheelhouse_path.is_dir():
            raise ManagedInstallationError("installation_wheelhouse_missing", "本地依赖 wheel 目录不存在")
        dependencies = {}
        if wheelhouse_path:
            for path in sorted(wheelhouse_path.glob("*.whl")):
                if path.is_symlink():
                    raise ManagedInstallationError("installation_path_unsafe", "依赖 wheel 不能是链接")
                dependencies[path.name] = file_sha256(path)
        with ZipFile(Path(target["wheel_path"])) as archive:
            requirements = json.loads(archive.read("strixnova/resources/" + COMPATIBILITY_RESOURCE))["dependency_lock"]["requirements"]
        expanded_dependencies = self._dependency_space(wheelhouse_path, requirements)
        return {
            "schema_version": "strixnova.managed-installation-plan.v1", "installation_root": str(self.root),
            "target": target, "source_runtime": source, "previous_selection": previous,
            "builder_python": str(builder), "builder_sha256": file_sha256(builder),
            "required_storage_bytes": 128 * 1024 * 1024 + 3 * (target["unpacked_size_bytes"] + expanded_dependencies),
            "wheelhouse": str(wheelhouse_path) if wheelhouse_path else None, "dependency_wheels": dependencies,
            "request": {"installation_root": str(self.root), "target_wheel": str(Path(wheel).expanduser().resolve()), "source_python": source["python_path"], "builder_python": str(builder), "wheelhouse": str(wheelhouse_path) if wheelhouse_path else None},
        }

    @_installation_write
    def prepare(
        self, target: dict[str, Any], *, builder_python: str | Path | None = None,
        wheelhouse: str | Path | None = None,
    ) -> dict[str, Any]:
        if not isinstance(target, dict) or self.inspect(target.get("wheel_path", "")) != target:
            raise ManagedInstallationError("installation_target_changed", "目标 wheel 自预检后已经改变")
        wheel = Path(target["wheel_path"])
        with ZipFile(wheel) as archive:
            contract = validate_compatibility(json.loads(archive.read("strixnova/resources/" + COMPATIBILITY_RESOURCE)))
        requirements = contract["dependency_lock"]["requirements"]
        has_dependencies = any(line.strip() and not line.lstrip().startswith("#") for line in requirements.splitlines())
        wheelhouse_path = Path(wheelhouse).expanduser().resolve() if wheelhouse is not None else None
        if has_dependencies and (wheelhouse_path is None or not wheelhouse_path.is_dir()):
            raise ManagedInstallationError("installation_wheelhouse_required", "需要本地依赖 wheel 目录；安装过程不自动访问包索引")
        expanded_dependencies = self._dependency_space(wheelhouse_path, requirements)
        builder = Path(builder_python or sys.executable).expanduser().resolve()
        if not builder.is_file():
            raise ManagedInstallationError("installation_python_missing", "隔离环境创建解释器不存在")
        self._validate_root(create=True)
        directory = self.root / "versions" / target["wheel_sha256"]
        if directory.is_symlink() or directory.is_junction():
            raise ManagedInstallationError("installation_path_unsafe", "目标安装不能是链接")
        marker = directory / "installation.json"
        _ordinary_install_path(marker)
        owner = {"schema_version": "strixnova.prepared-installation.v1", "target": target, "project": str(self.project)}
        if directory.exists():
            try:
                old = json.loads(marker.read_text(encoding="utf-8"))
                if any(old.get(key) != value for key, value in owner.items()):
                    raise ValueError
                if old.get("state") == "ready":
                    if self.probe(old["runtime"]["python_path"]) != old["runtime"]:
                        raise ManagedInstallationError("installed_runtime_changed", "已准备的程序或 Skill 已变化")
                    return old
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise ManagedInstallationError("installation_path_occupied", "目标安装目录没有匹配的创建记录") from error
        else:
            directory.mkdir(parents=True)
            write_maintenance_json(marker, {**owner, "state": "preparing"})
        if shutil.disk_usage(self.root).free < 128 * 1024 * 1024 + 3 * (target["unpacked_size_bytes"] + expanded_dependencies):
            raise ManagedInstallationError("installation_space_insufficient", "准备隔离安装的可用空间不足")
        environment = directory / "venv"
        if environment.is_symlink() or environment.is_junction():
            raise ManagedInstallationError("installation_path_unsafe", "虚拟环境不能是链接")
        logs = directory / "logs"
        _ordinary_install_path(directory / "requirements.txt")
        for relative in ("Scripts", "Lib", "Lib/site-packages", "Lib/site-packages/strixnova") if os.name == "nt" else ("bin", "lib"):
            _ordinary_install_path(environment / relative, directory=True)
        self._run([str(builder), "-I", "-m", "venv", str(environment)], cwd=directory, log_root=logs)
        python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        lock = directory / "requirements.txt"
        lock.write_text(requirements, encoding="utf-8", newline="")
        if has_dependencies:
            self._run([str(python), "-I", "-m", "pip", "install", "--no-cache-dir", "--no-index", "--only-binary=:all:", "--require-hashes", "--find-links", str(wheelhouse_path), "-r", str(lock)], cwd=directory, log_root=logs)
        self._run([str(python), "-I", "-m", "pip", "install", "--no-cache-dir", "--no-index", "--no-deps", str(wheel)], cwd=directory, log_root=logs)
        self._run([str(python), "-I", "-m", "pip", "check"], cwd=directory, log_root=logs)
        runtime = self.probe(python)
        for key in ("version", "build_sha256", "skill_sha256"):
            if runtime[key] != target[key]:
                raise ManagedInstallationError("installed_runtime_mismatch", "实际程序或配套 Skill 与目标 wheel 不一致")
        if runtime["authority_format"] != target["formats"]["authority"]:
            raise ManagedInstallationError("installed_runtime_mismatch", "实际程序的格式支持与目标声明不一致")
        ready = {**owner, "state": "ready", "runtime": runtime, "logs_directory": str(logs)}
        write_maintenance_json(marker, ready)
        return ready

    @_installation_write
    def select(self, runtime: dict[str, Any], *, upgrade_id: str, expected: dict[str, Any] | None) -> dict[str, Any]:
        self._validate_root(create=True)
        if self.active() != expected:
            raise ManagedInstallationError("installation_selection_changed", "当前运行选择自预检后已经变化")
        if self.probe(runtime["python_path"]) != runtime:
            raise ManagedInstallationError("installed_runtime_changed", "待选择的程序或 Skill 已变化")
        selection = {"schema_version": "strixnova.runtime-selection.v1", "project": str(self.project), "upgrade_id": upgrade_id, "runtime": runtime}
        write_maintenance_json(self.root / "active.json", selection)
        return selection

    def run(self, arguments: list[str], *, timeout: float = 3600) -> ProcessResult:
        selected = self.active()
        if selected is None:
            raise ManagedInstallationError("installation_not_selected", "尚未选择实际运行版本")
        runtime = selected["runtime"]
        if self.probe(runtime["python_path"]) != runtime:
            raise ManagedInstallationError("installed_runtime_changed", "当前运行程序或配套 Skill 已变化")
        command_arguments = list(arguments)
        for index, argument in enumerate(arguments):
            value = arguments[index + 1] if argument == "--project-dir" and index + 1 < len(arguments) else argument.split("=", 1)[1] if argument.startswith("--project-dir=") else None
            if value is None:
                continue
            project = Path(value).expanduser().resolve()
            if project != self.project:
                raise ManagedInstallationError("installation_project_mismatch", "受管运行入口不能代替其他项目选择版本")
            # The child runs in self.project, so pass the absolute path that
            # was validated in the caller's directory.
            if argument == "--project-dir":
                command_arguments[index + 1] = str(project)
            else:
                command_arguments[index] = "--project-dir=" + str(project)
        scope = nullcontext() if arguments and arguments[0] == "upgrade" else project_operation(self.project, writer_format=runtime["authority_format"], activity_format=runtime["activity_format"])
        with scope:
            return self._run([runtime["entrypoint"], *command_arguments], cwd=self.project, timeout=timeout, check=False)

    def validate_project(self, runtime: dict[str, Any], *, upgrade_id: str, expected_snapshot_sha256: str) -> dict[str, Any]:
        """Exercise the actual selected console entry before ending maintenance."""
        command = [runtime["entrypoint"], "upgrade", "validate", "--project-dir", str(self.project), "--upgrade-id", upgrade_id]
        result = self._run(command, cwd=self.project, timeout=60)
        try:
            envelope = json.loads(result.stdout)
            validation = envelope["validation"]
            if envelope.get("ok") is not True or validation["project"] != str(self.project) or validation["upgrade_id"] != upgrade_id:
                raise ValueError
            if validation["build_sha256"] != runtime["build_sha256"] or validation["skill_sha256"] != runtime["skill_sha256"] or validation["database_snapshot_sha256"] != expected_snapshot_sha256:
                raise ValueError
        except (ValueError, KeyError, TypeError) as error:
            raise ManagedInstallationError("installation_trial_invalid", "目标原生入口未返回匹配的项目试读结果") from error
        return {**validation, "actual_entrypoint": runtime["entrypoint"], "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(), "exit_code": result.exit_code}
