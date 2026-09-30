from __future__ import annotations

from pathlib import Path
import shutil

import pytest

from scripts.check_skill_cn_sync import (
    REVIEW_ROOT,
    SOURCE_ROOT,
    SkillCnSyncError,
    refresh_manifest,
    validate_skill_cn_sync,
)
from scripts.skill_bundle_manifest import directory_manifest


def test_review_only_chinese_skill_mirror_is_complete_and_non_authoritative() -> None:
    result = validate_skill_cn_sync()

    assert result["status"] == "valid"
    assert result["skill_bundle_manifest_sha256"] == directory_manifest(SOURCE_ROOT)[
        "sha256"
    ]
    assert len(result["skill_bundle_manifest_sha256"]) == 64
    assert result["protected_token_count"] > 0
    assert result["semantic_translation_machine_proven"] is False
    assert not (REVIEW_ROOT / "SKILL.md").exists()
    assert not list(REVIEW_ROOT.rglob("*.yaml"))
    assert not list(REVIEW_ROOT.rglob("*.yml"))


def _copy_mirror(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    review = tmp_path / "review"
    shutil.copytree(SOURCE_ROOT, source)
    shutil.copytree(REVIEW_ROOT, review)
    refresh_manifest(source_root=source, review_root=review)
    return source, review


def test_skill_source_change_requires_a_review_manifest_refresh(
    tmp_path: Path,
) -> None:
    source, review = _copy_mirror(tmp_path)
    entry = source / "SKILL.md"
    entry.write_text(
        entry.read_text(encoding="utf-8") + "\nChanged formal instruction.\n",
        encoding="utf-8",
    )

    with pytest.raises(SkillCnSyncError, match="未同步"):
        validate_skill_cn_sync(source_root=source, review_root=review)


def test_skill_review_mirror_must_preserve_contract_tokens(
    tmp_path: Path,
) -> None:
    source, review = _copy_mirror(tmp_path)
    translated = review / "references/implementation-alignment-workflow.zh-CN.md"
    translated.write_text(
        translated.read_text(encoding="utf-8").replace(
            "strixnova.implementation-alignment-candidate-decisions.v1",
            "遗漏合同版本",
        ),
        encoding="utf-8",
    )

    with pytest.raises(SkillCnSyncError, match="合同 token"):
        validate_skill_cn_sync(source_root=source, review_root=review)


def test_skill_review_mirror_cannot_gain_a_runnable_entrypoint(
    tmp_path: Path,
) -> None:
    source, review = _copy_mirror(tmp_path)
    (review / "SKILL.md").write_text("not allowed\n", encoding="utf-8")

    with pytest.raises(SkillCnSyncError, match="缺失或未登记|可运行"):
        validate_skill_cn_sync(source_root=source, review_root=review)


def test_selected_skill_dependency_manifest_ignores_unrelated_files(
    tmp_path: Path,
) -> None:
    source, _ = _copy_mirror(tmp_path)
    selected = ["SKILL.md"]
    baseline = directory_manifest(source, relative_paths=selected)
    unrelated = source / "references" / "direction.md"
    unrelated.write_text(
        unrelated.read_text(encoding="utf-8") + "\nUnrelated change.\n",
        encoding="utf-8",
    )

    assert directory_manifest(source, relative_paths=selected) == baseline

    entry = source / "SKILL.md"
    entry.write_text(
        entry.read_text(encoding="utf-8") + "\nRelevant change.\n",
        encoding="utf-8",
    )
    assert directory_manifest(source, relative_paths=selected) != baseline
