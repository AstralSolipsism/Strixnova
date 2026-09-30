from pathlib import Path

import pytest

from tests.support.project_context import git, repository


def package(root: Path, attributes: str):
    repository(root)
    path = root / "strixnova/src/strixnova/example.py"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"first\r\nsecond\n")
    (root / ".gitattributes").write_text(attributes, encoding="utf-8")
    git(root, "add", ".")
    return path


def test_package_checkout_preserves_explicit_original_bytes_and_git_index(tmp_path):
    from scripts.check_package_checkout import check_package_checkout
    root = tmp_path / "repo"
    package(root, "* text=auto eol=lf\nstrixnova/src/strixnova/example.py -text\n")
    index = (root / ".git/index").read_bytes()
    result = check_package_checkout(root, tmp_path / "work")
    assert result["status"] == "passed" and result["checked_files"] == 1
    assert (root / ".git/index").read_bytes() == index
    assert not list((tmp_path / "work").iterdir())


def test_package_checkout_detects_conversion_and_unstaged_code(tmp_path):
    from scripts.check_package_checkout import check_package_checkout
    root = tmp_path / "repo"
    path = package(root, "* text=auto eol=lf\n")
    result = check_package_checkout(root, tmp_path / "work")
    assert result["status"] == "mismatch"
    assert result["differences"] == ["strixnova/src/strixnova/example.py"]
    path.write_bytes(b"new code\n")
    assert check_package_checkout(root, tmp_path / "work")["status"] == "mismatch"


def test_package_checkout_reports_new_source_and_refuses_conversion_hooks(tmp_path):
    from scripts.check_package_checkout import check_package_checkout
    from strixnova.git_project_reader import GitProjectReaderError
    root = tmp_path / "repo"
    path = package(root, "* -text\n")
    new = path.with_name("new.py")
    new.write_bytes(b"new\n")
    result = check_package_checkout(root, tmp_path / "work")
    assert result["untracked_sources"] == ["strixnova/src/strixnova/new.py"]
    new.unlink()
    (root / ".gitattributes").write_text("* filter=forbidden\n", encoding="utf-8")
    # No filter is configured or invoked: the reader rejects the attribute first.
    with pytest.raises(GitProjectReaderError):
        check_package_checkout(root, tmp_path / "work")


def test_package_checkout_checks_wheel_bytes_and_requires_staged_attributes(tmp_path):
    from scripts.check_package_checkout import check_package_checkout
    from zipfile import ZipFile
    root = tmp_path / "repo"
    path = package(root, "* -text\n")
    wheel = tmp_path / "candidate.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("strixnova/example.py", path.read_bytes())
    assert check_package_checkout(root, tmp_path / "work", wheel=wheel)["status"] == "passed"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("strixnova/example.py", b"other version")
    assert check_package_checkout(root, tmp_path / "work", wheel=wheel)["wheel_differences"] == ["strixnova/example.py"]
    (root / ".gitattributes").write_text("* text eol=lf\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Stage attribute"):
        check_package_checkout(root, tmp_path / "work")


def test_checkout_does_not_certify_untracked_or_local_only_attributes(tmp_path):
    from scripts.check_package_checkout import check_package_checkout
    root = tmp_path / "repo"
    path = package(root, "* -text\n")
    attributes = path.parent / ".gitattributes"
    attributes.write_text("* -text\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Stage attribute"):
        check_package_checkout(root, tmp_path / "work")
    attributes.unlink()
    (root / ".git/info/attributes").write_text("* -text\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Local-only"):
        check_package_checkout(root, tmp_path / "work")


@pytest.mark.parametrize("mutation", [
    "new_source", "removed_source", "staged_attributes", "working_attributes",
    "new_attributes", "conversion_config",
])
@pytest.mark.parametrize("phase", ["checkout", "wheel"])
def test_checkout_rejects_input_changes_before_returning_success(tmp_path, monkeypatch, mutation, phase):
    from scripts import check_package_checkout as module
    from zipfile import ZipFile
    root = tmp_path / "repo"
    path = package(root, "* -text\n")
    if mutation == "conversion_config":
        path.write_bytes(b"first\nsecond\n")
        (root / ".gitattributes").write_bytes(b"* text\n")
        git(root, "add", ".")
    wheel = tmp_path / "candidate.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("strixnova/example.py", path.read_bytes())
    mutated = False

    def change_inputs():
        nonlocal mutated
        if mutated:
            return
        mutated = True
        if mutation == "new_source":
            path.with_name("new.py").write_bytes(b"new = 2\n")
        elif mutation == "removed_source":
            path.unlink()
        elif mutation == "conversion_config":
            git(root, "config", "core.autocrlf", "true")
        elif mutation == "new_attributes":
            (path.parent / ".gitattributes").write_bytes(b"* text eol=crlf\n")
        else:
            (root / ".gitattributes").write_bytes(b"* text eol=crlf\n")
            if mutation == "staged_attributes":
                git(root, "add", ".gitattributes")

    native_git = module._git

    def git_during_inspection(project, *arguments, data=None):
        result = native_git(project, *arguments, data=data)
        if phase == "checkout" and arguments[0] == "checkout-index":
            change_inputs()
        return result

    class WheelDuringInspection(ZipFile):
        def read(self, *args, **kwargs):
            if phase == "wheel":
                change_inputs()
            return super().read(*args, **kwargs)

    monkeypatch.setattr(module, "_git", git_during_inspection)
    monkeypatch.setattr(module, "ZipFile", WheelDuringInspection)
    with pytest.raises(ValueError, match="changed during inspection"):
        module.check_package_checkout(root, tmp_path / "work", wheel=wheel)
    assert mutated
    assert not list((tmp_path / "work").iterdir())
