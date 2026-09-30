"""One read model for CLI, UI, and local host adapters."""

from __future__ import annotations

from strixnova.work_item_repositories import repository_responsibility_view, previous_integrations
from strixnova.project_content_snapshot import capture_repository_content, compose_content_snapshot, verification_input_paths, continued_verification_paths, verification_snapshot_matches

from collections import Counter
import base64
import hashlib
import json
from os.path import normcase
from datetime import date
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from strixnova import __version__
from strixnova.current_action import current_action_for, direction_revision_action_for
from strixnova.test_case_evidence import receipts_with_freshness
from strixnova.delivery_activity import DeliveryActivityAuthority
from strixnova.engineering_change_planning import implementation_reporting_coverage
from strixnova.execution_context import execution_context
from strixnova.project_authority_progress import current_project_authority_decisions, planned_upstream_authority_kinds
from strixnova.engineering_trace_projection import EngineeringTraceProjection
from strixnova.project_authority_consistency import (
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
    direction_context_invalidation_issues,
    direction_context_requires_validation,
    unadopted_project_direction_context,
)
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.project_engineering_assurance import (
    DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH,
    ProjectEngineeringAssurance,
    ProjectEngineeringAssuranceError,
)
from strixnova.verification_runner import (
    VerificationRunner,
    VerificationRunnerError,
)
from strixnova.work_item_relations import (
    build_work_item_relation_views,
    empty_work_item_relation_view,
)
from strixnova.workflow_authority import AUTHORITY_DATABASE_NAME, TERMINAL_STATES, WorkflowAuthority, WorkflowAuthorityError
from strixnova.work_item_history import WorkItemHistory, HistoryQueryError
from strixnova.follow_ups import ref_key
from strixnova.project_context import (
    ProjectContextError,
    ProjectContext,
    ProjectContextResolver,
    project_context_contract,
)
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.review_context_projection import ReviewContextError, ReviewContextProjection, review_context_contract


READ_MODEL_SCHEMA = "strixnova.work-item-read-model.v1"
ISOLATED_INSTALL_ACCEPTANCE_COVERAGE = "project.isolated_install_acceptance"


class ProjectIntegrationReferenceError(ProjectEngineeringBaselineError):
    """The configured adopted Git state is missing or cannot be resolved."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__([message])
        self.code = code


class ProjectContextQueryError(ValueError):
    """Stable errors for bootstrap reads that do not construct an Authority."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class WorkItemReadModel:
    """Project WorkflowAuthority and Git facts without owning new state."""

    @staticmethod
    def context_contract(action: str) -> dict[str, Any]:
        try:
            if action == "review":
                return review_context_contract()
            return project_context_contract(action)
        except ProjectContextError as error:
            raise ProjectContextQueryError(error.code, str(error), details=error.details) from error

    @staticmethod
    def query_project_context(
        project_dir: str | Path, action: str, request: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Read supplied bootstrap inputs without constructing project state."""

        try:
            if action == "review":
                return ReviewContextProjection(project_dir).read(request)
            resolver = ProjectContextResolver(project_dir)
            if action == "inspect":
                return resolver.resolve(request).view()
            if action == "read":
                return resolver.read(request)
            raise ProjectContextError("project_context_action_invalid", "上下文查询种类无效")
        except (ProjectContextError, GitProjectReaderError, ReviewContextError) as error:
            raise ProjectContextQueryError(error.code, str(error), details=error.details) from error

    @staticmethod
    def prepare_project_context(project_dir: str | Path, bindings: Mapping[str, Any] | None = None) -> ProjectContext | None:
        try:
            return ProjectContextResolver(project_dir).configured(bindings=bindings, use_execution_bindings=False)
        except (ProjectContextError, GitProjectReaderError) as error:
            raise ProjectContextQueryError(error.code, str(error), details=error.details) from error

    def __init__(
        self, project_dir: str | Path, *, project_bindings: Mapping[str, Any] | None = None,
        shared_context: ProjectContext | None = None,
    ) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self.project_bindings = deepcopy(project_bindings)
        context = shared_context
        management = self.project
        if context is None and self.project_bindings is not None:
            management = ProjectContextResolver(self.project).management_binding(self.project_bindings)
            try:
                context = self.prepare_project_context(self.project, self.project_bindings)
            except ProjectContextQueryError:
                context = None
        self.management_project = context.management_root if context is not None else management
        self.project_context = context
        self._authority: WorkflowAuthority | None = None
        # Cache only a complete immutable scope, including repository bindings
        # and locator paths. Resolve moving refs before lookup so subsequent
        # reads still observe a branch advance or a different local binding.
        self._baseline_readers_by_scope: dict[
            str, ProjectEngineeringBaseline
        ] = {}
        self._baselines_by_scope: dict[str, dict[str, Any] | None] = {}
        self._consistency_by_scope: dict[
            str, ProjectAuthorityConsistency
        ] = {}
        self._authorities_by_scope: dict[str, dict[str, Any]] = {}

    @property
    def authority(self) -> WorkflowAuthority:
        if self._authority is None:
            self._authority = WorkflowAuthority(self.management_project, project_id=self.project_context.project_id if self.project_context is not None else (self.project_bindings or {}).get("project_id"))
        return self._authority

    def _project_baseline(self, observed_ref: str | None = None) -> ProjectEngineeringBaseline:
        try:
            context = ProjectContextResolver(self.project).configured(
                bindings=self.project_bindings, observed_ref=observed_ref,
            )
            if context is None:
                return ProjectEngineeringBaseline(self.project, observed_ref=observed_ref)
            return ProjectEngineeringBaseline(self.project, shared_context=context)
        except (ProjectContextError, GitProjectReaderError) as error:
            raise ProjectIntegrationReferenceError(error.code, str(error)) from error

    def revision(self) -> dict[str, Any]:
        if not self.management_project.exists():
            return {"schema_version": "strixnova.authority-revision.v1", "revision": 0, "updated_at": None}
        revision = self.authority.revision()
        return {
            "schema_version": "strixnova.read-model-revision.v1",
            **revision,
        }

    def history_query(self, **query: Any) -> dict[str, Any]:
        try:
            roots = {entry.repository_id: entry.checkout_path for entry in self.project_context.repositories if entry.checkout_path is not None and entry.availability == "available"} if self.project_context is not None else {}
            return WorkItemHistory(self.management_project, repository_roots=roots).query(**query)
        except WorkflowAuthorityError as error:
            raise HistoryQueryError(error.code, str(error)) from error

    def overview(self, focus_work_item_id: str | None = None) -> dict[str, Any]:
        work_items = self._project_work_items(self.authority.list())
        focus = self._focus(work_items, focus_work_item_id)
        counts = Counter(item["status"] for item in work_items)
        awaiting_user = sum(
            1
            for item in work_items
            if isinstance(item.get("current_action"), Mapping)
            and item["current_action"].get("actor") == "user"
        )
        active = sum(
            1 for item in work_items if item["status"] not in TERMINAL_STATES
        )
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "overview",
            "revision": self.revision(),
            "project": self._project_summary(focus),
            "summary": {
                "total": len(work_items),
                "active": active,
                "awaiting_user": awaiting_user,
                "blocked": counts["integration_conflict"],
                "completed": counts["completed"],
                "cancelled": counts["cancelled"],
                "by_status": dict(sorted(counts.items())),
            },
            "focus": (
                self._work_item_summary(focus)
                if focus
                else None
            ),
            "attention": [
                self._work_item_summary(item)
                for item in work_items
                if item["status"] not in TERMINAL_STATES
            ],
            "product": {
                "name": "Strixnova",
                "version": __version__,
                "authority": "local_workflow_authority",
                "remote_git_in_scope": False,
            },
        }

    def work_items(self) -> dict[str, Any]:
        work_items = self._project_work_items(self.authority.list()) if self.management_project.exists() else []
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "work_items",
            "revision": self.revision(),
            "work_items": [
                self._work_item_summary(item)
                for item in work_items
            ],
        }

    def work_item(self, work_item_id: str) -> dict[str, Any]:
        focused = self.focused_work_item(work_item_id)
        item = focused["work_item"]
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "work_item",
            "revision": self.revision(),
            "work_item": item,
            "git_status": self._git_status(item),
            "history": self.authority.history(work_item_id),
            "repository_deliveries": repository_responsibility_view(item),
            "long_lived_engineering": self._long_lived_engineering(item),
            "delivery_activities": self.delivery_activities(
                work_item_id=work_item_id
            ),
        }

    def focused_work_item(self, work_item_id: str) -> dict[str, Any]:
        """Return current item facts without resolving optional project state."""

        item = self._project_work_item(self.authority.get(work_item_id))
        projected = deepcopy(item)
        projected["relations"] = self.work_item_relations(work_item_id)
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "focused_work_item",
            "revision": self.revision(),
            "work_item": projected,
        }

    def execution_basis_commit(self, current: Mapping[str, Any]) -> str | None:
        commit = self._configured_integration_ref()
        if commit is not None:
            return commit
        reference = current.get("data", {}).get("engineering", {}).get("plan", {}).get("investigation_ref")
        if isinstance(reference, str) and reference and reference != "working_tree":
            return self._project_baseline(reference).configuration_commit
        return None

    def review_subject(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return ProjectAuthorityConsistency.review_subject_for(self.project, current, project_context=self.project_context, bindings=self.project_bindings)

    def current_review_subject(self, work_item_id: str, *, expected_version: int) -> dict[str, Any]:
        current = self.authority.get(work_item_id)
        if current["version"] != expected_version:
            raise ProjectContextQueryError("record_read_source_changed", "事项版本已变化，请重新读取审阅对象")
        return self.review_subject(current)

    def execution_context(self, current: Mapping[str, Any], *, slice_id: str | None = None, at_commit: str | None = None) -> dict[str, Any]:
        context = execution_context(current, slice_id=slice_id)
        commit = at_commit or self.execution_basis_commit(current)
        required_kinds = planned_upstream_authority_kinds(current, current_progress_only=False)
        decisions = current_project_authority_decisions(current) if required_kinds else []
        context["authority_changes"] = [
            {"authority_kind": kind, "decision_recorded": any(row["authority_kind"] == kind for row in decisions)}
            for kind in required_kinds
        ]
        if required_kinds and len(decisions) == len(required_kinds):
            resolver = ProjectContextResolver(self.project)
            with resolver.operation(self.project_bindings):
                project_context = resolver.configured(bindings=self.project_bindings)
                data = current.get("data") or {}
                areas = data.get("repository_deliveries") or [{"repository_id": data.get("selected_repository_id"), "git": data.get("git") or {}}]
                with resolver.execution_readers(project_context, areas):
                    checker = ProjectAuthorityConsistency(self.project, shared_baseline=self._project_baseline(None))
                    context["project_rules"] = checker.confirmed_execution_materials([row["operation"] for row in context["resolved_operations"]], decisions)
            context["source"]["project_configuration_commit"] = None
            return context
        checker = self._adopted_consistency(commit, required=False) if commit is not None else None
        if checker is None:
            context["project_rules"] = {
                "sources": {}, "architecture": None, "domain_facts": None,
                "product_guardrails": None, "engineering_policy": None,
                "gaps": [{"code": "execution_rule_basis_unavailable", "message": "尚无可读取的已采用项目规则依据；保留当前方案与方向材料"}],
                "semantic_content_machine_proven": False,
            }
        else:
            context["project_rules"] = checker.execution_materials([row["operation"] for row in context["resolved_operations"]])
            context["project_rules"]["basis_kind"] = "integrated_authorities"
        context["source"]["project_configuration_commit"] = commit
        return context

    def execution_slice(self, current: Mapping[str, Any], slice_id: str, *, at_commit: str | None = None) -> dict[str, Any]:
        context = self.execution_context(current, slice_id=slice_id, at_commit=at_commit)
        return {**context["slice"], "resolved_operations": context["resolved_operations"], "execution_context": context}

    def work_item_relations(
        self,
        work_item_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        """Return relations only for one explicitly focused WorkItem."""

        self.authority.get(work_item_id)
        return self._relation_view_for(work_item_id)

    def repository_deliveries(self, work_item_id: str) -> dict[str, Any]:
        return repository_responsibility_view(self.authority.get(work_item_id))

    def follow_ups(self, *, limit: int = 25, cursor: str | None = None, include_closed: bool = False) -> dict[str, Any]:
        """Read explicit promises in bounded pages, without advancing any action."""
        if type(limit) is not int or not 1 <= limit <= 100 or type(include_closed) is not bool:
            raise WorkflowAuthorityError("follow_up_query_invalid", "跟进查询 limit 必须为 1–100，include_closed 必须为布尔值")
        snapshot = self.authority.follow_up_snapshot()
        today, offset = date.today().isoformat(), 0
        binding = {"project": hashlib.sha256(normcase(str(self.project)).encode("utf-8")).hexdigest(), "revision": snapshot["revision"], "include_closed": include_closed, "limit": limit, "date": today}
        if cursor is not None:
            try:
                if not isinstance(cursor, str) or len(cursor) > 2048:
                    raise ValueError
                value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
                if set(value) != {*binding, "offset"} or type(value["offset"]) is not int or value["offset"] < 0:
                    raise ValueError
                if {key: value[key] for key in binding} != binding:
                    raise WorkflowAuthorityError("follow_up_cursor_stale", "跟进记录、日期或筛选已变化，请重新查询")
                offset = value["offset"]
            except (ValueError, TypeError, KeyError, UnicodeError) as error:
                if isinstance(error, WorkflowAuthorityError):
                    raise
                raise WorkflowAuthorityError("follow_up_query_invalid", "跟进续页引用无效") from error
        items = []
        for original in snapshot["items"]:
            if not include_closed and original["state"] != "open":
                continue
            item = deepcopy(original)
            due = item["origin"]["due_on"]
            item["date_attention"] = "due" if item["state"] == "open" and due and due <= today else "scheduled" if item["state"] == "open" and due else "not_scheduled"
            item["condition_requires_agent_review"] = bool(item["state"] == "open" and item["origin"]["review_condition"])
            item["related_work_items"] = [deepcopy(assignment) for assignment in snapshot["assignments"] if ref_key(assignment["follow_up_ref"]) == ref_key(item["follow_up_ref"])]
            items.append(item)
        items.sort(key=lambda item: (item["date_attention"] != "due", item["origin"]["due_on"] or "9999-12-31", ref_key(item["follow_up_ref"])))
        if offset > len(items):
            raise WorkflowAuthorityError("follow_up_query_invalid", "跟进续页位置越界")
        next_offset = offset + limit
        next_cursor = base64.urlsafe_b64encode(json.dumps({**binding, "offset": next_offset}, sort_keys=True).encode()).decode() if next_offset < len(items) else None
        return {"schema_version": "strixnova.follow-up-view.v1", "revision": snapshot["revision"], "as_of_local_date": today, "total": len(items), "items": items[offset:next_offset], "next_cursor": next_cursor, "coverage": "explicit_accepted_records_only", "historical_obligations_inferred": False, "semantic_content_machine_proven": False}

    def decisions(self, work_item_id: str) -> dict[str, Any]:
        item = self._project_work_item(self.authority.get(work_item_id))
        engineering = item["data"]["engineering"]
        assessment = engineering.get("assessment")
        assessment = assessment if isinstance(assessment, Mapping) else {}
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "decisions",
            "revision": self.revision(),
            "work_item": self._work_item_summary(item),
            "direction": deepcopy(item["data"].get("direction")),
            "direction_confirmation": deepcopy(
                item["data"].get("direction_confirmation")
            ),
            "engineering_assessment": {
                field: deepcopy(assessment.get(field) or [])
                for field in (
                    "alternatives_and_tradeoffs",
                    "design_decisions",
                    "adr_plans",
                    "unknowns_and_limitations",
                    "method_applications",
                )
            },
            "engineering_plan": deepcopy(engineering.get("plan")),
            "engineering_method_confirmation": self._method_confirmation(item),
            "plan_confirmation": deepcopy(
                engineering.get("plan_confirmation")
            ),
            "long_lived_refs": deepcopy(
                (item["data"].get("actual_result") or {}).get(
                    "long_lived_refs"
                )
                or []
            ),
            "long_lived_engineering": self._long_lived_engineering(item),
        }

    def impact(self, work_item_id: str) -> dict[str, Any]:
        item = self._project_work_item(self.authority.get(work_item_id))
        assessment = item["data"]["engineering"].get("assessment")
        assessment = assessment if isinstance(assessment, Mapping) else {}
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "impact",
            "revision": self.revision(),
            "work_item": self._work_item_summary(item),
            "impact_scope": deepcopy(assessment.get("impact_scope") or {}),
            "risk_assessments": deepcopy(
                assessment.get("risk_assessments") or []
            ),
            "operations": deepcopy(assessment.get("operations") or []),
            "git_status": self._git_status(item),
            "management_trace": self._management_trace(item),
        }

    def verification(self, work_item_id: str) -> dict[str, Any]:
        item = self._project_work_item(self.authority.get(work_item_id))
        commands, coverage = self._verification_state(item)
        git = item["data"].get("git") or {}
        return {
            "schema_version": READ_MODEL_SCHEMA,
            "view": "verification",
            "revision": self.revision(),
            "work_item": self._work_item_summary(item),
            "commands": commands,
            "receipts": deepcopy(item["data"].get("verifications") or []),
            "coverage": coverage,
            "behavior_examples": deepcopy((item["data"].get("engineering", {}).get("plan") or {}).get("behavior_examples")),
            "behavior_status": (
                "planned" if (item["data"].get("engineering", {}).get("plan") or {}).get("behavior_examples")
                else "not_applicable" if "behavior_examples" in (item["data"].get("engineering", {}).get("plan") or {})
                else "recorded_inconsistent" if item["data"].get("engineering", {}).get("plan") else "not_planned"
            ),
            "actual_result": deepcopy(item["data"].get("actual_result")),
            "actual_result_confirmation": deepcopy(
                item["data"].get("actual_result_confirmation")
            ),
            "delivery": {
                "result_commits": list(git.get("result_commits") or []),
                "integration": deepcopy(git.get("integration")),
                "cleanup": deepcopy(git.get("cleanup")),
                "external_activities": DeliveryActivityAuthority(
                    self.management_project
                ).list(work_item_id=work_item_id),
            },
        }

    def authority_adoption(
        self,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Project deterministic authority metadata required before commits."""

        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        stored = data.get("authority_adoption") if isinstance(data, Mapping) else None
        stored_ready = bool(
            isinstance(stored, Mapping)
            and stored.get("schema_version") == "strixnova.authority-adoption.v1"
            and stored.get("ready_for_atomic_commits") is True
            and stored.get("accepted_candidate_snapshot_verified") is True
            and not list(stored.get("blocking_issues") or [])
        )
        git = data.get("git") if isinstance(data, Mapping) else None
        worktree_path = (
            str(git.get("worktree_path") or "").strip()
            if isinstance(git, Mapping)
            else ""
        )
        if not worktree_path:
            raise ProjectAuthorityConsistencyError(
                ["当前事项没有可读取的隔离实施工作区"]
            )
        engineering = data.get("engineering")
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
        actual_result = data.get("actual_result")
        confirmation = data.get("actual_result_confirmation")
        confirmed_at = (
            str(confirmation.get("confirmed_at") or "")
            if isinstance(confirmation, Mapping)
            else ""
        )
        resolver = ProjectContextResolver(self.project)
        with resolver.operation(self.project_bindings):
            context = self.prepare_project_context(self.project, self.project_bindings)
            with resolver.execution_readers(context, data.get("repository_deliveries") or []):
                return ProjectAuthorityConsistency(
                    worktree_path
                ).authority_adoption_record(
                    actual_result if isinstance(actual_result, Mapping) else {},
                    investigation_ref=investigation_ref,
                    actual_result_confirmed=(
                        isinstance(confirmation, Mapping)
                        and confirmation.get("accepted") is True
                    ),
                    confirmed_on=confirmed_at[:10] or None,
                    mechanical_adoption_applied=stored_ready,
                )

    def delivery_activities(
        self,
        *,
        work_item_id: str | None = None,
    ) -> dict[str, Any]:
        authority = DeliveryActivityAuthority(self.management_project)
        activities = authority.list(work_item_id=work_item_id)
        counts = Counter(item["state"] for item in activities)
        return {
            "schema_version": "strixnova.delivery-activity-read-model.v1",
            "view": "delivery_activities",
            "work_item_id": work_item_id,
            "capabilities": authority.capabilities(),
            "summary": {
                "total": len(activities),
                "by_state": dict(sorted(counts.items())),
                "external_execution_performed_by_strixnova": False,
            },
            "activities": activities,
        }

    def delivery_activity(self, activity_id: str) -> dict[str, Any]:
        authority = DeliveryActivityAuthority(self.management_project)
        return {
            "schema_version": "strixnova.delivery-activity-read-model.v1",
            "view": "delivery_activity",
            "capabilities": authority.capabilities(),
            "activity": authority.get(activity_id),
            "history": authority.history(activity_id),
        }

    def project_status(
        self,
        *,
        at_commit: str | None = None,
        working_tree: bool = False,
    ) -> dict[str, Any]:
        """Separate target, implementation, evidence, and external activity facts."""

        if working_tree and at_commit is not None:
            raise ProjectIntegrationReferenceError(
                "project_status_scope_conflict",
                "工作树候选检查不能同时指定不可变提交",
            )
        if working_tree:
            try:
                consistency = ProjectAuthorityConsistency(self.project, shared_baseline=self._project_baseline())
                integration_ref = self._configured_integration_ref()
                adopted_authorities = (
                    self._adopted_authorities(
                        integration_ref,
                        required=False,
                    )
                    if integration_ref is not None
                    else None
                )
                if adopted_authorities is None:
                    authorities = consistency.load_working_tree_candidate(None)
                    assurance_consistency = consistency
                else:
                    authorities = consistency.load_working_tree_candidate(
                        adopted_authorities
                    )
                    assurance_consistency = self._adopted_consistency(
                        integration_ref,
                        required=True,
                    )
            except ProjectAuthorityConsistencyError as error:
                raise ProjectIntegrationReferenceError(
                    "working_tree_authority_candidate_invalid",
                    "当前工作树长期权威候选结构或引用无效：" + str(error),
                ) from error
            status = self._project_status_from_authorities(
                authorities,
                consistency=assurance_consistency,
            )
            status["authority_scope"] = "working_tree_candidate"
            status["candidate_only"] = True
            status["candidate_base_observed_commit"] = authorities.get(
                "candidate_base_observed_commit"
            )
            status["changed_authority_kinds"] = list(
                authorities.get("changed_authority_kinds") or []
            )
            status["candidate_baseline_changed"] = bool(
                authorities.get("candidate_baseline_changed")
            )
            return status
        if at_commit is None and self._configured_integration_ref() is None:
            return self._unadopted_project_status()
        authorities = self._adopted_authorities(at_commit, required=False)
        if authorities is None:
            return self._unadopted_project_status()
        status = self._project_status_from_authorities(authorities)
        status["authority_scope"] = "adopted_integration_commit"
        status["candidate_only"] = False
        return status

    def project_engineering_governance(
        self,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any] | None:
        """Return compact engineering-policy adoption facts."""

        authorities = self._adopted_authorities(at_commit, required=False)
        if authorities is None:
            return None
        baseline = authorities["baseline"]
        policy = authorities["engineering_policy"]
        return {
            "schema_version": "strixnova.project-engineering-governance.v1",
            "baseline_id": baseline["baseline_id"],
            "manifest_path": baseline.get("_manifest_path"),
            "policy_id": policy["policy_id"],
            "policy_revision_id": policy["revision"]["revision_id"],
            "observed_commit": authorities["observed_commit"],
            "engineering_methods": [
                {
                    **deepcopy(adoption),
                    "policy_ref": (
                        "engineering-policy:method:"
                        + str(adoption["method_id"])
                    ),
                }
                for adoption in policy["method_adoptions"]
            ],
        }

    def project_direction_context(
        self,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        """Return all current product capabilities and guardrails without ranking."""

        if at_commit is None and self._configured_integration_ref() is None:
            return unadopted_project_direction_context()
        consistency = self._adopted_consistency(at_commit, required=False)
        if consistency is None:
            return unadopted_project_direction_context()
        return consistency.direction_context()

    def project_engineering_assurance(
        self,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the project assurance matrix when the artifact exists."""

        consistency = self._adopted_consistency(at_commit, required=False)
        if consistency is None:
            return None
        consistency.load()
        assurance = ProjectEngineeringAssurance(
            consistency.project,
            shared_consistency=consistency,
        )
        if not assurance.reader.exists(DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH):
            return None
        return assurance.matrix()

    def project_domain_catalog(
        self,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any] | None:
        """Return routing metadata only; Fact bodies remain on-demand."""

        consistency = self._adopted_consistency(
            at_commit,
            required=False,
        )
        if consistency is None:
            return None
        catalog = consistency.domain_routing_catalog()
        for collection in catalog["root_collections"]:
            collection["record_ref"] = (
                "project.domain.collection:"
                + str(collection["collection_id"])
                + ":ROOT:"
                + str(collection["path"])
            )
        return catalog

    def project_domain_collection(
        self,
        collection_id: str,
        *,
        parent_collection_id: str | None = None,
        collection_path: str | None = None,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        consistency = self._adopted_consistency(
            at_commit,
            required=True,
        )
        assert consistency is not None
        catalog = consistency.domain_collection_catalog(
            collection_id,
            parent_collection_id=parent_collection_id,
            collection_path=collection_path,
        )
        selected = catalog["collection"]
        for child in catalog["child_collections"]:
            child["record_ref"] = (
                "project.domain.collection:"
                + str(child["collection_id"])
                + ":"
                + str(selected["collection_id"])
                + ":"
                + str(child["path"])
            )
        for source in catalog["sources"]:
            source["record_ref"] = (
                "project.domain.source:"
                + str(source["source_id"])
                + ":"
                + str(selected["path"])
            )
        return catalog

    def project_domain_source(
        self,
        source_id: str,
        *,
        collection_path: str | None = None,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        consistency = self._adopted_consistency(
            at_commit,
            required=True,
        )
        assert consistency is not None
        catalog = consistency.domain_source_catalog(
            source_id,
            collection_path=collection_path,
        )
        selected = catalog["source"]
        for fact in catalog["facts"]:
            fact["record_ref"] = (
                "project.domain.fact:"
                + str(fact["fact_id"])
                + ":"
                + str(selected["source_id"])
                + ":"
                + str(selected["collection_id"])
                + ":"
                + str(selected["collection_path"])
                + ":"
                + str(selected["path"])
            )
        return catalog

    def project_domain_fact(
        self,
        fact_id: str,
        *,
        source_id: str | None = None,
        collection_id: str | None = None,
        collection_path: str | None = None,
        source_path: str | None = None,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        """Load exactly one canonical Fact body after catalog routing."""

        consistency = self._adopted_consistency(
            at_commit,
            required=True,
        )
        assert consistency is not None
        return consistency.domain_fact_body(
            fact_id,
            source_id=source_id,
            collection_id=collection_id,
            collection_path=collection_path,
            source_path=source_path,
        )

    def project_domain_closure(
        self,
        fact_ids: list[str],
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        consistency = self._adopted_consistency(
            at_commit,
            required=True,
        )
        assert consistency is not None
        return consistency.domain_required_closure(fact_ids)

    def project_architecture(
        self,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        authorities = self._adopted_authorities(at_commit, required=True)
        assert authorities is not None
        return deepcopy(authorities["target_architecture"])

    def project_domain_alignment(
        self,
        *,
        at_commit: str | None = None,
    ) -> dict[str, Any] | None:
        authorities = self._adopted_authorities(at_commit, required=True)
        assert authorities is not None
        return deepcopy(authorities["implementation_alignment"])

    def engineering_trace_for_work_item(
        self,
        work_item_id: str,
        *,
        mode: str = "current",
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        with ProjectContextResolver(self.project).operation(self.project_bindings):
            return self._trace_projection().for_work_item(work_item_id, mode=mode, at_commit=at_commit)

    def engineering_trace_for_fact(
        self,
        fact_id: str,
        *,
        mode: str = "current",
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        with ProjectContextResolver(self.project).operation(self.project_bindings):
            return self._trace_projection().for_fact(fact_id, mode=mode, at_commit=at_commit)

    def engineering_trace_for_artifact(
        self,
        artifact_id: str,
        *,
        mode: str = "current",
        at_commit: str | None = None,
    ) -> dict[str, Any]:
        with ProjectContextResolver(self.project).operation(self.project_bindings):
            return self._trace_projection().for_artifact(artifact_id, mode=mode, at_commit=at_commit)

    def _trace_projection(self) -> EngineeringTraceProjection:
        return EngineeringTraceProjection(self.project, authority=self.authority, management_dir=self.management_project)

    def _project_summary(
        self,
        focus: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        reader = self._integrated_baseline_reader(focus)
        if reader is None:
            return {
                "name": self.project.name,
                "root": str(self.project),
                "engineering_baseline": None,
            }
        baseline = reader.load(required=False)
        if baseline is None:
            return {
                "name": self.project.name,
                "root": str(self.project),
                "engineering_baseline": None,
            }
        project = baseline["project"]
        consistency = ProjectAuthorityConsistency(
            self.project,
            observed_ref=reader.observed_commit,
        )
        authorities = consistency.load()
        product = authorities["product_definition"]
        return {
            "name": self.project.name,
            "root": str(self.project),
            "engineering_baseline": {
                "baseline_id": baseline["baseline_id"],
                "project_id": project["project_id"],
                "title": project["title"],
                "goal": product["purpose"],
                "current_architecture_stage_id": baseline[
                    "current_architecture_stage_id"
                ],
                "authority_statuses": {
                    kind: deepcopy(reference["status"])
                    for kind, reference in baseline["authority_refs"].items()
                },
                "review_state": deepcopy(baseline["review_state"]),
                "manifest_path": baseline.get("_manifest_path"),
                "status_view": self._project_status_from_authorities(
                    authorities,
                    consistency=consistency,
                ),
            },
        }

    def _status_records(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        authority_path = self.management_project / ".strixnova" / AUTHORITY_DATABASE_NAME
        items = self.authority.list() if authority_path.exists() or authority_path.is_symlink() else []
        activities = DeliveryActivityAuthority(self.management_project).list() if self.management_project.is_dir() else []
        return items, activities

    def _project_status_from_authorities(
        self,
        authorities: Mapping[str, Any],
        *,
        consistency: ProjectAuthorityConsistency | None = None,
    ) -> dict[str, Any]:
        baseline = authorities["baseline"]
        product = authorities["product_definition"]
        domain = authorities["domain_catalog"]
        architecture = authorities["target_architecture"]
        alignment = authorities["implementation_alignment"]
        work_items, activities = self._status_records()

        fact_statuses = Counter(str(item["status"]) for item in domain["facts"])
        responsibility_statuses = Counter(
            str(item["status"])
            for item in alignment["target_responsibilities"]
        )
        implementation_statuses = Counter(
            str(item["implementation_status"])
            for item in alignment["domain_fact_implementation"]
        )
        verification_records: list[dict[str, Any]] = []
        install_records: list[dict[str, Any]] = []
        for item in work_items:
            engineering = item["data"].get("engineering")
            plan = (
                engineering.get("plan")
                if isinstance(engineering, Mapping)
                else None
            )
            if not isinstance(plan, Mapping):
                continue
            try:
                commands, coverage = self._verification_state(item)
            except VerificationRunnerError as error:
                verification_records.append(
                    {
                        "work_item_id": item["work_item_id"],
                        "work_item_version": item["version"],
                        "plan_id": plan.get("plan_id"),
                        "verification_status": "recorded_inconsistent",
                        "required_command_ids": [],
                        "latest_receipt_ids": {},
                        "error_code": error.code,
                    }
                )
                continue
            verification_records.append(
                {
                    "work_item_id": item["work_item_id"],
                    "work_item_version": item["version"],
                    "plan_id": plan.get("plan_id"),
                    "verification_status": coverage["verification_status"],
                    "target_verification_status": (
                        (item["data"].get("actual_result") or {}).get("target_verification", {}).get("status")
                        or ("pending" if "verification_targets" in plan else "recorded_inconsistent")
                    ),
                    "required_command_ids": coverage["required_command_ids"],
                    "latest_receipt_ids": coverage["latest_receipt_ids"],
                }
            )
            for command in commands:
                if ISOLATED_INSTALL_ACCEPTANCE_COVERAGE not in command["covers"]:
                    continue
                command_id = command["command_id"]
                install_records.append(
                    {
                        "work_item_id": item["work_item_id"],
                        "command_id": command_id,
                        "receipt_id": coverage["latest_receipt_ids"].get(command_id),
                        "result": coverage["results"].get(command_id),
                        "retest_required": command_id
                        in coverage["retest_required_command_ids"],
                    }
                )
        verification_statuses = Counter(
            item["verification_status"] for item in verification_records
        )
        if not install_records:
            install_status = "not_recorded"
        elif any(
            item["result"] is None or item["retest_required"]
            for item in install_records
        ):
            install_status = "pending"
        elif all(item["result"] == "passed" for item in install_records):
            install_status = "passed"
        else:
            install_status = "completed_with_issues"

        construction_counts = Counter(item["status"] for item in work_items)
        delivery_release = self._activity_status(
            activities,
            kinds={"delivery", "release"},
        )
        deployment = self._activity_status(
            activities,
            kinds={"deployment", "rollback"},
        )
        runtime = self._activity_status(
            activities,
            kinds={"observation", "operations_maintenance"},
        )
        assurance_status = self._engineering_assurance_status(
            authorities,
            consistency=consistency,
        )
        next_actions: list[str] = []
        if authorities["review_state"]["required"]:
            next_actions.append("refresh_implementation_alignment")
        if any(
            status not in {"implemented", "no_independent_implementation"}
            for status in responsibility_statuses
        ):
            next_actions.append("close_target_responsibility_gaps")
        if verification_statuses.get("pending", 0):
            next_actions.append("complete_approved_verification")
        if verification_statuses.get("recorded_inconsistent", 0):
            next_actions.append("repair_verification_record_binding")
        if any(
            section["by_state"].get("failed", 0)
            for section in (delivery_release, deployment, runtime)
        ):
            next_actions.append("record_external_recovery_or_replan")
        if not next_actions:
            next_actions.append("owner_review_required_before_completion_claim")

        return {
            "schema_version": "strixnova.project-status-view.v1",
            "view": "project_status",
            "baseline_id": baseline["baseline_id"],
            "observed_commit": authorities["observed_commit"],
            "observed_repository_id": authorities.get("observed_repository_id"),
            "authority_content_refs": deepcopy(authorities.get("authority_content_refs", {})),
            "baseline_content_ref": deepcopy(authorities.get("baseline_content_ref")),
            "configuration_content_ref": deepcopy(authorities.get("configuration_content_ref")),
            "cross_authority_consistency": {
                "structurally_consistent": authorities[
                    "structurally_consistent"
                ],
                "review_state": deepcopy(authorities["review_state"]),
                "semantic_correctness_machine_proven": False,
            },
            "product_definition": {
                "product_id": product["product_id"],
                "revision_id": product["revision"]["revision_id"],
                "revision_status": product["revision"]["status"],
                "structurally_validated": True,
                "semantic_correctness_machine_proven": False,
            },
            "domain_model": {
                "model_id": domain["model_id"],
                "revision_id": domain["revision"]["revision_id"],
                "revision_status": domain["revision"]["status"],
                "active_fact_count": len(domain["facts"]),
                "tombstone_count": len(domain["retired_facts"]),
                "fact_statuses": dict(sorted(fact_statuses.items())),
                "structurally_validated": True,
                "semantic_correctness_machine_proven": False,
            },
            "target_architecture": {
                "architecture_id": architecture["architecture_id"],
                "revision_id": architecture["revision"]["revision_id"],
                "revision_status": architecture["revision"]["status"],
                "module_count": len(architecture["modules"]),
                "relationship_count": len(architecture["relationships"]),
                "constraint_count": len(architecture["constraints"]),
                "current_stage_id": authorities["current_architecture_stage_id"],
                "structurally_validated": True,
                "semantic_correctness_machine_proven": False,
            },
            "implementation_alignment": {
                "alignment_model_id": alignment["alignment_model_id"],
                "revision_id": alignment["revision"]["revision_id"],
                "revision_status": alignment["revision"]["status"],
                "target_responsibility_statuses": dict(
                    sorted(responsibility_statuses.items())
                ),
                "domain_fact_implementation_statuses": dict(
                    sorted(implementation_statuses.items())
                ),
                "open_deviation_count": len(alignment["deviations"]),
                "review_required": authorities["review_state"]["required"],
                "semantic_content_machine_proven": False,
            },
            "engineering_assurance": assurance_status,
            "construction": {
                "total": len(work_items),
                "by_state": dict(sorted(construction_counts.items())),
            },
            "verification": {
                "work_item_plan_count": len(verification_records),
                "by_status": dict(sorted(verification_statuses.items())),
                "records": verification_records,
                "zero_exit_expanded_to_overall_correctness": False,
            },
            "isolated_install_acceptance": {
                "coverage_id": ISOLATED_INSTALL_ACCEPTANCE_COVERAGE,
                "status": install_status,
                "records": install_records,
                "implied_by_other_tests": False,
            },
            "delivery_release": delivery_release,
            "deployment": deployment,
            "runtime_operations": runtime,
            "next_required_actions": next_actions,
            "overall_usability_machine_decided": False,
        }

    def _engineering_assurance_status(
        self,
        authorities: Mapping[str, Any],
        *,
        consistency: ProjectAuthorityConsistency | None = None,
    ) -> dict[str, Any]:
        observed_commit = authorities.get("observed_commit")
        commit = str(observed_commit) if observed_commit is not None else None
        if consistency is None:
            consistency = self._consistency_by_scope.get(str(authorities.get("_content_scope_key") or ""))
        if consistency is None:
            consistency = (
                self._adopted_consistency(commit, required=True)
                if commit is not None
                else ProjectAuthorityConsistency(self.project)
            )
            assert consistency is not None
        assurance = ProjectEngineeringAssurance(
            consistency.project,
            shared_consistency=consistency,
        )
        if not assurance.reader.exists(DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH):
            return {
                "status": "not_recorded",
                "manifest_path": DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH,
                "semantic_content_machine_proven": False,
                "external_assurance_machine_proven": False,
            }
        try:
            matrix = assurance.matrix()
        except ProjectEngineeringAssuranceError as error:
            return {
                "status": "recorded_inconsistent",
                "manifest_path": DEFAULT_PROJECT_ENGINEERING_ASSURANCE_PATH,
                "issues": deepcopy(error.issues),
                "semantic_content_machine_proven": False,
                "external_assurance_machine_proven": False,
            }
        return {
            "status": "recorded",
            "manifest_path": matrix["manifest_path"],
            "assurance_id": matrix["assurance_id"],
            "assurance_revision_id": matrix["assurance_revision_id"],
            "by_status": deepcopy(matrix["by_status"]),
            "external_assurance": deepcopy(matrix["external_assurance"]),
            "unresolved_items": deepcopy(matrix["unresolved_items"]),
            "semantic_content_machine_proven": False,
            "external_assurance_machine_proven": False,
        }

    @staticmethod
    def _activity_status(
        activities: list[Mapping[str, Any]],
        *,
        kinds: set[str],
    ) -> dict[str, Any]:
        selected = [
            item
            for item in activities
            if item["plan"]["activity_kind"] in kinds
        ]
        counts = Counter(item["state"] for item in selected)
        return {
            "activity_kinds": sorted(kinds),
            "total": len(selected),
            "by_state": dict(sorted(counts.items())),
            "completed_external_receipt_count": sum(
                1
                for item in selected
                if item["state"] == "completed"
                and bool(item["external_receipts"])
            ),
            "strixnova_executes_external_activity": False,
        }

    def _unadopted_project_status(self) -> dict[str, Any]:
        work_items, activities = self._status_records()
        return {
            "schema_version": "strixnova.project-status-view.v1",
            "view": "project_status",
            "authority_scope": "unadopted_project",
            "candidate_only": False,
            "baseline_id": None,
            "observed_commit": None,
            "cross_authority_consistency": {
                "structurally_consistent": False,
                "review_state": {
                    "required": True,
                    "reasons": [
                        "项目尚未由项目负责人决定并采用可解析的长期项目权威；"
                        "讨论、调查和明确不交付仓库文件的 A0 事项仍可继续；"
                        "任何首次仓库修改或交付必须用 create_project 完整建立项目权威。"
                    ],
                    "affected_authority_kinds": [],
                },
                "semantic_correctness_machine_proven": False,
            },
            "product_definition": None,
            "domain_model": None,
            "target_architecture": None,
            "implementation_alignment": None,
            "construction": {
                "total": len(work_items),
                "by_state": dict(
                    sorted(Counter(item["status"] for item in work_items).items())
                ),
            },
            "verification": {
                "work_item_plan_count": 0,
                "by_status": {},
                "records": [],
                "zero_exit_expanded_to_overall_correctness": False,
            },
            "isolated_install_acceptance": {
                "coverage_id": ISOLATED_INSTALL_ACCEPTANCE_COVERAGE,
                "status": "not_recorded",
                "records": [],
                "implied_by_other_tests": False,
            },
            "delivery_release": self._activity_status(
                activities,
                kinds={"delivery", "release"},
            ),
            "deployment": self._activity_status(
                activities,
                kinds={"deployment", "rollback"},
            ),
            "runtime_operations": self._activity_status(
                activities,
                kinds={"observation", "operations_maintenance"},
            ),
            "next_required_actions": [
                "adopt_project_authorities_before_repository_delivery"
            ],
            "overall_usability_machine_decided": False,
        }

    def _long_lived_engineering(
        self,
        item: Mapping[str, Any] | None,
    ) -> dict[str, Any] | None:
        reader = self._integrated_baseline_reader(item)
        if reader is None:
            return None
        baseline = reader.load(required=False)
        if baseline is None:
            return None
        authorities = ProjectAuthorityConsistency(
            self.project,
            shared_baseline=reader,
        ).load()
        catalog = authorities["domain_catalog"]
        architecture = authorities["target_architecture"]
        alignment = authorities["implementation_alignment"]
        policy = authorities["engineering_policy"]
        implementation_counts = Counter(
            item["implementation_status"]
            for item in alignment["domain_fact_implementation"]
        )
        return {
            "baseline_id": baseline["baseline_id"],
            "manifest_path": baseline.get("_manifest_path"),
            "authority_refs": deepcopy(baseline["authority_refs"]),
            "engineering_methods": [
                {
                    "method_id": item["method_id"],
                    "status": item["status"],
                }
                for item in policy["method_adoptions"]
            ],
            "domain_model": {
                "model_id": catalog["model_id"],
                "title": catalog["title"],
                "collection_count": len(catalog["collections"]),
                "source_count": len(catalog["sources"]),
                "fact_count": len(catalog["facts"]),
                "retired_fact_count": len(catalog["retired_facts"]),
                "bodies_included": False,
            },
            "target_architecture": {
                "architecture_id": architecture["architecture_id"],
                "module_count": len(architecture["modules"]),
                "relationship_count": len(architecture["relationships"]),
                "constraint_count": len(architecture["constraints"]),
                "current_stage_id": baseline["current_architecture_stage_id"],
            },
            "implementation_alignment": {
                "alignment_model_id": alignment["alignment_model_id"],
                "behavior_file_count": len(alignment["source_ownership"]),
                "direct_dependency_count": len(alignment["actual_dependencies"]),
                "target_responsibility_count": len(
                    alignment["target_responsibilities"]
                ),
                "domain_fact_statuses": dict(sorted(implementation_counts.items())),
                "deviation_count": len(alignment["deviations"]),
                "semantic_content_machine_proven": False,
            },
            "review_state": deepcopy(authorities["review_state"]),
        }

    @staticmethod
    def _method_confirmation(item: Mapping[str, Any]) -> dict[str, Any]:
        """Expose the existing plan confirmation as the method confirmation seam."""

        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        engineering = (
            data.get("engineering")
            if isinstance(data.get("engineering"), Mapping)
            else {}
        )
        plan = (
            engineering.get("plan")
            if isinstance(engineering.get("plan"), Mapping)
            else {}
        )
        confirmation = (
            engineering.get("plan_confirmation")
            if isinstance(engineering.get("plan_confirmation"), Mapping)
            else None
        )
        applications = list(plan.get("method_applications") or [])
        coding_agent_assessed = bool(applications) and all(
            isinstance(application, Mapping)
            and application.get("decision_source") == "coding_agent_assessment"
            for application in applications
        )
        return {
            "coding_agent_assessed": coding_agent_assessed,
            "machine_validated": bool(applications)
            and all(
                application.get("machine_validated") is True
                if isinstance(application, Mapping)
                else False
                for application in applications
            ),
            "included_in_confirmed_plan": bool(
                applications
                and confirmation is not None
                and confirmation.get("accepted") is True
            ),
            "confirmation_scope": "engineering_plan",
            "explicit_method_name_confirmation": False,
            "applications": deepcopy(applications),
        }

    def _integrated_baseline_reader(
        self,
        item: Mapping[str, Any] | None,
    ) -> ProjectEngineeringBaseline | None:
        """Read adopted Git facts, never provisional files in a work branch."""

        observed_ref: str | None = None
        if isinstance(item, Mapping):
            data = item.get("data")
            data = data if isinstance(data, Mapping) else {}
            git = data.get("git")
            if isinstance(git, Mapping):
                observed_ref = str(git.get("target_ref") or "").strip() or None
            if observed_ref is None:
                engineering = data.get("engineering")
                assessment = (
                    engineering.get("assessment")
                    if isinstance(engineering, Mapping)
                    else None
                )
                if isinstance(assessment, Mapping):
                    value = str(
                        assessment.get("investigation_ref") or ""
                    ).strip()
                    if value and value != "working_tree":
                        observed_ref = value
        if observed_ref is None:
            observed_ref = self._configured_integration_ref()
        if observed_ref is None:
            return None
        return self._project_baseline(observed_ref)

    def adopted_project_commit(self) -> str:
        """Select the configuration carrier's commit for a coherent read batch."""

        reader = self._adopted_baseline_reader(None)
        if reader.configuration_commit is None:
            raise ProjectEngineeringBaselineError(
                ["项目长期事实必须从不可变 Git commit 读取"]
            )
        return reader.configuration_commit

    def _adopted_project_baseline(
        self,
        at_commit: str | None,
        *,
        required: bool,
    ) -> tuple[ProjectEngineeringBaseline, dict[str, Any] | None]:
        reader = self._adopted_baseline_reader(at_commit)
        commit = reader.observed_commit
        if commit is None:
            raise ProjectEngineeringBaselineError(
                ["项目长期事实必须从不可变 Git commit 读取"]
            )
        key = reader.scope_key
        if key not in self._baselines_by_scope:
            self._baselines_by_scope[key] = reader.load(required=required)
        baseline = self._baselines_by_scope[key]
        if baseline is None and required:
            # Preserve ProjectEngineeringBaseline's precise missing-file error.
            baseline = reader.load(required=True)
            self._baselines_by_scope[key] = baseline
        return reader, baseline

    def _adopted_consistency(
        self,
        at_commit: str | None,
        *,
        required: bool,
    ) -> ProjectAuthorityConsistency | None:
        reader, baseline = self._adopted_project_baseline(
            at_commit,
            required=required,
        )
        if baseline is None:
            return None
        commit = reader.observed_commit
        if commit is None:
            raise ProjectEngineeringBaselineError(
                ["项目长期权威必须从不可变 Git commit 读取"]
            )
        key = reader.scope_key
        consistency = self._consistency_by_scope.get(key)
        if consistency is None:
            consistency = ProjectAuthorityConsistency(
                self.project,
                shared_baseline=reader,
            )
            self._consistency_by_scope[key] = consistency
        return consistency

    def _adopted_authorities(
        self,
        at_commit: str | None,
        *,
        required: bool,
    ) -> dict[str, Any] | None:
        consistency = self._adopted_consistency(
            at_commit,
            required=required,
        )
        if consistency is None:
            return None
        commit = consistency.observed_commit
        assert commit is not None
        key = consistency.baseline_reader.scope_key
        if key not in self._authorities_by_scope:
            self._authorities_by_scope[key] = {**consistency.load(), "_content_scope_key": key}
        return deepcopy(self._authorities_by_scope[key])

    def _adopted_baseline_reader(
        self,
        at_commit: str | None,
    ) -> ProjectEngineeringBaseline:
        observed_ref = at_commit or self._configured_integration_ref()
        if not observed_ref:
            raise ProjectIntegrationReferenceError(
                "integration_ref_required",
                "项目没有配置本地集成分支；请在 strixnova-project.yaml 设置 "
                "default_integration_ref",
            )
        reader = self._project_baseline(observed_ref)
        if reader.observed_commit is not None:
            existing = self._baseline_readers_by_scope.get(
                reader.scope_key
            )
            if existing is not None:
                return existing
            self._baseline_readers_by_scope[reader.scope_key] = reader
        return reader

    def _configured_integration_ref(self) -> str | None:
        try:
            context = ProjectContextResolver(self.project).configured(bindings=self.project_bindings)
            if context is None:
                return None
            assert context.configuration is not None
            configuration = context.configuration
        except (ProjectContextError, ProjectEngineeringBaselineError, GitProjectReaderError) as error:
            raise ProjectIntegrationReferenceError(
                "project_configuration_invalid",
                f"strixnova-project.yaml 无效：{error}",
            ) from error
        raw_ref = str(
            configuration.get("default_integration_ref") or ""
        ).strip()
        if not raw_ref:
            return None
        try:
            assert context.configuration_reader is not None
            return context.configuration_reader.resolve_commit(raw_ref)
        except GitProjectReaderError as error:
            raise ProjectIntegrationReferenceError(
                "integration_ref_not_found",
                "strixnova-project.yaml 已配置 default_integration_ref="
                f"{raw_ref!r}，但本地 Git 中不存在该提交引用；"
                "请先确认正确的本地分支或提交已经存在",
            ) from error

    @staticmethod
    def _focus(
        items: list[dict[str, Any]],
        work_item_id: str | None,
    ) -> dict[str, Any] | None:
        if work_item_id:
            for item in items:
                if item["work_item_id"] == work_item_id:
                    return item
        return next(
            (
                item
                for item in items
                if item["status"] not in TERMINAL_STATES
            ),
            items[0] if items else None,
        )

    def _project_work_items(
        self,
        items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Use one current product projection for every public item summary."""

        projected = [deepcopy(item) for item in items]
        for item in projected:
            if item.get("status") not in {"implementing", "exploring", "integration_conflict"}:
                continue
            check_item = deepcopy(item)
            check_item["data"]["verifications"] = self._verification_receipts(check_item)
            item["current_action"] = current_action_for(check_item)
        candidates = [
            item
            for item in projected
            if direction_context_requires_validation(item)
        ]
        if not candidates:
            return projected
        current_context = self.project_direction_context()
        for item in candidates:
            issues = direction_context_invalidation_issues(item, current_context)
            if issues:
                item["current_action"] = direction_revision_action_for(
                    item,
                    issues,
                )
        return projected

    def _project_work_item(
        self,
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        return self._project_work_items([dict(item)])[0]

    def _relation_view_for(
        self,
        work_item_id: str,
    ) -> dict[str, list[dict[str, Any]]]:
        relation_views = build_work_item_relation_views(self.authority.list())
        return deepcopy(
            relation_views.get(work_item_id, empty_work_item_relation_view())
        )

    @staticmethod
    def _work_item_summary(
        item: Mapping[str, Any],
    ) -> dict[str, Any]:
        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        engineering = (
            data.get("engineering")
            if isinstance(data.get("engineering"), Mapping)
            else {}
        )
        plan = (
            engineering.get("plan")
            if isinstance(engineering.get("plan"), Mapping)
            else {}
        )
        return {
            "work_item_id": item["work_item_id"],
            "title": item["title"],
            "status": item["status"],
            "is_terminal": item["status"] in TERMINAL_STATES,
            "version": item["version"],
            "updated_at": item["updated_at"],
            "current_action": deepcopy(item.get("current_action")),
            "assurance_band": plan.get("assurance_band"),
            "blockers": deepcopy(data.get("blockers") or []),
        }

    def _git_status(self, item: Mapping[str, Any]) -> dict[str, Any] | None:
        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        entries = data.get('repository_deliveries') or []
        if entries:
            statuses = []
            for entry in entries:
                projected = {**item, 'data': {'git': entry.get('git') or {}}}
                statuses.append({'repository_id': entry['repository_id'], 'status': self._git_status(projected)})
            states = [entry['status'].get('state') if entry['status'] is not None else 'not_started' for entry in statuses]
            state = 'cleaned' if all(value == 'cleaned' for value in states) else 'partially_integrated' if any(value in {'integrated', 'cleaned'} for value in states) else 'recorded'
            prior = previous_integrations(data)
            if prior and state == 'recorded':
                state = 'partially_integrated'
            return {'state': state, 'repositories': statuses, 'previous_integrations': prior, 'live_workspace_inspected': False}
        value = data.get("git")
        if not isinstance(value, Mapping) or value.get("schema_version") != (
            "strixnova.git-work-area.v1"
        ):
            return None
        if isinstance(value.get("cleanup"), Mapping):
            return {
                "state": "cleaned",
                "work_ref": value.get("work_ref"),
                "target_ref": value.get("target_ref"),
                "recorded_cleanup": deepcopy(value["cleanup"]),
            }
        if isinstance(value.get("integration"), Mapping):
            state = "integrated"
        elif value.get("result_commits"):
            state = "committed"
        else:
            state = "recorded"
        return {
            "state": state,
            "live_workspace_inspected": False,
            "recorded": deepcopy(dict(value)),
        }

    def _verification_receipts(self, item: Mapping[str, Any]) -> list[dict[str, Any]]:
        data = item['data']
        receipts = deepcopy(list(data.get('verifications') or []))
        if item.get('status') not in {'implementing', 'exploring', 'integration_conflict'}:
            return receipts
        plan = data.get('engineering', {}).get('plan') or {}
        scope = {entry['repository_id']: entry for entry in (plan.get('repository_scope') or {}).get('repositories', [])}
        continued = continued_verification_paths(plan, receipts, data.get('implementation_slice_completions') or [])
        areas = {entry['repository_id']: entry.get('git') or {} for entry in data.get('repository_deliveries') or []}
        def reader_for(identifier):
            area = areas.get(identifier) or (data.get('git') or {} if not areas else {})
            selection = scope.get(identifier, {})
            observed = selection.get('investigation_ref') if selection.get('role') == 'read' else (area.get('integration') or {}).get('integrated_commit')
            if observed == 'working_tree':
                observed = None
            root = area.get('repository') if observed or area.get('conflict_resolution') else area.get('worktree_path')
            if root is None and self.project_context is not None and identifier is not None:
                root = self.project_context.repository(identifier).checkout_path
            return GitProjectReader(root or self.project, observed_ref=observed)
        commands = {entry['command_id']: entry for entry in plan.get('verification_commands') or []}
        for index, receipt in enumerate(receipts):
            command = commands.get(receipt.get('command_id')) or {}
            try:
                reader = reader_for(command.get('repository_id'))
                excluded = continued.get(command.get('command_id'), {})
                checked = receipts_with_freshness([receipt], reader.project if reader.observed_commit is None else None, exclude_paths=excluded.get(command.get('repository_id'), ()))[0]
                expected = receipt.get('project_input_snapshot')
                if expected is not None:
                    inputs = []
                    for entry in expected['repositories']:
                        source = reader_for(entry['repository_id'])
                        paths = verification_input_paths(plan, command, entry['repository_id'], source)
                        inputs.append(capture_repository_content(entry['repository_id'], source, sorted(paths), canonical=entry['repository_id'] is not None or item.get('status') != 'exploring'))
                    current = compose_content_snapshot(plan['plan_id'], inputs, dependencies=expected.get('dependencies') or [])
                    if not verification_snapshot_matches(expected, current, excluded) or receipt.get('inputs_changed_during_execution'):
                        checked['_case_input_stale'] = True
                receipts[index] = checked
            except (GitProjectReaderError, ProjectContextError):
                receipt['_case_input_stale'] = True
        return receipts

    def _verification_state(
        self,
        item: Mapping[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        data = item.get("data") if isinstance(item.get("data"), Mapping) else {}
        engineering = (
            data.get("engineering")
            if isinstance(data.get("engineering"), Mapping)
            else {}
        )
        plan = engineering.get("plan")
        if not isinstance(plan, Mapping):
            return [], {
                "schema_version": "strixnova.verification-coverage.v1",
                "verification_status": "pending",
                "required_command_ids": [],
                "latest_receipt_ids": {},
                "results": {},
                "missing_command_ids": [],
                "assessment_missing_command_ids": [],
                "retest_required_command_ids": [],
            }
        commands = deepcopy(list(plan.get("verification_commands") or []))
        receipts = self._verification_receipts(item)
        coverage = VerificationRunner.coverage_status(
            commands,
            receipts,
            work_item_id=str(item["work_item_id"]),
            execution_root=None,
        )
        completions = data.get("implementation_slice_completions")
        coverage = implementation_reporting_coverage(
            plan,
            receipts,
            completions if isinstance(completions, list) else [],
            coverage,
        )
        return commands, coverage

    def _management_trace(self, item: Mapping[str, Any]) -> dict[str, Any]:
        data = item["data"]
        engineering = data["engineering"]
        assessment = engineering.get("assessment")
        assessment = assessment if isinstance(assessment, Mapping) else {}
        plan = engineering.get("plan")
        plan = plan if isinstance(plan, Mapping) else {}
        nodes: list[dict[str, Any]] = [
            {
                "id": "direction",
                "kind": "direction",
                "label": str((data.get("direction") or {}).get("goal") or "方向"),
            }
        ]
        edges: list[dict[str, str]] = []
        direction = data.get("direction")
        direction = direction if isinstance(direction, Mapping) else {}
        direction_fields = (
            ("scope", "requirement_id", "direction.requirement"),
            ("constraints", "constraint_id", "direction.constraint"),
            ("acceptance", "acceptance_id", "direction.acceptance"),
        )
        for field, identifier_field, reference_prefix in direction_fields:
            for direction_item in direction.get(field) or []:
                if not isinstance(direction_item, Mapping):
                    continue
                identifier = str(direction_item.get(identifier_field) or "")
                if not identifier:
                    continue
                fact_ref = f"{reference_prefix}:{identifier}"
                nodes.append(
                    {
                        "id": fact_ref,
                        "kind": reference_prefix.replace(".", "_"),
                        "label": str(
                            direction_item.get("statement") or fact_ref
                        ),
                    }
                )
                edges.append(
                    {
                        "source": "direction",
                        "target": fact_ref,
                        "type": "contains",
                    }
                )
                if field == "acceptance":
                    for requirement_id in (
                        direction_item.get("requirement_refs") or []
                    ):
                        edges.append(
                            {
                                "source": fact_ref,
                                "target": (
                                    "direction.requirement:"
                                    f"{requirement_id}"
                                ),
                                "type": "covers",
                            }
                        )
        for reference, example in plan.get("behavior_examples", {}).items():
            nodes.append({"id": reference, "kind": "behavior_example", "label": example["title"]})
            edges.append({"source": example["parent_acceptance_ref"], "target": reference, "type": "illustrated_by"})
            for basis in example["basis_refs"]:
                edges.append({"source": reference, "target": basis, "type": "expected_from"})
        semantic_fields = (
            "risk_assessments",
            "alternatives_and_tradeoffs",
            "design_decisions",
            "operations",
            "adr_plans",
            "unknowns_and_limitations",
        )
        for field in semantic_fields:
            for index, fact in enumerate(assessment.get(field) or []):
                if not isinstance(fact, Mapping):
                    continue
                fact_ref = f"{field}[{index}]"
                label = (
                    fact.get("statement")
                    or fact.get("option")
                    or fact.get("reason")
                    or fact_ref
                )
                nodes.append(
                    {"id": fact_ref, "kind": field, "label": str(label)}
                )
                if "direction" in list(fact.get("evidence_refs") or []):
                    edges.append(
                        {
                            "source": "direction",
                            "target": fact_ref,
                            "type": "supported_by",
                        }
                    )
                for source in list(fact.get("implements") or []):
                    edges.append(
                        {
                            "source": str(source),
                            "target": fact_ref,
                            "type": "implemented_by",
                        }
                    )
        impact_scope = assessment.get("impact_scope")
        impact_scope = impact_scope if isinstance(impact_scope, Mapping) else {}
        for status in ("affected", "unknown"):
            for index, impact in enumerate(impact_scope.get(status) or []):
                if not isinstance(impact, Mapping):
                    continue
                dimension = str(impact.get("dimension") or "")
                impact_ref = f"impact_scope.{status}[{index}]"
                nodes.append(
                    {
                        "id": impact_ref,
                        "kind": "impact",
                        "label": str(impact.get("reason") or dimension),
                    }
                )
                if "direction" in list(impact.get("evidence_refs") or []):
                    edges.append(
                        {
                            "source": "direction",
                            "target": impact_ref,
                            "type": "supported_by",
                        }
                    )
        for index, dimension in enumerate(impact_scope.get("unaffected") or []):
            nodes.append(
                {
                    "id": f"impact_scope.unaffected[{index}]",
                    "kind": "impact",
                    "label": str(dimension),
                }
            )
        authority_change_set = plan.get("authority_change_set")
        if isinstance(authority_change_set, Mapping):
            nodes.append(
                {
                    "id": "authority_change_set",
                    "kind": "authority_change_set",
                    "label": str(
                        authority_change_set.get("change_set_id")
                        or "长期权威变更集"
                    ),
                }
            )
            for index, change in enumerate(
                authority_change_set.get("changes") or []
            ):
                if not isinstance(change, Mapping):
                    continue
                change_ref = f"authority_change_set.changes[{index}]"
                nodes.append(
                    {
                        "id": change_ref,
                        "kind": "authority_change",
                        "label": str(change.get("summary") or change_ref),
                    }
                )
                edges.append(
                    {
                        "source": "authority_change_set",
                        "target": change_ref,
                        "type": "contains",
                    }
                )
        semantic_review = plan.get("semantic_review")
        if isinstance(semantic_review, Mapping):
            nodes.append(
                {
                    "id": "semantic_review",
                    "kind": "semantic_review",
                    "label": str(
                        semantic_review.get("review_id") or "跨产物语义审查"
                    ),
                }
            )
            for index, finding in enumerate(semantic_review.get("findings") or []):
                if not isinstance(finding, Mapping):
                    continue
                finding_ref = f"semantic_review.findings[{index}]"
                nodes.append(
                    {
                        "id": finding_ref,
                        "kind": "semantic_review_finding",
                        "label": str(finding.get("statement") or finding_ref),
                    }
                )
                edges.append(
                    {
                        "source": "semantic_review",
                        "target": finding_ref,
                        "type": "found",
                    }
                )
        for implementation_slice in plan.get("implementation_slices") or []:
            if not isinstance(implementation_slice, Mapping):
                continue
            slice_id = str(implementation_slice.get("slice_id") or "")
            if not slice_id:
                continue
            slice_ref = f"implementation_slice:{slice_id}"
            nodes.append(
                {
                    "id": slice_ref,
                    "kind": "implementation_slice",
                    "label": str(
                        implementation_slice.get("purpose") or slice_id
                    ),
                }
            )
            for implemented in implementation_slice.get("implements") or []:
                edges.append(
                    {
                        "source": str(implemented),
                        "target": slice_ref,
                        "type": "planned_as",
                    }
                )
            for operation_ref in implementation_slice.get("operation_refs") or []:
                edges.append(
                    {
                        "source": slice_ref,
                        "target": str(operation_ref),
                        "type": "owns_operation",
                    }
                )
            for dependency in implementation_slice.get("depends_on") or []:
                edges.append(
                    {
                        "source": f"implementation_slice:{dependency}",
                        "target": slice_ref,
                        "type": "precedes",
                    }
                )
            for command_id in implementation_slice.get(
                "verification_command_ids"
            ) or []:
                edges.append(
                    {
                        "source": slice_ref,
                        "target": str(command_id),
                        "type": "verified_by",
                    }
                )
        commands, _coverage = self._verification_state(item)
        for command in commands:
            command_id = command["command_id"]
            nodes.append(
                {
                    "id": command_id,
                    "kind": "verification_command",
                    "label": " ".join(command["argv"]),
                }
            )
            for covered in command["covers"]:
                edges.append(
                    {
                        "source": str(covered),
                        "target": command_id,
                        "type": "verified_by",
                    }
                )
        for receipt in list(data.get("verifications") or []):
            receipt_id = str(receipt.get("receipt_id") or "")
            if not receipt_id:
                continue
            nodes.append(
                {
                    "id": receipt_id,
                    "kind": "verification_receipt",
                    "label": str(receipt.get("result") or "unknown"),
                }
            )
            edges.append(
                {
                    "source": str(receipt.get("command_id") or ""),
                    "target": receipt_id,
                    "type": "produced",
                }
            )
        repositories = data.get("repository_deliveries") or [{"repository_id": None, "git": data.get("git") or {}}]
        for entry in repositories:
            for commit in list((entry.get("git") or {}).get("result_commits") or []):
                identifier = f"{entry['repository_id']}:{commit}" if entry["repository_id"] is not None else commit
                nodes.append({"id": identifier, "kind": "result_commit", "label": commit[:12], "repository_id": entry["repository_id"]})
                if data.get("actual_result"):
                    edges.append({"source": "actual_result", "target": identifier, "type": "delivered_as"})
        if data.get("actual_result"):
            nodes.append(
                {
                    "id": "actual_result",
                    "kind": "actual_result",
                    "label": str(
                        data["actual_result"].get("effect_summary")
                        or "实际结果"
                    ),
                }
            )
            for receipt_id in list(
                data["actual_result"].get("verification_receipt_ids") or []
            ):
                edges.append(
                    {
                        "source": str(receipt_id),
                        "target": "actual_result",
                        "type": "supports",
                    }
                )
        return {
            "schema_version": "strixnova.management-trace.v1",
            "graph_kind": "engineering_management_trace",
            "nodes": nodes,
            "edges": [
                edge
                for edge in edges
                if edge["source"] and edge["target"]
            ],
        }


__all__ = [
    "ProjectIntegrationReferenceError",
    "READ_MODEL_SCHEMA",
    "WorkItemReadModel",
]
