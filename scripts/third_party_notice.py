"""Keep third-party method notices derived from one root-README source."""

from __future__ import annotations

import hashlib
from email import policy
from email.parser import BytesParser
from pathlib import Path
from zipfile import ZipFile


NOTICE_START = "<!-- STRIXNOVA-THIRD-PARTY-METHOD-NOTICE:START -->"
NOTICE_END = "<!-- STRIXNOVA-THIRD-PARTY-METHOD-NOTICE:END -->"


class ThirdPartyNoticeError(RuntimeError):
    """The single-source notice is missing, duplicated, or has drifted."""


def _extract_notice_bytes(readme: Path) -> bytes:
    """Return the exact one canonical marker block including its final LF."""

    try:
        content = readme.read_bytes()
        content.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ThirdPartyNoticeError(
            f"无法读取仓库根第三方声明：{readme}"
        ) from error
    start_marker = NOTICE_START.encode("utf-8")
    end_marker = NOTICE_END.encode("utf-8")
    if content.count(start_marker) != 1 or content.count(end_marker) != 1:
        raise ThirdPartyNoticeError("仓库根 README 必须恰好包含一份第三方方法声明")
    start = content.index(start_marker)
    end = content.index(end_marker) + len(end_marker)
    if end <= start:
        raise ThirdPartyNoticeError("仓库根 README 的第三方方法声明边界无效")
    block = content[start:end]
    following = content[end : end + 2]
    if following.startswith(b"\r\n"):
        return block + b"\r\n"
    return block + b"\n"


def extract_notice(readme: Path) -> str:
    """Return the exact one canonical marker block as UTF-8 text."""

    return _extract_notice_bytes(readme).decode("utf-8")


def project_notice(source_project: Path) -> str | None:
    """Read the optional notice directly from the repository root README."""

    source_project = source_project.resolve()
    root_readme = source_project.parent / "README.md"
    if not root_readme.is_file():
        return None
    try:
        content = root_readme.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ThirdPartyNoticeError(
            f"无法读取仓库根第三方声明：{root_readme}"
        ) from error
    if NOTICE_START not in content and NOTICE_END not in content:
        return None
    return extract_notice(root_readme)


def append_notice_to_staged_readme(staged_project: Path, notice: str) -> None:
    """Inject the canonical notice into only the temporary wheel README."""

    readme = staged_project / "README.md"
    try:
        content = readme.read_bytes()
        content.decode("utf-8")
    except (OSError, UnicodeError) as error:
        raise ThirdPartyNoticeError(f"无法读取临时 wheel README：{readme}") from error
    if (
        NOTICE_START.encode("utf-8") in content
        or NOTICE_END.encode("utf-8") in content
    ):
        raise ThirdPartyNoticeError("包 README 不得人工维护第三方方法声明副本")
    readme.write_bytes(
        content.rstrip(b"\r\n") + b"\n\n" + notice.encode("utf-8")
    )


def verify_wheel_notice(wheel_path: Path, notice: str) -> None:
    """Keep the root notice in wheel metadata without standalone copies."""

    notice_bytes = notice.encode("utf-8")
    start_marker = NOTICE_START.encode("utf-8")
    end_marker = NOTICE_END.encode("utf-8")
    normalized_notice = notice_bytes.replace(b"\r\n", b"\n")
    with ZipFile(wheel_path) as archive:
        metadata_names = [
            name
            for name in archive.namelist()
            if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ThirdPartyNoticeError(
                "wheel 必须恰好包含一份可核验第三方声明的 METADATA"
            )
        try:
            metadata = archive.read(metadata_names[0])
            metadata.decode("utf-8")
        except (KeyError, UnicodeDecodeError) as error:
            raise ThirdPartyNoticeError(
                "wheel 元数据缺少可解析第三方声明"
            ) from error
        duplicate_paths = [
            entry.filename
            for entry in archive.infolist()
            if not entry.is_dir()
            and entry.filename != metadata_names[0]
            and normalized_notice in archive.read(entry).replace(b"\r\n", b"\n")
        ]
        if duplicate_paths:
            raise ThirdPartyNoticeError(
                "wheel 不得包含独立第三方声明副本：" + "、".join(duplicate_paths)
            )
    normalized_metadata = metadata.replace(b"\r\n", b"\n")
    if (
        metadata.count(start_marker) != 1
        or metadata.count(end_marker) != 1
        or normalized_notice not in normalized_metadata
    ):
        raise ThirdPartyNoticeError("wheel 长描述没有机械携带唯一根 README 声明")
    parsed_metadata = BytesParser(policy=policy.default).parsebytes(metadata)
    license_headers = parsed_metadata.get_all("License-File", [])
    if license_headers:
        raise ThirdPartyNoticeError(
            "wheel 不得登记独立许可文件；第三方声明只随根 README 进入长描述"
        )


def notice_sha256(notice: str) -> str:
    return hashlib.sha256(notice.encode("utf-8")).hexdigest()
