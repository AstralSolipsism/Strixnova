"""Pure project-authority progress and confirmation projections.

This module reads only one WorkItem value. It never opens or writes project
authority files, so CurrentAction can depend on it without crossing into the
application use-case boundary.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from typing import Any

from strixnova.engineering_change_planning import permitted_slice_operation_paths
from strixnova.confirmation_protocol import CONFIRMATION_CHALLENGE_SCHEMA


PROJECT_AUTHORITY_CANDIDATE_SCHEMA = "strixnova.project-authority-candidate.v1"


PROJECT_AUTHORITY_PRESENTATION_SCHEMA = "strixnova.project-authority-presentation.v1"


PROJECT_AUTHORITY_REVIEW_SCHEMA = "strixnova.project-authority-review.v1"


PROJECT_AUTHORITY_DECISION_SCHEMA = "strixnova.project-authority-decision.v1"


PROJECT_AUTHORITY_KINDS = (
    "product_definition",
    "domain_model",
    "target_architecture",
    "engineering_policy",
)


PROJECT_AUTHORITY_ORDER = PROJECT_AUTHORITY_KINDS


PROJECT_AUTHORITY_REVIEW_ORDER = (
    *PROJECT_AUTHORITY_ORDER,
    "implementation_alignment",
)


_AUTHORITY_PREREQUISITES = {
    "product_definition": (),
    "domain_model": ("product_definition",),
    "target_architecture": ("product_definition", "domain_model"),
    "engineering_policy": ("product_definition",),
}


def project_authority_prerequisites(authority_kind: str) -> tuple[str, ...]:
    if authority_kind not in _AUTHORITY_PREREQUISITES:
        raise ProjectAuthorityDecisionError(
            "project_authority_kind_invalid",
            "长期权威种类必须是产品、领域、目标架构或工程政策之一",
        )
    return tuple(_AUTHORITY_PREREQUISITES[authority_kind])


_ARTIFACT_TYPE_BY_KIND = {
    "product_definition": "product_governance",
    "domain_model": "domain_model",
    "target_architecture": "architecture",
    "engineering_policy": "quality_policy",
}


PROJECT_AUTHORITY_KIND_BY_ARTIFACT_TYPE = {
    artifact_type: kind for kind, artifact_type in _ARTIFACT_TYPE_BY_KIND.items()
}


_CHANGE_CONTEXT_PATH_BY_KIND = {
    "product_definition": "project_product_definition_path",
    "domain_model": "project_domain_model_path",
    "target_architecture": "project_architecture_description_path",
    "engineering_policy": "project_engineering_policy_path",
}


_DECISION_LABEL_BY_KIND = {
    "product_definition": "当前展示的产品定义候选",
    "domain_model": "当前展示的领域模型候选",
    "target_architecture": "当前展示的目标架构候选",
    "engineering_policy": "当前展示的工程政策候选",
}


class ProjectAuthorityDecisionError(ValueError):
    """One planned authority candidate cannot be read or confirmed exactly."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _plan(item: Mapping[str, Any]) -> Mapping[str, Any]:
    data = item.get("data")
    engineering = data.get("engineering") if isinstance(data, Mapping) else None
    plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
    confirmation = (
        engineering.get("plan_confirmation")
        if isinstance(engineering, Mapping)
        else None
    )
    if not isinstance(plan, Mapping) or not isinstance(confirmation, Mapping):
        raise ProjectAuthorityDecisionError(
            "project_authority_plan_missing",
            "当前建设事项没有已确认工程方案",
        )
    if confirmation.get("accepted") is not True:
        raise ProjectAuthorityDecisionError(
            "project_authority_plan_not_confirmed",
            "当前工程方案尚未由项目负责人接受",
        )
    return plan


def project_authority_plan_ref(item: Mapping[str, Any]) -> dict[str, Any]:
    """Return the immutable identity of the exact accepted engineering plan."""

    plan = _plan(item)
    plan_id = str(plan.get("plan_id") or "").strip()
    assessment_ref = plan.get("assessment_ref")
    data = item.get("data")
    engineering = data.get("engineering") if isinstance(data, Mapping) else None
    confirmation = (
        engineering.get("plan_confirmation")
        if isinstance(engineering, Mapping)
        else None
    )
    confirmation_fingerprint = (
        str(confirmation.get("candidate_fingerprint") or "").strip()
        if isinstance(confirmation, Mapping)
        else ""
    )
    if (
        not plan_id
        or not isinstance(assessment_ref, Mapping)
        or not str(assessment_ref.get("assessment_id") or "").strip()
        or type(assessment_ref.get("assessment_revision")) is not int
        or not confirmation_fingerprint
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_plan_identity_invalid",
            "长期权威候选必须绑定已确认工程方案的精确身份、评估修订和确认指纹",
        )
    return {
        "plan_id": plan_id,
        "assessment_ref": deepcopy(dict(assessment_ref)),
        "plan_content_sha256": _canonical_sha256(plan),
        "plan_confirmation_fingerprint": confirmation_fingerprint,
    }


def planned_upstream_authority_kinds(
    item: Mapping[str, Any],
    *,
    current_progress_only: bool,
) -> list[str]:
    """Return upstream authority kinds owned by all or active plan slices."""

    data = item.get("data")
    engineering = data.get("engineering") if isinstance(data, Mapping) else None
    plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
    if not isinstance(plan, Mapping):
        return []
    operations = [
        operation
        for operation in plan.get("operations") or []
        if isinstance(operation, Mapping)
    ]
    permitted: set[str] | None = None
    if current_progress_only and plan.get("implementation_slices"):
        receipts = data.get("verifications") if isinstance(data, Mapping) else []
        completions = (
            data.get("implementation_slice_completions")
            if isinstance(data, Mapping)
            else []
        )
        scope = permitted_slice_operation_paths(
            plan,
            receipts if isinstance(receipts, list) else [],
            completions if isinstance(completions, list) else [],
        )
        permitted = set(scope["permitted_paths"])
    kinds: set[str] = set()
    for operation in operations:
        paths = {
            str(operation.get(field) or "").replace("\\", "/").strip()
            for field in ("path", "to_path")
            if str(operation.get(field) or "").strip()
        }
        if permitted is not None and not paths.intersection(permitted):
            continue
        artifact = operation.get("long_lived_artifact")
        artifact_type = (
            str(artifact.get("artifact_type") or "")
            if isinstance(artifact, Mapping)
            else ""
        )
        kind = PROJECT_AUTHORITY_KIND_BY_ARTIFACT_TYPE.get(artifact_type)
        if kind is not None:
            kinds.add(kind)
    return [kind for kind in PROJECT_AUTHORITY_ORDER if kind in kinds]


def _planned_candidate_ref(
    item: Mapping[str, Any],
    authority_kind: str,
) -> dict[str, str]:
    if authority_kind not in PROJECT_AUTHORITY_KINDS:
        raise ProjectAuthorityDecisionError(
            "project_authority_kind_invalid",
            "长期权威种类必须是产品、领域、目标架构或工程政策之一",
        )
    plan = _plan(item)
    change_context = plan.get("change_context")
    expected_path = (
        str(
            change_context.get(_CHANGE_CONTEXT_PATH_BY_KIND[authority_kind])
            or ""
        ).strip()
        if isinstance(change_context, Mapping)
        else ""
    )
    change_set = plan.get("authority_change_set")
    exact_candidate = None
    if isinstance(change_set, Mapping):
        exact_candidate = next(
            (
                value
                for value in change_set.get("candidate_authorities") or []
                if isinstance(value, Mapping)
                and value.get("authority_kind") == authority_kind
            ),
            None,
        )
        if isinstance(exact_candidate, Mapping):
            expected_path = str(exact_candidate.get("path") or "").strip()
    expected_type = _ARTIFACT_TYPE_BY_KIND[authority_kind]
    operations = [
        value
        for value in plan.get("operations") or []
        if isinstance(value, Mapping)
        and isinstance(value.get("long_lived_artifact"), Mapping)
        and value["long_lived_artifact"].get("artifact_type") == expected_type
        and (
            not expected_path
            or str(
                (
                    value.get("to_path")
                    if value.get("action") == "move"
                    else value.get("path")
                )
                or ""
            ).replace("\\", "/")
            == expected_path.replace("\\", "/")
        )
    ]
    if len(operations) != 1:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_not_planned",
            "已确认工程方案没有唯一绑定该长期权威候选的根文件操作",
            details={
                "authority_kind": authority_kind,
                "candidate_count": len(operations),
            },
        )
    operation = operations[0]
    artifact = operation["long_lived_artifact"]
    result = {
        "authority_kind": authority_kind,
        "artifact_id": str(artifact.get("artifact_id") or "").strip(),
        "path": str(
            (
                operation.get("to_path")
                if operation.get("action") == "move"
                else operation.get("path")
            )
            or ""
        ).replace("\\", "/").strip(),
    }
    if operation.get("repository_id") is not None:
        result["repository_id"] = operation["repository_id"]
    if isinstance(exact_candidate, Mapping):
        result["revision_id"] = str(
            exact_candidate.get("revision_id") or ""
        ).strip()
    if not result["artifact_id"] or not result["path"]:
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_not_planned",
            "长期权威候选缺少稳定身份或根文件路径",
        )
    return result


def _stable_candidate_matches_plan(
    item: Mapping[str, Any],
    candidate: Mapping[str, Any],
    authority_kind: str,
) -> bool:
    """Compare only identities that may safely survive a plan revision."""

    try:
        planned = _planned_candidate_ref(item, authority_kind)
    except ProjectAuthorityDecisionError:
        return False
    if (
        candidate.get("authority_kind") != authority_kind
        or str(candidate.get("artifact_id") or "") != planned["artifact_id"]
        or str(candidate.get("path") or "") != planned["path"]
        or (planned.get("repository_id") is not None and candidate.get("repository_id") != planned["repository_id"])
    ):
        return False
    expected_revision = str(planned.get("revision_id") or "")
    if expected_revision and str(candidate.get("revision_id") or "") != expected_revision:
        return False
    governed = candidate.get("governed_paths")
    return (
        isinstance(governed, list)
        and bool(governed)
        and all(isinstance(path, str) and path.strip() for path in governed)
    )


def _candidate_binding_reference(
    candidate: Mapping[str, Any],
) -> dict[str, str]:
    reference = {
        "authority_kind": str(candidate.get("authority_kind") or ""),
        "artifact_id": str(candidate.get("artifact_id") or ""),
        "revision_id": str(candidate.get("revision_id") or ""),
        "path": str(candidate.get("path") or ""),
        "owner_id": str(candidate.get("owner_id") or ""),
        "content_state": "presented_candidate",
        "bound_content_sha256": str(candidate.get("content_sha256") or ""),
    }
    if any(not value for value in reference.values()):
        return {}
    if candidate.get("repository_id") is not None:
        reference["repository_id"] = candidate["repository_id"]
    return reference


def _decision_reference(record: Mapping[str, Any]) -> dict[str, str]:
    candidate = record.get("candidate")
    if not isinstance(candidate, Mapping):
        return {}
    return _candidate_binding_reference(candidate)


def _planned_kind_set(item: Mapping[str, Any]) -> set[str]:
    return set(
        planned_upstream_authority_kinds(
            item,
            current_progress_only=False,
        )
    )


def _upstream_refs_match_structure(
    item: Mapping[str, Any],
    authority_kind: str,
    candidate: Mapping[str, Any],
    bindings_by_kind: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Check prerequisite order and all refs decidable without reading files."""

    raw_refs = candidate.get("upstream_authority_refs")
    if not isinstance(raw_refs, list):
        return False
    prerequisites = _AUTHORITY_PREREQUISITES[authority_kind]
    if len(raw_refs) != len(prerequisites):
        return False
    planned_kinds = _planned_kind_set(item)
    for index, prerequisite in enumerate(prerequisites):
        raw = raw_refs[index]
        if not isinstance(raw, Mapping) or raw.get("authority_kind") != prerequisite:
            return False
        if prerequisite in planned_kinds:
            binding = bindings_by_kind.get(prerequisite)
            if not isinstance(binding, Mapping):
                return False
            if dict(raw) != dict(binding):
                return False
        elif any(
            not str(raw.get(field) or "").strip()
            for field in (
                "artifact_id",
                "revision_id",
                "path",
                "owner_id",
                "content_state",
                "bound_content_sha256",
            )
        ):
            return False
    return True


def project_authority_decision_matches_plan_structure(
    item: Mapping[str, Any],
    record: Mapping[str, Any],
    bindings_by_kind: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Pure projection check; file-backed validation remains the final gate."""

    if (
        record.get("schema_version") != PROJECT_AUTHORITY_DECISION_SCHEMA
        or not isinstance(record.get("confirmation"), Mapping)
        or record["confirmation"].get("accepted") is not True
        or not str(record.get("confirmed_content_sha256") or "").strip()
    ):
        return False
    candidate = record.get("candidate")
    if not isinstance(candidate, Mapping):
        return False
    kind = str(record.get("authority_kind") or "")
    return (
        kind in PROJECT_AUTHORITY_KINDS
        and _stable_candidate_matches_plan(item, candidate, kind)
        and _upstream_refs_match_structure(
            item,
            kind,
            candidate,
            bindings_by_kind,
        )
    )


def current_semantic_reviews(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Share the same recorded review selection for execution and results."""
    data = item.get("data") or {}
    plan = data.get("engineering", {}).get("plan") or {}
    result = []
    if isinstance(plan.get("semantic_review"), Mapping):
        result.append({"source_ref": "engineering.plan#/semantic_review", "review": deepcopy(dict(plan["semantic_review"]))})
    try:
        plan_ref = project_authority_plan_ref(item)
    except ProjectAuthorityDecisionError:
        return result
    records = data.get("project_authority_reviews") or []
    for index in range(len(records) - 1, -1, -1):
        record = records[index]
        if isinstance(record, Mapping) and record.get("plan_ref") == plan_ref and isinstance(record.get("semantic_review"), Mapping):
            result.append({"source_ref": f"project_authority_reviews#/{index}/semantic_review", "review": deepcopy(dict(record["semantic_review"]))})
            break
    return result


def current_project_authority_decisions(item: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return recorded decisions matching this plan, in upstream order.

    This is a read projection of stored declarations. Callers must still check
    the confirmed content against the selected repository bytes before use.
    """
    data = item.get("data") or {}
    if (data.get("engineering", {}).get("plan_confirmation") or {}).get("accepted") is not True:
        return []
    records = data.get("project_authority_decisions") or []
    bindings: dict[str, Mapping[str, Any]] = {}
    result = []
    for kind in planned_upstream_authority_kinds(item, current_progress_only=False):
        record = next((record for record in reversed(records)
            if isinstance(record, Mapping) and record.get("authority_kind") == kind
            and project_authority_decision_matches_plan_structure(item, record, bindings)), None)
        if record is not None:
            bindings[kind] = _decision_reference(record)
            result.append(deepcopy(dict(record)))
    return result


def project_authority_presentation_matches_plan_structure(
    item: Mapping[str, Any],
    presentation: Mapping[str, Any],
    authority_kind: str,
    bindings_by_kind: Mapping[str, Mapping[str, Any]],
) -> bool:
    """Prove a candidate was separately presented under the current plan."""

    candidate = presentation.get("candidate")
    challenge = presentation.get("confirmation_challenge")
    try:
        current_plan_ref = project_authority_plan_ref(item)
    except ProjectAuthorityDecisionError:
        return False
    return bool(
        presentation.get("schema_version")
        == PROJECT_AUTHORITY_PRESENTATION_SCHEMA
        and presentation.get("authority_kind") == authority_kind
        and type(presentation.get("presented_at_work_item_version")) is int
        and int(presentation["presented_at_work_item_version"])
        <= int(item.get("version") or 0)
        and isinstance(candidate, Mapping)
        and candidate.get("plan_ref") == current_plan_ref
        and _stable_candidate_matches_plan(item, candidate, authority_kind)
        and _upstream_refs_match_structure(
            item,
            authority_kind,
            candidate,
            bindings_by_kind,
        )
        and isinstance(challenge, Mapping)
        and dict(challenge) == authority_confirmation_challenge(item, candidate)
    )


def project_authority_review_matches_plan_structure(
    item: Mapping[str, Any],
    review: Mapping[str, Any],
    presentations: Sequence[Mapping[str, Any]],
) -> bool:
    """Match one agent review to the exact plan and presentation package."""

    try:
        plan_ref = project_authority_plan_ref(item)
    except ProjectAuthorityDecisionError:
        return False
    fingerprints = [
        str(value["confirmation_challenge"].get("candidate_fingerprint") or "")
        for value in presentations
        if isinstance(value, Mapping)
        and isinstance(value.get("confirmation_challenge"), Mapping)
    ]
    bundle = review.get("candidate_bundle")
    semantic_review = review.get("semantic_review")
    if not isinstance(bundle, Mapping) or not isinstance(semantic_review, Mapping):
        return False
    candidates = bundle.get("candidates")
    reviewed_refs = bundle.get("reviewed_refs")
    if (
        bundle.get("schema_version")
        != "strixnova.project-authority-review-bundle.v1"
        or bundle.get("plan_ref") != plan_ref
        or not isinstance(candidates, list)
        or not candidates
        or any(not isinstance(value, Mapping) for value in candidates)
        or not isinstance(reviewed_refs, list)
        or reviewed_refs != [_candidate_review_ref(value) for value in candidates]
    ):
        return False
    bundle_projection = deepcopy(dict(bundle))
    recorded_bundle_sha256 = str(bundle_projection.pop("content_sha256", ""))
    if not recorded_bundle_sha256 or recorded_bundle_sha256 != _canonical_sha256(
        bundle_projection
    ):
        return False
    candidates_by_kind = {
        str(value.get("authority_kind") or ""): value for value in candidates
    }
    for presentation in presentations:
        candidate = presentation.get("candidate")
        if not isinstance(candidate, Mapping):
            return False
        reviewed_candidate = candidates_by_kind.get(
            str(candidate.get("authority_kind") or "")
        )
        if not isinstance(reviewed_candidate, Mapping) or any(
            str(reviewed_candidate.get(field) or "")
            != str(candidate.get(field) or "")
            for field in (
                "authority_kind",
                "artifact_id",
                "revision_id",
                "path",
                "content_sha256",
            )
        ):
            return False
    return bool(
        review.get("schema_version") == PROJECT_AUTHORITY_REVIEW_SCHEMA
        and review.get("plan_ref") == plan_ref
        and review.get("presentation_fingerprints") == fingerprints
        and semantic_review.get("schema_version")
        == "strixnova.semantic-review.v1"
        and semantic_review.get("reviewed_refs") == reviewed_refs
        and review.get("semantic_content_machine_proven") is False
    )


def project_authority_stage(
    item: Mapping[str, Any],
    *,
    current_progress_only: bool,
) -> dict[str, Any] | None:
    """Project the next authority author/review/confirmation boundary."""

    # Candidate authoring is a pre-implementation governance boundary, not a
    # slice-local implementation action.  Always prepare and decide the whole
    # pending upstream package before any slice may produce implementation
    # evidence; slice ownership remains unchanged.
    required = planned_upstream_authority_kinds(
        item,
        current_progress_only=False,
    )
    if not required:
        return None
    data = item.get("data")
    records = data.get("project_authority_decisions") if isinstance(data, Mapping) else []
    presentations = (
        data.get("project_authority_presentations")
        if isinstance(data, Mapping)
        else []
    )
    records = records if isinstance(records, list) else []
    presentations = presentations if isinstance(presentations, list) else []
    reviews = (
        data.get("project_authority_reviews")
        if isinstance(data, Mapping)
        else []
    )
    reviews = reviews if isinstance(reviews, list) else []
    bindings_by_kind: dict[str, Mapping[str, Any]] = {}
    pending_presentations: list[dict[str, Any]] = []
    all_planned = planned_upstream_authority_kinds(
        item,
        current_progress_only=False,
    )
    for kind in all_planned:
        matching_record = next(
            (
                record
                for record in reversed(records)
                if isinstance(record, Mapping)
                and record.get("authority_kind") == kind
                and project_authority_decision_matches_plan_structure(
                    item,
                    record,
                    bindings_by_kind,
                )
            ),
            None,
        )
        if matching_record is not None:
            binding = _decision_reference(matching_record)
            if binding:
                bindings_by_kind[kind] = binding
                continue
        presentation = next(
            (
                value
                for value in reversed(presentations)
                if isinstance(value, Mapping)
                and project_authority_presentation_matches_plan_structure(
                    item,
                    value,
                    kind,
                    bindings_by_kind,
                )
            ),
            None,
        )
        if presentation is not None:
            candidate = presentation.get("candidate")
            if isinstance(candidate, Mapping):
                binding = _candidate_binding_reference(candidate)
                if binding:
                    bindings_by_kind[kind] = binding
            if kind in required:
                pending_presentations.append(deepcopy(dict(presentation)))
            continue
        if kind in required:
            return {
                "authority_kind": kind,
                "authority_kinds": [kind],
                "stage": "author",
                "presentation": None,
                "presentations": [],
            }
    if pending_presentations:
        matching_review = next(
            (
                value
                for value in reversed(reviews)
                if isinstance(value, Mapping)
                and project_authority_review_matches_plan_structure(
                    item,
                    value,
                    pending_presentations,
                )
            ),
            None,
        )
        if matching_review is None:
            return {
                "authority_kind": str(
                    pending_presentations[0]["authority_kind"]
                ),
                "authority_kinds": [
                    str(value["authority_kind"])
                    for value in pending_presentations
                ],
                "stage": "review",
                "presentation": deepcopy(pending_presentations[0]),
                "presentations": pending_presentations,
                "review": None,
            }
        return {
            "authority_kind": str(
                pending_presentations[0]["authority_kind"]
            ),
            "authority_kinds": [
                str(value["authority_kind"])
                for value in pending_presentations
            ],
            "stage": "confirm",
            "presentation": deepcopy(pending_presentations[0]),
            "presentations": pending_presentations,
            "review": deepcopy(dict(matching_review)),
        }
    return None


def current_project_authority_presentation(
    item: Mapping[str, Any],
    authority_kind: str,
) -> dict[str, Any]:
    """Return only the separately recorded presentation for the next kind."""

    stage = project_authority_stage(item, current_progress_only=True)
    if (
        not isinstance(stage, Mapping)
        or stage.get("authority_kind") != authority_kind
        or stage.get("stage") != "confirm"
        or not isinstance(stage.get("presentation"), Mapping)
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_not_presented",
            "长期权威候选必须先在独立事项版本中完整展示，随后才能确认",
        )
    return deepcopy(dict(stage["presentation"]))


def current_project_authority_presentations(
    item: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Return the complete, separately presented confirmation package."""

    stage = project_authority_stage(item, current_progress_only=True)
    if (
        not isinstance(stage, Mapping)
        or stage.get("stage") not in {"review", "confirm"}
        or not isinstance(stage.get("presentations"), list)
        or not stage["presentations"]
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_candidate_not_presented",
            "当前阶段的长期权威候选尚未形成完整独立展示包",
        )
    return [
        deepcopy(dict(value))
        for value in stage["presentations"]
        if isinstance(value, Mapping)
    ]


def current_project_authority_review(
    item: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the exact agent review that unlocked the confirmation package."""

    stage = project_authority_stage(item, current_progress_only=False)
    if (
        not isinstance(stage, Mapping)
        or stage.get("stage") != "confirm"
        or not isinstance(stage.get("review"), Mapping)
    ):
        raise ProjectAuthorityDecisionError(
            "project_authority_review_missing",
            "完整长期权威候选包尚未经过绑定精确正文的八视角复核",
        )
    return deepcopy(dict(stage["review"]))


def _candidate_review_ref(candidate: Mapping[str, Any]) -> str:
    return (
        "project_authority_candidate:"
        + str(candidate.get("authority_kind") or "")
        + ":"
        + str(candidate.get("artifact_id") or "")
        + ":"
        + str(candidate.get("revision_id") or "")
        + ":sha256:"
        + str(candidate.get("content_sha256") or "")
    )


def authority_confirmation_challenge(
    item: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Bind a user decision to one exact candidate within one WorkItem."""

    kind = str(candidate["authority_kind"])
    envelope = {
        "work_item_id": str(item["work_item_id"]),
        "candidate": dict(candidate),
    }
    digest = _canonical_sha256(envelope)
    decision_label = _DECISION_LABEL_BY_KIND[kind]
    return {
        "schema_version": CONFIRMATION_CHALLENGE_SCHEMA,
        "candidate_kind": f"project_authority:{kind}",
        "candidate_fingerprint": f"sha256:{digest}",
        "decision_label": decision_label,
        "decision_interpreter": "coding_agent",
    }


__all__ = [
    "PROJECT_AUTHORITY_CANDIDATE_SCHEMA",
    "PROJECT_AUTHORITY_DECISION_SCHEMA",
    "PROJECT_AUTHORITY_KIND_BY_ARTIFACT_TYPE",
    "PROJECT_AUTHORITY_KINDS",
    "PROJECT_AUTHORITY_ORDER",
    "PROJECT_AUTHORITY_PRESENTATION_SCHEMA",
    "PROJECT_AUTHORITY_REVIEW_SCHEMA",
    "ProjectAuthorityDecisionError",
    "authority_confirmation_challenge",
    "current_project_authority_presentation",
    "current_project_authority_presentations",
    "current_project_authority_review",
    "planned_upstream_authority_kinds",
    "project_authority_decision_matches_plan_structure",
    "project_authority_plan_ref",
    "project_authority_presentation_matches_plan_structure",
    "project_authority_prerequisites",
    "project_authority_review_matches_plan_structure",
    "project_authority_stage",
]
