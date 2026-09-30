"""Deterministic application-use-case coordination without semantic judgment."""

from __future__ import annotations

from strixnova.work_item_repositories import repository_item, repository_operation, selected_repository, previous_integrations
from strixnova.project_content_snapshot import capture_repository_content, compose_content_snapshot, verification_input_paths, repository_path_key, continued_verification_paths, verification_snapshot_matches
from strixnova.verification_dependencies import dependency_evidence_stale
from inspect import signature

from collections.abc import Mapping, Sequence
from contextlib import contextmanager, nullcontext
from copy import deepcopy
from datetime import datetime, timezone
from functools import wraps
import hashlib
import os
from pathlib import Path
from typing import Any

from strixnova.actual_result import (
    ActualResultError,
    validate_actual_result,
)
from strixnova.follow_ups import declared_refs
from strixnova.agent_setup import AgentSetupError, install_agent_skill
from strixnova.project_maintenance import MaintenanceError, ProjectMaintenance, project_operation
from strixnova.persistent_evidence import EvidenceReferenceError, capture_outputs
from strixnova.test_case_evidence import receipts_with_freshness
from strixnova.confirmation_protocol import (
    ConfirmationProtocolError,
    confirmation_input_schema,
    confirmation_record_from_input,
)
from strixnova.current_action import (
    current_action_for,
    direction_revision_action_for,
)
from strixnova.delivery_activity import (
    DeliveryActivityAuthority,
    DeliveryActivityError,
)
from strixnova.engineering_governance import (
    ASSESSMENT_SCHEMA,
    EngineeringGovernanceError,
    compile_engineering_plan,
    validate_assessment,
)
from strixnova.engineering_change_planning import (
    ChangePlanningError,
    focused_slice,
    implementation_reporting_coverage,
    implementation_slice_reportability,
    permitted_slice_operation_paths,
    validate_semantic_review,
)
from strixnova.git_workspace import GitWorkspace, GitWorkspaceError
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.project_context import ProjectContext, ProjectContextError, ProjectContextResolver
from strixnova.implementation_candidate_evidence import (
    ImplementationCandidateEvidence,
)
from strixnova.implementation_alignment_preparation import (
    ImplementationAlignmentPreparation,
    ImplementationAlignmentPreparationError,
)
from strixnova.project_authority_consistency import (
    DIRECTION_CONTEXT_RECOVERY_STATES,
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
    direction_context_invalidation_issues,
    direction_context_requires_validation,
)
from strixnova.project_authority_progress import (
    PROJECT_AUTHORITY_DECISION_SCHEMA,
    PROJECT_AUTHORITY_KINDS,
    PROJECT_AUTHORITY_PRESENTATION_SCHEMA,
    PROJECT_AUTHORITY_REVIEW_SCHEMA,
    ProjectAuthorityDecisionError,
    authority_confirmation_challenge,
    current_project_authority_presentations,
    current_project_authority_review,
    current_semantic_reviews,
    planned_upstream_authority_kinds,
    project_authority_prerequisites,
    project_authority_plan_ref,
)
from strixnova.project_authority_decision import (
    apply_project_authority_confirmation_transaction,
    build_project_authority_confirmation_transaction,
    confirmed_project_authority_snapshot,
    planned_project_authority_paths,
    project_authority_candidate,
    project_authority_review_bundle,
    validate_authority_change_targets,
    validate_project_authority_decision,
)
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.project_engineering_policy import load_base_governance_profile
from strixnova.project_implementation_alignment import (
    ProjectImplementationAlignment,
    ProjectImplementationAlignmentError,
)
from strixnova.project_product_definition import (
    ProjectProductDefinitionError,
    unadopted_project_direction_context,
    validate_direction_context_binding,
)
from strixnova.verification_runner import (
    APPROVED_VERIFICATION_REQUEST_SCHEMA,
    VerificationRunner,
    VerificationRunnerError,
)
from strixnova.yaml_metadata_patch import (
    YamlMetadataPatchError,
    apply_yaml_patch_transaction,
    atomic_write_bytes,
    build_yaml_patch_transaction,
    restore_yaml_patch_originals,
)
from strixnova.workflow_authority import (
    AUTHORITY_LOCAL_EXCLUDE_LINES,
    AuthorityConflict,
    TERMINAL_STATES,
    WORK_ITEM_STATES,
    WorkflowAuthority,
    WorkflowAuthorityError,
)


REPLAN_REQUEST_SCHEMA = "strixnova.replan-request.v1"


@contextmanager
def _exclusive_effect_lock(lock_path: Path):
    """Serialize one recoverable file-and-authority transaction per host."""

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    stream = lock_path.open("a+b")
    try:
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write(b"\0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
    finally:
        stream.close()


class ApplicationCoordinatorError(RuntimeError):
    """One application use case was rejected at a stable public boundary."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


class _InputValueError(ValueError):
    """One representation accepted by this coordinator is invalid."""


def required_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise _InputValueError(f"{field} 必须是字符串")
    normalized = value.strip()
    if not normalized:
        raise _InputValueError(f"{field} 不能为空")
    return normalized


def optional_text(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return required_text(value, field)


def closed_enum(value: Any, field: str, allowed: Sequence[str]) -> str:
    normalized = required_text(value, field)
    vocabulary = frozenset(allowed)
    if normalized not in vocabulary:
        raise _InputValueError(
            f"{field} 必须是 " + "、".join(sorted(vocabulary)) + " 之一"
        )
    return normalized


def string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise _InputValueError(f"{field} 必须是数组")
    return [
        required_text(item, f"{field}[{index}]")
        for index, item in enumerate(value)
    ]


def _public_use_case(function: Any) -> Any:
    """Translate internal module errors into one application error contract."""

    parameters = list(signature(function).parameters)
    item_position = parameters.index("work_item_id") if "work_item_id" in parameters else None

    @wraps(function)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        try:
            configured_scope = ProjectContextResolver(args[0].project).operation(args[0].project_bindings) if args and hasattr(args[0], "project") else nullcontext()
            with configured_scope:
                if args and hasattr(args[0], "project"):
                    if function.__name__ not in {
                        "project_current_action", "inspect_implementation_alignment",
                        "cancel", "cancel_planned_delivery_activity", "request_replan",
                    }:
                        identifier = kwargs.get("work_item_id")
                        if identifier is None and item_position is not None and item_position < len(args):
                            identifier = args[item_position]
                        args[0]._prepare_project_use_case(function.__name__, identifier)
                    scope = project_operation(args[0].management_project, operation_name=function.__name__)
                else:
                    scope = nullcontext()
                with scope:
                    if args and item_position is not None:
                        arguments = signature(function).bind_partial(*args, **kwargs).arguments
                        with args[0]._repository_operation_for(function.__name__, arguments):
                            effect_lock = args[0]._effect_lock(arguments["work_item_id"], "verification") if function.__name__ == "verify" else nullcontext()
                            with effect_lock:
                                return function(*args, **kwargs)
                    return function(*args, **kwargs)
        except ApplicationCoordinatorError:
            raise
        except (
            WorkflowAuthorityError,
            MaintenanceError,
            EvidenceReferenceError,
            EngineeringGovernanceError,
            GitWorkspaceError,
            GitProjectReaderError,
            ProjectContextError,
            VerificationRunnerError,
            ActualResultError,
            DeliveryActivityError,
            AgentSetupError,
            ProjectAuthorityConsistencyError,
            ProjectEngineeringBaselineError,
            ProjectAuthorityDecisionError,
            ProjectImplementationAlignmentError,
            ImplementationAlignmentPreparationError,
            YamlMetadataPatchError,
            OSError,
        ) as error:
            error_codes = {
                GitProjectReaderError: "project_read_failed",
                ProjectImplementationAlignmentError: (
                    "project_implementation_alignment_invalid"
                ),
                YamlMetadataPatchError: "project_metadata_patch_failed",
                OSError: "project_io_failed",
            }
            default_code = next(
                (
                    code
                    for error_type, code in error_codes.items()
                    if isinstance(error, error_type)
                ),
                "application_use_case_rejected",
            )
            raise ApplicationCoordinatorError(
                getattr(error, "code", default_code),
                str(error),
                details=(
                    getattr(error, "issues", None)
                    or getattr(error, "details", None)
                ),
            ) from error

    return wrapped


class ApplicationCoordinator:
    """Coordinate explicit use cases through existing domain boundaries."""

    def __init__(
        self, project_dir: str | Path, *, project_bindings: Mapping[str, Any] | None = None,
        shared_context: ProjectContext | None = None,
    ) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self.project_bindings = deepcopy(project_bindings)
        self.project_context = shared_context
        management = self.project
        if shared_context is None and project_bindings is not None:
            resolver = ProjectContextResolver(self.project)
            management = resolver.management_binding(project_bindings)
            try:
                self.project_context = resolver.configured(bindings=project_bindings)
            except (ProjectContextError, GitProjectReaderError):
                # Ordinary operations resolve again and reject damaged content.
                # Cancellation and history can still use explicit stored facts.
                self.project_context = None
        self.management_project = self.project_context.management_root if self.project_context is not None else management
        self._authority: WorkflowAuthority | None = None
        self.implementation_evidence = ImplementationCandidateEvidence(
            self.management_project
        )

    @property
    def authority(self) -> WorkflowAuthority:
        project_id = self.project_context.project_id if self.project_context is not None else (self.project_bindings or {}).get("project_id")
        if self._authority is None:
            self._authority = WorkflowAuthority(self.management_project, project_id=project_id)
        elif self._authority.expected_project_id != project_id:
            self._authority.expected_project_id = project_id
            self._authority.require_project_identity()
        return self._authority

    def _prepare_project_use_case(self, operation: str | None = None, work_item_id: str | None = None) -> None:
        self.project_context = ProjectContextResolver(self.project).configured(bindings=self.project_bindings, use_execution_bindings=False)
        if self.project_context is not None:
            baseline = ProjectEngineeringBaseline(self.project, shared_context=self.project_context)
            baseline.load(required=False, allow_candidate_refs=True)
            if self.project_context.management_root != self.management_project:
                raise ProjectContextError("management_binding_changed", "项目管理数据位置已改变，需要重新打开明确绑定")
            if self.management_project != self.project and (self.management_project / "strixnova-project.yaml").is_file():
                resident = ProjectContextResolver(self.management_project).configured()
                if resident is not None and resident.project_id != self.project_context.project_id:
                    raise ProjectContextError("authority_project_mismatch", "管理位置已有另一个项目的声明，不能共享事项库")
            if self.management_project.is_dir():
                self.authority.require_project_identity()
        if work_item_id is not None and not self.management_project.is_dir():
            raise WorkflowAuthorityError("authority_not_initialized", "项目尚未建立事项管理存储，不能执行该事项动作")

    @contextmanager
    def _repository_operation_for(self, operation: str, arguments: Mapping[str, Any]):
        identifier = arguments.get("work_item_id")
        if identifier is None:
            yield
            return
        current = self.authority.get(identifier)
        data = current["data"]
        chosen = selected_repository(data, current["status"])
        request = arguments.get("request") or arguments.get("receipt") or {}
        command_id = request.get("command_id")
        if operation == "assess_verification":
            receipt = next((value for value in data.get("verifications") or [] if value.get("receipt_id") == arguments.get("receipt_id")), {})
            command_id = receipt.get("command_id")
        if command_id:
            command = next((value for value in self._verification_commands(current) if value["command_id"] == command_id), None)
            if command is not None:
                chosen = command.get("repository_id")
        if operation == "project_authority_candidate":
            artifact_type = {"product_definition": "product_governance", "domain_model": "domain_model", "target_architecture": "architecture", "engineering_policy": "quality_policy"}.get(arguments.get("authority_kind"))
            candidates = [entry for entry in (data.get("engineering", {}).get("plan") or {}).get("operations", []) if (entry.get("long_lived_artifact") or {}).get("artifact_type") == artifact_type]
            if len(candidates) == 1:
                chosen = candidates[0].get("repository_id")
        if operation in {"prepare_implementation_alignment", "inspect_implementation_alignment", "capture_external_implementation_alignment", "write_implementation_alignment_candidate"}:
            alignment = [entry for entry in (data.get("engineering", {}).get("plan") or {}).get("operations", []) if (entry.get("long_lived_artifact") or {}).get("artifact_type") == "domain_alignment"]
            if len(alignment) == 1:
                chosen = alignment[0].get("repository_id")
        if "repository_id" in request and request["repository_id"] != chosen:
            raise ApplicationCoordinatorError("repository_action_mismatch", "仓库选择与当前命令或计划交付顺序不符")
        target_versions = {entry["repository_id"]: None for entry in data.get("repository_deliveries") or [] if not ((entry.get("git") or {}).get("integration") or {}).get("integrated_commit") and ((entry.get("git") or {}).get("conflict_resolution") or ((entry.get("git") or {}).get("integration") or {}).get("outcome") == "conflict")}
        readers = nullcontext() if operation in {"cancel", "request_replan"} else ProjectContextResolver(self.project).execution_readers(self.project_context, data.get("repository_deliveries") or [], observed_versions=target_versions or None)
        with repository_operation(chosen), readers:
            yield

    def _repository_root(self, current: Mapping[str, Any]) -> Path:
        identifier = current["data"].get("selected_repository_id")
        area = current["data"].get("git") or {}
        if self.project_context is not None and identifier is not None:
            repository = self.project_context.repository(identifier, for_modification=True)
            assert repository.checkout_path is not None
            return repository.checkout_path
        return Path(area["repository"]) if area.get("repository") else self.project

    def _workspace(self, current: Mapping[str, Any]) -> GitWorkspace:
        return GitWorkspace(self._repository_root(current))

    @staticmethod
    def _read_only_verification(current: Mapping[str, Any]) -> Mapping[str, Any] | None:
        identifier = current["data"].get("selected_repository_id")
        plan = (current["data"].get("engineering") or {}).get("plan") or {}
        declared = next((entry for entry in (plan.get("repository_scope") or {}).get("repositories", []) if identifier is not None and entry["repository_id"] == identifier and entry["role"] == "read"), None)
        if declared is not None:
            return declared
        integrated = ((current["data"].get("git") or {}).get("integration") or {}).get("integrated_commit")
        if identifier is not None and integrated:
            return {"repository_id": identifier, "investigation_ref": integrated, "role": "read"}
        return None

    @staticmethod
    def _conflict_item(current: Mapping[str, Any]) -> dict[str, Any]:
        for entry in current["data"].get("repository_deliveries") or []:
            area = entry.get("git") or {}
            if not (area.get("integration") or {}).get("integrated_commit") and (area.get("conflict_resolution") or (area.get("integration") or {}).get("outcome") == "conflict"):
                return repository_item(current, entry["repository_id"])
        return deepcopy(dict(current))

    def _verification_work_area(self, current: Mapping[str, Any]) -> Mapping[str, Any]:
        if self._read_only_verification(current):
            entries = current["data"].get("repository_deliveries") or []
            selected = next((entry for entry in entries if not ((entry.get("git") or {}).get("cleanup") or {}).get("safe")), None)
            if selected is None:
                raise VerificationRunnerError("implementation_work_area_missing", "缺少当前实施仓库工作区")
            current = repository_item(current, selected["repository_id"])
        binding = self._workspace(current).require_work_area_binding(self._work_area(current))
        if (current["data"].get("git") or {}).get("conflict_resolution"):
            binding = {**binding, "worktree_path": str(self._repository_root(current))}
        return binding

    @staticmethod
    def _execution_root_for_area(area: Mapping[str, Any], fallback: str | Path) -> str | Path:
        return area.get("repository") if area.get("conflict_resolution") or (area.get("integration") or {}).get("integrated_commit") else area.get("worktree_path") or fallback

    @staticmethod
    def _repository_changed_paths(current: Mapping[str, Any]) -> list[str]:
        area = ApplicationCoordinator._work_area(current)
        workspace = GitWorkspace(area["repository"])
        return workspace.changed_worktree_paths_from(workspace.resolve_commit("HEAD")) if area.get("conflict_resolution") else workspace.changed_paths(area)

    def _materialize_verification_input(self, current: Mapping[str, Any], receipt_id: str) -> Path:
        selection = self._read_only_verification(current)
        assert selection is not None and self.project_context is not None
        repository = self.project_context.repository(selection["repository_id"])
        reader = GitProjectReader.for_repository(repository.scope, observed_ref=None if selection["investigation_ref"] == "working_tree" else selection["investigation_ref"])
        target = self.management_project / ".strixnova/artifacts" / current["work_item_id"] / "repository-inputs" / receipt_id
        target.mkdir(parents=True, exist_ok=False)
        for path in reader.tracked_paths():
            if path.split("/", 1)[0] in {".git", ".strixnova"}:
                continue
            destination = target.joinpath(*path.split("/"))
            destination.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_bytes(destination, reader.read_canonical_bytes(path, "verification input"))
        return target

    def _result_readers(self, current: Mapping[str, Any]) -> dict[str | None, GitProjectReader]:
        entries = current["data"].get("repository_deliveries") or []
        if not entries:
            return {current["data"].get("selected_repository_id"): GitProjectReader(self._verification_execution_root(current))}
        readers = {}
        for entry in entries:
            selected = repository_item(current, entry["repository_id"])
            observed = ((entry.get("git") or {}).get("integration") or {}).get("integrated_commit")
            readers[entry["repository_id"]] = GitProjectReader(self._verification_execution_root(selected), observed_ref=observed)
        return readers

    def _review_subject(self, current: Mapping[str, Any]) -> dict[str, Any]:
        return ProjectAuthorityConsistency.review_subject_for(self.project, current, project_context=self.project_context, bindings=self.project_bindings)

    @contextmanager
    def _delivery_authority_checker(self, current: Mapping[str, Any], observed_ref: str | None = None):
        identifier = current["data"].get("selected_repository_id")
        with ProjectContextResolver(self.project).execution_readers(self.project_context, current["data"].get("repository_deliveries") or [], observed_versions={identifier: observed_ref} if identifier is not None else None):
            yield ProjectAuthorityConsistency(self._repository_root(current))

    def _require_project_result_content(self, current: Mapping[str, Any], *, before_acceptance: bool = False) -> None:
        latest_receipts = {entry["command_id"]: entry for entry in current["data"].get("verifications") or []}
        if any(entry.get("dependency_evidence") and dependency_evidence_stale(entry["dependency_evidence"]) for entry in latest_receipts.values()):
            raise WorkflowAuthorityError("dependency_evidence_expired", "整体结果依赖的版本证据已过期，需重新规划并核验后再接受或继续交付")
        entries = current["data"].get("repository_deliveries") or []
        for entry in entries or [{"repository_id": current["data"].get("selected_repository_id"), "git": current["data"].get("git") or {}}]:
            selected = repository_item(current, entry["repository_id"])
            area = entry.get("git") or {}
            if not area.get("work_ref"):
                continue
            integrated = (area.get("integration") or {}).get("integrated_commit")
            resolution = area.get("conflict_resolution")
            root = self._repository_root(selected) if integrated or isinstance(resolution, Mapping) else area["worktree_path"]
            if integrated and area.get("integrated_content_snapshot"):
                selected["data"]["actual_result"] = {"implementation_candidate_snapshot": area["integrated_content_snapshot"]}
            resolved_snapshot = (resolution or {}).get("implementation_candidate_snapshot")
            comparison_base = (area.get("integration") or {}).get("contribution_base_commit") if integrated else None
            if isinstance(resolution, Mapping) and not integrated:
                comparison_base = (resolved_snapshot or {}).get("comparison_base_commit")
            self._require_implementation_candidate_snapshot(selected, project_dir=root, observed_ref=integrated, comparison_base_ref=comparison_base, exclude_paths=self._mechanical_authority_paths(selected), use_conflict_resolution=bool(resolved_snapshot) and not integrated and not before_acceptance)
            if before_acceptance and not integrated and not resolution:
                if self._workspace(selected).result_commits(area, require_clean=False) != list(area.get("result_commits") or []):
                    raise ApplicationCoordinatorError("premature_result_commit", "整体结果接受前不能形成任一仓库的交付提交")

    @contextmanager
    def read_operation(self):
        """Keep a complete public read inside one maintenance admission."""
        try:
            with ProjectContextResolver(self.project).operation(self.project_bindings), project_operation(self.management_project, read_only=True):
                yield
        except MaintenanceError as error:
            raise ApplicationCoordinatorError(
                error.code, str(error), details=error.details
            ) from error

    def _effect_lock(self, work_item_id: str, kind: str):
        # Validate the Authority store and WorkItem through the read-only gate
        # before creating a persistent host lock file.
        self.authority.get(work_item_id)
        return self._project_effect_lock()

    def _project_effect_lock(self):
        # All project-authority effects share one lock.  Different operation
        # names or WorkItems must not concurrently replace the same long-lived
        # authority files.
        identity = hashlib.sha256(
            b"strixnova:project-authority-effects:v1"
        ).hexdigest()[:32]
        return _exclusive_effect_lock(
            self.authority.strixnova_root
            / "artifacts"
            / "effect-locks"
            / f"{identity}.lock"
        )

    @_public_use_case
    def project_authority_candidate(
        self,
        work_item_id: str,
        authority_kind: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Validate and record one exact candidate presentation."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"implementing"},
        )
        self._require_current_work_item_direction_context(current)
        binding = self._verification_work_area(current)
        action = current.get("current_action")
        if not isinstance(action, Mapping):
            action = current_action_for(current)
        author_action = bool(
            isinstance(action, Mapping)
            and action.get("action_type")
            == "author_project_authority_candidate"
            and action.get("authority_kind") == authority_kind
        )
        refresh_action = bool(
            isinstance(action, Mapping)
            and action.get("action_type")
            in {
                "review_project_authority_candidates",
                "confirm_project_authority_candidates",
            }
            and authority_kind in (action.get("authority_kinds") or [])
        )
        if not author_action and not refresh_action:
            raise ApplicationCoordinatorError(
                "project_authority_action_not_current",
                "只能按当前动作起草或重新展示长期权威候选",
            )
        candidate = project_authority_candidate(
            str(binding["worktree_path"]),
            current,
            authority_kind,
        )
        challenge = authority_confirmation_challenge(current, candidate)
        existing_presentations = current["data"].get(
            "project_authority_presentations"
        ) or []
        existing = next(
            (
                value
                for value in reversed(existing_presentations)
                if isinstance(value, Mapping)
                and value.get("authority_kind") == authority_kind
                and value.get("candidate") == candidate
                and value.get("confirmation_challenge") == challenge
            ),
            None,
        )
        if isinstance(existing, Mapping):
            return {
                "candidate": candidate,
                "confirmation_challenge": challenge,
                "confirmation_input_schema": confirmation_input_schema(
                    challenge
                ),
                "presented_at_work_item_version": existing.get(
                    "presented_at_work_item_version"
                ),
                "current_action": action,
            }
        presented_at = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        presentation = {
            "schema_version": PROJECT_AUTHORITY_PRESENTATION_SCHEMA,
            "authority_kind": authority_kind,
            "candidate": candidate,
            "confirmation_challenge": challenge,
            "presented_at": presented_at,
            "presented_at_work_item_version": expected_version + 1,
            "semantic_content_machine_proven": False,
        }
        updated = self.authority.transition(
            work_item_id,
            "record_project_authority_presentation",
            {"project_authority_presentation": presentation},
            expected_version=expected_version,
        )
        return {
            "candidate": candidate,
            "confirmation_challenge": challenge,
            "confirmation_input_schema": confirmation_input_schema(challenge),
            "presented_at_work_item_version": updated["version"],
            "current_action": updated.get("current_action"),
        }

    @_public_use_case
    def project_authority_review_candidate(
        self,
        work_item_id: str,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Read the exact final authority bundle that the agent must review."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"implementing"},
        )
        self._require_current_work_item_direction_context(current)
        action = current.get("current_action")
        if not isinstance(action, Mapping):
            action = current_action_for(current)
        if (
            not isinstance(action, Mapping)
            or action.get("action_type")
            not in {
                "review_project_authority_candidates",
                "confirm_project_authority_candidates",
            }
        ):
            raise ApplicationCoordinatorError(
                "project_authority_action_not_current",
                "只有完整候选包形成后才能读取待复核的五类长期权威正文身份",
            )
        binding = self._workspace(current).require_work_area_binding(
            self._work_area(current)
        )
        presentations = current_project_authority_presentations(current)
        candidate_bundle = project_authority_review_bundle(
            str(binding["worktree_path"]),
            current,
            presentations,
        )
        return {
            "candidate_bundle": candidate_bundle,
            "current_action": deepcopy(dict(action)),
            "work_item_version": current["version"],
        }

    @_public_use_case
    def review_project_authorities(
        self,
        work_item_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Record an agent eight-view review bound to the final candidate bytes."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"implementing"},
        )
        self._require_current_work_item_direction_context(current)
        action = current.get("current_action")
        if not isinstance(action, Mapping):
            action = current_action_for(current)
        if (
            not isinstance(action, Mapping)
            or action.get("action_type")
            not in {
                "review_project_authority_candidates",
                "confirm_project_authority_candidates",
            }
        ):
            raise ApplicationCoordinatorError(
                "project_authority_action_not_current",
                "只有完整候选包形成后才能提交绑定规范正文的八视角复核",
            )
        if set(payload) != {"schema_version", "semantic_review"} or payload.get(
            "schema_version"
        ) != "strixnova.project-authority-review-submission.v1":
            raise ApplicationCoordinatorError(
                "project_authority_review_invalid",
                "长期权威候选复核输入必须符合公开复核提交合同",
            )
        raw_review = payload.get("semantic_review")
        if not isinstance(raw_review, Mapping):
            raise ApplicationCoordinatorError(
                "project_authority_review_invalid",
                "semantic_review 必须是完整八视角复核对象",
            )
        binding = self._workspace(current).require_work_area_binding(
            self._work_area(current)
        )
        worktree = str(binding["worktree_path"])
        presentations = current_project_authority_presentations(current)
        candidate_bundle = project_authority_review_bundle(
            worktree,
            current,
            presentations,
        )
        plan = current["data"]["engineering"]["plan"]
        plan_review = plan.get("semantic_review")
        plan_decision_refs = (
            plan_review.get("question_budget", {}).get(
                "resolved_decision_refs",
                [],
            )
            if isinstance(plan_review, Mapping)
            and isinstance(plan_review.get("question_budget"), Mapping)
            else []
        )
        try:
            semantic_review = validate_semantic_review(
                raw_review,
                known_refs=set(candidate_bundle["reviewed_refs"]),
                known_decision_refs={
                    "direction",
                    *{
                        str(reference)
                        for reference in plan_decision_refs
                        if str(reference).strip()
                    },
                },
            )
        except ChangePlanningError as error:
            raise ApplicationCoordinatorError(
                "project_authority_review_invalid",
                "最终长期权威候选的八视角复核没有通过结构与证据绑定校验",
                details=error.issues,
            ) from error
        if set(semantic_review["reviewed_refs"]) != set(
            candidate_bundle["reviewed_refs"]
        ):
            raise ApplicationCoordinatorError(
                "project_authority_review_incomplete",
                "八视角复核必须逐一覆盖完整五类长期权威候选的精确正文身份",
                details={
                    "required_refs": candidate_bundle["reviewed_refs"],
                    "reviewed_refs": semantic_review["reviewed_refs"],
                },
            )
        existing_reviews = current["data"].get("project_authority_reviews") or []
        existing = next(
            (
                value
                for value in reversed(existing_reviews)
                if isinstance(value, Mapping)
                and isinstance(value.get("candidate_bundle"), Mapping)
                and value["candidate_bundle"].get("content_sha256")
                == candidate_bundle["content_sha256"]
            ),
            None,
        )
        if isinstance(existing, Mapping):
            return {
                "project_authority_review": deepcopy(dict(existing)),
                "work_item": current,
            }
        reviewed_at = datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )
        review_record = {
            "schema_version": PROJECT_AUTHORITY_REVIEW_SCHEMA,
            "plan_ref": deepcopy(candidate_bundle["plan_ref"]),
            "presentation_fingerprints": [
                str(
                    value["confirmation_challenge"].get(
                        "candidate_fingerprint"
                    )
                    or ""
                )
                for value in presentations
            ],
            "candidate_bundle": candidate_bundle,
            "semantic_review": semantic_review,
            "reviewed_at": reviewed_at,
            "reviewed_at_work_item_version": expected_version + 1,
            "semantic_content_machine_proven": False,
        }
        updated = self.authority.transition(
            work_item_id,
            "record_project_authority_review",
            {"project_authority_review": review_record},
            expected_version=expected_version,
        )
        return {
            "project_authority_review": review_record,
            "work_item": updated,
        }

    @_public_use_case
    def confirm_project_authorities(
        self,
        work_item_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Atomically apply one complete, separately presented decision package."""

        with self._effect_lock(work_item_id, "project_authority_confirmation"):
            return self._confirm_project_authorities_locked(
                work_item_id,
                payload,
                expected_version=expected_version,
            )

    def _confirm_project_authorities_locked(
        self,
        work_item_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Run one complete authority transaction while holding its host lock."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"implementing"},
        )
        self._require_current_work_item_direction_context(current)
        binding = self._verification_work_area(current)
        worktree = str(binding["worktree_path"])
        action = current.get("current_action")
        if not isinstance(action, Mapping):
            action = current_action_for(current)
        if (
            not isinstance(action, Mapping)
            or action.get("action_type")
            != "confirm_project_authority_candidates"
        ):
            raise ApplicationCoordinatorError(
                "project_authority_action_not_current",
                "只能确认当前动作中已完整独立展示的长期权威候选包",
            )
        presentations = current_project_authority_presentations(current)
        candidate_review = current_project_authority_review(current)
        current_bundle = project_authority_review_bundle(
            worktree,
            current,
            presentations,
        )
        recorded_bundle = candidate_review.get("candidate_bundle")
        if (
            not isinstance(recorded_bundle, Mapping)
            or dict(recorded_bundle) != dict(current_bundle)
        ):
            raise ApplicationCoordinatorError(
                "project_authority_review_stale",
                "八视角复核之后候选正文发生变化；必须先重新复核当前完整候选包",
                details={
                    "recorded_bundle_sha256": (
                        recorded_bundle.get("content_sha256")
                        if isinstance(recorded_bundle, Mapping)
                        else None
                    ),
                    "current_bundle_sha256": current_bundle["content_sha256"],
                },
            )
        raw_decisions = payload.get("decisions")
        if set(payload) != {"decisions"} or not isinstance(raw_decisions, list):
            raise ApplicationCoordinatorError(
                "project_authority_confirmation_bundle_invalid",
                "长期权威确认必须且只能提交完整 decisions（决定）数组",
            )
        expected_kinds = [
            str(presentation["authority_kind"])
            for presentation in presentations
        ]
        submitted_kinds = [
            str(value.get("authority_kind") or "")
            if isinstance(value, Mapping)
            else ""
            for value in raw_decisions
        ]
        if submitted_kinds != expected_kinds:
            raise ApplicationCoordinatorError(
                "project_authority_confirmation_bundle_invalid",
                "长期权威确认包必须按展示顺序完整覆盖当前全部候选",
                details={
                    "expected_authority_kinds": expected_kinds,
                    "submitted_authority_kinds": submitted_kinds,
                },
            )
        confirmations: list[dict[str, Any]] = []
        for index, (presentation, raw) in enumerate(
            zip(presentations, raw_decisions, strict=True)
        ):
            assert isinstance(raw, Mapping)
            if set(raw) != {
                "authority_kind",
                "candidate_fingerprint",
                "user_confirmation",
                "agent_decision",
            }:
                raise ApplicationCoordinatorError(
                    "project_authority_confirmation_bundle_invalid",
                    f"decisions[{index}] 字段不完整或包含未知字段",
                )
            try:
                confirmations.append(
                    confirmation_record_from_input(
                        presentation["confirmation_challenge"],
                        {
                            "candidate_fingerprint": raw.get(
                                "candidate_fingerprint"
                            ),
                            "user_confirmation": raw.get(
                                "user_confirmation"
                            ),
                            "agent_decision": raw.get("agent_decision"),
                        },
                    )
                )
            except ConfirmationProtocolError as error:
                raise ApplicationCoordinatorError(
                    error.code,
                    str(error),
                    details={"decision_index": index},
                ) from error
        accepted_by_kind = {
            kind: confirmation["accepted"] is True
            for kind, confirmation in zip(
                expected_kinds,
                confirmations,
                strict=True,
            )
        }
        invalid_acceptances = {
            kind: [
                prerequisite
                for prerequisite in project_authority_prerequisites(kind)
                if prerequisite in accepted_by_kind
                and accepted_by_kind[prerequisite] is False
            ]
            for kind in expected_kinds
            if accepted_by_kind[kind]
        }
        invalid_acceptances = {
            kind: prerequisites
            for kind, prerequisites in invalid_acceptances.items()
            if prerequisites
        }
        if invalid_acceptances:
            raise ApplicationCoordinatorError(
                "project_authority_confirmation_order_invalid",
                "被接受的下游候选不能依赖同一确认包中已退回的上游候选",
                details=invalid_acceptances,
            )
        self._require_authority_confirmation_path_scope(
            current,
            project_dir=worktree,
        )
        pending_effect = current.get("data", {}).get("pending_effect")
        recovering_confirmation = bool(
            isinstance(pending_effect, Mapping)
            and pending_effect.get("kind")
            == "project_authority_confirmation"
        )
        if not recovering_confirmation:
            for presentation in presentations:
                authority_kind = str(presentation["authority_kind"])
                current_candidate = project_authority_candidate(
                    worktree,
                    current,
                    authority_kind,
                )
                if dict(current_candidate) != dict(presentation["candidate"]):
                    raise ApplicationCoordinatorError(
                        "project_authority_candidate_changed",
                        "候选展示之后长期权威正文或上游绑定发生变化；请重新展示候选包",
                        details={"authority_kind": authority_kind},
                    )
        intent_base = {
            "decisions": deepcopy(list(raw_decisions)),
            "candidate_fingerprints": [
                str(
                    presentation["confirmation_challenge"].get(
                        "candidate_fingerprint"
                    )
                    or ""
                )
                for presentation in presentations
            ],
        }
        transaction_decisions = [
            {
                "candidate": deepcopy(dict(presentation["candidate"])),
                "accepted": confirmation["accepted"] is True,
            }
            for presentation, confirmation in zip(
                presentations,
                confirmations,
                strict=True,
            )
        ]
        if recovering_confirmation:
            assert isinstance(pending_effect, Mapping)
            stored_intent = pending_effect.get("intent")
            if not isinstance(stored_intent, Mapping):
                raise WorkflowAuthorityError(
                    "external_effect_intent_invalid",
                    "长期权威确认恢复意图结构无效",
                )
            confirmed_at = str(stored_intent.get("confirmed_at") or "")
            if any(
                stored_intent.get(field) != value
                for field, value in intent_base.items()
            ):
                raise WorkflowAuthorityError(
                    "external_effect_intent_changed",
                    "待恢复长期权威确认与当前完整决定包不一致",
                )
            metadata_transaction = stored_intent.get("metadata_transaction")
            if not isinstance(metadata_transaction, Mapping):
                raise WorkflowAuthorityError(
                    "external_effect_intent_invalid",
                    "长期权威确认恢复意图缺少精确元数据事务",
                )
            confirmation_intent = deepcopy(dict(stored_intent))
        else:
            confirmed_at = datetime.now(timezone.utc).isoformat().replace(
                "+00:00", "Z"
            )
            metadata_transaction = (
                build_project_authority_confirmation_transaction(
                    worktree,
                    current,
                    transaction_decisions,
                    confirmed_on=confirmed_at[:10],
                )
            )
            confirmation_intent = {
                **intent_base,
                "confirmed_at": confirmed_at,
                "metadata_transaction": metadata_transaction,
            }
        current = self._claim_external_effect(
            current,
            kind="project_authority_confirmation",
            intent=confirmation_intent,
        )
        records: list[dict[str, Any]] = []
        originals: dict[Path, bytes] = {}
        working_item = deepcopy(dict(current))
        working_data = deepcopy(dict(working_item.get("data") or {}))
        working_item["data"] = working_data
        working_records = list(
            working_data.get("project_authority_decisions") or []
        )
        try:
            changed_originals = (
                apply_project_authority_confirmation_transaction(
                    worktree,
                    metadata_transaction,
                )
            )
            originals.update(changed_originals)
            for presentation, confirmation in zip(
                presentations,
                confirmations,
                strict=True,
            ):
                authority_kind = str(presentation["authority_kind"])
                candidate = presentation["candidate"]
                if confirmation["accepted"] is True:
                    confirmed = confirmed_project_authority_snapshot(
                        worktree,
                        working_item,
                        candidate,
                    )
                    current_candidate = dict(candidate)
                else:
                    current_candidate = project_authority_candidate(
                        worktree,
                        working_item,
                        authority_kind,
                    )
                if dict(current_candidate) != dict(candidate):
                    raise ApplicationCoordinatorError(
                        "project_authority_candidate_changed",
                        "候选展示之后长期权威正文或上游绑定发生变化；请重新展示候选包",
                        details={"authority_kind": authority_kind},
                    )
                record: dict[str, Any] = {
                    "schema_version": PROJECT_AUTHORITY_DECISION_SCHEMA,
                    "authority_kind": authority_kind,
                    "candidate": deepcopy(dict(candidate)),
                    "confirmation_challenge": deepcopy(
                        dict(presentation["confirmation_challenge"])
                    ),
                    "confirmation": confirmation,
                    "confirmed_at": confirmed_at,
                    "confirmed_on": None,
                    "confirmed_content_sha256": None,
                    "semantic_content_machine_proven": False,
                }
                if confirmation["accepted"] is True:
                    record["confirmed_on"] = confirmed["confirmed_on"]
                    record["confirmed_content_sha256"] = confirmed[
                        "confirmed_content_sha256"
                    ]
                working_records.append(record)
                working_data["project_authority_decisions"] = working_records
                records.append(record)
            return self.authority.transition(
                work_item_id,
                "record_project_authority_decision_bundle",
                {"project_authority_decisions": records},
                expected_version=int(current["version"]),
            )
        except Exception:
            restore_yaml_patch_originals(worktree, metadata_transaction, originals)
            raise

    @staticmethod
    @_public_use_case
    def install_agent_guidance(
        *,
        skills_dir: Path | None = None,
        replace: bool = False,
    ) -> dict[str, Any]:
        """Install optional packaged guidance without changing host settings."""

        return install_agent_skill(
            skills_dir=skills_dir,
            replace=replace,
        )

    @_public_use_case
    def intake(self, *, title: str, raw_request: str) -> dict[str, Any]:
        """Create one work item from explicit text without inferring intent."""

        try:
            normalized_title = required_text(title, "title")
            normalized_request = required_text(raw_request, "request")
        except _InputValueError as error:
            raise ApplicationCoordinatorError("invalid_intake", str(error)) from error
        if not self.management_project.exists():
            self.management_project.mkdir(parents=True)
        # Authority format is the first trust boundary. Reject an unsupported
        # development database before touching Git excludes or support files.
        self.authority.initialize()
        try:
            local_entry = self.management_project == self.project and (
                self.project_context is None or len([item for item in self.project_context.repositories if item.membership == "member"]) == 1
            )
            if local_entry and not GitWorkspace.local_excludes_present(
                self.project,
                AUTHORITY_LOCAL_EXCLUDE_LINES,
            ):
                GitWorkspace(self.project).ensure_local_excludes(
                    AUTHORITY_LOCAL_EXCLUDE_LINES
                )
        except GitWorkspaceError as error:
            if error.code not in {
                "git_missing",
                "git_required",
                "project_root_mismatch",
            }:
                raise
        return self.authority.create(
            title=normalized_title,
            raw_request=normalized_request,
        )

    @_public_use_case
    def project_current_action(
        self,
        current: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        """Overlay deterministic project-context invalidation on stored state."""

        action = current.get("current_action")
        projected = deepcopy(dict(action)) if isinstance(action, Mapping) else None
        issues = self._direction_context_invalidation_issues(current)
        if issues:
            return direction_revision_action_for(current, issues)
        if current.get("status") in {"implementing", "exploring", "integration_conflict"}:
            return current_action_for(self._with_case_input_checks(current))
        return projected

    def _verification_execution_root(self, current: Mapping[str, Any]) -> Path:
        selection = self._read_only_verification(current)
        if selection is not None and self.project_context is not None:
            return self.project_context.repository(selection["repository_id"]).checkout_path
        git = current.get("data", {}).get("git") or {}
        git = git if isinstance(git, Mapping) else {}
        if current.get("status") == "exploring" or isinstance(git.get("conflict_resolution"), Mapping) or (git.get("integration") or {}).get("integrated_commit"):
            return self._repository_root(current)
        worktree = git.get("worktree_path")
        return Path(worktree) if isinstance(worktree, str) else self._repository_root(current)

    def _verification_input_snapshot(self, current: Mapping[str, Any], command: Mapping[str, Any]) -> dict[str, Any]:
        plan = current["data"]["engineering"]["plan"]
        identifiers = command.get("input_repository_ids") or [command.get("repository_id")]
        inputs = []
        for identifier in identifiers:
            scoped = next((entry for entry in (plan.get("repository_scope") or {}).get("repositories", []) if entry["repository_id"] == identifier), {})
            selected = repository_item(current, identifier)
            if scoped.get("role") == "read" and identifier is not None:
                if self.project_context is None:
                    raise ProjectContextError("project_repository_unbound", "只读输入仓库需要明确的本机绑定")
                root = self.project_context.repository(identifier).checkout_path
                reader = GitProjectReader(root, observed_ref=None if scoped["investigation_ref"] == "working_tree" else scoped["investigation_ref"])
            else:
                root = self._verification_execution_root(selected)
                integrated = (selected["data"].get("git", {}).get("integration") or {}).get("integrated_commit")
                reader = GitProjectReader(root, observed_ref=integrated)
            paths = verification_input_paths(plan, command, identifier, reader)
            inputs.append(capture_repository_content(identifier, reader, sorted(paths), canonical=identifier is not None or current.get("status") != "exploring"))
        return compose_content_snapshot(plan["plan_id"], inputs)

    def _with_case_input_checks(self, current: Mapping[str, Any]) -> dict[str, Any]:
        projected = deepcopy(dict(current))
        if current.get("status") not in {"exploring", "implementing", "integration_conflict", "awaiting_actual_result"}:
            return projected
        data = projected.get("data")
        if isinstance(data, dict) and data.get("verifications"):
            commands = {entry["command_id"]: entry for entry in self._verification_commands(current)}
            continued = continued_verification_paths(data['engineering']['plan'], data['verifications'], data.get('implementation_slice_completions') or [])
            receipts = []
            for receipt in data.get("verifications") or []:
                command = commands.get(receipt.get("command_id"))
                if command is None:
                    receipts.append(receipt)
                    continue
                selected = repository_item(current, command.get("repository_id"))
                excluded = continued.get(command['command_id'], {})
                checked = receipts_with_freshness([receipt], None if self._read_only_verification(selected) else self._verification_execution_root(selected), exclude_paths=excluded.get(command.get('repository_id'), ()))[0]
                if receipt.get("dependency_evidence") and dependency_evidence_stale(receipt["dependency_evidence"]):
                    checked["_case_input_stale"] = True
                if receipt.get("project_input_snapshot") is not None:
                    live = self._verification_input_snapshot(current, command)
                    if receipt.get("inputs_changed_during_execution") or not verification_snapshot_matches(receipt['project_input_snapshot'], live, excluded):
                        checked["_case_input_stale"] = True
                receipts.append(checked)
            data["verifications"] = receipts
        return projected

    @_public_use_case
    def prepare_implementation_alignment(
        self,
        work_item_id: str,
        request: Mapping[str, Any] | None,
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Create one immutable local observation packet without changing state."""

        with self._effect_lock(work_item_id, "implementation_alignment"):
            current = self._current_for_effect(
                work_item_id,
                expected_version,
                {"implementing"},
            )
            return ImplementationAlignmentPreparation(self.management_project).prepare(
                current,
                request,
            )

    @_public_use_case
    def inspect_implementation_alignment(
        self,
        work_item_id: str,
        preparation_ref: Mapping[str, Any],
        *,
        cursor: str | None,
        limit: int,
        expected_version: int,
    ) -> dict[str, Any]:
        """Read one bounded logical page from an immutable preparation."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"implementing"},
        )
        return ImplementationAlignmentPreparation(self.management_project).inspect(
            current,
            preparation_ref,
            cursor=cursor,
            limit=limit,
        )

    @_public_use_case
    def garbage_collect_implementation_alignment(
        self,
        *,
        apply: bool,
        expected_orphan_set_sha256: str | None,
    ) -> dict[str, Any]:
        """Preview or remove only unreferenced alignment cache components."""

        module = ImplementationAlignmentPreparation(self.management_project)
        if not apply:
            return module.garbage_collect_artifacts(apply=False)
        with self._project_effect_lock():
            return module.garbage_collect_artifacts(
                apply=True,
                expected_orphan_set_sha256=expected_orphan_set_sha256,
            )

    @_public_use_case
    def capture_external_implementation_alignment(
        self,
        work_item_id: str,
        preparation_ref: Mapping[str, Any],
        *,
        authorize_external: bool,
        expected_version: int,
    ) -> dict[str, Any]:
        """Run only exact confirmed provider plans under explicit authorization."""

        with self._effect_lock(work_item_id, "implementation_alignment"):
            current = self._current_for_effect(
                work_item_id,
                expected_version,
                {"implementing"},
            )
            return ImplementationAlignmentPreparation(
                self.management_project
            ).capture_external(
                current,
                preparation_ref,
                authorize_external=authorize_external,
            )

    @_public_use_case
    def write_implementation_alignment_candidate(
        self,
        work_item_id: str,
        payload: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Write one draft candidate transaction without confirming or advancing."""

        with self._effect_lock(work_item_id, "implementation_alignment"):
            current = self._current_for_effect(
                work_item_id,
                expected_version,
                {"implementing"},
            )
            return ImplementationAlignmentPreparation(self.management_project).write_candidate(
                current,
                payload,
                current_binding_check=lambda: self._current_for_effect(
                    work_item_id,
                    expected_version,
                    {"implementing"},
                ),
            )

    def _current_for_effect(
        self,
        work_item_id: str,
        expected_version: int,
        allowed_states: set[str],
        *, check_inputs: bool = True,
    ) -> dict[str, Any]:
        current = self.authority.get(work_item_id)
        if current["version"] != expected_version:
            raise AuthorityConflict(
                "stale_version",
                (
                    f"WorkItem 已是版本 {current['version']}，"
                    f"调用方仍基于版本 {expected_version}；请重新读取"
                ),
            )
        if current["status"] not in allowed_states:
            raise WorkflowAuthorityError(
                "invalid_transition",
                (
                    f"当前状态 {current['status']} 不允许执行该操作；"
                    "请读取 CurrentAction"
                ),
            )
        return self._with_case_input_checks(current) if check_inputs else current

    @staticmethod
    def _work_area(current: Mapping[str, Any]) -> dict[str, Any]:
        data = current.get("data")
        value = data.get("git") if isinstance(data, Mapping) else None
        if not isinstance(value, Mapping) or value.get("schema_version") != (
            "strixnova.git-work-area.v1"
        ):
            raise WorkflowAuthorityError(
                "git_work_area_missing",
                "当前 WorkItem 没有有效的 Git 工作区记录",
            )
        return dict(value)

    @staticmethod
    def _stable_authority_value(value: Any) -> Any:
        """Remove reader-only observation metadata from an authority value."""

        if isinstance(value, Mapping):
            return {
                str(key): ApplicationCoordinator._stable_authority_value(item)
                for key, item in value.items()
                if not str(key).startswith("_")
                and str(key) != "observed_commit"
            }
        if isinstance(value, list):
            return [
                ApplicationCoordinator._stable_authority_value(item)
                for item in value
            ]
        return deepcopy(value)

    @staticmethod
    def _authority_ref_projection(
        project_dir: str | Path,
        observed_ref: str,
        *,
        checker: ProjectAuthorityConsistency | None = None,
    ) -> dict[str, Any] | None:
        """Read the exact adopted authority chain and deterministic readiness."""

        baseline = checker.baseline_reader if checker is not None else ProjectEngineeringBaseline(
            project_dir,
            observed_ref=observed_ref,
        )
        if not baseline.engineering_baseline_exists():
            return None
        loaded = (checker or ProjectAuthorityConsistency(
            project_dir,
            observed_ref=observed_ref,
        )).load()
        authority_kinds = (
            "product_definition",
            "domain_model",
            "target_architecture",
            "engineering_policy",
            "implementation_alignment",
        )
        baseline_value = loaded["baseline"]
        alignment_value = loaded["implementation_alignment"]
        return {
            "baseline": ApplicationCoordinator._stable_authority_value(
                {
                    "schema_version": baseline_value.get("schema_version"),
                    "baseline_id": baseline_value.get("baseline_id"),
                    "project": baseline_value.get("project"),
                    "authority_refs": {
                        kind: baseline_value.get("authority_refs", {}).get(kind)
                        for kind in authority_kinds
                    },
                    "current_architecture_stage_id": baseline_value.get(
                        "current_architecture_stage_id"
                    ),
                }
            ),
            "product_definition": ApplicationCoordinator._stable_authority_value(
                loaded["product_definition"]
            ),
            "domain_catalog": ApplicationCoordinator._stable_authority_value(
                loaded["domain_catalog"]
            ),
            "target_architecture": ApplicationCoordinator._stable_authority_value(
                loaded["target_architecture"]
            ),
            "engineering_policy": ApplicationCoordinator._stable_authority_value(
                loaded["engineering_policy"]
            ),
            # A different adopted alignment revision makes a plan based on the
            # old exact chain mechanically stale.  The observation-only code
            # snapshot is intentionally excluded: an unrelated item may
            # refresh those bytes without changing this plan's semantics.
            "implementation_alignment": ApplicationCoordinator._stable_authority_value(
                {
                    key: value
                    for key, value in alignment_value.items()
                    if key != "code_snapshot"
                }
            ),
        }

    def _record_delivery_target_advance(
        self,
        current: Mapping[str, Any],
        workspace: GitWorkspace,
    ) -> dict[str, Any] | None:
        """Record a target movement before any commit or integration side effect."""

        area = self._work_area(current)
        if current["status"] in {"commit_required", "integration_required"} and not current["data"].get("pending_effect"):
            self._require_project_result_content(current)
        target_ref = str(area["target_ref"])
        base_commit = str(area["base_commit"])
        target_commit = str(workspace.inspect(target_ref)["target_commit"])
        if target_commit == base_commit:
            return None
        prior = area.get("target_advance")
        if isinstance(prior, Mapping) and prior.get("target_commit") == target_commit and isinstance(prior.get("assessment"), Mapping):
            return None
        try:
            with self._delivery_authority_checker(current, base_commit) as checker:
                previous_authorities = self._authority_ref_projection(self._repository_root(current), base_commit, checker=checker)
            with self._delivery_authority_checker(current, target_commit) as checker:
                current_authorities = self._authority_ref_projection(self._repository_root(current), target_commit, checker=checker)
            authority_refs_changed = previous_authorities != current_authorities
        except (
            ProjectEngineeringBaselineError,
            ProjectAuthorityConsistencyError,
        ):
            authority_refs_changed = True
        advance = {
            "schema_version": "strixnova.target-advance.v1",
            "target_ref": target_ref,
            "target_commit": target_commit,
            "investigation_commit": base_commit,
            "authority_refs_changed": authority_refs_changed,
            "assessment": None,
        }
        if prior == advance:
            return dict(current)
        return self.authority.transition(
            str(current["work_item_id"]),
            "record_target_advance",
            {"target_advance": advance},
            expected_version=int(current["version"]),
        )

    def _claim_external_effect(
        self,
        current: Mapping[str, Any],
        *,
        kind: str,
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        data = current.get("data")
        pending = (
            data.get("pending_effect") if isinstance(data, Mapping) else None
        )
        if isinstance(pending, Mapping):
            if pending.get("kind") != kind:
                raise WorkflowAuthorityError(
                    "external_effect_in_progress",
                    "当前 WorkItem 正在处理其他外部副作用："
                    + str(pending.get("kind")),
                )
            if dict(pending.get("intent") or {}) != dict(intent):
                raise WorkflowAuthorityError(
                    "external_effect_intent_changed",
                    "待恢复外部副作用的精确意图与本次调用不一致",
                )
            return dict(current)
        return self.authority.transition(
            str(current["work_item_id"]),
            "claim_external_effect",
            {"kind": kind, "intent": dict(intent)},
            expected_version=int(current["version"]),
        )

    @_public_use_case
    def delivery(
        self,
        work_item_id: str,
        request: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Coordinate one explicit local-delivery action and record its facts."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {
                "implementation_ready",
                "exploring",
                "implementing",
                "commit_required",
                "integration_required",
                "integration_conflict",
                "cleanup_required",
            },
        )
        if current.get("status") in DIRECTION_CONTEXT_RECOVERY_STATES:
            self._require_current_work_item_direction_context(current)
        action = current.get("current_action") or {}
        if action.get("action_type") in {
            "investigate_and_report",
            "present_actual_result",
            "present_actual_result_after_conflict",
        }:
            updated, coverage = self.present_actual_result(
                work_item_id,
                request,
                expected_version=int(current["version"]),
            )
            return {
                "work_item": updated,
                "steps": ["actual_result_presented"],
                "coverage": coverage,
            }
        if current["status"] in {"exploring", "implementing"}:
            raise WorkflowAuthorityError(
                "verification_or_result_expected",
                "当前应继续实施并验证；验证满足后再提交实际结果",
            )
        allowed_fields = {
            "repository_id",
            "target_ref",
            "worktree_path",
            "merge_strategy",
        }
        extra = sorted(set(request) - allowed_fields)
        if extra:
            raise ApplicationCoordinatorError(
                "invalid_delivery_request",
                "当前 delivery 输入包含未知字段：" + ", ".join(extra),
            )
        try:
            target_ref = optional_text(request.get("target_ref"), "target_ref")
            worktree_path = (
                Path(required_text(request.get("worktree_path"), "worktree_path"))
                .expanduser()
                if "worktree_path" in request
                else None
            )
            merge_strategy = (
                closed_enum(
                    request.get("merge_strategy"),
                    "merge_strategy",
                    {"no_ff", "ff_only"},
                )
                if "merge_strategy" in request
                else None
            )
        except _InputValueError as error:
            raise ApplicationCoordinatorError(
                "invalid_delivery_request",
                str(error),
            ) from error

        repository_root = self._repository_root(current)
        workspace = GitWorkspace(repository_root)
        steps: list[str] = []
        if current["status"] == "implementation_ready":
            pending = current["data"].get("pending_effect")
            if isinstance(pending, Mapping) and pending.get("kind") == "prepare_work_area":
                area = deepcopy(pending["intent"]["work_area"])
                if (target_ref and target_ref != area["target_ref"]) or (worktree_path is not None and worktree_path.resolve() != Path(area["worktree_path"])) or (merge_strategy and merge_strategy != area["merge_strategy"]):
                    raise WorkflowAuthorityError("external_effect_intent_changed", "恢复工作区建立必须沿用原目标、位置和合入策略")
                materialized = workspace.materialize_work_area(area)
                updated = self.authority.transition(work_item_id, "record_implementation_started", {"git": materialized}, expected_version=int(current["version"]))
                return {"work_item": updated, "steps": ["work_area_recovered"]}
            responsibility = next((entry for entry in current["data"].get("repository_deliveries") or [] if entry["repository_id"] == current["data"].get("selected_repository_id")), {})
            planned_target = responsibility.get("target_ref")
            if target_ref and planned_target and target_ref != planned_target:
                raise WorkflowAuthorityError("repository_target_mismatch", "交付目标必须与已确认仓库责任一致")
            target_ref = target_ref or planned_target
            if not target_ref:
                raise WorkflowAuthorityError(
                    "target_ref_required",
                    "开始实施必须给出本地 target_ref",
                )
            inspection = workspace.inspect(target_ref)
            assessment = current["data"]["engineering"].get("assessment") or {}
            investigation_commit = str(
                responsibility.get("investigation_commit") or assessment.get("investigation_ref") or ""
            ).strip()
            target_commit = str(inspection["target_commit"])
            target_advance = current["data"].get("git") or {}
            target_advance = (
                target_advance.get("target_advance")
                if isinstance(target_advance, Mapping)
                else None
            )
            if investigation_commit and target_commit != investigation_commit:
                matches = (
                    isinstance(target_advance, Mapping)
                    and target_advance.get("target_ref") == target_ref
                    and target_advance.get("target_commit") == target_commit
                    and target_advance.get("investigation_commit")
                    == investigation_commit
                )
                if not matches:
                    try:
                        authority_refs_changed = (
                            self._authority_ref_projection(
                                repository_root,
                                investigation_commit,
                            )
                            != self._authority_ref_projection(
                                repository_root,
                                target_commit,
                            )
                        )
                    except (
                        ProjectEngineeringBaselineError,
                        ProjectAuthorityConsistencyError,
                    ):
                        authority_refs_changed = True
                    updated = self.authority.transition(
                        work_item_id,
                        "record_target_advance",
                        {
                            "target_advance": {
                                "schema_version": "strixnova.target-advance.v1",
                                "target_ref": target_ref,
                                "target_commit": target_commit,
                                "investigation_commit": investigation_commit,
                                "authority_refs_changed": (
                                    authority_refs_changed
                                ),
                                "assessment": None,
                            }
                        },
                        expected_version=int(current["version"]),
                    )
                    return {
                        "work_item": updated,
                        "steps": ["target_advance_detected"],
                    }
                if not isinstance(target_advance.get("assessment"), Mapping):
                    return {
                        "work_item": current,
                        "steps": ["target_advance_waiting_for_assessment"],
                    }
            else:
                target_advance = None
            area = workspace.create_work_area(
                work_item_id=work_item_id,
                target_ref=target_ref,
                worktree_path=worktree_path,
                merge_strategy=merge_strategy or "no_ff",
                expected_target_commit=target_commit,
                plan_only=True,
            )
            if isinstance(target_advance, Mapping):
                area["target_advance"] = dict(target_advance)
            current = self._claim_external_effect(current, kind="prepare_work_area", intent={"work_area": area})
            area = workspace.materialize_work_area(area)
            updated = self.authority.transition(work_item_id, "record_implementation_started", {"git": area}, expected_version=int(current["version"]))
            return {"work_item": updated, "steps": ["work_area_created"]}

        area = self._work_area(current)
        if current["status"] in {"commit_required", "integration_required"}:
            pending_effect = current.get("data", {}).get("pending_effect")
            recovering_integration = bool(
                isinstance(pending_effect, Mapping)
                and pending_effect.get("kind") == "integrate"
            )
            target_advance_update = (
                None
                if recovering_integration
                else self._record_delivery_target_advance(
                    current,
                    workspace,
                )
            )
            if target_advance_update is not None:
                return {
                    "work_item": target_advance_update,
                    "steps": ["target_advance_detected"],
                }
        if current["status"] == "commit_required":
            worktree_path = str(area["worktree_path"])
            already_mechanical_paths = self._mechanical_authority_paths(
                current
            )
            self._require_implementation_candidate_snapshot(
                current,
                project_dir=worktree_path,
                exclude_paths=already_mechanical_paths,
            )
            finalized = self._finalize_authority_adoption(
                current,
                project_dir=worktree_path,
            )
            if finalized is not None:
                return {
                    "work_item": finalized,
                    "steps": ["authority_adoption_finalized"],
                }
            mechanical_paths = self._mechanical_authority_paths(current)
            self._require_implementation_candidate_snapshot(
                current,
                project_dir=worktree_path,
                exclude_paths=mechanical_paths,
            )
            self._require_completed_slice_snapshots(
                current,
                project_dir=worktree_path,
                exclude_paths=mechanical_paths,
            )
            commits = workspace.result_commits(area)
            self._require_implementation_candidate_snapshot(
                current,
                project_dir=worktree_path,
                observed_ref=commits[-1],
                exclude_paths=mechanical_paths,
            )
            self._require_completed_slice_snapshots(
                current,
                project_dir=worktree_path,
                observed_ref=commits[-1],
                exclude_paths=mechanical_paths,
            )
            current = self.authority.transition(
                work_item_id,
                "record_result_commits",
                {"commits": commits},
                expected_version=int(current["version"]),
            )
            steps.append("result_commits_recorded")
            area = self._work_area(current)

        if current["status"] in {"integration_required", "integration_conflict"}:
            recorded_commits = list(area.get("result_commits") or [])
            expected_target_commit = str(
                (
                    area.get("target_advance", {}).get("target_commit")
                    if isinstance(area.get("target_advance"), Mapping)
                    and isinstance(
                        area.get("target_advance", {}).get("assessment"),
                        Mapping,
                    )
                    else area["base_commit"]
                )
            )
            if recorded_commits:
                live_commits = workspace.branch_result_commits(area)
                if live_commits != recorded_commits:
                    raise WorkflowAuthorityError(
                        "result_commits_changed_before_integration",
                        "已记录的结果提交在本地合入前发生变化；禁止合入未由负责人确认的新提交",
                        details={
                            "recorded_result_commits": recorded_commits,
                            "current_result_commits": live_commits,
                        },
                    )
                if current["status"] != "integration_conflict":
                    mechanical_paths = self._mechanical_authority_paths(current)
                    self._require_implementation_candidate_snapshot(
                        current,
                        project_dir=str(area["worktree_path"]),
                        observed_ref=live_commits[-1],
                        exclude_paths=mechanical_paths,
                    )
                    self._require_completed_slice_snapshots(
                        current,
                        project_dir=str(area["worktree_path"]),
                        observed_ref=recorded_commits[-1],
                        exclude_paths=mechanical_paths,
                    )
            if current["status"] == "integration_conflict":
                action_type = (current.get("current_action") or {}).get(
                    "action_type"
                )
                if action_type != "complete_git_merge":
                    raise WorkflowAuthorityError(
                        "conflict_resolution_incomplete",
                        "请先记录冲突判断并重跑受影响验证",
                    )
                conflict_resolution = area.get("conflict_resolution")
                use_conflict_snapshot = bool(
                    isinstance(conflict_resolution, Mapping)
                    and isinstance(
                        conflict_resolution.get(
                            "implementation_candidate_snapshot"
                        ),
                        Mapping,
                    )
                )
                self._require_implementation_candidate_snapshot(
                    current,
                    project_dir=repository_root,
                    use_conflict_resolution=use_conflict_snapshot,
                )
                try:
                    integration = workspace.integration_result(
                        area,
                        expected_result_commits=recorded_commits or None,
                        expected_target_commit=expected_target_commit,
                    )
                except GitWorkspaceError as error:
                    if error.code != "integration_not_complete":
                        raise
                    raise WorkflowAuthorityError(
                        "merge_commit_required",
                        "冲突已经复测；请由 Agent 完成当前原生 Git merge commit 后重试",
                    ) from error
            else:
                current = self._claim_external_effect(
                    current,
                    kind="integrate",
                    intent={
                        "merge_strategy": (
                            merge_strategy
                            or str(area.get("merge_strategy") or "no_ff")
                        ),
                        "expected_result_commits": recorded_commits,
                        "expected_target_commit": expected_target_commit,
                    },
                )
                pending = current["data"]["pending_effect"]
                assert isinstance(pending, Mapping)
                intent = pending.get("intent")
                assert isinstance(intent, Mapping)
                try:
                    integration = workspace.integrate(
                        area,
                        merge_strategy=str(intent["merge_strategy"]),
                        expected_result_commits=recorded_commits or None,
                        expected_target_commit=expected_target_commit,
                        prepare_only=True,
                    )
                except GitWorkspaceError as error:
                    if error.code not in {
                        "target_changed_before_integration",
                        "ff_only_not_possible",
                    }:
                        raise
                    released = self.authority.transition(
                        work_item_id,
                        "release_external_effect",
                        {"reason": error.code},
                        expected_version=int(current["version"]),
                    )
                    return {
                        "work_item": released,
                        "steps": ["integration_claim_released"],
                    }
                if integration["outcome"] == "prepared":
                    try:
                        mechanical_paths = self._mechanical_authority_paths(
                            current
                        )
                        self._require_implementation_candidate_snapshot(
                            current,
                            project_dir=repository_root,
                            comparison_base_ref=expected_target_commit,
                            exclude_paths=mechanical_paths,
                        )
                        self._require_completed_slice_snapshots(
                            current,
                            project_dir=repository_root,
                            exclude_paths=mechanical_paths,
                        )
                        actual_result = current["data"].get("actual_result")
                        assessment = current["data"]["engineering"].get(
                            "assessment"
                        )
                        with self._delivery_authority_checker(current) as checker:
                            checker.verify_working_tree_candidate_snapshot(
                                (
                                    actual_result
                                    if isinstance(actual_result, Mapping)
                                    else {}
                                ),
                                investigation_ref=(
                                    str(assessment.get("investigation_ref") or "")
                                    if isinstance(assessment, Mapping)
                                    else ""
                                ),
                            )
                        integration = workspace.commit_prepared_integration(
                            area,
                            expected_result_commits=recorded_commits,
                            expected_target_commit=expected_target_commit,
                        )
                    except (
                        GitWorkspaceError,
                        ProjectAuthorityConsistencyError,
                        VerificationRunnerError,
                    ):
                        workspace.abort_prepared_integration(
                            area,
                            expected_result_tip=recorded_commits[-1],
                            expected_target_commit=expected_target_commit,
                        )
                        self.authority.transition(
                            work_item_id,
                            "release_external_effect",
                            {
                                "reason": (
                                    "integration_candidate_changed_before_commit"
                                )
                            },
                            expected_version=int(current["version"]),
                        )
                        raise
            if integration["outcome"] == "integrated":
                mechanical_paths = self._mechanical_authority_paths(current)
                conflict_resolution = area.get("conflict_resolution")
                conflict_candidate = bool(
                    isinstance(conflict_resolution, Mapping)
                    and isinstance(
                        conflict_resolution.get(
                            "implementation_candidate_snapshot"
                        ),
                        Mapping,
                    )
                )
                confirmation = current["data"].get(
                    "actual_result_confirmation"
                )
                conflict_result_reconfirmed = bool(
                    current["status"] == "integration_conflict"
                    and isinstance(conflict_resolution, Mapping)
                    and isinstance(confirmation, Mapping)
                    and confirmation.get("accepted") is True
                    and confirmation.get("confirmed_at")
                    != conflict_resolution.get("confirmation_at_decision")
                )
                self._require_implementation_candidate_snapshot(
                    current,
                    project_dir=repository_root,
                    observed_ref=str(integration["integrated_commit"]),
                    comparison_base_ref=str(
                        integration.get("contribution_base_commit")
                        or area["base_commit"]
                    ),
                    exclude_paths=mechanical_paths,
                    use_conflict_resolution=conflict_candidate,
                )
                if not conflict_candidate and not conflict_result_reconfirmed:
                    self._require_completed_slice_snapshots(
                        current,
                        project_dir=repository_root,
                        observed_ref=str(integration["integrated_commit"]),
                        exclude_paths=mechanical_paths,
                    )
                actual_result = current["data"].get("actual_result")
                with self._delivery_authority_checker(current, str(integration["integrated_commit"])) as checker:
                    proof = checker.verify_integrated_candidate_snapshot(
                        (
                            actual_result
                            if isinstance(actual_result, Mapping)
                            else {}
                        ),
                        integrated_commit=str(integration["integrated_commit"]),
                        repository_id=current["data"].get("selected_repository_id"),
                        confirmed_on=str(
                            (
                                current["data"].get("actual_result_confirmation")
                                or {}
                            ).get("confirmed_at")
                            or ""
                        )[:10]
                        or None,
                    )
                integration = {
                    **integration,
                    "authority_candidate_snapshot_verification": proof,
                }
                snapshot = (area.get("conflict_resolution") or {}).get("implementation_candidate_snapshot") if conflict_candidate else (actual_result or {}).get("implementation_candidate_snapshot")
                if isinstance(snapshot, Mapping) and snapshot.get("schema_version") == "strixnova.project-implementation-snapshot.v1":
                    snapshot = next((entry for entry in snapshot["repositories"] if entry["repository_id"] == current["data"].get("selected_repository_id")), None)
                if isinstance(snapshot, Mapping):
                    # Record the immutable output after checking its correspondence
                    # to the accepted input, including authorized metadata changes.
                    delivered = deepcopy(snapshot)
                    delivered["paths"] = ImplementationCandidateEvidence(repository_root).path_snapshot([entry["path"] for entry in snapshot["paths"]], observed_ref=integration["integrated_commit"])
                    delivered["comparison_base_commit"] = integration.get("contribution_base_commit") or area["base_commit"]
                    delivered["changed_paths"] = self._workspace(current).changed_paths_between(delivered["comparison_base_commit"], integration["integrated_commit"])
                    integration["implementation_content_snapshot"] = delivered
            current = self.authority.transition(
                work_item_id,
                "record_local_integration",
                {
                    "outcome": integration["outcome"],
                    "integration": integration,
                    "blockers": (
                        ["git_conflict"]
                        if integration["outcome"] == "conflict"
                        else []
                    ),
                },
                expected_version=int(current["version"]),
            )
            steps.append(
                "integration_conflict"
                if integration["outcome"] == "conflict"
                else "locally_integrated"
            )
            if current["status"] == "integration_conflict":
                return {"work_item": current, "steps": steps}

        if current["status"] == "cleanup_required":
            current = self._claim_external_effect(
                current,
                kind="cleanup",
                intent={},
            )
            cleaned = workspace.cleanup(self._work_area(current))
            current = self.authority.transition(
                work_item_id,
                "record_cleanup",
                {"cleanup": cleaned},
                expected_version=int(current["version"]),
            )
            steps.append("work_area_cleaned")
        return {"work_item": current, "steps": steps}

    def _finalize_authority_adoption(
        self,
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> dict[str, Any] | None:
        work_item_id = str(current.get("work_item_id") or "")
        with self._effect_lock(work_item_id, "authority_adoption"):
            latest = self.authority.get(work_item_id)
            return self._finalize_authority_adoption_locked(
                latest,
                project_dir=project_dir,
            )

    def _finalize_authority_adoption_locked(
        self,
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> dict[str, Any] | None:
        """Apply and record the narrow metadata authorized by result acceptance.

        The exact two-file edit is persisted as an intent before either file is
        replaced.  Each replacement is atomic and the transaction is
        idempotent, so a restart can finish after either the alignment file or
        the baseline file was written without accepting any third state.
        """

        data = current.get("data")
        data = data if isinstance(data, Mapping) else {}
        stored_adoption = data.get("authority_adoption")
        stored_adoption_ready = bool(
            isinstance(stored_adoption, Mapping)
            and stored_adoption.get("schema_version")
            == "strixnova.authority-adoption.v1"
            and stored_adoption.get("ready_for_atomic_commits") is True
            and stored_adoption.get("accepted_candidate_snapshot_verified")
            is True
            and not list(stored_adoption.get("blocking_issues") or [])
        )
        pending_effect = data.get("pending_effect")
        recovering_adoption = bool(
            isinstance(pending_effect, Mapping)
            and pending_effect.get("kind") == "authority_adoption"
        )
        actual_result = data.get("actual_result")
        confirmation = data.get("actual_result_confirmation")
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
        confirmed_at = (
            str(confirmation.get("confirmed_at") or "")
            if isinstance(confirmation, Mapping)
            else ""
        )
        actual_result_value = (
            actual_result if isinstance(actual_result, Mapping) else {}
        )
        actual_result_confirmed = bool(
            isinstance(confirmation, Mapping)
            and confirmation.get("accepted") is True
        )
        snapshot = (
            actual_result.get("authority_candidate_snapshot")
            if isinstance(actual_result, Mapping)
            else None
        )
        intent_identity = {
            "actual_result_confirmation_fingerprint": str(
                confirmation.get("candidate_fingerprint") or ""
            )
            if isinstance(confirmation, Mapping)
            else "",
            "confirmed_at": confirmed_at,
            "candidate_baseline_sha256": str(
                snapshot.get("baseline_content_sha256") or ""
            )
            if isinstance(snapshot, Mapping)
            else "",
        }

        try:
            checker = ProjectAuthorityConsistency(project_dir)
            context = checker.baseline_reader.context
            metadata_roots = {entry.repository_id: entry.checkout_path for entry in context.repositories if entry.checkout_path is not None and entry.availability == "available"} if context is not None else {None: Path(project_dir)}
            for entry in current["data"].get("repository_deliveries") or []:
                area = entry.get("git") or {}
                if area.get("worktree_path"):
                    metadata_roots[entry["repository_id"]] = Path(self._execution_root_for_area(area, project_dir))
            metadata_roots[checker.reader.repository_id] = checker.project
            if stored_adoption_ready:
                record = checker.authority_adoption_record(
                    actual_result_value,
                    investigation_ref=investigation_ref,
                    actual_result_confirmed=actual_result_confirmed,
                    confirmed_on=confirmed_at[:10] or None,
                    mechanical_adoption_applied=True,
                )
                if (
                    record.get("ready_for_atomic_commits") is not True
                    or record.get("mechanical_adoption_final_state_verified")
                    is not True
                ):
                    raise ApplicationCoordinatorError(
                        "authority_adoption_not_finalized",
                        "已记录的实现对齐机械定档状态已发生变化",
                        details=record,
                    )
                return None

            if recovering_adoption:
                assert isinstance(pending_effect, Mapping)
                stored_intent = pending_effect.get("intent")
                if not isinstance(stored_intent, Mapping) or any(
                    stored_intent.get(field) != value
                    for field, value in intent_identity.items()
                ):
                    raise WorkflowAuthorityError(
                        "external_effect_intent_changed",
                        "待恢复实现对齐定档与已接受实际结果不一致",
                    )
                metadata_transaction = stored_intent.get(
                    "metadata_transaction"
                )
                if not isinstance(metadata_transaction, Mapping):
                    raise WorkflowAuthorityError(
                        "external_effect_intent_invalid",
                        "实现对齐定档恢复意图缺少精确元数据事务",
                    )
                adoption_intent = deepcopy(dict(stored_intent))
            else:
                planned_record = checker.authority_adoption_record(
                    actual_result_value,
                    investigation_ref=investigation_ref,
                    actual_result_confirmed=actual_result_confirmed,
                    confirmed_on=confirmed_at[:10] or None,
                    mechanical_adoption_applied=False,
                )
                if planned_record["blocking_issues"]:
                    raise ApplicationCoordinatorError(
                        "authority_adoption_not_finalized",
                        "已接受实际结果仍存在不能由程序代替的长期权威决定",
                        details=planned_record,
                    )
                if planned_record["required"] is not True:
                    return None
                updates = list(planned_record["authority_updates"])
                if any(
                    update.get("authority_kind")
                    != "implementation_alignment"
                    for update in updates
                ):
                    raise ApplicationCoordinatorError(
                        "authority_adoption_scope_invalid",
                        "普通实际结果只能机械采用实现对齐，不能确认其他长期权威",
                        details=planned_record,
                    )
                patch_updates: dict[
                    str,
                    dict[tuple[str | int, ...], Any],
                ] = {}
                baseline_path = str(planned_record.get("baseline_path") or "")
                baseline_key = (planned_record.get("baseline_repository_id"), baseline_path)
                for update in updates:
                    path = str(update.get("path") or "")
                    path_key = (update.get("repository_id"), path)
                    revision_fields = update.get("set_revision_fields")
                    if isinstance(revision_fields, Mapping):
                        target_updates = patch_updates.setdefault(path_key, {})
                        for field, value in revision_fields.items():
                            target_updates[("revision", str(field))] = value
                    baseline_fields = update.get("set_baseline_ref_fields")
                    if isinstance(baseline_fields, Mapping):
                        target_updates = patch_updates.setdefault(
                            baseline_key,
                            {},
                        )
                        target_updates[
                            (
                                "authority_refs",
                                "implementation_alignment",
                                "revision_id",
                            )
                        ] = baseline_fields.get("revision_id")
                        status = baseline_fields.get("status")
                        if isinstance(status, Mapping):
                            target_updates[
                                (
                                    "authority_refs",
                                    "implementation_alignment",
                                    "status",
                                    "revision_status",
                                )
                            ] = status.get("revision_status")
                            target_updates[
                                (
                                    "authority_refs",
                                    "implementation_alignment",
                                    "status",
                                    "adoption_status",
                                )
                            ] = status.get("adoption_status")
                baseline_update = planned_record.get("baseline_update")
                if isinstance(baseline_update, Mapping):
                    review_state = baseline_update.get("set_review_state")
                    if isinstance(review_state, Mapping):
                        target_updates = patch_updates.setdefault(
                            baseline_key,
                            {},
                        )
                        for field, value in review_state.items():
                            target_updates[("review_state", str(field))] = value
                metadata_transaction = build_yaml_patch_transaction(
                    project_dir,
                    patch_updates,
                    repository_roots=metadata_roots,
                )
                adoption_intent = {
                    **intent_identity,
                    "metadata_transaction": metadata_transaction,
                }
            current = self._claim_external_effect(
                current,
                kind="authority_adoption",
                intent=adoption_intent,
            )
            changed_originals: dict[Path, bytes] = {}
            try:
                changed_originals = apply_yaml_patch_transaction(
                    project_dir,
                    metadata_transaction,
                    repository_roots=metadata_roots,
                )
                record = ProjectAuthorityConsistency(
                    project_dir
                ).authority_adoption_record(
                    actual_result_value,
                    investigation_ref=investigation_ref,
                    actual_result_confirmed=actual_result_confirmed,
                    confirmed_on=confirmed_at[:10] or None,
                    mechanical_adoption_applied=True,
                )
                if (
                    record["blocking_issues"]
                    or record["ready_for_atomic_commits"] is not True
                    or record.get("mechanical_adoption_final_state_verified")
                    is not True
                ):
                    raise ProjectAuthorityConsistencyError(
                        ["实现对齐机械定档后仍未达到提交条件"]
                    )
                latest_data = current.get("data")
                latest_data = (
                    latest_data if isinstance(latest_data, Mapping) else {}
                )
                existing = latest_data.get("authority_adoption")
                if isinstance(existing, Mapping) and dict(existing) == record:
                    return None
                return self.authority.transition(
                    str(current["work_item_id"]),
                    "record_authority_adoption",
                    {"authority_adoption": record},
                    expected_version=int(current["version"]),
                )
            except Exception:
                restore_yaml_patch_originals(project_dir, metadata_transaction, changed_originals)
                raise
        except ApplicationCoordinatorError:
            raise
        except (
            ProjectAuthorityConsistencyError,
            ProjectEngineeringBaselineError,
            ProjectImplementationAlignmentError,
            YamlMetadataPatchError,
        ) as error:
            raise ApplicationCoordinatorError(
                "authority_adoption_write_failed",
                "实现对齐机械定档未能形成可恢复的一致权威链",
                details=getattr(error, "issues", [str(error)]),
            ) from error

    def _recover_pending_verification(self, current: Mapping[str, Any], request: Mapping[str, Any]) -> dict[str, Any]:
        pending = current["data"]["pending_effect"]
        intent = pending["intent"]
        unsettled = [entry for entry in ProjectMaintenance(self.management_project).unclosed_operations() if entry["state"] == "interrupted"]
        if unsettled:
            raise VerificationRunnerError("verification_execution_unclosed", "先通过原维护入口核验并收口未结束操作，再恢复验证回执", details=unsettled)
        if request.get("mode") != "run" or request.get("command_id") != intent["approved_request"]["command"]["command_id"]:
            raise VerificationRunnerError("verification_recovery_required", "必须先接收原命令的执行结果，不能覆盖当前执行意图")
        runner = VerificationRunner(self.management_project, artifact_root=self.management_project / '.strixnova/artifacts')
        receipt = runner.recover_receipt(intent["approved_request"], intent["receipt_id"])
        if receipt.get("execution_evidence_unavailable") is True:
            receipt["started_at"] = intent["started_at"]
            receipt["repository_id"] = pending.get("repository_id")
            receipt["project_input_snapshot"] = intent["project_input_snapshot"]
        if receipt.get("repository_id") != pending.get("repository_id") or receipt.get("project_input_snapshot") != intent["project_input_snapshot"]:
            raise VerificationRunnerError("verification_recovery_binding_changed", "恢复回执不属于原仓库内容输入")
        updated = self.report_verification(current["work_item_id"], receipt, expected_version=current["version"], execution_area=intent["execution_area"])
        return {"work_item": updated, "verification": receipt, "coverage": VerificationRunner.coverage_status(self._verification_commands(current), updated["data"]["verifications"], work_item_id=current["work_item_id"]), "recovered_execution": True}

    @_public_use_case
    def verify(
        self,
        work_item_id: str,
        request: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Run, record, or assess one command from the approved plan."""

        try:
            command_id = required_text(request.get("command_id"), "command_id")
            execution_area = closed_enum(
                request.get("execution_area", "worktree"),
                "execution_area",
                {"worktree", "target"},
            )
            mode = closed_enum(
                request.get("mode"),
                "mode",
                {"run", "not_run", "assess"},
            )
        except _InputValueError as error:
            raise ApplicationCoordinatorError(
                "invalid_verification_request",
                str(error),
            ) from error
        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"exploring", "implementing", "integration_conflict"},
            check_inputs=False,
        )
        if (current["data"].get("pending_effect") or {}).get("kind") == "verification":
            return self._recover_pending_verification(current, request)
        current = self._with_case_input_checks(current)
        if current.get("status") != "integration_conflict":
            self._require_current_work_item_direction_context(current)
        if current.get("status") == "implementing":
            binding = self._verification_work_area(current)
            self._require_current_slice_path_scope(
                current,
                project_dir=str(binding["worktree_path"]),
            )
            self._require_planned_upstream_authority_decisions(
                current,
                project_dir=str(binding["worktree_path"]),
            )
        commands = self._verification_commands(current)
        selected = next(
            (item for item in commands if item["command_id"] == command_id),
            None,
        )
        if selected is None:
            raise VerificationRunnerError(
                "verification_command_missing",
                f"工程方案不存在验证命令：{command_id}",
            )
        allowed_fields = {
            "run": {"command_id", "mode", "execution_area", "limitations"},
            "not_run": {
                "command_id",
                "mode",
                "execution_area",
                "not_run_reason",
                "limitations",
                "code_change_assessment",
            },
            "assess": {
                "command_id",
                "mode",
                "receipt_id",
                "code_change_assessment",
            },
        }[mode]
        extra = sorted(set(request) - allowed_fields)
        if extra:
            raise ApplicationCoordinatorError(
                "invalid_verification_request",
                "verify 输入包含未知字段：" + ", ".join(extra),
            )
        if current.get("status") != "implementing":
            self._require_current_slice_path_scope(
                current,
                project_dir=self.project,
            )
        if mode == "assess":
            try:
                receipt_id = required_text(
                    request.get("receipt_id"),
                    "receipt_id",
                )
            except _InputValueError as error:
                raise ApplicationCoordinatorError(
                    "invalid_verification_request",
                    str(error),
                ) from error
            matching = next(
                (
                    receipt
                    for receipt in current["data"].get("verifications") or []
                    if isinstance(receipt, Mapping)
                    and receipt.get("receipt_id") == receipt_id
                ),
                None,
            )
            if matching is None or matching.get("command_id") != command_id:
                raise VerificationRunnerError(
                    "verification_receipt_missing",
                    "待判断回执不存在或不属于所选命令",
                )
            assessment = request.get("code_change_assessment")
            if not isinstance(assessment, Mapping):
                raise ApplicationCoordinatorError(
                    "invalid_verification_request",
                    "code_change_assessment 必须是对象",
                )
            updated = self.assess_verification(
                work_item_id,
                receipt_id,
                assessment,
                expected_version=int(current["version"]),
            )
            coverage = VerificationRunner.coverage_status(
                commands,
                updated["data"]["verifications"],
                work_item_id=work_item_id,
                execution_root=None,
            )
            assessed = next(
                receipt
                for receipt in updated["data"]["verifications"]
                if receipt.get("receipt_id") == receipt_id
            )
            return {
                "work_item": updated,
                "verification": assessed,
                "coverage": coverage,
            }

        try:
            limitations = (
                []
                if request.get("limitations") is None
                else string_list(request.get("limitations"), "limitations")
            )
        except _InputValueError as error:
            raise ApplicationCoordinatorError(
                "invalid_verification_request",
                str(error),
            ) from error
        read_only_input = self._read_only_verification(current)
        area = None if current["status"] == "exploring" or read_only_input else self._work_area(current)
        conflict_item = self._conflict_item(current)
        git_value = conflict_item["data"].get("git")
        resolution = (
            git_value.get("conflict_resolution")
            if isinstance(git_value, Mapping)
            else None
        )
        conflict_resolved = isinstance(resolution, Mapping)
        if current["status"] == "exploring" and execution_area == "target":
            raise VerificationRunnerError(
                "target_verification_not_expected",
                "非正式调查没有 Git 目标工作树",
            )
        if current["status"] == "integration_conflict" and not conflict_resolved:
            raise VerificationRunnerError(
                "conflict_resolution_required",
                "必须先由 Agent 记录 Git 冲突解决判断，再运行受影响验证",
            )
        conflict_execution = conflict_resolved and conflict_item["data"].get("selected_repository_id") == current["data"].get("selected_repository_id")
        if conflict_execution and execution_area != "target":
            raise VerificationRunnerError(
                "target_verification_required",
                "Git 冲突解决后的验证必须在本地目标工作树执行",
            )
        if execution_area == "target" and not conflict_execution:
            raise VerificationRunnerError(
                "target_verification_not_expected",
                "只有 Git 冲突解决阶段可以在本地目标工作树验证",
            )
        runner = VerificationRunner(
            (
                self.management_project
                if read_only_input
                else
                self._repository_root(current)
                if execution_area == "target" or current["status"] == "exploring"
                else area["worktree_path"]
            ),
            artifact_root=self.management_project / ".strixnova" / "artifacts",
        )
        approved_request = self._approved_verification_request(
            current,
            selected,
        )
        plan_id = str(approved_request["plan_id"])
        input_snapshot = self._verification_input_snapshot(current, selected)
        if mode == "run":
            if "code_change_assessment" in request:
                raise VerificationRunnerError(
                    "assessment_must_follow_execution",
                    "run 输入不能预填验证后变化判断；命令完成后请用 assess 提交",
                )
            approved_request["work_item_version"] = int(current["version"]) + 1
            receipt_id = runner._receipt_id(work_item_id)
            current = self._claim_external_effect(current, kind="verification", intent={
                "approved_request": approved_request, "receipt_id": receipt_id,
                "project_input_snapshot": input_snapshot, "execution_area": "exploration" if current["status"] == "exploring" else execution_area,
                "started_at": datetime.now(timezone.utc).isoformat(),
            })
            if read_only_input:
                runner = VerificationRunner(self._materialize_verification_input(current, receipt_id), artifact_root=self.management_project / ".strixnova/artifacts")
            receipt = runner.run(
                approved_request,
                expected_work_item_id=work_item_id,
                expected_work_item_version=int(current["version"]),
                expected_plan_id=plan_id,
                limitations=limitations,
                receipt_id=receipt_id,
            )
        else:
            try:
                reason = required_text(
                    request.get("not_run_reason"),
                    "not_run_reason",
                )
            except _InputValueError as error:
                raise ApplicationCoordinatorError(
                    "invalid_verification_request",
                    str(error),
                ) from error
            receipt = runner.not_run(
                approved_request,
                expected_work_item_id=work_item_id,
                expected_work_item_version=int(current["version"]),
                expected_plan_id=plan_id,
                reason=reason,
                limitations=limitations,
                code_change_assessment=request.get("code_change_assessment"),
            )
        receipt["repository_id"] = selected.get("repository_id")
        receipt["project_input_snapshot"] = input_snapshot
        try:
            receipt["inputs_changed_during_execution"] = self._verification_input_snapshot(current, selected) != input_snapshot
            if read_only_input and mode == "run":
                expected = next(entry for entry in input_snapshot["repositories"] if entry["repository_id"] == selected.get("repository_id"))
                actual = capture_repository_content(selected.get("repository_id"), GitProjectReader(runner.execution_root), [entry["path"] for entry in expected["paths"]], canonical=False)
                receipt["inputs_changed_during_execution"] |= actual != expected
        except (GitProjectReaderError, ProjectContextError) as error:
            receipt["inputs_changed_during_execution"] = True
            receipt["limitations"].append("执行后无法重读完整输入：" + str(error))
        if mode == "run":
            runner.save_receipt(receipt)
        updated = self.report_verification(
            work_item_id,
            receipt,
            expected_version=int(current["version"]),
            execution_area=(
                "exploration"
                if current["status"] == "exploring"
                else execution_area
            ),
        )
        coverage = VerificationRunner.coverage_status(
            commands,
            updated["data"]["verifications"],
            work_item_id=work_item_id,
            execution_root=None,
        )
        return {
            "work_item": updated,
            "verification": receipt,
            "coverage": coverage,
        }

    @_public_use_case
    def plan_delivery_activity(
        self,
        work_item_id: str,
        plan: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Record an external-activity plan without pretending to execute it."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            set(WORK_ITEM_STATES)
            - {
                "discussion",
                "awaiting_direction_confirmation",
                "needs_engineering_assessment",
                "awaiting_plan_confirmation",
                "cancelled_changes_pending",
                "cancelled",
            },
        )
        if current.get("status") in DIRECTION_CONTEXT_RECOVERY_STATES:
            self._require_current_work_item_direction_context(current)
        engineering = current["data"].get("engineering")
        engineering_plan = (
            engineering.get("plan")
            if isinstance(engineering, Mapping)
            else None
        )
        confirmation = (
            engineering.get("plan_confirmation")
            if isinstance(engineering, Mapping)
            else None
        )
        if (
            not isinstance(engineering_plan, Mapping)
            or not isinstance(confirmation, Mapping)
            or confirmation.get("accepted") is not True
        ):
            raise DeliveryActivityError(
                "delivery_activity_plan_not_authorized",
                "交付运行活动计划必须绑定已接受的工程方案",
            )
        return DeliveryActivityAuthority(self.management_project).plan(
            plan,
            work_item_id=work_item_id,
            work_item_version=int(current["version"]),
            engineering_plan_id=str(engineering_plan["plan_id"]),
        )

    @_public_use_case
    def authorize_delivery_activity(
        self,
        activity_id: str,
        *,
        expected_activity_version: int,
        expected_work_item_version: int,
    ) -> dict[str, Any]:
        """Authorize only after the bound WorkItem result was accepted."""

        activity_authority = DeliveryActivityAuthority(self.management_project)
        activity = activity_authority.get(activity_id)
        work_item_id = str(activity["work_item_ref"]["work_item_id"])
        current = self._current_for_effect(
            work_item_id,
            expected_work_item_version,
            set(WORK_ITEM_STATES) - {"cancelled_changes_pending", "cancelled"},
        )
        confirmation = current["data"].get("actual_result_confirmation")
        if not isinstance(confirmation, Mapping) or confirmation.get(
            "accepted"
        ) is not True:
            raise DeliveryActivityError(
                "delivery_activity_not_authorized",
                "建设事项实际结果尚未由项目负责人接受",
            )
        return activity_authority.authorize(
            activity_id,
            expected_version=expected_activity_version,
            authorization_ref={
                "work_item_id": work_item_id,
                "work_item_version": int(current["version"]),
                "actual_result_accepted": True,
            },
        )

    @_public_use_case
    def record_delivery_activity_receipt(
        self,
        activity_id: str,
        receipt: Mapping[str, Any],
        *,
        expected_activity_version: int,
    ) -> dict[str, Any]:
        """Record one externally supplied fact; Strixnova executes nothing here."""

        authority = DeliveryActivityAuthority(self.management_project)
        activity = authority.get(activity_id)
        self.authority.get(str(activity["work_item_ref"]["work_item_id"]))
        return authority.record_external_receipt(
            activity_id,
            receipt,
            expected_version=expected_activity_version,
        )

    @_public_use_case
    def cancel_planned_delivery_activity(
        self,
        activity_id: str,
        *,
        expected_activity_version: int,
        canceled_by: str,
        reason: str,
    ) -> dict[str, Any]:
        """Cancel a never-authorized plan without fabricating an external receipt."""

        return DeliveryActivityAuthority(self.management_project).cancel_planned(
            activity_id,
            expected_version=expected_activity_version,
            canceled_by=canceled_by,
            reason=reason,
        )

    @staticmethod
    def _cancellation_repositories(current: Mapping[str, Any]) -> list[dict[str, Any]]:
        data = current["data"]
        return list(data.get("repository_deliveries") or [{"repository_id": data.get("selected_repository_id"), "git": data.get("git") or {}}])

    def _project_cancellation_state(self, current: Mapping[str, Any]) -> dict[str, Any]:
        states = []
        for entry in self._cancellation_repositories(current):
            area = entry.get("git") or {}
            if area.get("schema_version") != "strixnova.git-work-area.v1":
                continue
            if (area.get("cleanup") or {}).get("safe") is True:
                state = {"requires_user_decision": False, "already_integrated": bool((area.get("integration") or {}).get("integrated_commit")), "scope": "recorded_closed_work_area", "result_commits": list(area.get("result_commits") or [])}
            else:
                state = GitWorkspace(area["repository"]).cancellation_state(area)
            states.append({"repository_id": entry["repository_id"], "state": state})
        return {"schema_version": "strixnova.project-git-cancellation-state.v1", "repositories": states, "previous_integrations": previous_integrations(current["data"]), "requires_user_decision": any(entry["state"]["requires_user_decision"] for entry in states)}

    def _cleanup_cancellation_repositories(self, current: Mapping[str, Any], *, discard: bool = False) -> dict[str, Any]:
        for entry in self._cancellation_repositories(current):
            area = entry.get("git") or {}
            if area.get("schema_version") != "strixnova.git-work-area.v1" or (area.get("cleanup") or {}).get("safe") is True:
                continue
            workspace = GitWorkspace(area["repository"])
            if discard:
                cleanup = {**workspace.discard_cancelled_work(area, destructive_confirmed=True), "safe": True}
            else:
                state = workspace.cancellation_state(area)
                if state["requires_user_decision"]:
                    raise GitWorkspaceError("work_area_not_empty", "取消清理期间出现新工作，必须重新读取并处置")
                cleanup = workspace.cleanup(area) if state.get("already_integrated") and state.get("result_commits") else workspace.rollback_empty_work_area(area)
            with repository_operation(entry["repository_id"]):
                current = self.authority.transition(current["work_item_id"], "record_repository_cleanup", {"repository_id": entry["repository_id"], "cleanup": cleanup}, expected_version=current["version"])
        return current

    @_public_use_case
    def cancel(
        self,
        work_item_id: str,
        request: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Coordinate cancellation and any explicitly authorized cleanup."""

        if "decision" in request:
            allowed = {"decision", "details", "confirm_discard"}
            extra = sorted(set(request) - allowed)
            if extra:
                raise ApplicationCoordinatorError(
                    "invalid_cancel_request",
                    "取消决策包含未知字段：" + ", ".join(extra),
                )
            try:
                decision = closed_enum(
                    request.get("decision"),
                    "decision",
                    {"preserve", "transfer", "discard"},
                )
            except _InputValueError as error:
                raise ApplicationCoordinatorError(
                    "invalid_cancel_request",
                    str(error),
                ) from error
            details = request.get("details", {})
            if not isinstance(details, Mapping):
                raise ApplicationCoordinatorError(
                    "invalid_cancel_request",
                    "details 必须是对象",
                )
            confirm_discard = request.get("confirm_discard", False)
            if type(confirm_discard) is not bool:
                raise ApplicationCoordinatorError(
                    "invalid_cancel_request",
                    "confirm_discard 必须是布尔值",
                )
            current = self._current_for_effect(
                work_item_id,
                expected_version,
                {"cancelled_changes_pending"},
                check_inputs=False,
            )
            if decision == "discard":
                current = self._claim_external_effect(
                    current,
                    kind="cancel_discard",
                    intent={
                        "decision": "discard",
                        "details": dict(details),
                        "destructive_confirmed": confirm_discard,
                    },
                )
                current = self._cleanup_cancellation_repositories(current, discard=True)
            return self.authority.transition(
                work_item_id,
                "resolve_cancelled_work",
                {
                    "decision": decision,
                    "details": dict(details),
                    "destructive_confirmed": confirm_discard,
                },
                expected_version=int(current["version"]),
            )

        if set(request) != {"reason"}:
            raise ApplicationCoordinatorError(
                "invalid_cancel_request",
                "开始取消时 input 必须且只能包含 reason；待处理工作应提交 decision",
            )
        try:
            reason = required_text(request.get("reason"), "reason")
        except _InputValueError as error:
            raise ApplicationCoordinatorError(
                "invalid_cancel_request",
                str(error),
            ) from error
        current = self._current_for_effect(
            work_item_id,
            expected_version,
            set(WORK_ITEM_STATES - TERMINAL_STATES),
            check_inputs=False,
        )
        pending = current["data"].get("pending_effect")
        if isinstance(pending, Mapping) and pending.get("kind") == "prepare_work_area":
            if any(entry["state"] == "interrupted" for entry in ProjectMaintenance(self.management_project).unclosed_operations()):
                raise WorkflowAuthorityError("external_effect_in_progress", "先核验并收口原工作区建立进程，再取消该事项")
            with self._effect_lock(work_item_id, "prepare_work_area"):
                area = pending["intent"]["work_area"]
                cleanup = GitWorkspace(area["repository"]).rollback_empty_work_area(area)
                current = self.authority.transition(work_item_id, "release_external_effect", {"cleanup": cleanup}, expected_version=current["version"])
            pending = None
        if isinstance(pending, Mapping) and pending.get("kind") != "cancel_cleanup":
            raise WorkflowAuthorityError("external_effect_in_progress", "Settle the recorded external effect before cancellation")
        state = self._project_cancellation_state(current)
        has_unmerged_work = state["requires_user_decision"]
        cleanup = None
        if isinstance(pending, Mapping) or (state["repositories"] and not has_unmerged_work):
            intent = pending["intent"] if isinstance(pending, Mapping) else {"reason": reason, "has_unmerged_work": False, "git_state": state}
            current = self._claim_external_effect(current, kind="cancel_cleanup", intent=intent)
            try:
                current = self._cleanup_cancellation_repositories(current)
            except GitWorkspaceError:
                latest = self.authority.get(work_item_id)
                refreshed = self._project_cancellation_state(latest)
                if refreshed["requires_user_decision"]:
                    return self.authority.transition(work_item_id, "record_cancel_cleanup_blocked", {"git_state": refreshed}, expected_version=latest["version"])
                raise
            cleanup = {"safe": True, "repositories": [{"repository_id": entry["repository_id"], "cleanup": (entry.get("git") or {}).get("cleanup")} for entry in self._cancellation_repositories(current)]}
        return self.authority.transition(work_item_id, "cancel_work_item", {"reason": reason, "has_unmerged_work": has_unmerged_work, "git_state": state, "cleanup": cleanup}, expected_version=current["version"])

    @_public_use_case
    def submit_current_action_input(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Route caller-provided input by the deterministic current action."""

        current = self.authority.get(work_item_id)
        action = self.project_current_action(current)
        action_type = action["action_type"] if action is not None else None
        if value.get("schema_version") == REPLAN_REQUEST_SCHEMA:
            return self.request_replan(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        if action_type == "submit_direction":
            return self.submit_direction(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        if action_type == "revise_direction":
            return self.submit_direction(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        if action_type == "submit_engineering_assessment":
            return self.submit_engineering_assessment(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        if action_type == "revise_engineering_plan":
            if value.get("schema_version") == ASSESSMENT_SCHEMA:
                return self.submit_engineering_assessment(
                    work_item_id,
                    value,
                    expected_version=expected_version,
                )
            return self.submit_direction(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        if action_type == "resolve_git_conflict":
            expected_fields = {
                "user_visible_result_changed",
                "confirmed_direction_or_plan_changed",
                "reason",
                "retest_command_ids",
            }
            extra = sorted(set(value) - expected_fields)
            missing = sorted(expected_fields - set(value))
            if missing or extra:
                raise ApplicationCoordinatorError(
                    "invalid_conflict_resolution",
                    "冲突判断字段不完整"
                    + (f"；缺少 {', '.join(missing)}" if missing else "")
                    + (f"；未知 {', '.join(extra)}" if extra else ""),
                )
            command_ids = {
                command["command_id"]
                for command in self._verification_commands(current)
            }
            retest_ids = value.get("retest_command_ids")
            if (
                not isinstance(retest_ids, list)
                or any(
                    not isinstance(command_id, str)
                    or not command_id.strip()
                    for command_id in retest_ids
                )
                or len(set(retest_ids)) != len(retest_ids)
                or not set(retest_ids).issubset(command_ids)
            ):
                raise ApplicationCoordinatorError(
                    "invalid_conflict_resolution",
                    "retest_command_ids 只能列出工程方案中确实受冲突影响的命令；"
                    "没有适用命令时可以为空",
                )
            transition_value = dict(value)
            if not retest_ids:
                conflict_snapshot = self._conflict_candidate_snapshot(current)
                if conflict_snapshot is None:
                    raise ApplicationCoordinatorError(
                        "conflict_candidate_snapshot_missing",
                        "零验证命令的冲突解决仍必须绑定负责人已接受的完整文件快照",
                    )
                actual_result = current["data"].get("actual_result")
                engineering = current["data"].get("engineering")
                assessment = (
                    engineering.get("assessment")
                    if isinstance(engineering, Mapping)
                    else None
                )
                ProjectAuthorityConsistency(
                    self._repository_root(current)
                ).verify_working_tree_candidate_snapshot(
                    actual_result if isinstance(actual_result, Mapping) else {},
                    investigation_ref=(
                        str(assessment.get("investigation_ref") or "")
                        if isinstance(assessment, Mapping)
                        else ""
                    ),
                )
                transition_value["implementation_candidate_snapshot"] = (
                    conflict_snapshot
                )
            self.authority.transition(
                work_item_id,
                "record_conflict_resolution",
                transition_value,
                expected_version=expected_version,
            )
            return self.authority.get(work_item_id)
        if action_type == "assess_target_advance":
            expected_fields = {
                "schema_version",
                "semantic_impact",
                "reason",
            }
            if set(value) != expected_fields or value.get(
                "schema_version"
            ) != "strixnova.target-advance-assessment.v1":
                raise ApplicationCoordinatorError(
                    "invalid_target_advance_assessment",
                    "目标分支变化判断字段不完整或包含未知字段",
                )
            try:
                impact = closed_enum(
                    value.get("semantic_impact"),
                    "semantic_impact",
                    {"affected", "unaffected"},
                )
                reason = required_text(value.get("reason"), "reason")
            except _InputValueError as error:
                raise ApplicationCoordinatorError(
                    "invalid_target_advance_assessment",
                    str(error),
                ) from error
            git = current["data"].get("git")
            target_advance = (
                git.get("target_advance")
                if isinstance(git, Mapping)
                else None
            )
            mechanical_impact = bool(
                isinstance(target_advance, Mapping)
                and target_advance.get("authority_refs_changed") is True
            )
            if impact == "unaffected" and mechanical_impact:
                raise ApplicationCoordinatorError(
                    "target_advance_mechanically_affects_plan",
                    "目标分支已改变精确项目权威引用或本方案文件；不能声明为不受影响，必须重新规划",
                )
            if impact == "affected":
                self.authority.transition(
                    work_item_id,
                    "request_replan",
                    {"reasons": [reason]},
                    expected_version=expected_version,
                )
            else:
                self.authority.transition(
                    work_item_id,
                    "record_target_advance_assessment",
                    {"assessment": dict(value)},
                    expected_version=expected_version,
                )
            return self.authority.get(work_item_id)
        if action_type == "complete_implementation_slice":
            return self.complete_implementation_slice(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        if action_type in {"begin_implementation", "implement_and_verify"}:
            return self.request_replan(
                work_item_id,
                value,
                expected_version=expected_version,
            )
        raise ApplicationCoordinatorError(
            "current_action_input_not_expected",
            f"当前动作 {action_type or '<none>'} 不接收通用提交输入",
        )

    @_public_use_case
    def complete_implementation_slice(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Record explicit completion for a slice with no verification command."""

        expected_fields = {
            "schema_version",
            "slice_id",
            "completion_summary",
            "semantic_content_machine_proven",
        }
        if set(value) != expected_fields or value.get(
            "schema_version"
        ) != "strixnova.implementation-slice-completion.v1":
            raise ApplicationCoordinatorError(
                "implementation_slice_completion_invalid",
                "无验证命令切片的完成记录字段不完整或包含未知字段",
            )
        try:
            slice_id = required_text(value.get("slice_id"), "slice_id")
            summary = required_text(
                value.get("completion_summary"),
                "completion_summary",
            )
        except _InputValueError as error:
            raise ApplicationCoordinatorError(
                "implementation_slice_completion_invalid",
                str(error),
            ) from error
        if value.get("semantic_content_machine_proven") is not False:
            raise ApplicationCoordinatorError(
                "implementation_slice_completion_invalid",
                "semantic_content_machine_proven 必须明确为 false",
            )
        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"implementing"},
        )
        self._require_current_work_item_direction_context(current)
        binding = self._workspace(current).require_work_area_binding(
            self._work_area(current)
        )
        data = current.get("data")
        engineering = data.get("engineering") if isinstance(data, Mapping) else None
        plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
        if not isinstance(plan, Mapping):
            raise ApplicationCoordinatorError(
                "implementation_slice_plan_missing",
                "当前建设事项没有可执行工程方案",
            )
        receipts = data.get("verifications") if isinstance(data, Mapping) else []
        completions = (
            data.get("implementation_slice_completions")
            if isinstance(data, Mapping)
            else []
        )
        current_slice = focused_slice(
            plan,
            receipts if isinstance(receipts, list) else [],
            completions if isinstance(completions, list) else [],
        )
        if not isinstance(current_slice, Mapping) or current_slice.get(
            "slice_id"
        ) != slice_id:
            raise ApplicationCoordinatorError(
                "implementation_slice_not_ready",
                "完成记录不属于当前可执行实施切片",
            )
        if current_slice.get("verification_command_ids"):
            raise ApplicationCoordinatorError(
                "implementation_slice_verification_required",
                "当前实施切片已经分配验证命令，必须取得真实回执",
            )
        self._require_current_slice_path_scope(
            current,
            project_dir=str(binding["worktree_path"]),
        )
        self._require_planned_upstream_authority_decisions(
            current,
            project_dir=str(binding["worktree_path"]),
        )
        operation_results = self._require_slice_operations_realized(
            current,
            plan,
            current_slice,
            project_dir=str(binding["worktree_path"]),
        )
        completion = {
            "schema_version": "strixnova.implementation-slice-completion.v1",
            "slice_id": slice_id,
            "completion_summary": summary,
            "evidence_kind": "explicit_no_command",
            "source_receipt_ids": [],
            "operation_results": operation_results,
            "owned_path_snapshot": self._slice_content_snapshot(current, plan, current_slice, project_dir=str(binding["worktree_path"])),
            "semantic_content_machine_proven": False,
        }
        self.authority.transition(
            work_item_id,
            "complete_implementation_slice",
            {"completion": completion},
            expected_version=expected_version,
        )
        return self.authority.get(work_item_id)

    @_public_use_case
    def request_replan(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        allowed = {"schema_version", "reasons"}
        missing = sorted(allowed - set(value))
        extra = sorted(set(value) - allowed)
        if missing or extra or value.get("schema_version") != REPLAN_REQUEST_SCHEMA:
            raise ApplicationCoordinatorError(
                "invalid_replan_request",
                "重新评估请求必须只包含有效 schema_version 和 reasons",
            )
        reasons = value.get("reasons")
        if (
            not isinstance(reasons, list)
            or not reasons
            or any(not isinstance(reason, str) or not reason.strip() for reason in reasons)
        ):
            raise ApplicationCoordinatorError(
                "invalid_replan_request",
                "重新评估请求必须给出至少一个具体原因",
            )
        self.authority.transition(
            work_item_id,
            "request_replan",
            {"reasons": [reason.strip() for reason in reasons]},
            expected_version=expected_version,
        )
        return self.authority.get(work_item_id)

    @_public_use_case
    def submit_direction(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        current = self.authority.get(work_item_id)
        invalidation_issues = self._direction_context_invalidation_issues(current)
        if value.get("ready_for_confirmation") is True:
            direction = value.get("direction")
            if not isinstance(direction, Mapping):
                raise ApplicationCoordinatorError(
                    "direction_context_invalid",
                    "可确认方向必须包含完整 direction 对象",
                )
            self._require_current_direction_context(direction)
        action = "submit_direction"
        payload = dict(value)
        if invalidation_issues and current.get("status") != "discussion":
            action = "revise_direction"
            payload["invalidation_issues"] = invalidation_issues
        self.authority.transition(
            work_item_id,
            action,
            payload,
            expected_version=expected_version,
        )
        return self.authority.get(work_item_id)

    @_public_use_case
    def submit_engineering_assessment(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        current = self.authority.get(work_item_id)
        direction = current["data"].get("direction")
        confirmation = current["data"].get("direction_confirmation")
        if (
            not isinstance(direction, Mapping)
            or not isinstance(confirmation, Mapping)
            or confirmation.get("accepted") is not True
            or type(confirmation.get("direction_version")) is not int
        ):
            raise EngineeringGovernanceError(
                ["工程评估必须引用当前已确认方向"]
            )
        direction_version = int(confirmation["direction_version"])
        self._require_current_direction_context(direction)
        profile, project_context = self._governance_context(value)
        assessment = validate_assessment(
            value,
            project_dir=self.project,
            candidate_context=project_context["candidate_context"],
            work_item_id=work_item_id,
            direction=direction,
            direction_version=direction_version,
            profile=profile,
            known_baseline_refs=project_context["baseline_refs"],
            domain_model_id=project_context["domain_model_id"],
            known_domain_fact_locations=project_context[
                "domain_fact_locations"
            ],
            known_authority_artifacts=project_context.get(
                "authority_artifacts"
            ),
        )
        self._require_reconsidered_guardrails_planned(direction, assessment)
        self._require_planned_source_alignment(assessment)
        # Cross-authority invalidation is computed by the dedicated checker.
        # The adapter does not reinterpret changed paths as semantic alignment
        # decisions; the application use case will bind any required review.
        current_git = current["data"].get("git")
        if (
            assessment["change_context"]["formal_implementation"] is False
            and isinstance(current_git, Mapping)
            and current_git.get("work_ref")
        ):
            raise EngineeringGovernanceError(
                [
                    "已有 Git 工作区的 WorkItem 不能改成 A0 非交付事项；"
                    "不再交付时必须走取消后的保留、转移或丢弃闭环"
                ]
            )
        previous = current["data"]["engineering"].get("assessment")
        if isinstance(previous, Mapping):
            if (
                assessment["assessment_id"] != previous.get("assessment_id")
                or assessment["assessment_revision"]
                <= int(previous.get("assessment_revision") or 0)
            ):
                raise EngineeringGovernanceError(
                    ["修订评估必须保留 assessment_id 并增加 assessment_revision"]
                )
        elif assessment["assessment_revision"] != 1:
            raise EngineeringGovernanceError(
                ["首个评估的 assessment_revision 必须为 1"]
            )
        plan = compile_engineering_plan(
            assessment,
            project_dir=self.project,
            candidate_context=project_context["candidate_context"],
            direction=direction,
            direction_version=direction_version,
            profile=profile,
            known_baseline_refs=project_context["baseline_refs"],
            domain_model_id=project_context["domain_model_id"],
            known_domain_fact_locations=project_context[
                "domain_fact_locations"
            ],
            known_authority_artifacts=project_context.get(
                "authority_artifacts"
            ),
            work_item_id=work_item_id,
        )
        self.authority.transition(
            work_item_id,
            "submit_engineering_assessment",
            {"assessment": assessment, "plan": plan},
            expected_version=expected_version,
        )
        return self.authority.get(work_item_id)

    @_public_use_case
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
        actions = {
            "direction": "confirm_direction",
            "engineering_plan": "confirm_engineering_plan",
            "actual_result": "confirm_actual_result",
        }
        action = actions.get(kind)
        if action is None:
            raise ApplicationCoordinatorError(
                "invalid_confirmation_kind",
                f"未知确认类型：{kind}",
            )
        current = self.authority.get(work_item_id)
        if kind == "actual_result":
            plan = current["data"]["engineering"].get("plan")
        current_action = self.project_current_action(current)
        if (
            not isinstance(current_action, Mapping)
            or current_action.get("action_type") != action
        ):
            raise ApplicationCoordinatorError(
                "confirmation_not_expected",
                "当前候选卡不接受该确认",
            )
        challenge = current_action.get("confirmation_challenge")
        if not isinstance(challenge, Mapping):
            raise ApplicationCoordinatorError(
                "confirmation_challenge_missing",
                "当前确认动作缺少候选卡口令",
            )
        payload = {
            "candidate_fingerprint": candidate_fingerprint,
            "user_confirmation": user_confirmation,
            "agent_decision": agent_decision,
        }
        try:
            decision = confirmation_record_from_input(challenge, payload)
        except ConfirmationProtocolError as error:
            raise ApplicationCoordinatorError(error.code, str(error)) from error
        accepted = bool(decision["accepted"])
        if accepted and kind == "engineering_plan":
            self._require_planned_source_alignment(
                current["data"]["engineering"].get("assessment") or {}
            )
            scope = (current["data"]["engineering"].get("plan") or {}).get("repository_scope")
            if scope is not None and self.project_context is not None:
                if scope["project_id"] not in {None, self.project_context.project_id}:
                    raise ApplicationCoordinatorError("work_item_project_mismatch", "方案项目归属已经改变")
                for entry in scope["repositories"]:
                    if entry["repository_id"] is not None:
                        self.project_context.repository(entry["repository_id"], for_modification=entry["role"] == "modify")
        if accepted and kind in {
            "direction",
            "engineering_plan",
            "actual_result",
        }:
            data = current.get("data")
            data = data if isinstance(data, Mapping) else {}
            direction = data.get("direction")
            if not isinstance(direction, Mapping):
                raise ApplicationCoordinatorError(
                    "direction_context_invalid",
                    "当前确认缺少完整方向决定上下文",
                )
            self._require_current_direction_context(direction)
        if kind == "actual_result" and accepted:
            self._require_project_result_content(current, before_acceptance=True)
            data = current.get("data")
            data = data if isinstance(data, Mapping) else {}
            actual_result = data.get("actual_result")
            if not isinstance(actual_result, Mapping):
                raise ApplicationCoordinatorError(
                    "actual_result_missing",
                    "当前实际结果不存在，不能确认",
                )
            git = current["data"].get("git")
            if isinstance(git, Mapping):
                resolution = git.get("conflict_resolution")
                snapshot_root = (
                    self._repository_root(current)
                    if isinstance(resolution, Mapping)
                    else str(git.get("worktree_path") or self._repository_root(current))
                )
                self._require_implementation_candidate_snapshot(
                    current,
                    project_dir=snapshot_root,
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
            ProjectAuthorityConsistency(
                snapshot_root if isinstance(git, Mapping) else self.project
            ).verify_working_tree_candidate_snapshot(
                actual_result,
                investigation_ref=investigation_ref,
            )
            if isinstance(git, Mapping):
                resolution = git.get("conflict_resolution")
                if isinstance(resolution, Mapping):
                    try:
                        self._workspace(current).integration_result(dict(git))
                    except GitWorkspaceError as error:
                        if error.code != "integration_not_complete":
                            raise
                    else:
                        raise ApplicationCoordinatorError(
                            "premature_conflict_merge_commit",
                            "冲突后的实际结果确认前不得完成 merge commit；"
                            "请按项目 Git 策略恢复正确交付顺序",
                        )
            if isinstance(git, Mapping) and not list(
                git.get("result_commits") or []
            ):
                worktree_path = str(git.get("worktree_path") or "").strip()
                base_commit = str(git.get("base_commit") or "").strip()
                work_ref = str(git.get("work_ref") or "").strip()
                if worktree_path and base_commit and work_ref:
                    commits = self._workspace(current).result_commits(
                        dict(git),
                        require_clean=False,
                    )
                    if commits:
                        raise ApplicationCoordinatorError(
                            "premature_result_commit",
                            "实际结果确认前不得形成实现提交；请恢复为未提交实现后再确认",
                        )
        self.authority.transition(
            work_item_id,
            action,
            payload,
            expected_version=expected_version,
        )
        return self.authority.get(work_item_id)

    @_public_use_case
    def report_verification(
        self,
        work_item_id: str,
        receipt: Mapping[str, Any],
        *,
        expected_version: int,
        execution_area: str,
    ) -> dict[str, Any]:
        current = self.authority.get(work_item_id)
        pending_verification = (current["data"].get("pending_effect") or {}).get("kind") == "verification"
        if not pending_verification:
            if current.get("status") != "integration_conflict":
                self._require_current_work_item_direction_context(current)
            if execution_area not in {"worktree", "target", "exploration"}:
                raise VerificationRunnerError(
                    "invalid_execution_area",
                    "execution_area 必须是 worktree、target 或 exploration",
                )
            conflict_current = self._conflict_item(current)
            git = conflict_current["data"].get("git")
            resolution = git.get("conflict_resolution") if isinstance(git, Mapping) else None
            if current["status"] == "integration_conflict" and not isinstance(
                resolution, Mapping
            ):
                raise VerificationRunnerError(
                    "conflict_resolution_required",
                    "必须先由 Agent 记录 Git 冲突解决判断，再运行受影响验证",
                )
            expected_area = (
                "exploration"
                if current["status"] == "exploring"
                else "target"
                if isinstance(resolution, Mapping) and conflict_current["data"].get("selected_repository_id") == current["data"].get("selected_repository_id")
                else "worktree"
            )
            if execution_area != expected_area:
                raise VerificationRunnerError(
                    "verification_execution_area_mismatch",
                    f"当前验证必须在 {expected_area} 执行",
                )
            if current.get("status") == "implementing":
                binding = self._verification_work_area(current)
                self._require_current_slice_path_scope(
                    current,
                    project_dir=str(binding["worktree_path"]),
                )
                self._require_planned_upstream_authority_decisions(
                    current,
                    project_dir=str(binding["worktree_path"]),
                )
                data = current["data"]
                plan = data["engineering"]["plan"]
                focused = focused_slice(
                    plan,
                    list(data.get("verifications") or []),
                    list(data.get("implementation_slice_completions") or []),
                )
                if (
                    not isinstance(focused, Mapping)
                    or receipt.get("command_id")
                    not in set(focused.get("verification_command_ids") or [])
                ):
                    raise VerificationRunnerError(
                        "implementation_slice_verification_not_ready",
                        "验证回执不属于当前可执行实施切片",
                    )
        commands = self._verification_commands(current)
        receipts = [
            *list(current["data"].get("verifications") or []),
            dict(receipt),
        ]
        VerificationRunner.coverage_status(
            commands,
            receipts,
            work_item_id=work_item_id,
            execution_root=None,
        )
        if receipt.get("result") != "not_run" and receipt.get("execution_evidence_unavailable") is not True:
            safe_work_item_id = "".join(
                character
                if character.isalnum() or character in "._-"
                else "-"
                for character in work_item_id
            ).strip("-")
            artifact_root = (
                self.management_project / ".strixnova" / "artifacts" / safe_work_item_id
            ).resolve()
            raw_refs = receipt.get("raw_output_refs")
            assert isinstance(raw_refs, Mapping)
            for name in ("stdout", "stderr"):
                path = Path(str(raw_refs[name])).expanduser().resolve()
                if (
                    (path != artifact_root and artifact_root not in path.parents)
                    or not path.is_file()
                ):
                    raise VerificationRunnerError(
                        "verification_output_missing",
                        f"验证原始输出不存在或不属于当前项目：{name}",
                    )
        self.authority.transition(
            work_item_id,
            "record_verification",
            {
                "verification": dict(receipt),
                "output_evidence": capture_outputs(
                    self.management_project, work_item_id, receipt,
                    observation_kind="execution", observed_at=datetime.now(timezone.utc).isoformat(),
                ),
            },
            expected_version=expected_version,
        )
        return self.authority.get(work_item_id)

    @_public_use_case
    def assess_verification(
        self,
        work_item_id: str,
        receipt_id: str,
        code_change_assessment: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> dict[str, Any]:
        """Record the Agent's post-execution change judgment."""

        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"exploring", "implementing", "integration_conflict"},
        )
        if current.get("status") != "integration_conflict":
            self._require_current_work_item_direction_context(current)
        receipts = list(current["data"].get("verifications") or [])
        slice_completion: dict[str, Any] | None = None
        binding: Mapping[str, Any] | None = None
        focused: Mapping[str, Any] | None = None
        selected = next(
            (
                receipt
                for receipt in receipts
                if isinstance(receipt, Mapping)
                and receipt.get("receipt_id") == receipt_id
            ),
            None,
        )
        if selected is None:
            raise VerificationRunnerError(
                "verification_receipt_missing",
                f"当前 WorkItem 不存在验证回执：{receipt_id}",
            )
        if current.get("status") == "implementing":
            binding = self._verification_work_area(current)
            self._require_current_slice_path_scope(
                current,
                project_dir=str(binding["worktree_path"]),
            )
            self._require_planned_upstream_authority_decisions(
                current,
                project_dir=str(binding["worktree_path"]),
            )
            data = current["data"]
            focused = focused_slice(
                data["engineering"]["plan"],
                list(data.get("verifications") or []),
                list(data.get("implementation_slice_completions") or []),
            )
            if (
                not isinstance(focused, Mapping)
                or selected.get("command_id")
                not in set(focused.get("verification_command_ids") or [])
            ):
                raise VerificationRunnerError(
                    "implementation_slice_verification_not_ready",
                    "待评估回执不属于当前可执行实施切片",
                )
        assessed = VerificationRunner.assess_receipt(
            selected,
            code_change_assessment,
        )
        updated_receipts = [
            assessed
            if isinstance(receipt, Mapping)
            and receipt.get("receipt_id") == receipt_id
            else dict(receipt)
            for receipt in receipts
        ]
        VerificationRunner.coverage_status(
            self._verification_commands(current),
            updated_receipts,
            work_item_id=work_item_id,
            execution_root=None,
        )
        if (
            current.get("status") == "implementing"
            and isinstance(binding, Mapping)
            and isinstance(focused, Mapping)
        ):
            command_ids = list(focused.get("verification_command_ids") or [])
            latest = {
                str(receipt.get("command_id") or ""): receipt
                for receipt in updated_receipts
                if isinstance(receipt, Mapping)
            }
            if command_ids and all(
                command_id in latest
                and latest[command_id].get("result") == "passed"
                and latest[command_id].get("_case_input_stale") is not True
                and isinstance(
                    latest[command_id].get("code_change_assessment"),
                    Mapping,
                )
                and latest[command_id]["code_change_assessment"].get(
                    "needs_retest"
                )
                is False
                for command_id in command_ids
            ):
                operation_results = self._require_slice_operations_realized(
                    current,
                    current["data"]["engineering"]["plan"],
                    focused,
                    project_dir=str(binding["worktree_path"]),
                )
                slice_completion = {
                    "schema_version": "strixnova.implementation-slice-completion.v1",
                    "slice_id": str(focused["slice_id"]),
                    "completion_summary": (
                        "切片全部计划验证命令已取得通过且无需重测的当前回执。"
                    ),
                    "evidence_kind": "verified_commands",
                    "source_receipt_ids": [
                        str(latest[command_id]["receipt_id"])
                        for command_id in command_ids
                    ],
                    "operation_results": operation_results,
                    "owned_path_snapshot": self._slice_content_snapshot(current, current["data"]["engineering"]["plan"], focused, project_dir=str(binding["worktree_path"])),
                    "semantic_content_machine_proven": False,
                }
        transition_payload: dict[str, Any] = {
            "receipt_id": receipt_id,
            "code_change_assessment": assessed[
                "code_change_assessment"
            ],
        }
        if slice_completion is not None:
            transition_payload["implementation_slice_completion"] = (
                slice_completion
            )
        conflict_current = self._conflict_item(current)
        git = conflict_current["data"].get("git")
        resolution = (
            git.get("conflict_resolution")
            if isinstance(git, Mapping)
            else None
        )
        if isinstance(resolution, Mapping) and current["status"] == "integration_conflict":
            required_ids = set(resolution.get("retest_command_ids") or [])
            previous_ids = set(
                resolution.get("receipt_ids_at_decision") or []
            )
            latest = {
                str(value.get("command_id") or ""): value
                for value in updated_receipts
                if isinstance(value, Mapping)
                and value.get("receipt_id") not in previous_ids
                and value.get("command_id") in required_ids
            }
            if required_ids and all(
                command_id in latest
                and latest[command_id].get("result") == "passed"
                and isinstance(
                    latest[command_id].get("code_change_assessment"),
                    Mapping,
                )
                and latest[command_id]["code_change_assessment"].get(
                    "needs_retest"
                )
                is False
                for command_id in required_ids
            ):
                conflict_snapshot = self._conflict_candidate_snapshot(conflict_current)
                if conflict_snapshot is not None:
                    transition_payload[
                        "conflict_candidate_snapshot"
                    ] = conflict_snapshot
        with repository_operation(conflict_current["data"].get("selected_repository_id") if isinstance(resolution, Mapping) else current["data"].get("selected_repository_id")):
            self.authority.transition(work_item_id, "assess_verification", transition_payload, expected_version=expected_version)
        return self.authority.get(work_item_id)

    @_public_use_case
    def check_actual_result(
        self,
        work_item_id: str,
        value: Mapping[str, Any],
        *,
        expected_version: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        current = self._current_for_effect(
            work_item_id,
            expected_version,
            {"exploring", "implementing", "integration_conflict"},
        )
        if current.get("status") != "integration_conflict":
            self._require_current_work_item_direction_context(current)
        plan = current["data"]["engineering"]["plan"]
        commands = self._verification_commands(current)
        coverage = VerificationRunner.coverage_status(
            commands,
            list(current["data"].get("verifications") or []),
            work_item_id=work_item_id,
            execution_root=None,
        )
        git = current["data"].get("git")
        worktree = (
            git.get("worktree_path") if isinstance(git, Mapping) else None
        )
        if current.get("status") == "exploring":
            worktree = self.project
        resolution = git.get("conflict_resolution") if isinstance(git, Mapping) else None
        result_root = (
            self._repository_root(current)
            if isinstance(resolution, Mapping)
            else worktree
        )
        actual_paths: set[str] = set()
        if (
            current.get("status") == "implementing"
            and isinstance(git, Mapping)
            and git.get("schema_version") == "strixnova.git-work-area.v1"
        ):
            binding = self._workspace(current).require_work_area_binding(
                dict(git)
            )
            self._require_current_slice_path_scope(
                current,
                project_dir=str(binding["worktree_path"]),
            )
            self._require_planned_upstream_authority_decisions(
                current,
                project_dir=str(binding["worktree_path"]),
            )
            reportability = implementation_slice_reportability(
                plan,
                list(current["data"].get("verifications") or []),
                list(
                    current["data"].get(
                        "implementation_slice_completions"
                    )
                    or []
                ),
            )
            if not reportability["reportable"]:
                raise VerificationRunnerError(
                    "implementation_slices_incomplete",
                    "仍有实施切片缺少当前验证评估或显式完成记录",
                )
            coverage = implementation_reporting_coverage(
                plan,
                list(current["data"].get("verifications") or []),
                list(
                    current["data"].get(
                        "implementation_slice_completions"
                    )
                    or []
                ),
                coverage,
            )
            planned_paths = {
                str(path).replace("\\", "/")
                for item in list(
                    plan.get("operations")
                    or []
                )
                for path in (
                    item.get("path"),
                    item.get("to_path"),
                )
                if path
            }
            actual_paths = set(self._repository_changed_paths(current))
            unplanned_paths = sorted(actual_paths - planned_paths)
            if unplanned_paths:
                raise VerificationRunnerError(
                    "unplanned_repository_change",
                    "实际 Git 改动超出已确认工程操作；误改应恢复，必要改动必须先提交重新规划请求",
                    details=unplanned_paths,
                )
        planned_semantic_reviews = [entry["review"] for entry in current_semantic_reviews(current)]
        subject = self._review_subject(current)
        actual_result = validate_actual_result(
            value,
            coverage,
            project_dir=result_root,
            repository_readers=self._result_readers(current),
            planned_operations=plan.get("operations") or [],
            planned_method_applications=list(
                current["data"]["engineering"]["assessment"].get(
                    "method_applications"
                )
                or []
            ),
            planned_domain_fact_changes=list(
                current["data"]["engineering"]["assessment"].get(
                    "domain_fact_changes"
                )
                or []
            ),
            planned_governance_rules=list(
                current["data"]["engineering"]["plan"].get(
                    "applicable_rules"
                )
                or []
            ),
            planned_semantic_reviews=planned_semantic_reviews,
            planned_verification_targets=plan.get("verification_targets"),
            planned_follow_up_refs=declared_refs(current["data"].get("direction") or {}),
            expected_review_subject_ref=subject["subject_ref"],
        )
        if current.get("status") in {"implementing", "integration_conflict"}:
            implementation_snapshot = self._implementation_candidate_snapshot(
                current,
                project_dir=result_root,
            )
            if implementation_snapshot is not None:
                actual_result["implementation_candidate_snapshot"] = (
                    implementation_snapshot
                )
        self._validate_long_lived_trace(
            current,
            actual_result,
            project_dir=result_root,
        )
        self._validate_domain_change_results(
            current,
            actual_result,
            project_dir=result_root,
            actual_changed_paths=sorted(actual_paths),
        )
        authority_checker = ProjectAuthorityConsistency(result_root)
        investigation_ref = str(
            current["data"]["engineering"]["assessment"].get(
                "investigation_ref"
            )
            or ""
        )
        prior_adoption = self._prior_authority_adoption(current)
        authority_snapshot = authority_checker.authority_candidate_snapshot(
            actual_result,
            investigation_ref=investigation_ref,
            **({"prior_adoption": prior_adoption} if prior_adoption is not None else {}),
        )
        if authority_snapshot["required"]:
            if "implementation_alignment" in set(
                authority_snapshot.get("changed_authority_kinds") or []
            ):
                candidate_authorities = (
                    authority_checker.load_working_tree_candidate_for(
                        investigation_ref
                    )
                )
                validate_authority_change_targets(
                    Path(result_root),
                    current,
                    "implementation_alignment",
                    candidate_authorities["implementation_alignment"],
                )
            self._require_upstream_authority_decisions(
                current,
                authority_snapshot,
                project_dir=result_root,
            )
            actual_result["authority_candidate_snapshot"] = authority_snapshot
        if self._review_subject(current)["subject_ref"] != subject["subject_ref"]:
            raise ActualResultError("review_subject_changed", "实际结果核对期间审阅对象发生变化，请重新读取并复核")
        actual_result["review_subject"] = subject
        return actual_result, coverage

    @_public_use_case
    def present_actual_result(
        self, work_item_id: str, value: Mapping[str, Any], *, expected_version: int,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        actual_result, coverage = self.check_actual_result(work_item_id, value, expected_version=expected_version)
        self.authority.transition(work_item_id, "present_actual_result", {"actual_result": actual_result}, expected_version=expected_version)
        return self.authority.get(work_item_id), coverage

    def _prior_authority_adoption(self, current: Mapping[str, Any]) -> dict[str, Any] | None:
        """Read original successful adoption facts, bounded by this item version."""
        data = current["data"]
        if not data.get("superseded_deliveries") and not (data.get("git") or {}).get("conflict_resolution") and not any((entry.get("git") or {}).get("integration") for entry in data.get("repository_deliveries") or []):
            return None
        events = [event for event in self.authority.history(current["work_item_id"]) if event["version"] <= current["version"]]
        for index in range(len(events) - 1, -1, -1):
            event = events[index]
            if event["event_type"] != "record_authority_adoption":
                continue
            record = event["payload"].get("authority_adoption") or {}
            if not (record.get("accepted_candidate_snapshot_verified") is True and record.get("mechanical_adoption_final_state_verified") is True):
                continue
            claim = next((value for value in reversed(events[:index]) if value["event_type"] == "claim_external_effect" and value["payload"].get("kind") == "authority_adoption"), None)
            if claim is None:
                continue
            result = next((value["payload"].get("actual_result") for value in reversed(events[:index]) if value["event_type"] == "present_actual_result"), None)
            intent = claim["payload"].get("intent") or {}
            if result is not None and (result.get("authority_candidate_snapshot") or {}).get("baseline_content_sha256") == intent.get("candidate_baseline_sha256") and intent.get("confirmed_at"):
                return {"actual_result": result, "confirmed_on": intent["confirmed_at"][:10], "adoption_event_sequence": event["sequence"]}
        return None

    @staticmethod
    def _require_upstream_authority_decisions(
        current: Mapping[str, Any],
        authority_snapshot: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> None:
        required_kinds = set(
            authority_snapshot.get("changed_authority_kinds") or []
        ).intersection(PROJECT_AUTHORITY_KINDS)
        if not required_kinds:
            return
        data = current.get("data")
        records = (
            data.get("project_authority_decisions")
            if isinstance(data, Mapping)
            else []
        )
        records = records if isinstance(records, list) else []
        issues: list[str] = []
        for kind in sorted(required_kinds):
            matching = [
                record
                for record in reversed(records)
                if isinstance(record, Mapping)
                and record.get("authority_kind") == kind
                and isinstance(record.get("confirmation"), Mapping)
                and record["confirmation"].get("accepted") is True
            ]
            if not matching:
                issues.append(f"{kind} 缺少独立项目负责人接受记录")
                continue
            last_error: ProjectAuthorityDecisionError | None = None
            for record in matching:
                try:
                    validate_project_authority_decision(
                        project_dir,
                        current,
                        record,
                    )
                except ProjectAuthorityDecisionError as error:
                    last_error = error
                    continue
                break
            else:
                issues.append(
                    f"{kind} 的负责人接受记录不再绑定当前精确正文："
                    + str(last_error or "未知错误")
                )
        if issues:
            raise VerificationRunnerError(
                "project_authority_decision_missing",
                "变化的上游长期权威必须先通过独立负责人决定完成确认",
                details=issues,
            )

    @staticmethod
    def _require_planned_upstream_authority_decisions(current: Mapping[str, Any], *, project_dir: str | Path) -> None:
        entries = current["data"].get("repository_deliveries") or []
        if not entries:
            ApplicationCoordinator._require_planned_upstream_authority_decisions_in_repository(current, project_dir=project_dir)
            return
        for entry in entries:
            area = entry.get("git") or {}
            if (area.get("cleanup") or {}).get("safe"):
                continue
            ApplicationCoordinator._require_planned_upstream_authority_decisions_in_repository(repository_item(current, entry["repository_id"]), project_dir=ApplicationCoordinator._execution_root_for_area(area, project_dir))

    @staticmethod
    def _require_planned_upstream_authority_decisions_in_repository(
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> None:
        """Close the authority-first order before any implementation proof."""
        if not (current["data"].get("git") or {}).get("work_ref"):
            entry = next((entry for entry in current["data"].get("repository_deliveries") or [] if (entry.get("git") or {}).get("worktree_path") == str(project_dir)), None)
            if entry is not None:
                current = repository_item(current, entry["repository_id"])
        data = current.get("data")
        engineering = (
            data.get("engineering") if isinstance(data, Mapping) else None
        )
        plan = (
            engineering.get("plan")
            if isinstance(engineering, Mapping)
            else None
        )
        required_kinds = planned_upstream_authority_kinds(
            current,
            current_progress_only=False,
        )
        if required_kinds:
            ApplicationCoordinator._require_upstream_authority_decisions(
                current,
                {"changed_authority_kinds": required_kinds},
                project_dir=project_dir,
            )

        if not isinstance(plan, Mapping):
            return
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
        active_paths = set(scope["permitted_paths"])
        active_operations = [
            operation
            for operation in plan.get("operations") or []
            if isinstance(operation, Mapping)
            and any(
                str(operation.get(field) or "").replace("\\", "/")
                in active_paths
                for field in ("path", "to_path")
            )
        ]
        alignment_active = any(
            isinstance(operation.get("long_lived_artifact"), Mapping)
            and operation["long_lived_artifact"].get("artifact_type")
            == "domain_alignment"
            for operation in active_operations
        )
        records = data.get("project_authority_decisions") if isinstance(data, Mapping) else []
        governed_paths = {
            str(path).replace("\\", "/")
            for record in records or []
            if isinstance(record, Mapping)
            and isinstance(record.get("confirmation"), Mapping)
            and record["confirmation"].get("accepted") is True
            and isinstance(record.get("candidate"), Mapping)
            for path in record["candidate"].get("governed_paths") or []
        }
        change_context = plan.get("change_context")
        if isinstance(change_context, Mapping):
            governed_paths.update(
                str(path).replace("\\", "/")
                for key, path in change_context.items()
                if str(key).endswith("_path") and str(path).strip()
            )
        governed_paths.update(
            str(operation.get("path") or "").replace("\\", "/")
            for operation in active_operations
            if isinstance(operation.get("long_lived_artifact"), Mapping)
            and operation["long_lived_artifact"].get("artifact_type")
            not in {"domain_alignment"}
        )
        work_area = ApplicationCoordinator._work_area(current)
        actual_paths = set(
            ApplicationCoordinator._repository_changed_paths(current)
        )
        business_started = bool(actual_paths - governed_paths)
        chain_required = bool(
            alignment_active
            or business_started
            or (not required_kinds and actual_paths)
        )
        if not chain_required:
            return

        all_required_kinds = planned_upstream_authority_kinds(
            current,
            current_progress_only=False,
        )
        if all_required_kinds:
            ApplicationCoordinator._require_upstream_authority_decisions(
                current,
                {"changed_authority_kinds": all_required_kinds},
                project_dir=project_dir,
            )
        assessment = engineering.get("assessment")
        investigation_ref = (
            str(assessment.get("investigation_ref") or "")
            if isinstance(assessment, Mapping)
            else ""
        )
        try:
            ProjectAuthorityConsistency(
                project_dir
            ).load_working_tree_candidate_for(investigation_ref)
        except ProjectAuthorityConsistencyError as error:
            raise VerificationRunnerError(
                "project_authority_chain_invalid",
                "进入业务实施前，产品、领域、架构、政策和实现对齐必须形成完整一致的候选链",
                details=error.issues,
            ) from error

    @staticmethod
    def _require_authority_confirmation_path_scope(current: Mapping[str, Any], *, project_dir: str | Path) -> None:
        entries = current["data"].get("repository_deliveries") or []
        if not entries:
            ApplicationCoordinator._require_authority_confirmation_path_scope_in_repository(current, project_dir=project_dir)
            return
        for entry in entries:
            area = entry.get("git") or {}
            if (area.get("cleanup") or {}).get("safe"):
                continue
            ApplicationCoordinator._require_authority_confirmation_path_scope_in_repository(repository_item(current, entry["repository_id"]), project_dir=ApplicationCoordinator._execution_root_for_area(area, project_dir))

    @staticmethod
    def _require_authority_confirmation_path_scope_in_repository(
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> None:
        """Reject an owner decision requested after business work has started."""

        work_area = ApplicationCoordinator._work_area(current)
        worktree = str(work_area["worktree_path"])
        allowed = set(planned_project_authority_paths(worktree, current))
        actual = set(
            ApplicationCoordinator._repository_changed_paths(current)
        )
        data = current.get("data")
        engineering = data.get("engineering") if isinstance(data, Mapping) else None
        plan = engineering.get("plan") if isinstance(engineering, Mapping) else None
        planned_paths = {
            str(operation.get(field) or "").replace("\\", "/")
            for operation in (
                (plan.get("operations") or [])
                if isinstance(plan, Mapping)
                else []
            )
            if isinstance(operation, Mapping)
            for field in ("path", "to_path")
            if str(operation.get(field) or "").strip()
        }
        unplanned_paths = sorted(actual - planned_paths)
        if unplanned_paths:
            raise VerificationRunnerError(
                "unplanned_repository_change",
                "长期权威候选包含工程方案未声明的持久文件改动；"
                "请恢复这些改动或先重新规划",
                details=unplanned_paths,
            )
        business_paths = sorted(actual - allowed)
        if business_paths:
            raise VerificationRunnerError(
                "project_authority_decision_too_late",
                "上游长期权威必须在业务实现开始前独立确认；"
                "请先恢复业务改动再确认候选",
                details=business_paths,
            )

    @staticmethod
    def _working_tree_candidate_authorities(
        project_dir: str | Path,
        *,
        investigation_ref: str,
    ) -> tuple[ProjectAuthorityConsistency, dict[str, Any]]:
        """Load one candidate chain against the investigation-time authority base."""

        checker = ProjectAuthorityConsistency(project_dir)
        return checker, checker.load_working_tree_candidate_for(investigation_ref)

    @staticmethod
    def _validate_long_lived_trace(
        current: Mapping[str, Any],
        actual_result: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> None:
        engineering = current["data"]["engineering"]
        assessment = engineering["assessment"]
        plan = engineering["plan"]
        operations = list(plan.get("operations") or [])
        realized_operation_refs: set[str] | None = None
        slices = [
            item
            for item in plan.get("implementation_slices") or []
            if isinstance(item, Mapping)
        ]
        reportability: Mapping[str, Any] = {}
        if slices:
            receipts = list(current["data"].get("verifications") or [])
            completions = list(
                current["data"].get("implementation_slice_completions") or []
            )
            reportability = implementation_slice_reportability(
                plan,
                receipts,
                completions,
            )
            realized_operation_refs = {
                str(result.get("operation_ref") or "")
                for completion in completions
                if isinstance(completion, Mapping)
                for result in completion.get("operation_results") or []
                if isinstance(result, Mapping) and result.get("realized") is True
            }
            terminal_slice_id = str(
                reportability.get("terminal_slice_id") or ""
            )
            terminal_slice = next(
                (
                    item
                    for item in slices
                    if str(item.get("slice_id") or "") == terminal_slice_id
                ),
                None,
            )
            if isinstance(terminal_slice, Mapping):
                realized_operation_refs.update(
                    str(result.get("operation_ref") or "")
                    for result in ApplicationCoordinator._slice_operation_realization(
                        current,
                        plan,
                        terminal_slice,
                        project_dir=project_dir,
                    )
                    if result.get("realized") is True
                )
        planned_paths: set[str] = set()
        planned_actions: dict[str, str] = {}
        planned_long_lived: dict[tuple[str, str, str], str] = {}
        expected_adrs: dict[tuple[str, str], str] = {}
        for index, operation in enumerate(operations):
            if (
                realized_operation_refs is not None
                and f"operations[{index}]" not in realized_operation_refs
            ):
                continue
            action = str(operation.get("action") or "")
            if operation.get("path"):
                path = str(operation["path"])
                key = repository_path_key(operation.get("repository_id"), path)
                planned_paths.add(key)
                planned_actions[key] = action
            if operation.get("to_path"):
                destination = str(operation["to_path"])
                key = repository_path_key(operation.get("repository_id"), destination)
                planned_paths.add(key)
                planned_actions[key] = "move"
            long_lived = operation.get("long_lived_artifact")
            if isinstance(long_lived, Mapping):
                artifact_path = str(
                    operation.get("to_path")
                    if action == "move"
                    else operation.get("path")
                )
                identity = (
                    str(long_lived.get("artifact_id") or ""),
                    str(long_lived.get("artifact_type") or ""),
                    repository_path_key(operation.get("repository_id"), artifact_path),
                )
                planned_long_lived[identity] = action
        for adr in list(assessment.get("adr_plans") or []):
            if adr.get("disposition") in {"create", "update"}:
                identity = (str(adr["artifact_id"]), repository_path_key(adr.get("repository_id"), str(adr["path"])))
                if any(
                    artifact_id == identity[0] and path == identity[1]
                    for artifact_id, _, path in planned_long_lived
                ):
                    expected_adrs[identity] = str(adr["disposition"])
        actual = list(actual_result.get("long_lived_refs") or [])
        actual_changes = {
            (
                str(item["artifact_id"]),
                str(item["artifact_type"]),
                repository_path_key(item.get("repository_id"), str(item["path"])),
            )
            for item in actual
        }
        missing_planned = sorted(set(planned_long_lived) - actual_changes)
        if missing_planned:
            raise VerificationRunnerError(
                "long_lived_trace_missing",
                "已计划的长期工程文件没有出现在实际结果中",
                details=["/".join([item[0], item[1], item[2].removeprefix("_:")]) for item in missing_planned],
            )
        change_context = assessment.get("change_context") or {}
        if (
            change_context.get("change_kind") == "create_project"
            and reportability.get("reason") != "terminal_slice_issue"
        ):
            expected_baseline_path = str(
                change_context.get("project_engineering_baseline_path") or ""
            )
            project_root = Path(project_dir).expanduser().resolve()
            config_path = project_root / "strixnova-project.yaml"
            if not config_path.is_file():
                raise VerificationRunnerError(
                    "project_config_result_missing",
                    "新项目实际结果缺少 strixnova-project.yaml",
                )
            try:
                located = ProjectEngineeringBaseline(project_root).locate()
                relative = located.relative_to(project_root).as_posix()
            except (ProjectEngineeringBaselineError, ValueError) as error:
                raise VerificationRunnerError(
                    "project_config_result_invalid",
                    "新项目配置不能定位首个工程基线",
                    details=(
                        error.issues
                        if isinstance(error, ProjectEngineeringBaselineError)
                        else [str(error)]
                    ),
                ) from error
            if relative != expected_baseline_path:
                raise VerificationRunnerError(
                    "project_config_result_mismatch",
                    "新项目配置定位的工程基线与已确认候选不一致",
                )
            expected_authorities = {
                "product_governance": str(
                    change_context.get("project_product_definition_path") or ""
                ),
                "domain_model": str(
                    change_context.get("project_domain_model_path") or ""
                ),
                "architecture": str(
                    change_context.get("project_architecture_description_path")
                    or ""
                ),
                "quality_policy": str(
                    change_context.get("project_engineering_policy_path") or ""
                ),
                "domain_alignment": str(
                    change_context.get("project_implementation_alignment_path")
                    or ""
                ),
            }
            missing_authorities = sorted(
                f"{artifact_type}:{path}:relation=introduced"
                for artifact_type, path in expected_authorities.items()
                if not any(
                    item.get("artifact_type") == artifact_type
                    and str(item.get("path") or "") == path
                    and item.get("relation") == "introduced"
                    for item in actual
                )
            )
            if missing_authorities:
                raise VerificationRunnerError(
                    "project_authority_result_missing",
                    "新项目实际结果必须以 introduced 关系包含五类独立项目权威",
                    details=missing_authorities,
                )
        actual_adrs = {
            (str(item["artifact_id"]), repository_path_key(item.get("repository_id"), str(item["path"])))
            for item in actual
            if item.get("artifact_type") == "adr"
        }
        missing = sorted(set(expected_adrs) - actual_adrs)
        if missing:
            raise VerificationRunnerError(
                "long_lived_trace_missing",
                "已计划的 ADR 没有出现在实际结果中",
                details=missing,
            )
        unexpected_paths = sorted(
            str(item["path"])
            for item in actual
            if repository_path_key(item.get("repository_id"), str(item["path"])) not in planned_paths
        )
        if unexpected_paths:
            raise VerificationRunnerError(
                "long_lived_change_unplanned",
                "长期工程文件没有对应的计划操作",
                details=unexpected_paths,
            )
        invalid_relations: list[str] = []
        for item in actual:
            relation = str(item.get("relation") or "")
            path = str(item.get("path") or "")
            key = repository_path_key(item.get("repository_id"), path)
            action = planned_actions.get(key)
            allowed = {
                "create": {"introduced"},
                "modify": {"updated", "realized"},
                "move": {"updated"},
                "delete": {"removed"},
            }.get(action, set())
            if relation not in allowed:
                invalid_relations.append(f"{path}:{action}->{relation}")
            if item.get("artifact_type") == "adr":
                disposition = expected_adrs.get(
                    (str(item.get("artifact_id") or ""), key)
                )
                adr_allowed = {
                    "create": {"introduced"},
                    "update": {"updated", "realized"},
                }.get(disposition, set())
                if relation not in adr_allowed:
                    invalid_relations.append(
                        f"{item.get('artifact_id')}:{disposition}->{relation}"
                    )
        if invalid_relations:
            raise VerificationRunnerError(
                "long_lived_relation_mismatch",
                "长期工程文件的实际关系与已确认操作不一致",
                details=sorted(set(invalid_relations)),
            )
        # A normal WorkItem with no planned or reported long-lived artifact
        # has no changed authority chain to reconcile. Requiring a baseline here
        # would turn A0 and ordinary source-only changes into implicit project
        # initialization work. New projects and every reported long-lived
        # change still pass through the full checks below.
        if not actual and change_context.get("change_kind") != "create_project":
            return
        try:
            ApplicationCoordinator._working_tree_candidate_authorities(
                project_dir,
                investigation_ref=str(assessment.get("investigation_ref") or ""),
            )
        except (
            ProjectEngineeringBaselineError,
            ProjectAuthorityConsistencyError,
        ) as error:
            raise VerificationRunnerError(
                "long_lived_artifact_invalid",
                "长期工程产物没有形成一致的项目权威链",
                details=getattr(error, "issues", [str(error)]),
            ) from error

    def _require_planned_source_alignment(
        self, assessment: Mapping[str, Any],
    ) -> None:
        """Apply the adopted path scope before presenting or accepting a plan.

        This is the same recorded behavior scope used at actual-result time.
        It does not infer domain meaning or decide how source maps to modules.
        Existing assessment validators own artifact identity and slice coverage.
        """
        context = assessment.get("change_context") or {}
        if context.get("formal_implementation") is not True or context.get("change_kind") == "create_project":
            return
        reference = assessment.get("investigation_ref")
        if not isinstance(reference, str) or not reference or reference == "working_tree":
            return  # Immutable investigation requirements are checked separately.
        baseline = ProjectEngineeringBaseline(self.project, observed_ref=reference)
        if not baseline.engineering_baseline_exists():
            return  # First-adoption requirements remain with their existing validator.
        authorities = ProjectAuthorityConsistency(self.project, observed_ref=reference).load()
        alignment = authorities["implementation_alignment"]
        alignment_repository = authorities.get("authority_content_refs", {}).get(
            "implementation_alignment", {}
        ).get("repository_id")
        if alignment_repository is not None:
            # An omitted repository belongs to the authority's own repository,
            # not every member that happens to contain the same relative path.
            for field in ("source_ownership", "governed_source_scopes"):
                for record in alignment.get(field, []):
                    if record.get("repository_id") is None:
                        record["repository_id"] = alignment_repository
        operations = assessment.get("operations") or []
        affected = sorted({
            str(operation.get("repository_id") or "") + ":" + str(operation[field])
            for operation in operations
            for field in ("path", "to_path")
            if field in operation
            and ProjectImplementationAlignment.is_behavior_path(
                alignment, str(operation[field]), repository_id=operation.get("repository_id")
            )
        })
        if affected and not any(
            (operation.get("long_lived_artifact") or {}).get("artifact_type") == "domain_alignment"
            and operation.get("action") in {"create", "modify", "move"}
            for operation in operations
        ):
            raise EngineeringGovernanceError([
                "计划改动命中已采用实现对齐的受管源码范围：" + ", ".join(affected),
                "必须规划实现对齐更新，并按现有合同安排根文件、四份底账和工程基线；"
                "业务含义或模块职责未变不代表旧源码观察仍匹配。",
            ])

    @staticmethod
    def _validate_domain_change_results(
        current: Mapping[str, Any],
        actual_result: Mapping[str, Any],
        *,
        project_dir: str | Path,
        actual_changed_paths: Sequence[str] = (),
    ) -> None:
        """Check declared domain lifecycle results against exact before/after facts."""

        assessment = current["data"]["engineering"]["assessment"]
        planned_changes = [
            change
            for change in assessment.get("domain_fact_changes") or []
            if isinstance(change, Mapping)
        ]
        planned_alignment_review = any(
            isinstance(operation, Mapping)
            and isinstance(operation.get("long_lived_artifact"), Mapping)
            and operation["long_lived_artifact"].get("artifact_type")
            == "domain_alignment"
            and operation.get("action") in {"create", "modify", "move"}
            for operation in current["data"]["engineering"]["plan"].get(
                "operations"
            )
            or []
        )
        investigation_ref = str(assessment.get("investigation_ref") or "")
        prior_authorities: Mapping[str, Any] | None = None
        prior_checker: ProjectAuthorityConsistency | None = None
        # A changed ordinary source file does not prove a domain change.  A
        # changed path that the adopted authority chain explicitly owns as a
        # domain or alignment document is different: that classification is a
        # recorded path fact, so silently skipping it would bypass the plan.
        if not planned_changes and not planned_alignment_review:
            if not actual_changed_paths:
                return
            if not investigation_ref or investigation_ref == "working_tree":
                return
            try:
                prior_state = ProjectEngineeringBaseline(
                    project_dir,
                    observed_ref=investigation_ref,
                )
                if not prior_state.engineering_baseline_exists():
                    return
                prior_checker = ProjectAuthorityConsistency(
                    project_dir,
                    observed_ref=investigation_ref,
                )
                prior_authorities = prior_checker.load()
                prior_scope = prior_checker.invalidation_scope(
                    changed_paths=actual_changed_paths
                )
                direct_changes = set(
                    prior_scope["directly_changed_authority_kinds"]
                )
            except (
                ProjectEngineeringBaselineError,
                ProjectAuthorityConsistencyError,
            ) as error:
                details = getattr(error, "issues", [str(error)])
                raise VerificationRunnerError(
                    "domain_change_prior_authority_invalid",
                    "无法从调查提交重读变化前的项目权威链",
                    details=details,
                ) from error
            if not direct_changes.intersection(
                {"domain_model", "implementation_alignment"}
            ) and not prior_scope.get("changed_behavior_paths"):
                return

        try:
            checker, current_authorities = (
                ApplicationCoordinator._working_tree_candidate_authorities(
                    project_dir,
                    investigation_ref=investigation_ref,
                )
            )
        except (
            ProjectEngineeringBaselineError,
            ProjectAuthorityConsistencyError,
        ) as error:
            raise VerificationRunnerError(
                "domain_authority_result_invalid",
                "领域变化后的项目权威链无效",
                details=getattr(error, "issues", [str(error)]),
            ) from error

        if (
            prior_authorities is None
            and investigation_ref
            and investigation_ref != "working_tree"
        ):
            try:
                prior_checker = ProjectAuthorityConsistency(
                    project_dir,
                    observed_ref=investigation_ref,
                )
                prior_authorities = prior_checker.load()
            except ProjectAuthorityConsistencyError as error:
                if (
                    assessment.get("change_context", {}).get("change_kind")
                    != "create_project"
                ):
                    raise VerificationRunnerError(
                        "domain_change_prior_authority_invalid",
                        "无法从调查提交重读领域变化前的项目权威链",
                        details=error.issues,
                    ) from error
        elif planned_changes or planned_alignment_review:
            raise VerificationRunnerError(
                "domain_change_prior_commit_missing",
                "领域或实现对齐变化必须绑定可重读的调查提交",
            )
        if prior_authorities is None:
            return

        current_catalog = current_authorities["domain_catalog"]
        prior_catalog = prior_authorities["domain_catalog"]
        current_active = {
            str(item["fact_id"]): item for item in current_catalog["facts"]
        }
        current_retired = {
            str(item["fact_id"]): item
            for item in current_catalog["retired_facts"]
        }
        prior_active = {
            str(item["fact_id"]): item for item in prior_catalog["facts"]
        }
        prior_retired = {
            str(item["fact_id"]): item
            for item in prior_catalog["retired_facts"]
        }
        current_all = {**current_active, **current_retired}
        prior_all = {**prior_active, **prior_retired}

        realized: dict[str, str] = {}
        for change in planned_changes:
            target_ref = change.get("target_ref")
            if not isinstance(target_ref, Mapping):
                continue
            fact_id = str(target_ref.get("fact_id") or "")
            result = next(
                (
                    item
                    for item in actual_result.get(
                        "domain_fact_change_results", []
                    )
                    if isinstance(item, Mapping)
                    and item.get("target_ref", {}).get("fact_id") == fact_id
                ),
                None,
            )
            if isinstance(result, Mapping) and result.get("outcome") == "realized":
                realized[fact_id] = str(change.get("disposition") or "")

        observed: dict[str, str] = {}
        for fact_id in sorted(set(prior_all) | set(current_all)):
            if fact_id not in prior_all:
                observed[fact_id] = "add"
            elif fact_id not in current_all:
                observed[fact_id] = "remove"
            elif (
                fact_id in prior_active
                and fact_id in current_retired
            ):
                observed[fact_id] = "retire"
            elif prior_all[fact_id] != current_all[fact_id]:
                observed[fact_id] = "update"

        issues: list[str] = []
        for fact_id, disposition in observed.items():
            planned = realized.get(fact_id)
            if planned != disposition:
                issues.append(
                    f"领域事实发生未计划的 {disposition}：{fact_id}"
                )
        for fact_id, disposition in realized.items():
            if disposition == "retain":
                if fact_id not in current_all:
                    issues.append(f"领域事实声明保留但当前不存在：{fact_id}")
            elif observed.get(fact_id) != disposition:
                issues.append(
                    f"领域事实计划 {disposition} 但实际未形成对应变化：{fact_id}"
                )
            if fact_id in prior_retired and disposition != "retain":
                issues.append(f"领域事实已在调查版本退役：{fact_id}")

        def alignment_body(value: Mapping[str, Any]) -> dict[str, Any]:
            return {
                key: deepcopy(item)
                for key, item in value.items()
                if not str(key).startswith("_")
                and key != "semantic_content_machine_proven"
            }

        current_alignment = current_authorities["implementation_alignment"]
        prior_alignment = prior_authorities["implementation_alignment"]
        alignment_changed = alignment_body(current_alignment) != alignment_body(
            prior_alignment
        )
        if alignment_changed and not planned_alignment_review:
            issues.append(
                "实现对齐修订发生未计划变更："
                + str(current_alignment["alignment_model_id"])
            )
        scope = checker.invalidation_scope(
            changed_paths=actual_changed_paths
        )
        if (
            actual_changed_paths
            and "implementation_alignment"
            in scope["affected_authority_kinds"]
            and not alignment_changed
        ):
            issues.append("实际改动使实现对齐待复核，但当前实现对齐修订未更新")

        if issues:
            raise VerificationRunnerError(
                "domain_change_result_mismatch",
                "领域或实现对齐变化的实际结果与已确认计划不一致",
                details=sorted(set(issues)),
            )

    def _governance_context(
        self,
        assessment: Mapping[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Load the exact adopted policy and authority chain at investigation_ref."""

        base_profile = load_base_governance_profile()
        candidate_context = ProjectAuthorityConsistency(
            self.project
        ).engineering_candidate_context(assessment)
        change_context = assessment.get("change_context")
        if not isinstance(change_context, Mapping):
            raise EngineeringGovernanceError(["change_context 必须是对象"])
        try:
            change_kind = closed_enum(
                change_context.get("change_kind"),
                "change_context.change_kind",
                {
                    "modify_existing",
                    "add_capability",
                    "create_project",
                    "exploration",
                },
            )
            investigation_ref = required_text(
                assessment.get("investigation_ref"),
                "investigation_ref",
            )
        except _InputValueError as error:
            raise EngineeringGovernanceError([str(error)]) from error
        formal = change_context.get("formal_implementation") is True
        if formal and investigation_ref in {"", "working_tree"}:
            raise EngineeringGovernanceError(
                [
                    "正式工程评估必须用 investigation_ref 引用调查时的"
                    "不可变 Git 提交"
                ]
            )
        empty_context = {
            "baseline_refs": set(),
            "domain_model_id": None,
            "domain_fact_locations": {},
            "authority_artifacts": None,
            "candidate_context": candidate_context,
        }
        if not investigation_ref or investigation_ref == "working_tree":
            return base_profile, empty_context
        try:
            state_reader = ProjectEngineeringBaseline(
                self.project,
                observed_ref=investigation_ref,
            )
        except ProjectEngineeringBaselineError as error:
            raise EngineeringGovernanceError(error.issues) from error

        project_config_exists = state_reader.project_config_exists()
        engineering_baseline_exists = (
            state_reader.engineering_baseline_exists()
        )
        if change_kind == "create_project":
            if project_config_exists or engineering_baseline_exists:
                raise EngineeringGovernanceError(
                    [
                        "create_project 引用的 Git 提交已经存在项目配置或工程基线；"
                        "必须按既存项目评估"
                    ]
                )
            return base_profile, empty_context
        if not project_config_exists:
            if formal:
                raise ApplicationCoordinatorError(
                    "unadopted_project_requires_create_project",
                    "新项目第一次修改或交付仓库文件，必须先用 create_project "
                    "建立完整项目权威",
                    details={
                        "current_change_kind": change_kind,
                        "required_change_kind": "create_project",
                    },
                )
            return base_profile, empty_context
        if not engineering_baseline_exists:
            raise EngineeringGovernanceError(
                ["调查提交的项目配置所指工程基线不存在"]
            )

        checker = ProjectAuthorityConsistency(
            self.project,
            observed_ref=investigation_ref,
        )
        try:
            governance = checker.engineering_governance_context()
        except ProjectAuthorityConsistencyError as error:
            raise EngineeringGovernanceError(error.issues) from error
        return governance["profile"], {
            "baseline_refs": set(governance["baseline_refs"]),
            "domain_model_id": governance["domain_model_id"],
            "domain_fact_locations": governance["domain_fact_locations"],
            "authority_artifacts": governance["authority_artifacts"],
            "candidate_context": candidate_context,
        }

    def _current_direction_context(self) -> dict[str, Any]:
        baseline_reader = ProjectEngineeringBaseline(self.project)
        configuration = baseline_reader.project_configuration()
        integration_ref = str(
            configuration.get("default_integration_ref") or ""
        ).strip()
        if not integration_ref:
            return unadopted_project_direction_context()
        observed_commit = baseline_reader.resolve_code_ref(integration_ref)
        observed_baseline = ProjectEngineeringBaseline(
            self.project,
            observed_ref=observed_commit,
        )
        # A create-project worktree may already contain its first project
        # configuration while the immutable integration commit intentionally
        # contains no project authority yet.  Direction freshness is about the
        # adopted integration commit, not that unadopted working-tree
        # candidate.  Once a configuration is present in the observed commit,
        # however, a missing or invalid baseline must still fail closed through
        # ProjectAuthorityConsistency below.
        if not observed_baseline.project_config_exists():
            return unadopted_project_direction_context()
        return ProjectAuthorityConsistency(
            self.project,
            observed_ref=observed_commit,
        ).direction_context()

    def _direction_context_invalidation_issues(
        self,
        current: Mapping[str, Any],
    ) -> list[str]:
        """Return only mechanically provable reasons a stored direction is stale."""

        if not direction_context_requires_validation(current):
            return []
        return direction_context_invalidation_issues(
            current,
            self._current_direction_context(),
        )

    def _require_current_work_item_direction_context(
        self,
        current: Mapping[str, Any],
    ) -> None:
        issues = self._direction_context_invalidation_issues(current)
        if issues:
            raise ApplicationCoordinatorError(
                "direction_context_invalid",
                "已确认方向绑定的产品决定上下文已经失效；必须先修订并重新确认方向",
                details=issues,
            )

    def _require_current_direction_context(
        self,
        direction: Mapping[str, Any],
    ) -> dict[str, Any]:
        binding = direction.get("decision_context")
        if not isinstance(binding, Mapping):
            raise ApplicationCoordinatorError(
                "direction_context_invalid",
                "方向决定缺少完整 decision_context",
            )
        current_context = self._current_direction_context()
        try:
            validate_direction_context_binding(binding, current_context)
        except ProjectProductDefinitionError as error:
            raise ApplicationCoordinatorError(
                "direction_context_invalid",
                str(error),
                details=error.issues,
            ) from error
        return current_context

    @staticmethod
    def _require_reconsidered_guardrails_planned(
        direction: Mapping[str, Any],
        assessment: Mapping[str, Any],
    ) -> None:
        binding = direction.get("decision_context")
        binding = binding if isinstance(binding, Mapping) else {}
        dispositions = binding.get("guardrail_dispositions")
        reconsidered = [
            str(item.get("decision_ref") or "")
            for item in dispositions or []
            if isinstance(item, Mapping)
            and item.get("disposition") == "reconsider"
        ]
        if not reconsidered:
            return

        impact_scope = assessment.get("impact_scope")
        impact_scope = impact_scope if isinstance(impact_scope, Mapping) else {}
        impacted_dimensions = {
            str(item.get("dimension") or "")
            for group in ("affected", "unknown")
            for item in impact_scope.get(group) or []
            if isinstance(item, Mapping)
        }
        change_set = assessment.get("authority_change_set")
        change_set = change_set if isinstance(change_set, Mapping) else {}
        has_product_candidate = any(
            isinstance(candidate, Mapping)
            and candidate.get("authority_kind") == "product_definition"
            for candidate in change_set.get("candidate_authorities") or []
        )
        issues: list[str] = []
        if "product_scope" not in impacted_dimensions:
            issues.append(
                "方向建议重新考虑既有产品护栏时，工程评估必须把 product_scope "
                "标为 affected 或 unknown"
            )
        if not has_product_candidate:
            issues.append(
                "方向建议重新考虑既有产品护栏时，工程评估必须规划产品定义候选"
            )
        if issues:
            raise ApplicationCoordinatorError(
                "guardrail_reconsideration_unplanned",
                "；".join(issues),
                details=issues,
            )

    @staticmethod
    def _verification_commands(current: Mapping[str, Any]) -> list[dict[str, Any]]:
        data = current.get("data")
        engineering = (
            data.get("engineering") if isinstance(data, Mapping) else None
        )
        plan = (
            engineering.get("plan")
            if isinstance(engineering, Mapping)
            else None
        )
        if not isinstance(plan, Mapping):
            raise VerificationRunnerError(
                "verification_commands_missing",
                "当前 WorkItem 没有工程方案",
            )
        commands = plan.get("verification_commands") or []
        if not isinstance(commands, list) or any(
            not isinstance(item, Mapping) for item in commands
        ):
            raise VerificationRunnerError(
                "verification_commands_missing",
                "当前工程方案没有有效验证命令",
            )
        return [deepcopy(dict(item)) for item in commands]

    @staticmethod
    def _approved_verification_request(
        current: Mapping[str, Any],
        selected: Mapping[str, Any],
    ) -> dict[str, Any]:
        data = current.get("data")
        engineering = (
            data.get("engineering") if isinstance(data, Mapping) else None
        )
        plan = (
            engineering.get("plan")
            if isinstance(engineering, Mapping)
            else None
        )
        confirmation = (
            engineering.get("plan_confirmation")
            if isinstance(engineering, Mapping)
            else None
        )
        if not isinstance(plan, Mapping):
            raise VerificationRunnerError(
                "verification_plan_missing",
                "当前建设事项没有可执行工程方案",
            )
        plan_id = plan.get("plan_id")
        if not isinstance(plan_id, str) or not plan_id.strip():
            raise VerificationRunnerError(
                "verification_plan_missing",
                "当前工程方案缺少精确身份",
            )
        if not isinstance(confirmation, Mapping) or confirmation.get(
            "accepted"
        ) is not True:
            raise VerificationRunnerError(
                "verification_plan_not_confirmed",
                "当前工程方案尚未由项目负责人接受",
            )
        planned = next(
            (
                item
                for item in plan.get("verification_commands") or []
                if isinstance(item, Mapping)
                and item.get("command_id") == selected.get("command_id")
            ),
            None,
        )
        if planned is None or dict(planned) != dict(selected):
            raise VerificationRunnerError(
                "verification_command_not_approved",
                "验证命令不是当前已确认方案中的精确命令",
            )
        if (
            current.get("status") == "implementing"
            and plan.get("implementation_slices")
        ):
            receipts = data.get("verifications") if isinstance(data, Mapping) else []
            current_slice = focused_slice(
                plan,
                receipts if isinstance(receipts, list) else [],
                (
                    data.get("implementation_slice_completions")
                    if isinstance(data, Mapping)
                    and isinstance(
                        data.get("implementation_slice_completions"), list
                    )
                    else []
                ),
            )
            allowed_command_ids = (
                set(current_slice.get("verification_command_ids") or [])
                if isinstance(current_slice, Mapping)
                else set()
            )
            if selected.get("command_id") not in allowed_command_ids:
                raise VerificationRunnerError(
                    "verification_slice_not_ready",
                    "验证命令不属于当前可执行实施切片；请先完成前置切片",
                    details={
                        "current_slice_id": (
                            current_slice.get("slice_id")
                            if isinstance(current_slice, Mapping)
                            else None
                        ),
                        "allowed_command_ids": sorted(allowed_command_ids),
                    },
                )
        policy_decision = plan.get("verification_policy_decision")
        if not isinstance(policy_decision, Mapping):
            raise VerificationRunnerError(
                "verification_policy_decision_missing",
                "当前已确认方案没有绑定验证政策决议",
            )
        return {
            "schema_version": APPROVED_VERIFICATION_REQUEST_SCHEMA,
            "work_item_id": str(current["work_item_id"]),
            "work_item_version": int(current["version"]),
            "plan_id": plan_id,
            "plan_confirmation": {"plan_id": plan_id, "accepted": True},
            "policy_decision": deepcopy(dict(policy_decision)),
            "command": deepcopy(dict(selected)),
        }

    @staticmethod
    def _slice_operation_refs(
        slice_value: Mapping[str, Any],
    ) -> list[str]:
        return ImplementationCandidateEvidence.operation_refs(slice_value)

    @staticmethod
    def _slice_operation_paths(
        plan: Mapping[str, Any],
        slice_value: Mapping[str, Any],
    ) -> list[str]:
        return ImplementationCandidateEvidence.operation_paths(
            plan,
            slice_value,
        )

    @staticmethod
    def _slice_operation_realization(
        current: Mapping[str, Any],
        plan: Mapping[str, Any],
        slice_value: Mapping[str, Any],
        *,
        project_dir: str | Path,
        observed_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        return ImplementationCandidateEvidence(
            project_dir
        ).operation_realization(
            current,
            plan,
            slice_value,
            observed_ref=observed_ref,
        )

    @staticmethod
    def _require_slice_operations_realized(
        current: Mapping[str, Any],
        plan: Mapping[str, Any],
        slice_value: Mapping[str, Any],
        *,
        project_dir: str | Path,
        observed_ref: str | None = None,
    ) -> list[dict[str, Any]]:
        entries = current["data"].get("repository_deliveries") or []
        results = []
        for entry in entries or [{"repository_id": current["data"].get("selected_repository_id"), "git": current["data"].get("git") or {}}]:
            if not ImplementationCandidateEvidence.operation_paths(plan, slice_value, repository_id=entry["repository_id"]):
                continue
            selected = repository_item(current, entry["repository_id"])
            area = entry.get("git") or {}
            integrated = (area.get("integration") or {}).get("integrated_commit")
            root = ApplicationCoordinator._execution_root_for_area(area, project_dir)
            results.extend(ImplementationCandidateEvidence(root).require_operations_realized(selected, plan, slice_value, observed_ref=integrated or observed_ref))
        order = ImplementationCandidateEvidence.operation_refs(slice_value)
        return sorted(results, key=lambda value: order.index(value["operation_ref"]))

    @staticmethod
    def _slice_content_snapshot(current: Mapping[str, Any], plan: Mapping[str, Any], slice_value: Mapping[str, Any], *, project_dir: str | Path) -> list[dict[str, Any]]:
        entries = current["data"].get("repository_deliveries") or []
        if not entries:
            return ImplementationCandidateEvidence(project_dir).path_snapshot(ImplementationCandidateEvidence.operation_paths(plan, slice_value))
        result = []
        for entry in entries:
            identifier = entry["repository_id"]
            paths = ImplementationCandidateEvidence.operation_paths(plan, slice_value, repository_id=identifier)
            if not paths:
                continue
            root = ApplicationCoordinator._execution_root_for_area(entry.get("git") or {}, project_dir)
            result.extend({**value, "repository_id": identifier} for value in ImplementationCandidateEvidence(root).path_snapshot(paths))
        return result

    @staticmethod
    def _slice_path_snapshot(
        project_dir: str | Path,
        paths: Sequence[str],
        *,
        observed_ref: str | None = None,
    ) -> list[dict[str, str]]:
        return ImplementationCandidateEvidence(project_dir).path_snapshot(
            paths,
            observed_ref=observed_ref,
        )

    @staticmethod
    def _require_completed_slice_snapshots(
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
        observed_ref: str | None = None,
        exclude_paths: Sequence[str] = (),
    ) -> None:
        ImplementationCandidateEvidence(
            project_dir
        ).require_completed_slice_snapshots(
            current,
            observed_ref=observed_ref,
            exclude_paths=exclude_paths,
        )

    @staticmethod
    def _implementation_candidate_snapshot(
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> dict[str, Any] | None:
        entries = current["data"].get("repository_deliveries") or []
        if not entries:
            return ImplementationCandidateEvidence(project_dir).candidate_snapshot(current)
        snapshots = []
        for entry in entries:
            selected = repository_item(current, entry["repository_id"])
            area = entry.get("git") or {}
            integrated = (area.get("integration") or {}).get("integrated_commit")
            if integrated:
                previous = (current["data"].get("actual_result") or {}).get("implementation_candidate_snapshot") or {}
                snapshot = area.get("integrated_content_snapshot") or next((value for value in previous.get("repositories", []) if value["repository_id"] == entry["repository_id"]), None)
                resolved = None if area.get("integrated_content_snapshot") else (area.get("conflict_resolution") or {}).get("implementation_candidate_snapshot")
                if resolved:
                    snapshot = resolved
                if snapshot is None:
                    raise VerificationRunnerError("implementation_candidate_snapshot_missing", "已交付仓库缺少原结果内容证据，不能重建为新的实现事实")
                selected["data"]["actual_result"] = {"implementation_candidate_snapshot": snapshot}
                ImplementationCandidateEvidence(area["repository"]).require_candidate_snapshot(selected, observed_ref=integrated, comparison_base_ref=(area.get("integration") or {}).get("contribution_base_commit"), exclude_paths=ImplementationCandidateEvidence.mechanical_authority_paths(selected), use_conflict_resolution=bool(resolved))
                snapshot = deepcopy(snapshot)
            else:
                root = project_dir if entry["repository_id"] == current["data"].get("selected_repository_id") else ApplicationCoordinator._execution_root_for_area(area, project_dir)
                snapshot = ImplementationCandidateEvidence(root).candidate_snapshot(selected)
            if snapshot is not None:
                snapshots.append(snapshot)
        return {
            "schema_version": "strixnova.project-implementation-snapshot.v1",
            "plan_id": current["data"]["engineering"]["plan"]["plan_id"],
            "repositories": snapshots, "semantic_content_machine_proven": False,
        }

    def _conflict_candidate_snapshot(
        self,
        current: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        return ImplementationCandidateEvidence(self._repository_root(current)).conflict_candidate_snapshot(
            current
        )

    @staticmethod
    def _require_implementation_candidate_snapshot(
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
        observed_ref: str | None = None,
        comparison_base_ref: str | None = None,
        exclude_paths: Sequence[str] = (),
        use_conflict_resolution: bool = False,
    ) -> None:
        ImplementationCandidateEvidence(project_dir).require_candidate_snapshot(
            current,
            observed_ref=observed_ref,
            comparison_base_ref=comparison_base_ref,
            exclude_paths=exclude_paths,
            use_conflict_resolution=use_conflict_resolution,
        )

    @staticmethod
    def _mechanical_authority_paths(
        current: Mapping[str, Any],
    ) -> list[str]:
        return ImplementationCandidateEvidence.mechanical_authority_paths(
            current
        )

    @staticmethod
    def _require_current_slice_path_scope(
        current: Mapping[str, Any],
        *,
        project_dir: str | Path,
    ) -> None:
        """Check every prepared repository against the same overall slice."""
        entries = current["data"].get("repository_deliveries") or []
        for entry in entries or [{"repository_id": current["data"].get("selected_repository_id"), "git": current["data"].get("git") or {}}]:
            if ((entry.get("git") or {}).get("cleanup") or {}).get("safe"):
                continue
            root = ApplicationCoordinator._execution_root_for_area(entry.get("git") or {}, project_dir)
            ApplicationCoordinator._require_repository_slice_path_scope(repository_item(current, entry["repository_id"]), project_dir=root)

    @staticmethod
    def _require_repository_slice_path_scope(current: Mapping[str, Any], *, project_dir: str | Path) -> None:

        if current.get("status") != "implementing":
            return
        data = current.get("data")
        engineering = (
            data.get("engineering") if isinstance(data, Mapping) else None
        )
        plan = (
            engineering.get("plan")
            if isinstance(engineering, Mapping)
            else None
        )
        if not isinstance(plan, Mapping) or not plan.get(
            "implementation_slices"
        ):
            return
        receipts = data.get("verifications") if isinstance(data, Mapping) else []
        completions = (
            data.get("implementation_slice_completions")
            if isinstance(data, Mapping)
            else []
        )
        current_slice = focused_slice(
            plan,
            receipts if isinstance(receipts, list) else [],
            completions if isinstance(completions, list) else [],
        )
        if isinstance(current_slice, Mapping) and current_slice.get(
            "continued_operation_refs"
        ):
            assessment = engineering.get("assessment")
            investigation_ref = (
                str(assessment.get("investigation_ref") or "")
                if isinstance(assessment, Mapping)
                else ""
            )
            checker = ProjectAuthorityConsistency(project_dir)
            try:
                candidate = checker.load_working_tree_candidate_for(
                    investigation_ref
                )
                alignment_paths = set(
                    checker.authority_governed_paths(
                        candidate,
                        "implementation_alignment",
                    )
                )
            except ProjectAuthorityConsistencyError as error:
                raise VerificationRunnerError(
                    "implementation_alignment_refresh_scope_invalid",
                    "实现对齐延续刷新前无法复核完整候选权威路径",
                    details=error.issues,
                ) from error
            continued_paths = set(
                ApplicationCoordinator._slice_operation_paths(
                    plan,
                    {
                        **dict(current_slice),
                        "operation_refs": [],
                    },
                )
            )
            outside_alignment = sorted(continued_paths - alignment_paths)
            if outside_alignment:
                raise VerificationRunnerError(
                    "implementation_alignment_refresh_scope_invalid",
                    "延续操作包含不属于当前实现对齐候选的治理路径",
                    details={
                        "slice_id": current_slice.get("slice_id"),
                        "outside_alignment_paths": outside_alignment,
                    },
                )
        ApplicationCoordinator._require_completed_slice_snapshots(
            current,
            project_dir=project_dir,
        )
        scope = permitted_slice_operation_paths(
            plan,
            receipts if isinstance(receipts, list) else [],
            completions if isinstance(completions, list) else [],
            repository_id=current["data"].get("selected_repository_id"),
        )
        work_area = ApplicationCoordinator._work_area(current)
        actual_paths = set(
            ApplicationCoordinator._repository_changed_paths(current)
        )
        permitted_paths = set(scope["permitted_paths"])
        planned_paths = set(scope["planned_paths"])
        future_paths = set(scope["future_paths"])
        preauthored_governance_paths: set[str] = set()
        all_authority_kinds = planned_upstream_authority_kinds(
            current,
            current_progress_only=False,
        )
        if all_authority_kinds:
            ApplicationCoordinator._require_upstream_authority_decisions(
                current,
                {"changed_authority_kinds": all_authority_kinds},
                project_dir=project_dir,
            )
            try:
                preauthored_governance_paths.update(
                    planned_project_authority_paths(project_dir, current)
                )
            except ProjectAuthorityDecisionError as error:
                raise VerificationRunnerError(
                    error.code,
                    str(error),
                    details=error.details,
                ) from error
        premature_paths = sorted(
            actual_paths & (future_paths - preauthored_governance_paths)
        )
        if premature_paths:
            raise VerificationRunnerError(
                "implementation_slice_path_not_ready",
                "工作树包含只属于后续实施切片的文件；请恢复提前改动，"
                "或在确需调整顺序时先重新规划",
                details={
                    "current_slice_id": scope["current_slice_id"],
                    "permitted_paths": sorted(permitted_paths),
                    "premature_paths": premature_paths,
                },
            )
        unplanned_paths = sorted(actual_paths - planned_paths)
        if unplanned_paths:
            raise VerificationRunnerError(
                "unplanned_repository_change",
                "工作树包含未归属于任何已确认工程操作的路径；验证副产物或误改应精确清理，"
                "必要的持久改动必须先重新规划",
                details={
                    "current_slice_id": scope["current_slice_id"],
                    "unplanned_paths": unplanned_paths,
                },
            )


__all__ = [
    "ApplicationCoordinator",
    "ApplicationCoordinatorError",
]
