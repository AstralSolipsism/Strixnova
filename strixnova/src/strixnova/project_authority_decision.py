"""Exact upstream project-authority candidates and mechanical confirmation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
import hashlib
from pathlib import Path
from typing import Any

import yaml

from strixnova.project_authority_progress import (
    PROJECT_AUTHORITY_CANDIDATE_SCHEMA,
    PROJECT_AUTHORITY_DECISION_SCHEMA,
    PROJECT_AUTHORITY_REVIEW_ORDER,
    ProjectAuthorityDecisionError,
    _AUTHORITY_PREREQUISITES,
    _candidate_binding_reference,
    _candidate_review_ref,
    _canonical_sha256,
    _decision_reference,
    _plan,
    _planned_candidate_ref,
    _planned_kind_set,
    _stable_candidate_matches_plan,
    planned_upstream_authority_kinds,
    project_authority_plan_ref,
)

from strixnova.confirmation_protocol import (
    ConfirmationProtocolError,
    reproduce_confirmation_record,
)
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.project_context import ProjectContextResolver
from strixnova.project_authority_consistency import (
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
    authority_owned_target_refs,
)
from strixnova.project_architecture_description import (
    ProjectArchitectureDescription,
    ProjectArchitectureDescriptionError,
)
from strixnova.project_domain_model import (
    ACTIVE_FACT_STATUSES,
    ProjectDomainModel,
    ProjectDomainModelError,
)
from strixnova.project_engineering_policy import (
    ProjectEngineeringPolicy,
    ProjectEngineeringPolicyError,
    project_engineering_policy_governed_paths,
)
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.project_product_definition import (
    ProjectProductDefinition,
    ProjectProductDefinitionError,
)
from strixnova.yaml_metadata_patch import (
    YamlMetadataPatchError,
    apply_yaml_patch_transaction,
    build_yaml_patch_transaction,
)



# This order is deliberately not alphabetical.  It is the confirmation
# topology of the authority chain: a downstream decision is only meaningful
# after the exact upstream body it relies on has already been accepted.



_IDENTITY_FIELD_BY_KIND = {
    "product_definition": "product_id",
    "domain_model": "model_id",
    "target_architecture": "architecture_id",
    "engineering_policy": "policy_id",
}






def _governed_content_sha256(
    reader: GitProjectReader,
    paths: list[str],
    label: str,
) -> str:
    """Hash exact Git-canonical bytes while retaining every governed path."""

    path_hashes: dict[str, str] = {}
    for path in sorted(paths):
        try:
            content = reader.read_canonical_bytes(path, label)
        except GitProjectReaderError as error:
            raise ProjectAuthorityDecisionError(
                "project_authority_candidate_invalid",
                "长期权威文件不能形成稳定的规范字节身份",
                details=[str(error)],
            ) from error
        path_hashes[path] = hashlib.sha256(content).hexdigest()
    return _canonical_sha256(path_hashes)




































def project_authority_review_bundle(
    project_dir: str | Path,
    item: Mapping[str, Any],
    presentations: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Read the complete five-authority candidate chain for agent review."""

    project = Path(project_dir).expanduser().resolve()
    plan = _plan(item)
    investigation_ref = str(plan.get("investigation_ref") or "").strip()
    if not investigation_ref:
        raise ProjectAuthorityDecisionError(
            "project_authority_review_invalid",
            "工程方案缺少候选复核所需的调查版本",
        )
    expected_presentations = {
        str(value.get("authority_kind") or ""): value
        for value in presentations
        if isinstance(value, Mapping)
    }
    for kind in planned_upstream_authority_kinds(
        item,
        current_progress_only=False,
    ):
        presentation = expected_presentations.get(kind)
        if not isinstance(presentation, Mapping):
            raise ProjectAuthorityDecisionError(
                "project_authority_review_invalid",
                "候选复核前没有形成完整上游展示包",
                details={"missing_authority_kind": kind},
            )
        current = project_authority_candidate(project, item, kind)
        if current != presentation.get("candidate"):
            raise ProjectAuthorityDecisionError(
                "project_authority_candidate_changed",
                "候选展示后长期权威正文或上游绑定发生变化；必须重新展示并复核",
                details={"authority_kind": kind},
            )
    try:
        checker = ProjectAuthorityConsistency(project)
        authorities = checker.load_working_tree_candidate_for(investigation_ref)
    except ProjectAuthorityConsistencyError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_review_invalid",
            "完整候选包没有形成可复核的五类权威链",
            details=error.issues,
        ) from error
    baseline = authorities["baseline"]
    values_by_kind = {
        "product_definition": authorities["product_definition"],
        "domain_model": authorities["domain_catalog"],
        "target_architecture": authorities["target_architecture"],
        "engineering_policy": authorities["engineering_policy"],
        "implementation_alignment": authorities["implementation_alignment"],
    }
    identity_fields = {
        "product_definition": "product_id",
        "domain_model": "model_id",
        "target_architecture": "architecture_id",
        "engineering_policy": "policy_id",
        "implementation_alignment": "alignment_model_id",
    }
    candidates: list[dict[str, Any]] = []
    for kind in PROJECT_AUTHORITY_REVIEW_ORDER:
        value = values_by_kind[kind]
        reference = baseline["authority_refs"][kind]
        reader = _candidate_reader(project, reference)
        paths = checker.authority_governed_paths(authorities, kind)
        candidate = {
            "authority_kind": kind,
            "artifact_id": str(value[identity_fields[kind]]),
            "revision_id": str(value["revision"]["revision_id"]),
            "path": str(reference["path"]),
            **({"repository_id": reference["repository_id"]} if reference.get("repository_id") is not None else {}),
            "content_sha256": _governed_content_sha256(
                reader,
                paths,
                "长期权威候选复核文件",
            ),
            "governed_paths": paths,
        }
        presentation = expected_presentations.get(kind)
        if isinstance(presentation, Mapping):
            presented = presentation.get("candidate")
            if not isinstance(presented, Mapping) or any(
                str(presented.get(field) or "")
                != str(candidate.get(field) or "")
                for field in (
                    "authority_kind",
                    "artifact_id",
                    "revision_id",
                    "path",
                    "repository_id",
                    "content_sha256",
                )
            ):
                raise ProjectAuthorityDecisionError(
                    "project_authority_candidate_changed",
                    "候选展示与完整权威链中的规范正文不一致；必须重新展示并复核",
                    details={"authority_kind": kind},
                )
        candidates.append(candidate)
    review_refs = [_candidate_review_ref(value) for value in candidates]
    projection = {
        "schema_version": "strixnova.project-authority-review-bundle.v1",
        "plan_ref": project_authority_plan_ref(item),
        "candidates": candidates,
        "reviewed_refs": review_refs,
        "semantic_content_machine_proven": False,
    }
    projection["content_sha256"] = _canonical_sha256(projection)
    return projection


def _candidate_reader(project: Path, reference: Mapping[str, Any]) -> GitProjectReader:
    context = ProjectContextResolver(project).configured()
    if context is None:
        return GitProjectReader(project)
    if reference.get("repository_id") is None:
        if context.configuration_reader.project == project:
            return context.configuration_reader
        return GitProjectReader(project)
    return context.authority_reader(reference, parent_reader=context.configuration_reader)


def _transaction_roots(project: Path) -> dict[str | None, Path]:
    context = ProjectContextResolver(project).configured()
    roots = {None: project}
    if context is not None:
        roots.update({entry.repository_id: entry.checkout_path for entry in context.repositories if entry.membership == "member" and entry.availability == "available"})
    return roots


def _load_candidate(
    project: Path,
    planned: Mapping[str, str],
    *,
    required_status: str | None,
) -> tuple[dict[str, Any], list[str], str]:
    kind = planned["authority_kind"]
    path = planned["path"]
    reader = _candidate_reader(project, planned)
    source = reader.project
    try:
        if kind == "product_definition":
            value = ProjectProductDefinition(source, path, shared_reader=reader).load()
            paths = [path]
            owner_id = str(value["product_owner"]["owner_id"])
        elif kind == "domain_model":
            value = ProjectDomainModel(source, path, shared_reader=reader).catalog()
            paths = [
                path,
                *[str(item["path"]) for item in value["collections"]],
                *[str(item["path"]) for item in value["sources"]],
            ]
            owner_id = ""
        elif kind == "target_architecture":
            value = ProjectArchitectureDescription(source, path, shared_reader=reader).load()
            paths = [path, *[str(item) for item in value["artifact_paths"].values()]]
            owner_id = ""
        else:
            value = ProjectEngineeringPolicy(source, path, shared_reader=reader).load()
            paths = project_engineering_policy_governed_paths(path, value)
            owner_id = ""
    except (
        GitProjectReaderError,
        ProjectProductDefinitionError,
        ProjectDomainModelError,
        ProjectArchitectureDescriptionError,
        ProjectEngineeringPolicyError,
    ) as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_invalid",
            "长期权威候选没有通过自身完整结构与引用检查",
            details=getattr(error, "issues", [str(error)]),
        ) from error
    identity = str(value.get(_IDENTITY_FIELD_BY_KIND[kind]) or "")
    revision = value.get("revision")
    if identity != planned["artifact_id"] or not isinstance(revision, Mapping):
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_identity_mismatch",
            "长期权威候选与已确认工程方案中的稳定身份不一致",
            details={
                "authority_kind": kind,
                "planned_artifact_id": planned["artifact_id"],
                "candidate_artifact_id": identity,
            },
        )
    expected_revision = str(planned.get("revision_id") or "")
    if expected_revision and revision.get("revision_id") != expected_revision:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_identity_mismatch",
            "长期权威候选与权威变更集中的精确修订不一致",
        )
    if required_status is not None and revision.get("status") != required_status:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_status_invalid",
            f"长期权威候选必须处于 {required_status} 状态",
        )
    unresolved = value.get("unresolved_decisions")
    if isinstance(unresolved, list) and unresolved:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_unresolved",
            "长期权威候选仍有未决事项，不能交给负责人定档",
            details=deepcopy(unresolved),
        )
    return value, list(dict.fromkeys(paths)), owner_id


def validate_authority_change_targets(
    project: Path,
    item: Mapping[str, Any],
    authority_kind: str,
    value: Mapping[str, Any],
) -> None:
    """Prove the declared identity operations exist in the candidate body."""

    change_set = _plan(item).get("authority_change_set")
    if not isinstance(change_set, Mapping):
        return
    changes = [
        change
        for change in change_set.get("changes") or []
        if isinstance(change, Mapping)
        and change.get("authority_kind") == authority_kind
    ]
    if not changes:
        return
    candidate_targets = set(authority_owned_target_refs(authority_kind, value))
    introduced_targets: list[str] = []
    issues: list[str] = []
    for change in changes:
        operation = str(change.get("operation") or "")
        target = str(change.get("target_ref") or "")
        replacement = str(change.get("replacement_ref") or "")
        if operation == "add":
            introduced_targets.append(target)
            if target not in candidate_targets:
                issues.append(f"新增身份没有出现在候选正文：{target}")
        elif operation == "modify" and target not in candidate_targets:
            issues.append(f"修改身份没有保留在候选正文：{target}")
        elif operation == "retire" and target in candidate_targets:
            issues.append(f"退役身份仍存在于候选正文：{target}")
        elif operation == "rename":
            introduced_targets.append(replacement)
            if target in candidate_targets:
                issues.append(f"更名前身份仍存在于候选正文：{target}")
            if replacement not in candidate_targets:
                issues.append(f"更名目标没有出现在候选正文：{replacement}")
    duplicate_introductions = sorted(
        {
            target
            for target in introduced_targets
            if introduced_targets.count(target) > 1
        }
    )
    if duplicate_introductions:
        issues.append(
            "多个新增或更名操作复用了同一候选身份："
            + ", ".join(duplicate_introductions)
        )
    engineering = (
        item.get("data", {}).get("engineering")
        if isinstance(item.get("data"), Mapping)
        else None
    )
    assessment = (
        engineering.get("assessment")
        if isinstance(engineering, Mapping)
        else None
    )
    investigation_ref = (
        str(assessment.get("investigation_ref") or "")
        if isinstance(assessment, Mapping)
        else ""
    )
    if investigation_ref:
        try:
            context = ProjectAuthorityConsistency(
                project,
                observed_ref=investigation_ref,
            ).engineering_governance_context()
            base_candidate = next(
                (
                    authority
                    for authority in context["authority_artifacts"].values()
                    if isinstance(authority, Mapping)
                    and authority.get("authority_kind") == authority_kind
                ),
                None,
            )
        except ProjectAuthorityConsistencyError as error:
            raise ProjectAuthorityDecisionError(
                "project_authority_candidate_change_set_mismatch",
                "无法从调查版本复核权威变更集的完整身份差异",
                details=error.issues,
            ) from error
        if isinstance(base_candidate, Mapping):
            base_targets = {
                str(target) for target in base_candidate.get("target_refs") or []
            }
            declared_added = {
                str(change.get("target_ref") or "")
                for change in changes
                if change.get("operation") == "add"
            } | {
                str(change.get("replacement_ref") or "")
                for change in changes
                if change.get("operation") == "rename"
            }
            declared_removed = {
                str(change.get("target_ref") or "")
                for change in changes
                if change.get("operation") in {"retire", "rename"}
            }
            expected_targets = (base_targets - declared_removed) | declared_added
            unexpected_added = sorted(candidate_targets - expected_targets)
            unexpected_removed = sorted(expected_targets - candidate_targets)
            if unexpected_added:
                issues.append(
                    "候选正文新增了变更集未声明的身份："
                    + ", ".join(unexpected_added)
                )
            if unexpected_removed:
                issues.append(
                    "候选正文删除了变更集未声明的身份："
                    + ", ".join(unexpected_removed)
                )
    if issues:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_change_set_mismatch",
            "长期权威候选正文没有精确实现权威变更集中的身份操作",
            details=issues,
        )


def planned_project_authority_paths(
    project_dir: str | Path,
    item: Mapping[str, Any],
) -> list[str]:
    """Return the exact non-business paths allowed before upstream decisions."""

    project = Path(project_dir).expanduser().resolve()
    plan = _plan(item)
    paths: set[str] = {"strixnova-project.yaml"}
    try:
        baseline_reader = ProjectEngineeringBaseline(project)
        if baseline_reader.engineering_baseline_exists():
            if baseline_reader.reader.project == project:
                paths.add(baseline_reader.locate().relative_to(project).as_posix())
    except ProjectEngineeringBaselineError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_invalid",
            "无法定位项目工程基线",
            details=error.issues,
        ) from error
    for kind in planned_upstream_authority_kinds(
        item,
        current_progress_only=False,
    ):
        try:
            planned = _planned_candidate_ref(item, kind)
        except ProjectAuthorityDecisionError as error:
            if error.code == "project_authority_candidate_not_planned":
                continue
            raise
        if _candidate_reader(project, planned).project != project:
            continue
        _value, governed, _owner = _load_candidate(
            project,
            planned,
            required_status=None,
        )
        paths.update(governed)
    for operation in plan.get("operations") or []:
        if not isinstance(operation, Mapping):
            continue
        if operation.get("repository_id") is not None and _candidate_reader(project, operation).project != project:
            continue
        artifact = operation.get("long_lived_artifact")
        artifact_type = (
            str(artifact.get("artifact_type") or "")
            if isinstance(artifact, Mapping)
            else ""
        )
        raw_path = str(operation.get("path") or "").replace("\\", "/")
        if artifact_type == "adr" and raw_path:
            paths.add(raw_path)
        if artifact_type != "domain_alignment" or not raw_path:
            continue
        try:
            alignment = GitProjectReader(project).load_yaml(
                raw_path,
                "实现对齐候选根文件",
            )
        except GitProjectReaderError as error:
            raise ProjectAuthorityDecisionError(
                "project_authority_candidate_invalid",
                "无法读取已计划实现对齐候选",
                details=[str(error)],
            ) from error
        if not isinstance(alignment, Mapping) or not isinstance(
            alignment.get("artifact_paths"), Mapping
        ):
            raise ProjectAuthorityDecisionError(
                "project_authority_candidate_invalid",
                "已计划实现对齐候选缺少支撑文件清单",
            )
        paths.add(raw_path)
        paths.update(
            str(path).replace("\\", "/")
            for path in alignment["artifact_paths"].values()
            if str(path).strip()
        )
    return sorted(paths)


def _owner_id(project: Path, item: Mapping[str, Any]) -> str:
    try:
        baseline = ProjectEngineeringBaseline(project).load(
            required=False,
            allow_candidate_refs=True,
        )
    except ProjectEngineeringBaselineError:
        baseline = None
    if isinstance(baseline, Mapping):
        project_record = baseline.get("project")
        owner_id = (
            str(project_record.get("owner_id") or "")
            if isinstance(project_record, Mapping)
            else ""
        )
        if owner_id:
            return owner_id
    planned = _planned_candidate_ref(item, "product_definition")
    try:
        reader = _candidate_reader(project, planned)
        value = ProjectProductDefinition(reader.project, planned["path"], shared_reader=reader).load()
    except ProjectProductDefinitionError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_owner_missing",
            "无法从已计划产品定义取得项目负责人身份",
            details=error.issues,
        ) from error
    owner = value.get("product_owner")
    owner_id = str(owner.get("owner_id") or "") if isinstance(owner, Mapping) else ""
    if not owner_id:
        raise ProjectAuthorityDecisionError(
            "project_authority_owner_missing",
            "已计划产品定义缺少项目负责人身份",
        )
    return owner_id


def _validated_candidate_owner_id(
    project: Path,
    item: Mapping[str, Any],
    candidate_owner_id: str,
) -> str:
    """Return the single project owner after checking product/baseline identity."""

    project_owner_id = _owner_id(project, item)
    if candidate_owner_id and candidate_owner_id != project_owner_id:
        raise ProjectAuthorityDecisionError(
            "project_authority_owner_mismatch",
            "产品定义负责人和项目工程基线负责人不是同一身份",
            details={
                "product_owner_id": candidate_owner_id,
                "project_owner_id": project_owner_id,
            },
        )
    return project_owner_id


def _adopted_authority_reference(
    project: Path,
    authority_kind: str,
) -> dict[str, str]:
    """Read one unchanged prerequisite from the adopted authority chain."""

    try:
        baseline = ProjectEngineeringBaseline(project).load(
            required=True,
            allow_candidate_refs=True,
        )
    except ProjectEngineeringBaselineError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_upstream_decision_missing",
            "长期权威候选缺少可绑定的已采用上游权威",
            details=error.issues,
        ) from error
    assert baseline is not None
    reference = baseline["authority_refs"].get(authority_kind)
    if not isinstance(reference, Mapping):
        raise ProjectAuthorityDecisionError(
            "project_authority_upstream_decision_missing",
            f"长期权威候选缺少已采用上游权威：{authority_kind}",
        )
    if reference.get("status") != {
        "revision_status": "confirmed",
        "adoption_status": "current",
    }:
        raise ProjectAuthorityDecisionError(
            "project_authority_upstream_decision_missing",
            f"本轮未变的上游权威尚未确认并采用：{authority_kind}",
        )
    planned = {
        "authority_kind": authority_kind,
        "artifact_id": str(
            reference.get(_IDENTITY_FIELD_BY_KIND[authority_kind]) or ""
        ),
        "revision_id": str(reference.get("revision_id") or ""),
        "path": str(reference.get("path") or ""),
        **{field: reference[field] for field in ("repository_id", "ref") if field in reference},
    }
    value, paths, candidate_owner = _load_candidate(
        project,
        planned,
        required_status="confirmed",
    )
    owner_id = candidate_owner
    if not owner_id:
        project_record = baseline.get("project")
        owner_id = (
            str(project_record.get("owner_id") or "")
            if isinstance(project_record, Mapping)
            else ""
        )
    if not owner_id:
        raise ProjectAuthorityDecisionError(
            "project_authority_owner_missing",
            "已采用上游权威缺少项目负责人身份",
        )
    return {
        "authority_kind": authority_kind,
        "artifact_id": planned["artifact_id"],
        "revision_id": str(value["revision"]["revision_id"]),
        "path": planned["path"],
        "owner_id": owner_id,
        "content_state": "confirmed_current",
        "bound_content_sha256": _governed_content_sha256(
            _candidate_reader(project, planned),
            paths,
            "已采用上游长期权威文件",
        ),
        **({"repository_id": planned["repository_id"]} if planned.get("repository_id") is not None else {}),
    }


def _validated_upstream_authority_refs(
    project: Path,
    item: Mapping[str, Any],
    authority_kind: str,
) -> list[dict[str, str]]:
    """Bind a candidate to exact confirmed or separately presented prerequisites."""

    planned_kinds = _planned_kind_set(item)
    data = item.get("data")
    records = data.get("project_authority_decisions") if isinstance(data, Mapping) else []
    presentations = (
        data.get("project_authority_presentations")
        if isinstance(data, Mapping)
        else []
    )
    records = records if isinstance(records, list) else []
    presentations = presentations if isinstance(presentations, list) else []
    result: list[dict[str, str]] = []
    for prerequisite in _AUTHORITY_PREREQUISITES[authority_kind]:
        if prerequisite not in planned_kinds:
            result.append(_adopted_authority_reference(project, prerequisite))
            continue
        last_error: ProjectAuthorityDecisionError | None = None
        for record in reversed(records):
            if (
                not isinstance(record, Mapping)
                or record.get("authority_kind") != prerequisite
                or not isinstance(record.get("confirmation"), Mapping)
                or record["confirmation"].get("accepted") is not True
            ):
                continue
            try:
                confirmed = validate_project_authority_decision(
                    project,
                    item,
                    record,
                )
            except ProjectAuthorityDecisionError as error:
                last_error = error
                continue
            binding = _decision_reference(record)
            if not binding:
                last_error = ProjectAuthorityDecisionError(
                    "project_authority_decision_invalid",
                    "已接受上游权威缺少可复核的候选正文绑定",
                )
                continue
            result.append(binding)
            break
        else:
            current_candidate: dict[str, Any] | None = None
            try:
                current_candidate = project_authority_candidate(
                    project,
                    item,
                    prerequisite,
                )
            except ProjectAuthorityDecisionError as error:
                last_error = error
            matching_presentation = next(
                (
                    presentation
                    for presentation in reversed(presentations)
                    if isinstance(presentation, Mapping)
                    and presentation.get("authority_kind") == prerequisite
                    and isinstance(presentation.get("candidate"), Mapping)
                    and current_candidate is not None
                    and dict(presentation["candidate"])
                    == dict(current_candidate)
                ),
                None,
            )
            if isinstance(matching_presentation, Mapping):
                binding = _candidate_binding_reference(
                    matching_presentation["candidate"]
                )
                if binding:
                    result.append(binding)
                    continue
            raise ProjectAuthorityDecisionError(
                "project_authority_upstream_decision_missing",
                "下游长期权威候选必须绑定已确认或已独立展示的精确上游候选",
                details={
                    "authority_kind": authority_kind,
                    "missing_upstream_kind": prerequisite,
                    "last_error": str(last_error) if last_error else None,
                },
            )
    return result


def project_authority_candidate(
    project_dir: str | Path,
    item: Mapping[str, Any],
    authority_kind: str,
) -> dict[str, Any]:
    """Return one exact confirmable candidate from the accepted plan."""

    project = Path(project_dir).expanduser().resolve()
    planned = _planned_candidate_ref(item, authority_kind)
    value, paths, candidate_owner = _load_candidate(
        project,
        planned,
        required_status="ready_for_confirmation",
    )
    validate_authority_change_targets(project, item, authority_kind, value)
    owner_id = _validated_candidate_owner_id(project, item, candidate_owner)
    reader = _candidate_reader(project, planned)
    revision = value["revision"]
    return {
        "schema_version": PROJECT_AUTHORITY_CANDIDATE_SCHEMA,
        "plan_ref": project_authority_plan_ref(item),
        "authority_kind": authority_kind,
        "artifact_id": planned["artifact_id"],
        "revision_id": str(revision["revision_id"]),
        "path": planned["path"],
        **({"repository_id": reader.repository_id} if reader.repository_id is not None else {}),
        "owner_id": owner_id,
        "upstream_authority_refs": _validated_upstream_authority_refs(
            project,
            item,
            authority_kind,
        ),
        "candidate_status": "ready_for_confirmation",
        "content_sha256": _governed_content_sha256(
            reader,
            paths,
            "长期权威候选文件",
        ),
        "governed_paths": sorted(paths),
        "semantic_content_machine_proven": False,
    }




def build_project_authority_confirmation_transaction(
    project_dir: str | Path,
    item: Mapping[str, Any],
    decisions: Sequence[Mapping[str, Any]],
    *,
    confirmed_on: str,
) -> dict[str, Any]:
    """Freeze every metadata write for one independently reviewed bundle."""

    project = Path(project_dir).expanduser().resolve()
    try:
        normalized_date = date.fromisoformat(confirmed_on).isoformat()
    except (TypeError, ValueError) as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_confirmation_date_invalid",
            "长期权威确认日期必须是有效日期",
        ) from error
    updates: dict[tuple[str | None, str], dict[tuple[str | int, ...], Any]] = {}
    roots = _transaction_roots(project)
    accepted_kinds: list[str] = []
    accepted_candidates: list[Mapping[str, Any]] = []
    for index, decision in enumerate(decisions):
        candidate = decision.get("candidate")
        accepted = decision.get("accepted")
        if not isinstance(candidate, Mapping) or type(accepted) is not bool:
            raise ProjectAuthorityDecisionError(
                "project_authority_confirmation_bundle_invalid",
                f"长期权威确认事务 decisions[{index}] 结构无效",
            )
        if not accepted:
            continue
        kind = str(candidate.get("authority_kind") or "")
        planned = _planned_candidate_ref(item, kind)
        current = project_authority_candidate(project, item, kind)
        if dict(current) != dict(candidate):
            raise ProjectAuthorityDecisionError(
                "project_authority_candidate_changed",
                "负责人决定之后长期权威候选发生变化；请重新展示精确候选",
            )
        value, paths, _candidate_owner = _load_candidate(
            project,
            planned,
            required_status="ready_for_confirmation",
        )
        identifier = planned.get("repository_id")
        candidate_reader = _candidate_reader(project, planned)
        if candidate_reader.observed_commit is not None:
            raise ProjectAuthorityDecisionError("immutable_authority_write", "确认写入必须定位已计划的工作树候选，不能改写固定版本引用")
        roots[identifier] = candidate_reader.project
        root_updates = updates.setdefault((identifier, planned["path"]), {})
        root_updates.update(
            {
                ("revision", "status"): "confirmed",
                ("revision", "confirmed_by_owner_id"): str(
                    candidate["owner_id"]
                ),
                ("revision", "confirmed_on"): normalized_date,
            }
        )
        if kind == "domain_model":
            for path in paths:
                if path == planned["path"]:
                    continue
                try:
                    raw = candidate_reader.load_yaml(path, "领域权威支撑文件")
                except (OSError, UnicodeError, yaml.YAMLError) as error:
                    raise ProjectAuthorityDecisionError(
                        "project_authority_candidate_invalid",
                        "领域长期权威支撑文件无法形成确认事务",
                        details={"path": path},
                    ) from error
                if not isinstance(raw, Mapping) or not isinstance(
                    raw.get("facts"), list
                ):
                    continue
                fact_updates = updates.setdefault((identifier, path), {})
                fact_updates.update(
                    {
                        ("facts", fact_index, "status"): "confirmed"
                        for fact_index, fact in enumerate(raw["facts"])
                        if isinstance(fact, Mapping)
                        and fact.get("status") in ACTIVE_FACT_STATUSES
                    }
                )
        accepted_kinds.append(kind)
        accepted_candidates.append(candidate)

    if accepted_candidates:
        baseline_reader = ProjectEngineeringBaseline(project)
        try:
            baseline = baseline_reader.load(
                required=True,
                allow_candidate_refs=True,
            )
            if baseline_reader.reader.observed_commit is not None:
                raise ProjectAuthorityDecisionError("immutable_baseline_write", "基线仍绑定固定提交，需先按方案形成当前工作树候选")
            baseline_path = baseline_reader.locate().relative_to(baseline_reader.reader.project).as_posix()
        except (OSError, ProjectEngineeringBaselineError) as error:
            raise ProjectAuthorityDecisionError(
                "project_authority_baseline_missing",
                "长期权威确认前必须存在可机械采用的项目工程基线",
                details=getattr(error, "issues", [str(error)]),
            ) from error
        assert baseline is not None
        baseline_identifier = baseline_reader.reader.repository_id
        roots[baseline_identifier] = baseline_reader.reader.project
        baseline_updates = updates.setdefault((baseline_identifier, baseline_path), {})
        for kind, candidate in zip(
            accepted_kinds,
            accepted_candidates,
            strict=True,
        ):
            planned = _planned_candidate_ref(item, kind)
            reference = baseline["authority_refs"][kind]
            identity_field = _IDENTITY_FIELD_BY_KIND[kind]
            if reference.get(identity_field) != planned["artifact_id"]:
                raise ProjectAuthorityDecisionError(
                    "project_authority_confirmation_metadata_invalid",
                    f"项目工程基线中的 {kind} 不是待确认的同一长期权威",
                )
            if str(reference.get("path") or "") != planned["path"] or (planned.get("repository_id") is not None and reference.get("repository_id") != planned["repository_id"]):
                raise ProjectAuthorityDecisionError(
                    "project_authority_confirmation_metadata_invalid",
                    f"项目工程基线中的 {kind} 没有采用候选根文件的精确路径",
                )
            baseline_updates.update(
                {
                    ("authority_refs", kind, "revision_id"): str(
                        candidate["revision_id"]
                    ),
                    (
                        "authority_refs",
                        kind,
                        "status",
                        "revision_status",
                    ): "confirmed",
                    (
                        "authority_refs",
                        kind,
                        "status",
                        "adoption_status",
                    ): "current",
                }
            )
        review_state = baseline.get("review_state")
        affected = [
            str(kind)
            for kind in (
                review_state.get("affected_authority_kinds")
                if isinstance(review_state, Mapping)
                else []
            )
            if str(kind) not in set(accepted_kinds)
        ]
        baseline_updates[("review_state", "required")] = bool(affected)
        baseline_updates[("review_state", "affected_authority_kinds")] = affected
        if not affected:
            baseline_updates[("review_state", "reasons")] = []
    try:
        return build_yaml_patch_transaction(project, updates, repository_roots=roots)
    except YamlMetadataPatchError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_confirmation_write_failed",
            "长期权威确认元数据不能形成可恢复事务",
            details=[str(error)],
        ) from error


def apply_project_authority_confirmation_transaction(
    project_dir: str | Path,
    transaction: Mapping[str, Any],
) -> dict[Path, bytes]:
    """Idempotently apply a durable upstream-authority confirmation intent."""

    try:
        return apply_yaml_patch_transaction(project_dir, transaction, repository_roots=_transaction_roots(Path(project_dir).expanduser().resolve()))
    except YamlMetadataPatchError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_confirmation_write_failed",
            "长期权威确认元数据事务无法安全恢复",
            details=[str(error)],
        ) from error


def confirmed_project_authority_snapshot(
    project_dir: str | Path,
    item: Mapping[str, Any],
    candidate: Mapping[str, Any],
    *,
    allow_plan_carry_forward: bool = False,
) -> dict[str, Any]:
    """Re-read the exact mechanically confirmed candidate content."""

    project = Path(project_dir).expanduser().resolve()
    kind = str(candidate.get("authority_kind") or "")
    planned = _planned_candidate_ref(item, kind)
    value, paths, candidate_owner = _load_candidate(
        project,
        planned,
        required_status="confirmed",
    )
    revision = value["revision"]
    owner_id = _validated_candidate_owner_id(project, item, candidate_owner)
    plan_matches = candidate.get("plan_ref") == project_authority_plan_ref(item)
    upstream_refs = _validated_upstream_authority_refs(project, item, kind)
    if (
        (not plan_matches and not allow_plan_carry_forward)
        or not _stable_candidate_matches_plan(item, candidate, kind)
        or str(candidate.get("artifact_id") or "") != planned["artifact_id"]
        or str(candidate.get("revision_id") or "")
        != str(revision["revision_id"])
        or str(candidate.get("path") or "") != planned["path"]
        or str(candidate.get("owner_id") or "") != owner_id
        or sorted(candidate.get("governed_paths") or []) != sorted(paths)
        or candidate.get("upstream_authority_refs") != upstream_refs
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_candidate_mismatch",
            "负责人决定没有绑定当前工程方案中的同一长期权威候选",
        )
    if revision.get("confirmed_by_owner_id") != owner_id or not str(
        revision.get("confirmed_on") or ""
    ).strip():
        raise ProjectAuthorityDecisionError(
            "project_authority_confirmation_metadata_invalid",
            "长期权威确认元数据没有绑定当前项目负责人",
        )
    try:
        baseline = ProjectEngineeringBaseline(project).load(
            required=True,
            allow_candidate_refs=True,
        )
    except ProjectEngineeringBaselineError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_confirmation_metadata_invalid",
            "长期权威确认后无法读取项目工程基线",
            details=error.issues,
        ) from error
    assert baseline is not None
    baseline_reference = baseline["authority_refs"][kind]
    if (
        baseline_reference.get("revision_id") != revision.get("revision_id")
        or baseline_reference.get("status")
        != {
            "revision_status": "confirmed",
            "adoption_status": "current",
        }
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_confirmation_metadata_invalid",
            "项目工程基线没有精确采用负责人已确认的长期权威修订",
        )
    reader = _candidate_reader(project, planned)
    return {
        "authority_kind": kind,
        "artifact_id": planned["artifact_id"],
        "revision_id": str(revision["revision_id"]),
        "path": planned["path"],
        "owner_id": owner_id,
        "upstream_authority_refs": upstream_refs,
        "confirmed_on": str(revision["confirmed_on"]),
        "governed_paths": sorted(paths),
        "confirmed_content_sha256": _governed_content_sha256(
            reader,
            paths,
            "已确认长期权威文件",
        ),
        "semantic_content_machine_proven": False,
    }


def validate_project_authority_decision(
    project_dir: str | Path,
    item: Mapping[str, Any],
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove one stored owner decision still matches the confirmed files."""

    if record.get("schema_version") != PROJECT_AUTHORITY_DECISION_SCHEMA:
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_invalid",
            "长期权威负责人决定记录结构无效",
        )
    candidate = record.get("candidate")
    confirmation = record.get("confirmation")
    if not isinstance(candidate, Mapping) or not isinstance(
        confirmation, Mapping
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_invalid",
            "长期权威负责人决定缺少精确候选或确认记录",
        )
    if confirmation.get("accepted") is not True:
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_not_accepted",
            "长期权威候选没有被项目负责人接受",
        )
    challenge = record.get("confirmation_challenge")
    if not isinstance(challenge, Mapping):
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_invalid",
            "长期权威负责人决定缺少原始确认挑战",
        )
    try:
        reproduced = reproduce_confirmation_record(challenge, confirmation)
    except ConfirmationProtocolError as error:
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_invalid",
            "长期权威负责人确认原文无法按公开协议复核",
            details=[str(error)],
        ) from error
    if dict(reproduced) != dict(confirmation):
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_invalid",
            "长期权威负责人决定记录与原始确认挑战不一致",
        )
    confirmed = confirmed_project_authority_snapshot(
        project_dir,
        item,
        candidate,
        allow_plan_carry_forward=True,
    )
    project = Path(project_dir).expanduser().resolve()
    authority_kind = str(candidate.get("authority_kind") or "")
    planned = _planned_candidate_ref(item, authority_kind)
    confirmed_value, _paths, _owner_id = _load_candidate(
        project,
        planned,
        required_status="confirmed",
    )
    validate_authority_change_targets(
        project,
        item,
        authority_kind,
        confirmed_value,
    )
    if (
        record.get("confirmed_content_sha256")
        != confirmed["confirmed_content_sha256"]
        or record.get("confirmed_on") != confirmed["confirmed_on"]
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_decision_content_changed",
            "负责人接受之后长期权威正文或确认元数据发生变化",
        )
    return confirmed


__all__ = [
    "PROJECT_AUTHORITY_CANDIDATE_SCHEMA",
    "PROJECT_AUTHORITY_DECISION_SCHEMA",
    "ProjectAuthorityDecisionError",
    "apply_project_authority_confirmation_transaction",
    "build_project_authority_confirmation_transaction",
    "confirmed_project_authority_snapshot",
    "planned_project_authority_paths",
    "project_authority_candidate",
    "project_authority_review_bundle",
    "validate_authority_change_targets",
    "validate_project_authority_decision",
]
