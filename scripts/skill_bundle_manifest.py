"""Create metadata-independent fingerprints for an installed Strixnova Skill.

The manifest identifies a set of relative paths and their exact bytes.  It is
deliberately independent of wheel ZIP order, timestamps, compression, and other
archive metadata so that behavior evidence can be tied to Skill content without
pretending that two separately built wheel archives are the same artifact.
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Mapping
import hashlib
import json
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


MANIFEST_SCHEMA = "strixnova.skill-bundle-content-manifest.v1"
WHEEL_SKILL_PREFIX = "strixnova/resources/agent-skill/strixnova/"


class SkillBundleManifestError(RuntimeError):
    """The requested Skill content set cannot be fingerprinted safely."""


def _safe_relative_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or any(character in value for character in "\x00\r\n")
    ):
        raise SkillBundleManifestError(f"无效的 Skill 相对路径：{value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise SkillBundleManifestError(f"无效的 Skill 相对路径：{value!r}")
    return value


def content_manifest(files: Mapping[str, bytes]) -> dict[str, object]:
    """Fingerprint exact file bytes using a stable path-and-content envelope."""

    if not files:
        raise SkillBundleManifestError("Skill 内容清单不能为空")
    normalized: dict[str, bytes] = {}
    folded_paths: set[str] = set()
    for raw_path, content in files.items():
        path = _safe_relative_path(raw_path)
        if path.casefold() in folded_paths:
            raise SkillBundleManifestError(
                f"Skill 路径在大小写不敏感文件系统中冲突：{path}"
            )
        if not isinstance(content, bytes):
            raise SkillBundleManifestError(f"Skill 文件内容必须是 bytes：{path}")
        normalized[path] = content
        folded_paths.add(path.casefold())

    digest = hashlib.sha256()
    digest.update((MANIFEST_SCHEMA + "\n").encode("utf-8"))
    for path, content in sorted(normalized.items()):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(content).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return {
        "schema_version": MANIFEST_SCHEMA,
        "file_count": len(normalized),
        "sha256": digest.hexdigest(),
    }


def directory_manifest(
    root: Path,
    *,
    relative_paths: Iterable[str] | None = None,
) -> dict[str, object]:
    """Fingerprint all files, or one explicit dependency set, below ``root``."""

    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise SkillBundleManifestError(f"Skill 目录不存在：{root}")
    if relative_paths is None:
        paths = sorted(
            path.relative_to(resolved_root).as_posix()
            for path in resolved_root.rglob("*")
            if path.is_file()
        )
    else:
        if isinstance(relative_paths, (str, bytes)):
            raise SkillBundleManifestError("Skill 依赖路径必须是路径集合")
        paths = list(relative_paths)
        if len(paths) != len(set(paths)):
            raise SkillBundleManifestError("Skill 依赖路径不得重复")

    files: dict[str, bytes] = {}
    for raw_path in paths:
        relative = _safe_relative_path(raw_path)
        target = resolved_root.joinpath(*PurePosixPath(relative).parts).resolve()
        try:
            target.relative_to(resolved_root)
        except ValueError as error:
            raise SkillBundleManifestError(
                f"Skill 路径越出根目录：{relative}"
            ) from error
        if not target.is_file():
            raise SkillBundleManifestError(f"Skill 文件不存在：{relative}")
        files[relative] = target.read_bytes()
    return content_manifest(files)


def wheel_manifest(
    wheel_path: Path,
    *,
    prefix: str = WHEEL_SKILL_PREFIX,
) -> dict[str, object]:
    """Fingerprint bundled Skill bytes while ignoring ZIP container metadata."""

    files: dict[str, bytes] = {}
    folded_paths: set[str] = set()
    with ZipFile(wheel_path) as archive:
        for entry in archive.infolist():
            if entry.is_dir() or not entry.filename.startswith(prefix):
                continue
            relative = _safe_relative_path(entry.filename[len(prefix) :])
            if relative in files or relative.casefold() in folded_paths:
                raise SkillBundleManifestError(
                    f"wheel 中存在重复 Skill 路径：{relative}"
                )
            files[relative] = archive.read(entry)
            folded_paths.add(relative.casefold())
    return content_manifest(files)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="计算与目录或 wheel 容器元数据无关的 Strixnova Skill 内容指纹。"
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--directory", type=Path)
    source.add_argument("--wheel", type=Path)
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        result = (
            directory_manifest(options.directory)
            if options.directory is not None
            else wheel_manifest(options.wheel)
        )
    except (BadZipFile, OSError, SkillBundleManifestError) as error:
        print(str(error))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
