"""Compare frozen package bytes with a real index checkout; never stage or build."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "strixnova/src") not in sys.path:
    sys.path.insert(0, str(ROOT / "strixnova/src"))

from scripts.build_clean_wheel import _ignored_source
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError


def _git(project: Path, *arguments: str, data: bytes | None = None) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_OPTIONAL_LOCKS="0", GIT_NO_LAZY_FETCH="1", GIT_TERMINAL_PROMPT="0")
    return subprocess.run(
        ["git", "-c", f"safe.directory={project.as_posix()}", "-c", "core.fsmonitor=false", *arguments],
        cwd=project, input=data, capture_output=True, check=True, env=env,
    ).stdout


def _package_paths(project: Path) -> list[str]:
    source = project / "strixnova/src/strixnova"
    if not source.is_dir() or source.is_symlink() or source.is_junction():
        raise ValueError("No Strixnova package source tree")
    paths = []
    for directory, folders, names in os.walk(source, followlinks=False):
        ignored = _ignored_source(directory, folders + names)
        for name in folders + names:
            target = Path(directory) / name
            if target.is_symlink() or target.is_junction():
                raise ValueError("Package checkout check does not follow links")
        folders[:] = [name for name in folders if name not in ignored]
        paths.extend((Path(directory) / name).relative_to(project).as_posix()
                     for name in names if name not in ignored)
    paths.sort()
    if not paths:
        raise ValueError("Package source tree is empty")
    return paths


def _checkout_attributes(project: Path, paths: list[str]) -> dict:
    # Use a fresh reader on every capture; a cached attribute lookup could hide
    # changes made while checkout or wheel comparison was running.
    reader = GitProjectReader(project)
    # Checkout attributes must belong to the staged candidate too. Otherwise a
    # local, unstaged attribute edit could conceal a conversion on a fresh clone.
    tracked_paths = set(_git(project, "ls-files", "--cached", "-z").decode("utf-8").split("\0"))
    attribute_paths = {path for path in tracked_paths if path and Path(path).name == ".gitattributes"}
    for path in paths:
        for parent in (project / path).parents:
            if not parent.is_relative_to(project):
                break
            candidate = parent / ".gitattributes"
            if candidate.exists():
                attribute_paths.add(candidate.relative_to(project).as_posix())
    attributes = {}
    for path in sorted(attribute_paths):
        if path not in tracked_paths:
            raise ValueError("Stage attribute changes before checking the package checkout")
        content = reader.read_canonical_bytes(path)
        if content != _git(project, "show", f":{path}"):
            raise ValueError("Stage attribute changes before checking the package checkout")
        attributes[path] = content
    local_attributes = Path(_git(project, "rev-parse", "--git-path", "info/attributes").decode().strip())
    if not local_attributes.is_absolute():
        local_attributes = project / local_attributes
    if local_attributes.is_file() and local_attributes.read_bytes().strip():
        raise ValueError("Local-only Git attributes cannot establish portable checkout bytes")
    configuration = {}
    for key in ("core.autocrlf", "core.eol", "core.attributesfile"):
        try:
            configuration[key] = _git(project, "config", "--get", key)
        except subprocess.CalledProcessError as error:
            if error.returncode != 1:
                raise
            configuration[key] = None
    return {
        "files": attributes,
        "effective": _git(project, "check-attr", "--all", "-z", "--stdin",
                          data=("\0".join(paths) + "\0").encode("utf-8")),
        "configuration": configuration,
    }


def check_package_checkout(project: Path, work: Path, *, wheel: Path | None = None) -> dict:
    project = project.resolve()
    source = project / "strixnova/src/strixnova"
    paths = _package_paths(project)
    # Validate attributes before checkout; conversions must not run project code.
    list(GitProjectReader(project).iter_canonical_files(paths, "package checkout preflight"))
    attributes = _checkout_attributes(project, paths)
    indexed = _git(project, "ls-files", "--stage", "-z", "--", "strixnova/src/strixnova").split(b"\0")
    staged = set()
    for row in indexed:
        if not row:
            continue
        metadata, raw_path = row.split(b"\t", 1)
        mode, _, stage = metadata.split()
        if mode not in {b"100644", b"100755"} or stage != b"0":
            raise ValueError("Package index contains a link, gitlink or unresolved merge")
        staged.add(raw_path.decode("utf-8"))
    untracked = sorted(set(paths) - staged)
    absent = sorted(staged - set(paths))
    work = work.resolve()
    if work == source or work.is_relative_to(source):
        raise ValueError("Checkout scratch directory must be outside the package")
    work.mkdir(parents=True, exist_ok=True)
    frozen = {path: (project / path).read_bytes() for path in paths}
    selected = sorted(staged & set(paths))
    differences = []
    with tempfile.TemporaryDirectory(prefix="package-checkout-", dir=work) as directory:
        checkout = Path(directory)
        if selected:
            _git(project, "checkout-index", f"--prefix={checkout.as_posix()}/", "--stdin", "-z",
                 data=("\0".join(selected) + "\0").encode("utf-8"))
        differences = [path for path in selected if (checkout / path).read_bytes() != frozen[path]]
    wheel_differences = []
    if wheel is not None:
        with ZipFile(wheel) as archive:
            packaged = {name: archive.read(name) for name in archive.namelist()
                        if name.startswith("strixnova/") and not name.endswith("/")}
        expected = {path.removeprefix("strixnova/src/"): content for path, content in frozen.items()}
        wheel_differences = sorted(path for path in set(packaged) | set(expected)
                                   if packaged.get(path) != expected.get(path))
    # Revalidate after all reads, including the optional wheel comparison.
    # Existing-file hashes alone miss new/removed paths; the package index alone
    # misses staged attributes outside that directory.
    try:
        if _package_paths(project) != paths:
            raise ValueError("Package path set changed")
        if any((project / path).read_bytes() != content for path, content in frozen.items()):
            raise ValueError("Package source content changed")
        if _checkout_attributes(project, paths) != attributes:
            raise ValueError("Checkout attributes changed")
        if _git(project, "ls-files", "--stage", "-z", "--", "strixnova/src/strixnova").split(b"\0") != indexed:
            raise ValueError("Package index changed")
    except (OSError, ValueError, GitProjectReaderError, subprocess.CalledProcessError) as error:
        raise ValueError("Package checkout inputs changed during inspection or are no longer readable") from error
    return {
        "status": "mismatch" if differences or untracked or absent or wheel_differences else "passed",
        "checked_files": len(selected), "differences": differences,
        "untracked_sources": untracked, "missing_sources": absent, "wheel_differences": wheel_differences,
        "wheel_checked": wheel is not None, "scope": "index_checkout_and_frozen_worktree_bytes",
        "semantic_content_machine_proven": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", type=Path, default=ROOT)
    parser.add_argument("--wheel", type=Path)
    options = parser.parse_args()
    work = os.environ.get("STRIXNOVA_VALIDATION_WORK")
    if not work:
        parser.error("Run through scripts/local_validation.py run")
    result = check_package_checkout(options.project_dir, Path(work), wheel=options.wheel)
    evidence = os.environ.get("STRIXNOVA_VALIDATION_EVIDENCE")
    if evidence:
        (Path(evidence) / "package-checkout.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
