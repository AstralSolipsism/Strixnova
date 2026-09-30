"""Project-owned engineering policy authority with deterministic checks only."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
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
from strixnova.schema_error_reporting import schema_error_message


ENGINEERING_POLICY_SCHEMA = "strixnova.project-engineering-policy.v1"
BASE_GOVERNANCE_PROFILE_SCHEMA = "strixnova.governance-profile.v1"
ASSURANCE_BANDS = ("A0", "A1", "A2", "A3", "A4")
IMPACT_DIMENSIONS = frozenset(
    {
        "user_behavior",
        "product_scope",
        "domain",
        "architecture",
        "interface",
        "data",
        "security_privacy",
        "quality_performance",
        "operations_deployment",
        "compatibility_migration",
        "testing",
        "documentation_support",
    }
)
INFORMATION_KINDS = frozenset(
    {
        "requirement",
        "acceptance",
        "constraint",
        "impact",
        "risk",
        "option",
        "design",
        "operation",
        "verification",
        "delivery",
        "adr_candidate",
        "unknown",
    }
)
REQUIRED_FORBIDDEN_AGENT_PROGRAM_NAMES = frozenset(
    {"aider", "claude", "codex", "cursor", "gemini", "opencode", "windsurf"}
)


class ProjectEngineeringPolicyError(ValueError):
    """The project engineering policy is structurally invalid."""

    def __init__(self, issues: Sequence[str]) -> None:
        self.issues = sorted({str(issue) for issue in issues if str(issue)})
        super().__init__("；".join(self.issues) or "项目工程政策无效")


def project_engineering_policy_governed_paths(
    policy_path: str,
    policy: Mapping[str, Any],
) -> list[str]:
    """Return the exact files whose bytes define one policy candidate."""

    return list(
        dict.fromkeys(
            [
                policy_path,
                *[
                    str(source["path"])
                    for source in policy["project_sources"]
                ],
            ]
        )
    )


def _schema_issues(value: Mapping[str, Any]) -> list[str]:
    resource = files("strixnova.resources").joinpath(
        "project-engineering-policy-v1.schema.json"
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
        location = f".{path}" if path else ""
        issues.append(
            f"项目工程政策{location} 不符合结构合同："
            + schema_error_message(error)
        )
    return issues


def load_base_governance_profile() -> dict[str, Any]:
    """Load the shipped reference profile without applying project decisions."""

    resource = files("strixnova.resources").joinpath("governance-profile-v1.json")
    try:
        value = json.loads(resource.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProjectEngineeringPolicyError(["随包基础治理档案无法读取"]) from error
    if not isinstance(value, Mapping):
        raise ProjectEngineeringPolicyError(["随包基础治理档案必须是对象"])
    required = {
        "schema_version",
        "profile_id",
        "profile_version",
        "scope",
        "sources",
        "engineering_methods",
        "rules",
    }
    issues: list[str] = []
    if set(value) != required:
        missing = sorted(required - set(value))
        extra = sorted(set(value) - required)
        if missing:
            issues.append("随包基础治理档案缺少字段：" + ", ".join(missing))
        if extra:
            issues.append("随包基础治理档案包含未知字段：" + ", ".join(extra))
    if value.get("schema_version") != BASE_GOVERNANCE_PROFILE_SCHEMA:
        issues.append("随包基础治理档案结构版本无效")
    for name in ("profile_id", "profile_version", "scope"):
        if not isinstance(value.get(name), str) or not value[name].strip():
            issues.append(f"随包基础治理档案 {name} 必须是非空字符串")
    collections: dict[str, tuple[str, set[str]]] = {
        "sources": ("source_id", set()),
        "engineering_methods": ("method_id", set()),
        "rules": ("rule_id", set()),
    }
    for collection_name, (identity_name, known) in collections.items():
        collection = value.get(collection_name)
        if not isinstance(collection, list) or not collection:
            issues.append(f"随包基础治理档案 {collection_name} 必须是非空数组")
            continue
        for index, item in enumerate(collection):
            if not isinstance(item, Mapping):
                issues.append(
                    f"随包基础治理档案 {collection_name}[{index}] 必须是对象"
                )
                continue
            identifier = item.get(identity_name)
            if not isinstance(identifier, str) or not identifier.strip():
                issues.append(
                    f"随包基础治理档案 {collection_name}[{index}]."
                    f"{identity_name} 必须是非空字符串"
                )
            elif identifier in known:
                issues.append(
                    f"随包基础治理档案 {collection_name} 身份重复：{identifier}"
                )
            else:
                known.add(identifier)
    source_ids = collections["sources"][1]
    for method in value.get("engineering_methods", []):
        if isinstance(method, Mapping):
            unknown = sorted(set(method.get("source_ids") or []) - source_ids)
            if unknown:
                issues.append(
                    "随包工程方法引用未知来源：" + ", ".join(unknown)
                )
    for rule in value.get("rules", []):
        if isinstance(rule, Mapping):
            unknown = sorted(set(rule.get("source_ids") or []) - source_ids)
            if unknown:
                issues.append("随包治理规则引用未知来源：" + ", ".join(unknown))
    if issues:
        raise ProjectEngineeringPolicyError(issues)
    return deepcopy(dict(value))


class ProjectEngineeringPolicy:
    """Deep interface for one exact project engineering-policy revision."""

    def __init__(
        self,
        project_dir: str | Path,
        policy_path: str,
        *,
        observed_ref: str | None = None,
        shared_reader: GitProjectReader | None = None,
    ) -> None:
        try:
            self.reader = project_reader_for_scope(
                project_dir,
                observed_ref=observed_ref,
                shared_reader=shared_reader,
            )
            self.policy_path = repository_relative_path(
                policy_path,
                "engineering_policy_path",
            )
        except GitProjectReaderError as error:
            raise ProjectEngineeringPolicyError([str(error)]) from error
        self.project = self.reader.project
        self.observed_commit = self.reader.observed_commit
        self._policy_cache: dict[str, Any] | None = None

    def load(self) -> dict[str, Any]:
        if self._policy_cache is not None:
            return deepcopy(self._policy_cache)
        try:
            value = self.reader.load_yaml(self.policy_path, "项目工程政策")
        except GitProjectReaderError as error:
            raise ProjectEngineeringPolicyError([str(error)]) from error
        if not isinstance(value, Mapping):
            raise ProjectEngineeringPolicyError(["项目工程政策必须是对象"])
        if value.get("schema_version") != ENGINEERING_POLICY_SCHEMA:
            raise ProjectEngineeringPolicyError(
                ["项目工程政策必须使用当前第一版结构合同，旧混合基线不再裁决政策"]
            )
        issues = _schema_issues(value)
        try:
            self.reader.prefetch(
                [
                    repository_relative_path(
                        source.get("path"),
                        f"project_sources[{index}].path",
                    )
                    for index, source in enumerate(value.get("project_sources", []))
                    if isinstance(source, Mapping)
                ]
            )
        except GitProjectReaderError as error:
            issues.append(str(error))
        base_profile = load_base_governance_profile()
        base_ref = value.get("base_profile_ref") or {}
        if base_ref != {
            "profile_id": base_profile["profile_id"],
            "profile_version": base_profile["profile_version"],
        }:
            issues.append("项目工程政策没有绑定当前随包基础治理档案的精确版本")

        method_by_id = {
            str(method["method_id"]): method
            for method in base_profile["engineering_methods"]
        }
        adoption_ids: set[str] = set()
        for adoption in value.get("method_adoptions", []):
            if not isinstance(adoption, Mapping):
                continue
            method_id = str(adoption.get("method_id") or "")
            if method_id in adoption_ids:
                issues.append(f"项目工程方法采用身份重复：{method_id}")
            adoption_ids.add(method_id)
            method = method_by_id.get(method_id)
            if method is None:
                issues.append(f"项目工程方法采用引用未知方法：{method_id}")
                continue
            known_techniques = {
                str(item["technique_id"]) for item in method["techniques"]
            }
            adopted = set(adoption.get("adopted_technique_ids") or [])
            unknown = sorted(adopted - known_techniques)
            if unknown:
                issues.append(
                    f"{method_id} 采用状态引用未知技术：" + ", ".join(unknown)
                )
            if adoption.get("status") in {"adopted", "conditional"}:
                missing = sorted(
                    set(method["project_adoption_requires"]) - adopted
                )
                if missing:
                    issues.append(
                        f"{method_id} 项目采用缺少必要技术："
                        + ", ".join(missing)
                    )

        source_ids = {
            str(source["source_id"]) for source in base_profile["sources"]
        }
        for index, source in enumerate(value.get("project_sources", [])):
            if not isinstance(source, Mapping):
                continue
            source_id = str(source.get("source_id") or "")
            if source_id in source_ids:
                issues.append(f"项目工程政策来源身份冲突：{source_id}")
            source_ids.add(source_id)
            try:
                source_path = repository_relative_path(
                    source.get("path"),
                    f"project_sources[{index}].path",
                )
                if not self.reader.exists(source_path):
                    issues.append(f"项目工程政策来源不存在：{source_path}")
            except GitProjectReaderError as error:
                issues.append(str(error))

        base_rule_by_id = {
            str(rule["rule_id"]): rule for rule in base_profile["rules"]
        }
        extension_ids: set[str] = set()
        for extension in value.get("rule_extensions", []):
            if not isinstance(extension, Mapping):
                continue
            rule_id = str(extension.get("rule_id") or "")
            if rule_id in base_rule_by_id or rule_id in extension_ids:
                issues.append(f"项目工程政策扩展规则身份冲突：{rule_id}")
            extension_ids.add(rule_id)
            unknown_sources = sorted(
                set(extension.get("source_ids") or []) - source_ids
            )
            if unknown_sources:
                issues.append(
                    f"项目工程政策扩展规则 {rule_id} 引用未知来源："
                    + ", ".join(unknown_sources)
                )
            unknown_dimensions = sorted(
                set(extension.get("impact_dimensions") or [])
                - IMPACT_DIMENSIONS
            )
            if unknown_dimensions:
                issues.append(
                    f"项目工程政策扩展规则 {rule_id} 包含未知影响维度："
                    + ", ".join(unknown_dimensions)
                )
            unknown_kinds = sorted(
                set(extension.get("required_information_kinds") or [])
                - INFORMATION_KINDS
            )
            if unknown_kinds:
                issues.append(
                    f"项目工程政策扩展规则 {rule_id} 包含未知信息种类："
                    + ", ".join(unknown_kinds)
                )

        tailored: set[str] = set()
        for tailoring in value.get("rule_tailoring", []):
            if not isinstance(tailoring, Mapping):
                continue
            rule_id = str(tailoring.get("rule_id") or "")
            if rule_id in tailored:
                issues.append(f"项目工程政策规则重复裁剪：{rule_id}")
            tailored.add(rule_id)
            rule = base_rule_by_id.get(rule_id)
            if rule is None:
                issues.append(f"项目工程政策裁剪引用未知规则：{rule_id}")
                continue
            requested = tailoring.get("minimum_assurance")
            disposition = tailoring.get("disposition")
            if disposition == "strengthened":
                if requested is None:
                    issues.append(f"{rule_id} 强化时必须声明最低保障等级")
                elif ASSURANCE_BANDS.index(str(requested)) < ASSURANCE_BANDS.index(
                    str(rule["minimum_assurance"])
                ):
                    issues.append(f"{rule_id} 的强化不得降低最低保障等级")
            elif requested is not None:
                issues.append(f"{rule_id} 非强化裁剪不得声明最低保障等级")

        verification_policy = value.get("verification_command_policy")
        if isinstance(verification_policy, Mapping):
            forbidden_programs = {
                str(item).strip().casefold()
                for item in verification_policy.get(
                    "forbidden_agent_program_names"
                )
                or []
            }
            missing_forbidden = sorted(
                REQUIRED_FORBIDDEN_AGENT_PROGRAM_NAMES - forbidden_programs
            )
            if missing_forbidden:
                issues.append(
                    "项目验证政策缺少必须禁止的智能编码代理程序："
                    + ", ".join(missing_forbidden)
                )
            allowed_identities: set[str] = set()
            for index, allowed in enumerate(
                verification_policy.get("allowed_programs") or []
            ):
                if not isinstance(allowed, Mapping):
                    continue
                program = str(allowed.get("program") or "")
                normalized = program.replace("\\", "/").casefold()
                name = Path(normalized).name.casefold()
                stem = Path(name).stem.casefold()
                identity = normalized.removeprefix("./")
                if identity in allowed_identities:
                    issues.append(
                        "项目验证政策允许程序身份重复：" + program
                    )
                allowed_identities.add(identity)
                if {name, stem} & forbidden_programs:
                    issues.append(
                        f"项目验证政策 allowed_programs[{index}] 同时允许并禁止代理程序"
                    )

        revision = value.get("revision") or {}
        if revision.get("status") == "confirmed" and value.get(
            "unresolved_decisions"
        ):
            issues.append("已确认项目工程政策不得保留未决事项")
        if issues:
            raise ProjectEngineeringPolicyError(issues)
        normalized = deepcopy(dict(value))
        normalized["_manifest_path"] = self.policy_path
        normalized["_observed_commit"] = self.observed_commit
        normalized["_semantic_content_machine_proven"] = False
        self._policy_cache = normalized
        return deepcopy(normalized)

    def governance_profile(self) -> dict[str, Any]:
        """Return the exact deterministic profile consumed by assessment governance."""

        policy = self.load()
        profile = load_base_governance_profile()
        source_ids = {str(item["source_id"]) for item in profile["sources"]}
        for source in policy["project_sources"]:
            source_id = str(source["source_id"])
            if source_id in source_ids:
                continue
            profile["sources"].append(
                {
                    "source_id": source_id,
                    "source_kind": "project_artifact",
                    "designation": source_id,
                    "title": source["title"],
                    "edition": policy["revision"]["revision_id"],
                    "status": source["status"],
                    "location": source["path"],
                    "verified_on": policy["revision"]["confirmed_on"],
                    "usage": source["usage"],
                }
            )
            source_ids.add(source_id)
        rule_by_id = {str(rule["rule_id"]): rule for rule in profile["rules"]}
        for tailoring in policy["rule_tailoring"]:
            rule = rule_by_id[str(tailoring["rule_id"])]
            rule["project_tailoring"] = {
                "disposition": tailoring["disposition"],
                "reason": tailoring["reason"],
                "owner_confirmed": True,
            }
            if tailoring["disposition"] == "project_not_applicable":
                rule["project_not_applicable"] = True
            elif tailoring["disposition"] == "strengthened":
                rule["minimum_assurance"] = tailoring["minimum_assurance"]
        for extension in policy["rule_extensions"]:
            profile["rules"].append(deepcopy(extension))
        profile["project_tailoring"] = deepcopy(policy["rule_tailoring"])
        profile["project_method_adoptions"] = deepcopy(
            policy["method_adoptions"]
        )
        profile["project_policy_statements"] = deepcopy(
            policy["policy_statements"]
        )
        profile["verification_command_policy"] = deepcopy(
            policy["verification_command_policy"]
        )
        profile["project_engineering_policy_ref"] = {
            "policy_id": policy["policy_id"],
            "revision_id": policy["revision"]["revision_id"],
            "path": self.policy_path,
            "observed_commit": self.observed_commit,
        }
        profile["profile_id"] = (
            f"{profile['profile_id']}+{policy['policy_id']}"
        )
        return profile

    def obligations(
        self,
        impact_dimensions: Sequence[str],
        assurance_band: str,
    ) -> dict[str, Any]:
        """Project explicit policy rules onto already supplied impact facts."""

        unknown_dimensions = sorted(set(impact_dimensions) - IMPACT_DIMENSIONS)
        if unknown_dimensions:
            raise ProjectEngineeringPolicyError(
                ["未知影响维度：" + ", ".join(unknown_dimensions)]
            )
        if assurance_band not in ASSURANCE_BANDS:
            raise ProjectEngineeringPolicyError(
                ["未知保障等级：" + str(assurance_band)]
            )
        profile = self.governance_profile()
        selected: list[dict[str, Any]] = []
        required_band = "A0"
        for rule in profile["rules"]:
            if rule.get("project_not_applicable"):
                continue
            applies = bool(rule["always_for_formal_implementation"]) or bool(
                set(rule["impact_dimensions"]) & set(impact_dimensions)
            )
            if not applies:
                continue
            selected.append(deepcopy(rule))
            if ASSURANCE_BANDS.index(str(rule["minimum_assurance"])) > (
                ASSURANCE_BANDS.index(required_band)
            ):
                required_band = str(rule["minimum_assurance"])
        return {
            "schema_version": "strixnova.project-engineering-obligations.v1",
            "policy_ref": profile["project_engineering_policy_ref"],
            "supplied_impact_dimensions": sorted(set(impact_dimensions)),
            "supplied_assurance_band": assurance_band,
            "minimum_required_assurance_band": required_band,
            "rules": selected,
            "semantic_content_machine_proven": False,
        }


__all__ = [
    "ASSURANCE_BANDS",
    "BASE_GOVERNANCE_PROFILE_SCHEMA",
    "ENGINEERING_POLICY_SCHEMA",
    "IMPACT_DIMENSIONS",
    "INFORMATION_KINDS",
    "ProjectEngineeringPolicy",
    "ProjectEngineeringPolicyError",
    "REQUIRED_FORBIDDEN_AGENT_PROGRAM_NAMES",
    "load_base_governance_profile",
    "project_engineering_policy_governed_paths",
]
