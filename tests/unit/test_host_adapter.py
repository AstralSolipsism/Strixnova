from __future__ import annotations

from tests.support.implementation_alignment import observation_coverage as current_observation_coverage

from tests.support.project_context import FRONTEND

from tests.support.project_configuration import configure_repository

import os
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

import strixnova.application_coordinator as application_coordinator_module
from strixnova.application_coordinator import (
    ApplicationCoordinator,
    ApplicationCoordinatorError,
)
from strixnova.engineering_governance import (
    IMPACT_DIMENSIONS,
)
from strixnova.git_workspace import GitWorkspace
from strixnova.git_project_reader import GitProjectReader
from strixnova.implementation_observation import observe_implementation
from strixnova.host_adapter import (
    HostAdapterError,
    LocalHostAdapter,
)
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)
from strixnova.workflow_authority import WorkflowAuthority
from strixnova.verification_runner import (
    VerificationRunner,
    VerificationRunnerError,
    normalize_verification_commands,
)
from strixnova.work_item_read_model import WorkItemReadModel
from tests.support.governance_assessment import (
    assessment_fixture,
    bind_assessment_to_work_item,
    clone_assessment,
    exploration_assessment,
    satisfied_governance_rule_results,
    semantic_review_fixture,
)
from tests.support.project_baseline import (
    TEST_ALIGNMENT_ID,
    TEST_INVARIANT_FACT_ID,
    TEST_TERM_FACT_ID,
    adopt_portable_ddd,
    portable_project_baseline,
)
from tests.support.verification_approval import (
    approval_expectations,
    approved_verification_request,
)


def _git(repo: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _observation_coverage(project: Path, alignment: dict, *, observed_ref: str | None = None) -> dict:
    return current_observation_coverage(project, alignment, observed_ref=observed_ref)


def _confirmation_payload(
    current_action: dict,
    *,
    accepted: bool = True,
    correction: str = "需要修正候选内容",
) -> dict[str, str]:
    challenge = current_action["confirmation_challenge"]
    return {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": (
            "同意当前候选，可以继续。"
            if accepted
            else correction
        ),
        "agent_decision": {
            "decision": "accept" if accepted else "request_changes",
            "reason": "负责人明确接受当前候选" if accepted else correction,
        },
    }


def _adapter_confirmation_arguments(
    adapter: LocalHostAdapter,
    work_item_id: str,
    *,
    accepted: bool = True,
    correction: str = "需要修正候选内容",
) -> dict[str, str]:
    action = adapter.current_action(work_item_id)
    assert action is not None
    return _confirmation_payload(
        action,
        accepted=accepted,
        correction=correction,
    )


def _adopted_ddd_baseline(
    project: Path,
    repository_root: Path,
) -> tuple[dict, dict[str, str]]:
    baseline = portable_project_baseline(
        project,
        baseline_id="adopted-ddd-host-test",
        artifacts=[
            {
                "artifact_id": "BASELINE-001",
                "artifact_type": "product_governance",
                "path": "docs/engineering/baseline.yaml",
                "status": "current",
                "relations": [],
            }
        ],
    )
    identities = adopt_portable_ddd(
        project,
        baseline,
        verification_path="tests/test_src.py",
    )
    return baseline, identities


def _prepare_adopted_ddd_repository(
    project: Path,
    repository_root: Path,
) -> tuple[dict, dict[str, str]]:
    """Create a committed, drift-free authority chain for host-level tests."""

    del repository_root
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline, identities = _adopted_ddd_baseline(project, project)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(project, integration_ref="main")
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    _git(project, "add", "src.py", "strixnova-project.yaml", "docs")
    if (project / "tests").exists():
        _git(project, "add", "tests")
    _git(project, "commit", "-m", "adopt ddd baseline")
    observation_base = _git(project, "rev-parse", "HEAD")

    source_digest = hashlib.sha256(
        GitProjectReader(project).read_canonical_bytes(
            "src.py",
            "测试行为文件",
        )
    ).hexdigest()
    alignment_path = project / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    ownership_path = project / alignment["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["sha256"] = source_digest
    ownership_path.write_text(
        yaml.safe_dump(ownership, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment["code_snapshot"].update(
        {'repositories': [{'repository_id': FRONTEND, 'base_commit': observation_base, 'worktree_state': 'clean'}], 'governed_source_manifest_sha256': hashlib.sha256(f'{FRONTEND}:src.py:{source_digest}\n'.encode('utf-8')).hexdigest()}
    )
    alignment["observation_coverage"] = _observation_coverage(
        project,
        alignment,
    )
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    baseline["code_version"] = {'repositories': [{'repository_id': FRONTEND, 'base_commit': observation_base, 'worktree_state': 'clean'}]}
    baseline["review_state"] = {
        "required": False,
        "reasons": [],
        "affected_authority_kinds": [],
    }
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(project, "add", "docs")
    _git(project, "commit", "-m", "bind implementation evidence")
    _git(project, "branch", "-M", "main")
    return baseline, identities


def _direction_context_binding(project: Path) -> dict[str, object]:
    context = WorkItemReadModel(project).project_direction_context()
    capabilities = context["capability_catalog"]
    return {
        "context_ref": context["context_ref"],
        "capability_refs": [capabilities[0]["capability_ref"]],
        "guardrail_dispositions": [
            {
                "decision_ref": guardrail["decision_ref"],
                "disposition": "applies",
                "reason": "本测试方向继续遵守这项已确认产品护栏。",
            }
            for guardrail in context["guardrails"]
        ],
        "assumptions": [],
    }


def _stable_direction(
    *,
    goal: str,
    scope: list[str],
    acceptance: list[str],
    decision_context: dict[str, object] | None = None,
    non_goals: list[str] | None = None,
    constraints: list[str] | None = None,
    tradeoffs: list[str] | None = None,
) -> dict[str, object]:
    requirement_ids = [
        "DIRREQ-1111111111111111",
        "DIRREQ-4444444444444444",
        "DIRREQ-7777777777777777",
    ]
    constraint_ids = [
        "DIRCON-2222222222222222",
        "DIRCON-5555555555555555",
        "DIRCON-8888888888888888",
    ]
    acceptance_ids = [
        "DIRACC-3333333333333333",
        "DIRACC-6666666666666666",
        "DIRACC-9999999999999999",
    ]
    assert len(scope) <= len(requirement_ids)
    assert len(constraints or []) <= len(constraint_ids)
    assert len(acceptance) <= len(acceptance_ids)
    requirements = [
        {"requirement_id": requirement_ids[index], "statement": statement}
        for index, statement in enumerate(scope)
    ]
    return {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": decision_context
        or {
            "context_ref": None,
            "capability_refs": [],
            "guardrail_dispositions": [],
            "assumptions": [],
        },
        "goal": goal,
        "scope": requirements,
        "non_goals": list(non_goals or []),
        "constraints": [
            {"constraint_id": constraint_ids[index], "statement": statement}
            for index, statement in enumerate(constraints or [])
        ],
        "tradeoffs": list(tradeoffs or []),
        "acceptance": [
            {
                "acceptance_id": acceptance_ids[index],
                "statement": statement,
                "requirement_refs": [
                    item["requirement_id"] for item in requirements
                ],
                "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
            }
            for index, statement in enumerate(acceptance)
        ],
    }


def test_host_adapter_is_explicit_intent_transport_not_session_authority(
    tmp_path: Path,
) -> None:
    adapter = LocalHostAdapter(tmp_path)

    assert adapter.describe() == {
        "schema_version": "strixnova.local-host-adapter.v1",
        "adapter_id": "local-request-adapter-v2",
        "transport": "local_explicit_intents",
        "reads_current_action": True,
        "accepts_coding_agent_candidates": True,
        "reports_execution_facts": True,
        "issues_credentials": False,
        "owns_sessions": False,
        "maintains_leases": False,
        "controls_remote_git": False,
    }


def test_next_step_discloses_only_records_requested_by_the_current_action(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="优化测试", raw_request="测试等待过久。")
    adapter = LocalHostAdapter(tmp_path)

    minimal = adapter.next_step(created["work_item_id"])
    assert minimal["current_action"]["intent"] == "submit"
    assert minimal["current_action"]["input_kind"] == "direction"
    contract_ref = minimal["current_action"]["input_contract_ref"]
    assert contract_ref == "input.contract:submit_direction"
    assert minimal["current_action"]["record_refs"] == [
        "request",
        "project.direction_context",
        "project.follow_ups",
    ]
    assert minimal["current_action"]["conditional_record_refs"] == []
    assert minimal["records"] == {}

    with_request_and_contract = adapter.next_step(
        created["work_item_id"],
        record_refs=["request", "project.direction_context", contract_ref],
    )
    assert with_request_and_contract["records"]["request"] == {
        "title": "优化测试",
        "raw_request": "测试等待过久。",
    }
    assert with_request_and_contract["records"]["project.direction_context"] == {
        "schema_version": "strixnova.project-direction-context.v1",
        "authority_scope": "unadopted_project",
        "observed_commit": None,
        "context_ref": None,
        "product": None,
        "capability_catalog": [],
        "guardrails": [],
        "semantic_relevance_machine_proven": False,
    }
    contract = with_request_and_contract["records"][contract_ref]
    assert contract["schema_version"] == "strixnova.input-contract.v1"
    assert contract["command"] == "submit"
    assert set(contract["payload_schema"]["required"]) == {
        "direction",
        "ready_for_confirmation",
        "blockers",
    }
    assert "direction-decision-v1.schema.json" in contract["referenced_schemas"]
    with pytest.raises(HostAdapterError) as captured:
        adapter.next_step(
            created["work_item_id"],
            record_refs=["direction"],
        )
    assert captured.value.code == "record_not_available_for_action"


def test_verification_action_discloses_exact_confirmed_command_record(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="验证接口", raw_request="运行确认过的命令。")
    identifier = item["work_item_id"]
    command = normalize_verification_commands(
        [
            {
                "argv": ["tool", "check"],
                "cwd": ".",
                "run_kind": "full_regression",
                "covers": [
                    "direction.acceptance:DIRACC-3333333333333333"
                ],
                "reason": "证明验收结果。",
            }
        ]
    )[0]

    def transition(action: str, body: dict) -> dict:
        current = authority.get(identifier)
        if action in {
            "confirm_direction",
            "confirm_engineering_plan",
            "confirm_actual_result",
        }:
            body = _confirmation_payload(
                current["current_action"],
                accepted="reject_correction" not in body,
                correction=str(
                    body.get("reject_correction") or "需要修正候选内容"
                ),
            )
        return authority.transition(
            identifier,
            action,
            body,
            expected_version=current["version"],
        )

    transition(
        "submit_direction",
        {
            "direction": _stable_direction(
                goal="运行确认过的验证",
                scope=["验证接口"],
                acceptance=["命令身份可发现"],
                constraints=["原始回执只能由程序提供，Agent 不得重写。"],
            ),
            "ready_for_confirmation": True,
        },
    )
    transition("confirm_direction", {})
    transition(
        "submit_engineering_assessment",
        {
            "assessment": {
                "change_context": {"formal_implementation": True},
                "verification_commands": [command],
            },
            "plan": {
                "change_context": {"formal_implementation": True},
                "operations": [
                    {
                        "action": "modify",
                        "path": "src.py",
                        "reason": "实现并验证当前接口。",
                        "evidence_refs": [
                            "direction.requirement:DIRREQ-1111111111111111"
                        ],
                        "implements": [
                            "direction.requirement:DIRREQ-1111111111111111"
                        ],
                    }
                ],
                "verification_commands": [command],
                "implementation_slices": [
                    {
                        "schema_version": "strixnova.implementation-slice-plan.v1",
                        "slice_id": "SLICE-001",
                        "source_slice_ref": "implementation_slices[0]",
                        "purpose": "实现并验证当前接口。",
                        "implements": [
                            "direction.acceptance:DIRACC-3333333333333333"
                        ],
                        "operation_refs": ["operations[0]"],
                        "depends_on": [],
                        "parallel_safe_with": [],
                        "completion_criteria": ["接口验证通过。"],
                        "verification_command_ids": ["VC-001"],
                        "rollback_or_recovery": "失败时修正当前切片。",
                        "machine_validated": True,
                    }
                ],
            },
        },
    )
    transition(
        "confirm_engineering_plan",
        {},
    )
    transition(
        "record_implementation_started",
        {
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "worktree_path": str(tmp_path),
                "work_ref": f"strixnova/{identifier}",
            }
        },
    )

    adapter = LocalHostAdapter(tmp_path)
    minimal = adapter.next_step(identifier)
    assert minimal["current_action"]["record_refs"] == [
        "engineering.plan.implementation_slice:SLICE-001",
        "engineering.plan.verification_commands",
        "git",
        "engineering.execution_context",
        "engineering.review_subject",
    ]
    disclosed = adapter.next_step(
        identifier,
        record_refs=[
            "engineering.plan.implementation_slice:SLICE-001",
            "engineering.plan.verification_commands",
            "engineering.execution_context",
        ],
    )
    assert disclosed["records"]["engineering.plan.verification_commands"] == [
        command
    ]
    assert disclosed["records"][
        "engineering.plan.implementation_slice:SLICE-001"
    ]["slice_id"] == "SLICE-001"
    assert disclosed["records"][
        "engineering.plan.implementation_slice:SLICE-001"
    ]["resolved_operations"] == [
        {
            "operation_ref": "operations[0]",
            "slice_ownership": "owned",
            "operation": {
                "action": "modify",
                "path": "src.py",
                "reason": "实现并验证当前接口。",
                "evidence_refs": [
                    "direction.requirement:DIRREQ-1111111111111111"
                ],
                "implements": [
                    "direction.requirement:DIRREQ-1111111111111111"
                ],
            },
        }
    ]
    context = disclosed["records"][
        "engineering.plan.implementation_slice:SLICE-001"
    ]["execution_context"]
    assert context["direction"]["goal"] == "运行确认过的验证"
    assert context["direction"]["constraints"] == [
        {
            "constraint_id": "DIRCON-2222222222222222",
            "statement": "原始回执只能由程序提供，Agent 不得重写。",
        }
    ]
    assert context["verification_commands"] == [command]
    assert context["source"]["work_item_version"] == minimal["work_item_version"]
    assert context["semantic_content_machine_proven"] is False
    assert disclosed["records"]["engineering.execution_context"] == context
    reference = "engineering.execution_context#/direction/constraints/0/statement"
    bounded = adapter.next_step(identifier, record_refs=[reference], max_output_bytes=3072)
    assert bounded["records"][reference] == "原始回执只能由程序提供，Agent 不得重写。"
    with pytest.raises(HostAdapterError) as error:
        adapter.next_step(identifier, record_refs=[reference], max_output_bytes=3072, expected_sha256="0" * 64)
    assert error.value.code == "record_read_source_changed"


def test_verification_cannot_skip_the_current_implementation_slice() -> None:
    commands = [
        {"command_id": "VC-001"},
        {"command_id": "VC-002"},
    ]
    current = {
        "work_item_id": "WI-SLICE-GATE",
        "version": 7,
        "status": "implementing",
        "data": {
            "engineering": {
                "plan": {
                    "plan_id": "PLAN-WI-SLICE-GATE",
                    "verification_commands": commands,
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "depends_on": [],
                            "verification_command_ids": ["VC-001"],
                        },
                        {
                            "slice_id": "SLICE-002",
                            "depends_on": ["SLICE-001"],
                            "verification_command_ids": ["VC-002"],
                        },
                    ],
                    "verification_policy_decision": {
                        "schema_version": (
                            "strixnova.verification-policy-decision.v1"
                        )
                    },
                },
                "plan_confirmation": {
                    "plan_id": "PLAN-WI-SLICE-GATE",
                    "accepted": True,
                },
            },
            "verifications": [],
        },
    }

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._approved_verification_request(
            current,
            commands[1],
        )

    assert captured.value.code == "verification_slice_not_ready"
    assert captured.value.details == {
        "current_slice_id": "SLICE-001",
        "allowed_command_ids": ["VC-001"],
    }


def test_verification_blocks_paths_owned_only_by_a_future_slice(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    current = {
        "status": "implementing",
        "data": {
            "engineering": {
                "plan": {
                    "operations": [
                        {"action": "modify", "path": "src/first.py"},
                        {"action": "modify", "path": "src/future.py"},
                    ],
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "operation_refs": ["operations[0]"],
                            "depends_on": [],
                            "verification_command_ids": ["VC-001"],
                        },
                        {
                            "slice_id": "SLICE-002",
                            "operation_refs": ["operations[1]"],
                            "depends_on": ["SLICE-001"],
                            "verification_command_ids": ["VC-002"],
                        },
                    ],
                }
            },
            "verifications": [],
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "repository": str(tmp_path.resolve()),
                "worktree_path": str(tmp_path),
            },
        },
    }
    monkeypatch.setattr(
        GitWorkspace,
        "changed_paths",
        lambda _self, _area: ["src/first.py", "src/future.py"],
    )

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._require_current_slice_path_scope(
            current,
            project_dir=tmp_path,
        )

    assert captured.value.code == "implementation_slice_path_not_ready"
    assert captured.value.details == {
        "current_slice_id": "SLICE-001",
        "permitted_paths": ["src/first.py"],
        "premature_paths": ["src/future.py"],
    }


def test_zero_command_slice_completion_still_rejects_future_slice_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    current = {
        "work_item_id": "WI-ZERO-COMMAND-SLICE",
        "version": 7,
        "status": "implementing",
        "data": {
            "engineering": {
                "plan": {
                    "operations": [
                        {"action": "modify", "path": "docs/current.md"},
                        {"action": "modify", "path": "src/future.py"},
                    ],
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "operation_refs": ["operations[0]"],
                            "depends_on": [],
                            "verification_command_ids": [],
                        },
                        {
                            "slice_id": "SLICE-002",
                            "operation_refs": ["operations[1]"],
                            "depends_on": ["SLICE-001"],
                            "verification_command_ids": ["VC-002"],
                        },
                    ],
                }
            },
            "verifications": [],
            "implementation_slice_completions": [],
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "repository": str(tmp_path.resolve()),
                "work_item_id": "WI-ZERO-COMMAND-SLICE",
                "target_ref": "main",
                "base_commit": "0" * 40,
                "worktree_path": str(tmp_path),
                "work_ref": "main",
                "worktree_mode": "in_place",
                "created_by_strixnova": True,
                "merge_strategy": "no_ff",
            },
        },
    }
    coordinator = ApplicationCoordinator(tmp_path)
    monkeypatch.setattr(coordinator.authority, "get", lambda _identifier: current)
    monkeypatch.setattr(
        GitWorkspace,
        "changed_paths",
        lambda _self, _area: ["docs/current.md", "src/future.py"],
    )

    with pytest.raises(ApplicationCoordinatorError) as captured:
        coordinator.complete_implementation_slice(
            current["work_item_id"],
            {
                "schema_version": "strixnova.implementation-slice-completion.v1",
                "slice_id": "SLICE-001",
                "completion_summary": "当前说明文档已经完成。",
                "semantic_content_machine_proven": False,
            },
            expected_version=current["version"],
        )

    assert captured.value.code == "implementation_slice_path_not_ready"
    assert captured.value.details["premature_paths"] == ["src/future.py"]


def test_verification_reports_unplanned_command_byproducts_separately(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    current = {
        "status": "implementing",
        "data": {
            "engineering": {
                "plan": {
                    "operations": [
                        {"action": "modify", "path": "src/first.py"},
                    ],
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "operation_refs": ["operations[0]"],
                            "depends_on": [],
                            "verification_command_ids": ["VC-001"],
                        },
                    ],
                }
            },
            "verifications": [],
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "repository": str(tmp_path.resolve()),
                "worktree_path": str(tmp_path),
            },
        },
    }
    monkeypatch.setattr(
        GitWorkspace,
        "changed_paths",
        lambda _self, _area: [
            "src/first.py",
            "src/__pycache__/first.cpython-312.pyc",
        ],
    )

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._require_current_slice_path_scope(
            current,
            project_dir=tmp_path,
        )

    assert captured.value.code == "unplanned_repository_change"
    assert captured.value.details == {
        "current_slice_id": "SLICE-001",
        "unplanned_paths": ["src/__pycache__/first.cpython-312.pyc"],
    }


def test_rejected_plan_keeps_confirmed_direction_version_discoverable(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="优化测试", raw_request="测试等待过久。")
    work_item_id = created["work_item_id"]
    proposed = authority.transition(
        work_item_id,
        "submit_direction",
        {
            "direction": _stable_direction(
                goal="减少测试等待时间",
                scope=["测试结构和执行策略"],
                acceptance=["报告真实耗时"],
                non_goals=["删除必要行为覆盖"],
                constraints=["使用项目 venv"],
                tradeoffs=["不设置人为秒数门槛"],
            ),
            "ready_for_confirmation": True,
        },
        expected_version=created["version"],
    )
    direction_action = authority.get(work_item_id)["current_action"]
    confirmed = authority.transition(
        work_item_id,
        "confirm_direction",
        _confirmation_payload(direction_action),
        expected_version=proposed["version"],
    )
    assessed = authority.transition(
        work_item_id,
        "submit_engineering_assessment",
        {
            "assessment": {"assessment_id": "EA-001"},
            "plan": {"change_context": {"formal_implementation": True}},
        },
        expected_version=confirmed["version"],
    )
    rejected = authority.transition(
        work_item_id,
        "confirm_engineering_plan",
        _confirmation_payload(
            authority.get(work_item_id)["current_action"],
            accepted=False,
            correction="方案需要收敛",
        ),
        expected_version=assessed["version"],
    )

    assert rejected["version"] > confirmed["version"]
    adapter = LocalHostAdapter(tmp_path)
    minimal = adapter.next_step(work_item_id)
    assert minimal["current_action"]["record_refs"] == [
        "direction",
        "direction_confirmation",
        "project.direction_context",
        "project.follow_ups",
    ]
    assert minimal["current_action"]["conditional_record_refs"] == []
    with_records = adapter.next_step(
        work_item_id,
        record_refs=[
            "direction",
            "direction_confirmation",
            "project.direction_context",
        ],
    )
    direction_confirmation = with_records["records"][
        "direction_confirmation"
    ]
    assert direction_confirmation["accepted"] is True
    assert direction_confirmation["candidate_fingerprint"] == (
        direction_action["confirmation_challenge"]["candidate_fingerprint"]
    )
    assert direction_confirmation["direction_version"] == confirmed["version"]
    with pytest.raises(HostAdapterError) as captured:
        adapter.next_step(
            work_item_id,
            record_refs=[
                "project.domain.fact:FACT-AAAAAAAAAAAAAAAA:"
                "SRC-BBBBBBBBBBBBBBBB:COLL-CCCCCCCCCCCCCCCC:"
                "docs/domain/collections/missing.yaml:"
                "docs/domain/sources/missing.yaml"
            ],
        )
    assert captured.value.code == "record_not_available_for_action"


def test_conflict_merge_commit_cannot_precede_result_reconfirmation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init")
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="冲突结果", raw_request="先确认再完成 merge")
    identifier = item["work_item_id"]

    def transition(action: str, body: dict) -> dict:
        nonlocal item
        if action in {
            "confirm_direction",
            "confirm_engineering_plan",
            "confirm_actual_result",
        }:
            current = authority.get(identifier)
            body = _confirmation_payload(
                current["current_action"],
                accepted="reject_correction" not in body,
                correction=str(
                    body.get("reject_correction") or "需要修正候选内容"
                ),
            )
        item = authority.transition(
            identifier,
            action,
            body,
            expected_version=item["version"],
        )
        return item

    transition(
        "submit_direction",
        {
            "direction": _stable_direction(
                goal="修复冲突",
                scope=["冲突文件"],
                acceptance=["用户确认后才完成 merge"],
            ),
            "ready_for_confirmation": True,
        },
    )
    transition("confirm_direction", {})
    transition(
        "submit_engineering_assessment",
        {
            "assessment": {
                "change_context": {"formal_implementation": True},
                "verification_commands": [],
            },
            "plan": {"change_context": {"formal_implementation": True}},
        },
    )
    transition(
        "confirm_engineering_plan",
        {},
    )
    transition(
        "record_implementation_started",
        {
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "worktree_path": str(tmp_path),
                "work_ref": f"strixnova/{identifier}",
                "target_ref": "main",
                "base_commit": "a" * 40,
            }
        },
    )
    transition("present_actual_result", {"actual_result": {"first": True}})
    transition("confirm_actual_result", {})
    transition("record_result_commits", {"commits": ["b" * 40]})
    transition(
        "claim_external_effect",
        {"kind": "integrate", "intent": {"merge_strategy": "no_ff"}},
    )
    transition(
        "record_local_integration",
        {
            "outcome": "conflict",
            "integration": {
                "outcome": "conflict",
                "conflict_entries": ["UU shared.txt"],
            },
            "blockers": ["git_conflict"],
        },
    )
    transition(
        "record_conflict_resolution",
        {
            "user_visible_result_changed": True,
            "confirmed_direction_or_plan_changed": False,
            "reason": "冲突解决改变了用户可见结果。",
            "retest_command_ids": ["VC-001"],
        },
    )
    transition("present_actual_result", {"actual_result": {"changed": True}})

    monkeypatch.setattr(
        GitWorkspace,
        "integration_result",
        lambda self, work_area: {"outcome": "integrated"},
    )
    adapter = LocalHostAdapter(tmp_path)
    with pytest.raises(HostAdapterError) as captured:
        adapter.confirm(
            identifier,
            "actual_result",
            **_adapter_confirmation_arguments(adapter, identifier),
            expected_version=item["version"],
        )
    assert captured.value.code == "premature_conflict_merge_commit"


def test_cli_and_hosts_share_one_engineering_assessment_interface(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    assessment["operations"][0].update(action="create", path="work-notes.md")
    _prepare_adopted_ddd_repository(
        tmp_path,
        Path(__file__).resolve().parents[2],
    )
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="事项", raw_request="优化测试")
    identifier = created["work_item_id"]
    adapter = LocalHostAdapter(tmp_path)
    adapter.submit_direction(
        identifier,
        {
            "direction": _stable_direction(
                goal="优化测试",
                scope=["测试结构"],
                acceptance=["报告实际结果"],
                decision_context=_direction_context_binding(tmp_path),
                non_goals=["删除必要覆盖"],
                constraints=["使用项目 venv"],
                tradeoffs=["用户确认后提交"],
            ),
            "ready_for_confirmation": True,
        },
        expected_version=1,
    )
    adapter.confirm(
        identifier,
        "direction",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=2,
    )
    bind_assessment_to_work_item(assessment, authority.get(identifier))
    assessment["investigation_ref"] = "main"
    assessment["source_references"][0]["observed_ref"] = "main"
    assessment["verification_commands"][0]["argv"][0] = sys.executable

    assessed = adapter.submit_engineering_assessment(
        identifier,
        assessment,
        expected_version=3,
    )

    assert assessed["status"] == "awaiting_plan_confirmation"
    assert assessed["data"]["engineering"]["plan"][
        "semantic_content_machine_proven"
    ] is False
    assert all(
        rule["source_ids"]
        for rule in assessed["data"]["engineering"]["plan"][
            "applicable_rules"
        ]
    )
    ready = adapter.confirm(
        identifier,
        "engineering_plan",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=assessed["version"],
    )
    implementing = authority.transition(
        identifier,
        "record_implementation_started",
        {
                "git": {
                    "schema_version": "strixnova.git-work-area.v1",
                    "repository": str(tmp_path.resolve()),
                    "work_item_id": identifier,
                    "target_ref": "main",
                    "base_commit": _git(tmp_path, "rev-parse", "HEAD"),
                    "worktree_path": str(tmp_path),
                    "work_ref": "main",
                    "worktree_mode": "in_place",
                    "created_by_strixnova": True,
                    "merge_strategy": "no_ff",
                }
        },
        expected_version=ready["version"],
    )
    first_plan = assessed["data"]["engineering"]["plan"]
    first_command = first_plan["verification_commands"][0]
    first_approval = approved_verification_request(
        first_command,
        work_item_id=identifier,
        work_item_version=implementing["version"],
        plan_id=first_plan["plan_id"],
    )
    first_receipt = VerificationRunner(
        tmp_path,
        artifact_root=tmp_path / ".strixnova" / "artifacts",
    ).not_run(
        first_approval,
        **approval_expectations(first_approval),
        reason="重规划前环境不具备执行条件。",
        limitations=["重规划前没有可用的执行环境。"],
        code_change_assessment={
            "changed_after": False,
            "needs_retest": False,
            "rationale": "回执后尚未修改实现。",
        },
    )
    recorded = adapter.report_verification(
        identifier,
        first_receipt,
        expected_version=implementing["version"],
        execution_area="worktree",
    )
    assert recorded["current_action"]["action_type"] == "present_actual_result"
    configuration_path = tmp_path / "strixnova-project.yaml"
    original_configuration = configuration_path.read_bytes()
    configuration_path.write_text("invalid: current locator\n", encoding="utf-8")
    replanning = adapter.request_replan(
        identifier,
        {
            "schema_version": "strixnova.replan-request.v1",
            "reasons": ["目标分支前进后的 diff 改变了已确认设计依据。"],
        },
        expected_version=recorded["version"],
    )
    assert replanning["status"] == "replanning_required"
    assert replanning["data"]["blockers"] == [
        "目标分支前进后的 diff 改变了已确认设计依据。"
    ]
    assert replanning["data"]["verifications"] == []
    assert replanning["data"]["engineering"]["plan"] is None
    assert configuration_path.read_text(encoding="utf-8") == "invalid: current locator\n"
    configuration_path.write_bytes(original_configuration)

    downgraded = exploration_assessment(tmp_path)
    bind_assessment_to_work_item(downgraded, replanning)
    downgraded["assessment_id"] = assessment["assessment_id"]
    downgraded["assessment_revision"] = 2
    with pytest.raises(HostAdapterError) as rejected:
        adapter.submit_engineering_assessment(
            identifier,
            downgraded,
            expected_version=replanning["version"],
        )
    assert rejected.value.code == "application_use_case_rejected"

    revised = clone_assessment(assessment)
    revised["assessment_revision"] = 2
    revised["verification_commands"][0]["reason"] = (
        "按目标分支最新事实重新验证确认的验收。"
    )
    assessed_again = adapter.submit_engineering_assessment(
        identifier,
        revised,
        expected_version=replanning["version"],
    )
    implementing_again = adapter.confirm(
        identifier,
        "engineering_plan",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=assessed_again["version"],
    )
    replacement_plan = assessed_again["data"]["engineering"]["plan"]
    replacement_command = replacement_plan["verification_commands"][0]
    replacement_approval = approved_verification_request(
        replacement_command,
        work_item_id=identifier,
        work_item_version=implementing_again["version"],
        plan_id=replacement_plan["plan_id"],
    )
    replacement_receipt = VerificationRunner(
        tmp_path,
        artifact_root=tmp_path / ".strixnova" / "artifacts",
    ).not_run(
        replacement_approval,
        **approval_expectations(replacement_approval),
        reason="修订方案的环境检查仍不可运行。",
        limitations=["修订方案仍缺少可用的执行环境。"],
        code_change_assessment={
            "changed_after": False,
            "needs_retest": False,
            "rationale": "修订回执后未继续修改实现。",
        },
    )
    rerecorded = adapter.report_verification(
        identifier,
        replacement_receipt,
        expected_version=implementing_again["version"],
        execution_area="worktree",
    )
    assert rerecorded["data"]["verifications"] == [replacement_receipt]


def test_new_product_authority_invalidates_an_unadopted_direction_binding(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="方向连续性", raw_request="先确认一个新项目方向")
    identifier = created["work_item_id"]
    adapter = LocalHostAdapter(tmp_path)
    proposed = adapter.submit_direction(
        identifier,
        {
            "direction": _stable_direction(
                goal="建立一个可追溯方向",
                scope=["当前本地项目"],
                acceptance=["方向绑定当前产品事实"],
                non_goals=["远程操作"],
                constraints=["不伪造产品决定"],
            ),
            "ready_for_confirmation": True,
        },
        expected_version=created["version"],
    )
    confirmed = adapter.confirm(
        identifier,
        "direction",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=proposed["version"],
    )
    assessment = assessment_fixture(tmp_path, work_item_id=identifier)
    _prepare_adopted_ddd_repository(
        tmp_path,
        Path(__file__).resolve().parents[2],
    )
    bind_assessment_to_work_item(assessment, authority.get(identifier))
    assessment["investigation_ref"] = "main"
    assessment["source_references"][0]["observed_ref"] = "main"
    assessment["verification_commands"][0]["argv"][0] = sys.executable

    with pytest.raises(HostAdapterError) as captured:
        adapter.submit_engineering_assessment(
            identifier,
            assessment,
            expected_version=confirmed["version"],
        )

    assert captured.value.code == "direction_context_invalid"
    assert any("已经过期" in issue for issue in captured.value.details)

    action = adapter.current_action(identifier)
    assert action is not None
    assert action["action_type"] == "revise_direction"
    assert action["actor"] == "coding_agent"
    assert action["record_refs"] == [
        "request",
        "direction",
        "direction_confirmation",
        "engineering.plan",
        "project.direction_context",
    ]
    contract_ref = action["input_contract_ref"]
    next_step = adapter.next_step(
        identifier,
        record_refs=["project.direction_context", contract_ref],
    )
    current_context = next_step["records"]["project.direction_context"]
    assert current_context["context_ref"] is not None
    assert next_step["records"][contract_ref]["command"] == "submit"

    read_model = WorkItemReadModel(tmp_path)
    listed = read_model.work_items()["work_items"]
    assert listed[0]["current_action"]["action_type"] == "revise_direction"
    overview = read_model.overview(focus_work_item_id=identifier)
    assert overview["focus"]["current_action"]["action_type"] == "revise_direction"
    assert overview["attention"][0]["current_action"]["action_type"] == (
        "revise_direction"
    )
    detailed = read_model.work_item(identifier)
    assert detailed["work_item"]["current_action"]["action_type"] == (
        "revise_direction"
    )

    history_before_invalid_revision = authority.history(identifier)
    with pytest.raises(HostAdapterError) as invalid_revision:
        adapter.submit_current_action_input(
            identifier,
            {
                "direction": {
                    "schema_version": "strixnova.direction-decision.v1",
                    "decision_context": _direction_context_binding(tmp_path),
                    "goal": "缺少其余方向字段",
                },
                "ready_for_confirmation": True,
                "blockers": [],
            },
            expected_version=confirmed["version"],
        )
    assert invalid_revision.value.code == "direction_incomplete"
    assert authority.get(identifier)["version"] == confirmed["version"]
    assert authority.history(identifier) == history_before_invalid_revision

    revised = adapter.submit_current_action_input(
        identifier,
        {
            "direction": _stable_direction(
                goal="在当前产品决定下建立一条可追溯方向",
                scope=["当前本地项目"],
                acceptance=["修订方向绑定当前产品事实"],
                decision_context=_direction_context_binding(tmp_path),
                non_goals=["远程操作"],
                constraints=["不伪造产品决定"],
            ),
            "ready_for_confirmation": True,
            "blockers": [],
        },
        expected_version=confirmed["version"],
    )

    assert revised["status"] == "awaiting_direction_confirmation"
    assert revised["version"] == confirmed["version"] + 1
    assert revised["data"]["engineering"]["plan"] is None
    assert revised["data"]["direction_confirmation"] is None
    assert revised["data"]["direction"]["decision_context"]["context_ref"] == (
        current_context["context_ref"]
    )
    revision_event = authority.history(identifier)[-1]
    assert revision_event["event_type"] == "revise_direction"
    assert revision_event["payload"]["invalidation_issues"]
    assert all(
        isinstance(issue, str) and issue
        for issue in revision_event["payload"]["invalidation_issues"]
    )


def test_reconsidering_a_guardrail_requires_a_product_candidate(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    _prepare_adopted_ddd_repository(
        tmp_path,
        Path(__file__).resolve().parents[2],
    )
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="重新考虑护栏", raw_request="调整既有产品边界")
    identifier = created["work_item_id"]
    adapter = LocalHostAdapter(tmp_path)
    binding = _direction_context_binding(tmp_path)
    binding["guardrail_dispositions"][0]["disposition"] = "reconsider"
    binding["guardrail_dispositions"][0]["reason"] = (
        "用户请求可能需要重新打开这项产品决定。"
    )
    proposed = adapter.submit_direction(
        identifier,
        {
            "direction": _stable_direction(
                goal="评估是否调整既有产品边界",
                scope=["产品方向调查"],
                acceptance=["任何边界变化先形成产品候选"],
                decision_context=binding,
                non_goals=["程序替负责人决定"],
                constraints=["既有护栏在新产品修订确认前继续有效"],
            ),
            "ready_for_confirmation": True,
        },
        expected_version=created["version"],
    )
    confirmed = adapter.confirm(
        identifier,
        "direction",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=proposed["version"],
    )
    bind_assessment_to_work_item(assessment, authority.get(identifier))
    assessment["investigation_ref"] = "main"
    assessment["source_references"][0]["observed_ref"] = "main"
    assessment["verification_commands"][0]["argv"][0] = sys.executable

    with pytest.raises(HostAdapterError) as captured:
        adapter.submit_engineering_assessment(
            identifier,
            assessment,
            expected_version=confirmed["version"],
        )

    assert captured.value.code == "guardrail_reconsideration_unplanned"
    assert any("product_scope" in issue for issue in captured.value.details)
    assert any("产品定义候选" in issue for issue in captured.value.details)


def test_affected_target_advance_returns_to_engineering_assessment(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="目标前进", raw_request="判断方案是否仍成立")
    identifier = item["work_item_id"]
    transitions = [
        (
            "submit_direction",
            {
                "direction": _stable_direction(
                    goal="按最新目标分支实施",
                    scope=["本地改动"],
                    acceptance=["不使用过期方案"],
                    non_goals=["远程 Git"],
                    constraints=["变化影响语义时重新评估"],
                ),
                "ready_for_confirmation": True,
            },
        ),
        ("confirm_direction", {}),
        (
            "submit_engineering_assessment",
            {
                "assessment": {"id": "assessment"},
                "plan": {"change_context": {"formal_implementation": True}},
            },
        ),
        (
            "confirm_engineering_plan",
            {},
        ),
        (
            "record_target_advance",
            {
                "target_advance": {
                    "schema_version": "strixnova.target-advance.v1",
                    "target_ref": "main",
                    "target_commit": "b" * 40,
                    "investigation_commit": "a" * 40,
                    "assessment": None,
                }
            },
        ),
    ]
    for action, payload in transitions:
        if action in {
            "confirm_direction",
            "confirm_engineering_plan",
            "confirm_actual_result",
        }:
            payload = _confirmation_payload(
                authority.get(identifier)["current_action"]
            )
        item = authority.transition(
            identifier,
            action,
            payload,
            expected_version=item["version"],
        )

    replanning = LocalHostAdapter(tmp_path).submit_current_action_input(
        identifier,
        {
            "schema_version": "strixnova.target-advance-assessment.v1",
            "semantic_impact": "affected",
            "reason": "目标分支修改了当前设计依赖，旧方案不再成立。",
        },
        expected_version=item["version"],
    )

    assert replanning["status"] == "replanning_required"
    assert replanning["data"]["blockers"] == [
        "目标分支修改了当前设计依赖，旧方案不再成立。"
    ]
    revised = authority.transition(
        identifier,
        "submit_engineering_assessment",
        {
            "assessment": {"id": "revised-assessment"},
            "plan": {"change_context": {"formal_implementation": True}},
        },
        expected_version=replanning["version"],
    )
    assert "target_advance" not in revised["data"]["git"]


def test_host_reads_project_governance_from_the_assessment_git_commit(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    assessment = assessment_fixture(tmp_path)
    assessment["operations"][0].update(action="create", path="work-notes.md")
    for relative in ("strixnova-project.yaml",):
        source = repository_root / relative
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="governance-ref-test",
        artifacts=[],
    )
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    configure_repository(tmp_path, integration_ref="main")
    _git(tmp_path, "add", "src.py", "strixnova-project.yaml", "docs")
    _git(tmp_path, "commit", "-m", "adopt project engineering baseline")
    _git(tmp_path, "branch", "-M", "main")
    assessment["investigation_ref"] = "main"
    assessment["source_references"][0]["observed_ref"] = "main"
    assessment["verification_commands"][0]["argv"][0] = sys.executable

    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="并行事项", raw_request="按 main 的治理评估")
    identifier = item["work_item_id"]
    authority.transition(
        identifier,
        "submit_direction",
        {
            "direction": _stable_direction(
                goal="只采用明确引用提交中的治理事实",
                scope=["工程评估"],
                acceptance=["临时工作树不污染候选"],
                decision_context=_direction_context_binding(tmp_path),
                non_goals=["读取其他 WorkItem 临时内容"],
                constraints=["Git 是长期事实权威"],
            ),
            "ready_for_confirmation": True,
        },
        expected_version=1,
    )
    authority.transition(
        identifier,
        "confirm_direction",
        _confirmation_payload(
            authority.get(identifier)["current_action"]
        ),
        expected_version=2,
    )
    bind_assessment_to_work_item(assessment, authority.get(identifier))
    adapter = LocalHostAdapter(tmp_path)
    policy_path = tmp_path / baseline["authority_refs"]["engineering_policy"][
        "path"
    ]
    provisional = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    provisional["base_profile_ref"]["profile_id"] = (
        "provisional-wrong-profile"
    )
    policy_path.write_text(
        yaml.safe_dump(provisional, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    assessed = adapter.submit_engineering_assessment(
        identifier,
        assessment,
        expected_version=3,
    )

    assert assessed["status"] == "awaiting_plan_confirmation"
    assert {
        reference["observed_ref"]
        for reference in assessed["data"]["engineering"]["assessment"][
            "source_references"
        ]
    } == {_git(tmp_path, "rev-parse", "main")}


@pytest.mark.slow
def test_adopted_ddd_choice_reaches_plan_actual_result_and_focused_read_model(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_src.py").write_text(
        "def test_placeholder():\n    assert True\n",
        encoding="utf-8",
    )
    assessment = exploration_assessment(tmp_path)
    _, identities = _prepare_adopted_ddd_repository(
        tmp_path,
        repository_root,
    )

    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="梳理领域术语", raw_request="明确 WorkItem 含义")
    identifier = created["work_item_id"]
    adapter = LocalHostAdapter(tmp_path)
    proposed = adapter.submit_direction(
        identifier,
        {
            "direction": _stable_direction(
                goal="明确测试项目中的 WorkItem 领域含义",
                scope=["统一语言分析"],
                acceptance=["工程方案和实际结果可追溯本次方法使用"],
                decision_context=_direction_context_binding(tmp_path),
                non_goals=["修改项目文件"],
                constraints=["使用已采用的 DDD 项目事实"],
                tradeoffs=["只做领域分析，不形成实现"],
            ),
            "ready_for_confirmation": True,
        },
        expected_version=created["version"],
    )
    confirmed = adapter.confirm(
        identifier,
        "direction",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=proposed["version"],
    )

    head = _git(tmp_path, "rev-parse", "main")
    assessment["investigation_ref"] = head
    assessment["source_references"] = [
        {
            "reference_id": "SRC-001",
            "path": "src.py",
            "line_start": 1,
            "line_end": 2,
            "observed_ref": head,
            "epistemic_status": "observed",
        },
        {
            "reference_id": "SRC-PROJECT-CONFIG",
            "path": "strixnova-project.yaml",
            "observed_ref": head,
            "epistemic_status": "observed",
        },
        {
            "reference_id": "SRC-PROJECT-BASELINE",
            "path": "docs/engineering/baseline.yaml",
            "observed_ref": head,
            "epistemic_status": "observed",
        },
    ]
    assessment["impact_scope"] = {
        "affected": [
            {
                "dimension": "domain",
                "reason": "本事项明确 WorkItem 的统一语言含义。",
                "evidence_refs": ["SRC-001", "SRC-PROJECT-BASELINE"],
            }
        ],
        "unknown": [],
        "unaffected": [
            dimension for dimension in IMPACT_DIMENSIONS if dimension != "domain"
        ],
    }
    assessment["method_applications"] = [
        {
            "method_id": "ddd",
            "decision": "applied",
            "purpose": "用项目统一语言明确 WorkItem 含义。",
            "evidence_refs": ["SRC-001", "SRC-PROJECT-BASELINE"],
            "baseline_refs": ["engineering-policy:method:ddd"],
            "domain_fact_refs": [
                {
                    "schema_version": "strixnova.domain-fact-reference.v1",
                    "authority_kind": "project_domain_model",
                    "model_id": identities["model_id"],
                    "fact_id": identities["term_fact_id"],
                    "observed_commit": head,
                }
            ],
            "planned_uses": [
                {
                    "use_id": "DDD-USE-001",
                    "stage": "domain_analysis",
                    "technique_ids": ["ubiquitous_language"],
                    "purpose": "核对项目术语与本事项表达。",
                    "target_refs": ["impact_scope.affected[0]"],
                    "evidence_refs": ["SRC-001", "SRC-PROJECT-BASELINE"],
                }
            ],
        }
    ]
    assessment["semantic_review"] = semantic_review_fixture(
        "SRC-001",
        "SRC-PROJECT-BASELINE",
    )
    bind_assessment_to_work_item(assessment, confirmed)
    assessed = adapter.submit_engineering_assessment(
        identifier,
        assessment,
        expected_version=confirmed["version"],
    )
    method_plan = assessed["data"]["engineering"]["plan"][
        "method_applications"
    ][0]
    assert method_plan["decision"] == "applied"
    assert method_plan["decision_source"] == "coding_agent_assessment"

    exploring = adapter.confirm(
        identifier,
        "engineering_plan",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=assessed["version"],
    )
    result_payload = {
        "schema_version": "strixnova.actual-result.v1",
        "review_subject_ref": adapter.read_model.review_subject(exploring)["subject_ref"],
        "semantic_content_machine_proven": False,
        "effect_summary": "已完成 WorkItem 统一语言分析。",
        "delivered_outcomes": ["已核对项目术语与事项表达。"],
        "deviations": [],
        "limitations": ["本事项没有修改项目文件。", "本夹具未执行计划中的逐项语义复核，只验证方法记录与读模型的协议行为。"],
        "verification_review_results": [
            {"target_ref": target["target_ref"], "outcome": "not_verified",
             "rationale": "该夹具只验证方法记录和投影，未重演逐项语义复核。", "evidence_refs": []}
            for target in assessed["data"]["engineering"]["plan"]["verification_targets"]
            if not target.get("command_ids")
        ],
        "verification_receipt_ids": [],
        "long_lived_refs": [],
        "method_application_results": [
            {
                "method_id": "ddd",
                "use_results": [
                    {
                        "use_id": "DDD-USE-001",
                        "status": "realized",
                        "outcome": "统一语言核对已完成。",
                        "evidence_refs": ["delivered_outcomes[0]"],
                    }
                ],
                "deviations": [],
            }
        ],
        "governance_rule_results": satisfied_governance_rule_results(
            assessed["data"]["engineering"]["plan"],
            "delivered_outcomes[0]",
        ),
    }
    prepared = adapter.prepare_input(identifier)
    judgments = {"fields": {key: value for key, value in result_payload.items() if key not in prepared["template"]}, "answers": {}}
    for row in prepared["checklist"]:
        value, fixed = result_payload, prepared["template"]
        for part in row["path"]:
            value, fixed = value[part], fixed[part]
        judgments["answers"][row["id"]] = {key: item for key, item in value.items() if key not in fixed}
    before = authority.get(identifier)
    events_before = authority.history(identifier)
    preview = adapter.preview_input(prepared, judgments)
    assert preview["ok"], preview["issues"]
    assert authority.get(identifier) == before
    assert authority.history(identifier) == events_before
    applied = adapter.apply_input(prepared, judgments)
    presented, coverage = applied["result"]["work_item"], applied["result"]["coverage"]
    assert coverage["verification_status"] == "not_required"
    completed = adapter.confirm(
        identifier,
        "actual_result",
        **_adapter_confirmation_arguments(adapter, identifier),
        expected_version=presented["version"],
    )
    assert completed["status"] == "completed"
    decisions = WorkItemReadModel(tmp_path).decisions(identifier)
    assert decisions["engineering_method_confirmation"]["applications"][0][
        "method_id"
    ] == "ddd"


@pytest.mark.slow
def test_actual_result_rejects_an_unplanned_sibling_domain_fact_change(
    tmp_path: Path,
) -> None:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_src.py").write_text(
        "def test_source():\n    assert True\n",
        encoding="utf-8",
    )
    baseline, identities = _adopted_ddd_baseline(tmp_path, tmp_path)
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "adopt domain model")
    _git(tmp_path, "branch", "-M", "main")
    observed_commit = _git(tmp_path, "rev-parse", "main")

    source_path = identities["source_path"]
    source = yaml.safe_load(
        (tmp_path / source_path).read_text(encoding="utf-8")
    )
    by_id = {item["fact_id"]: item for item in source["facts"]}
    original_term = by_id[TEST_TERM_FACT_ID]["content"]["definition"]
    original_invariant = by_id[TEST_INVARIANT_FACT_ID]["content"][
        "statement"
    ]
    by_id[TEST_TERM_FACT_ID]["content"]["definition"] = (
        "已计划的新建设事项定义。"
    )
    by_id[TEST_INVARIANT_FACT_ID]["content"]["statement"] = (
        "未计划改写的不变量。"
    )
    (tmp_path / source_path).write_text(
        yaml.safe_dump(source, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_path = identities["alignment_path"]
    alignment = yaml.safe_load(
        (tmp_path / alignment_path).read_text(encoding="utf-8")
    )
    original_alignment_date = alignment["code_snapshot"]["observed_on"]
    alignment["code_snapshot"]["observed_on"] = "2026-08-25"
    (tmp_path / alignment_path).write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    fact_ref = {
        "schema_version": "strixnova.domain-fact-reference.v1",
        "authority_kind": "project_domain_model",
        "model_id": identities["model_id"],
        "fact_id": TEST_TERM_FACT_ID,
        "observed_commit": observed_commit,
    }
    current = {
        "data": {
            "engineering": {
                "assessment": {
                    "investigation_ref": observed_commit,
                    "change_context": {"change_kind": "modify_existing"},
                    "domain_fact_changes": [
                        {
                            "disposition": "update",
                            "target_ref": fact_ref,
                            "source_path": source_path,
                            "lineage": [],
                        }
                    ],
                    "method_applications": [
                        {
                            "method_id": "ddd",
                        }
                    ],
                }
            }
        }
    }
    current["data"]["engineering"]["plan"] = {"operations": []}
    actual_result = {
        "domain_fact_change_results": [
            {"target_ref": fact_ref, "outcome": "realized"}
        ],
        "method_application_results": [
            {
                "method_id": "ddd",
            }
        ]
    }

    with pytest.raises(VerificationRunnerError) as caught:
        ApplicationCoordinator._validate_domain_change_results(
            current,
            actual_result,
            project_dir=tmp_path,
        )
    assert caught.value.code == "domain_authority_result_invalid"
    assert "复用现行修订身份时改写了权威内容" in "；".join(
        str(item) for item in caught.value.details
    )

    by_id[TEST_TERM_FACT_ID]["content"]["definition"] = original_term
    by_id[TEST_INVARIANT_FACT_ID]["content"]["statement"] = original_invariant
    (tmp_path / source_path).write_text(
        yaml.safe_dump(source, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment["code_snapshot"]["observed_on"] = original_alignment_date
    (tmp_path / alignment_path).write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    actual_result["domain_fact_change_results"][0]["outcome"] = "deferred"
    ApplicationCoordinator._validate_domain_change_results(
        current,
        actual_result,
        project_dir=tmp_path,
    )


@pytest.mark.slow
def test_actual_result_does_not_skip_unplanned_domain_metadata_change(
    tmp_path: Path,
) -> None:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_src.py").write_text(
        "def test_source():\n    assert True\n",
        encoding="utf-8",
    )
    baseline, identities = _adopted_ddd_baseline(tmp_path, tmp_path)
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "adopt domain model")
    _git(tmp_path, "branch", "-M", "main")
    observed_commit = _git(tmp_path, "rev-parse", "main")

    source_path = identities["source_path"]
    source = yaml.safe_load(
        (tmp_path / source_path).read_text(encoding="utf-8")
    )
    term = next(
        item
        for item in source["facts"]
        if item["fact_id"] == TEST_TERM_FACT_ID
    )
    term["content"]["definition"] += " 当前工作树发生未计划修改。"
    (tmp_path / source_path).write_text(
        yaml.safe_dump(source, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    current = {
        "data": {
            "engineering": {
                "assessment": {
                    "investigation_ref": observed_commit,
                    "change_context": {"change_kind": "modify_existing"},
                    "method_applications": [],
                }
            }
        }
    }
    current["data"]["engineering"]["plan"] = {"operations": []}

    with pytest.raises(VerificationRunnerError) as caught:
        ApplicationCoordinator._validate_domain_change_results(
            current,
            {"method_application_results": []},
            project_dir=tmp_path,
            actual_changed_paths=[source_path],
        )
    assert caught.value.code == "domain_authority_result_invalid"
    assert "复用现行修订身份时改写了权威内容" in "；".join(
        str(item) for item in caught.value.details
    )


def test_unadopted_adr_does_not_become_part_of_the_project_authority_chain(
    tmp_path: Path,
) -> None:
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="invalid-adr-test",
        artifacts=[
            {
                "artifact_id": "ADR-0099",
                "artifact_type": "adr",
                "path": "docs/adr/ADR-0099.md",
                "status": "current",
                "relations": [
                    {
                        "type": "originated_by",
                        "target_kind": "work_item",
                        "target_id": "WI-INVALID-ADR",
                    }
                ],
            }
        ],
    )
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    adr_path = tmp_path / "docs" / "adr" / "ADR-0099.md"
    adr_path.parent.mkdir(parents=True)
    adr_path.write_text("# 只有文件，没有 ADR 合同\n", encoding="utf-8")
    current = {
        "work_item_id": "WI-INVALID-ADR",
        "data": {
            "engineering": {
                "assessment": {
                    "operations": [
                        {
                            "action": "create",
                            "path": "docs/adr/ADR-0099.md",
                            "long_lived_artifact": {
                                "artifact_id": "ADR-0099",
                                "artifact_type": "adr",
                            },
                        },
                    ],
                    "adr_plans": [
                        {
                            "disposition": "create",
                            "artifact_id": "ADR-0099",
                            "path": "docs/adr/ADR-0099.md",
                        }
                    ],
                }
            }
        }
    }
    current["data"]["engineering"]["plan"] = {
        "operations": current["data"]["engineering"]["assessment"]["operations"]
    }
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": "ADR-0099",
                "artifact_type": "adr",
                "path": "docs/adr/ADR-0099.md",
                "relation": "introduced",
            }
        ]
    }

    ApplicationCoordinator._validate_long_lived_trace(
        current,
        actual_result,
        project_dir=tmp_path,
    )

    adopted = ProjectAuthorityConsistency(tmp_path).load()
    assert all(
        reference["path"] != "docs/adr/ADR-0099.md"
        for reference in adopted["baseline"]["authority_refs"].values()
    )


def test_actual_result_accepts_a_successor_alignment_over_an_unintegrated_baseline(
    tmp_path: Path,
) -> None:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_src.py").write_text(
        "def test_source():\n    assert True\n",
        encoding="utf-8",
    )
    baseline, identities = _adopted_ddd_baseline(tmp_path, tmp_path)
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_path = tmp_path / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    adopted_revision = alignment["revision"]["revision_id"]
    candidate_revision = "ALIGNREV-3333333333333333"
    alignment["revision"] = {
        "revision_id": candidate_revision,
        "status": "draft",
        "supersedes_revision_id": adopted_revision,
        "confirmed_by_owner_id": None,
        "confirmed_on": None,
    }
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for artifact_path in alignment["artifact_paths"].values():
        path = tmp_path / artifact_path
        artifact = yaml.safe_load(path.read_text(encoding="utf-8"))
        artifact["alignment_revision_id"] = candidate_revision
        path.write_text(
            yaml.safe_dump(artifact, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    operation = {
        "action": "modify",
        "path": identities["alignment_path"],
        "long_lived_artifact": {
            "artifact_id": TEST_ALIGNMENT_ID,
            "artifact_type": "domain_alignment",
        },
    }
    current = {
        "work_item_id": "WI-CANDIDATE-ALIGNMENT",
        "data": {
            "engineering": {
                "assessment": {
                    "investigation_ref": "",
                    "operations": [operation],
                    "adr_plans": [],
                    "change_context": {"change_kind": "modify_existing"},
                },
                "plan": {"operations": [operation]},
            }
        },
    }
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": TEST_ALIGNMENT_ID,
                "artifact_type": "domain_alignment",
                "path": identities["alignment_path"],
                "relation": "updated",
            }
        ]
    }

    ApplicationCoordinator._validate_long_lived_trace(
        current,
        actual_result,
        project_dir=tmp_path,
    )


def test_next_step_exposes_exact_mechanical_authority_adoption_before_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "branch", "-M", "main")
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_src.py").write_text(
        "def test_source():\n    assert True\n",
        encoding="utf-8",
    )
    baseline, identities = _adopted_ddd_baseline(tmp_path, tmp_path)
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)
    _git(tmp_path, "add", "strixnova-project.yaml", "docs", "src.py", "tests")
    _git(tmp_path, "commit", "-m", "adopt project authorities")
    investigation_ref = _git(tmp_path, "rev-parse", "HEAD")
    baseline["review_state"] = {
        "required": True,
        "reasons": ["实现后实现对齐候选尚未采用。"],
        "affected_authority_kinds": [
            "implementation_alignment",
            "code_version",
        ],
    }
    baseline["code_version"]["repositories"][0]["base_commit"] = investigation_ref
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)
    alignment_path = tmp_path / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    source_digest = hashlib.sha256(
        GitProjectReader(tmp_path).read_canonical_bytes(
            "src.py",
            "测试行为文件",
        )
    ).hexdigest()
    source_ownership_path = tmp_path / alignment["artifact_paths"][
        "source_ownership"
    ]
    source_ownership = yaml.safe_load(
        source_ownership_path.read_text(encoding="utf-8")
    )
    source_ownership["records"][0]["sha256"] = source_digest
    source_ownership_path.write_text(
        yaml.safe_dump(source_ownership, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment["code_snapshot"]["repositories"][0]["base_commit"] = investigation_ref
    alignment["code_snapshot"]["governed_source_manifest_sha256"] = hashlib.sha256(
        f"{FRONTEND}:src.py:{source_digest}\n".encode("utf-8")
    ).hexdigest()
    alignment["observation_coverage"] = _observation_coverage(
        tmp_path,
        alignment,
    )
    adopted_revision = alignment["revision"]["revision_id"]
    candidate_revision = "ALIGNREV-4444444444444444"
    alignment["revision"] = {
        "revision_id": candidate_revision,
        "status": "draft",
        "supersedes_revision_id": adopted_revision,
        "confirmed_by_owner_id": None,
        "confirmed_on": None,
    }
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for artifact_path in alignment["artifact_paths"].values():
        path = tmp_path / artifact_path
        artifact = yaml.safe_load(path.read_text(encoding="utf-8"))
        artifact["alignment_revision_id"] = candidate_revision
        path.write_text(
            yaml.safe_dump(artifact, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="采用实现对齐", raw_request="采用已接受的实际结果")
    identifier = item["work_item_id"]

    def transition(action: str, body: dict) -> dict:
        nonlocal item
        if action in {
            "confirm_direction",
            "confirm_engineering_plan",
            "confirm_actual_result",
        }:
            current = authority.get(identifier)
            body = _confirmation_payload(current["current_action"])
        item = authority.transition(
            identifier,
            action,
            body,
            expected_version=item["version"],
        )
        return item

    transition(
        "submit_direction",
        {
            "direction": _stable_direction(
                goal="采用已实现并验证的实现对齐候选",
                scope=["实现对齐权威"],
                acceptance=["实际结果接受后再定档并提交"],
            ),
            "ready_for_confirmation": True,
        },
    )
    transition("confirm_direction", {})
    transition(
        "submit_engineering_assessment",
        {
            "assessment": {
                "investigation_ref": investigation_ref,
                "change_context": {"formal_implementation": True},
                "verification_commands": [],
            },
            "plan": {"change_context": {"formal_implementation": True}},
        },
    )
    transition("confirm_engineering_plan", {})
    transition(
        "record_implementation_started",
        {
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "worktree_path": str(tmp_path),
                "work_ref": f"strixnova/{identifier}",
                "target_ref": "main",
                "base_commit": investigation_ref,
            }
        },
    )
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": TEST_ALIGNMENT_ID,
                "artifact_type": "domain_alignment",
                "path": identities["alignment_path"],
                "relation": "updated",
            }
        ]
    }
    missing_snapshot_record = ProjectAuthorityConsistency(
        tmp_path
    ).authority_adoption_record(
        actual_result,
        investigation_ref=investigation_ref,
        actual_result_confirmed=True,
        confirmed_on="2026-08-28",
    )
    assert missing_snapshot_record["ready_for_atomic_commits"] is False
    assert missing_snapshot_record["accepted_candidate_snapshot_verified"] is False
    assert "已接受实际结果缺少候选权威正文快照" in (
        missing_snapshot_record["blocking_issues"]
    )
    actual_result["authority_candidate_snapshot"] = (
        ProjectAuthorityConsistency(tmp_path).authority_candidate_snapshot(
            actual_result,
            investigation_ref=investigation_ref,
        )
    )
    transition(
        "present_actual_result",
        {"actual_result": actual_result},
    )
    transition("confirm_actual_result", {})

    record = LocalHostAdapter(tmp_path).next_step(
        identifier,
        record_refs=["delivery.authority_adoption"],
    )["records"]["delivery.authority_adoption"]

    assert record["schema_version"] == "strixnova.authority-adoption.v1"
    assert record["required"] is True
    assert record["authorized_by_actual_result_confirmation"] is True
    assert record["accepted_candidate_snapshot_verified"] is True
    assert record["semantic_reconfirmation_required"] is False
    assert record["ready_for_atomic_commits"] is False
    assert record["changed_authority_kinds"] == [
        "implementation_alignment"
    ]
    assert record["authority_updates"] == [
        {
            "authority_kind": "implementation_alignment",
            "path": identities["alignment_path"],
            "repository_id": baseline["authority_refs"]["implementation_alignment"]["repository_id"],
            "revision_id": candidate_revision,
            "set_revision_fields": {
                "status": "confirmed",
                "confirmed_by_owner_id": baseline["project"]["owner_id"],
                "confirmed_on": item["data"]["actual_result_confirmation"][
                    "confirmed_at"
                ][:10],
            },
            "set_baseline_ref_fields": {
                "revision_id": candidate_revision,
                "status": {
                    "revision_status": "confirmed",
                    "adoption_status": "current",
                },
            },
        }
    ]
    assert record["baseline_update"] == {
        "path": "docs/engineering/baseline.yaml",
        "set_review_state": {
            "required": False,
            "reasons": [],
            "affected_authority_kinds": [],
        },
    }
    assert record["blocking_issues"] == []
    assert record["semantic_content_machine_proven"] is False

    original_apply = application_coordinator_module.apply_yaml_patch_transaction
    interrupted = False

    def interrupt_after_first_file(
        project_dir: Path,
        transaction: dict,
        **kwargs,
    ) -> dict[Path, bytes]:
        nonlocal interrupted
        if not interrupted:
            interrupted = True
            original_apply(
                project_dir,
                {
                    "schema_version": transaction["schema_version"],
                    "entries": transaction["entries"][:1],
                },
                **kwargs,
            )
            raise KeyboardInterrupt("injected adoption interruption")
        return original_apply(project_dir, transaction, **kwargs)

    monkeypatch.setattr(
        application_coordinator_module,
        "apply_yaml_patch_transaction",
        interrupt_after_first_file,
    )
    coordinator = ApplicationCoordinator(tmp_path)
    with pytest.raises(KeyboardInterrupt, match="adoption interruption"):
        coordinator.delivery(
            identifier,
            {},
            expected_version=item["version"],
        )
    interrupted_item = authority.get(identifier)
    assert interrupted_item["data"]["pending_effect"]["kind"] == (
        "authority_adoption"
    )
    recovered = coordinator.delivery(
        identifier,
        {},
        expected_version=interrupted_item["version"],
    )
    assert recovered["steps"] == ["authority_adoption_finalized"]
    assert recovered["work_item"]["data"]["pending_effect"] is None


def test_actual_result_translates_an_invalid_independent_architecture(
    tmp_path: Path,
) -> None:
    _write_test_engineering_baseline(
        tmp_path,
        artifacts=[
            {
                "artifact_id": "ARCHITECTURE-001",
                "artifact_type": "architecture",
                "path": "docs/engineering/architecture.yaml",
                "status": "current",
                "relations": [
                    {
                        "type": "updated_by",
                        "target_kind": "work_item",
                        "target_id": "WI-INVALID-ARCHITECTURE",
                    }
                ],
            }
        ],
    )
    architecture = tmp_path / "docs" / "architecture" / "model.yaml"
    architecture.write_text(
        "architecture: [\n",
        encoding="utf-8",
    )
    current = {
        "work_item_id": "WI-INVALID-ARCHITECTURE",
        "data": {
            "engineering": {
                "assessment": {
                    "operations": [
                        {
                            "action": "modify",
                            "path": "docs/architecture/model.yaml",
                            "long_lived_artifact": {
                                "artifact_id": "ARCHITECTURE-001",
                                "artifact_type": "architecture",
                            },
                        }
                    ]
                }
            }
        },
    }
    current["data"]["engineering"]["plan"] = {
        "operations": current["data"]["engineering"]["assessment"]["operations"]
    }
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": "ARCHITECTURE-001",
                "artifact_type": "architecture",
                "path": "docs/architecture/model.yaml",
                "relation": "updated",
            }
        ]
    }

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._validate_long_lived_trace(
            current,
            actual_result,
            project_dir=tmp_path,
        )

    assert captured.value.code == "long_lived_artifact_invalid"
    assert any("YAML" in str(item) for item in captured.value.details)


def _write_test_engineering_baseline(
    project: Path,
    *,
    artifacts: list[dict],
) -> None:
    baseline = portable_project_baseline(
        project,
        baseline_id="long-lived-trace-test",
        artifacts=artifacts,
    )
    destination = project / "docs" / "engineering" / "baseline.yaml"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def test_actual_result_requires_every_planned_long_lived_artifact(
    tmp_path: Path,
) -> None:
    current = {
        "work_item_id": "WI-MISSING-LONG-LIVED",
        "data": {
            "engineering": {
                "assessment": {
                    "operations": [
                        {
                            "action": "modify",
                            "path": "docs/architecture.md",
                            "long_lived_artifact": {
                                "artifact_id": "ARCH-001",
                                "artifact_type": "architecture",
                            },
                        }
                    ]
                }
            }
        },
    }
    current["data"]["engineering"]["plan"] = {
        "operations": current["data"]["engineering"]["assessment"]["operations"]
    }

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._validate_long_lived_trace(
            current,
            {"long_lived_refs": []},
            project_dir=tmp_path,
        )

    assert captured.value.code == "long_lived_trace_missing"
    assert captured.value.details == [
        "ARCH-001/architecture/docs/architecture.md"
    ]


def test_new_project_actual_result_requires_all_declared_authority_paths(
    tmp_path: Path,
) -> None:
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text("schema_version: placeholder\n", encoding="utf-8")
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)
    expected = {
        "product_governance": "docs/product/definition.yaml",
        "domain_model": "docs/domain/model.yaml",
        "architecture": "docs/architecture/model.yaml",
        "quality_policy": "docs/engineering/policy.yaml",
        "domain_alignment": "docs/engineering/alignment.yaml",
    }
    planned = dict(expected)
    planned["product_governance"] = "docs/product/wrong.yaml"
    operations = [
        {
            "action": "create",
            "path": path,
            "long_lived_artifact": {
                "artifact_id": f"AUTHORITY-{index}",
                "artifact_type": artifact_type,
            },
        }
        for index, (artifact_type, path) in enumerate(planned.items(), start=1)
    ]
    current = {
        "work_item_id": "WI-NEW-PROJECT-AUTHORITIES",
        "data": {
            "engineering": {
                "assessment": {
                    "change_context": {
                        "change_kind": "create_project",
                        "project_engineering_baseline_path": (
                            "docs/engineering/baseline.yaml"
                        ),
                        "project_product_definition_path": expected[
                            "product_governance"
                        ],
                        "project_domain_model_path": expected["domain_model"],
                        "project_architecture_description_path": expected[
                            "architecture"
                        ],
                        "project_engineering_policy_path": expected[
                            "quality_policy"
                        ],
                        "project_implementation_alignment_path": expected[
                            "domain_alignment"
                        ],
                    },
                    "operations": operations,
                }
            }
        },
    }
    current["data"]["engineering"]["plan"] = {"operations": operations}
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": operation["long_lived_artifact"]["artifact_id"],
                "artifact_type": operation["long_lived_artifact"][
                    "artifact_type"
                ],
                "path": operation["path"],
                "relation": "introduced",
            }
            for operation in operations
        ]
    }

    with pytest.raises(VerificationRunnerError) as captured:
        ApplicationCoordinator._validate_long_lived_trace(
            current,
            actual_result,
            project_dir=tmp_path,
        )

    assert captured.value.code == "project_authority_result_missing"
    assert captured.value.details == [
        "product_governance:docs/product/definition.yaml:relation=introduced"
    ]


def test_actual_result_accepts_a_planned_long_lived_move(
    tmp_path: Path,
) -> None:
    work_item_id = "WI-MOVE-LONG-LIVED"
    destination = "docs/architecture/current.md"
    _write_test_engineering_baseline(
        tmp_path,
        artifacts=[
            {
                "artifact_id": "ARCH-001",
                "artifact_type": "architecture",
                "path": destination,
                "status": "current",
                "relations": [
                    {
                        "type": "updated_by",
                        "target_kind": "work_item",
                        "target_id": work_item_id,
                    }
                ],
            }
        ],
    )
    moved = tmp_path / destination
    moved.parent.mkdir(parents=True, exist_ok=True)
    moved.write_text("# Current architecture\n", encoding="utf-8")
    current = {
        "work_item_id": work_item_id,
        "data": {
            "engineering": {
                "assessment": {
                    "operations": [
                        {
                            "action": "move",
                            "path": "docs/architecture/legacy.md",
                            "to_path": destination,
                            "long_lived_artifact": {
                                "artifact_id": "ARCH-001",
                                "artifact_type": "architecture",
                            },
                        }
                    ]
                }
            }
        },
    }
    current["data"]["engineering"]["plan"] = {
        "operations": current["data"]["engineering"]["assessment"]["operations"]
    }

    ApplicationCoordinator._validate_long_lived_trace(
        current,
        {
            "long_lived_refs": [
                {
                    "artifact_id": "ARCH-001",
                    "artifact_type": "architecture",
                    "path": destination,
                    "relation": "updated",
                }
            ]
        },
        project_dir=tmp_path,
    )


def test_actual_result_accepts_a_removed_long_lived_artifact_only_after_unindexing(
    tmp_path: Path,
) -> None:
    work_item_id = "WI-DELETE-LONG-LIVED"
    path = "docs/architecture/obsolete.md"
    _write_test_engineering_baseline(tmp_path, artifacts=[])
    current = {
        "work_item_id": work_item_id,
        "data": {
            "engineering": {
                "assessment": {
                    "operations": [
                        {
                            "action": "delete",
                            "path": path,
                            "long_lived_artifact": {
                                "artifact_id": "ARCH-OLD",
                                "artifact_type": "architecture",
                            },
                        }
                    ]
                }
            }
        },
    }
    current["data"]["engineering"]["plan"] = {
        "operations": current["data"]["engineering"]["assessment"]["operations"]
    }

    ApplicationCoordinator._validate_long_lived_trace(
        current,
        {
            "long_lived_refs": [
                {
                    "artifact_id": "ARCH-OLD",
                    "artifact_type": "architecture",
                    "path": path,
                    "relation": "removed",
                }
            ]
        },
        project_dir=tmp_path,
    )


def test_first_project_authority_set_is_valid_without_a_mixed_artifact_index(
    tmp_path: Path,
) -> None:
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="new-project",
        artifacts=[],
    )
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)

    authorities = ProjectAuthorityConsistency(tmp_path).load()

    assert authorities["structurally_consistent"] is True
    assert set(authorities["baseline"]) == {
        "schema_version",
        "baseline_id",
        "project",
        "authority_refs",
        "current_architecture_stage_id",
        "code_version",
        "review_state",
        "_manifest_path",
        "_observed_commit",
        "semantic_content_machine_proven",
    }
