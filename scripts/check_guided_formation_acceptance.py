"""Validate the guided-formation acceptance catalog and evidence freshness.

This check compares declared Skill, runtime, harness, fixture and evidence bytes.
Incomplete execution dependency declarations cannot establish full freshness.
It does not judge whether an Agent response is semantically correct.
"""

from __future__ import annotations

import argparse
import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping
import json
from pathlib import Path, PurePosixPath
import re

import yaml

try:
    from scripts.skill_bundle_manifest import (
        SkillBundleManifestError,
        directory_manifest,
    )
except ModuleNotFoundError:  # Direct script execution.
    from skill_bundle_manifest import SkillBundleManifestError, directory_manifest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = "tests/acceptance/guided-formation-cases.yaml"
CATALOG_SCHEMA = "strixnova.guided-formation-acceptance-catalog.v1"
CHECK_SCHEMA = "strixnova.guided-formation-acceptance-check.v1"
DEPENDENCY_GROUPS = ("runtime", "harness", "fixture", "evidence")
VERIFICATION_KINDS = {"agent_response", "contract_structure"}
CASE_FIELDS = {
    "case_id",
    "title",
    "verification_kind",
    "expected_behavior",
    "must_avoid",
    "dependency_paths",
    "evidence",
}
EVIDENCE_FIELDS = {
    "result",
    "path",
    "locator",
    "dependency_manifest_sha256",
    "full_skill_bundle_manifest_sha256",
    "binding_basis",
}
EVIDENCE_RESULTS = {"passed", "pending"}
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
CASE_ID_PATTERN = re.compile(r"GF-[A-Z0-9]+(?:-[A-Z0-9]+)+")


class GuidedFormationAcceptanceError(RuntimeError):
    """The catalog is malformed or points outside its declared boundaries."""


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise GuidedFormationAcceptanceError(f"{label} 必须是对象")
    return value


def _safe_repo_path(project_root: Path, value: object, *, label: str) -> Path:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or ":" in value
        or any(character in value for character in "\x00\r\n")
    ):
        raise GuidedFormationAcceptanceError(f"{label} 必须是仓库内 POSIX 相对路径")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not path.parts
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise GuidedFormationAcceptanceError(f"{label} 必须是仓库内 POSIX 相对路径")
    target = project_root.joinpath(*path.parts).resolve()
    try:
        target.relative_to(project_root)
    except ValueError as error:
        raise GuidedFormationAcceptanceError(f"{label} 越出仓库") from error
    return target


def _nonempty_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GuidedFormationAcceptanceError(f"{label} 必须是非空文本")
    return value


def _sha256(value: object, *, label: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise GuidedFormationAcceptanceError(f"{label} 必须是 SHA-256")
    return value


def _execution_dependency_states(project: Path, value: object, *, report_path: str) -> dict:
    if value is None:
        return {group: {"state": "unassessed", "reason": "No execution dependency binding recorded", "changed_paths": []}
                for group in DEPENDENCY_GROUPS}
    groups = _mapping(value, label="execution_dependencies")
    if set(groups) != set(DEPENDENCY_GROUPS):
        raise GuidedFormationAcceptanceError("Execution dependencies require runtime, harness, fixture and evidence groups")
    states = {}
    for group in DEPENDENCY_GROUPS:
        declaration = _mapping(groups[group], label=f"execution_dependencies.{group}")
        if set(declaration) != {"status", "reason", "files"}:
            raise GuidedFormationAcceptanceError("Dependency group fields must be status, reason and files")
        status = declaration["status"]
        if not isinstance(status, str) or status not in {"recorded", "not_applicable", "unrecorded"}:
            raise GuidedFormationAcceptanceError("Unknown dependency declaration status")
        reason = _nonempty_text(declaration["reason"], label="dependency reason")
        files = declaration["files"]
        if not isinstance(files, list) or (status == "recorded") != bool(files):
            raise GuidedFormationAcceptanceError("Only recorded dependencies must contain a nonempty file list")
        if group == "evidence" and status == "not_applicable":
            raise GuidedFormationAcceptanceError("A passed result cannot omit its evidence binding")
        changed, seen = [], set()
        for item in files:
            entry = _mapping(item, label="dependency file")
            if set(entry) != {"path", "sha256"}:
                raise GuidedFormationAcceptanceError("Dependency file requires path and sha256")
            path = _safe_repo_path(project, entry["path"], label="dependency path")
            identity = str(path)
            if identity in seen:
                raise GuidedFormationAcceptanceError("Dependency file is repeated")
            seen.add(identity)
            digest = _sha256(entry["sha256"], label="dependency sha256")
            try:
                current = hashlib.sha256(path.read_bytes()).hexdigest()
            except FileNotFoundError:
                current = None
            except OSError as error:
                raise GuidedFormationAcceptanceError(f"Cannot read dependency: {entry['path']}") from error
            if current != digest:
                changed.append(entry["path"])
        if group == "evidence" and status == "recorded" and not any(item["path"] == report_path for item in files):
            raise GuidedFormationAcceptanceError("Evidence dependencies must bind the actual case report")
        state = "stale" if changed else {"recorded": "current", "not_applicable": "not_applicable", "unrecorded": "unassessed"}[status]
        states[group] = {"state": state, "reason": reason, "changed_paths": changed}
    return states


def check_catalog(
    project_root: Path = REPOSITORY_ROOT,
    *,
    catalog_path: str = DEFAULT_CATALOG,
) -> dict[str, object]:
    """Return structural validity and current/stale evidence counts by case."""

    project = project_root.resolve()
    catalog_file = _safe_repo_path(project, catalog_path, label="catalog_path")
    try:
        raw_catalog = yaml.safe_load(catalog_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as error:
        raise GuidedFormationAcceptanceError("验收目录缺失或不是有效 UTF-8 YAML") from error
    catalog = _mapping(raw_catalog, label="验收目录")
    if set(catalog) != {
        "schema_version",
        "skill_source_root",
        "semantic_content_machine_proven",
        "cases",
    }:
        raise GuidedFormationAcceptanceError("验收目录字段不完整或包含未知字段")
    version = catalog.get("schema_version")
    if not isinstance(version, str) or version != CATALOG_SCHEMA:
        raise GuidedFormationAcceptanceError("验收目录版本无效")
    if catalog.get("semantic_content_machine_proven") is not False:
        raise GuidedFormationAcceptanceError("验收目录不得宣称机器证明语义正确")
    skill_root = _safe_repo_path(
        project,
        catalog.get("skill_source_root"),
        label="skill_source_root",
    )
    raw_cases = catalog.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise GuidedFormationAcceptanceError("验收目录必须包含非空 cases")

    case_ids: list[str] = []
    states: list[dict[str, object]] = []
    kind_counts: Counter[str] = Counter()
    current_kind_counts: Counter[str] = Counter()
    for index, raw_case in enumerate(raw_cases):
        case = _mapping(raw_case, label=f"cases[{index}]")
        expected_fields = CASE_FIELDS | {"execution_dependencies"}
        if set(case) != expected_fields:
            raise GuidedFormationAcceptanceError(
                f"cases[{index}] 字段不完整或包含未知字段"
            )
        case_id = _nonempty_text(case.get("case_id"), label=f"cases[{index}].case_id")
        if CASE_ID_PATTERN.fullmatch(case_id) is None:
            raise GuidedFormationAcceptanceError(f"验收场景身份无效：{case_id}")
        case_ids.append(case_id)
        _nonempty_text(case.get("title"), label=f"{case_id}.title")
        _nonempty_text(
            case.get("expected_behavior"), label=f"{case_id}.expected_behavior"
        )
        _nonempty_text(case.get("must_avoid"), label=f"{case_id}.must_avoid")
        verification_kind = case.get("verification_kind")
        if verification_kind not in VERIFICATION_KINDS:
            raise GuidedFormationAcceptanceError(
                f"{case_id}.verification_kind 无效"
            )
        kind_counts[str(verification_kind)] += 1

        dependency_paths = case.get("dependency_paths")
        if (
            not isinstance(dependency_paths, list)
            or not dependency_paths
            or any(not isinstance(path, str) for path in dependency_paths)
            or len(dependency_paths) != len(set(dependency_paths))
        ):
            raise GuidedFormationAcceptanceError(
                f"{case_id}.dependency_paths 必须是非空无重复路径列表"
            )
        try:
            current_manifest = directory_manifest(
                skill_root,
                relative_paths=dependency_paths,
            )
        except SkillBundleManifestError as error:
            raise GuidedFormationAcceptanceError(str(error)) from error

        evidence = _mapping(case.get("evidence"), label=f"{case_id}.evidence")
        if set(evidence) != EVIDENCE_FIELDS:
            raise GuidedFormationAcceptanceError(
                f"{case_id}.evidence 字段不完整或包含未知字段"
            )
        evidence_result = evidence.get("result")
        if evidence_result not in EVIDENCE_RESULTS:
            raise GuidedFormationAcceptanceError(f"{case_id}.evidence.result 无效")
        _nonempty_text(
            evidence.get("binding_basis"), label=f"{case_id}.evidence.binding_basis"
        )
        if evidence_result == "pending":
            if case.get("execution_dependencies") is not None:
                raise GuidedFormationAcceptanceError("Pending evidence cannot record execution dependency bindings")
            pending_fields = (
                "path",
                "locator",
                "dependency_manifest_sha256",
                "full_skill_bundle_manifest_sha256",
            )
            if any(evidence.get(field) is not None for field in pending_fields):
                raise GuidedFormationAcceptanceError(
                    f"{case_id} 的待验场景不得伪造证据定位或内容指纹"
                )
            states.append(
                {
                    "case_id": case_id,
                    "verification_kind": verification_kind,
                    "evidence_state": "pending",
                    "skill_dependency_state": "pending",
                    "execution_dependency_states": _execution_dependency_states(project, None, report_path=""),
                    "recorded_dependency_manifest_sha256": None,
                    "current_dependency_manifest_sha256": current_manifest["sha256"],
                }
            )
            continue
        recorded_manifest = _sha256(
            evidence.get("dependency_manifest_sha256"),
            label=f"{case_id}.evidence.dependency_manifest_sha256",
        )
        full_skill_manifest = _sha256(
            evidence.get("full_skill_bundle_manifest_sha256"),
            label=f"{case_id}.evidence.full_skill_bundle_manifest_sha256",
            nullable=True,
        )
        if verification_kind == "agent_response" and full_skill_manifest is None:
            raise GuidedFormationAcceptanceError(
                f"{case_id} 的 Agent 响应证据必须绑定完整 Skill 内容指纹"
            )
        if (
            verification_kind == "contract_structure"
            and full_skill_manifest is not None
        ):
            raise GuidedFormationAcceptanceError(
                f"{case_id} 的合同结构证据不得冒充完整安装态 Skill 回执"
            )
        evidence_path = _safe_repo_path(
            project,
            evidence.get("path"),
            label=f"{case_id}.evidence.path",
        )
        locator = _nonempty_text(
            evidence.get("locator"), label=f"{case_id}.evidence.locator"
        )
        try:
            evidence_text = evidence_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise GuidedFormationAcceptanceError(
                f"{case_id} 证据文件缺失或不是 UTF-8"
            ) from error
        if evidence_text.count(locator) != 1:
            raise GuidedFormationAcceptanceError(
                f"{case_id} 证据定位文字必须恰好出现一次"
            )
        if full_skill_manifest is not None and full_skill_manifest not in evidence_text:
            raise GuidedFormationAcceptanceError(
                f"{case_id} 的完整 Skill 内容指纹未写入证据文件"
            )

        skill_state = (
            "current"
            if recorded_manifest == current_manifest["sha256"]
            else "stale"
        )
        execution_states = _execution_dependency_states(project, case.get("execution_dependencies"), report_path=evidence["path"])
        dependency_states = {entry["state"] for entry in execution_states.values()}
        if skill_state == "stale" or "stale" in dependency_states:
            state = "stale"
        elif "unassessed" in dependency_states:
            state = "unassessed"
        else:
            state = "current"
        if state == "current":
            current_kind_counts[str(verification_kind)] += 1
        states.append(
            {
                "case_id": case_id,
                "verification_kind": verification_kind,
                "evidence_state": state,
                "skill_dependency_state": skill_state,
                "execution_dependency_states": execution_states,
                "recorded_dependency_manifest_sha256": recorded_manifest,
                "current_dependency_manifest_sha256": current_manifest["sha256"],
            }
        )

    if len(case_ids) != len(set(case_ids)):
        raise GuidedFormationAcceptanceError("验收场景身份不得重复")
    current_count = sum(item["evidence_state"] == "current" for item in states)
    stale_count = sum(item["evidence_state"] == "stale" for item in states)
    pending_count = sum(item["evidence_state"] == "pending" for item in states)
    skill_manifest = directory_manifest(skill_root)
    return {
        "schema_version": CHECK_SCHEMA,
        "status": "valid",
        "case_count": len(states),
        "current_evidence_count": current_count,
        "stale_evidence_count": stale_count,
        "pending_evidence_count": pending_count,
        "unassessed_evidence_count": sum(item["evidence_state"] == "unassessed" for item in states),
        "skill_current_count": sum(item["skill_dependency_state"] == "current" for item in states),
        "freshness_scope": "declared_dependencies_only",
        "acceptance_complete": current_count == len(states),
        "counts_by_verification_kind": dict(sorted(kind_counts.items())),
        "current_counts_by_verification_kind": dict(
            sorted(current_kind_counts.items())
        ),
        "skill_bundle_file_count": skill_manifest["file_count"],
        "skill_bundle_manifest_sha256": skill_manifest["sha256"],
        "cases": states,
        "semantic_content_machine_proven": False,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="核验引导式形成验收目录、证据定位和按依赖失效状态。"
    )
    parser.add_argument("--catalog", default=DEFAULT_CATALOG)
    parser.add_argument(
        "--require-current",
        action="store_true",
        help="任一场景待验、依赖失效或完整依赖未登记时返回非零；不调用 Agent。",
    )
    return parser


def main(arguments: Iterable[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    try:
        result = check_catalog(catalog_path=options.catalog)
    except (GuidedFormationAcceptanceError, OSError) as error:
        print(str(error))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if options.require_current and not result["acceptance_complete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
