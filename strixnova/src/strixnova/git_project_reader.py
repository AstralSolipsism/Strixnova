"""Read project-owned engineering files from a working tree or Git commit."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
import base64
import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import shutil
from typing import Any

import yaml

from strixnova.process_supervisor import (
    ProcessExecutionError,
    ProcessLimits,
    ProcessPolicy,
    ProcessResult,
    run_process,
)


FORBIDDEN_PROJECT_ROOTS = frozenset({".git", ".strixnova"})
_SAFE_REF = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_COMMIT = re.compile(r"[0-9a-f]{40,64}")
_OBJECT_ID = re.compile(r"[0-9a-f]{40,64}")
_MAX_GIT_INPUT_BYTES = 1024 * 1024
_MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
_MAX_WORKTREE_PATHS = 200_000
_BATCH_HEADER_ALLOWANCE = 160
_NO_LAZY_FETCH_MINIMUM_VERSION = (2, 45, 0)


def _git_auto_text_is_binary(content: bytes) -> bool:
    """Mirror Git's full-buffer text statistics for ``text=auto``.

    A prefix-only NUL probe is insufficient: Git also treats a lone carriage
    return and a material density of control bytes as binary, and it scans the
    complete buffer for those facts.
    """

    printable = 0
    nonprintable = 0
    nul = False
    lone_cr = 0
    index = 0
    while index < len(content):
        value = content[index]
        if value == 13:
            if index + 1 < len(content) and content[index + 1] == 10:
                index += 2
                continue
            lone_cr += 1
        elif value == 10:
            pass
        elif value == 0:
            nul = True
            nonprintable += 1
        elif value == 127 or (
            value < 32 and value not in {8, 9, 12, 27}
        ):
            nonprintable += 1
        else:
            printable += 1
        index += 1
    # Git treats a trailing DOS end-of-file marker as text metadata rather
    # than as a binary control byte when computing the density threshold.
    if content.endswith(b"\x1a") and nonprintable:
        nonprintable -= 1
    if lone_cr or nul:
        return True
    return nonprintable > (printable >> 7)


def _index_preserves_crlf(indexed: bytes | None) -> bool:
    """Match Git's CRLF-in-index guard for an existing text blob."""

    return bool(
        indexed is not None
        and b"\r\n" in indexed
        and not _git_auto_text_is_binary(indexed)
    )


def _direct_git_executable(discovered: str, *, windows: bool) -> str:
    """Avoid the short-lived Git for Windows command-directory launcher."""

    selected = Path(discovered).resolve()
    if windows and selected.parent.name.casefold() == "cmd":
        candidate = (
            selected.parent.parent / "mingw64" / "bin" / selected.name
        )
        if candidate.is_file():
            return str(candidate.resolve())
    return str(selected)


class GitProjectReaderError(ValueError):
    """A project path or Git-backed read is invalid."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "project_read_failed",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


@dataclass(frozen=True, slots=True)
class RepositoryReadScope:
    """A declared repository identity bound to one inspected local Git root."""

    repository_id: str
    project_dir: Path
    git_common_dir: Path


def repository_path_from_git(
    value: bytes,
    field: str = "Git 路径",
) -> str:
    """Decode one Git-returned path without changing its identity."""

    try:
        decoded = value.decode("utf-8", errors="strict")
    except UnicodeError as error:
        raise GitProjectReaderError(
            f"{field}必须是 UTF-8",
            code="git_path_encoding_invalid",
        ) from error
    if "\\" in decoded:
        raise GitProjectReaderError(
            f"{field}包含不能安全表示的反斜杠文件名",
            code="git_path_unsupported",
            details={"path": decoded},
        )
    path = PurePosixPath(decoded)
    if (
        not decoded
        or path.is_absolute()
        or ".." in path.parts
        or ":" in decoded
        or not path.parts
        or path.as_posix() != decoded
    ):
        raise GitProjectReaderError(
            f"{field}不是可安全表示的 Git 仓库相对路径",
            code="git_path_unsupported",
            details={"path": decoded},
        )
    # Git may legitimately return tracked internal paths such as
    # .strixnova/.gitignore while we scan an immutable tree.  Preserve that
    # identity here; public project-file entry points still reject internal
    # roots through repository_relative_path().
    return decoded


class _ReadOnlyGit:
    """Private read-only Git implementation behind the project-reader seam."""

    def __init__(self, project: Path) -> None:
        self.project = project
        discovered_git = shutil.which("git")
        self.git = (
            _direct_git_executable(
                discovered_git,
                windows=os.name == "nt",
            )
            if discovered_git
            else None
        )
        self._verified_commits: set[str] = set()
        self._trees: dict[
            str,
            dict[str, tuple[str, int | None, str, str]],
        ] = {}
        self._objects: dict[str, bytes] = {}
        if not self.git:
            raise GitProjectReaderError(
                "未检测到 Git",
                code="git_not_available",
            )
        top = self._run(["rev-parse", "--show-toplevel"], allow_failure=True)
        if top.exit_code != 0:
            raise GitProjectReaderError(
                "精确版本读取要求本地 Git 仓库",
                code="git_repository_required",
            )
        try:
            reported = Path(top.stdout_text().strip()).resolve()
        except (OSError, RuntimeError, ValueError) as error:
            raise GitProjectReaderError(
                "无法确定 Git 项目根",
                code="git_repository_invalid",
            ) from error
        if reported != self.project:
            raise GitProjectReaderError(
                "Git 项目根与请求的项目目录不一致："
                f"{reported} != {self.project}",
                code="git_repository_mismatch",
            )
        if self._git_version() < _NO_LAZY_FETCH_MINIMUM_VERSION:
            partial_clone = self._run(
                ["config", "--local", "--get", "extensions.partialClone"],
                allow_failure=True,
            )
            promisor_remote = self._run(
                [
                    "config",
                    "--local",
                    "--get-regexp",
                    r"^remote\..*\.promisor$",
                ],
                allow_failure=True,
            )
            if partial_clone.exit_code == 0 or promisor_remote.exit_code == 0:
                raise GitProjectReaderError(
                    "当前 Git 版本早于 2.45，不能保证部分克隆缺失对象读取不会访问远端",
                    code="git_lazy_fetch_unsafe",
                )

    def _git_version(self) -> tuple[int, int, int]:
        output = self._run(["version"]).stdout_text().strip()
        match = re.search(r"\b(\d+)\.(\d+)\.(\d+)", output)
        if match is None:
            raise GitProjectReaderError(
                "无法识别本地 Git 版本",
                code="git_version_invalid",
            )
        return tuple(int(value) for value in match.groups())

    def resolve_commit(self, ref: str) -> str:
        selected = str(ref or "").strip()
        if (
            _SAFE_REF.fullmatch(selected) is None
            or ".." in selected
            or selected.endswith("/")
            or "//" in selected
            or selected.startswith("-")
        ):
            raise GitProjectReaderError(
                "observed_ref 不是安全的本地 Git 引用",
                code="git_ref_invalid",
            )
        if _COMMIT.fullmatch(selected) and selected in self._verified_commits:
            return selected
        result = self._run(
            ["rev-parse", "--verify", f"{selected}^{{commit}}"],
            allow_failure=True,
        )
        commit = result.stdout_text().strip()
        if result.exit_code != 0 or _COMMIT.fullmatch(commit) is None:
            raise GitProjectReaderError(
                f"Git 引用不存在或不是提交：{selected}",
                code="git_ref_not_found",
            )
        self._verified_commits.add(commit)
        return commit

    def path_exists_at(self, commit: str, relative_path: str) -> bool:
        return relative_path in self._tree_entries_at(commit)

    def read_file_at(self, commit: str, relative_path: str) -> bytes:
        return self.read_files_at(commit, [relative_path])[relative_path]

    def read_files_at(
        self,
        commit: str,
        relative_paths: Sequence[str],
    ) -> dict[str, bytes]:
        """Read exact blob objects in bounded one-shot batches."""

        paths = list(dict.fromkeys(relative_paths))
        if not paths:
            return {}
        tree = self._tree_entries_at(commit)
        path_to_object: dict[str, str] = {}
        object_sizes: dict[str, int] = {}
        for path in paths:
            entry = tree.get(path)
            if entry is None:
                raise GitProjectReaderError(
                    f"{path} 在 Git 提交 {commit} 中不存在"
                )
            object_id, size, object_type, mode = entry
            if object_type != "blob" or size is None or mode not in {"100644", "100755"}:
                raise GitProjectReaderError(
                    f"{path} 在 Git 提交 {commit} 中不是普通文件",
                    code="git_entry_mode_unsupported",
                )
            if size + _BATCH_HEADER_ALLOWANCE > _MAX_GIT_OUTPUT_BYTES:
                raise GitProjectReaderError(
                    f"{path} 超过不可变项目文件读取上限"
                )
            path_to_object[path] = object_id
            object_sizes[object_id] = size

        pending = [
            object_id for object_id in object_sizes if object_id not in self._objects
        ]
        self._load_objects(pending, object_sizes)
        return {
            path: self._objects[object_id]
            for path, object_id in path_to_object.items()
        }

    def _load_objects(
        self,
        pending: Sequence[str],
        object_sizes: Mapping[str, int],
    ) -> None:
        """Share bounded immutable-object reads across tree and index views."""

        chunk: list[str] = []
        chunk_output_size = 0
        chunk_input_size = 0
        for object_id in pending:
            expected_output = object_sizes[object_id] + _BATCH_HEADER_ALLOWANCE
            expected_input = len(object_id) + 1
            if chunk and (
                chunk_output_size + expected_output > _MAX_GIT_OUTPUT_BYTES
                or chunk_input_size + expected_input > _MAX_GIT_INPUT_BYTES
            ):
                self._read_object_batch(chunk, object_sizes)
                chunk = []
                chunk_output_size = 0
                chunk_input_size = 0
            chunk.append(object_id)
            chunk_output_size += expected_output
            chunk_input_size += expected_input
        if chunk:
            self._read_object_batch(chunk, object_sizes)

    def tracked_paths_at(
        self,
        commit: str,
        *,
        prefix: str | None = None,
    ) -> list[str]:
        paths = self._tree_entries_at(commit)
        if prefix is None:
            return sorted(paths)
        boundary = prefix.rstrip("/") + "/"
        return sorted(
            path
            for path in paths
            if path == prefix or path.startswith(boundary)
        )

    def worktree_paths(self, *, prefix: str | None = None) -> list[str]:
        """List tracked and non-ignored untracked files through Git path rules."""

        arguments = [
            "-c",
            "core.quotepath=false",
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
        ]
        if prefix is not None:
            arguments.append(f":(literal){prefix}")
        result = self._run(arguments)
        paths: list[str] = []
        for raw_path in result.stdout.split(b"\0"):
            if not raw_path:
                continue
            path = repository_path_from_git(raw_path, "Git 工作树路径")
            candidate = self.project.joinpath(*PurePosixPath(path).parts)
            if not candidate.is_file():
                continue
            paths.append(path)
            if len(paths) > _MAX_WORKTREE_PATHS:
                raise GitProjectReaderError(
                    "Git 工作树文件数量超过实现观察上限",
                    code="worktree_path_limit_exceeded",
                    details={"limit": _MAX_WORKTREE_PATHS},
                )
        return sorted(set(paths))

    def _tree_entries_at(
        self,
        commit: str,
    ) -> dict[str, tuple[str, int | None, str, str]]:
        cached = self._trees.get(commit)
        if cached is not None:
            return cached
        result = self._run(
            [
                "-c",
                "core.quotepath=false",
                "ls-tree",
                "-r",
                "--long",
                "-z",
                commit,
                "--",
            ]
        )
        entries: dict[str, tuple[str, int | None, str, str]] = {}
        for record in result.stdout.split(b"\0"):
            if not record:
                continue
            header, separator, raw_path = record.partition(b"\t")
            parts = header.split()
            if not separator or len(parts) != 4:
                raise GitProjectReaderError("Git 树快照格式无效")
            raw_mode, raw_type, raw_object_id, raw_size = parts
            try:
                mode = raw_mode.decode("ascii", errors="strict")
                object_type = raw_type.decode("ascii", errors="strict")
                object_id = raw_object_id.decode("ascii", errors="strict")
                path = repository_path_from_git(raw_path, "Git 树路径")
                size = None if raw_size == b"-" else int(raw_size)
            except GitProjectReaderError:
                raise
            except (UnicodeError, ValueError) as error:
                raise GitProjectReaderError("Git 树快照内容无效") from error
            if _OBJECT_ID.fullmatch(object_id) is None or path in entries:
                raise GitProjectReaderError("Git 树快照对象或路径无效")
            if mode not in {"100644", "100755", "120000", "160000"}:
                raise GitProjectReaderError("Git 树快照文件模式无效")
            entries[path] = (object_id, size, object_type, mode)
        self._trees[commit] = entries
        return entries

    def _read_object_batch(
        self,
        object_ids: Sequence[str],
        expected_sizes: Mapping[str, int],
    ) -> None:
        stdin_bytes = b"".join(
            object_id.encode("ascii") + b"\n" for object_id in object_ids
        )
        loaded: dict[str, bytes] = {}
        try:
            result = self._run(
                ["cat-file", "--batch"],
                stdin_bytes=stdin_bytes,
            )
            cursor = 0
            for expected_object_id in object_ids:
                header_end = result.stdout.find(b"\n", cursor)
                if header_end < 0:
                    raise GitProjectReaderError("Git 批量对象输出缺少头部")
                header = result.stdout[cursor:header_end].split()
                if len(header) != 3:
                    raise GitProjectReaderError("Git 批量对象输出头部无效")
                try:
                    object_id = header[0].decode("ascii", errors="strict")
                    object_type = header[1].decode("ascii", errors="strict")
                    size = int(header[2])
                except (UnicodeError, ValueError) as error:
                    raise GitProjectReaderError(
                        "Git 批量对象输出头部无效"
                    ) from error
                if (
                    object_id != expected_object_id
                    or object_type != "blob"
                    or size != expected_sizes[expected_object_id]
                ):
                    raise GitProjectReaderError(
                        "Git 批量对象输出与树快照不一致"
                    )
                content_start = header_end + 1
                content_end = content_start + size
                if (
                    content_end >= len(result.stdout)
                    or result.stdout[content_end : content_end + 1] != b"\n"
                ):
                    raise GitProjectReaderError("Git 批量对象输出长度无效")
                loaded[object_id] = result.stdout[content_start:content_end]
                cursor = content_end + 1
            if cursor != len(result.stdout):
                raise GitProjectReaderError("Git 批量对象输出包含多余内容")
        except GitProjectReaderError:
            loaded = {}
            for object_id in object_ids:
                fallback = self._run(["cat-file", "blob", object_id])
                if len(fallback.stdout) != expected_sizes[object_id]:
                    raise GitProjectReaderError(
                        "Git 单对象回退读取与树快照长度不一致"
                    )
                loaded[object_id] = fallback.stdout
        self._objects.update(loaded)

    def changed_paths_between(
        self,
        older_commit: str,
        newer_commit: str,
    ) -> list[str]:
        result = self._run(
            [
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-only",
                "-z",
                older_commit,
                newer_commit,
                "--",
            ]
        )
        try:
            return sorted(
                repository_path_from_git(value, "Git 变化路径")
                for value in result.stdout.split(b"\0")
                if value
            )
        except UnicodeError as error:
            raise GitProjectReaderError("Git 路径必须是 UTF-8") from error

    def change_entries(
        self, older_commit: str, newer_commit: str | None,
    ) -> list[dict[str, str | None]]:
        """Read changes, retaining both rename endpoints without executing filters."""

        if newer_commit is None:
            # Even a name-only diff can invoke a clean/process filter while
            # comparing worktree bytes. Reject conversions before asking Git
            # for any diff, using the same policy as canonical content reads.
            paths = self.worktree_paths()
            for path, attributes in self._explicit_path_attributes_many(paths).items():
                self._validate_conversion_attributes(path, attributes)
        arguments = [
            # Porcelain diff can refresh stat-only index entries even when
            # optional locks are disabled. A query must preserve index bytes.
            "-c", "core.quotepath=false", "-c", "diff.autoRefreshIndex=false",
            "diff", "--no-ext-diff",
            "--no-textconv", "--name-status", "-z", "--find-renames", older_commit,
        ]
        if newer_commit is not None:
            arguments.append(newer_commit)
        tokens = self._run([*arguments, "--"]).stdout.split(b"\0")
        entries: list[dict[str, str | None]] = []
        index = 0
        while index < len(tokens) and tokens[index]:
            status = tokens[index].decode("ascii", errors="strict")
            count = 2 if status.startswith(("R", "C")) else 1
            if index + count >= len(tokens) or any(not item for item in tokens[index + 1:index + count + 1]):
                raise GitProjectReaderError("Git 变化记录不完整", code="git_change_output_invalid")
            paths = [repository_path_from_git(item, "Git 变化路径") for item in tokens[index + 1:index + count + 1]]
            entries.append({
                "status": status,
                "old_path": paths[0] if status[0] != "A" else None,
                "path": paths[-1] if status[0] != "D" else None,
            })
            index += count + 1
        if newer_commit is None:
            # Name-only output can retain stat-only entries when automatic
            # index refresh is disabled. Numstat actually compares contents;
            # retain its real changes, including zero-line mode changes.
            if entries:
                raw_changes = self._run([
                    *("--numstat" if value == "--name-status" else value
                      for value in arguments), "--",
                ]).stdout.split(b"\0")
                changed_paths: set[str] = set()
                position = 0
                while position < len(raw_changes) and raw_changes[position]:
                    fields = raw_changes[position].split(b"\t", 2)
                    if len(fields) != 3 or any(
                        count != b"-" and not count.isdigit() for count in fields[:2]
                    ):
                        raise GitProjectReaderError("Git 变化统计格式无效", code="git_change_output_invalid")
                    position += 1
                    paths = [fields[2]]
                    if not fields[2]:
                        paths = raw_changes[position:position + 2]
                        if len(paths) != 2 or any(not path for path in paths):
                            raise GitProjectReaderError("Git 重命名统计不完整", code="git_change_output_invalid")
                        position += 2
                    changed_paths.update(repository_path_from_git(path, "Git 变化统计路径") for path in paths)
                entries = [entry for entry in entries if entry["path"] in changed_paths or entry["old_path"] in changed_paths]
            raw = self._run(["ls-files", "--others", "--exclude-standard", "-z"]).stdout
            entries.extend({
                "status": "?", "old_path": None,
                "path": repository_path_from_git(path, "Git 未跟踪路径"),
            } for path in raw.split(b"\0") if path)
        return sorted(entries, key=lambda item: (item["path"] or item["old_path"] or "", item["status"] or ""))

    def is_ancestor(self, older_commit: str, newer_commit: str) -> bool:
        """Return whether the older commit is an ancestor of the newer one."""

        result = self._run(
            ["merge-base", "--is-ancestor", older_commit, newer_commit],
            allow_failure=True,
        )
        if result.exit_code == 0:
            return True
        if result.exit_code == 1:
            return False
        raise GitProjectReaderError(
            "无法判断 Git 提交祖先关系："
            f"{older_commit} -> {newer_commit}"
        )

    def pending_operations(self) -> list[str]:
        result = self._run(["rev-parse", "--absolute-git-dir"])
        try:
            directory = Path(result.stdout.decode("utf-8").rstrip("\r\n"))
            if not directory.is_absolute() or not directory.is_dir():
                raise ValueError
            return [name for name in ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply", "sequencer") if (directory / name).exists()]
        except (OSError, UnicodeError, ValueError) as error:
            raise GitProjectReaderError("无法确定工作树实际 Git 操作状态", code="git_operation_state_invalid") from error

    def worktree_dirty(self) -> bool:
        result = self._run(
            ["-c", "core.quotepath=false", "status", "--porcelain", "-z"]
        )
        return bool(result.stdout)

    def canonical_worktree_bytes(
        self,
        relative_path: str,
        content: bytes,
        *,
        explicit_attributes: Mapping[str, str] | None = None,
        index_blobs: Mapping[str, bytes | None] | None = None,
        autocrlf: str | None = None,
    ) -> bytes:
        """Return the bytes Git would store for one working-tree file."""

        if len(content) > _MAX_GIT_INPUT_BYTES:
            raise GitProjectReaderError(
                f"{relative_path} 超过工作树规范内容读取上限"
            )
        if explicit_attributes is None:
            explicit_attributes = self._explicit_path_attributes(relative_path)
        self._validate_conversion_attributes(relative_path, explicit_attributes)
        text_attribute = explicit_attributes.get("text", "unspecified")
        if text_attribute not in {"set", "unset", "auto", "unspecified"}:
            raise GitProjectReaderError(
                f"当前文件使用了不能安全重放的 text 属性：{relative_path}"
            )
        eol_attribute = explicit_attributes.get("eol", "unspecified")
        if eol_attribute not in {"lf", "crlf", "unspecified"}:
            raise GitProjectReaderError(
                f"当前文件使用了不能安全重放的 eol 属性：{relative_path}"
            )
        crlf_attribute = explicit_attributes.get("crlf", "unspecified")
        if crlf_attribute not in {"set", "unset", "input", "unspecified"}:
            raise GitProjectReaderError(
                f"当前文件使用了不能安全重放的 crlf 属性：{relative_path}"
            )
        if crlf_attribute != "unspecified":
            if text_attribute != "unspecified" or eol_attribute != "unspecified":
                raise GitProjectReaderError(
                    f"当前文件同时使用了新旧换行属性，不能安全重放：{relative_path}"
                )
            if crlf_attribute == "set":
                text_attribute = "set"
            elif crlf_attribute == "unset":
                text_attribute = "unset"
            else:
                text_attribute = "set"
                eol_attribute = "lf"

        binary = _git_auto_text_is_binary(content)
        normalize_text = False
        if text_attribute == "set":
            normalize_text = True
        elif text_attribute == "auto":
            indexed = (
                self._index_blob_bytes(relative_path)
                if index_blobs is None
                else index_blobs[relative_path]
            )
            normalize_text = not binary and not _index_preserves_crlf(indexed)
        elif text_attribute == "unspecified":
            if autocrlf is None:
                autocrlf = self._core_autocrlf()
            indexed = (
                self._index_blob_bytes(relative_path)
                if index_blobs is None
                else index_blobs[relative_path]
            )
            normalize_text = (
                autocrlf in {"true", "input"}
                and not binary
                and not _index_preserves_crlf(indexed)
            )
        if eol_attribute in {"lf", "crlf"} and text_attribute == "unspecified":
            normalize_text = True
        return content.replace(b"\r\n", b"\n") if normalize_text else content

    @staticmethod
    def _validate_conversion_attributes(
        relative_path: str,
        explicit_attributes: Mapping[str, str],
    ) -> None:
        unsafe_attributes = {
            name: value
            for name, value in explicit_attributes.items()
            if name in {"filter", "ident", "working-tree-encoding"}
        }
        if unsafe_attributes:
            detail = "、".join(
                f"{name}={value}"
                for name, value in sorted(unsafe_attributes.items())
            )
            raise GitProjectReaderError(
                "当前文件配置了Strixnova不会执行的 Git 提交转换："
                f"{relative_path}（{detail}）；"
                "请先移除外部 clean filter（提交前转换器）、ident "
                "（对象身份展开）或 working-tree-encoding（工作树编码转换）",
                code="git_conversion_unsafe",
                details={"path": relative_path, "attributes": unsafe_attributes},
            )
    def _core_autocrlf(self) -> str:
        raw = self._run(
            ["config", "--get", "core.autocrlf"], allow_failure=True
        ).stdout_text().strip().casefold()
        if raw == "input":
            return "input"
        if not raw:
            return "false"
        parsed = self._run(
            ["config", "--type=bool", "--get", "core.autocrlf"],
            allow_failure=True,
        )
        value = parsed.stdout_text().strip().casefold()
        if parsed.exit_code != 0 or value not in {"false", "true"}:
            raise GitProjectReaderError(
                "core.autocrlf 使用了不能安全解释的值：" + raw
            )
        return value

    @staticmethod
    def _path_chunks(paths: Sequence[str]) -> Iterator[list[str]]:
        chunk: list[str] = []
        size = 0
        limit = min(16 * 1024, _MAX_GIT_INPUT_BYTES)
        for path in paths:
            cost = len(path.encode("utf-8")) + len(":(literal)") + 3
            if cost > limit:
                raise GitProjectReaderError("仓库路径超过批读取上限")
            if chunk and (size + cost > limit or len(chunk) >= 128):
                yield chunk
                chunk, size = [], 0
            chunk.append(path)
            size += cost
        if chunk:
            yield chunk

    def canonical_worktree_files(
        self, contents: Mapping[str, bytes]
    ) -> dict[str, bytes]:
        """Use invocation-local metadata; never cache mutable path state."""

        if not contents:
            return {}
        for path, content in contents.items():
            if len(content) > _MAX_GIT_INPUT_BYTES:
                raise GitProjectReaderError(
                    f"{path} 超过工作树规范内容读取上限"
                )
        attributes = self._explicit_path_attributes_many(list(contents))
        for path, selected in attributes.items():
            self._validate_conversion_attributes(path, selected)
        index_paths = [
            path for path, selected in attributes.items()
            if selected.get("text", "unspecified") in {"auto", "unspecified"}
            and selected.get("crlf", "unspecified") == "unspecified"
        ]
        index_blobs = self._index_blobs_many(index_paths)
        autocrlf = (
            self._core_autocrlf()
            if any(
                attributes[path].get("text", "unspecified") == "unspecified"
                for path in index_paths
            )
            else None
        )
        return {
            path: self.canonical_worktree_bytes(
                path, content,
                explicit_attributes=attributes[path],
                index_blobs=index_blobs,
                autocrlf=autocrlf,
            )
            for path, content in contents.items()
        }

    def _index_blobs_many(
        self, relative_paths: Sequence[str]
    ) -> dict[str, bytes | None]:
        paths = list(dict.fromkeys(relative_paths))
        selected: dict[str, str] = {}
        for chunk in self._path_chunks(paths):
            result = self._run(
                ["ls-files", "--stage", "-z", "--",
                 *(f":(literal){path}" for path in chunk)],
                allow_failure=True,
            )
            if result.exit_code != 0:
                return {path: self._index_blob_bytes(path) for path in paths}
            requested = set(chunk)
            for record in result.stdout.split(b"\0"):
                if not record:
                    continue
                header, separator, raw_path = record.partition(b"\t")
                parts = header.split()
                if not separator or len(parts) != 3:
                    raise GitProjectReaderError("Git 暂存区条目格式无效")
                try:
                    mode, object_id, stage = (
                        value.decode("ascii", errors="strict") for value in parts
                    )
                    path = repository_path_from_git(raw_path, "Git 暂存区路径")
                except UnicodeError as error:
                    raise GitProjectReaderError("Git 暂存区条目编码无效") from error
                if (
                    path not in requested or path in selected
                    or mode not in {"100644", "100755"} or stage != "0"
                    or _OBJECT_ID.fullmatch(object_id) is None
                ):
                    raise GitProjectReaderError(
                        f"Git 暂存区条目身份无效：{path}"
                    )
                selected[path] = object_id
        pending = [
            oid for oid in dict.fromkeys(selected.values())
            if oid not in self._objects
        ]
        sizes: dict[str, int] = {}
        for chunk in self._path_chunks(pending):
            result = self._run(
                ["cat-file", "--batch-check"],
                stdin_bytes=("\n".join(chunk) + "\n").encode("ascii"),
            )
            lines = result.stdout.splitlines()
            if len(lines) != len(chunk):
                raise GitProjectReaderError("Git 暂存区对象信息不完整")
            for expected, line in zip(chunk, lines, strict=True):
                fields = line.split()
                if len(fields) != 3 or fields[0] != expected.encode("ascii"):
                    raise GitProjectReaderError("Git 暂存区对象身份无效")
                try:
                    size = int(fields[2])
                except ValueError as error:
                    raise GitProjectReaderError("Git 暂存区对象大小无效") from error
                if fields[1] != b"blob" or not 0 <= size <= _MAX_GIT_INPUT_BYTES:
                    raise GitProjectReaderError("Git 暂存区对象类型或大小无效")
                sizes[expected] = size
        self._load_objects(pending, sizes)
        if any(
            len(self._objects[object_id]) > _MAX_GIT_INPUT_BYTES
            for object_id in selected.values()
        ):
            raise GitProjectReaderError("Git 暂存区对象超过工作树规范内容读取上限")
        return {
            path: self._objects[selected[path]] if path in selected else None
            for path in paths
        }

    def _explicit_path_attributes_many(
        self, relative_paths: Sequence[str]
    ) -> dict[str, dict[str, str]]:
        attributes: dict[str, dict[str, str]] = {
            path: {} for path in relative_paths
        }
        for chunk in self._path_chunks(relative_paths):
            result = self._run(
                ["check-attr", "-z", "--all", "--stdin"],
                stdin_bytes=("\0".join(chunk) + "\0").encode("utf-8"),
            )
            fields = result.stdout.split(b"\0")
            if fields and fields[-1] == b"":
                fields.pop()
            if len(fields) % 3:
                raise GitProjectReaderError("Git 显式路径属性响应不完整")
            requested = set(chunk)
            try:
                for index in range(0, len(fields), 3):
                    path = repository_path_from_git(fields[index], "Git 属性路径")
                    name = fields[index + 1].decode("utf-8", errors="strict")
                    value = fields[index + 2].decode("utf-8", errors="strict")
                    if path not in requested or name in attributes[path]:
                        raise GitProjectReaderError("Git 显式路径属性身份无效")
                    attributes[path][name] = value
            except UnicodeError as error:
                raise GitProjectReaderError("Git 路径属性不是有效 UTF-8") from error
        return attributes

    def _index_blob_bytes(self, relative_path: str) -> bytes | None:
        result = self._run(
            ["ls-files", "--stage", "-z", "--", relative_path],
            allow_failure=True,
        )
        if result.exit_code != 0 or not result.stdout:
            return None
        records = [record for record in result.stdout.split(b"\0") if record]
        if len(records) != 1:
            raise GitProjectReaderError(
                f"Git 暂存区包含不能安全解释的多阶段条目：{relative_path}"
            )
        header, separator, raw_path = records[0].partition(b"\t")
        parts = header.split()
        if not separator or len(parts) != 3:
            raise GitProjectReaderError(
                f"Git 暂存区条目格式无效：{relative_path}"
            )
        raw_mode, raw_object_id, raw_stage = parts
        try:
            mode = raw_mode.decode("ascii", errors="strict")
            object_id = raw_object_id.decode("ascii", errors="strict")
            stage = raw_stage.decode("ascii", errors="strict")
            path = repository_path_from_git(raw_path, "Git 暂存区路径")
        except UnicodeError as error:
            raise GitProjectReaderError(
                f"Git 暂存区条目编码无效：{relative_path}"
            ) from error
        if (
            mode not in {"100644", "100755"}
            or _OBJECT_ID.fullmatch(object_id) is None
            or stage != "0"
            or path != relative_path
        ):
            raise GitProjectReaderError(
                f"Git 暂存区条目身份无效：{relative_path}"
            )
        blob = self._objects.get(object_id)
        if blob is None:
            blob = self._run(["cat-file", "blob", object_id]).stdout
        if len(blob) > _MAX_GIT_INPUT_BYTES:
            raise GitProjectReaderError(
                f"{relative_path} 超过工作树规范内容读取上限"
            )
        self._objects[object_id] = blob
        return blob

    def _explicit_path_attributes(self, relative_path: str) -> dict[str, str]:
        """Return only attributes explicitly selected for one path.

        ``git check-attr <name>`` renders an absent attribute and a literal
        value such as ``filter=unspecified`` with the same text.  ``--all``
        omits truly absent attributes, so an attacker cannot hide a configured
        clean driver behind one of Git's presentation words.  Any explicit
        conversion attribute is rejected conservatively, including an explicit
        unset declaration, because safety matters more than accepting a
        redundant attribute spelling.
        """

        result = self._run(["check-attr", "-z", "--all", "--", relative_path])
        fields = result.stdout.split(b"\0")
        if fields and fields[-1] == b"":
            fields.pop()
        if len(fields) % 3:
            raise GitProjectReaderError(
                f"Git 没有返回完整的显式路径属性：{relative_path}"
            )
        attributes: dict[str, str] = {}
        try:
            for index in range(0, len(fields), 3):
                path = repository_path_from_git(
                    fields[index],
                    "Git 显式路径属性路径",
                )
                name = fields[index + 1].decode("utf-8", errors="strict")
                value = fields[index + 2].decode("utf-8", errors="strict")
                if path != relative_path:
                    raise GitProjectReaderError(
                        f"Git 显式路径属性身份不匹配：{relative_path}"
                    )
                attributes[name] = value
        except UnicodeError as error:
            raise GitProjectReaderError(
                f"Git 显式路径属性不是有效 UTF-8：{relative_path}"
            ) from error
        return attributes

    def _run(
        self,
        arguments: list[str],
        *,
        allow_failure: bool = False,
        stdin_bytes: bytes | None = None,
    ) -> ProcessResult:
        environment = dict(os.environ)
        for name in (
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_COMMON_DIR",
            "GIT_INDEX_FILE",
            "GIT_OBJECT_DIRECTORY",
            "GIT_ALTERNATE_OBJECT_DIRECTORIES",
            "GIT_PREFIX",
            "GIT_CONFIG_PARAMETERS",
        ):
            environment.pop(name, None)
        environment.update(
            {
                "GIT_CONFIG_COUNT": "2",
                "GIT_CONFIG_KEY_0": "safe.directory",
                "GIT_CONFIG_VALUE_0": self.project.as_posix(),
                "GIT_CONFIG_KEY_1": "core.fsmonitor",
                "GIT_CONFIG_VALUE_1": "false",
                "GIT_NO_REPLACE_OBJECTS": "1",
                "GIT_NO_LAZY_FETCH": "1",
                "GIT_OPTIONAL_LOCKS": "0",
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
        try:
            command = [str(self.git), *arguments]
            result = run_process(
                command,
                cwd=self.project,
                policy=ProcessPolicy.exact(
                    "strixnova.git-project-reader.v1",
                    "read_project_git_state",
                    command,
                ),
                env=environment,
                limits=ProcessLimits(
                    timeout_seconds=60,
                    cleanup_timeout_seconds=10,
                    max_input_bytes=_MAX_GIT_INPUT_BYTES,
                    max_output_bytes=_MAX_GIT_OUTPUT_BYTES,
                ),
                stdin_bytes=stdin_bytes,
            )
        except ProcessExecutionError as error:
            raise GitProjectReaderError(str(error)) from error
        if result.exit_code != 0 and not allow_failure:
            raise GitProjectReaderError(
                "只读 Git 命令失败："
                + " ".join(arguments)
                + (f"：{result.stderr_text().strip()}" if result.stderr else "")
            )
        return result


def repository_relative_path(value: Any, field: str = "path") -> str:
    """Validate and normalize one ordinary repository-relative path."""

    if not isinstance(value, str) or not value.strip():
        raise GitProjectReaderError(
            f"{field} 必须是非空字符串",
            code="repository_path_invalid",
        )
    raw = value.strip()
    if "\\" in raw:
        raise GitProjectReaderError(
            f"{field} 必须使用仓库规范的 / 路径分隔符",
            code="repository_path_invalid",
        )
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or ":" in raw
        or not path.parts
        or path.parts[0].casefold() in FORBIDDEN_PROJECT_ROOTS
        or path.as_posix() != raw
    ):
        raise GitProjectReaderError(
            f"{field} 必须是仓库内普通相对路径",
            code="repository_path_invalid",
        )
    return path.as_posix()


def repository_scope_root(value: Any, field: str = "root") -> str:
    """Allow the repository itself as a source scope, never as a file path."""

    if value == ".":
        return "."
    return repository_relative_path(value, field)


class GitProjectReader:
    """Small shared boundary for ref-aware long-lived project authorities."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        observed_ref: str | None = None,
    ) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        if not self.project.is_dir():
            raise GitProjectReaderError(f"项目目录不存在：{self.project}")
        self.observed_commit: str | None = None
        self._git: _ReadOnlyGit | None = None
        self._exists_cache: dict[str, bool] = {}
        self._bytes_cache: dict[str, bytes] = {}
        self._repository_scope: RepositoryReadScope | None = None
        if observed_ref is not None:
            self._git = _ReadOnlyGit(self.project)
            self.observed_commit = self._git.resolve_commit(observed_ref)

    def repository_scope(self, repository_id: str) -> RepositoryReadScope:
        """Inspect only local Git metadata; never derive the declared identity."""

        if not isinstance(repository_id, str) or re.fullmatch(
            r"REPO-[0-9A-F]{16}", repository_id
        ) is None:
            raise GitProjectReaderError(
                "仓库身份必须匹配 REPO-加十六位大写十六进制",
                code="repository_identity_invalid",
            )
        git = self._git or _ReadOnlyGit(self.project)
        self._git = git
        raw = git._run(["rev-parse", "--git-common-dir"]).stdout_text().strip()
        if not raw:
            raise GitProjectReaderError(
                "无法确定仓库共同目录", code="git_common_directory_invalid"
            )
        common = Path(raw)
        if not common.is_absolute():
            common = self.project / common
        common = common.resolve()
        if not common.is_dir():
            raise GitProjectReaderError(
                "仓库共同目录不可用", code="git_common_directory_invalid"
            )
        return RepositoryReadScope(repository_id, self.project, common)

    def bind_repository_identity(self, repository_id: str) -> RepositoryReadScope:
        """Bind a newly read declaration to this already selected reader."""

        self._repository_scope = self.repository_scope(repository_id)
        return self._repository_scope

    @property
    def repository_id(self) -> str | None:
        return self._repository_scope.repository_id if self._repository_scope is not None else None

    @classmethod
    def for_repository(
        cls,
        scope: RepositoryReadScope,
        *,
        observed_ref: str | None = None,
    ) -> GitProjectReader:
        """Bind an immutable scope, rechecking its root before content reads."""

        if not isinstance(scope, RepositoryReadScope):
            raise GitProjectReaderError(
                "读取必须提供已解析仓库范围", code="repository_scope_required"
            )
        reader = cls(scope.project_dir, observed_ref=observed_ref)
        return reader.bind_repository(scope)

    def bind_repository(self, scope: RepositoryReadScope) -> GitProjectReader:
        """Attach a checked identity while retaining this reader's exact cache."""

        if not isinstance(scope, RepositoryReadScope):
            raise GitProjectReaderError("读取必须提供已解析仓库范围", code="repository_scope_required")
        current = self.repository_scope(scope.repository_id)
        if current != scope:
            raise GitProjectReaderError(
                "仓库本机绑定已经改变",
                code="repository_binding_changed",
                details={"repository_id": scope.repository_id},
            )
        self._repository_scope = current
        return self

    def content_window(
        self,
        relative_path: str,
        *,
        offset: int = 0,
        limit: int = 65536,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Return exact canonical bytes in a bounded, digest-bound window."""

        if self._repository_scope is None:
            raise GitProjectReaderError(
                "内容窗口必须绑定明确仓库身份", code="repository_scope_required"
            )
        if (
            isinstance(offset, bool) or not isinstance(offset, int) or offset < 0
            or isinstance(limit, bool) or not isinstance(limit, int)
            or not 1 <= limit <= 1048576
        ):
            raise GitProjectReaderError(
                "字节位置或窗口长度无效", code="repository_content_range_invalid"
            )
        if expected_sha256 is not None and (
            not isinstance(expected_sha256, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None
        ):
            raise GitProjectReaderError(
                "预期内容摘要无效", code="repository_content_digest_invalid"
            )
        path = repository_relative_path(relative_path, "reference.path")
        if self.observed_commit is None:
            parent = self.project
            for part in PurePosixPath(path).parts[:-1]:
                parent = parent / part
                if parent.is_symlink() or parent.is_junction():
                    raise GitProjectReaderError(
                        "仓库内容路径不得经过链接", code="repository_symlink_forbidden"
                    )
                if (parent / ".git").exists():
                    raise GitProjectReaderError(
                        "内容路径进入了另一个仓库工作区",
                        code="repository_content_crosses_worktree",
                        details={"path": path},
                    )
        content = self.read_canonical_bytes(path, "仓库内容")
        digest = hashlib.sha256(content).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise GitProjectReaderError(
                "仓库内容已经改变",
                code="repository_content_changed",
                details={"expected_sha256": expected_sha256, "actual_sha256": digest},
            )
        if offset > len(content):
            raise GitProjectReaderError(
                "字节位置超出文件长度", code="repository_content_range_invalid"
            )
        chunk = content[offset:offset + limit]
        next_offset = offset + len(chunk) if offset + len(chunk) < len(content) else None
        return {
            "schema_version": "strixnova.repository-content.v1",
            "repository_id": self._repository_scope.repository_id,
            "path": path,
            "scope": "git_commit" if self.observed_commit is not None else "working_tree",
            "observed_commit": self.observed_commit,
            "byte_representation": "git_canonical",
            "sha256": digest,
            "size_bytes": len(content),
            "offset": offset,
            "returned_bytes": len(chunk),
            "encoding": "base64",
            "content_base64": base64.b64encode(chunk).decode("ascii"),
            "next_offset": next_offset,
            "writes_performed": False,
        }

    def absolute_path(self, relative_path: str) -> Path:
        normalized = repository_relative_path(relative_path)
        candidate = self.project
        for part in PurePosixPath(normalized).parts:
            candidate = candidate / part
            if candidate.is_symlink() or candidate.is_junction():
                raise GitProjectReaderError(
                    f"项目工作树规范读取不接受符号链接：{normalized}",
                    code="repository_symlink_forbidden",
                )
            if (self._repository_scope is not None and candidate != self.project / normalized
                    and (candidate / ".git").exists()):
                raise GitProjectReaderError(
                    "内容路径进入了另一个仓库工作区", code="repository_content_crosses_worktree",
                )
        try:
            resolved = candidate.resolve()
            resolved.relative_to(self.project)
        except (OSError, RuntimeError, ValueError) as error:
            raise GitProjectReaderError(
                f"项目工作树路径不得通过链接指向仓库外：{normalized}",
                code="repository_symlink_forbidden",
            ) from error
        return resolved

    def exists(self, relative_path: str) -> bool:
        normalized = repository_relative_path(relative_path)
        if self.observed_commit is None:
            return self.absolute_path(normalized).is_file()
        if normalized in self._exists_cache:
            return self._exists_cache[normalized]
        assert self._git is not None
        exists = self._git.path_exists_at(self.observed_commit, normalized)
        self._exists_cache[normalized] = exists
        return exists

    def path_scope_exists(self, relative_path: str) -> bool:
        """Accept an ordinary file or directory/prefix at the selected ref."""

        normalized = repository_scope_root(relative_path)
        if normalized == ".":
            return self.project.is_dir()
        if self.observed_commit is None:
            return self.absolute_path(normalized).exists()
        assert self._git is not None
        if self._git.path_exists_at(self.observed_commit, normalized):
            return True
        return bool(
            self._git.tracked_paths_at(
                self.observed_commit,
                prefix=normalized,
            )
        )

    def read_bytes(self, relative_path: str, label: str = "项目文件") -> bytes:
        normalized = repository_relative_path(relative_path)
        if self.observed_commit is None:
            try:
                return self.absolute_path(normalized).read_bytes()
            except OSError as error:
                raise GitProjectReaderError(
                    f"无法读取 {label}：{normalized}"
                ) from error
        if normalized in self._bytes_cache:
            return self._bytes_cache[normalized]
        assert self._git is not None
        try:
            self.prefetch([normalized])
            return self._bytes_cache[normalized]
        except GitProjectReaderError as error:
            raise GitProjectReaderError(
                f"无法从 Git 读取 {label}：{normalized}",
                code=error.code,
                details=error.details,
            ) from error

    def read_canonical_bytes(
        self,
        relative_path: str,
        label: str = "项目文件",
    ) -> bytes:
        """Read bytes in the same canonical form used by a future Git blob."""

        normalized = repository_relative_path(relative_path)
        content = self.read_bytes(normalized, label)
        if self.observed_commit is not None:
            return content
        git = self._git or _ReadOnlyGit(self.project)
        self._git = git
        return git.canonical_worktree_bytes(normalized, content)

    def prefetch(self, relative_paths: Sequence[str]) -> None:
        """Batch immutable file reads into this command-scoped reader."""

        normalized = [
            repository_relative_path(path)
            for path in dict.fromkeys(relative_paths)
        ]
        if self.observed_commit is None or not normalized:
            return
        pending = [
            path for path in normalized if path not in self._bytes_cache
        ]
        if not pending:
            return
        assert self._git is not None
        loaded = self._git.read_files_at(self.observed_commit, pending)
        self._bytes_cache.update(loaded)
        self._exists_cache.update({path: True for path in loaded})

    def iter_canonical_files(
        self,
        relative_paths: Sequence[str],
        label: str = "项目文件",
    ) -> Iterator[tuple[str, bytes]]:
        """Yield bounded fresh worktree batches, or the exact immutable view.

        Path attributes, configuration and index selection live only within a
        batch. Subsequent calls on this reader must observe their current state.
        Only immutable Git object contents are reused across calls.
        """

        if isinstance(relative_paths, (str, bytes)):
            raise GitProjectReaderError("批读取路径必须是路径集合")
        paths = list(dict.fromkeys(
            repository_relative_path(path) for path in relative_paths
        ))
        if not paths:
            return
        if self.observed_commit is not None:
            self.prefetch(paths)
            for path in paths:
                yield path, self.read_canonical_bytes(path, label)
            return
        git = self._git or _ReadOnlyGit(self.project)
        self._git = git
        for chunk in git._path_chunks(paths):
            contents: dict[str, bytes] = {}
            size = 0
            for path in chunk:
                content = self.read_bytes(path, label)
                if len(content) > _MAX_GIT_INPUT_BYTES:
                    raise GitProjectReaderError(
                        f"{path} 超过工作树规范内容读取上限"
                    )
                if contents and size + len(content) > _MAX_GIT_OUTPUT_BYTES:
                    yield from git.canonical_worktree_files(contents).items()
                    contents, size = {}, 0
                contents[path] = content
                size += len(content)
            if contents:
                yield from git.canonical_worktree_files(contents).items()

    def changed_paths_between(self, newer_ref: str) -> list[str]:
        """Return paths changed from the selected immutable commit to another ref."""

        if self.observed_commit is None or self._git is None:
            raise GitProjectReaderError("变化比较必须从精确 Git 提交读取")
        newer_commit = self._git.resolve_commit(newer_ref)
        return self._git.changed_paths_between(
            self.observed_commit,
            newer_commit,
        )

    def changes_from(self, base_ref: str) -> dict[str, Any]:
        """Compare a fixed base with this reader's commit or current worktree."""

        if self._git is None:
            self._git = _ReadOnlyGit(self.project)
        base_commit = self._git.resolve_commit(base_ref)
        return {
            "repository_id": self.repository_id,
            "base_commit": base_commit,
            "target_commit": self.observed_commit,
            "scope": "git_commit" if self.observed_commit is not None else "working_tree",
            "entries": self._git.change_entries(base_commit, self.observed_commit),
        }

    def resolve_commit(self, ref: str = "HEAD") -> str:
        """Resolve a selected ref without invoking the local-delivery module."""

        git = self._git or _ReadOnlyGit(self.project)
        return git.resolve_commit(ref)

    def is_ancestor(self, older_ref: str, newer_ref: str) -> bool:
        """Compare two immutable refs through the read-only Git boundary."""

        git = self._git or _ReadOnlyGit(self.project)
        older_commit = (
            older_ref
            if _COMMIT.fullmatch(str(older_ref))
            else git.resolve_commit(older_ref)
        )
        newer_commit = (
            newer_ref
            if _COMMIT.fullmatch(str(newer_ref))
            else git.resolve_commit(newer_ref)
        )
        return git.is_ancestor(older_commit, newer_commit)

    def pending_operations(self) -> list[str]:
        """Read this worktree's actual Git metadata, including linked trees."""
        git = self._git or _ReadOnlyGit(self.project)
        return git.pending_operations()

    def worktree_dirty(self) -> bool:
        """Return the native Git worktree state without persisting a shadow."""

        git = self._git or _ReadOnlyGit(self.project)
        return git.worktree_dirty()

    def tracked_paths(self, prefix: str | None = None) -> list[str]:
        """List project files at the selected commit or current working tree."""

        normalized_prefix = (
            repository_relative_path(prefix, "prefix")
            if prefix is not None and prefix != "."
            else None
        )
        if self.observed_commit is not None:
            assert self._git is not None
            return self._git.tracked_paths_at(
                self.observed_commit,
                prefix=normalized_prefix,
            )
        if self._git is None:
            try:
                self._git = _ReadOnlyGit(self.project)
            except GitProjectReaderError as error:
                marker = self.project / ".git"
                # An explicitly selected, unbound directory may live inside
                # another repository. Its working files remain local inputs;
                # the ancestor's identity and ignore rules are not its basis.
                # Exact-ref and bound-repository readers still require their
                # own verified Git root and never take this fallback.
                directory_only = (
                    error.code == "git_repository_mismatch"
                    and self._repository_scope is None
                    and not marker.exists()
                    and not marker.is_symlink()
                )
                if error.code not in {
                    "git_not_available",
                    "git_repository_required",
                } and not directory_only:
                    raise
        if self._git is not None:
            return self._git.worktree_paths(prefix=normalized_prefix)
        root = (
            self.absolute_path(normalized_prefix)
            if normalized_prefix is not None
            else self.project
        )
        if root.is_file():
            return [root.relative_to(self.project).as_posix()]
        if not root.exists():
            return []
        paths: list[str] = []
        for path in root.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            paths.append(path.relative_to(self.project).as_posix())
            if len(paths) > _MAX_WORKTREE_PATHS:
                raise GitProjectReaderError(
                    "非 Git 项目文件数量超过实现观察上限",
                    code="worktree_path_limit_exceeded",
                    details={"limit": _MAX_WORKTREE_PATHS},
                )
        return sorted(paths)

    def read_text(self, relative_path: str, label: str = "项目文件") -> str:
        normalized = repository_relative_path(relative_path)
        try:
            return self.read_bytes(normalized, label).decode("utf-8")
        except UnicodeError as error:
            raise GitProjectReaderError(
                f"{label} 必须是 UTF-8：{normalized}"
            ) from error

    def load_yaml(self, relative_path: str, label: str = "项目文件") -> Any:
        normalized = repository_relative_path(relative_path)
        try:
            return yaml.safe_load(self.read_text(normalized, label))
        except yaml.YAMLError as error:
            raise GitProjectReaderError(
                f"{label} YAML 无效：{normalized}"
            ) from error


def project_reader_for_scope(
    project_dir: str | Path,
    *,
    observed_ref: str | None = None,
    shared_reader: GitProjectReader | None = None,
) -> GitProjectReader:
    """Create or safely reuse one command-scoped project reader."""

    if shared_reader is None:
        return GitProjectReader(project_dir, observed_ref=observed_ref)
    project = Path(project_dir).expanduser().resolve()
    if shared_reader.project != project:
        raise GitProjectReaderError("共享项目读取器不属于请求的项目目录")
    if observed_ref is not None:
        resolved = shared_reader.resolve_commit(observed_ref)
        if shared_reader.observed_commit != resolved:
            raise GitProjectReaderError("共享项目读取器不属于请求的精确版本")
    return shared_reader


__all__ = [
    "FORBIDDEN_PROJECT_ROOTS",
    "GitProjectReader",
    "GitProjectReaderError",
    "RepositoryReadScope",
    "project_reader_for_scope",
    "repository_path_from_git",
    "repository_relative_path",
]
