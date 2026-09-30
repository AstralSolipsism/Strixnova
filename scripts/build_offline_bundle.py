"""Assemble a fixed offline bundle from an already built clean wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZIP_DEFLATED, ZipFile

from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "strixnova/src"))
sys.path.insert(0, str(ROOT))

from strixnova.managed_installation import ManagedInstallation
from strixnova.runtime_identity import locked_dependencies
from scripts.offline_install import inspect_bundle


def build_bundle(wheel: Path, wheelhouse: Path, output_dir: Path) -> dict:
    wheel, wheelhouse, output_dir = wheel.resolve(), wheelhouse.resolve(), output_dir.resolve()
    archive_path = output_dir.with_name(output_dir.name + ".zip")
    if output_dir.exists() or archive_path.exists():
        raise ValueError("Bundle output must be a new directory")
    target = ManagedInstallation.inspect(wheel)
    with ZipFile(wheel) as archive:
        compatibility = json.loads(archive.read("strixnova/resources/runtime-compatibility-v1.json"))
    required = locked_dependencies(compatibility["dependency_lock"]["requirements"])
    supported_tags = set(cpython_tags((3, 12), abis=["cp312"], platforms=["win_amd64"]))
    supported_tags.update(compatible_tags((3, 12), interpreter="cp312", platforms=["win_amd64"]))
    selected = {}
    for candidate in sorted(wheelhouse.glob("*.whl")):
        if candidate.is_symlink() or candidate.is_junction():
            raise ValueError("Dependency wheel cannot be a link")
        name, _, _, tags = parse_wheel_filename(candidate.name)
        if not tags.intersection(supported_tags):
            continue
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        for requirement, permitted in required.items():
            if name == requirement and digest in permitted and requirement not in selected:
                selected[requirement] = candidate
    if set(selected) != set(required):
        raise ValueError("Missing locked wheels: " + ", ".join(sorted(set(required) - set(selected))))
    output_dir.mkdir(parents=True)
    (output_dir / "dependencies").mkdir()
    shutil.copyfile(wheel, output_dir / wheel.name)
    for candidate in selected.values():
        shutil.copyfile(candidate, output_dir / "dependencies" / candidate.name)
    shutil.copyfile(ROOT / "scripts/offline_install.py", output_dir / "install.py")
    shutil.copyfile(ROOT / "scripts/install_offline.ps1", output_dir / "install.ps1")
    guide = next((ROOT / "docs").glob("*/installation-and-first-use.md"))
    shutil.copyfile(guide, output_dir / "README.md")
    inventory = {
        p.relative_to(output_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output_dir.rglob("*")) if p.is_file()
    }
    manifest = {
        "schema_version": "strixnova.offline-bundle.v1", "version": target["version"],
        "python": "3.12", "platform": "win-amd64", "strixnova_wheel": wheel.name,
        "wheelhouse": "dependencies", "files": inventory,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    inspect_bundle(output_dir)
    with ZipFile(archive_path, "x", compression=ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, output_dir.name + "/" + path.relative_to(output_dir).as_posix())
    return {"bundle_directory": str(output_dir), "archive_path": str(archive_path), "sha256": hashlib.sha256(archive_path.read_bytes()).hexdigest(), "dependency_wheels": len(selected), "version": target["version"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--wheelhouse", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(build_bundle(args.wheel, args.wheelhouse, args.output_dir), ensure_ascii=False))
