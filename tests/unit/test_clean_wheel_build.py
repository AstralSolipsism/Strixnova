from __future__ import annotations

import importlib.util
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest


PROJECT_ROOT = Path(__file__).parents[2]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "build_clean_wheel.py"
SPEC = importlib.util.spec_from_file_location("build_clean_wheel", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _source_project(root: Path) -> Path:
    project = root / "strixnova"
    (project / "src" / "strixnova" / "resources").mkdir(parents=True)
    (project / "pyproject.toml").write_text(
        "[build-system]\n"
        "requires = [\"setuptools>=75\", \"wheel\"]\n"
        "build-backend = \"setuptools.build_meta\"\n\n"
        "[project]\n"
        "name = \"strixnova-clean-wheel-fixture\"\n"
        "version = \"0.0.0\"\n\n"
        "description = \"fixture package summary\"\n\n"
        "[tool.setuptools.packages.find]\n"
        "where = [\"src\"]\n\n"
        "[tool.setuptools.package-data]\n"
        "strixnova = [\"resources/**/*\"]\n",
        encoding="utf-8",
    )
    (project / "README.md").write_text("# Strixnova\n", encoding="utf-8")
    (project / "src" / "strixnova" / "__init__.py").write_text(
        '"""Fixture module description."""\n\n__version__ = \'0.0.0\'\n',
        encoding="utf-8",
    )
    (project / "src" / "strixnova" / "resources" / "current.json").write_text(
        '{"current": true}\n',
        encoding="utf-8",
    )
    return project


def test_stage_project_excludes_every_generated_source_tree(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    stale = source / "build" / "lib" / "strixnova" / "resources"
    stale.mkdir(parents=True)
    (stale / "retired.schema.json").write_text("{}\n", encoding="utf-8")
    (source / "dist").mkdir()
    (source / "src" / "strixnova.egg-info").mkdir()
    cache = source / "src" / "strixnova" / "resources" / "__pycache__"
    cache.mkdir()
    (cache / "cached.pyc").write_bytes(b"stale")
    staged = tmp_path / "staged"

    MODULE.stage_project(source, staged)

    assert (staged / "src" / "strixnova" / "resources" / "current.json").is_file()
    assert not (staged / "build").exists()
    assert not (staged / "dist").exists()
    assert not (staged / "src" / "strixnova.egg-info").exists()
    assert not (staged / "src" / "strixnova" / "resources" / "__pycache__").exists()


def test_clean_build_cannot_package_a_retired_schema_from_old_build_cache(
    tmp_path: Path,
) -> None:
    source = _source_project(tmp_path)
    stale = source / "build" / "lib" / "strixnova" / "resources"
    stale.mkdir(parents=True)
    (stale / "retired.schema.json").write_text("{}\n", encoding="utf-8")

    result = MODULE.build_clean_wheel(
        source_project=source,
        output_dir=tmp_path / "dist",
    )

    wheel = Path(result["wheel_path"])
    with ZipFile(wheel) as archive:
        packaged = set(archive.namelist())
    assert "strixnova/resources/current.json" in packaged
    assert "strixnova/resources/retired.schema.json" not in packaged
    assert "skill_bundle_manifest_sha256" not in result


def test_repository_build_rejects_a_missing_root_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MODULE, "project_notice", lambda source_project: None)

    with pytest.raises(MODULE.CleanWheelBuildError, match="README"):
        MODULE.build_clean_wheel(output_dir=tmp_path / "dist")
    assert not (tmp_path / "dist").exists()


def _wheel(path: Path, entries: dict[str, bytes]) -> Path:
    with ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr("strixnova/resources/" + name, content)
    return path


def _identity_wheel(
    path: Path,
    *,
    summary: str = "fixture package summary",
    module_docstring: str = "Fixture module description.",
) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr(
            "strixnova_fixture-0.0.0.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: strixnova-clean-wheel-fixture\n"
            "Version: 0.0.0\n"
            f"Summary: {summary}\n",
        )
        archive.writestr(
            "strixnova/__init__.py",
            f'"""{module_docstring}"""\n\n__version__ = \'0.0.0\'\n',
        )
    return path


def _skill_wheel(
    path: Path,
    entries: list[tuple[str, bytes]],
    *,
    timestamp: tuple[int, int, int, int, int, int],
) -> Path:
    with ZipFile(path, "w") as archive:
        for name, content in entries:
            info = ZipInfo(
                "strixnova/resources/agent-skill/strixnova/" + name,
                date_time=timestamp,
            )
            archive.writestr(info, content)
    return path


def test_wheel_identity_must_equal_the_current_source(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    wheel = _identity_wheel(tmp_path / "strixnova.whl")

    MODULE.verify_wheel_identity(wheel, source)


@pytest.mark.parametrize("difference", ["summary", "module_docstring"])
def test_wheel_identity_drift_is_rejected(
    tmp_path: Path,
    difference: str,
) -> None:
    source = _source_project(tmp_path)
    arguments = {difference: "drifted"}
    wheel = _identity_wheel(tmp_path / "strixnova.whl", **arguments)

    with pytest.raises(MODULE.CleanWheelBuildError):
        MODULE.verify_wheel_identity(wheel, source)


def test_wheel_resources_must_equal_the_current_source_bytes(tmp_path: Path) -> None:
    source = _source_project(tmp_path)
    resources = source / "src" / "strixnova" / "resources"
    expected = (resources / "current.json").read_bytes()
    wheel = _wheel(tmp_path / "strixnova.whl", {"current.json": expected})

    assert MODULE.verify_wheel_resources(wheel, resources) == 1


def test_review_only_translation_is_rejected_anywhere_in_wheel(
    tmp_path: Path,
) -> None:
    wheel = tmp_path / "strixnova.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("skills-cn/strixnova/strixnova.zh-CN.md", "review only")

    with pytest.raises(MODULE.CleanWheelBuildError, match="中文审阅"):
        MODULE.verify_review_material_excluded(wheel)


def test_skill_content_manifest_ignores_wheel_order_and_metadata(
    tmp_path: Path,
) -> None:
    entries = [("SKILL.md", b"entry\n"), ("references/guide.md", b"guide\n")]
    first = _skill_wheel(
        tmp_path / "first.whl",
        entries,
        timestamp=(2025, 1, 1, 0, 0, 0),
    )
    second = _skill_wheel(
        tmp_path / "second.whl",
        list(reversed(entries)),
        timestamp=(2026, 9, 3, 12, 0, 0),
    )

    assert MODULE.wheel_manifest(first) == MODULE.wheel_manifest(second)

    changed = _skill_wheel(
        tmp_path / "changed.whl",
        [("SKILL.md", b"changed\n"), entries[1]],
        timestamp=(2026, 9, 3, 12, 0, 0),
    )
    assert MODULE.wheel_manifest(first) != MODULE.wheel_manifest(changed)


def test_wheel_skill_manifest_must_equal_source_skill_bytes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "skill"
    (source / "references").mkdir(parents=True)
    (source / "SKILL.md").write_bytes(b"entry\n")
    (source / "references" / "guide.md").write_bytes(b"guide\n")
    wheel = _skill_wheel(
        tmp_path / "strixnova.whl",
        [("SKILL.md", b"entry\n"), ("references/guide.md", b"guide\n")],
        timestamp=(2026, 9, 3, 12, 0, 0),
    )

    result = MODULE.verify_wheel_skill_bundle(wheel, source)
    assert result["file_count"] == 2
    assert len(result["sha256"]) == 64

    (source / "SKILL.md").write_bytes(b"changed\n")
    with pytest.raises(MODULE.CleanWheelBuildError, match="内容指纹"):
        MODULE.verify_wheel_skill_bundle(wheel, source)


def test_skill_manifest_rejects_paths_that_collide_on_windows(
    tmp_path: Path,
) -> None:
    wheel = _skill_wheel(
        tmp_path / "strixnova.whl",
        [("SKILL.md", b"first\n"), ("skill.md", b"second\n")],
        timestamp=(2026, 9, 3, 12, 0, 0),
    )

    with pytest.raises(MODULE.SkillBundleManifestError, match="重复"):
        MODULE.wheel_manifest(wheel)


@pytest.mark.parametrize("difference", ["missing", "unexpected", "changed"])
def test_wheel_resource_drift_is_rejected(
    tmp_path: Path,
    difference: str,
) -> None:
    source = _source_project(tmp_path)
    resources = source / "src" / "strixnova" / "resources"
    expected = (resources / "current.json").read_bytes()
    entries = {"current.json": expected}
    if difference == "missing":
        entries = {}
    elif difference == "unexpected":
        entries["retired.schema.json"] = b"{}\n"
    else:
        entries["current.json"] = b"changed\n"
    wheel = _wheel(tmp_path / "strixnova.whl", entries)

    with pytest.raises(MODULE.CleanWheelBuildError):
        MODULE.verify_wheel_resources(wheel, resources)
