"""Rebuild read-only engineering trace views from adopted and recorded facts."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from strixnova.delivery_activity import DeliveryActivityAuthority
from strixnova.project_authority_consistency import (
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
)
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.workflow_authority import WorkflowAuthority, WorkflowAuthorityError


TRACE_SCHEMA = "strixnova.engineering-trace-projection.v1"
TRACE_MODES = frozenset({"current", "audit"})

_AUTHORITY_ID_FIELDS = {
    "product_definition": "product_id",
    "domain_model": "model_id",
    "target_architecture": "architecture_id",
    "engineering_policy": "policy_id",
    "implementation_alignment": "alignment_model_id",
}
_NON_CURRENT_ITEM_STATES = frozenset(
    {"replanning_required", "cancelled_changes_pending", "cancelled"}
)


class EngineeringTraceProjectionError(ValueError):
    """A trace cannot be rebuilt without inventing missing facts."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class EngineeringTraceProjection:
    """A stateless query seam over immutable project and local event facts."""

    def __init__(
        self,
        project_dir: str | Path,
        *,
        authority: Any | None = None,
        management_dir: str | Path | None = None,
    ) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self.management_project = Path(management_dir).expanduser().resolve() if management_dir is not None else self.project
        self.authority = authority or WorkflowAuthority(self.management_project)

    def for_work_item(
        self,
        work_item_id: str,
        *,
        mode: str = "current",
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        selected_mode = self._mode(mode)
        commit, authorities = self._authority_snapshot(at_commit)
        try:
            item = self.authority.get(work_item_id)
            history = self.authority.history(work_item_id)
        except (WorkflowAuthorityError, KeyError) as error:
            raise EngineeringTraceProjectionError(
                getattr(error, "code", "work_item_not_found"),
                str(error),
            ) from error
        edges = self._work_item_edges(
            item,
            history,
            authorities,
            query_commit=commit,
            mode=selected_mode,
        )
        activities = DeliveryActivityAuthority(self.management_project).list(
            work_item_id=str(item["work_item_id"])
        )
        return {
            "schema_version": TRACE_SCHEMA,
            "view": "work_item",
            "mode": selected_mode,
            "at_commit": commit,
            "work_item": {
                "work_item_id": item["work_item_id"],
                "version": item["version"],
                "status": item["status"],
                "current_action": deepcopy(item.get("current_action")),
            },
            "authority_snapshot": self._authority_summary(authorities),
            "edges": edges,
            "external_activities": activities,
            "persisted_cache": False,
            "write_interface": False,
            "semantic_content_machine_proven": False,
        }

    def for_fact(
        self,
        fact_id: str,
        *,
        mode: str = "current",
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        selected_mode = self._mode(mode)
        commit, authorities = self._authority_snapshot(at_commit)
        identifier = self._identifier(fact_id, "fact_id")
        catalog = authorities["domain_catalog"]
        active = {str(fact["fact_id"]): fact for fact in catalog["facts"]}
        retired = {
            str(fact["fact_id"]): fact for fact in catalog["retired_facts"]
        }
        fact: dict[str, Any] | None = None
        if identifier in active:
            fact = ProjectAuthorityConsistency(
                self.project,
                observed_ref=commit,
            ).domain_fact_body(identifier)
            status = "current"
        elif identifier in retired:
            status = "retired"
            if selected_mode == "audit":
                fact = deepcopy(retired[identifier])
        else:
            status = "not_adopted"
        if selected_mode == "current" and status != "current":
            raise EngineeringTraceProjectionError(
                "domain_fact_not_current",
                f"当前采用领域模型中不存在有效事实：{identifier}",
            )

        edges = [
            edge
            for item in self.authority.list()
            for edge in self._work_item_edges(
                item,
                self.authority.history(str(item["work_item_id"])),
                authorities,
                query_commit=commit,
                mode=selected_mode,
                include_governance=False,
                include_activities=False,
            )
            if edge["target"].get("fact_id") == identifier
        ]
        alignment_record = next(
            (
                deepcopy(record)
                for record in authorities["implementation_alignment"][
                    "domain_fact_implementation"
                ]
                if record["domain_fact_id"] == identifier
            ),
            None,
        )
        return {
            "schema_version": TRACE_SCHEMA,
            "view": "domain_fact",
            "mode": selected_mode,
            "at_commit": commit,
            "fact_id": identifier,
            "fact_status": status,
            "fact": fact,
            "implementation_alignment": alignment_record,
            "edges": self._deduplicate(edges),
            "historical_references_retargeted": False,
            "persisted_cache": False,
            "write_interface": False,
            "semantic_content_machine_proven": False,
        }

    def for_artifact(
        self,
        artifact_id: str,
        *,
        mode: str = "current",
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        selected_mode = self._mode(mode)
        commit, authorities = self._authority_snapshot(at_commit)
        identifier = self._identifier(artifact_id, "artifact_id")
        formal = self._formal_artifact(identifier, authorities)
        edges = [
            edge
            for item in self.authority.list()
            for edge in self._work_item_edges(
                item,
                self.authority.history(str(item["work_item_id"])),
                authorities,
                query_commit=commit,
                mode=selected_mode,
                include_governance=False,
                include_activities=False,
            )
            if self._artifact_target_matches(edge["target"], identifier)
        ]
        current_refs = [
            edge
            for edge in edges
            if edge["provenance"]["source_kind"] == "current_work_item"
            and edge["target"].get("relation") != "removed"
        ]
        if formal is not None:
            status = "current"
            artifact = formal
        elif current_refs:
            status = "recorded_output"
            artifact = deepcopy(current_refs[-1]["target"])
        elif edges and selected_mode == "audit":
            status = "historical_only"
            artifact = None
        else:
            raise EngineeringTraceProjectionError(
                "engineering_artifact_not_found",
                f"没有可追溯的长期产物或权威：{identifier}",
            )
        return {
            "schema_version": TRACE_SCHEMA,
            "view": "long_lived_artifact",
            "mode": selected_mode,
            "at_commit": commit,
            "artifact_id": identifier,
            "artifact_status": status,
            "artifact": artifact,
            "edges": self._deduplicate(edges),
            "persisted_cache": False,
            "write_interface": False,
            "semantic_content_machine_proven": False,
        }

    def _authority_snapshot(
        self,
        at_commit: str | None,
    ) -> tuple[str, dict[str, Any]]:
        baseline_reader = ProjectEngineeringBaseline(self.project)
        try:
            if at_commit is None:
                configuration = baseline_reader.project_configuration()
                reference = configuration.get("default_integration_ref")
                if not reference:
                    raise EngineeringTraceProjectionError(
                        "integration_ref_required",
                        "工程追溯必须指定不可变版本或配置本地集成分支",
                    )
                commit = baseline_reader.resolve_code_ref(str(reference))
            else:
                commit = baseline_reader.resolve_code_ref(at_commit)
            authorities = ProjectAuthorityConsistency(
                self.project,
                observed_ref=commit,
            ).load()
        except EngineeringTraceProjectionError:
            raise
        except (
            ProjectEngineeringBaselineError,
            ProjectAuthorityConsistencyError,
        ) as error:
            raise EngineeringTraceProjectionError(
                "engineering_trace_authority_unavailable",
                str(error),
            ) from error
        return commit, authorities

    def _work_item_edges(
        self,
        item: Mapping[str, Any],
        history: list[Mapping[str, Any]],
        authorities: Mapping[str, Any],
        *,
        query_commit: str,
        mode: str,
        include_governance: bool = True,
        include_activities: bool = True,
    ) -> list[dict[str, Any]]:
        identifier = str(item["work_item_id"])
        source = {
            "authority_kind": "work_item",
            "work_item_id": identifier,
            "work_item_version": int(item["version"]),
        }
        if mode == "current" and item.get("status") in _NON_CURRENT_ITEM_STATES:
            return []
        edges: list[dict[str, Any]] = []
        if include_governance:
            for target in self._formal_authorities(authorities):
                edges.append(
                    self._edge(
                        "governed_by",
                        source,
                        target,
                        source_kind="adopted_authority_snapshot",
                        source_ref=query_commit,
                        adopted=True,
                    )
                )
        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        edges.extend(
            self._payload_edges(
                source,
                data,
                authorities,
                query_commit=query_commit,
                source_kind="current_work_item",
                source_ref=f"{identifier}@{item['version']}",
            )
        )
        if mode == "audit":
            for event in history:
                payload = (
                    event.get("payload")
                    if isinstance(event.get("payload"), Mapping)
                    else {}
                )
                edges.extend(
                    self._payload_edges(
                        source,
                        payload,
                        authorities,
                        query_commit=query_commit,
                        source_kind="authority_event",
                        source_ref=(
                            f"{identifier}@{event.get('version')}:"
                            f"{event.get('event_type')}"
                        ),
                    )
                )
        if include_activities:
            for activity in DeliveryActivityAuthority(self.management_project).list(
                work_item_id=identifier
            ):
                edges.append(
                    self._edge(
                        "external_activity",
                        source,
                        {
                            "authority_kind": "delivery_activity",
                            "activity_id": activity["activity_id"],
                            "activity_kind": activity["plan"]["activity_kind"],
                            "state": activity["state"],
                            "external_execution_required": True,
                        },
                        source_kind="delivery_activity_authority",
                        source_ref=(
                            f"{activity['activity_id']}@{activity['version']}"
                        ),
                        adopted=None,
                    )
                )
        return self._deduplicate(edges)

    def _payload_edges(
        self,
        source: Mapping[str, Any],
        payload: Mapping[str, Any],
        authorities: Mapping[str, Any],
        *,
        query_commit: str,
        source_kind: str,
        source_ref: str,
    ) -> list[dict[str, Any]]:
        active_fact_ids = {
            str(item["fact_id"])
            for item in authorities["domain_catalog"]["facts"]
        }
        retired_fact_ids = {
            str(item["fact_id"])
            for item in authorities["domain_catalog"]["retired_facts"]
        }
        result: list[dict[str, Any]] = []
        for reference in self._domain_references(payload):
            fact_id = str(reference["fact_id"])
            adopted = True if fact_id in active_fact_ids else False
            status = (
                "current"
                if fact_id in active_fact_ids
                else "retired"
                if fact_id in retired_fact_ids
                else "not_adopted"
            )
            result.append(
                self._edge(
                    "domain_fact_reference",
                    source,
                    {**deepcopy(reference), "fact_status_at_query_commit": status},
                    source_kind=source_kind,
                    source_ref=source_ref,
                    adopted=adopted,
                )
            )
        for reference in self._artifact_references(payload):
            relation = str(reference.get("relation") or "planned")
            formal = self._formal_artifact(
                str(reference.get("artifact_id") or reference.get("path")),
                authorities,
            )
            adopted = True if formal is not None else False if relation == "removed" else None
            result.append(
                self._edge(
                    "long_lived_output_reference",
                    source,
                    deepcopy(reference),
                    source_kind=source_kind,
                    source_ref=source_ref,
                    adopted=adopted,
                )
            )
        for receipt in self._verification_receipts(payload):
            result.append(
                self._edge(
                    "verification_receipt",
                    source,
                    {
                        "authority_kind": "verification_receipt",
                        "receipt_id": receipt.get("receipt_id"),
                        "command_id": receipt.get("command_id"),
                        "result": receipt.get("result"),
                    },
                    source_kind=source_kind,
                    source_ref=source_ref,
                    adopted=None,
                )
            )
        git = payload.get("git") if isinstance(payload.get("git"), Mapping) else payload
        if isinstance(git, Mapping):
            for commit in git.get("result_commits") or []:
                result.append(
                    self._edge(
                        "result_commit",
                        source,
                        {
                            "authority_kind": "external_version_fact",
                            "commit": str(commit),
                        },
                        source_kind=source_kind,
                        source_ref=source_ref,
                        adopted=(str(commit) == query_commit) or None,
                    )
                )
            integration = git.get("integration")
            if isinstance(integration, Mapping):
                integrated_commit = integration.get("integrated_commit")
                if integrated_commit:
                    result.append(
                        self._edge(
                            "local_integration_receipt",
                            source,
                            {
                                "authority_kind": "external_version_fact",
                                "integrated_commit": str(integrated_commit),
                                "result_commits": list(
                                    integration.get("result_commits") or []
                                ),
                            },
                            source_kind=source_kind,
                            source_ref=source_ref,
                            adopted=(str(integrated_commit) == query_commit) or None,
                        )
                    )
        return result

    @staticmethod
    def _domain_references(value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(candidate: Any) -> None:
            if isinstance(candidate, Mapping):
                if (
                    candidate.get("authority_kind") == "project_domain_model"
                    and isinstance(candidate.get("fact_id"), str)
                ):
                    result.append(deepcopy(dict(candidate)))
                for child in candidate.values():
                    visit(child)
            elif isinstance(candidate, list):
                for child in candidate:
                    visit(child)

        visit(value)
        return EngineeringTraceProjection._deduplicate(result)

    @staticmethod
    def _artifact_references(value: Any) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []

        def visit(candidate: Any) -> None:
            if isinstance(candidate, Mapping):
                if isinstance(candidate.get("artifact_id"), str) and (
                    "artifact_type" in candidate or "path" in candidate
                ):
                    result.append(deepcopy(dict(candidate)))
                for child in candidate.values():
                    visit(child)
            elif isinstance(candidate, list):
                for child in candidate:
                    visit(child)

        visit(value)
        return EngineeringTraceProjection._deduplicate(result)

    @staticmethod
    def _verification_receipts(value: Mapping[str, Any]) -> list[dict[str, Any]]:
        receipts: list[dict[str, Any]] = []
        direct = value.get("verifications")
        if isinstance(direct, list):
            receipts.extend(
                deepcopy(item) for item in direct if isinstance(item, Mapping)
            )
        receipt = value.get("verification")
        if isinstance(receipt, Mapping):
            receipts.append(deepcopy(dict(receipt)))
        if value.get("schema_version") == "strixnova.verification-summary.v1":
            receipts.append(deepcopy(dict(value)))
        return EngineeringTraceProjection._deduplicate(receipts)

    @staticmethod
    def _formal_authorities(
        authorities: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        baseline = authorities["baseline"]
        result: list[dict[str, Any]] = [
            {
                "authority_kind": "project_engineering_baseline",
                "authority_id": baseline["baseline_id"],
                "path": baseline.get("_manifest_path"),
                "observed_commit": authorities["observed_commit"],
            }
        ]
        for kind, identifier_field in _AUTHORITY_ID_FIELDS.items():
            reference = baseline["authority_refs"][kind]
            result.append(
                {
                    "authority_kind": kind,
                    "authority_id": reference[identifier_field],
                    "revision_id": reference["revision_id"],
                    "path": reference["path"],
                    "revision_status": reference["status"]["revision_status"],
                    "adoption_status": reference["status"]["adoption_status"],
                    "observed_commit": authorities["observed_commit"],
                }
            )
        return result

    @classmethod
    def _formal_artifact(
        cls,
        identifier: str,
        authorities: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        candidates = cls._formal_authorities(authorities)
        architecture = authorities["target_architecture"]
        for label, path in architecture["artifact_paths"].items():
            candidates.append(
                {
                    "authority_kind": "target_architecture_artifact",
                    "authority_id": label,
                    "path": path,
                    "observed_commit": authorities["observed_commit"],
                }
            )
        alignment = authorities["implementation_alignment"]
        for label, path in alignment["artifact_paths"].items():
            candidates.append(
                {
                    "authority_kind": "implementation_alignment_artifact",
                    "authority_id": label,
                    "path": path,
                    "observed_commit": authorities["observed_commit"],
                }
            )
        domain = authorities["domain_catalog"]
        for record in [*domain["collections"], *domain["sources"]]:
            authority_id = record.get("collection_id") or record.get("source_id")
            candidates.append(
                {
                    "authority_kind": "domain_model_artifact",
                    "authority_id": authority_id,
                    "path": record.get("path"),
                    "observed_commit": authorities["observed_commit"],
                }
            )
        return next(
            (
                deepcopy(candidate)
                for candidate in candidates
                if identifier
                in {
                    str(candidate.get("authority_id") or ""),
                    str(candidate.get("path") or ""),
                }
            ),
            None,
        )

    @staticmethod
    def _artifact_target_matches(
        target: Mapping[str, Any],
        identifier: str,
    ) -> bool:
        return identifier in {
            str(target.get("artifact_id") or ""),
            str(target.get("path") or ""),
            str(target.get("authority_id") or ""),
        }

    @staticmethod
    def _authority_summary(authorities: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "baseline_id": authorities["baseline"]["baseline_id"],
            "observed_commit": authorities["observed_commit"],
            "current_architecture_stage_id": authorities[
                "current_architecture_stage_id"
            ],
            "structurally_consistent": authorities["structurally_consistent"],
            "review_state": deepcopy(authorities["review_state"]),
        }

    @staticmethod
    def _edge(
        edge_kind: str,
        source: Mapping[str, Any],
        target: Mapping[str, Any],
        *,
        source_kind: str,
        source_ref: str,
        adopted: bool | None,
    ) -> dict[str, Any]:
        return {
            "edge_kind": edge_kind,
            "source": deepcopy(dict(source)),
            "target": deepcopy(dict(target)),
            "provenance": {
                "source_kind": source_kind,
                "source_ref": source_ref,
            },
            "adopted_at_query_commit": adopted,
        }

    @staticmethod
    def _deduplicate(values: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        result: list[dict[str, Any]] = []
        for value in values:
            key = json.dumps(value, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                result.append(value)
        return result

    @staticmethod
    def _mode(value: str) -> str:
        if value not in TRACE_MODES:
            raise EngineeringTraceProjectionError(
                "invalid_trace_mode",
                "工程追溯模式必须是 current（当前）或 audit（审计）",
            )
        return value

    @staticmethod
    def _identifier(value: str, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise EngineeringTraceProjectionError(
                "invalid_trace_identifier",
                f"{field} 必须是非空字符串",
            )
        return value.strip()


__all__ = [
    "EngineeringTraceProjection",
    "EngineeringTraceProjectionError",
    "TRACE_SCHEMA",
]
