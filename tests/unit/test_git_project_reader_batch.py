from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    _ReadOnlyGit,
)


def _git(project: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=project, input=data, capture_output=True, check=True
    ).stdout


def _project(path: Path) -> None:
    _git(path, "init", "-q")
    _git(path, "config", "user.name", "Reader Test")
    _git(path, "config", "user.email", "reader@example.invalid")
    _git(path, "config", "core.autocrlf", "false")


@pytest.mark.parametrize("count", [24, 160])
def test_batch_matches_actual_git_blobs_with_amortized_process_cost(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, count: int
) -> None:
    _project(tmp_path)
    (tmp_path / ".gitattributes").write_text(
        "* text=auto\n*.bin -text\n*.explicit text\n", encoding="utf-8"
    )
    payloads = {
        f"file-{index}.txt": f"line {index}\r\nnext\r\n".encode()
        for index in range(count)
    }
    payloads.update({
        "raw.bin": b"zero\x00\r\nbytes",
        "data.explicit": b"zero\x00\r\nbytes",
        "space name.txt": b"space\r\n",
        "记录.txt": "正文\r\n".encode(),
        "-leading.txt": b"leading\r\n",
    })
    for name, content in payloads.items():
        (tmp_path / name).write_bytes(content)
    calls: list[list[str]] = []
    original = _ReadOnlyGit._run

    def counted(self, arguments, **kwargs):
        calls.append(arguments)
        return original(self, arguments, **kwargs)

    monkeypatch.setattr(_ReadOnlyGit, "_run", counted)
    actual = dict(GitProjectReader(tmp_path).iter_canonical_files(list(payloads)))
    assert len(calls) <= max(12, len(payloads) // 4)
    assert set(actual) == set(payloads)
    assert all((tmp_path / name).read_bytes() == raw for name, raw in payloads.items())
    _git(tmp_path, "add", "--", ".")
    _git(tmp_path, "commit", "-qm", "record native Git normalization")
    for name, content in actual.items():
        assert content == _git(tmp_path, "show", f"HEAD:{name}")


def test_batches_observe_index_attributes_and_contents_again_on_same_reader(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    attributes = tmp_path / ".gitattributes"
    attributes.write_text("* text=auto\n", encoding="utf-8")
    target = tmp_path / "data.txt"
    target.write_bytes(b"current\r\n")
    old = _git(tmp_path, "hash-object", "-w", "--stdin", data=b"old\r\n").decode().strip()
    _git(tmp_path, "update-index", "--add", "--cacheinfo", "100644", old, "data.txt")
    reader = GitProjectReader(tmp_path)
    assert dict(reader.iter_canonical_files(["data.txt"])) == {"data.txt": b"current\r\n"}
    changed = _git(tmp_path, "hash-object", "-w", "--stdin", data=b"old\n").decode().strip()
    _git(tmp_path, "update-index", "--cacheinfo", "100644", changed, "data.txt")
    assert dict(reader.iter_canonical_files(["data.txt"])) == {"data.txt": b"current\n"}
    attributes.write_text("* -text\n", encoding="utf-8")
    target.write_bytes(b"new\r\n")
    assert dict(reader.iter_canonical_files(["data.txt"])) == {"data.txt": b"new\r\n"}


@pytest.mark.parametrize("attribute", [
    "filter=unspecified", "-filter", "ident=unset", "working-tree-encoding=unspecified",
])
def test_batch_keeps_explicit_conversion_rejection(
    tmp_path: Path, attribute: str,
) -> None:
    _project(tmp_path)
    (tmp_path / ".gitattributes").write_text(
        f"* text=auto\ndata.txt {attribute}\n", encoding="utf-8"
    )
    (tmp_path / "data.txt").write_bytes(b"body\r\n")
    with pytest.raises(GitProjectReaderError) as captured:
        dict(GitProjectReader(tmp_path).iter_canonical_files(["data.txt"]))
    assert captured.value.code == "git_conversion_unsafe"
    assert (tmp_path / "data.txt").read_bytes() == b"body\r\n"


def test_immutable_batch_ignores_later_worktree_content_and_attributes(
    tmp_path: Path,
) -> None:
    _project(tmp_path)
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / "data.txt").write_bytes(b"accepted\r\n")
    _git(tmp_path, "add", "--", ".")
    _git(tmp_path, "commit", "-qm", "record immutable source")
    expected = _git(tmp_path, "show", "HEAD:data.txt")
    reader = GitProjectReader(tmp_path, observed_ref="HEAD")
    (tmp_path / ".gitattributes").write_text("* filter=unsafe\n", encoding="utf-8")
    (tmp_path / "data.txt").write_bytes(b"unaccepted change\r\n")
    assert dict(reader.iter_canonical_files(["data.txt"])) == {"data.txt": expected}


def test_batch_rejects_unmerged_index_entries(tmp_path: Path) -> None:
    _project(tmp_path)
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / "data.txt").write_bytes(b"worktree\r\n")
    oid = _git(tmp_path, "hash-object", "-w", "--stdin", data=b"base\n").decode().strip()
    _git(tmp_path, "update-index", "--index-info", data=(
        f"100644 {oid} 1\tdata.txt\n100644 {oid} 2\tdata.txt\n"
    ).encode())
    with pytest.raises(GitProjectReaderError, match="暂存区"):
        dict(GitProjectReader(tmp_path).iter_canonical_files(["data.txt"]))


def test_cached_immutable_blob_keeps_the_worktree_index_size_limit(
    tmp_path: Path,
) -> None:
    from strixnova.git_project_reader import _MAX_GIT_INPUT_BYTES

    _project(tmp_path)
    (tmp_path / ".gitattributes").write_text("* text=auto\n", encoding="utf-8")
    (tmp_path / "data.txt").write_bytes(b"x" * (_MAX_GIT_INPUT_BYTES + 1))
    _git(tmp_path, "add", "--", ".")
    _git(tmp_path, "commit", "-qm", "record an immutable large blob")
    commit = _git(tmp_path, "rev-parse", "HEAD").decode().strip()
    git_reader = _ReadOnlyGit(tmp_path)
    assert len(git_reader.read_file_at(commit, "data.txt")) > _MAX_GIT_INPUT_BYTES
    (tmp_path / "data.txt").write_bytes(b"small\r\n")
    with pytest.raises(GitProjectReaderError, match="上限"):
        git_reader.canonical_worktree_files({"data.txt": b"small\r\n"})


@pytest.mark.parametrize("path", ["../outside.txt", ".git/config", ".strixnova/authority.sqlite3"])
def test_batch_does_not_expand_repository_path_authority(
    tmp_path: Path, path: str,
) -> None:
    _project(tmp_path)
    with pytest.raises(GitProjectReaderError) as captured:
        dict(GitProjectReader(tmp_path).iter_canonical_files([path]))
    assert captured.value.code == "repository_path_invalid"
