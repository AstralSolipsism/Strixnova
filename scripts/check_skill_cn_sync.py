"""Validate the review-only Chinese mirror of the packaged Strixnova Skill.

The check proves source-byte synchronization, complete file mapping, and
preservation of mechanically important tokens. It deliberately does not claim
that the Chinese prose is a semantically correct translation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from typing import Iterable

try:
    from scripts.skill_bundle_manifest import (
        SkillBundleManifestError,
        content_manifest,
    )
except ModuleNotFoundError:  # Direct ``python scripts/check_skill_cn_sync.py``.
    from skill_bundle_manifest import (
        SkillBundleManifestError,
        content_manifest,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = (
    REPOSITORY_ROOT
    / "strixnova"
    / "src"
    / "strixnova"
    / "resources"
    / "agent-skill"
    / "strixnova"
)
REVIEW_ROOT = REPOSITORY_ROOT / "skills-cn" / "strixnova"
MANIFEST_NAME = "sync-manifest.v1.json"
MANIFEST_SCHEMA = "strixnova.skill-cn-sync-manifest.v1"


class SkillCnSyncError(RuntimeError):
    """The review mirror is absent, stale, runnable, or structurally unsafe."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_files(source_root: Path) -> list[str]:
    return sorted(
        path.relative_to(source_root).as_posix()
        for path in source_root.rglob("*")
        if path.is_file()
    )


def review_path_for(source: str) -> str:
    path = PurePosixPath(source)
    if source == "SKILL.md":
        return "strixnova.zh-CN.md"
    if source == "agents/openai.yaml":
        return "agents/openai.zh-CN.md"
    if path.parent == PurePosixPath("references") and path.suffix == ".md":
        return f"references/{path.stem}.zh-CN.md"
    raise SkillCnSyncError(f"没有安全的中文审阅映射规则：{source}")


def _technical_tokens(text: str) -> list[str]:
    candidates: set[str] = set()
    patterns = (
        r"strixnova\.[a-z0-9][a-z0-9._-]*\.v[0-9]+",
        r"strixnova(?:[ \t]+[a-z][a-z0-9-]*)+",
        r"--[a-z][a-z0-9-]*",
        r"\b[A-Z][A-Z0-9]+(?:-[A-Z0-9<> ]+)+\b",
        r"\b[a-z][a-z0-9]*(?:_[a-z0-9]+){2,}\b",
        r"[a-z0-9-]+(?:-v[0-9]+)?\.schema\.json",
    )
    for pattern in patterns:
        candidates.update(re.findall(pattern, text))
    for value in re.findall(r"`([^`\r\n]{1,96})`", text):
        if (
            value.startswith(("strixnova", "--", "@"))
            or "_" in value
            or value.endswith((".json", ".yaml"))
            or re.fullmatch(r"[a-z][a-z0-9-]+", value)
        ):
            candidates.add(value)
    return sorted(candidates)


def _safe_file(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SkillCnSyncError(f"同步清单包含不安全相对路径：{relative}")
    target = root.joinpath(*path.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise SkillCnSyncError(f"同步路径越出根目录：{relative}") from error
    return target


def _manifest_entries(source_root: Path) -> list[dict[str, str]]:
    return [
        {
            "source": source,
            "review": review_path_for(source),
            "source_sha256": _sha256(_safe_file(source_root, source)),
        }
        for source in _source_files(source_root)
    ]


def _manifest_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def refresh_manifest(
    *,
    source_root: Path = SOURCE_ROOT,
    review_root: Path = REVIEW_ROOT,
) -> Path:
    """Refresh hashes only after the human-readable mirror files already exist."""

    source_root = source_root.resolve()
    review_root = review_root.resolve()
    entries = _manifest_entries(source_root)
    missing = [
        entry["review"]
        for entry in entries
        if not _safe_file(review_root, entry["review"]).is_file()
    ]
    if missing:
        raise SkillCnSyncError("刷新前缺少中文审阅文件：" + ", ".join(missing))
    review_root.mkdir(parents=True, exist_ok=True)
    target = review_root / MANIFEST_NAME
    target.write_text(
        json.dumps(
            {
                "schema_version": MANIFEST_SCHEMA,
                "source_root": _manifest_path(source_root),
                "review_root": _manifest_path(review_root),
                "files": entries,
                "semantic_translation_machine_proven": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return target


def validate_skill_cn_sync(
    *,
    source_root: Path = SOURCE_ROOT,
    review_root: Path = REVIEW_ROOT,
) -> dict[str, object]:
    source_root = source_root.resolve()
    review_root = review_root.resolve()
    manifest_path = review_root / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SkillCnSyncError("中文审阅同步清单缺失或不是有效 UTF-8 JSON") from error
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version",
        "source_root",
        "review_root",
        "files",
        "semantic_translation_machine_proven",
    }:
        raise SkillCnSyncError("中文审阅同步清单字段不完整或包含未知字段")
    if (
        manifest.get("schema_version") != MANIFEST_SCHEMA
        or manifest.get("semantic_translation_machine_proven") is not False
    ):
        raise SkillCnSyncError("中文审阅同步清单版本或语义证明边界无效")
    if manifest.get("source_root") != _manifest_path(
        source_root
    ) or manifest.get("review_root") != _manifest_path(review_root):
        raise SkillCnSyncError("中文审阅同步清单绑定了错误的正式源或审阅目录")
    entries = manifest.get("files")
    if not isinstance(entries, list) or any(
        not isinstance(entry, dict)
        or set(entry) != {"source", "review", "source_sha256"}
        for entry in entries
    ):
        raise SkillCnSyncError("中文审阅同步清单 files 结构无效")
    expected_sources = _source_files(source_root)
    actual_sources = [str(entry["source"]) for entry in entries]
    if actual_sources != expected_sources or len(set(actual_sources)) != len(
        actual_sources
    ):
        raise SkillCnSyncError("中文审阅同步清单没有逐文件覆盖正式 Skill")
    expected_reviews = [review_path_for(source) for source in expected_sources]
    actual_reviews = [str(entry["review"]) for entry in entries]
    if actual_reviews != expected_reviews or len(set(actual_reviews)) != len(
        actual_reviews
    ):
        raise SkillCnSyncError("中文审阅文件映射不唯一或不符合非运行目录规则")
    present_reviews = sorted(
        path.relative_to(review_root).as_posix()
        for path in review_root.rglob("*")
        if path.is_file() and path.name != MANIFEST_NAME
    )
    if present_reviews != sorted(expected_reviews):
        raise SkillCnSyncError("中文审阅目录存在缺失或未登记文件")
    for path in review_root.rglob("*"):
        if not path.is_file():
            continue
        if path.name.casefold() == "skill.md" or path.suffix.casefold() in {
            ".yaml",
            ".yml",
        }:
            raise SkillCnSyncError(f"中文审阅目录不得形成可运行 Skill：{path}")

    token_count = 0
    source_contents: dict[str, bytes] = {}
    for entry in entries:
        source = _safe_file(source_root, str(entry["source"]))
        review = _safe_file(review_root, str(entry["review"]))
        if not source.is_file() or not review.is_file():
            raise SkillCnSyncError(f"同步文件缺失：{entry}")
        source_content = source.read_bytes()
        actual_hash = hashlib.sha256(source_content).hexdigest()
        if entry["source_sha256"] != actual_hash:
            raise SkillCnSyncError(
                f"正式 Skill 已变化但中文审阅映射未同步：{entry['source']}"
            )
        try:
            source_text = source_content.decode("utf-8")
        except UnicodeError as error:
            raise SkillCnSyncError(
                f"正式 Skill 不是有效 UTF-8：{entry['source']}"
            ) from error
        review_text = review.read_text(encoding="utf-8")
        missing_tokens = [
            token
            for token in _technical_tokens(source_text)
            if token not in review_text
        ]
        if missing_tokens:
            raise SkillCnSyncError(
                f"中文审阅文件遗漏受保护合同 token：{entry['review']} -> "
                + ", ".join(missing_tokens)
            )
        token_count += len(_technical_tokens(source_text))
        source_contents[str(entry["source"])] = source_content
    try:
        skill_manifest = content_manifest(source_contents)
    except SkillBundleManifestError as error:
        raise SkillCnSyncError(str(error)) from error
    return {
        "schema_version": "strixnova.skill-cn-sync-check.v1",
        "status": "valid",
        "file_count": len(entries),
        "skill_bundle_manifest_sha256": skill_manifest["sha256"],
        "protected_token_count": token_count,
        "semantic_translation_machine_proven": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="核验正式 Strixnova Skill 与中文审阅映射的同步边界。"
    )
    parser.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="在中文审阅文本已人工同步后刷新正式源文件散列。",
    )
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        if options.refresh_manifest:
            refresh_manifest()
        result = validate_skill_cn_sync()
    except (SkillCnSyncError, OSError, ValueError) as error:
        print(str(error))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
