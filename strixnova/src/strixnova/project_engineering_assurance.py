"""Versioned internal engineering assurance without semantic self-certification."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    project_reader_for_scope,
    repository_relative_path,
)
from strixnova.project_authority_consistency import (
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
)
from strixnova.schema_error_reporting import schema_error_message
PROJECT_ENGINEERING_ASSURANCE_SCHEMA = (
    "strixnova.project-engineering-assurance.v1"
)
DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH = (
    "docs/engineering/assurance/model.yaml"
)


class ProjectEngineeringAssuranceError(ValueError):
    """A project assurance candidate is structurally or evidentially invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目工程保障评估无效")


def _schema_issues(value: Mapping[str, Any]) -> list[str]:
    resource = files("strixnova.resources").joinpath(
        "project-engineering-assurance-v1.schema.json"
    )
    schema = json.loads(resource.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(
            schema,
            format_checker=FormatChecker(),
        ).iter_errors(value),
        key=lambda error: tuple(str(item) for item in error.absolute_path),
    )
    issues: list[str] = []
    for error in errors:
        path = ".".join(str(item) for item in error.absolute_path)
        location = f" {path}" if path else ""
        issues.append(
            f"项目工程保障评估{location} 不符合结构合同："
            + schema_error_message(error)
        )
    return issues


class ProjectEngineeringAssurance:
    """Validate and project one downstream assurance artifact."""

    def __init__(
        self,
        project_dir: str | Path,
        assurance_path: str = DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH,
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
        shared_consistency: ProjectAuthorityConsistency | None = None,
    ) -> None:
        try:
            if shared_consistency is not None:
                if (
                    shared_reader is not None
                    and shared_reader is not shared_consistency.reader
                ):
                    raise GitProjectReaderError(
                        "共享一致性检查器与共享项目读取器不属于同一读取范围"
                    )
                shared_reader = shared_consistency.reader
            self.reader = project_reader_for_scope(
                project_dir,
                observed_ref=observed_ref,
                shared_reader=shared_reader,
            )
            self.assurance_path = repository_relative_path(
                assurance_path,
                "project_engineering_assurance_path",
            )
        except GitProjectReaderError as error:
            raise ProjectEngineeringAssuranceError([str(error)]) from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit
        self._consistency = shared_consistency
        self._cache: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        """Load and deterministically validate exact bindings and evidence."""

        if self._cache is not None:
            return deepcopy(self._cache)
        try:
            value = self.reader.load_yaml(
                self.assurance_path,
                "项目工程保障评估",
            )
        except GitProjectReaderError as error:
            raise ProjectEngineeringAssuranceError([str(error)]) from error
        if not isinstance(value, Mapping):
            raise ProjectEngineeringAssuranceError(
                ["项目工程保障评估必须是对象"]
            )
        if value.get("schema_version") != PROJECT_ENGINEERING_ASSURANCE_SCHEMA:
            raise ProjectEngineeringAssuranceError(
                ["项目工程保障评估必须使用当前第一版结构合同"]
            )
        issues = _schema_issues(value)
        try:
            consistency = (
                self._consistency
                or ProjectAuthorityConsistency(
                    self.project,
                    shared_reader=self.reader,
                )
            )
            authorities = consistency.load()
            profile = consistency.governance_context()["governance_profile"]
        except ProjectAuthorityConsistencyError as error:
            raise ProjectEngineeringAssuranceError(error.issues) from error

        self._validate_bindings(value, authorities, profile, issues)
        evidence_by_id = self._validate_evidence(value, issues)
        self._validate_rule_assessments(
            value,
            profile,
            evidence_by_id,
            issues,
        )
        self._validate_external_assurance(value, evidence_by_id, issues)
        if issues:
            raise ProjectEngineeringAssuranceError(issues)
        normalized = deepcopy(dict(value))
        normalized["_manifest_path"] = self.assurance_path
        normalized["_observed_commit"] = self.observed_commit
        normalized["_governance_sources"] = deepcopy(profile["sources"])
        self._cache = normalized
        return deepcopy(normalized)

    def matrix(self) -> dict[str, Any]:
        """Return an honest read projection; never promote it to authority."""

        value = self.load()
        source_by_id = {
            str(source["source_id"]): source
            for source in value.pop("_governance_sources")
        }
        counts = Counter(
            str(item["status"]) for item in value["rule_assessments"]
        )
        rows: list[dict[str, Any]] = []
        for item in value["rule_assessments"]:
            row = deepcopy(item)
            row["sources"] = [
                {
                    "source_id": source_id,
                    "designation": source_by_id[source_id].get("designation"),
                    "title": source_by_id[source_id].get("title"),
                    "official_url": source_by_id[source_id].get("official_url"),
                    "status": source_by_id[source_id].get("status"),
                }
                for source_id in item["source_ids"]
            ]
            rows.append(row)
        return {
            "schema_version": "strixnova.project-engineering-assurance-matrix.v1",
            "assurance_id": value["assurance_id"],
            "assurance_revision_id": value["assurance_revision_id"],
            "scope": value["scope"],
            "authority_refs": deepcopy(value["authority_refs"]),
            "governance_profile_ref": deepcopy(
                value["governance_profile_ref"]
            ),
            "evidence_base_commit": value["evidence_base_commit"],
            "by_status": dict(sorted(counts.items())),
            "rule_assessments": rows,
            "external_assurance": deepcopy(value["external_assurance"]),
            "unresolved_items": deepcopy(value["unresolved_items"]),
            "machine_validation_scope": [
                "结构合同",
                "精确权威与治理档案绑定",
                "治理规则和来源完整覆盖",
                "证据路径及内容摘要",
                "逐项状态与缺口纠偏约束",
            ],
            "semantic_content_machine_proven": False,
            "external_assurance_machine_proven": False,
            "projection_is_project_authority": False,
            "manifest_path": value["_manifest_path"],
            "observed_commit": value["_observed_commit"],
        }

    @staticmethod
    def _expected_authority_refs(
        authorities: Mapping[str, Any],
    ) -> dict[str, Any]:
        baseline_refs = authorities["baseline"]["authority_refs"]
        identity_fields = {
            "product_definition": "product_id",
            "domain_model": "model_id",
            "target_architecture": "architecture_id",
            "engineering_policy": "policy_id",
            "implementation_alignment": "alignment_model_id",
        }
        return {
            kind: {
                "path": reference["path"],
                identity_fields[kind]: reference[identity_fields[kind]],
                "revision_id": reference["revision_id"],
                **{key: reference[key] for key in ("repository_id", "ref") if key in reference},
            }
            for kind, reference in baseline_refs.items()
        }

    def _validate_bindings(
        self,
        value: Mapping[str, Any],
        authorities: Mapping[str, Any],
        profile: Mapping[str, Any],
        issues: list[str],
    ) -> None:
        expected_refs = self._expected_authority_refs(authorities)
        if value.get("authority_refs") != expected_refs:
            issues.append("项目工程保障评估没有绑定当前采用的精确五权威链")
        policy = authorities["engineering_policy"]
        expected_profile_ref = {
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "policy_id": policy["policy_id"],
            "policy_revision_id": policy["revision"]["revision_id"],
        }
        if value.get("governance_profile_ref") != expected_profile_ref:
            issues.append("项目工程保障评估没有绑定当前采用的精确治理档案")
        base_commit = str(value.get("evidence_base_commit") or "")
        try:
            observed_commit = self.observed_commit or self.reader.resolve_commit(
                "HEAD"
            )
            if not self.reader.is_ancestor(base_commit, observed_commit):
                issues.append("项目工程保障评估的证据基线不是所读版本的祖先")
        except GitProjectReaderError as error:
            issues.append(str(error))

    def _validate_evidence(
        self,
        value: Mapping[str, Any],
        issues: list[str],
    ) -> dict[str, Mapping[str, Any]]:
        evidence_by_id: dict[str, Mapping[str, Any]] = {}
        paths: list[str] = []
        selected_ids: set[str] = set()
        for evidence in value.get("evidence") or []:
            if not isinstance(evidence, Mapping):
                continue
            evidence_id = str(evidence.get("evidence_id") or "")
            if evidence_id in selected_ids:
                continue
            selected_ids.add(evidence_id)
            try:
                paths.append(repository_relative_path(evidence.get("path")))
            except GitProjectReaderError:
                pass  # The existing per-record pass reports this exact error.
        evidence_hashes: dict[str, str | None] | None = {}
        try:
            for path, content in self.reader.iter_canonical_files(
                paths, "项目工程保障证据"
            ):
                try:
                    content.decode("utf-8", errors="strict")
                except UnicodeError:
                    evidence_hashes[path] = None
                else:
                    evidence_hashes[path] = hashlib.sha256(content).hexdigest()
        except GitProjectReaderError:
            evidence_hashes = None
        for index, evidence in enumerate(value.get("evidence") or []):
            if not isinstance(evidence, Mapping):
                continue
            evidence_id = str(evidence.get("evidence_id") or "")
            if evidence_id in evidence_by_id:
                issues.append(f"项目工程保障证据身份重复：{evidence_id}")
                continue
            evidence_by_id[evidence_id] = evidence
            kind = str(evidence.get("evidence_kind") or "")
            receipt_id = evidence.get("receipt_id")
            if kind == "repository_file" and receipt_id is not None:
                issues.append(f"普通仓库证据不得伪装成回执：{evidence_id}")
            if kind != "repository_file" and not (
                isinstance(receipt_id, str) and receipt_id.strip()
            ):
                issues.append(f"回执证据缺少回执身份：{evidence_id}")
            try:
                path = repository_relative_path(
                    evidence.get("path"),
                    f"evidence[{index}].path",
                )
                if evidence_hashes is None:
                    content = self.reader.read_canonical_bytes(
                        path, "项目工程保障证据"
                    )
                    try:
                        content.decode("utf-8", errors="strict")
                    except UnicodeError:
                        actual_hash = None
                    else:
                        actual_hash = hashlib.sha256(content).hexdigest()
                else:
                    actual_hash = evidence_hashes[path]
            except GitProjectReaderError as error:
                issues.append(str(error))
                continue
            if actual_hash is None:
                issues.append("项目工程保障证据必须是 UTF-8 文本")
                continue
            if evidence.get("sha256") != actual_hash:
                issues.append(f"项目工程保障证据内容已漂移：{path}")
        return evidence_by_id

    @staticmethod
    def _validate_rule_assessments(
        value: Mapping[str, Any],
        profile: Mapping[str, Any],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        rules = {
            str(rule["rule_id"]): rule for rule in profile["rules"]
        }
        assessments: dict[str, Mapping[str, Any]] = {}
        for assessment in value.get("rule_assessments") or []:
            if not isinstance(assessment, Mapping):
                continue
            rule_id = str(assessment.get("rule_id") or "")
            if rule_id in assessments:
                issues.append(f"治理规则评估重复：{rule_id}")
                continue
            assessments[rule_id] = assessment
            rule = rules.get(rule_id)
            if rule is None:
                issues.append(f"治理规则评估引用未知规则：{rule_id}")
                continue
            if assessment.get("source_ids") != rule.get("source_ids"):
                issues.append(f"治理规则评估来源绑定不精确：{rule_id}")
            evidence_ids = set(assessment.get("evidence_ids") or [])
            unknown_evidence = sorted(evidence_ids - set(evidence_by_id))
            if unknown_evidence:
                issues.append(
                    f"治理规则评估 {rule_id} 引用未知证据："
                    + ", ".join(unknown_evidence)
                )
            applicability = assessment.get("applicability")
            status = assessment.get("status")
            gaps = list(assessment.get("gaps") or [])
            remediation = list(assessment.get("remediation_actions") or [])
            if applicability == "not_applicable":
                if status != "not_applicable":
                    issues.append(f"不适用规则的状态必须是不适用：{rule_id}")
            elif applicability == "unknown":
                if status != "unknown":
                    issues.append(f"适用性未知规则的状态必须是未知：{rule_id}")
                if not gaps or not remediation:
                    issues.append(f"适用性未知必须记录缺口和解决计划：{rule_id}")
            elif status == "not_applicable":
                issues.append(f"适用规则不得标记为不适用：{rule_id}")
            elif status == "satisfied":
                if not evidence_ids:
                    issues.append(f"满足规则必须引用证据：{rule_id}")
                if gaps or remediation:
                    issues.append(f"满足规则不得同时保留缺口或纠偏：{rule_id}")
            elif status == "partially_satisfied":
                if not evidence_ids or not gaps or not remediation:
                    issues.append(
                        f"部分满足规则必须记录证据、缺口和纠偏：{rule_id}"
                    )
            elif status in {"not_satisfied", "unknown"}:
                if not gaps or not remediation:
                    issues.append(f"未满足或未知规则必须记录缺口和纠偏：{rule_id}")
        missing = sorted(set(rules) - set(assessments))
        if missing:
            issues.append("项目工程保障评估缺少治理规则：" + ", ".join(missing))

    @staticmethod
    def _validate_external_assurance(
        value: Mapping[str, Any],
        evidence_by_id: Mapping[str, Mapping[str, Any]],
        issues: list[str],
    ) -> None:
        external = value.get("external_assurance") or {}
        receipt_ids = list(external.get("receipt_evidence_ids") or [])
        if external.get("status") == "not_claimed" and receipt_ids:
            issues.append("未声明外部保障时不得绑定外部回执")
        if external.get("status") == "claimed_with_receipt" and not receipt_ids:
            issues.append("声明外部保障必须绑定真实外部回执")
        for evidence_id in receipt_ids:
            evidence = evidence_by_id.get(str(evidence_id))
            if evidence is None:
                issues.append(f"外部保障引用未知证据：{evidence_id}")
            elif evidence.get("evidence_kind") != "external_assurance_receipt":
                issues.append(f"外部保障引用的不是外部回执：{evidence_id}")


__all__ = [
    "DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH",
    "PROJECT_ENGINEERING_ASSURANCE_SCHEMA",
    "ProjectEngineeringAssurance",
    "ProjectEngineeringAssuranceError",
]
