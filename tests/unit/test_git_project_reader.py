from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest

import strixnova.git_project_reader as git_project_reader_module
from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
)


def _git(project: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def test_git_for_windows_cmd_wrapper_resolves_to_direct_binary(
    tmp_path: Path,
) -> None:
    wrapper = tmp_path / "cmd" / "git.exe"
    direct = tmp_path / "mingw64" / "bin" / "git.exe"
    wrapper.parent.mkdir(parents=True)
    direct.parent.mkdir(parents=True)
    wrapper.touch()
    direct.touch()

    assert git_project_reader_module._direct_git_executable(
        str(wrapper),
        windows=True,
    ) == str(direct.resolve())


def test_read_only_reader_distinguishes_ancestor_from_descendant(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    source = tmp_path / "behavior.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "behavior.py")
    _git(tmp_path, "commit", "-m", "base")
    base = _git(tmp_path, "rev-parse", "HEAD")

    source.write_text("VALUE = 1\n\n# ledger-only descendant\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "behavior.py")
    _git(tmp_path, "commit", "-m", "descendant")
    descendant = _git(tmp_path, "rev-parse", "HEAD")

    reader = GitProjectReader(tmp_path)
    assert reader.is_ancestor(base, descendant) is True
    assert reader.is_ancestor(descendant, base) is False


def test_worktree_paths_use_git_ignore_and_include_nonignored_untracked_files(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / ".gitignore").write_text(
        "node_modules/\ntarget/\n",
        encoding="utf-8",
    )
    (tmp_path / "tracked.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "tracked.py")
    (tmp_path / "new.py").write_text("VALUE = 2\n", encoding="utf-8")
    ignored = tmp_path / "node_modules" / "pkg" / "index.js"
    ignored.parent.mkdir(parents=True)
    ignored.write_text("export default 1;\n", encoding="utf-8")
    target = tmp_path / "target" / "debug" / "binary"
    target.parent.mkdir(parents=True)
    target.write_text("ignored\n", encoding="utf-8")

    assert GitProjectReader(tmp_path).tracked_paths() == [
        ".gitignore",
        "new.py",
        "tracked.py",
    ]


def test_unbound_directory_read_does_not_adopt_its_parent_repository(tmp_path):
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / "outside.txt").write_text("outside the selected project", encoding="utf-8")
    project = tmp_path / "independent-inputs"
    project.mkdir()
    (project / "source.txt").write_text("selected input", encoding="utf-8")

    assert GitProjectReader(project).tracked_paths() == ["source.txt"]
    assert not (project / ".git").exists()
    with pytest.raises(GitProjectReaderError) as caught:
        GitProjectReader(project, observed_ref="HEAD")
    assert caught.value.code == "git_repository_mismatch"


@pytest.mark.parametrize("root", ["../", "/", "C:/outside", "./", ".git"])
def test_scope_root_does_not_weaken_file_path_validation(root: str) -> None:
    assert git_project_reader_module.repository_scope_root(".") == "."
    with pytest.raises(GitProjectReaderError):
        git_project_reader_module.repository_relative_path(".")
    with pytest.raises(GitProjectReaderError):
        git_project_reader_module.repository_scope_root(root)


def test_root_scope_respects_git_ignore_at_worktree_and_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / ".gitignore").write_text("ignored.py\n", encoding="utf-8")
    (tmp_path / "main.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "ignored.py").write_text("ignored\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "main.py")
    _git(tmp_path, "commit", "-m", "root source")
    commit = _git(tmp_path, "rev-parse", "HEAD")
    assert GitProjectReader(tmp_path).tracked_paths(".") == [".gitignore", "main.py"]
    assert GitProjectReader(tmp_path, observed_ref=commit).tracked_paths(".") == [".gitignore", "main.py"]


def test_immutable_reader_batches_exact_blob_objects_without_git_show(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / "a.txt").write_text("same\n", encoding="utf-8")
    (tmp_path / "copy.txt").write_text("same\n", encoding="utf-8")
    (tmp_path / "binary.bin").write_bytes(b"\x00payload\xff\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "add immutable files")

    calls: list[tuple[tuple[str, ...], bytes | None]] = []
    original = git_project_reader_module.run_process

    def counted(command, **kwargs):
        calls.append((tuple(command[1:]), kwargs.get("stdin_bytes")))
        return original(command, **kwargs)

    monkeypatch.setattr(git_project_reader_module, "run_process", counted)
    reader = GitProjectReader(tmp_path, observed_ref="HEAD")
    reader.prefetch(["a.txt", "copy.txt", "binary.bin"])

    assert reader.read_bytes("a.txt") in {b"same\n", b"same\r\n"}
    assert reader.read_bytes("copy.txt") == reader.read_bytes("a.txt")
    assert reader.read_bytes("binary.bin") == b"\x00payload\xff\n"
    assert reader.exists("missing.txt") is False
    assert reader.tracked_paths() == ["a.txt", "binary.bin", "copy.txt"]
    arguments = [item[0] for item in calls]
    assert not any("show" in item for item in arguments)
    batch_inputs = [
        stdin_bytes
        for arguments, stdin_bytes in calls
        if "cat-file" in arguments and "--batch" in arguments
    ]
    assert len(batch_inputs) == 1
    assert batch_inputs[0] is not None
    assert len(batch_inputs[0].splitlines()) == 2


def test_immutable_reader_falls_back_when_batch_command_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / "a.txt").write_bytes(b"first\n")
    (tmp_path / "b.txt").write_bytes(b"second\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "record objects")
    original = git_project_reader_module._ReadOnlyGit._run

    def fail_batch(self, arguments, **kwargs):
        if arguments == ["cat-file", "--batch"]:
            raise GitProjectReaderError("injected batch failure")
        return original(self, arguments, **kwargs)

    monkeypatch.setattr(
        git_project_reader_module._ReadOnlyGit,
        "_run",
        fail_batch,
    )
    reader = GitProjectReader(tmp_path, observed_ref="HEAD")
    reader.prefetch(["a.txt", "b.txt"])

    assert reader.read_bytes("a.txt") == b"first\n"
    assert reader.read_bytes("b.txt") == b"second\n"


def test_working_tree_canonical_bytes_match_the_future_git_blob(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / ".gitattributes").write_text(
        "* text=auto eol=lf\n",
        encoding="utf-8",
    )
    source = tmp_path / "behavior.py"
    source.write_bytes(b"VALUE = 1\r\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "base")

    source.write_bytes(b"VALUE = 2\r\n")
    original = git_project_reader_module.run_process

    def reject_path_filtering_hash(command, **kwargs):
        if "hash-object" in command and any(
            str(argument).startswith("--path=") for argument in command
        ):
            raise AssertionError("规范字节读取不得调用路径过滤散列")
        return original(command, **kwargs)

    monkeypatch.setattr(
        git_project_reader_module,
        "run_process",
        reject_path_filtering_hash,
    )
    reader = GitProjectReader(tmp_path)

    assert reader.read_bytes("behavior.py") == b"VALUE = 2\r\n"
    canonical = reader.read_canonical_bytes("behavior.py", "行为文件")
    assert canonical == b"VALUE = 2\n"

    _git(tmp_path, "add", "--", "behavior.py")
    _git(tmp_path, "commit", "-m", "change")
    assert (
        GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
            "behavior.py"
        )
        == canonical
    )


@pytest.mark.parametrize(
    "content",
    [
        b"first\r\nsecond\r\n",
        b"first\rsecond\r\n",
        b"first\x01second\r\n",
        (b"A" * 8001) + b"\x00\r\n",
        (b"\x01" * 100) + b"\nX\r\n",
        (b"A" * 127) + b"\x1a\r\n",
        (b"A" * 127) + b"\r\n\x1a",
    ],
)
def test_auto_text_binary_classification_matches_the_committed_blob(
    tmp_path: Path,
    content: bytes,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / ".gitattributes").write_text(
        "*.dat text=auto eol=lf\n",
        encoding="utf-8",
    )
    target = tmp_path / "sample.dat"
    target.write_bytes(content)

    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "record sample")

    assert GitProjectReader(
        tmp_path,
        observed_ref="HEAD",
    ).read_bytes("sample.dat") == canonical


@pytest.mark.parametrize("content", [b"X\x01Y\r\n", b"X\x00Y\r\n"])
def test_explicit_text_normalizes_even_binary_looking_content(
    tmp_path: Path,
    content: bytes,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / ".gitattributes").write_text(
        "*.dat text eol=lf\n",
        encoding="utf-8",
    )
    target = tmp_path / "sample.dat"
    target.write_bytes(content)

    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "record explicit text")

    assert canonical == content.replace(b"\r\n", b"\n")
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == canonical


def test_auto_text_preserves_historical_crlf_blob_already_in_index(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    attributes = tmp_path / ".gitattributes"
    attributes.write_text("*.dat -text\n", encoding="utf-8")
    target = tmp_path / "sample.dat"
    target.write_bytes(b"first\r\nsecond\r\n")
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "record historical crlf")

    attributes.write_text("*.dat text=auto eol=lf\n", encoding="utf-8")
    target.write_bytes(b"changed\r\ncontent\r\n")
    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "preserve historical crlf")

    assert canonical == b"changed\r\ncontent\r\n"
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == canonical


def test_auto_text_does_not_preserve_crlf_from_binary_index_blob(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    attributes = tmp_path / ".gitattributes"
    attributes.write_text("*.dat -text\n", encoding="utf-8")
    target = tmp_path / "sample.dat"
    target.write_bytes(b"historical\r\n\x00")
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "record historical binary")

    attributes.write_text("*.dat text=auto eol=lf\n", encoding="utf-8")
    target.write_bytes(b"current\r\ntext\r\n")
    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "normalize current text")

    assert canonical == b"current\ntext\n"
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == canonical


@pytest.mark.parametrize("autocrlf", ["true", "input"])
def test_core_autocrlf_preserves_historical_crlf_blob_already_in_index(
    tmp_path: Path,
    autocrlf: str,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "config", "core.autocrlf", "false")
    target = tmp_path / "sample.dat"
    target.write_bytes(b"first\r\nsecond\r\n")
    _git(tmp_path, "add", "sample.dat")
    _git(tmp_path, "commit", "-m", "record historical crlf")

    _git(tmp_path, "config", "core.autocrlf", autocrlf)
    target.write_bytes(b"changed\r\ncontent\r\n")
    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", "sample.dat")
    _git(tmp_path, "commit", "-m", "preserve historical crlf")

    assert canonical == b"changed\r\ncontent\r\n"
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == canonical


@pytest.mark.parametrize(
    ("autocrlf", "expected"),
    [
        ("yes", b"first\nsecond\n"),
        ("on", b"first\nsecond\n"),
        ("1", b"first\nsecond\n"),
        ("no", b"first\r\nsecond\r\n"),
        ("off", b"first\r\nsecond\r\n"),
        ("0", b"first\r\nsecond\r\n"),
    ],
)
def test_core_autocrlf_accepts_git_boolean_aliases(
    tmp_path: Path,
    autocrlf: str,
    expected: bytes,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "core.autocrlf", autocrlf)
    (tmp_path / "sample.dat").write_bytes(b"first\r\nsecond\r\n")

    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )

    assert canonical == expected


@pytest.mark.parametrize("autocrlf", ["true", "input"])
def test_core_autocrlf_does_not_preserve_crlf_from_binary_index_blob(
    tmp_path: Path,
    autocrlf: str,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "config", "core.autocrlf", "false")
    target = tmp_path / "sample.dat"
    target.write_bytes(b"historical\r\n\x00")
    _git(tmp_path, "add", "sample.dat")
    _git(tmp_path, "commit", "-m", "record historical binary")

    _git(tmp_path, "config", "core.autocrlf", autocrlf)
    target.write_bytes(b"current\r\ntext\r\n")
    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", "sample.dat")
    _git(tmp_path, "commit", "-m", "normalize current text")

    assert canonical == b"current\ntext\n"
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == canonical


@pytest.mark.parametrize("content", [b"X\x01Y\r\n", b"X\x00Y\r\n"])
def test_explicit_eol_without_text_normalizes_binary_looking_content(
    tmp_path: Path,
    content: bytes,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / ".gitattributes").write_text(
        "*.dat eol=lf\n",
        encoding="utf-8",
    )
    target = tmp_path / "sample.dat"
    target.write_bytes(content)

    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "record eol text")

    assert canonical == content.replace(b"\r\n", b"\n")
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == canonical


@pytest.mark.parametrize(
    ("attribute", "expected"),
    [
        ("crlf", b"X\n"),
        ("-crlf", b"X\r\n"),
        ("crlf=input", b"X\n"),
    ],
)
def test_legacy_crlf_attribute_matches_git(
    tmp_path: Path,
    attribute: str,
    expected: bytes,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / ".gitattributes").write_text(
        f"*.dat {attribute}\n",
        encoding="utf-8",
    )
    target = tmp_path / "sample.dat"
    target.write_bytes(b"X\r\n")

    canonical = GitProjectReader(tmp_path).read_canonical_bytes(
        "sample.dat",
        "测试文件",
    )
    _git(tmp_path, "add", ".gitattributes", "sample.dat")
    _git(tmp_path, "commit", "-m", "record legacy crlf attribute")

    assert canonical == expected
    assert GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes(
        "sample.dat"
    ) == expected


def test_immutable_reader_rejects_git_symbolic_link_entry(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    result = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=tmp_path,
        input="target.py",
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    object_id = result.stdout.strip()
    _git(tmp_path, "update-index", "--add", "--cacheinfo", f"120000,{object_id},link.py")
    _git(tmp_path, "commit", "-m", "record symbolic link entry")

    with pytest.raises(GitProjectReaderError) as captured:
        GitProjectReader(tmp_path, observed_ref="HEAD").read_bytes("link.py")

    assert captured.value.code == "git_entry_mode_unsupported"


def test_read_only_git_commands_disable_locks_and_replace_objects(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    captured: list[dict[str, str]] = []
    original = git_project_reader_module.run_process

    def record_environment(command, **kwargs):
        captured.append(dict(kwargs["env"]))
        return original(command, **kwargs)

    monkeypatch.setattr(git_project_reader_module, "run_process", record_environment)
    git_project_reader_module._ReadOnlyGit(tmp_path)._run(["version"])

    assert captured[0]["GIT_OPTIONAL_LOCKS"] == "0"
    assert captured[0]["GIT_NO_REPLACE_OBJECTS"] == "1"
    assert captured[0]["GIT_NO_LAZY_FETCH"] == "1"


def test_old_git_rejects_partial_clone_before_any_object_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "remote.origin.promisor", "true")
    monkeypatch.setattr(
        git_project_reader_module._ReadOnlyGit,
        "_git_version",
        lambda self: (2, 40, 1),
    )

    with pytest.raises(GitProjectReaderError) as captured:
        git_project_reader_module._ReadOnlyGit(tmp_path)

    assert captured.value.code == "git_lazy_fetch_unsafe"


def test_worktree_canonical_reader_rejects_symbolic_links(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    target = tmp_path / "target.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    link = tmp_path / "behavior.py"
    try:
        link.symlink_to(target.name)
    except OSError as error:
        pytest.skip(f"当前测试主机不能创建符号链接：{error}")

    with pytest.raises(GitProjectReaderError) as captured:
        GitProjectReader(tmp_path).read_canonical_bytes(
            "behavior.py",
            "行为文件",
        )

    assert captured.value.code == "repository_symlink_forbidden"


@pytest.mark.parametrize(
    ("attribute", "configured_value"),
    [
        ("filter", "danger"),
        ("filter", "unset"),
        ("filter", "unspecified"),
        ("ident", "set"),
        ("working-tree-encoding", "UTF-16"),
    ],
)
def test_working_tree_canonical_bytes_reject_explicit_git_conversion_before_hash(
    tmp_path: Path,
    monkeypatch,
    attribute: str,
    configured_value: str,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / ".gitattributes").write_text(
        f"*.py {attribute}={configured_value}\n",
        encoding="utf-8",
    )
    (tmp_path / "behavior.py").write_text("VALUE = 1\n", encoding="utf-8")
    original = git_project_reader_module.run_process

    def reject_hash_object(command, **kwargs):
        if "hash-object" in command:
            raise AssertionError("不得调用可能执行外部 clean filter 的命令")
        return original(command, **kwargs)

    monkeypatch.setattr(
        git_project_reader_module,
        "run_process",
        reject_hash_object,
    )

    with pytest.raises(GitProjectReaderError) as captured:
        GitProjectReader(tmp_path).read_canonical_bytes(
            "behavior.py",
            "行为文件",
        )

    assert captured.value.code == "git_conversion_unsafe"
    assert attribute in captured.value.details["attributes"]


@pytest.mark.skipif(
    os.name == "nt",
    reason="Windows（视窗系统）不允许文件名包含反斜杠",
)
def test_git_returned_backslash_filename_is_rejected_without_aliasing(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    target = tmp_path / "a\\b.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "--", "a\\b.py")
    _git(tmp_path, "commit", "-m", "record backslash filename")

    with pytest.raises(GitProjectReaderError) as captured:
        GitProjectReader(tmp_path, observed_ref="HEAD").tracked_paths()

    assert captured.value.code == "git_path_unsupported"


def test_tracked_internal_path_does_not_block_an_allowed_immutable_read(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    internal = tmp_path / ".strixnova"
    internal.mkdir()
    (internal / ".gitignore").write_text("*\n", encoding="utf-8")
    (tmp_path / "allowed.txt").write_text("ok\n", encoding="utf-8")
    _git(tmp_path, "add", "-f", "--", ".strixnova/.gitignore", "allowed.txt")
    _git(tmp_path, "commit", "-m", "record internal marker")

    reader = GitProjectReader(tmp_path, observed_ref="HEAD")

    assert reader.read_text("allowed.txt") == "ok\n"
    with pytest.raises(GitProjectReaderError) as captured:
        reader.read_text(".strixnova/.gitignore")
    assert captured.value.code == "repository_path_invalid"
