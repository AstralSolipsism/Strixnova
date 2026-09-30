from __future__ import annotations

from tests.support.project_context import FRONTEND

from tests.support.project_configuration import configure_repository

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from strixnova.git_project_reader import GitProjectReader
from tests.support.implementation_alignment import observation_coverage
from strixnova.verification_runner import (
    VerificationRunner,
    normalize_verification_commands,
)
from strixnova.project_engineering_baseline import ProjectEngineeringBaseline
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_authority_progress import ProjectAuthorityDecisionError
from strixnova.project_authority_decision import validate_authority_change_targets
from strixnova.work_item_read_model import (
    ProjectIntegrationReferenceError,
    WorkItemReadModel,
)
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.governance_assessment import assessment_fixture
from tests.support.project_baseline import (
    adopt_portable_ddd,
    portable_project_baseline,
)
from tests.support.verification_approval import (
    approval_expectations,
    approved_verification_request,
)


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _adopt_test_authorities(repo: Path) -> tuple[str, str]:
    (repo / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Strixnova Tests")
    _git(repo, "config", "user.email", "strixnova@example.invalid")
    _git(repo, "add", "src.py")
    _git(repo, "commit", "-m", "initial evidence")
    evidence_commit = _git(repo, "rev-parse", "HEAD")

    baseline = portable_project_baseline(
        repo,
        baseline_id="adopted-candidate-base",
        artifacts=[],
    )
    identities = adopt_portable_ddd(repo, baseline)
    baseline["code_version"]["repositories"][0]["base_commit"] = evidence_commit
    baseline["review_state"] = {
        "required": False,
        "reasons": [],
        "affected_authority_kinds": [],
    }
    baseline_path = repo / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_path = repo / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    source_digest = hashlib.sha256(
        GitProjectReader(repo).read_canonical_bytes(
            "src.py",
            "测试行为文件",
        )
    ).hexdigest()
    alignment["code_snapshot"].update(
        {'repositories': [{'repository_id': FRONTEND, 'base_commit': evidence_commit, 'worktree_state': alignment['code_snapshot']['repositories'][0]['worktree_state']}], 'governed_source_manifest_sha256': hashlib.sha256(f'{FRONTEND}:src.py:{source_digest}\n'.encode('utf-8')).hexdigest()}
    )
    ownership_path = repo / alignment["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["sha256"] = source_digest
    ownership_path.write_text(
        yaml.safe_dump(ownership, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment["observation_coverage"] = observation_coverage(repo, alignment)
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(repo, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "adopt project authorities")
    return identities["alignment_path"], _git(repo, "rev-parse", "HEAD")


def _revise_alignment_candidate(repo: Path, alignment_path: str) -> str:
    manifest_path = repo / alignment_path
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    adopted_revision = manifest["revision"]["revision_id"]
    candidate_revision = "ALIGNREV-2222222222222222"
    manifest["revision"] = {
        "revision_id": candidate_revision,
        "status": "draft",
        "supersedes_revision_id": adopted_revision,
        "confirmed_by_owner_id": None,
        "confirmed_on": None,
    }
    manifest_path.write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for artifact_path in manifest["artifact_paths"].values():
        path = repo / artifact_path
        artifact = yaml.safe_load(path.read_text(encoding="utf-8"))
        artifact["alignment_revision_id"] = candidate_revision
        path.write_text(
            yaml.safe_dump(artifact, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return candidate_revision


def test_implementation_alignment_candidate_cannot_hide_an_undeclared_identity(
    tmp_path: Path,
) -> None:
    _alignment_path, adopted_commit = _adopt_test_authorities(tmp_path)
    adopted = ProjectAuthorityConsistency(
        tmp_path,
        observed_ref=adopted_commit,
    ).load()
    candidate = adopted["implementation_alignment"]
    candidate["deviations"] = [
        {
            "deviation_id": "DEVIATION-3333333333333333",
        }
    ]
    item = {
        "data": {
            "engineering": {
                "assessment": {"investigation_ref": adopted_commit},
                "plan_confirmation": {"accepted": True},
                "plan": {
                    "authority_change_set": {
                        "changes": [
                            {
                                "authority_kind": "implementation_alignment",
                                "operation": "modify",
                                "target_ref": candidate["alignment_model_id"],
                            }
                        ]
                    }
                },
            }
        }
    }

    with pytest.raises(ProjectAuthorityDecisionError) as captured:
        validate_authority_change_targets(
            tmp_path,
            item,
            "implementation_alignment",
            candidate,
        )

    assert captured.value.code == (
        "project_authority_candidate_change_set_mismatch"
    )
    assert any(
        "DEVIATION-3333333333333333" in detail
        for detail in captured.value.details
    )


def _direction(relations: list[dict] | None = None) -> dict:
    direction = {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
        "goal": "减少必要测试等待",
        "scope": [
            {
                "requirement_id": "DIRREQ-1111111111111111",
                "statement": "测试结构",
            }
        ],
        "non_goals": ["删除必要覆盖"],
        "constraints": [
            {
                "constraint_id": "DIRCON-2222222222222222",
                "statement": "保留独立行为价值",
            }
        ],
        "acceptance": [
            {
                "acceptance_id": "DIRACC-3333333333333333",
                "statement": "报告实际测试结果",
                "requirement_refs": ["DIRREQ-1111111111111111"],
                "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
            }
        ],
        "tradeoffs": ["不设置人为耗时门槛"],
    }
    if relations is not None:
        direction["work_item_relations"] = relations
    return direction


def _confirmation_payload(
    authority: WorkflowAuthority,
    work_item_id: str,
) -> dict[str, str]:
    challenge = authority.get(work_item_id)["current_action"][
        "confirmation_challenge"
    ]
    return {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "I accept the displayed candidate.",
        "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
    }


def test_empty_read_model_is_read_only_before_intake(tmp_path: Path) -> None:
    overview = WorkItemReadModel(tmp_path).overview()

    assert overview["summary"]["total"] == 0
    assert overview["revision"]["revision"] == 0
    assert not (tmp_path / ".strixnova").exists()


def test_all_views_read_the_same_authority_and_current_action(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="优化测试", raw_request="测试太慢")
    identifier = created["work_item_id"]
    authority.transition(
        identifier,
        "submit_direction",
        {"direction": _direction(), "ready_for_confirmation": True},
        expected_version=1,
    )
    reader = WorkItemReadModel(tmp_path)

    overview = reader.overview(identifier)
    listing = reader.work_items()
    detail = reader.work_item(identifier)

    assert overview["focus"]["work_item_id"] == identifier
    assert overview["focus"]["current_action"] == (
        listing["work_items"][0]["current_action"]
    )
    assert detail["work_item"]["current_action"] == (
        overview["focus"]["current_action"]
    )
    assert overview["summary"]["awaiting_user"] == 1
    assert overview["project"]["engineering_baseline"] is None
    assert detail["git_status"] is None
    assert "relations" not in overview["focus"]
    assert "relations" not in listing["work_items"][0]
    assert detail["work_item"]["relations"] == {
        "declared": [],
        "referenced_by": [],
    }


def test_confirmed_relation_is_projected_both_ways_without_writing_target(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    target = authority.create(title="基础事项", raw_request="建立基础能力")
    source = authority.create(title="延续事项", raw_request="继续建设")
    target_id = target["work_item_id"]
    source_id = source["work_item_id"]
    relation = {
        "target_work_item_id": target_id,
        "relation_type": "follows_up",
        "reason": "延续事项承接基础事项的已确认方向。",
    }
    proposed = authority.transition(
        source_id,
        "submit_direction",
        {
            "direction": _direction([relation]),
            "ready_for_confirmation": True,
        },
        expected_version=source["version"],
    )
    reader = WorkItemReadModel(tmp_path)
    assert reader.work_item_relations(source_id)["declared"] == []
    assert reader.work_item_relations(target_id)["referenced_by"] == []
    assert all(
        "relations" not in item
        for item in reader.work_items()["work_items"]
    )
    target_history_before = authority.history(target_id)

    confirmed = authority.transition(
        source_id,
        "confirm_direction",
        _confirmation_payload(authority, source_id),
        expected_version=proposed["version"],
    )
    source_relations = reader.work_item_relations(source_id)
    target_relations = reader.work_item_relations(target_id)
    edge = {
        "source_work_item_id": source_id,
        "target_work_item_id": target_id,
        "relation_type": "follows_up",
        "reason": relation["reason"],
    }

    assert source_relations["declared"] == [
        {
            **edge,
            "related_work_item": {
                "work_item_id": target_id,
                "title": "基础事项",
                "status": "discussion",
            },
        }
    ]
    assert target_relations["referenced_by"] == [
        {
            **edge,
            "related_work_item": {
                "work_item_id": source_id,
                "title": "延续事项",
                "status": confirmed["status"],
            },
        }
    ]
    assert reader.work_item(target_id)["work_item"]["relations"] == (
        target_relations
    )
    assert authority.get(target_id)["version"] == target["version"]
    assert authority.history(target_id) == target_history_before


def test_decision_impact_and_trace_are_views_of_the_engineering_assessment(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="事项", raw_request="优化测试")
    identifier = created["work_item_id"]
    authority.transition(
        identifier,
        "submit_direction",
        {"direction": _direction(), "ready_for_confirmation": True},
        expected_version=1,
    )
    authority.transition(
        identifier,
        "confirm_direction",
        _confirmation_payload(authority, identifier),
        expected_version=2,
    )
    assessment = assessment_fixture(tmp_path)
    authority.transition(
        identifier,
        "submit_engineering_assessment",
        {
            "assessment": assessment,
            "plan": {
                "change_context": {"formal_implementation": True},
                "method_applications": [],
                "verification_commands": normalize_verification_commands(
                    assessment["verification_commands"]
                ),
            },
        },
        expected_version=3,
    )
    reader = WorkItemReadModel(tmp_path)

    decisions = reader.decisions(identifier)
    impact = reader.impact(identifier)
    verification = reader.verification(identifier)

    assert "requirements" not in decisions["engineering_assessment"]
    assert decisions["direction"]["scope"] == _direction()["scope"]
    assert decisions["engineering_assessment"]["design_decisions"] == (
        assessment["design_decisions"]
    )
    assert impact["impact_scope"] == assessment["impact_scope"]
    assert impact["risk_assessments"] == assessment["risk_assessments"]
    assert impact["operations"] == assessment["operations"]
    trace = impact["management_trace"]
    assert trace["graph_kind"] == "engineering_management_trace"
    assert any(
        node["id"] == "direction.requirement:DIRREQ-1111111111111111"
        for node in trace["nodes"]
    )
    assert any(node["id"] == "VC-001" for node in trace["nodes"])
    assert {
        "source": "direction",
        "target": "direction.requirement:DIRREQ-1111111111111111",
        "type": "contains",
    } in trace["edges"]
    assert verification["commands"][0]["command_id"] == "VC-001"
    assert verification["coverage"]["verification_status"] == "pending"
    assert decisions["engineering_method_confirmation"] == {
        "coding_agent_assessed": False,
        "machine_validated": False,
        "included_in_confirmed_plan": False,
        "confirmation_scope": "engineering_plan",
        "explicit_method_name_confirmation": False,
        "applications": [],
    }

    serialized = json.dumps(
        {"decisions": decisions, "impact": impact, "verification": verification},
        ensure_ascii=False,
    )
    assert "ProjectMap" not in serialized
    assert "CodeFacts" not in serialized
    assert "file_sha256" not in serialized
    assert "excerpt_sha256" not in serialized


def test_read_model_exposes_separate_project_authority_and_implementation_status(
    monkeypatch,
    tmp_path: Path,
) -> None:
    _alignment_path, adopted_commit = _adopt_test_authorities(tmp_path)
    reader = WorkItemReadModel(tmp_path)
    monkeypatch.setattr(
        reader,
        "_integrated_baseline_reader",
        lambda _item: ProjectEngineeringBaseline(
            tmp_path,
            observed_ref=adopted_commit,
        ),
    )
    monkeypatch.setattr(reader.authority, "list", lambda: [])
    authority_validation_calls = 0
    load_authorities = ProjectAuthorityConsistency.load

    def counted_validation(self):
        nonlocal authority_validation_calls
        if self._cache is None:
            authority_validation_calls += 1
        return load_authorities(self)

    monkeypatch.setattr(
        ProjectAuthorityConsistency,
        "load",
        counted_validation,
    )

    project = reader._project_summary(None)
    assert authority_validation_calls == 1
    long_lived = reader._long_lived_engineering(None)
    assert authority_validation_calls == 2

    assert project["engineering_baseline"]["authority_statuses"][
        "implementation_alignment"
    ]["adoption_status"] == "current"
    assert long_lived is not None
    domain_model = long_lived["domain_model"]
    assert domain_model["model_id"]
    assert domain_model["title"]
    assert domain_model["collection_count"] > 0
    assert domain_model["source_count"] > 0
    assert domain_model["fact_count"] > 0
    assert domain_model["retired_fact_count"] >= 0
    assert domain_model["bodies_included"] is False
    assert long_lived["implementation_alignment"]["alignment_model_id"]
    assert long_lived["implementation_alignment"][
        "target_responsibility_count"
    ] > 0
    assert long_lived["implementation_alignment"][
        "semantic_content_machine_proven"
    ] is False
    assert long_lived["engineering_methods"][0]["status"] == "adopted"
    status = project["engineering_baseline"]["status_view"]
    assert status["product_definition"]["revision_status"] == "confirmed"
    assert status["domain_model"]["active_fact_count"] == domain_model["fact_count"]
    assert status["target_architecture"]["module_count"] > 0
    assert status["implementation_alignment"]["review_required"] is False
    assert status["isolated_install_acceptance"]["status"] == "not_recorded"
    assert status["overall_usability_machine_decided"] is False


def test_project_summary_does_not_adopt_the_working_tree_without_a_git_ref(
    tmp_path: Path,
) -> None:
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="unadopted-working-tree",
        artifacts=[],
    )
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)
    reader = WorkItemReadModel(tmp_path)

    assert reader._project_summary(None)["engineering_baseline"] is None
    assert reader._long_lived_engineering(None) is None


def test_project_status_explicitly_validates_a_working_tree_candidate(
    tmp_path: Path,
) -> None:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Tests")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "initial evidence")
    evidence_commit = _git(tmp_path, "rev-parse", "HEAD")

    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="working-tree-candidate",
        artifacts=[],
    )
    identities = adopt_portable_ddd(tmp_path, baseline)
    baseline["code_version"]["repositories"][0]["base_commit"] = evidence_commit
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_path = tmp_path / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    alignment["code_snapshot"]["repositories"][0]["base_commit"] = evidence_commit
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)

    reader = WorkItemReadModel(tmp_path)
    adopted = reader.project_status()
    candidate = reader.project_status(working_tree=True)

    assert adopted["authority_scope"] == "unadopted_project"
    assert adopted["baseline_id"] is None
    assert candidate["authority_scope"] == "working_tree_candidate"
    assert candidate["candidate_only"] is True
    assert candidate["observed_commit"] is None
    assert candidate["baseline_id"] == baseline["baseline_id"]
    assert candidate["cross_authority_consistency"][
        "structurally_consistent"
    ] is True
    assert candidate["cross_authority_consistency"][
        "semantic_correctness_machine_proven"
    ] is False

    successor_revision = _revise_alignment_candidate(
        tmp_path,
        identities["alignment_path"],
    )
    successor = WorkItemReadModel(tmp_path).project_status(working_tree=True)

    assert successor["candidate_base_observed_commit"] is None
    assert successor["changed_authority_kinds"] == [
        "domain_model",
        "engineering_policy",
        "implementation_alignment",
        "product_definition",
        "target_architecture",
    ]
    assert successor["implementation_alignment"]["revision_id"] == (
        successor_revision
    )
    assert successor["implementation_alignment"]["revision_status"] == "draft"
    assert successor["cross_authority_consistency"][
        "structurally_consistent"
    ] is True


def test_working_tree_status_compares_a_revision_candidate_to_adopted_authorities(
    tmp_path: Path,
) -> None:
    alignment_path, adopted_commit = _adopt_test_authorities(tmp_path)
    candidate_revision = _revise_alignment_candidate(
        tmp_path,
        alignment_path,
    )

    reader = WorkItemReadModel(tmp_path)
    adopted = reader.project_status()
    candidate = reader.project_status(working_tree=True)

    assert adopted["implementation_alignment"]["revision_status"] == "confirmed"
    assert adopted["implementation_alignment"]["revision_id"] != (
        candidate_revision
    )
    assert candidate["authority_scope"] == "working_tree_candidate"
    assert candidate["candidate_only"] is True
    assert candidate["candidate_base_observed_commit"] == adopted_commit
    assert candidate["changed_authority_kinds"] == [
        "implementation_alignment"
    ]
    assert candidate["implementation_alignment"]["revision_id"] == (
        candidate_revision
    )
    assert candidate["implementation_alignment"]["revision_status"] == "draft"
    assert candidate["cross_authority_consistency"][
        "structurally_consistent"
    ] is True


def test_working_tree_status_rejects_in_place_authority_content_rewrite(
    tmp_path: Path,
) -> None:
    alignment_path, _adopted_commit = _adopt_test_authorities(tmp_path)
    manifest = yaml.safe_load((tmp_path / alignment_path).read_text(encoding="utf-8"))
    ownership_path = tmp_path / manifest["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["rationale"] = "原地改写但故意复用旧修订身份。"
    ownership_path.write_text(
        yaml.safe_dump(ownership, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectIntegrationReferenceError) as invalid:
        WorkItemReadModel(tmp_path).project_status(working_tree=True)

    assert invalid.value.code == "working_tree_authority_candidate_invalid"
    assert "复用现行修订身份时改写了权威内容" in str(invalid.value)


def test_working_tree_status_reports_explicit_unsafe_git_attributes_stably(
    tmp_path: Path,
) -> None:
    alignment_path, _adopted_commit = _adopt_test_authorities(tmp_path)
    _revise_alignment_candidate(tmp_path, alignment_path)
    (tmp_path / ".gitattributes").write_text(
        "*.py filter=unset\n",
        encoding="utf-8",
    )

    status = WorkItemReadModel(tmp_path).project_status(working_tree=True)
    reasons = status["cross_authority_consistency"]["review_state"]["reasons"]

    assert status["implementation_alignment"]["review_required"] is True
    assert any("filter=unset" in reason for reason in reasons)
    assert any("Strixnova不会执行" in reason for reason in reasons)


def test_project_status_rejects_ambiguous_or_invalid_working_tree_scope(
    tmp_path: Path,
) -> None:
    reader = WorkItemReadModel(tmp_path)

    with pytest.raises(ProjectIntegrationReferenceError) as conflict:
        reader.project_status(at_commit="main", working_tree=True)
    assert conflict.value.code == "project_status_scope_conflict"

    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref=None)
    with pytest.raises(ProjectIntegrationReferenceError) as invalid:
        reader.project_status(working_tree=True)
    assert invalid.value.code == "working_tree_authority_candidate_invalid"


def test_adopted_project_commit_distinguishes_integration_reference_failures(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    missing.mkdir()
    with pytest.raises(ProjectIntegrationReferenceError) as no_ref:
        WorkItemReadModel(missing).adopted_project_commit()
    assert no_ref.value.code == "integration_ref_required"

    invalid = tmp_path / "invalid"
    invalid.mkdir()
    (invalid / "strixnova-project.yaml").write_text(
        "- not-an-object\n",
        encoding="utf-8",
    )
    with pytest.raises(ProjectIntegrationReferenceError) as bad_config:
        WorkItemReadModel(invalid).adopted_project_commit()
    assert bad_config.value.code == "project_configuration_invalid"

    unresolved = tmp_path / "unresolved"
    unresolved.mkdir()
    _git(unresolved, "init", "-b", "work")
    configure_repository(unresolved, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    with pytest.raises(ProjectIntegrationReferenceError) as missing_ref:
        WorkItemReadModel(unresolved).adopted_project_commit()
    assert missing_ref.value.code == "integration_ref_not_found"
    assert "main" in str(missing_ref.value)


def test_adopted_project_reads_reuse_commits_without_freezing_a_moving_ref(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Tests")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="BASELINE-1111111111111111",
        artifacts=[],
    )
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "baseline v1")
    first_commit = _git(tmp_path, "rev-parse", "HEAD")
    reader = WorkItemReadModel(tmp_path)

    first = reader.project_engineering_governance()
    assert first is not None
    assert first["baseline_id"] == "BASELINE-1111111111111111"
    assert first["observed_commit"] == first_commit

    baseline["baseline_id"] = "BASELINE-2222222222222222"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "docs/engineering/baseline.yaml")
    _git(tmp_path, "commit", "-m", "baseline v2")
    second_commit = _git(tmp_path, "rev-parse", "HEAD")

    second = reader.project_engineering_governance()
    assert second is not None
    assert second["baseline_id"] == "BASELINE-2222222222222222"
    assert second["observed_commit"] == second_commit
    assert second_commit != first_commit

    status = reader.project_status()
    assert status["observed_commit"] == second_commit
    assert status["product_definition"]["structurally_validated"] is True
    assert status["domain_model"]["semantic_correctness_machine_proven"] is False
    assert status["target_architecture"]["current_stage_id"]
    assert status["implementation_alignment"]["review_required"] is True
    assert status["construction"] == {"total": 0, "by_state": {}}
    assert status["isolated_install_acceptance"]["status"] == "not_recorded"
    assert status["delivery_release"]["strixnova_executes_external_activity"] is False
    assert status["deployment"]["total"] == 0
    assert status["runtime_operations"]["total"] == 0
    assert status["overall_usability_machine_decided"] is False


def test_revision_is_an_event_cursor_not_a_content_hash(tmp_path: Path) -> None:
    authority = WorkflowAuthority(tmp_path)
    reader = WorkItemReadModel(tmp_path)
    initial = reader.revision()
    authority.create(title="事项", raw_request="建设能力")
    updated = reader.revision()

    assert initial["revision"] == 0
    assert updated["revision"] == 1
    assert "sha" not in json.dumps(updated).lower()


def test_management_trace_connects_receipt_to_the_actual_result(
    tmp_path: Path,
) -> None:
    assessment = assessment_fixture(tmp_path)
    commands = normalize_verification_commands(
        assessment["verification_commands"]
    )
    approved = approved_verification_request(
        commands[0],
        work_item_id="WI-TRACE",
    )
    receipt = VerificationRunner(tmp_path).not_run(
        approved,
        **approval_expectations(approved),
        reason="本测试只验证管理关系投影。",
        limitations=["没有执行外部命令。"],
        code_change_assessment={
            "changed_after": False,
            "needs_retest": False,
            "rationale": "未运行命令，因此没有命令导致的代码变化。",
        },
    )
    item = {
        "work_item_id": "WI-TRACE",
        "data": {
            "direction": _direction(),
            "engineering": {
                "assessment": assessment,
                "plan": {
                    "verification_commands": commands,
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "purpose": "完成当前实现并验证。",
                            "implements": ["design_decisions[0]"],
                            "operation_refs": ["operations[0]"],
                            "depends_on": [],
                            "verification_command_ids": ["VC-001"],
                        }
                    ],
                },
            },
            "verifications": [receipt],
            "actual_result": {
                "effect_summary": "如实记录未运行限制。",
                "verification_receipt_ids": [receipt["receipt_id"]],
            },
            "git": {},
        },
    }

    trace = WorkItemReadModel(tmp_path)._management_trace(item)

    assert {
        "source": receipt["receipt_id"],
        "target": "actual_result",
        "type": "supports",
    } in trace["edges"]
    assert {
        "source": "design_decisions[0]",
        "target": "implementation_slice:SLICE-001",
        "type": "planned_as",
    } in trace["edges"]
    assert {
        "source": "implementation_slice:SLICE-001",
        "target": "VC-001",
        "type": "verified_by",
    } in trace["edges"]
