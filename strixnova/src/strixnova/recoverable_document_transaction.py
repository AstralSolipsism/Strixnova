"""Crash-recoverable replacement of one related document set."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
import hashlib
import errno
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any
import uuid


TRANSACTION_SCHEMA = "strixnova.recoverable-document-transaction.v1"


class DocumentTransactionError(RuntimeError):
    """A transaction could not be safely applied or recovered."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _write_bytes(path: Path, content: bytes) -> None:
    with path.open("wb") as stream:
        stream.write(content)
        stream.flush()
        os.fsync(stream.fileno())


def _replace_file(source: Path, target: Path) -> None:
    """Keep the final rename on the target volume, including during rollback."""
    try:
        os.replace(source, target)
        return
    except OSError as error:
        if error.errno != errno.EXDEV and getattr(error, "winerror", None) != 17:
            raise
    with tempfile.NamedTemporaryFile(prefix="replacement-", suffix=".next", dir=target.parent, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(source.read_bytes())
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.chmod(temporary, source.stat().st_mode)
        os.replace(temporary, target)
        source.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _scoped_target(target: Path, root: Path, allowed_targets: set[Path] | None) -> Path:
    absolute = target.absolute()
    for part in (absolute, *absolute.parents):
        if part.is_symlink() or part.is_junction():
            raise DocumentTransactionError("document_transaction_path_invalid", "事务目标不得经过链接或联接点")
    resolved = absolute.resolve(strict=False)
    if (allowed_targets is not None and resolved not in allowed_targets) or (allowed_targets is None and not resolved.is_relative_to(root)):
        raise DocumentTransactionError("document_transaction_path_invalid", "事务目标不在明确恢复范围中", details={"target": str(resolved)})
    return resolved


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _write_journal(path: Path, value: dict[str, Any]) -> None:
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix=".journal.",
        suffix=".next",
        dir=path.parent,
        delete=False,
    ) as stream:
        stream.write(_canonical_json(value))
        stream.flush()
        os.fsync(stream.fileno())
        temporary = Path(stream.name)
    try:
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _relative_path(root: Path, target: Path, field: str) -> str:
    resolved = target.resolve(strict=False)
    if not resolved.is_relative_to(root):
        raise DocumentTransactionError(
            "document_transaction_path_invalid",
            f"{field} 越出事务恢复根目录：{target}",
        )
    return resolved.relative_to(root).as_posix()


def _journal_path(root: Path, relative: Any, field: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise DocumentTransactionError(
            "document_transaction_journal_invalid",
            f"事务日志缺少 {field}",
        )
    pure = PurePosixPath(relative)
    if pure.is_absolute() or ".." in pure.parts or pure.as_posix() != relative:
        raise DocumentTransactionError(
            "document_transaction_journal_invalid",
            f"事务日志 {field} 不是安全相对路径",
        )
    target = root.joinpath(*pure.parts).resolve(strict=False)
    if not target.is_relative_to(root):
        raise DocumentTransactionError(
            "document_transaction_journal_invalid",
            f"事务日志 {field} 越出恢复根目录",
        )
    return target


def _read_journal(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DocumentTransactionError(
            "document_transaction_journal_invalid",
            f"事务日志不可读：{path}",
        ) from error
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != TRANSACTION_SCHEMA
        or value.get("state")
        not in {"prepared", "replacing", "validating", "committed"}
        or not isinstance(value.get("entries"), list)
    ):
        raise DocumentTransactionError(
            "document_transaction_journal_invalid",
            f"事务日志结构无效：{path}",
        )
    return value


def _current_digest(path: Path) -> str | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise DocumentTransactionError(
            "document_transaction_recovery_conflict",
            f"事务目标不再是普通文件：{path}",
        )
    return _sha256(path.read_bytes())


def _cleanup_transaction(transaction_dir: Path) -> None:
    for child in transaction_dir.iterdir():
        if child.is_dir() or child.is_symlink():
            raise DocumentTransactionError(
                "document_transaction_cleanup_invalid",
                f"事务目录包含意外条目：{child}",
            )
        child.unlink(missing_ok=True)
    transaction_dir.rmdir()
    _fsync_directory(transaction_dir.parent)


def _recover_one(transaction_dir: Path, recovery_root: Path, allowed_targets: set[Path] | None = None) -> None:
    journal_path = transaction_dir / "journal.json"
    if not journal_path.exists():
        # Replacement never starts before the first journal is durable.
        _cleanup_transaction(transaction_dir)
        return
    journal = _read_journal(journal_path)
    entries = journal["entries"]
    checked: list[tuple[dict[str, Any], Path, str | None]] = []
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise DocumentTransactionError(
                "document_transaction_journal_invalid",
                f"事务日志 entries[{index}] 无效",
            )
        raw_target = raw.get("target")
        if not isinstance(raw_target, str) or not Path(raw_target).is_absolute():
            raise DocumentTransactionError("document_transaction_journal_invalid", "事务日志缺少明确目标路径")
        target = Path(raw_target)
        target = _scoped_target(target, recovery_root, allowed_targets)
        original = raw.get("original_sha256")
        replacement = raw.get("replacement_sha256")
        if (
            original is not None
            and (
                not isinstance(original, str)
                or len(original) != 64
            )
        ) or not isinstance(replacement, str) or len(replacement) != 64:
            raise DocumentTransactionError(
                "document_transaction_journal_invalid",
                f"事务日志 entries[{index}] 摘要无效",
            )
        current = _current_digest(target)
        checked.append((raw, target, current))

    if journal["state"] == "committed":
        conflicts = [
            str(target)
            for raw, target, current in checked
            if current != raw["replacement_sha256"]
        ]
        if conflicts:
            raise DocumentTransactionError(
                "document_transaction_recovery_conflict",
                "已提交事务的目标字节发生变化，拒绝猜测恢复",
                details=conflicts,
            )
        _cleanup_transaction(transaction_dir)
        return

    conflicts = [
        str(target)
        for raw, target, current in checked
        if current
        not in {raw.get("original_sha256"), raw["replacement_sha256"]}
    ]
    if conflicts:
        raise DocumentTransactionError(
            "document_transaction_recovery_conflict",
            "未提交事务之后出现第三方文件变化，拒绝覆盖",
            details=conflicts,
        )

    restored: list[str] = []
    try:
        for index, (raw, target, _current) in enumerate(reversed(checked)):
            original = raw.get("original_sha256")
            live = _current_digest(target)
            if live == original:
                continue
            if live != raw["replacement_sha256"]:
                raise DocumentTransactionError("document_transaction_recovery_conflict", "恢复期间目标出现第三方变化", details={"target": str(target)})
            if original is None:
                target.unlink(missing_ok=True)
                _fsync_directory(target.parent)
                restored.append(str(target))
                continue
            backup = _journal_path(
                recovery_root,
                raw.get("backup"),
                f"entries[{len(checked) - index - 1}].backup",
            )
            if not backup.is_file() or _sha256(backup.read_bytes()) != original:
                raise DocumentTransactionError(
                    "document_transaction_backup_invalid",
                    f"事务旧文件副本无效：{backup}",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_file(backup, target)
            mode = raw.get("original_mode")
            if type(mode) is int:
                os.chmod(target, mode)
            _fsync_directory(target.parent)
            restored.append(str(target))
    except (OSError, DocumentTransactionError) as error:
        raise DocumentTransactionError(
            "document_transaction_rollback_incomplete",
            "文档事务恢复未能完整回滚",
            details={"restored": restored, "error": str(error)},
        ) from error
    _cleanup_transaction(transaction_dir)


def recover_document_transactions(
    transaction_root: Path,
    recovery_root: Path,
    *, allowed_targets: Sequence[Path] | None = None,
) -> int:
    """Recover every durable transaction journal under one exact root."""

    root = recovery_root.resolve()
    for directory in (transaction_root.absolute(), *transaction_root.absolute().parents):
        if directory.is_symlink() or directory.is_junction():
            raise DocumentTransactionError("document_transaction_path_invalid", "事务目录不得经过链接或联接点")
    transactions = transaction_root.resolve(strict=False)
    if not transactions.is_relative_to(root):
        raise DocumentTransactionError(
            "document_transaction_path_invalid",
            "事务目录必须位于恢复根目录内",
        )
    if not transactions.exists():
        return 0
    if not transactions.is_dir() or transactions.is_symlink():
        raise DocumentTransactionError(
            "document_transaction_path_invalid",
            "事务根目录不是普通目录",
        )
    recovered = 0
    for candidate in sorted(transactions.iterdir()):
        if not candidate.name.startswith("txn-"):
            continue
        if not candidate.is_dir() or candidate.is_symlink():
            raise DocumentTransactionError(
                "document_transaction_path_invalid",
                f"事务条目不是普通目录：{candidate}",
            )
        _recover_one(candidate, root, {path.resolve(strict=False) for path in allowed_targets} if allowed_targets is not None else None)
        recovered += 1
    return recovered


def replace_documents(
    documents: Sequence[tuple[Path, bytes]],
    *,
    validate_replaced: Callable[[], None] | None = None,
    transaction_root: Path | None = None,
    recovery_root: Path | None = None,
    expected_originals: Mapping[Path, str | None] | None = None,
    allowed_targets: Sequence[Path] | None = None,
) -> None:
    """Replace all documents with a durable journal and crash recovery."""

    if not documents:
        raise ValueError("documents must not be empty")
    targets = [target.absolute() for target, _content in documents]
    if len(set(targets)) != len(targets):
        raise ValueError("document transaction targets must be unique")
    if recovery_root is None and len({path.parent for path in targets}) > 1:
        raise DocumentTransactionError("document_transaction_recovery_root_required", "分离位置的文档事务必须给出明确恢复根目录和目标清单")
    root = (
        recovery_root.resolve()
        if recovery_root is not None
        else Path(os.path.commonpath([str(path.parent) for path in targets])).resolve()
    )
    transactions = (
        transaction_root.resolve(strict=False)
        if transaction_root is not None
        else root / ".strixnova" / "artifacts" / "document-transactions"
    )
    if not transactions.is_relative_to(root):
        raise DocumentTransactionError(
            "document_transaction_path_invalid",
            "事务目录必须位于恢复根目录内",
        )
    permitted = {path.resolve(strict=False) for path in allowed_targets} if allowed_targets is not None else None
    targets = [_scoped_target(target, root, permitted) for target in targets]
    transactions.mkdir(parents=True, exist_ok=True)
    recover_document_transactions(transactions, root, allowed_targets=allowed_targets)

    transaction_dir = transactions / f"txn-{uuid.uuid4().hex}"
    transaction_dir.mkdir()
    _fsync_directory(transactions)
    entries: list[dict[str, Any]] = []
    try:
        for index, ((target, content), resolved_target) in enumerate(
            zip(documents, targets, strict=True)
        ):
            if not isinstance(content, bytes):
                raise TypeError("document transaction content must be bytes")
            if resolved_target.exists() and not resolved_target.is_file():
                raise DocumentTransactionError(
                    "document_transaction_path_invalid",
                    f"事务目标不是普通文件：{resolved_target}",
                )
            original = (
                resolved_target.read_bytes()
                if resolved_target.exists()
                else None
            )
            if expected_originals is not None and (
                resolved_target not in expected_originals
                or (_sha256(original) if original is not None else None) != expected_originals[resolved_target]
            ):
                raise DocumentTransactionError("document_transaction_recovery_conflict", f"事务目标已不等于预检内容：{resolved_target}")
            mode = (
                resolved_target.stat().st_mode
                if resolved_target.exists()
                else None
            )
            backup = transaction_dir / f"backup-{index:04d}.bin"
            if original is not None:
                _write_bytes(backup, original)
            replacement = transaction_dir / f"replacement-{index:04d}.bin"
            _write_bytes(replacement, content)
            if mode is not None:
                os.chmod(replacement, mode)
            entries.append(
                {
                    "target": str(resolved_target),
                    "backup": (
                        _relative_path(root, backup, "backup")
                        if original is not None
                        else None
                    ),
                    "replacement": _relative_path(
                        root,
                        replacement,
                        "replacement",
                    ),
                    "original_sha256": (
                        _sha256(original) if original is not None else None
                    ),
                    "replacement_sha256": _sha256(content),
                    "original_mode": mode,
                }
            )
        _fsync_directory(transaction_dir)
        journal = {
            "schema_version": TRANSACTION_SCHEMA,
            "transaction_id": transaction_dir.name,
            "state": "prepared",
            "replaced_count": 0,
            "entries": entries,
        }
        journal_path = transaction_dir / "journal.json"
        _write_journal(journal_path, journal)
        journal["state"] = "replacing"
        _write_journal(journal_path, journal)
        for index, (raw, target) in enumerate(zip(entries, targets, strict=True)):
            if _current_digest(target) != raw["original_sha256"]:
                raise DocumentTransactionError("document_transaction_recovery_conflict", f"替换前目标内容已改变：{target}")
            replacement = _journal_path(
                root,
                raw["replacement"],
                f"entries[{index}].replacement",
            )
            target.parent.mkdir(parents=True, exist_ok=True)
            _replace_file(replacement, target)
            _fsync_directory(target.parent)
            journal["replaced_count"] = index + 1
            _write_journal(journal_path, journal)
        journal["state"] = "validating"
        _write_journal(journal_path, journal)
        if validate_replaced is not None:
            validate_replaced()
        journal["state"] = "committed"
        _write_journal(journal_path, journal)
    except BaseException:
        # In-process failures take the same durable recovery path.  A hard
        # process termination skips this block and is recovered next entry.
        try:
            if transaction_dir.exists():
                _recover_one(transaction_dir, root, permitted)
        except DocumentTransactionError:
            raise
        raise
    _recover_one(transaction_dir, root, permitted)


__all__ = [
    "DocumentTransactionError",
    "recover_document_transactions",
    "replace_documents",
]
