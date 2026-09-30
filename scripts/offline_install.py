"""Standard-library bootstrap for the verified Windows/Python 3.12 bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import sysconfig


SCHEMA = "strixnova.offline-bundle.v1"


def bundle_file(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or "\\" in relative or ":" in relative:
        raise ValueError("Invalid bundle file path")
    parts = PurePosixPath(relative)
    if parts.is_absolute() or ".." in parts.parts or parts.as_posix() != relative:
        raise ValueError("Bundle paths must be ordinary relative paths")
    path = root.joinpath(*parts.parts)
    for candidate in (path, *path.parents):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Bundle files cannot use links")
        if candidate == root:
            break
    if not path.is_file():
        raise ValueError("Bundle file is missing: " + relative)
    return path


def inspect_bundle(root: Path) -> dict:
    root = root.absolute()
    manifest_path = bundle_file(root, "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if set(manifest) != {"schema_version", "version", "python", "platform", "strixnova_wheel", "wheelhouse", "files"} or manifest["schema_version"] != SCHEMA:
        raise ValueError("Unsupported offline bundle manifest")
    if manifest["python"] != "3.12" or manifest["platform"] != "win-amd64":
        raise ValueError("This bundle supports Windows x64 and Python 3.12")
    entries = manifest["files"]
    if not isinstance(entries, dict) or not entries or len(entries) > 1000:
        raise ValueError("Invalid bundle inventory")
    if not {"install.py", "install.ps1", "README.md"} <= set(entries):
        raise ValueError("Bundle is missing its installation entry or instructions")
    folded = set()
    for relative, expected in entries.items():
        path = bundle_file(root, relative)
        if relative.casefold() in folded or not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
            raise ValueError("Invalid or duplicate bundle digest")
        folded.add(relative.casefold())
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != expected:
            raise ValueError("Bundle content changed: " + relative)
    wheel = manifest["strixnova_wheel"]
    if wheel not in entries or not wheel.endswith(".whl"):
        raise ValueError("The Strixnova wheel is not bound by the manifest")
    # pip scans this directory; reject unlisted wheels rather than letting an
    # extra archive participate in dependency selection.
    wheelhouse = manifest["wheelhouse"]
    if wheelhouse != "dependencies":
        raise ValueError("Unsupported dependency directory")
    actual_dependencies = {p.relative_to(root).as_posix() for p in (root / wheelhouse).glob("*.whl")}
    declared_dependencies = {p for p in entries if p.startswith(wheelhouse + "/")}
    if not actual_dependencies or actual_dependencies != declared_dependencies:
        raise ValueError("Dependency directory differs from the bundle inventory")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-dir", required=True, type=Path)
    parser.add_argument("--installation-root", required=True, type=Path)
    parser.add_argument("--skills-dir", type=Path)
    parser.add_argument("--replace-skill", action="store_true")
    args = parser.parse_args(argv)
    try:
        if sys.version_info[:2] != (3, 12):
            raise ValueError("Python 3.12 is required; this installer does not install Python")
        if sysconfig.get_platform() != "win-amd64":
            raise ValueError("This bundle requires Windows x64 Python")
        if shutil.which("git") is None:
            raise ValueError("Git is required; this installer does not install Git")
        root = Path(__file__).absolute().parent
        manifest = inspect_bundle(root)
        wheel = bundle_file(root, manifest["strixnova_wheel"])
        # -I -S plus the verified wheel keeps existing Strixnova installations and
        # site packages out of the bootstrap. The imported install path is stdlib-only.
        if any(name == "strixnova" or name.startswith("strixnova.") for name in sys.modules):
            raise ValueError("Run the standalone bundle installer in a fresh Python process")
        sys.path.insert(0, str(wheel))
        from strixnova.initial_installation import install_initial_runtime
        from strixnova.managed_installation import ManagedInstallation

        if ManagedInstallation.inspect(wheel)["version"] != manifest["version"]:
            raise ValueError("Bundle version differs from its Strixnova wheel")

        result = install_initial_runtime(
            args.project_dir, args.installation_root, wheel, root / manifest["wheelhouse"],
            builder_python=sys.executable, skills_dir=args.skills_dir, replace_skill=args.replace_skill,
        )
        print(json.dumps({"ok": True, "installation": result}, ensure_ascii=True))
        return 0
    except Exception as error:
        print(json.dumps({"ok": False, "error": {"code": getattr(error, "code", "offline_installation_failed"), "message": str(error), "details": getattr(error, "details", None)}}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
