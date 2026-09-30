"""Narrow, formatting-preserving YAML metadata edits.

Project authorities are human-authored documents.  Mechanical adoption may
change a few declared metadata values, but it must not re-serialize unrelated
prose, comments, ordering, quoting, or line endings.  This module locates exact
YAML value nodes, replaces only those spans, and writes atomically beside the
target file.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import hashlib
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Any

import yaml
from yaml.nodes import MappingNode, Node, SequenceNode

from strixnova.git_project_reader import (
    GitProjectReaderError,
    repository_relative_path,
)


class YamlMetadataPatchError(ValueError):
    """One requested metadata path could not be edited safely."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "project_metadata_patch_failed",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


YAML_PATCH_TRANSACTION_SCHEMA = "strixnova.yaml-patch-transaction.v1"


def _node_at(root: Node, path: Sequence[str | int]) -> tuple[Node, int | None]:
    current = root
    final_key_end: int | None = None
    walked: list[str] = []
    for part in path:
        walked.append(str(part))
        if isinstance(part, str) and isinstance(current, MappingNode):
            match = next(
                (
                    (key_node, value_node)
                    for key_node, value_node in current.value
                    if getattr(key_node, "value", None) == part
                ),
                None,
            )
            if match is None:
                raise YamlMetadataPatchError(
                    "YAML 元数据路径不存在：" + ".".join(walked)
                )
            key_node, current = match
            final_key_end = key_node.end_mark.index
            continue
        if (
            isinstance(part, int)
            and isinstance(current, SequenceNode)
            and 0 <= part < len(current.value)
        ):
            current = current.value[part]
            final_key_end = None
            continue
        raise YamlMetadataPatchError(
            "YAML 元数据路径类型不匹配：" + ".".join(walked)
        )
    return current, final_key_end


def _yaml_inline(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    except (TypeError, ValueError) as error:
        raise YamlMetadataPatchError("YAML 元数据值不能安全序列化") from error


def atomic_write_bytes(path: str | Path, content: bytes) -> None:
    """Replace one exact file atomically without widening its directory scope."""

    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = (
        stat.S_IMODE(target.stat().st_mode) if target.exists() else None
    )
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.",
        suffix=".tmp",
        dir=target.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            if existing_mode is not None:
                os.chmod(temporary, existing_mode)
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def render_yaml_value_patches(
    original: bytes,
    replacements: Mapping[tuple[str | int, ...], Any],
) -> bytes:
    """Return exact YAML bytes with only the selected value nodes replaced."""

    has_bom = original.startswith(b"\xef\xbb\xbf")
    try:
        text = original.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise YamlMetadataPatchError("YAML 内容必须是 UTF-8") from error
    try:
        root = yaml.compose(text)
    except yaml.YAMLError as error:
        raise YamlMetadataPatchError("YAML 内容无法解析") from error
    if root is None:
        raise YamlMetadataPatchError("YAML 内容不能为空")

    spans: list[tuple[int, int, str]] = []
    for raw_path, value in replacements.items():
        metadata_path = tuple(raw_path)
        if not metadata_path:
            raise YamlMetadataPatchError("YAML 元数据路径不能为空")
        node, key_end = _node_at(root, metadata_path)
        start = node.start_mark.index
        end = node.end_mark.index
        same_line_prefix = ""
        if key_end is not None and "\n" in text[key_end:start]:
            colon = text.find(":", key_end, start)
            if colon < 0:
                raise YamlMetadataPatchError(
                    "YAML 元数据映射缺少分隔符：" + ".".join(map(str, metadata_path))
                )
            start = colon + 1
            same_line_prefix = " "
        original_span = text[start:end]
        trailing = re.search(r"(\r?\n[ \t]*)$", original_span)
        replacement = same_line_prefix + _yaml_inline(value)
        if trailing is not None:
            replacement += trailing.group(1)
        spans.append((start, end, replacement))
    spans.sort(reverse=True)
    previous_start = len(text) + 1
    updated = text
    for start, end, replacement in spans:
        if end > previous_start:
            raise YamlMetadataPatchError("YAML 元数据替换范围发生重叠")
        updated = updated[:start] + replacement + updated[end:]
        previous_start = start
    try:
        yaml.safe_load(updated)
    except yaml.YAMLError as error:
        raise YamlMetadataPatchError("YAML 元数据替换后无法回读") from error
    encoded = updated.encode("utf-8")
    if has_bom:
        encoded = b"\xef\xbb\xbf" + encoded
    return encoded


def _transaction_target(project: Path, relative_path: str) -> Path:
    try:
        normalized = repository_relative_path(
            relative_path,
            "YAML 事务路径",
        )
    except GitProjectReaderError as error:
        raise YamlMetadataPatchError(
            str(error),
            code="yaml_transaction_path_unsafe",
            details=error.details,
        ) from error
    for ancestor in (project.absolute(), *project.absolute().parents):
        if ancestor.is_symlink() or ancestor.is_junction():
            raise YamlMetadataPatchError("YAML 事务根目录不得经过链接", code="yaml_transaction_path_unsafe")
    project = project.resolve()
    candidate = project
    for part in normalized.split("/"):
        candidate = candidate / part
        if candidate.is_symlink() or candidate.is_junction():
            raise YamlMetadataPatchError(
                f"YAML 事务路径不得经过符号链接：{normalized}",
                code="yaml_transaction_path_unsafe",
                details={"path": normalized},
            )
    try:
        target = candidate.resolve()
        target.relative_to(project)
    except (OSError, RuntimeError, ValueError) as error:
        raise YamlMetadataPatchError(
            "YAML 事务路径不得离开项目目录",
            code="yaml_transaction_path_unsafe",
        ) from error
    return target


def build_yaml_patch_transaction(
    project_dir: str | Path,
    updates: Mapping[str | tuple[str | None, str], Mapping[tuple[str | int, ...], Any]],
    *, repository_roots: Mapping[str | None, str | Path] | None = None,
) -> dict[str, Any]:
    """Freeze deterministic metadata edits before any file is changed.

    The durable record contains only repository-relative paths, exact before
    and after hashes, and narrow scalar replacements.  It never stores whole
    authority documents in workflow state.
    """

    project = Path(project_dir).resolve()
    roots = {identifier: Path(root).absolute() for identifier, root in (repository_roots or {None: project}).items()}
    entries: list[dict[str, Any]] = []
    seen_targets: set[str] = set()
    for key in sorted(updates, key=str):
        identifier, relative_path = key if isinstance(key, tuple) else (None, key)
        if identifier not in roots:
            raise YamlMetadataPatchError("YAML 事务目标仓库没有明确绑定", code="yaml_transaction_repository_missing")
        target = _transaction_target(roots[identifier], relative_path)
        target_identity = os.path.normcase(str(target))
        if target_identity in seen_targets:
            raise YamlMetadataPatchError(
                "YAML 元数据事务文件路径指向同一目标",
                code="yaml_transaction_path_duplicate",
            )
        seen_targets.add(target_identity)
        try:
            original = target.read_bytes()
        except OSError as error:
            raise YamlMetadataPatchError(
                f"无法读取 YAML 事务文件：{relative_path}"
            ) from error
        replacements = updates[key]
        updated = render_yaml_value_patches(original, replacements)
        serialized = [
            {"path": list(metadata_path), "value": value}
            for metadata_path, value in sorted(
                replacements.items(),
                key=lambda item: tuple(str(part) for part in item[0]),
            )
        ]
        entries.append(
            {
                "path": relative_path,
                "repository_id": identifier,
                "root_path": str(roots[identifier].resolve()),
                "before_sha256": hashlib.sha256(original).hexdigest(),
                "after_sha256": hashlib.sha256(updated).hexdigest(),
                "replacements": serialized,
            }
        )
    return {
        "schema_version": YAML_PATCH_TRANSACTION_SCHEMA,
        "entries": entries,
    }


def apply_yaml_patch_transaction(
    project_dir: str | Path,
    transaction: Mapping[str, Any],
    *, repository_roots: Mapping[str | None, str | Path] | None = None,
) -> dict[Path, bytes]:
    """Idempotently finish a previously frozen metadata transaction.

    Every file must still be either the exact pre-write body or the exact
    intended post-write body.  This permits restart recovery after any atomic
    per-file replacement while refusing unrelated edits.
    """

    if transaction.get("schema_version") != YAML_PATCH_TRANSACTION_SCHEMA:
        raise YamlMetadataPatchError("YAML 元数据事务版本无效")
    raw_entries = transaction.get("entries")
    if not isinstance(raw_entries, list):
        raise YamlMetadataPatchError("YAML 元数据事务缺少文件清单")
    project = Path(project_dir).resolve()
    roots = {identifier: Path(root).absolute() for identifier, root in (repository_roots or {None: project}).items()}
    originals: dict[Path, bytes] = {}
    prepared: list[tuple[Path, bytes, bytes]] = []
    seen_targets: set[str] = set()
    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, Mapping):
            raise YamlMetadataPatchError(
                f"YAML 元数据事务 entries[{index}] 必须是对象"
            )
        relative_path = raw_entry.get("path")
        if not isinstance(relative_path, str):
            raise YamlMetadataPatchError(
                "YAML 元数据事务文件路径重复或无效",
                code="yaml_transaction_path_duplicate",
            )
        identifier = raw_entry.get("repository_id")
        if identifier not in roots or str(roots[identifier].resolve()) != raw_entry.get("root_path"):
            raise YamlMetadataPatchError("YAML 事务恢复绑定与原目标仓库位置不一致", code="yaml_transaction_repository_changed")
        root = roots[identifier]
        target = _transaction_target(root, relative_path)
        target_identity = os.path.normcase(str(target))
        if target_identity in seen_targets:
            raise YamlMetadataPatchError(
                "YAML 元数据事务文件路径重复或无效",
                code="yaml_transaction_path_duplicate",
            )
        seen_targets.add(target_identity)
        try:
            current = target.read_bytes()
        except OSError as error:
            raise YamlMetadataPatchError(
                f"无法读取 YAML 事务文件：{relative_path}"
            ) from error
        current_sha256 = hashlib.sha256(current).hexdigest()
        before_sha256 = str(raw_entry.get("before_sha256") or "")
        after_sha256 = str(raw_entry.get("after_sha256") or "")
        if current_sha256 == after_sha256:
            continue
        if current_sha256 != before_sha256:
            raise YamlMetadataPatchError(
                f"YAML 元数据事务文件在恢复期间发生未授权变化：{relative_path}"
            )
        raw_replacements = raw_entry.get("replacements")
        if not isinstance(raw_replacements, list):
            raise YamlMetadataPatchError("YAML 元数据事务替换清单无效")
        replacements: dict[tuple[str | int, ...], Any] = {}
        for raw_replacement in raw_replacements:
            if (
                not isinstance(raw_replacement, Mapping)
                or not isinstance(raw_replacement.get("path"), list)
                or not raw_replacement["path"]
                or any(
                    not isinstance(part, (str, int)) or isinstance(part, bool)
                    for part in raw_replacement["path"]
                )
            ):
                raise YamlMetadataPatchError("YAML 元数据事务替换路径无效")
            metadata_path = tuple(raw_replacement["path"])
            if metadata_path in replacements:
                raise YamlMetadataPatchError("YAML 元数据事务替换路径重复")
            replacements[metadata_path] = raw_replacement.get("value")
        updated = render_yaml_value_patches(current, replacements)
        if hashlib.sha256(updated).hexdigest() != after_sha256:
            raise YamlMetadataPatchError(
                f"YAML 元数据事务目标散列无法重现：{relative_path}"
            )
        prepared.append((target, current, updated))
    try:
        for target, original, updated in prepared:
            originals[target] = original
            atomic_write_bytes(target, updated)
    except Exception as error:
        rollback_failures: list[str] = []
        for target, original in reversed(list(originals.items())):
            try:
                atomic_write_bytes(target, original)
            except Exception:
                rollback_failures.append(target.as_posix())
        if rollback_failures:
            raise YamlMetadataPatchError(
                "YAML 元数据事务写入失败且回滚不完整："
                + "、".join(rollback_failures),
                code="yaml_transaction_rollback_incomplete",
                details={"paths": rollback_failures},
            ) from error
        raise YamlMetadataPatchError(
            "YAML 元数据事务写入失败，已恢复本次已写文件",
            code="yaml_transaction_write_failed_rolled_back",
        ) from error
    return originals


def restore_yaml_patch_originals(project_dir: str | Path, transaction: Mapping[str, Any], originals: Mapping[Path, bytes]) -> None:
    """Restore only this transaction's bytes; preserve intervening user edits."""
    entries = {}
    for entry in transaction.get("entries", []):
        root = Path(entry.get("root_path") or project_dir)
        entries[_transaction_target(root, entry["path"])] = entry
    for target, content in reversed(list(originals.items())):
        entry = entries.get(target)
        if entry is None or hashlib.sha256(content).hexdigest() != entry.get("before_sha256"):
            raise YamlMetadataPatchError("回滚内容不属于原事务", code="yaml_transaction_rollback_invalid")
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if current == entry["before_sha256"]:
            continue
        if current != entry["after_sha256"]:
            raise YamlMetadataPatchError("事务后文件已被其他操作修改，保留现场以便恢复", code="yaml_transaction_rollback_conflict")
        atomic_write_bytes(target, content)


__all__ = [
    "YamlMetadataPatchError",
    "YAML_PATCH_TRANSACTION_SCHEMA",
    "apply_yaml_patch_transaction",
    "atomic_write_bytes",
    "build_yaml_patch_transaction",
    "render_yaml_value_patches",
    "restore_yaml_patch_originals",
]
