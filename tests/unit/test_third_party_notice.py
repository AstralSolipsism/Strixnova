from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.third_party_notice import (
    NOTICE_END,
    NOTICE_START,
    ThirdPartyNoticeError,
    append_notice_to_staged_readme,
    extract_notice,
    project_notice,
    verify_wheel_notice,
)
from strixnova.agent_setup import install_agent_skill


PROJECT_ROOT = Path(__file__).parents[2]
SOURCE_PROJECT = PROJECT_ROOT / "strixnova"
SOURCE_SKILL_NOTICE = (
    SOURCE_PROJECT
    / "src"
    / "strixnova"
    / "resources"
    / "agent-skill"
    / "strixnova"
    / "THIRD_PARTY_NOTICE.md"
)
REVIEW_NOTICE = (
    PROJECT_ROOT / "skills-cn" / "strixnova" / "third-party-notice.source.md"
)


def test_root_readme_is_the_only_repository_notice() -> None:
    root_readme = PROJECT_ROOT / "README.md"
    notice = project_notice(SOURCE_PROJECT)

    assert notice is not None
    assert notice == extract_notice(root_readme)
    assert root_readme.read_text(encoding="utf-8").count(NOTICE_START) == 1
    assert root_readme.read_text(encoding="utf-8").count(NOTICE_END) == 1
    assert not SOURCE_SKILL_NOTICE.exists()
    assert not REVIEW_NOTICE.exists()
    package_readme = (SOURCE_PROJECT / "README.md").read_text(encoding="utf-8")
    assert NOTICE_START not in package_readme
    assert NOTICE_END not in package_readme


def test_wheel_metadata_carries_root_notice_without_standalone_files(
    tmp_path: Path,
) -> None:
    notice = extract_notice(PROJECT_ROOT / "README.md")
    staged = tmp_path / "strixnova"
    staged.mkdir()
    (staged / "README.md").write_text("# Package\n", encoding="utf-8")

    append_notice_to_staged_readme(staged, notice)

    staged_readme = (staged / "README.md").read_text(encoding="utf-8")
    assert staged_readme.count(NOTICE_START) == 1
    wheel = tmp_path / "strixnova.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr(
            "strixnova-0.0.0.dist-info/METADATA",
            "Metadata-Version: 2.4\n"
            "Name: strixnova\n"
            "Version: 0.0.0\n"
            "\n"
            + staged_readme,
        )

    verify_wheel_notice(wheel, notice)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_project_notice_reads_root_without_a_skill_projection(
    tmp_path: Path, newline: str
) -> None:
    source_project = tmp_path / "strixnova"
    source_project.mkdir()
    expected = f"{NOTICE_START}\ncanonical\n{NOTICE_END}\n".replace("\n", newline)
    (tmp_path / "README.md").write_bytes(
        ("# Repository\n\n" + expected).encode("utf-8")
    )
    assert project_notice(source_project) == expected
    assert not (source_project / "src").exists()


@pytest.mark.parametrize(
    "body",
    [
        NOTICE_START,
        NOTICE_END,
        f"{NOTICE_END}\n{NOTICE_START}",
        f"{NOTICE_START}\n{NOTICE_START}\n{NOTICE_END}",
    ],
)
def test_malformed_root_notice_is_rejected(tmp_path: Path, body: str) -> None:
    source_project = tmp_path / "strixnova"
    (tmp_path / "README.md").write_text(body, encoding="utf-8")
    with pytest.raises(ThirdPartyNoticeError):
        project_notice(source_project)


def test_project_without_notice_has_no_notice_side_effects(tmp_path: Path) -> None:
    source_project = tmp_path / "strixnova"
    assert project_notice(source_project) is None
    (tmp_path / "README.md").write_text("# Fixture\n", encoding="utf-8")
    assert project_notice(source_project) is None
    assert not source_project.exists()


@pytest.mark.parametrize(
    "defect",
    ["missing", "changed", "duplicate", "standalone", "license_header"],
)
def test_wheel_rejects_missing_changed_or_copied_notice(
    tmp_path: Path, defect: str
) -> None:
    notice = extract_notice(PROJECT_ROOT / "README.md")
    body = notice
    headers = "Metadata-Version: 2.4\nName: strixnova\nVersion: 0.0.0\n"
    if defect == "missing":
        body = "# Package\n"
    elif defect == "changed":
        body = notice.replace("MIT License", "Changed License")
    elif defect == "duplicate":
        body = notice + notice
    elif defect == "license_header":
        headers += "License-File: NOTICE.md\n"
    wheel = tmp_path / "strixnova.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("strixnova-0.0.0.dist-info/METADATA", headers + "\n" + body)
        if defect == "standalone":
            archive.writestr("strixnova/resources/NOTICE.md", notice)
    with pytest.raises(ThirdPartyNoticeError):
        verify_wheel_notice(wheel, notice)


def test_setup_agent_does_not_create_a_notice_copy(tmp_path: Path) -> None:
    install_agent_skill(skills_dir=tmp_path / "skills")
    installed_root = tmp_path / "skills" / "strixnova"
    assert (installed_root / "SKILL.md").is_file()
    assert not (installed_root / "THIRD_PARTY_NOTICE.md").exists()
    assert all(
        NOTICE_START.encode("utf-8") not in path.read_bytes()
        for path in installed_root.rglob("*")
        if path.is_file()
    )
