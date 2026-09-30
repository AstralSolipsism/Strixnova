from __future__ import annotations

from tests.support.project_configuration import configure_repository

from pathlib import Path
import subprocess

import pytest
import yaml

import strixnova.application_coordinator as application_coordinator_module
import strixnova.project_authority_decision as project_authority_decision_module
from strixnova.application_coordinator import (
    ApplicationCoordinator,
    ApplicationCoordinatorError,
)
from strixnova.confirmation_protocol import confirmation_record_from_input
from strixnova.current_action import current_action_for
from strixnova.project_authority_progress import (
    PROJECT_AUTHORITY_DECISION_SCHEMA,
    ProjectAuthorityDecisionError,
    authority_confirmation_challenge,
)
from strixnova.project_authority_decision import (
    apply_project_authority_confirmation_transaction,
    build_project_authority_confirmation_transaction,
    confirmed_project_authority_snapshot,
    project_authority_candidate,
    project_authority_review_bundle,
    validate_project_authority_decision,
)
from strixnova.verification_runner import VerificationRunnerError
from tests.support.project_baseline import (
    TEST_OWNER_ID,
    TEST_POLICY_ID,
    TEST_PRODUCT_ID,
    TEST_PRODUCT_REVISION_ID,
    portable_project_baseline,
)


def test_confirmation_checks_authority_before_creating_an_effect_lock(
    tmp_path: Path,
) -> None:
    with pytest.raises(ApplicationCoordinatorError) as captured:
        ApplicationCoordinator(tmp_path).confirm_project_authorities(
            "WI-20260830-11111111",
            {"decisions": []},
            expected_version=1,
        )

    assert captured.value.code == "authority_not_initialized"
    assert not (tmp_path / ".strixnova").exists()


def _ready_product_project(project: Path) -> tuple[dict, Path]:
    work_item_id = "WI-20260828-11111111"
    branch = f"strixnova/{work_item_id}"
    subprocess.run(
        ["git", "init", "-b", branch],
        cwd=project,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Strixnova Test"],
        cwd=project,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "strixnova@example.invalid"],
        cwd=project,
        check=True,
    )
    (project / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=project, check=True)
    subprocess.run(
        ["git", "commit", "-m", "base"],
        cwd=project,
        check=True,
        capture_output=True,
    )
    base_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    baseline = portable_project_baseline(
        project,
        baseline_id="authority-decision",
        artifacts=[],
    )
    path = project / "docs" / "product" / "definition.yaml"
    product = yaml.safe_load(path.read_text(encoding="utf-8"))
    product["revision"].update(
        {
            "status": "ready_for_confirmation",
            "confirmed_by_owner_id": None,
            "confirmed_on": None,
        }
    )
    path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    baseline["authority_refs"]["product_definition"]["status"] = {
        "revision_status": "ready_for_confirmation",
        "adoption_status": "under_review",
    }
    baseline["review_state"] = {
        "required": True,
        "reasons": ["产品候选等待独立负责人确认。"],
        "affected_authority_kinds": ["product_definition"],
    }
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(project, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)
    item = {
        "work_item_id": work_item_id,
        "version": 7,
        "status": "implementing",
        "data": {
            "engineering": {
                "plan_confirmation": {
                    "accepted": True,
                    "candidate_fingerprint": "sha256:" + "1" * 64,
                },
                "plan": {
                    "plan_id": "PLAN-EA-1111111111111111-R1",
                    "assessment_ref": {
                        "work_item_id": work_item_id,
                        "assessment_id": "EA-1111111111111111",
                        "assessment_revision": 1,
                    },
                    "change_context": {
                        "project_product_definition_path": (
                            "docs/product/definition.yaml"
                        )
                    },
                    "operations": [
                        {
                            "action": "create",
                            "path": "docs/product/definition.yaml",
                            "long_lived_artifact": {
                                "artifact_id": TEST_PRODUCT_ID,
                                "artifact_type": "product_governance",
                            },
                        }
                    ],
                },
            },
            "git": {
                "schema_version": "strixnova.git-work-area.v1",
                "repository": str(project.resolve()),
                "work_item_id": work_item_id,
                "target_ref": "main",
                "base_commit": base_commit,
                "worktree_path": str(project),
                "work_ref": branch,
                "worktree_mode": "in_place",
                "created_by_strixnova": True,
                "merge_strategy": "no_ff",
            },
        },
    }
    return item, path


def _ready_policy_project(project: Path) -> tuple[dict, Path, Path]:
    item, product_path = _ready_product_project(project)
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    product["revision"].update(
        {
            "status": "confirmed",
            "confirmed_by_owner_id": TEST_OWNER_ID,
            "confirmed_on": "2026-08-23",
        }
    )
    product_path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    baseline = yaml.safe_load(baseline_path.read_text(encoding="utf-8"))
    baseline["authority_refs"]["product_definition"]["status"] = {
        "revision_status": "confirmed",
        "adoption_status": "current",
    }
    policy_path = project / "docs" / "engineering" / "policy.yaml"
    source_path = project / "docs" / "engineering" / "project-method.md"
    source_path.write_text("# Project method\n", encoding="utf-8")
    policy = yaml.safe_load(policy_path.read_text(encoding="utf-8"))
    policy["revision"].update(
        {
            "status": "ready_for_confirmation",
            "confirmed_by_owner_id": None,
            "confirmed_on": None,
        }
    )
    policy["project_sources"] = [
        {
            "source_id": "project-method",
            "title": "Project method",
            "path": "docs/engineering/project-method.md",
            "status": "current",
            "usage": "Defines the project-specific engineering method.",
        }
    ]
    policy_path.write_text(
        yaml.safe_dump(policy, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    baseline["authority_refs"]["engineering_policy"]["status"] = {
        "revision_status": "ready_for_confirmation",
        "adoption_status": "under_review",
    }
    baseline["review_state"] = {
        "required": True,
        "reasons": ["工程政策候选等待独立负责人确认。"],
        "affected_authority_kinds": ["engineering_policy"],
    }
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    plan = item["data"]["engineering"]["plan"]
    plan.update(
        {
            "investigation_ref": "working_tree",
            "change_context": {
                "project_engineering_policy_path": (
                    "docs/engineering/policy.yaml"
                )
            },
            "operations": [
                {
                    "action": "modify",
                    "path": "docs/engineering/policy.yaml",
                    "long_lived_artifact": {
                        "artifact_id": TEST_POLICY_ID,
                        "artifact_type": "quality_policy",
                    },
                }
            ],
        },
    )
    return item, policy_path, source_path


def _accepted_record(project: Path, item: dict) -> dict:
    candidate = project_authority_candidate(
        project,
        item,
        "product_definition",
    )
    challenge = authority_confirmation_challenge(item, candidate)
    confirmation = confirmation_record_from_input(
        challenge,
        {
            "candidate_fingerprint": challenge["candidate_fingerprint"],
            "user_confirmation": "I accept the displayed candidate.",
            "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
        },
    )
    transaction = build_project_authority_confirmation_transaction(
        project,
        item,
        [{"candidate": candidate, "accepted": True}],
        confirmed_on="2026-08-28",
    )
    apply_project_authority_confirmation_transaction(project, transaction)
    confirmed = confirmed_project_authority_snapshot(project, item, candidate)
    return {
        "schema_version": PROJECT_AUTHORITY_DECISION_SCHEMA,
        "authority_kind": "product_definition",
        "candidate": candidate,
        "confirmation_challenge": challenge,
        "confirmation": confirmation,
        "confirmed_at": "2026-08-28T01:02:03Z",
        "confirmed_on": confirmed["confirmed_on"],
        "confirmed_content_sha256": confirmed["confirmed_content_sha256"],
        "semantic_content_machine_proven": False,
    }


def _allow_reviewed_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    item: dict,
) -> None:
    """Keep transaction tests focused on file recovery, not review assembly."""

    bundle = {
        "schema_version": "strixnova.project-authority-review-bundle.v1",
        "content_sha256": "a" * 64,
    }
    monkeypatch.setattr(
        application_coordinator_module,
        "current_action_for",
        lambda _item: {
            "action_type": "confirm_project_authority_candidates",
        },
    )
    monkeypatch.setattr(
        application_coordinator_module,
        "current_project_authority_presentations",
        lambda _item: list(
            _item["data"]["project_authority_presentations"]
        ),
    )
    monkeypatch.setattr(
        application_coordinator_module,
        "current_project_authority_review",
        lambda _item: {"candidate_bundle": bundle},
    )
    monkeypatch.setattr(
        application_coordinator_module,
        "project_authority_review_bundle",
        lambda _project, _item, _presentations: bundle,
    )


def test_owner_decision_binds_candidate_and_confirmed_content(tmp_path: Path) -> None:
    item, _path = _ready_product_project(tmp_path)

    record = _accepted_record(tmp_path, item)
    confirmed = validate_project_authority_decision(tmp_path, item, record)

    assert record["candidate"]["artifact_id"] == TEST_PRODUCT_ID
    assert record["candidate"]["revision_id"] == TEST_PRODUCT_REVISION_ID
    assert record["candidate"]["owner_id"] == TEST_OWNER_ID
    assert confirmed["confirmed_content_sha256"] == record[
        "confirmed_content_sha256"
    ]
    baseline = yaml.safe_load(
        (tmp_path / "docs" / "engineering" / "baseline.yaml").read_text(
            encoding="utf-8"
        )
    )
    assert baseline["authority_refs"]["product_definition"]["status"] == {
        "revision_status": "confirmed",
        "adoption_status": "current",
    }
    assert baseline["review_state"] == {
        "required": False,
        "reasons": [],
        "affected_authority_kinds": [],
    }


def test_execution_reads_confirmed_unmerged_authority_from_its_exact_decision(tmp_path: Path) -> None:
    from strixnova.work_item_read_model import WorkItemReadModel

    item, product_path = _ready_product_project(tmp_path)
    record = _accepted_record(tmp_path, item)
    item["data"]["project_authority_decisions"] = [record]
    before = product_path.read_bytes()
    result = WorkItemReadModel(tmp_path).execution_context(item)
    rules = result["project_rules"]
    assert rules["basis_kind"] == "confirmed_execution_candidate"
    assert rules["product_guardrails"]["product_id"] == TEST_PRODUCT_ID
    assert rules["confirmed_decisions"][0]["confirmed_content_sha256"] == record["confirmed_content_sha256"]
    assert product_path.read_bytes() == before


def test_execution_does_not_use_authority_changed_after_owner_confirmation(tmp_path: Path) -> None:
    from strixnova.project_authority_consistency import ProjectAuthorityConsistencyError
    from strixnova.work_item_read_model import WorkItemReadModel

    item, product_path = _ready_product_project(tmp_path)
    record = _accepted_record(tmp_path, item)
    item["data"]["project_authority_decisions"] = [record]
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    product["purpose"] += " Changed after confirmation."
    product_path.write_text(yaml.safe_dump(product, allow_unicode=True, sort_keys=False), encoding="utf-8")
    with pytest.raises(ProjectAuthorityConsistencyError) as raised:
        WorkItemReadModel(tmp_path).execution_context(item)
    assert "确认后" in str(raised.value)


def test_product_candidate_rejects_owner_different_from_project_baseline(
    tmp_path: Path,
) -> None:
    item, path = _ready_product_project(tmp_path)
    product = yaml.safe_load(path.read_text(encoding="utf-8"))
    product["product_owner"]["owner_id"] = "OWNER-2222222222222222"
    path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectAuthorityDecisionError) as raised:
        project_authority_candidate(tmp_path, item, "product_definition")

    assert raised.value.code == "project_authority_owner_mismatch"


def test_candidate_fingerprint_changes_when_only_yaml_comment_changes(
    tmp_path: Path,
) -> None:
    item, path = _ready_product_project(tmp_path)
    before = project_authority_candidate(tmp_path, item, "product_definition")
    path.write_bytes(path.read_bytes() + b"\n# exact-candidate-comment\n")

    after = project_authority_candidate(tmp_path, item, "product_definition")

    assert after["content_sha256"] != before["content_sha256"]


def test_engineering_policy_candidate_binds_project_sources(
    tmp_path: Path,
) -> None:
    item, _policy_path, source_path = _ready_policy_project(tmp_path)

    before = project_authority_candidate(
        tmp_path,
        item,
        "engineering_policy",
    )
    presentation = {
        "authority_kind": "engineering_policy",
        "candidate": before,
    }
    bundle = project_authority_review_bundle(
        tmp_path,
        item,
        [presentation],
    )
    reviewed_policy = next(
        candidate
        for candidate in bundle["candidates"]
        if candidate["authority_kind"] == "engineering_policy"
    )
    source_path.write_text(
        "# Project method\n\nChanged.\n",
        encoding="utf-8",
    )
    after = project_authority_candidate(
        tmp_path,
        item,
        "engineering_policy",
    )

    assert before["governed_paths"] == [
        "docs/engineering/policy.yaml",
        "docs/engineering/project-method.md",
    ]
    assert reviewed_policy["governed_paths"] == before["governed_paths"]
    assert reviewed_policy["content_sha256"] == before["content_sha256"]
    assert after["content_sha256"] != before["content_sha256"]


def test_authority_challenge_stays_bound_to_candidate_across_item_versions(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    candidate = project_authority_candidate(tmp_path, item, "product_definition")
    later_item = dict(item)
    later_item["version"] = item["version"] + 1

    challenge = authority_confirmation_challenge(
        later_item,
        candidate,
    )

    assert challenge == authority_confirmation_challenge(item, candidate)
    assert challenge["decision_label"] == "当前展示的产品定义候选"
    assert challenge["decision_interpreter"] == "coding_agent"
    assert "accept_text" not in challenge
    assert "confirmation_token" not in challenge


def test_authority_candidate_changes_when_confirmed_plan_changes(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    before = project_authority_candidate(tmp_path, item, "product_definition")
    replacement = yaml.safe_load(yaml.safe_dump(item))
    replacement["data"]["engineering"]["plan"]["plan_id"] = (
        "PLAN-EA-1111111111111111-R2"
    )
    replacement["data"]["engineering"]["plan"]["assessment_ref"][
        "assessment_revision"
    ] = 2
    replacement["data"]["engineering"]["plan_confirmation"][
        "candidate_fingerprint"
    ] = "sha256:" + "3" * 64

    after = project_authority_candidate(
        tmp_path,
        replacement,
        "product_definition",
    )

    assert after["plan_ref"] != before["plan_ref"]
    assert authority_confirmation_challenge(
        replacement,
        after,
    )["candidate_fingerprint"] != authority_confirmation_challenge(
        item,
        before,
    )["candidate_fingerprint"]


def test_exact_owner_decision_is_carried_forward_after_safe_replanning(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    record = _accepted_record(tmp_path, item)
    replacement = yaml.safe_load(yaml.safe_dump(item))
    replacement["data"]["engineering"]["plan"]["plan_id"] = (
        "PLAN-EA-1111111111111111-R2"
    )
    replacement["data"]["engineering"]["plan"]["assessment_ref"][
        "assessment_revision"
    ] = 2
    replacement["data"]["engineering"]["plan_confirmation"][
        "candidate_fingerprint"
    ] = "sha256:" + "3" * 64

    confirmed = validate_project_authority_decision(
        tmp_path,
        replacement,
        record,
    )

    assert confirmed["revision_id"] == record["candidate"]["revision_id"]
    assert confirmed["confirmed_content_sha256"] == record[
        "confirmed_content_sha256"
    ]


def test_carried_forward_decision_revalidates_current_plan_change_targets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    record = _accepted_record(tmp_path, item)
    replacement = yaml.safe_load(yaml.safe_dump(item))
    replacement["data"]["engineering"]["plan"]["plan_id"] = (
        "PLAN-EA-1111111111111111-R2"
    )
    replacement["data"]["engineering"]["plan"]["assessment_ref"][
        "assessment_revision"
    ] = 2
    observed: list[tuple[str, str, str]] = []

    def _record_validation(
        _project: Path,
        current: dict,
        authority_kind: str,
        value: dict,
    ) -> None:
        observed.append(
            (
                current["data"]["engineering"]["plan"]["plan_id"],
                authority_kind,
                value["revision"]["status"],
            )
        )

    monkeypatch.setattr(
        project_authority_decision_module,
        "validate_authority_change_targets",
        _record_validation,
    )

    validate_project_authority_decision(tmp_path, replacement, record)

    assert observed == [
        (
            "PLAN-EA-1111111111111111-R2",
            "product_definition",
            "confirmed",
        )
    ]


def test_authority_confirmation_scope_requires_future_governance_candidates(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    plan = item["data"]["engineering"]["plan"]
    plan["operations"].append(
        {
            "action": "create",
            "path": "docs/domain/model.yaml",
            "long_lived_artifact": {
                "artifact_id": "MODEL-2222222222222222",
                "artifact_type": "domain_model",
            },
        }
    )
    plan["implementation_slices"] = [
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
            "verification_command_ids": [],
        },
    ]

    with pytest.raises(ProjectAuthorityDecisionError) as captured:
        application_coordinator_module.planned_project_authority_paths(
            tmp_path,
            item,
        )

    assert captured.value.code == "project_authority_candidate_identity_mismatch"


def test_public_candidate_rejects_changed_worktree_binding_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    subprocess.run(
        ["git", "switch", "-c", "other"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    coordinator = ApplicationCoordinator(tmp_path)
    monkeypatch.setattr(coordinator.authority, "get", lambda _identifier: item)

    with pytest.raises(ApplicationCoordinatorError) as raised:
        coordinator.project_authority_candidate(
            item["work_item_id"],
            "product_definition",
            expected_version=item["version"],
        )

    assert raised.value.code == "worktree_binding_changed"


def test_review_stage_can_represent_a_changed_authority_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, path = _ready_product_project(tmp_path)
    original = project_authority_candidate(
        tmp_path,
        item,
        "product_definition",
    )
    challenge = authority_confirmation_challenge(item, original)
    item["version"] += 1
    item["data"]["project_authority_presentations"] = [
        {
            "schema_version": "strixnova.project-authority-presentation.v1",
            "authority_kind": "product_definition",
            "candidate": original,
            "confirmation_challenge": challenge,
            "presented_at": "2026-09-03T01:01:01Z",
            "presented_at_work_item_version": item["version"],
            "semantic_content_machine_proven": False,
        }
    ]
    item["current_action"] = current_action_for(item)
    assert item["current_action"]["action_type"] == (
        "review_project_authority_candidates"
    )
    path.write_bytes(path.read_bytes() + b"\n# changed-after-presentation\n")
    coordinator = ApplicationCoordinator(tmp_path)
    monkeypatch.setattr(coordinator.authority, "get", lambda _identifier: item)
    transitioned: dict[str, object] = {}

    def record_presentation(
        _identifier: str,
        action: str,
        body: dict,
        *,
        expected_version: int,
    ) -> dict:
        transitioned.update(
            {
                "action": action,
                "body": body,
                "expected_version": expected_version,
            }
        )
        updated = yaml.safe_load(yaml.safe_dump(item))
        updated["version"] += 1
        updated["data"]["project_authority_presentations"].append(
            body["project_authority_presentation"]
        )
        updated["current_action"] = current_action_for(updated)
        return updated

    monkeypatch.setattr(
        coordinator.authority,
        "transition",
        record_presentation,
    )

    refreshed = coordinator.project_authority_candidate(
        item["work_item_id"],
        "product_definition",
        expected_version=item["version"],
    )

    assert refreshed["candidate"]["content_sha256"] != original[
        "content_sha256"
    ]
    assert refreshed["presented_at_work_item_version"] == item["version"] + 1
    assert transitioned["action"] == "record_project_authority_presentation"


def test_planned_authority_move_reads_the_explicit_destination(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    destination = "docs/product/product-definition.yaml"
    operation = item["data"]["engineering"]["plan"]["operations"][0]
    operation["action"] = "move"
    operation["to_path"] = destination
    item["data"]["engineering"]["plan"]["authority_change_set"] = {
        "candidate_authorities": [
            {
                "authority_kind": "product_definition",
                "revision_id": "REVISION-2222222222222222",
                "path": destination,
            }
        ]
    }

    planned = project_authority_decision_module._planned_candidate_ref(
        item,
        "product_definition",
    )

    assert planned["path"] == destination



def test_preconfirmed_upstream_file_cannot_replace_owner_decision(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    candidate = project_authority_candidate(tmp_path, item, "product_definition")
    transaction = build_project_authority_confirmation_transaction(
        tmp_path,
        item,
        [{"candidate": candidate, "accepted": True}],
        confirmed_on="2026-08-28",
    )
    apply_project_authority_confirmation_transaction(tmp_path, transaction)

    with pytest.raises(VerificationRunnerError) as raised:
        ApplicationCoordinator._require_upstream_authority_decisions(
            item,
            {"changed_authority_kinds": ["product_definition"]},
            project_dir=tmp_path,
        )

    assert raised.value.code == "project_authority_decision_missing"


def test_planned_upstream_decision_is_required_before_any_verification(
    tmp_path: Path,
) -> None:
    item, _path = _ready_product_project(tmp_path)

    with pytest.raises(VerificationRunnerError) as raised:
        ApplicationCoordinator._require_planned_upstream_authority_decisions(
            item,
            project_dir=tmp_path,
        )

    assert raised.value.code == "project_authority_decision_missing"

    record = _accepted_record(tmp_path, item)
    item["data"]["project_authority_decisions"] = [record]
    ApplicationCoordinator._require_planned_upstream_authority_decisions(
        item,
        project_dir=tmp_path,
    )


def test_owner_decision_is_rejected_after_business_implementation_started(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, _path = _ready_product_project(tmp_path)
    item["data"]["engineering"]["plan"]["operations"].append(
        {"action": "create", "path": "src/business.py"}
    )
    monkeypatch.setattr(
        application_coordinator_module,
        "planned_project_authority_paths",
        lambda *_args, **_kwargs: ["docs/product/definition.yaml"],
    )
    monkeypatch.setattr(
        application_coordinator_module.GitWorkspace,
        "changed_paths",
        lambda *_args, **_kwargs: [
            "docs/product/definition.yaml",
            "src/business.py",
        ],
    )

    with pytest.raises(VerificationRunnerError) as raised:
        ApplicationCoordinator._require_authority_confirmation_path_scope(
            item,
            project_dir=tmp_path,
        )

    assert raised.value.code == "project_authority_decision_too_late"
    assert raised.value.details == ["src/business.py"]


def test_owner_decision_rejects_content_changed_after_acceptance(
    tmp_path: Path,
) -> None:
    item, path = _ready_product_project(tmp_path)
    record = _accepted_record(tmp_path, item)
    product = yaml.safe_load(path.read_text(encoding="utf-8"))
    product["purpose"] = "负责人接受之后被改写的正文"
    path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectAuthorityDecisionError) as raised:
        validate_project_authority_decision(tmp_path, item, record)

    assert raised.value.code == "project_authority_decision_content_changed"


def test_coordinator_restores_exact_bytes_when_decision_record_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, path = _ready_product_project(tmp_path)
    original = path.read_bytes()
    coordinator = ApplicationCoordinator(tmp_path)
    candidate = project_authority_candidate(
        tmp_path,
        item,
        "product_definition",
    )
    challenge = authority_confirmation_challenge(item, candidate)
    payload = {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "I accept the displayed candidate.",
        "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
    }
    item["version"] += 1
    item["data"]["project_authority_presentations"] = [
        {
            "schema_version": "strixnova.project-authority-presentation.v1",
            "authority_kind": "product_definition",
            "candidate": candidate,
            "confirmation_challenge": challenge,
            "presented_at": "2026-08-28T01:01:01Z",
            "presented_at_work_item_version": item["version"],
            "semantic_content_machine_proven": False,
        }
    ]
    _allow_reviewed_confirmation(monkeypatch, item)
    monkeypatch.setattr(coordinator.authority, "get", lambda _identifier: item)
    monkeypatch.setattr(
        coordinator,
        "_require_current_slice_path_scope",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        coordinator,
        "_require_authority_confirmation_path_scope",
        lambda *_args, **_kwargs: None,
    )

    def fail_transition(
        _identifier: str,
        action: str,
        body: dict,
        **_kwargs: object,
    ) -> dict:
        if action == "claim_external_effect":
            claimed = yaml.safe_load(yaml.safe_dump(item))
            claimed["version"] += 1
            claimed["data"]["pending_effect"] = {
                "kind": body["kind"],
                "intent": body["intent"],
            }
            return claimed
        raise RuntimeError("injected authority database failure")

    monkeypatch.setattr(coordinator.authority, "transition", fail_transition)

    with pytest.raises(RuntimeError, match="injected authority database failure"):
        coordinator.confirm_project_authorities(
            item["work_item_id"],
            {
                "decisions": [
                    {
                        "authority_kind": "product_definition",
                        **payload,
                    }
                ]
            },
            expected_version=item["version"],
        )

    assert path.read_bytes() == original


def test_confirmation_recovers_after_files_were_written_before_decision_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item, path = _ready_product_project(tmp_path)
    coordinator = ApplicationCoordinator(tmp_path)
    candidate = project_authority_candidate(
        tmp_path,
        item,
        "product_definition",
    )
    challenge = authority_confirmation_challenge(item, candidate)
    payload = {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "I accept the displayed candidate.",
        "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
    }
    item["version"] += 1
    item["data"]["project_authority_presentations"] = [
        {
            "schema_version": "strixnova.project-authority-presentation.v1",
            "authority_kind": "product_definition",
            "candidate": candidate,
            "confirmation_challenge": challenge,
            "presented_at": "2026-08-28T01:01:01Z",
            "presented_at_work_item_version": item["version"],
            "semantic_content_machine_proven": False,
        }
    ]
    _allow_reviewed_confirmation(monkeypatch, item)
    state = yaml.safe_load(yaml.safe_dump(item))
    crash_once = True

    def get_state(_identifier: str) -> dict:
        return state

    def transition(
        _identifier: str,
        action: str,
        body: dict,
        **_kwargs: object,
    ) -> dict:
        nonlocal state, crash_once
        if action == "claim_external_effect":
            state = yaml.safe_load(yaml.safe_dump(state))
            state["version"] += 1
            state["data"]["pending_effect"] = {
                "kind": body["kind"],
                "intent": body["intent"],
            }
            return state
        if action == "record_project_authority_decision_bundle":
            if crash_once:
                crash_once = False
                raise KeyboardInterrupt("injected process interruption")
            state = yaml.safe_load(yaml.safe_dump(state))
            state["version"] += 1
            state["data"]["project_authority_decisions"] = body[
                "project_authority_decisions"
            ]
            state["data"]["pending_effect"] = None
            return state
        raise AssertionError(action)

    monkeypatch.setattr(coordinator.authority, "get", get_state)
    monkeypatch.setattr(coordinator.authority, "transition", transition)
    monkeypatch.setattr(
        coordinator,
        "_require_current_slice_path_scope",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        coordinator,
        "_require_authority_confirmation_path_scope",
        lambda *_args, **_kwargs: None,
    )

    with pytest.raises(KeyboardInterrupt, match="process interruption"):
        coordinator.confirm_project_authorities(
            item["work_item_id"],
            {
                "decisions": [
                    {
                        "authority_kind": "product_definition",
                        **payload,
                    }
                ]
            },
            expected_version=item["version"],
        )

    assert yaml.safe_load(path.read_text(encoding="utf-8"))["revision"][
        "status"
    ] == "confirmed"
    recovered = coordinator.confirm_project_authorities(
        item["work_item_id"],
        {
            "decisions": [
                {
                    "authority_kind": "product_definition",
                    **payload,
                }
            ]
        },
        expected_version=state["version"],
    )

    assert recovered["data"]["pending_effect"] is None
    assert recovered["data"]["project_authority_decisions"][0][
        "confirmed_content_sha256"
    ]
