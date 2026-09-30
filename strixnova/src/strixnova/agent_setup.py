"""Install the packaged Strixnova Agent Skill without changing Agent settings."""

from __future__ import annotations

from datetime import datetime, timezone
from importlib.resources import as_file, files
import os
from pathlib import Path
import shutil
import uuid
from typing import Any


class AgentSetupError(Exception):
    """A typed, user-actionable Agent Skill installation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message


def default_skills_dir() -> Path:
    """Return Codex's conventional skills directory without creating it."""

    codex_home = os.environ.get("CODEX_HOME", "").strip()
    root = Path(codex_home).expanduser() if codex_home else Path.home() / ".codex"
    return root / "skills"


def _tree_contents(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _backup_path(target: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    candidate = target.with_name(f"{target.name}.backup-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = target.with_name(
            f"{target.name}.backup-{timestamp}-{counter}"
        )
        counter += 1
    return candidate


def install_agent_skill(
    *,
    skills_dir: Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Install the packaged Skill as ``<skills_dir>/strixnova``.

    Existing different content is never overwritten silently. With explicit
    replacement it is moved to a recoverable sibling backup first.
    """

    root = (skills_dir or default_skills_dir()).expanduser().resolve()
    target = root / "strixnova"
    source = files("strixnova.resources").joinpath("agent-skill", "strixnova")
    root.mkdir(parents=True, exist_ok=True)

    backup: Path | None = None
    temporary = root / f".strixnova-install-{uuid.uuid4().hex}"
    try:
        with as_file(source) as source_path:
            packaged = _tree_contents(source_path)
            if target.exists():
                if not target.is_dir():
                    raise AgentSetupError(
                        "skill_target_not_directory",
                        f"Skill 目标已存在且不是目录：{target}",
                    )
                if _tree_contents(target) == packaged:
                    return _result("unchanged", target, None)
                if not replace:
                    raise AgentSetupError(
                        "skill_already_exists",
                        (
                            f"Skill 目标已有不同内容：{target}；"
                            "如确认替换，请使用 --replace，原目录会先备份"
                        ),
                    )
            shutil.copytree(source_path, temporary)

        if target.exists():
            backup = _backup_path(target)
            target.replace(backup)
        temporary.replace(target)
    except AgentSetupError:
        raise
    except OSError as error:
        if backup is not None and backup.exists() and not target.exists():
            backup.replace(target)
            backup = None
        raise AgentSetupError(
            "skill_install_failed",
            f"无法安装 Strixnova Agent Skill：{error}",
        ) from error
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)

    return _result("replaced" if backup else "installed", target, backup)


def _result(
    status: str,
    target: Path,
    backup: Path | None,
) -> dict[str, Any]:
    return {
        "schema_version": "strixnova.agent-skill-install.v1",
        "status": status,
        "target_path": str(target),
        "backup_path": str(backup) if backup else None,
        "modifies_host_config": False,
        "installs_hooks": False,
        "installs_plugins": False,
        "issues_credentials": False,
    }
