"""Build one wheel from a clean source snapshot and verify packaged content."""

from __future__ import annotations

import argparse
import ast
from email.parser import Parser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Iterable
from zipfile import ZipFile

try:
    from scripts.check_skill_cn_sync import (
        SkillCnSyncError,
        validate_skill_cn_sync,
    )
except ModuleNotFoundError:  # Direct ``python scripts/build_clean_wheel.py``.
    from check_skill_cn_sync import SkillCnSyncError, validate_skill_cn_sync

try:
    from scripts.skill_bundle_manifest import (
        SkillBundleManifestError,
        directory_manifest,
        wheel_manifest,
    )
except ModuleNotFoundError:  # Direct ``python scripts/build_clean_wheel.py``.
    from skill_bundle_manifest import (
        SkillBundleManifestError,
        directory_manifest,
        wheel_manifest,
    )

try:
    from scripts.third_party_notice import (
        ThirdPartyNoticeError,
        append_notice_to_staged_readme,
        notice_sha256,
        project_notice,
        verify_wheel_notice,
    )
except ModuleNotFoundError:  # Direct ``python scripts/build_clean_wheel.py``.
    from third_party_notice import (
        ThirdPartyNoticeError,
        append_notice_to_staged_readme,
        notice_sha256,
        project_notice,
        verify_wheel_notice,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PROJECT = REPOSITORY_ROOT / "strixnova"
DEFAULT_OUTPUT_DIR = SOURCE_PROJECT / "dist"
IGNORED_SOURCE_NAMES = {
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
}


class CleanWheelBuildError(RuntimeError):
    """The clean source build or packaged-resource verification failed."""


def _ignored_source(
    _directory: str,
    names: list[str],
) -> set[str]:
    return {
        name
        for name in names
        if name in IGNORED_SOURCE_NAMES
        or name.endswith(".egg-info")
        or name.endswith((".pyc", ".pyo"))
    }


def stage_project(source_project: Path, staged_project: Path) -> None:
    """Copy only build inputs, excluding every known generated source tree."""

    source_project = source_project.resolve()
    staged_project.mkdir(parents=True, exist_ok=False)
    for name in ("pyproject.toml", "README.md"):
        source = source_project / name
        if not source.is_file():
            raise CleanWheelBuildError(f"缺少 wheel 构建输入：{source}")
        shutil.copy2(source, staged_project / name)
    source_tree = source_project / "src"
    if not source_tree.is_dir():
        raise CleanWheelBuildError(f"缺少 wheel 源码目录：{source_tree}")
    shutil.copytree(
        source_tree,
        staged_project / "src",
        ignore=_ignored_source,
    )


def _source_resource_files(resource_root: Path) -> dict[str, bytes]:
    if not resource_root.is_dir():
        raise CleanWheelBuildError(f"缺少随包资源目录：{resource_root}")
    resources: dict[str, bytes] = {}
    for path in sorted(resource_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(resource_root)
        if any(part in IGNORED_SOURCE_NAMES for part in relative.parts):
            continue
        if path.name.endswith((".pyc", ".pyo")):
            continue
        resources[relative.as_posix()] = path.read_bytes()
    return resources


def verify_wheel_resources(wheel_path: Path, resource_root: Path) -> int:
    """Require the wheel resource tree to equal the current source byte-for-byte."""

    expected = _source_resource_files(resource_root)
    prefix = "strixnova/resources/"
    with ZipFile(wheel_path) as archive:
        actual_names = {
            name[len(prefix) :]
            for name in archive.namelist()
            if name.startswith(prefix) and not name.endswith("/")
        }
        missing = sorted(set(expected) - actual_names)
        unexpected = sorted(actual_names - set(expected))
        changed = sorted(
            name
            for name, content in expected.items()
            if name in actual_names and archive.read(prefix + name) != content
        )
    if missing or unexpected or changed:
        details: list[str] = []
        if missing:
            details.append("缺失=" + ", ".join(missing))
        if unexpected:
            details.append("多余=" + ", ".join(unexpected))
        if changed:
            details.append("字节不一致=" + ", ".join(changed))
        raise CleanWheelBuildError("wheel 随包资源与当前源码不一致：" + "；".join(details))
    return len(expected)


def verify_review_material_excluded(wheel_path: Path) -> None:
    """Reject any review-only translation material anywhere in the wheel."""

    with ZipFile(wheel_path) as archive:
        prohibited = [
            name
            for name in archive.namelist()
            if "skills-cn" in PurePosixPath(name).parts
            or ".zh-cn." in name.casefold()
            or name.endswith("sync-manifest.v1.json")
        ]
    if prohibited:
        raise CleanWheelBuildError(
            "wheel 不得包含中文审阅专用材料：" + ", ".join(prohibited)
        )


def verify_wheel_skill_bundle(
    wheel_path: Path,
    source_skill_root: Path,
) -> dict[str, object]:
    """Bind source and wheel to one metadata-independent Skill fingerprint."""

    try:
        source = directory_manifest(source_skill_root)
        packaged = wheel_manifest(wheel_path)
    except SkillBundleManifestError as error:
        raise CleanWheelBuildError(str(error)) from error
    if packaged != source:
        raise CleanWheelBuildError("wheel Skill 内容指纹与当前源码不一致")
    return source


def _module_docstring(content: str, *, source: str) -> str | None:
    try:
        module = ast.parse(content, filename=source)
    except SyntaxError as error:
        raise CleanWheelBuildError(f"无法解析模块说明：{source}") from error
    return ast.get_docstring(module, clean=False)


def verify_wheel_identity(wheel_path: Path, source_project: Path) -> None:
    """Require public wheel identity to equal the current source declarations."""

    pyproject_path = source_project / "pyproject.toml"
    init_path = source_project / "src" / "strixnova" / "__init__.py"
    try:
        project = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))["project"]
        expected_summary = project["description"]
    except (KeyError, tomllib.TOMLDecodeError) as error:
        raise CleanWheelBuildError(
            f"无法读取源码包摘要：{pyproject_path}"
        ) from error
    expected_docstring = _module_docstring(
        init_path.read_text(encoding="utf-8"),
        source=str(init_path),
    )

    with ZipFile(wheel_path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise CleanWheelBuildError(
                "wheel 必须恰好包含一份 dist-info/METADATA，"
                f"实际为 {len(metadata_names)}"
            )
        try:
            metadata_content = archive.read(metadata_names[0]).decode("utf-8")
            init_content = archive.read("strixnova/__init__.py").decode("utf-8")
        except (KeyError, UnicodeDecodeError) as error:
            raise CleanWheelBuildError("wheel 缺少可解析的公开身份内容") from error

    actual_summary = Parser().parsestr(metadata_content).get("Summary")
    actual_docstring = _module_docstring(
        init_content,
        source=f"{wheel_path}!/strixnova/__init__.py",
    )
    differences: list[str] = []
    if actual_summary != expected_summary:
        differences.append("包摘要")
    if actual_docstring != expected_docstring:
        differences.append("模块说明")
    if differences:
        raise CleanWheelBuildError(
            "wheel 公开身份与当前源码不一致：" + "、".join(differences)
        )


def _wheel_files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.glob("*.whl") if path.is_file())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_clean_wheel(
    *,
    source_project: Path = SOURCE_PROJECT,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> dict[str, object]:
    """Build in a temporary source tree and publish only a verified wheel."""

    source_project = source_project.resolve()
    output_dir = output_dir.resolve()
    runtime_contract = source_project / "src/strixnova/resources/runtime-compatibility-v1.json"
    if source_project == SOURCE_PROJECT.resolve():
        try:
            try:
                from scripts.update_runtime_compatibility import expected_bytes
            except ModuleNotFoundError:
                from update_runtime_compatibility import expected_bytes
            if not runtime_contract.is_file() or runtime_contract.read_bytes() != expected_bytes():
                raise CleanWheelBuildError("随包运行兼容清单与源依赖锁或已实现转换链不一致")
        except (OSError, ValueError) as error:
            raise CleanWheelBuildError("无法核对运行兼容清单") from error
    try:
        third_party_notice = project_notice(source_project)
    except ThirdPartyNoticeError as error:
        raise CleanWheelBuildError(str(error)) from error
    if source_project == SOURCE_PROJECT.resolve() and third_party_notice is None:
        raise CleanWheelBuildError("仓库根 README 缺少第三方方法声明")
    skill_root = (
        source_project
        / "src"
        / "strixnova"
        / "resources"
        / "agent-skill"
        / "strixnova"
    )
    source_skill_manifest: dict[str, object] | None = None
    if skill_root.is_dir():
        try:
            sync_result = validate_skill_cn_sync(
                source_root=skill_root,
                review_root=source_project.parent / "skills-cn" / "strixnova",
            )
            source_skill_manifest = directory_manifest(skill_root)
        except (SkillCnSyncError, SkillBundleManifestError) as error:
            raise CleanWheelBuildError(str(error)) from error
        if (
            sync_result["skill_bundle_manifest_sha256"]
            != source_skill_manifest["sha256"]
        ):
            raise CleanWheelBuildError("中文审阅同步检查绑定了不同的 Skill 内容指纹")
    with tempfile.TemporaryDirectory(prefix="strixnova-clean-wheel-") as temporary:
        temporary_root = Path(temporary)
        staged_project = temporary_root / "strixnova"
        staged_dist = temporary_root / "dist"
        stage_project(source_project, staged_project)
        if third_party_notice is not None:
            try:
                append_notice_to_staged_readme(
                    staged_project,
                    third_party_notice,
                )
            except ThirdPartyNoticeError as error:
                raise CleanWheelBuildError(str(error)) from error
        staged_dist.mkdir()
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--wheel",
                "--no-isolation",
                "--outdir",
                str(staged_dist),
                str(staged_project),
            ],
            cwd=REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.stdout:
            sys.stderr.write(completed.stdout)
        if completed.stderr:
            sys.stderr.write(completed.stderr)
        if completed.returncode != 0:
            raise CleanWheelBuildError(
                f"干净 wheel 构建失败，退出码 {completed.returncode}"
            )
        wheels = _wheel_files(staged_dist)
        if len(wheels) != 1:
            raise CleanWheelBuildError(
                f"干净构建必须恰好产生一个 wheel，实际为 {len(wheels)}"
            )
        staged_wheel = wheels[0]
        resource_count = verify_wheel_resources(
            staged_wheel,
            source_project / "src" / "strixnova" / "resources",
        )
        verify_wheel_identity(staged_wheel, source_project)
        verify_review_material_excluded(staged_wheel)
        if third_party_notice is not None:
            try:
                verify_wheel_notice(staged_wheel, third_party_notice)
            except ThirdPartyNoticeError as error:
                raise CleanWheelBuildError(str(error)) from error
        if source_skill_manifest is not None:
            packaged_skill_manifest = verify_wheel_skill_bundle(
                staged_wheel,
                skill_root,
            )
            if packaged_skill_manifest != source_skill_manifest:
                raise CleanWheelBuildError("构建期间 Skill 内容发生变化")
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / staged_wheel.name
        handle, temporary_name = tempfile.mkstemp(
            prefix=target.name + ".",
            suffix=".tmp",
            dir=output_dir,
        )
        os.close(handle)
        temporary_target = Path(temporary_name)
        try:
            shutil.copy2(staged_wheel, temporary_target)
            os.replace(temporary_target, target)
        finally:
            temporary_target.unlink(missing_ok=True)
    result: dict[str, object] = {
        "wheel_path": str(target),
        "sha256": _sha256(target),
        "resource_count": resource_count,
    }
    if source_skill_manifest is not None:
        result["skill_bundle_file_count"] = source_skill_manifest["file_count"]
        result["skill_bundle_manifest_sha256"] = source_skill_manifest["sha256"]
    if third_party_notice is not None:
        result["third_party_notice_sha256"] = notice_sha256(third_party_notice)
    return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从干净源码快照构建并核验 Strixnova wheel。"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="通过核验后写入 wheel 的目录，默认 strixnova/dist。",
    )
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        result = build_clean_wheel(output_dir=options.output_dir)
    except (CleanWheelBuildError, OSError) as error:
        sys.stderr.write(str(error) + "\n")
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
