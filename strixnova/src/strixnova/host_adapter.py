"""Thin local request and query adapter for coding agents."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from functools import wraps
from pathlib import Path
from typing import Any

from strixnova.application_coordinator import (
    REPLAN_REQUEST_SCHEMA,
    ApplicationCoordinator,
    ApplicationCoordinatorError,
)
from strixnova.public_input_contract import (
    PublicInputContractError,
    input_contract_for,
)
from strixnova.work_item_read_model import ProjectContextQueryError, WorkItemReadModel
from strixnova.work_item_history import HistoryQueryError
from strixnova.prepared_input import (
    PreparedInputError, prepare as prepare_input_context, result_requirements,
    check_context, assemble as assemble_input, evidence_catalog, schema_issues, digest,
)
from strixnova.confirmation_protocol import ConfirmationProtocolError
from strixnova.project_content_snapshot import snapshot_observations
from strixnova.test_case_evidence import preflight_case_report, TestCaseEvidenceError
from strixnova.work_item_repositories import repository_item
from strixnova.record_reading import RecordReadingError, bounded_next, select, split_reference


HOST_ADAPTER_SCHEMA = "strixnova.local-host-adapter.v1"
_FOCUSED_TRACE_RECORDS = {
    "engineering.trace.current": "current",
    "engineering.trace.audit": "audit",
}


class HostAdapterError(ValueError):
    """One explicit adapter request could not be converted or completed."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _adapter_use_case(function: Any) -> Any:
    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            with args[0].coordinator.read_operation():
                return function(*args, **kwargs)
        except ApplicationCoordinatorError as error:
            raise HostAdapterError(
                error.code,
                str(error),
                details=error.details,
            ) from error
        except (RecordReadingError, PreparedInputError, ConfirmationProtocolError, TestCaseEvidenceError) as error:
            raise HostAdapterError(error.code, str(error), details=getattr(error, "details", None)) from error

    return wrapped


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HostAdapterError(
            "invalid_record_refs",
            f"{field} 必须是非空字符串",
        )
    return value.strip()


class LocalHostAdapter:
    """Application-facing intents with no session or execution authority."""

    adapter_id = "local-request-adapter-v2"

    @staticmethod
    def context_contract(action: str) -> dict[str, Any]:
        try:
            return WorkItemReadModel.context_contract(action)
        except ProjectContextQueryError as error:
            raise HostAdapterError(error.code, str(error), details=error.details) from error

    @staticmethod
    def query_project_context(
        project_dir: str | Path, action: str, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        try:
            return WorkItemReadModel.query_project_context(project_dir, action, request)
        except ProjectContextQueryError as error:
            raise HostAdapterError(error.code, str(error), details=error.details) from error

    def __init__(self, project_dir: str | Path, *, project_bindings: Mapping[str, Any] | None = None) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        try:
            context = WorkItemReadModel.prepare_project_context(project_dir, project_bindings) if project_bindings is not None else None
        except ProjectContextQueryError:
            # Explicit management binding remains usable for stored cancellation
            # and history; ordinary coordinator operations resolve content again.
            context = None
        self.coordinator = ApplicationCoordinator(self.project, project_bindings=project_bindings, shared_context=context)
        self.read_model = WorkItemReadModel(self.project, project_bindings=project_bindings, shared_context=context)

    @_adapter_use_case
    def history(self, **query: Any) -> dict[str, Any]:
        try:
            return self.read_model.history_query(**query)
        except HistoryQueryError as error:
            raise HostAdapterError(error.code, str(error)) from error

    def describe(self) -> dict[str, Any]:
        return {
            "schema_version": HOST_ADAPTER_SCHEMA,
            "adapter_id": self.adapter_id,
            "transport": "local_explicit_intents",
            "reads_current_action": True,
            "accepts_coding_agent_candidates": True,
            "reports_execution_facts": True,
            "issues_credentials": False,
            "owns_sessions": False,
            "maintains_leases": False,
            "controls_remote_git": False,
        }

    @_adapter_use_case
    def prepare_input(self, work_item_id: str, *, receipt_id: str | None = None) -> dict[str, Any]:
        """Freeze a transport context; no event, decision or external action."""
        current = self.read_model.focused_work_item(work_item_id)["work_item"]
        current["current_action"] = self._applicable_current_action(current)
        action = current["current_action"]
        if not action:
            raise HostAdapterError("current_action_missing", "This item has no pending action")
        contract = input_contract_for(action)
        result = None
        if action["action_type"] in {"investigate_and_report", "present_actual_result", "present_actual_result_after_conflict"}:
            _, coverage = self.read_model._verification_state(current)
            subject = self.read_model.current_review_subject(work_item_id, expected_version=current["version"])
            result = result_requirements(current, coverage, subject["subject_ref"])
        context = prepare_input_context(current, contract, project=str(self.project), result=result)
        context["evidence_catalog"] = evidence_catalog(context)
        if receipt_id is not None:
            if action["action_type"] != "assess_verification_change" or "verifications:" + receipt_id not in action.get("record_refs", []):
                raise HostAdapterError("verification_receipt_not_current", "Select a receipt from the current assessment action")
            receipt = next(item for item in current["data"].get("verifications", []) if item["receipt_id"] == receipt_id)
            context["template"].update({"receipt_id": receipt_id, "command_id": receipt["command_id"], "mode": "assess"})
            context["binding"]["receipt_id"] = receipt_id
            command = next(item for item in current["data"]["engineering"]["plan"]["verification_commands"] if item["command_id"] == receipt["command_id"])
            try:
                live = self.coordinator._verification_input_snapshot(current, command)
                context["verification_observations"] = snapshot_observations(receipt.get("project_input_snapshot"), live)
            except (OSError, ValueError) as error:
                context["verification_observations"] = {**snapshot_observations(receipt.get("project_input_snapshot"), None), "read_error": str(error)}
            context["verification_observations"]["inputs_changed_during_execution"] = receipt.get("inputs_changed_during_execution")
            context["verification_observations"]["recorded_limitations"] = deepcopy(receipt.get("limitations") or [])
            context["verification_observations"]["recorded_dependency_evidence"] = deepcopy(receipt.get("dependency_evidence"))
            context["context_sha256"] = digest({key: value for key, value in context.items() if key != "context_sha256"})
        context["context_sha256"] = digest({key: value for key, value in context.items() if key != "context_sha256"})
        return context

    def _check_prepared_input(self, context: Mapping[str, Any]) -> None:
        binding = context.get("binding")
        if not isinstance(binding, Mapping) or not isinstance(binding.get("work_item_id"), str):
            raise HostAdapterError("prepared_input_invalid", "Missing prepared input binding")
        check_context(context, self.prepare_input(binding["work_item_id"], receipt_id=binding.get("receipt_id")))

    @_adapter_use_case
    def preview_input(self, context: Mapping[str, Any], submission: Mapping[str, Any],
                      *, user_message: str | None = None) -> dict[str, Any]:
        """Read-only assembly and all schema errors; never pre-authorizes a write."""
        self._check_prepared_input(context)
        issues = []
        try:
            payload = assemble_input(context, submission, user_message=user_message)
        except PreparedInputError as error:
            payload = error.payload
            issues = error.details if isinstance(error.details, list) else [{"code": error.code, "message": str(error), "details": error.details}]
        if payload is None:
            return {"ok": False, "payload": None, "issues": issues, "semantic_content_machine_proven": False}
        issues.extend(schema_issues(context, payload))
        action = context["binding"]["action"]
        if not issues and action["action_type"] in {"investigate_and_report", "present_actual_result", "present_actual_result_after_conflict"}:
            try:
                self.coordinator.check_actual_result(context["binding"]["work_item_id"], payload,
                    expected_version=context["binding"]["work_item_version"])
            except ApplicationCoordinatorError as error:
                issues.append({"code": error.code, "message": str(error), "details": error.details})
        self._check_prepared_input(context)
        return {"ok": not issues, "payload": payload, "issues": issues,
                "scope": "input_schema_and_result_checks" if action["action_type"].startswith("present_actual_result") else "input_schema",
                "effects_revalidated_on_apply": True, "semantic_content_machine_proven": False}

    @_adapter_use_case
    def apply_input(self, context: Mapping[str, Any], submission: Mapping[str, Any],
                    *, user_message: str | None = None) -> dict[str, Any]:
        """Route one explicit submission through the existing application methods."""
        self._check_prepared_input(context)
        payload = assemble_input(context, submission, user_message=user_message)
        issues = schema_issues(context, payload)
        if issues:
            raise HostAdapterError("prepared_input_incomplete", "Input is incomplete or structurally invalid", details=issues)
        binding = context["binding"]
        work_item_id, version = binding["work_item_id"], binding["work_item_version"]
        command, action = context["contract"]["command"], binding["action"]
        if command == "submit":
            result = self.coordinator.submit_current_action_input(work_item_id, payload, expected_version=version)
        elif command == "confirm":
            result = self.coordinator.confirm(work_item_id, action["confirmation_challenge"]["candidate_kind"],
                                              **payload, expected_version=version)
        elif command == "delivery":
            result = self.coordinator.delivery(work_item_id, payload, expected_version=version)
        elif command == "cancel":
            result = self.coordinator.cancel(work_item_id, payload, expected_version=version)
        elif command == "verify":
            result = self.coordinator.verify(work_item_id, payload, expected_version=version)
        elif command == "authority" and action["action_type"] == "review_project_authority_candidates":
            result = self.coordinator.review_project_authorities(work_item_id, payload, expected_version=version)
        elif command == "authority" and action["action_type"] == "confirm_project_authority_candidates":
            result = self.coordinator.confirm_project_authorities(work_item_id, payload, expected_version=version)
        elif command == "authority" and action["action_type"] == "author_project_authority_candidate":
            result = self.coordinator.project_authority_candidate(work_item_id, action["authority_kind"], expected_version=version)
        else:
            raise HostAdapterError("prepared_route_unavailable", "Use the explicit command from the input contract for this action")
        return {"ok": True, "result": result, "next": self.next_step(work_item_id)}


    @_adapter_use_case
    def current_action(self, work_item_id: str) -> dict[str, Any] | None:
        current = self.read_model.focused_work_item(work_item_id)["work_item"]
        return self._applicable_current_action(current)

    def _applicable_current_action(
        self,
        current: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Use the read model's live action, then hide inapplicable reads."""

        action = current.get("current_action")
        if not isinstance(action, Mapping):
            return None
        projected = deepcopy(dict(action))
        if not projected.get("conditional_record_refs"):
            return projected
        try:
            status = self.read_model.project_status()
        except ValueError:
            # A declared but invalid authority chain remains visible so its
            # stable project-status or record error is not silently bypassed.
            return projected
        if status.get("baseline_id") is None and status.get(
            "observed_commit"
        ) is None:
            projected["conditional_record_refs"] = []
        return projected

    def follow_ups(self, **query: Any) -> dict[str, Any]:
        try:
            return self.read_model.follow_ups(**query)
        except ValueError as error:
            raise HostAdapterError(getattr(error, "code", "follow_up_query_failed"), str(error)) from error

    @_adapter_use_case
    def project_status(
        self,
        *,
        at_commit: str | None = None,
        working_tree: bool = False,
    ) -> dict[str, Any]:
        try:
            return self.read_model.project_status(
                at_commit=at_commit,
                working_tree=working_tree,
            )
        except ValueError as error:
            raise HostAdapterError(
                getattr(error, "code", "project_status_query_failed"),
                str(error),
                details=getattr(error, "issues", None),
            ) from error

    @_adapter_use_case
    def preflight_cases(self, context: Mapping[str, Any], command_id: str, report: Mapping[str, Any]) -> dict[str, Any]:
        self._check_prepared_input(context)
        current = self.read_model.focused_work_item(context["binding"]["work_item_id"])["work_item"]
        plan = (current["data"].get("engineering") or {}).get("plan") or {}
        command = next((item for item in plan.get("verification_commands", []) if item["command_id"] == command_id), None)
        if command is None or not command.get("case_report"):
            raise HostAdapterError("test_case_command_missing", "Select an approved command with a case-report contract")
        selected = repository_item(current, command.get("repository_id"))
        root = self.coordinator._verification_execution_root(selected)
        result = preflight_case_report(report, config=command["case_report"], execution_root=Path(root))
        result["approved_command"] = deepcopy(command)
        self._check_prepared_input(context)
        return result

    @_adapter_use_case
    def present_authorities(self, context: Mapping[str, Any], authority_kinds: list[str]) -> dict[str, Any]:
        """Register caller-selected ready candidates; stop at every judgment gate.

        Each successful kind retains its normal event and version. A later
        failure returns the completed prefix explicitly; this is not an atomic
        owner decision and never marks a candidate accepted or understood.
        """
        self._check_prepared_input(context)
        allowed = {"product_definition", "domain_model", "target_architecture", "engineering_policy"}
        if not isinstance(authority_kinds, list) or not authority_kinds or any(not isinstance(k, str) or k not in allowed for k in authority_kinds) or len(set(authority_kinds)) != len(authority_kinds):
            raise HostAdapterError("authority_batch_invalid", "Select distinct explicit upstream authority kinds")
        binding = context["binding"]
        identifier, version = binding["work_item_id"], binding["work_item_version"]
        action, completed, stopped = binding["action"], [], None
        for kind in authority_kinds:
            if action.get("action_type") != "author_project_authority_candidate" or action.get("authority_kind") != kind:
                stopped = {"code": "authority_batch_boundary", "authority_kind": kind, "current_action": action}
                break
            try:
                value = self.coordinator.project_authority_candidate(identifier, kind, expected_version=version)
            except ApplicationCoordinatorError as error:
                stopped = {"code": error.code, "message": str(error), "authority_kind": kind, "details": error.details}
                break
            completed.append({"authority_kind": kind, **value})
            version = value["presented_at_work_item_version"]
            action = value.get("current_action") or {}
        return {"ok": stopped is None, "presented": completed, "stopped": stopped,
                "next": self.next_step(identifier), "semantic_content_machine_proven": False}

    @_adapter_use_case
    def project_authority_candidate(
        self,
        work_item_id: str,
        authority_kind: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.project_authority_candidate(
            work_item_id,
            authority_kind,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def project_authority_review_candidate(
        self,
        work_item_id: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.project_authority_review_candidate(
            work_item_id,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def review_project_authorities(
        self,
        work_item_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.review_project_authorities(
            work_item_id,
            payload,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def confirm_project_authorities(
        self,
        work_item_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.confirm_project_authorities(
            work_item_id,
            payload,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def next_step(
        self,
        work_item_id: str,
        *,
        record_refs: list[str] | tuple[str, ...] = (),
        max_output_bytes: int | None = None,
        cursor: str | None = None,
        expected_version: int | None = None,
        expected_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Return the small next action plus explicitly requested records."""

        current = self.read_model.focused_work_item(work_item_id)["work_item"]
        if expected_version is not None and current['version'] != expected_version:
            raise HostAdapterError('record_read_source_changed', '事项版本已变化；重新读取当前行动')
        action = self._applicable_current_action(current)
        projected_current = deepcopy(current)
        projected_current["current_action"] = action
        requested = [
            _required_text(ref, f"record_refs[{index}]")
            for index, ref in enumerate(record_refs)
        ]
        if len(set(requested)) != len(requested):
            raise HostAdapterError(
                "invalid_record_refs",
                "record_refs 必须是互不重复的非空记录引用",
            )
        allowed = set(action.get("record_refs") or []) if isinstance(
            action, Mapping
        ) else set()
        if isinstance(action, Mapping):
            allowed.update(action.get("conditional_record_refs") or [])
            contract_ref = action.get("input_contract_ref")
            if isinstance(contract_ref, str) and contract_ref:
                allowed.add(contract_ref)
        resolved = {ref: split_reference(ref, allowed | set(_FOCUSED_TRACE_RECORDS)) for ref in requested}
        unavailable = sorted(
            original_ref
            for original_ref, (ref, _) in resolved.items()
            if ref not in allowed
            and ref not in _FOCUSED_TRACE_RECORDS
            and not (
                "project.domain.catalog" in allowed
                and (
                    ref.startswith("project.domain.collection:")
                    or ref.startswith("project.domain.source:")
                    or ref.startswith("project.domain.fact:")
                    or ref.startswith("project.domain.closure:")
                )
            )
        )
        if unavailable:
            raise HostAdapterError(
                "record_not_available_for_action",
                "当前动作不需要这些记录：" + ", ".join(unavailable),
            )
        try:
            project_at_commit = (
                self.read_model.adopted_project_commit()
                if any(
                    ref.startswith("project.")
                    and ref not in {"project.direction_context", "project.follow_ups"}
                    for ref, _ in resolved.values()
                )
                else self.read_model.execution_basis_commit(current)
                if any(ref == "engineering.execution_context" or ref.startswith("engineering.plan.implementation_slice:") for ref, _ in resolved.values())
                else None
            )
        except ValueError as error:
            raise HostAdapterError(
                getattr(error, "code", "project_authority_invalid"),
                str(error),
            ) from error
        base = {
            "schema_version": "strixnova.next-step.v1",
            "work_item_id": current["work_item_id"],
            "work_item_version": current["version"],
            "work_item_status": current["status"],
            "current_action": deepcopy(action),
            "relations": self.read_model.work_item_relations(work_item_id),
            "records": {},
        }
        sources = {root: self._record_for_ref(projected_current, root, project_at_commit=project_at_commit)
                   for root in {root for root, _ in resolved.values()}}
        selections = {ref: (root, parts, sources[root]) for ref, (root, parts) in resolved.items()}
        if max_output_bytes is not None:
            return bounded_next(base, selections, max_output_bytes=max_output_bytes,
                                cursor=cursor, expected_sha256=expected_sha256)
        if cursor is not None or expected_sha256 is not None:
            raise HostAdapterError('record_read_budget_required', '续读和内容校验需要明确返回预算')
        base['records'] = {ref: deepcopy(select(source, parts)) for ref, (_, parts, source) in selections.items()}
        return base

    @_adapter_use_case
    def read_materials(self, work_item_id: str, *, record_refs: list[str] | tuple[str, ...]) -> dict[str, Any]:
        """Assemble only caller-selected references and verify a single read version.

        Persist or inspect the returned structured material; do not dump it into
        the host transcript. Every read still uses the same allowed-record gate.
        """
        if not record_refs:
            raise HostAdapterError("invalid_record_refs", "Select at least one record")
        result = self.next_step(work_item_id, record_refs=record_refs)
        again = self.next_step(work_item_id, record_refs=record_refs, expected_version=result["work_item_version"])
        if digest(result["records"]) != digest(again["records"]):
            raise HostAdapterError("record_read_source_changed", "Selected material changed during assembly")
        result["record_sources"] = {ref: {"sha256": digest(value)} for ref, value in result["records"].items()}
        result["reading"] = {"complete": True, "scope": list(record_refs), "unread_refs": [],
                             "semantic_content_machine_proven": False}
        return result

    def _record_for_ref(
        self,
        current: Mapping[str, Any],
        ref: str,
        *,
        project_at_commit: str | None = None,
    ) -> Any:
        try:
            action = current.get("current_action")
            if (
                isinstance(action, Mapping)
                and ref == action.get("input_contract_ref")
            ):
                return input_contract_for(action)
            if ref in _FOCUSED_TRACE_RECORDS:
                return self.read_model.engineering_trace_for_work_item(
                    str(current["work_item_id"]),
                    mode=_FOCUSED_TRACE_RECORDS[ref],
                )
            if ref == "project.follow_ups":
                return self.follow_ups()
            if ref == "engineering.execution_context":
                return self.read_model.execution_context(current, at_commit=project_at_commit)
            if ref == "engineering.review_subject":
                return self.read_model.current_review_subject(current["work_item_id"], expected_version=current["version"])
            if ref == "repository_deliveries":
                return self.read_model.repository_deliveries(str(current["work_item_id"]))
            if ref == "project.direction_context":
                return self.read_model.project_direction_context(
                    at_commit=project_at_commit,
                )
            if ref == "project.engineering":
                return self.read_model.project_engineering_governance(
                    at_commit=project_at_commit,
                )
            if ref == "project.engineering.assurance":
                return self.read_model.project_engineering_assurance(
                    at_commit=project_at_commit,
                )
            if ref == "project.domain.catalog":
                return self.read_model.project_domain_catalog(
                    at_commit=project_at_commit,
                )
            if ref.startswith("project.domain.collection:"):
                parts = ref.partition(":")[2].split(":", 2)
                if len(parts) != 3 or not all(part.strip() for part in parts):
                    raise HostAdapterError(
                        "invalid_record_ref",
                        "project.domain.collection 必须指定身份、父级和路径",
                    )
                return self.read_model.project_domain_collection(
                    parts[0].strip(),
                    parent_collection_id=(
                        None if parts[1].strip() == "ROOT" else parts[1].strip()
                    ),
                    collection_path=parts[2].strip(),
                    at_commit=project_at_commit,
                )
            if ref.startswith("project.domain.source:"):
                parts = ref.partition(":")[2].split(":", 1)
                if len(parts) != 2 or not all(part.strip() for part in parts):
                    raise HostAdapterError(
                        "invalid_record_ref",
                        "project.domain.source 必须指定 Source ID 和 Collection 路径",
                    )
                return self.read_model.project_domain_source(
                    parts[0].strip(),
                    collection_path=parts[1].strip(),
                    at_commit=project_at_commit,
                )
            if ref.startswith("project.domain.fact:"):
                parts = ref.partition(":")[2].split(":", 4)
                if len(parts) != 5 or not all(part.strip() for part in parts):
                    raise HostAdapterError(
                        "invalid_record_ref",
                        "project.domain.fact 必须指定 Fact、Source、Collection 和路径",
                    )
                return self.read_model.project_domain_fact(
                    parts[0].strip(),
                    source_id=parts[1].strip(),
                    collection_id=parts[2].strip(),
                    collection_path=parts[3].strip(),
                    source_path=parts[4].strip(),
                    at_commit=project_at_commit,
                )
            if ref.startswith("project.domain.closure:"):
                fact_ids = [
                    value.strip()
                    for value in ref.partition(":")[2].split(",")
                    if value.strip()
                ]
                if not fact_ids:
                    raise HostAdapterError(
                        "invalid_record_ref",
                        "project.domain.closure 必须指定至少一个 Fact ID",
                    )
                return self.read_model.project_domain_closure(
                    fact_ids,
                    at_commit=project_at_commit,
                )
            if ref.startswith("engineering.plan.implementation_slice:"):
                slice_id = ref.partition(":")[2].strip()
                if not slice_id:
                    raise HostAdapterError(
                        "invalid_record_ref",
                        "实施切片记录引用必须指定切片身份",
                    )
                return self.read_model.execution_slice(current, slice_id, at_commit=project_at_commit)
            if ref == "project.architecture":
                return self.read_model.project_architecture(
                    at_commit=project_at_commit,
                )
            if ref == "project.domain.alignment":
                return self.read_model.project_domain_alignment(
                    at_commit=project_at_commit,
                )
            if ref == "delivery.authority_adoption":
                return self.read_model.authority_adoption(current)
        except HostAdapterError:
            raise
        except PublicInputContractError as error:
            raise HostAdapterError(
                "public_input_contract_invalid",
                str(error),
            ) from error
        except ValueError as error:
            raise HostAdapterError(
                getattr(error, "code", "project_authority_invalid"),
                str(error),
                details=getattr(error, "details", None),
            ) from error
        data = current.get("data")
        data = data if isinstance(data, Mapping) else {}
        if ref == "request":
            return {
                "title": str(current.get("title") or ""),
                "raw_request": str(data.get("raw_request") or ""),
            }
        if ref.startswith("verifications:"):
            receipt_id = ref.partition(":")[2]
            for receipt in data.get("verifications") or []:
                if (
                    isinstance(receipt, Mapping)
                    and receipt.get("receipt_id") == receipt_id
                ):
                    return deepcopy(dict(receipt))
            raise HostAdapterError(
                "record_missing",
                f"验证回执不存在：{receipt_id}",
            )
        value: Any = data
        for part in ref.split("."):
            if not isinstance(value, Mapping):
                return None
            value = value.get(part)
        return deepcopy(value)

    @_adapter_use_case
    def submit_current_action_input(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.submit_current_action_input(
            work_item_id,
            value,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def request_replan(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.request_replan(
            work_item_id,
            value,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def submit_direction(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.submit_direction(
            work_item_id,
            value,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def submit_engineering_assessment(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.submit_engineering_assessment(
            work_item_id,
            value,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def confirm(
        self,
        work_item_id: str,
        kind: str,
        *,
        candidate_fingerprint: str,
        user_confirmation: str,
        agent_decision: Mapping[str, Any],
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.confirm(
            work_item_id,
            kind,
            candidate_fingerprint=candidate_fingerprint,
            user_confirmation=user_confirmation,
            agent_decision=agent_decision,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def report_verification(
        self,
        work_item_id: str,
        receipt: Mapping[str, Any],
        *,
        expected_version: int,
        execution_area: str,
    ) -> dict[str, Any]:
        return self.coordinator.report_verification(
            work_item_id,
            receipt,
            expected_version=expected_version,
            execution_area=execution_area,
        )

    @_adapter_use_case
    def assess_verification(
        self,
        work_item_id: str,
        receipt_id: str,
        code_change_assessment: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.assess_verification(
            work_item_id,
            receipt_id,
            code_change_assessment,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def present_actual_result(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        return self.coordinator.present_actual_result(
            work_item_id,
            value,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def plan_delivery_activity(
        self,
        work_item_id: str,
        plan: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.plan_delivery_activity(
            work_item_id,
            plan,
            expected_version=expected_version,
        )

    @_adapter_use_case
    def authorize_delivery_activity(
        self,
        activity_id: str,
        *,
        expected_activity_version: int,
        expected_work_item_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.authorize_delivery_activity(
            activity_id,
            expected_activity_version=expected_activity_version,
            expected_work_item_version=expected_work_item_version,
        )

    @_adapter_use_case
    def record_delivery_activity_receipt(
        self,
        activity_id: str,
        receipt: Mapping[str, Any],
        *,
        expected_activity_version: int,
    ) -> dict[str, Any]:
        return self.coordinator.record_delivery_activity_receipt(
            activity_id,
            receipt,
            expected_activity_version=expected_activity_version,
        )

    @_adapter_use_case
    def cancel_planned_delivery_activity(
        self,
        activity_id: str,
        *,
        expected_activity_version: int,
        canceled_by: str,
        reason: str,
    ) -> dict[str, Any]:
        return self.coordinator.cancel_planned_delivery_activity(
            activity_id,
            expected_activity_version=expected_activity_version,
            canceled_by=canceled_by,
            reason=reason,
        )

    def delivery_activities(
        self,
        *,
        work_item_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return self.read_model.delivery_activities(work_item_id=work_item_id)
        except ValueError as error:
            raise HostAdapterError(
                getattr(error, "code", "delivery_activity_query_failed"),
                str(error),
                details=getattr(error, "details", None),
            ) from error

    def delivery_activity(self, activity_id: str) -> dict[str, Any]:
        try:
            return self.read_model.delivery_activity(activity_id)
        except ValueError as error:
            raise HostAdapterError(
                getattr(error, "code", "delivery_activity_query_failed"),
                str(error),
                details=getattr(error, "details", None),
            ) from error

__all__ = [
    "HOST_ADAPTER_SCHEMA",
    "HostAdapterError",
    "LocalHostAdapter",
]
