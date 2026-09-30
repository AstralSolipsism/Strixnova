from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess


PROJECT = "PROJECT-1111111111111111"
OTHER_PROJECT = "PROJECT-2222222222222222"
FRONTEND = "REPO-1111111111111111"
BACKEND = "REPO-2222222222222222"
EXTERNAL = "REPO-3333333333333333"


def git(path: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=path, check=True, capture_output=True,
        text=True, encoding="utf-8", errors="strict",
    ).stdout.strip()


def repository(path: Path, content: bytes = b"sample\n", *, commit: bool = True) -> str | None:
    path.mkdir(parents=True)
    git(path, "init", "-b", "main")
    git(path, "config", "user.name", "Strixnova Context Test")
    git(path, "config", "user.email", "context@example.invalid")
    git(path, "config", "core.autocrlf", "false")
    (path / "same.txt").write_bytes(content)
    if not commit:
        return None
    git(path, "add", "--", "same.txt")
    git(path, "commit", "-m", "fixture")
    return git(path, "rev-parse", "HEAD")


def inspect_request(bindings: dict[str, str]) -> dict:
    return {
        "schema_version": "strixnova.project-context-inspect.v1",
        "declaration": {
            "project_id": PROJECT,
            "repositories": [
                {"repository_id": FRONTEND, "owner_project_id": PROJECT, "purpose": "前端"},
                {"repository_id": BACKEND, "owner_project_id": PROJECT, "purpose": "后端"},
            ],
        },
        "bindings": {
            "project_id": PROJECT,
            "management_root": "management-not-created",
            "repositories": [{"repository_id": key, "path": path} for key, path in bindings.items()],
        },
    }


def read_request(bindings: dict[str, str], repository_id: str = FRONTEND, *, ref: str | None = None) -> dict:
    value = inspect_request(bindings)
    value["schema_version"] = "strixnova.project-context-read.v1"
    value["reference"] = {"repository_id": repository_id, "path": "same.txt", "ref": ref}
    return value


def tree_bytes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*") if path.is_file()
    }
