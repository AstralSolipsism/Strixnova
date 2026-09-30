from pathlib import Path
import os
import stat

import pytest
import yaml

from strixnova.yaml_metadata_patch import (
    YamlMetadataPatchError,
    apply_yaml_patch_transaction,
    build_yaml_patch_transaction,
)
import strixnova.yaml_metadata_patch as yaml_metadata_patch


def test_patch_yaml_values_changes_only_selected_metadata_spans(
    tmp_path: Path,
) -> None:
    target = tmp_path / "authority.yaml"
    target.write_bytes(
        (
            "# 顶部说明\r\n"
            "revision:\r\n"
            "  status: ready_for_confirmation  # 保留行尾说明\r\n"
            "  confirmed_by_owner_id: null\r\n"
            "  confirmed_on: null\r\n"
            "purpose: '保留原来的引号和顺序'\r\n"
        ).encode("utf-8")
    )

    original = target.read_bytes()
    transaction = build_yaml_patch_transaction(
        tmp_path,
        {
            "authority.yaml": {
                ("revision", "status"): "confirmed",
                ("revision", "confirmed_by_owner_id"): "OWNER-AAAAAAAAAAAAAAAA",
                ("revision", "confirmed_on"): "2026-08-28",
            }
        },
    )
    apply_yaml_patch_transaction(tmp_path, transaction)

    assert b"ready_for_confirmation" in original
    updated = target.read_bytes()
    assert b"# \xe9\xa1\xb6\xe9\x83\xa8\xe8\xaf\xb4\xe6\x98\x8e\r\n" in updated
    assert b"# \xe4\xbf\x9d\xe7\x95\x99\xe8\xa1\x8c\xe5\xb0\xbe\xe8\xaf\xb4\xe6\x98\x8e\r\n" in updated
    assert b"purpose: '\xe4\xbf\x9d\xe7\x95\x99\xe5\x8e\x9f\xe6\x9d\xa5\xe7\x9a\x84\xe5\xbc\x95\xe5\x8f\xb7\xe5\x92\x8c\xe9\xa1\xba\xe5\xba\x8f'\r\n" in updated
    parsed = yaml.safe_load(updated.decode("utf-8"))
    assert parsed["revision"] == {
        "status": "confirmed",
        "confirmed_by_owner_id": "OWNER-AAAAAAAAAAAAAAAA",
        "confirmed_on": "2026-08-28",
    }


def test_atomic_replacement_preserves_existing_file_mode(tmp_path: Path) -> None:
    target = tmp_path / "authority.yaml"
    target.write_bytes(b"status: draft\n")
    target.chmod(0o640)
    before_mode = stat.S_IMODE(target.stat().st_mode)

    transaction = build_yaml_patch_transaction(
        tmp_path,
        {"authority.yaml": {("status",): "confirmed"}},
    )
    apply_yaml_patch_transaction(tmp_path, transaction)

    assert stat.S_IMODE(target.stat().st_mode) == before_mode


def test_yaml_patch_transaction_recovers_after_one_file_was_already_written(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first.write_text("status: draft\n", encoding="utf-8")
    second.write_text("status: draft\n", encoding="utf-8")
    transaction = build_yaml_patch_transaction(
        tmp_path,
        {
            "first.yaml": {("status",): "confirmed"},
            "second.yaml": {("status",): "confirmed"},
        },
    )

    apply_yaml_patch_transaction(
        tmp_path,
        {
            "schema_version": transaction["schema_version"],
            "entries": transaction["entries"][:1],
        },
    )
    apply_yaml_patch_transaction(tmp_path, transaction)

    assert yaml.safe_load(first.read_text(encoding="utf-8")) == {
        "status": "confirmed"
    }
    assert yaml.safe_load(second.read_text(encoding="utf-8")) == {
        "status": "confirmed"
    }


def test_yaml_patch_transaction_rolls_back_prior_files_when_later_write_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = tmp_path / "first.yaml"
    second = tmp_path / "second.yaml"
    first_before = b"# first\nstatus: draft\n"
    second_before = b"# second\nstatus: draft\n"
    first.write_bytes(first_before)
    second.write_bytes(second_before)
    transaction = build_yaml_patch_transaction(
        tmp_path,
        {
            "first.yaml": {("status",): "confirmed"},
            "second.yaml": {("status",): "confirmed"},
        },
    )
    real_write = yaml_metadata_patch.atomic_write_bytes
    calls = 0

    def fail_second_write(path: str | Path, content: bytes) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected second write failure")
        real_write(path, content)

    monkeypatch.setattr(
        yaml_metadata_patch,
        "atomic_write_bytes",
        fail_second_write,
    )

    with pytest.raises(YamlMetadataPatchError) as captured:
        apply_yaml_patch_transaction(tmp_path, transaction)

    assert captured.value.code == "yaml_transaction_write_failed_rolled_back"
    assert first.read_bytes() == first_before
    assert second.read_bytes() == second_before


@pytest.mark.parametrize(
    "relative_path",
    [
        ".git/config",
        ".strixnova/authority.yaml",
        "../outside.yaml",
        "nested\\authority.yaml",
        "nested//authority.yaml",
        "nested/./authority.yaml",
    ],
)
def test_yaml_patch_transaction_rejects_internal_and_noncanonical_paths(
    tmp_path: Path,
    relative_path: str,
) -> None:
    with pytest.raises(YamlMetadataPatchError):
        build_yaml_patch_transaction(
            tmp_path,
            {relative_path: {("status",): "confirmed"}},
        )


@pytest.mark.skipif(
    os.name != "nt",
    reason="大小写路径别名只在 Windows（视窗系统）上指向同一目标",
)
def test_yaml_patch_transaction_rejects_case_aliases_of_one_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "authority.yaml"
    target.write_text("status: draft\n", encoding="utf-8")

    with pytest.raises(YamlMetadataPatchError) as captured:
        build_yaml_patch_transaction(
            tmp_path,
            {
                "authority.yaml": {("status",): "confirmed"},
                "AUTHORITY.yaml": {("status",): "confirmed"},
            },
        )

    assert captured.value.code == "yaml_transaction_path_duplicate"


def test_yaml_patch_transaction_rejects_internal_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "authority.yaml"
    target.write_text("status: draft\n", encoding="utf-8")
    link = tmp_path / "linked.yaml"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("当前宿主不允许创建符号链接")

    with pytest.raises(YamlMetadataPatchError) as captured:
        build_yaml_patch_transaction(
            tmp_path,
            {"linked.yaml": {("status",): "confirmed"}},
        )

    assert captured.value.code == "yaml_transaction_path_unsafe"


def test_yaml_patch_transaction_rejects_external_symlink(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.yaml"
    outside.write_text("status: draft\n", encoding="utf-8")
    link = project / "linked.yaml"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("当前宿主不允许创建符号链接")

    with pytest.raises(YamlMetadataPatchError) as captured:
        build_yaml_patch_transaction(
            project,
            {"linked.yaml": {("status",): "confirmed"}},
        )

    assert captured.value.code == "yaml_transaction_path_unsafe"
