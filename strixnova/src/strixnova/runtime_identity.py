"""Content identities shared by source, wheel inspection and installed probes."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping

from strixnova import __version__
from strixnova.project_maintenance import MaintenanceError
from strixnova.storage_formats import ACTIVITY_FORMAT, AUTHORITY_FORMAT, EVIDENCE_FORMAT


COMPATIBILITY_RESOURCE = "runtime-compatibility-v1.json"


class RuntimeIdentityError(MaintenanceError):
    pass


def locked_dependencies(requirements: str) -> dict[str, set[str]]:
    """Accept only the exact pins and SHA-256 hashes used by our offline lock."""
    dependencies: dict[str, set[str]] = {}
    pending = ""
    for line in requirements.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        continuation = value.endswith("\\")
        pending += " " + (value[:-1].strip() if continuation else value)
        if continuation:
            continue
        match = re.fullmatch(
            r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)==([A-Za-z0-9][A-Za-z0-9.!+_-]*)"
            r"((?:\s+--hash=sha256:[a-f0-9]{64})+)\s*", pending,
        )
        if match is None:
            raise RuntimeIdentityError("runtime_compatibility_invalid", "离线依赖锁只允许精确版本与 SHA-256，不接受 URL、其他文件或安装选项")
        name = re.sub(r"[-_.]+", "-", match[1]).lower()
        if name in dependencies:
            raise RuntimeIdentityError("runtime_compatibility_invalid", "离线依赖锁包含重复包")
        dependencies[name] = set(re.findall(r"sha256:([a-f0-9]{64})", match[3]))
        pending = ""
    if pending:
        raise RuntimeIdentityError("runtime_compatibility_invalid", "离线依赖锁存在未结束的记录")
    return dependencies


def file_sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def content_identities(hashes: Mapping[str, str]) -> dict[str, Any]:
    build = hashlib.sha256(json.dumps(dict(hashes), sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    prefix = "resources/agent-skill/strixnova/"
    skill_files = {path[len(prefix):]: digest for path, digest in hashes.items() if path.startswith(prefix)}
    skill = hashlib.sha256(b"strixnova.skill-bundle-content-manifest.v1\n")
    for path, digest in sorted(skill_files.items()):
        skill.update(path.encode("utf-8") + b"\0" + digest.encode("ascii") + b"\n")
    return {"build_sha256": build, "skill_sha256": skill.hexdigest(), "package_file_count": len(hashes), "skill_file_count": len(skill_files)}


def validate_compatibility(value: Any) -> dict[str, Any]:
    try:
        if not isinstance(value, dict) or set(value) != {"schema_version", "python", "formats", "dependency_lock"}:
            raise ValueError
        if value["schema_version"] != "strixnova.runtime-compatibility.v1" or value["python"] != "3.12":
            raise ValueError
        formats = value["formats"]
        if set(formats) != {"authority", "delivery_activities", "evidence"} or any(type(number) is not int or number < 1 for number in formats.values()):
            raise ValueError
        lock = value["dependency_lock"]
        if not isinstance(lock, dict) or set(lock) != {"sha256", "requirements"} or not isinstance(lock["requirements"], str):
            raise ValueError
        if len(lock["requirements"].encode("utf-8")) > 1024 * 1024 or hashlib.sha256(lock["requirements"].encode("utf-8")).hexdigest() != lock["sha256"]:
            raise ValueError
        locked_dependencies(lock["requirements"])
        return value
    except (ValueError, KeyError, TypeError, AttributeError) as error:
        raise RuntimeIdentityError("runtime_compatibility_invalid", "运行兼容清单缺失、格式不受支持或依赖锁内容不一致") from error


def runtime_identity() -> dict[str, Any]:
    package = Path(__file__).parent
    hashes = {path.relative_to(package).as_posix(): file_sha256(path) for path in sorted(package.rglob("*")) if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"}
    try:
        declared = validate_compatibility(json.loads((package / "resources" / COMPATIBILITY_RESOURCE).read_text(encoding="utf-8")))
    except (OSError, ValueError) as error:
        raise RuntimeIdentityError("runtime_compatibility_invalid", "随包运行兼容清单无法读取") from error
    formats = {"authority": AUTHORITY_FORMAT, "delivery_activities": ACTIVITY_FORMAT, "evidence": EVIDENCE_FORMAT}
    if declared["formats"] != formats:
        raise RuntimeIdentityError("runtime_compatibility_invalid", "随包清单与实际运行代码的格式支持不一致")
    return {
        "schema_version": "strixnova.runtime-identity.v1", "version": __version__,
        "package_path": str(package.resolve()), **content_identities(hashes),
        "formats": formats,
        "dependency_lock_sha256": declared["dependency_lock"]["sha256"],
    }
