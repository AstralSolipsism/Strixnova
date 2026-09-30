"""Initial installation using the existing per-project managed runtime.

This module and its import chain stay standard-library-only so the offline
entry can load it directly from the verified wheel before dependencies exist.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from strixnova.managed_installation import ManagedInstallation, ManagedInstallationError


def install_initial_runtime(
    project_dir: str | Path,
    installation_root: str | Path,
    wheel: str | Path,
    wheelhouse: str | Path,
    *,
    builder_python: str | Path,
    skills_dir: str | Path | None = None,
    replace_skill: bool = False,
) -> dict[str, Any]:
    manager = ManagedInstallation(installation_root, project_dir)
    if not manager.project.is_dir():
        raise ManagedInstallationError("installation_project_missing", "请先准备目标项目目录")
    target = manager.inspect(wheel)
    active = manager.active()
    unchanged = active is not None
    if active is not None:
        runtime = active["runtime"]
        if any(runtime[key] != target[key] for key in ("version", "build_sha256", "skill_sha256")):
            raise ManagedInstallationError(
                "installation_upgrade_required", "当前项目已有其他运行版本，请使用显式升级入口",
            )
        if manager.probe(runtime["python_path"]) != runtime:
            raise ManagedInstallationError("installed_runtime_changed", "当前运行文件已变化，请先诊断或恢复")
    else:
        def require_fresh_project() -> None:
            stores = ("authority.sqlite3", "delivery-activities.sqlite3")
            if any((manager.project / ".strixnova" / name).exists() for name in stores):
                raise ManagedInstallationError(
                    "installation_upgrade_required", "项目已有 Strixnova 数据；首装入口不转换已有数据，请使用显式升级入口",
                )

        require_fresh_project()
        prepared = manager.prepare(target, builder_python=builder_python, wheelhouse=wheelhouse)
        require_fresh_project()
        runtime = prepared["runtime"]
        manager.select(
            runtime, upgrade_id="INSTALL-" + target["wheel_sha256"][:24].upper(),
            expected=None,
        )
    copied = None
    if skills_dir is not None:
        args = ["setup-agent", "--skills-dir", str(Path(skills_dir).expanduser().absolute())]
        if replace_skill:
            args.append("--replace")
        response = manager.run(args)
        if response.exit_code != 0:
            raise ManagedInstallationError(
                "installation_skill_setup_failed",
                "运行环境已准备，Skill 复制未完成；保留安装，可按相同参数重试或处理 Skill 目录冲突",
                details={"runtime": runtime, "stdout": response.stdout_text(), "stderr": response.stderr_text()},
            )
        copied = json.loads(response.stdout)
    return {
        "schema_version": "strixnova.initial-installation.v1",
        "status": "unchanged" if unchanged else "installed",
        "project": str(manager.project), "installation_root": str(manager.root),
        "runtime": runtime, "skill_copy": copied,
        "host_load_required": True, "host_loaded_verified": False,
        "project_adoption_performed": False, "project_data_migrated": False,
        "system_python_modified": False,
    }
