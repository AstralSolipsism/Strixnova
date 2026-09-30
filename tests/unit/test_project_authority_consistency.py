from __future__ import annotations

from pathlib import Path
import os
import subprocess

import pytest
import yaml

from tests.support.project_baseline import portable_project_baseline, adopt_portable_ddd

import strixnova.git_project_reader as git_project_reader_module
from strixnova.project_authority_consistency import (
    AUTHORITY_CONSISTENCY_SCHEMA,
    ProjectAuthorityConsistency,
    ProjectAuthorityConsistencyError,
)
from strixnova.project_engineering_baseline import (
    ProjectEngineeringBaseline,
    ProjectEngineeringBaselineError,
)


PROJECT_ROOT = Path(__file__).parents[2]


def _copy_authorities(project: Path) -> None:
    """Build a self-contained authority set without promoting repository drafts."""
    baseline = portable_project_baseline(project, baseline_id="consistency-fixture", artifacts=[])
    adopt_portable_ddd(project, baseline)
    path = project / "docs/engineering/baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _git(project: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _committed_authority_fixture(project: Path) -> str:
    _copy_authorities(project)
    _git(project, "init", "-b", "main")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    _git(project, "add", ".")
    _git(project, "commit", "-m", "current authority fixture")
    return _git(project, "rev-parse", "HEAD")




def test_immutable_full_authority_chain_uses_one_snapshot_and_bounded_batches(
    monkeypatch,
    tmp_path: Path,
) -> None:
    commit = _committed_authority_fixture(tmp_path)
    commands: list[tuple[str, ...]] = []
    original = git_project_reader_module.run_process

    def counted(command, **kwargs):
        commands.append(tuple(command[1:]))
        return original(command, **kwargs)

    monkeypatch.setattr(git_project_reader_module, "run_process", counted)

    result = ProjectAuthorityConsistency(
        tmp_path,
        observed_ref=commit,
    ).load()

    assert result["structurally_consistent"] is True
    # One fixed preflight checks partial-clone configuration before any object
    # read. The complete immutable authority load must still remain bounded.
    assert len(commands) <= 16
    assert sum("rev-parse" in command and "--git-common-dir" not in command for command in commands) <= 2
    assert sum("--git-common-dir" in command for command in commands) == 1
    assert not any("show" in command for command in commands)
    assert sum(
        "ls-tree" in command and "--long" in command
        for command in commands
    ) == 1


def test_baseline_identity_must_match_the_loaded_authority(tmp_path: Path) -> None:
    _copy_authorities(tmp_path)
    path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    value["authority_refs"]["domain_model"]["revision_id"] = (
        "MODELREV-0000000000000000"
    )
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectAuthorityConsistencyError) as caught:
        ProjectAuthorityConsistency(tmp_path).load()

    assert any("domain_model" in issue for issue in caught.value.issues)


def test_confirmed_policy_may_outlive_the_product_revision_it_was_reviewed_against(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    path = tmp_path / "docs" / "engineering" / "policy.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    value["product_definition_ref"]["revision_id"] = (
        "REVISION-0000000000000000"
    )
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    result = ProjectAuthorityConsistency(tmp_path).load()

    assert result["structurally_consistent"] is True
    assert result["engineering_policy"]["product_definition_ref"] == {
        "product_id": result["product_definition"]["product_id"],
        "revision_id": "REVISION-0000000000000000",
    }


def test_confirmed_policy_must_still_belong_to_the_same_stable_product(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    path = tmp_path / "docs" / "engineering" / "policy.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    value["product_definition_ref"]["product_id"] = (
        "PRODUCT-0000000000000000"
    )
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectAuthorityConsistencyError) as caught:
        ProjectAuthorityConsistency(tmp_path).load()

    assert any(
        "工程政策不属于当前稳定产品" in issue
        for issue in caught.value.issues
    )


def test_working_tree_candidate_baseline_can_point_at_a_draft_revision(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    reference = value["authority_refs"]["implementation_alignment"]
    reference["revision_id"] = "ALIGNREV-0000000000000000"
    reference["status"] = {
        "revision_status": "draft",
        "adoption_status": "current",
    }
    reader = ProjectEngineeringBaseline(tmp_path)

    with pytest.raises(ProjectEngineeringBaselineError):
        reader.validate(value, manifest_path="docs/engineering/baseline.yaml")

    candidate = reader.validate(
        value,
        manifest_path="docs/engineering/baseline.yaml",
        allow_candidate_refs=True,
    )

    assert candidate["authority_refs"]["implementation_alignment"] == reference


def test_domain_source_change_invalidates_only_known_downstream_chain(
    tmp_path: Path,
) -> None:
    commit = _committed_authority_fixture(tmp_path)
    checker = ProjectAuthorityConsistency(tmp_path, observed_ref=commit)

    scope = checker.invalidation_scope(
        changed_paths=["docs/domain/sources/core.yaml"]
    )

    assert scope["directly_changed_authority_kinds"] == ["domain_model"]
    assert scope["affected_authority_kinds"] == [
        "code_version",
        "domain_model",
        "implementation_alignment",
        "target_architecture",
    ]
    assert scope["semantic_impact_machine_proven"] is False


def test_behavior_path_remains_code_and_requires_alignment_refresh(
    tmp_path: Path,
) -> None:
    commit = _committed_authority_fixture(tmp_path)
    checker = ProjectAuthorityConsistency(tmp_path, observed_ref=commit)

    scope = checker.invalidation_scope(
        changed_paths=["src.py"]
    )

    assert scope["directly_changed_authority_kinds"] == ["code_version"]
    assert scope["affected_authority_kinds"] == [
        "code_version",
        "implementation_alignment",
    ]
    assert scope["changed_behavior_paths"] == [
        "src.py"
    ]


def test_unowned_non_behavior_path_does_not_claim_domain_meaning(
    tmp_path: Path,
) -> None:
    commit = _committed_authority_fixture(tmp_path)
    checker = ProjectAuthorityConsistency(tmp_path, observed_ref=commit)

    scope = checker.invalidation_scope(changed_paths=["notes/local.txt"])

    assert scope["directly_changed_authority_kinds"] == ["code_version"]
    assert scope["changed_behavior_paths"] == []


def test_actual_result_cannot_adopt_an_independent_product_revision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = ProjectAuthorityConsistency(tmp_path)
    candidate = {
        "baseline": {
            "project": {"owner_id": "OWNER-1111111111111111"},
            "authority_refs": {
                "product_definition": {
                    "path": "docs/product/definition.yaml",
                    "product_id": "PRODUCT-1111111111111111",
                    "revision_id": "REVISION-AAAAAAAAAAAAAAAA",
                    "status": {
                        "revision_status": "confirmed",
                        "adoption_status": "current",
                    },
                }
            },
            "review_state": {
                "required": True,
                "reasons": ["产品定义候选尚未独立确认。"],
                "affected_authority_kinds": ["product_definition"],
            },
            "_manifest_path": "docs/engineering/baseline.yaml",
        },
        "product_definition": {
            "product_id": "PRODUCT-1111111111111111",
            "revision": {
                "revision_id": "REVISION-BBBBBBBBBBBBBBBB",
                "status": "draft",
                "confirmed_by_owner_id": None,
                "confirmed_on": None,
            },
        },
        "changed_authority_kinds": ["product_definition"],
        "candidate_base_observed_commit": "a" * 40,
    }
    monkeypatch.setattr(
        checker,
        "load_working_tree_candidate_for",
        lambda _ref: candidate,
    )
    monkeypatch.setattr(
        checker,
        "_accepted_candidate_snapshot_verified",
        lambda *_args, **_kwargs: True,
    )
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": "PRODUCT-1111111111111111",
                "artifact_type": "product_governance",
                "path": "docs/product/definition.yaml",
                "relation": "updated",
            }
        ]
    }

    record = checker.authority_adoption_record(
        actual_result,
        investigation_ref="a" * 40,
        actual_result_confirmed=True,
        confirmed_on="2026-08-28",
    )

    assert record["authority_updates"] == []
    assert record["baseline_update"] is None
    assert record["ready_for_atomic_commits"] is False
    assert record["semantic_reconfirmation_required"] is True
    assert any(
        "普通实际结果确认不能替代" in issue
        for issue in record["blocking_issues"]
    )


def test_actual_result_rejects_a_preconfirmed_implementation_alignment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = ProjectAuthorityConsistency(tmp_path)
    candidate = {
        "baseline": {
            "authority_refs": {
                "implementation_alignment": {
                    "path": "docs/engineering/alignment.yaml",
                    "alignment_model_id": "ALIGNMODEL-1111111111111111",
                    "revision_id": "ALIGNREV-2222222222222222",
                    "status": {
                        "revision_status": "confirmed",
                        "adoption_status": "current",
                    },
                }
            },
            "review_state": {
                "required": False,
                "reasons": [],
                "affected_authority_kinds": [],
            },
        },
        "implementation_alignment": {
            "alignment_model_id": "ALIGNMODEL-1111111111111111",
            "revision": {
                "revision_id": "ALIGNREV-2222222222222222",
                "status": "confirmed",
                "confirmed_by_owner_id": "OWNER-3333333333333333",
                "confirmed_on": "2026-08-28",
            },
        },
        "changed_authority_kinds": ["implementation_alignment"],
    }
    monkeypatch.setattr(
        checker,
        "load_working_tree_candidate_for",
        lambda _ref: candidate,
    )

    with pytest.raises(ProjectAuthorityConsistencyError) as captured:
        checker.authority_candidate_snapshot(
            {
                "long_lived_refs": [
                    {
                        "artifact_id": "ALIGNMODEL-1111111111111111",
                        "artifact_type": "domain_alignment",
                        "path": "docs/engineering/alignment.yaml",
                        "relation": "updated",
                    }
                ]
            },
            investigation_ref="a" * 40,
        )

    assert any(
        "只能由当前实际结果接受事件机械定档" in issue
        for issue in captured.value.issues
    )


def test_actual_result_rejects_deterministic_alignment_drift_before_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copy_authorities(tmp_path)
    checker = ProjectAuthorityConsistency(tmp_path)
    candidate = checker.load_working_tree_candidate(None)
    candidate["review_state"]["required"] = True
    candidate["review_state"]["affected_authority_kinds"] = [
        "code_version",
        "implementation_alignment",
    ]
    candidate["review_state"]["reasons"].append(
        "实现对齐确定性漂移：实际直接依赖变化后对齐底账尚未复核"
    )
    candidate["changed_authority_kinds"] = ["implementation_alignment"]
    monkeypatch.setattr(
        checker,
        "load_working_tree_candidate_for",
        lambda _ref: candidate,
    )

    with pytest.raises(ProjectAuthorityConsistencyError) as captured:
        checker.authority_candidate_snapshot(
            {
                "long_lived_refs": [
                    {
                        "artifact_id": candidate[
                            "implementation_alignment"
                        ]["alignment_model_id"],
                        "artifact_type": "domain_alignment",
                        "path": candidate["baseline"]["authority_refs"][
                            "implementation_alignment"
                        ]["path"],
                        "relation": "updated",
                    }
                ]
            },
            investigation_ref="a" * 40,
        )

    assert any(
        "实际结果形成前必须先消除实现对齐确定性漂移" in issue
        and "实际直接依赖变化后对齐底账尚未复核" in issue
        for issue in captured.value.issues
    ), captured.value.issues


def test_first_project_candidate_reports_every_authority_as_new(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)

    candidate = ProjectAuthorityConsistency(tmp_path).load_working_tree_candidate(
        None
    )

    assert candidate["candidate_base_observed_commit"] is None
    assert candidate["changed_authority_kinds"] == [
        "domain_model",
        "engineering_policy",
        "implementation_alignment",
        "product_definition",
        "target_architecture",
    ]


def test_manual_confirmation_after_result_snapshot_cannot_fake_program_adoption(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checker = ProjectAuthorityConsistency(tmp_path)
    candidate = {
        "baseline": {
            "project": {"owner_id": "OWNER-1111111111111111"},
            "authority_refs": {
                "implementation_alignment": {
                    "path": "docs/engineering/alignment.yaml",
                    "alignment_model_id": "ALIGNMODEL-1111111111111111",
                    "revision_id": "ALIGNREV-2222222222222222",
                    "status": {
                        "revision_status": "confirmed",
                        "adoption_status": "current",
                    },
                }
            },
            "review_state": {
                "required": False,
                "reasons": [],
                "affected_authority_kinds": [],
            },
            "_manifest_path": "docs/engineering/baseline.yaml",
        },
        "implementation_alignment": {
            "alignment_model_id": "ALIGNMODEL-1111111111111111",
            "revision": {
                "revision_id": "ALIGNREV-2222222222222222",
                "status": "confirmed",
                "confirmed_by_owner_id": "OWNER-1111111111111111",
                "confirmed_on": "2026-08-28",
            },
        },
        "changed_authority_kinds": ["implementation_alignment"],
        "candidate_base_observed_commit": "a" * 40,
    }
    monkeypatch.setattr(
        checker,
        "load_working_tree_candidate_for",
        lambda _ref: candidate,
    )
    monkeypatch.setattr(
        checker,
        "_accepted_candidate_snapshot_verified",
        lambda *_args, **_kwargs: True,
    )
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": "ALIGNMODEL-1111111111111111",
                "artifact_type": "domain_alignment",
                "path": "docs/engineering/alignment.yaml",
                "relation": "updated",
            }
        ],
        "authority_candidate_snapshot": {
            "schema_version": "strixnova.authority-candidate-snapshot.v1",
            "required": True,
            "revision_metadata_mutable_authority_kinds": [
                "implementation_alignment"
            ],
            "baseline_ref_metadata_mutable_authority_kinds": [
                "implementation_alignment"
            ],
            "baseline_review_state_mutable": True,
        },
    }

    record = checker.authority_adoption_record(
        actual_result,
        investigation_ref="a" * 40,
        actual_result_confirmed=True,
        confirmed_on="2026-08-28",
    )

    assert record["ready_for_atomic_commits"] is False
    assert record["mechanical_adoption_final_state_verified"] is False
    assert any(
        "程序机械定档前" in issue for issue in record["blocking_issues"]
    )


def test_integrated_commit_must_still_match_the_accepted_authority_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        ProjectAuthorityConsistency,
        "_review_state",
        lambda *_args, **_kwargs: {
            "required": False,
            "reasons": [],
            "affected_authority_kinds": [],
            "semantic_review_performed": False,
        },
    )
    _copy_authorities(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "accepted authority snapshot")
    accepted_commit = _git(tmp_path, "rev-parse", "HEAD")
    checker = ProjectAuthorityConsistency(
        tmp_path,
        observed_ref=accepted_commit,
    )
    candidate = checker.load()
    candidate["candidate_base_observed_commit"] = accepted_commit
    snapshot = checker._build_authority_candidate_snapshot(
        candidate,
        reported_kinds={"product_definition"},
        changed_kinds={"product_definition"},
        revision_metadata_mutable_kinds=set(),
        baseline_ref_metadata_mutable_kinds=set(),
        baseline_review_state_mutable=False,
    )
    actual_result = {"authority_candidate_snapshot": snapshot}

    proof = ProjectAuthorityConsistency(
        tmp_path
    ).verify_integrated_candidate_snapshot(
        actual_result,
        integrated_commit=accepted_commit,
    )
    assert proof["accepted_candidate_snapshot_verified"] is True

    product_path = tmp_path / "docs" / "product" / "definition.yaml"
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    product["title"] = "合入冲突解决后被改写的产品正文"
    product_path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(tmp_path, "add", "docs/product/definition.yaml")
    _git(tmp_path, "commit", "-m", "pollute integrated authority")
    polluted_commit = _git(tmp_path, "rev-parse", "HEAD")

    with pytest.raises(ProjectAuthorityConsistencyError) as captured:
        ProjectAuthorityConsistency(
            tmp_path
        ).verify_integrated_candidate_snapshot(
            actual_result,
            integrated_commit=polluted_commit,
        )

    assert any(
        "本地合入后的项目权威不再等于" in issue
        for issue in captured.value.issues
    )


def test_actual_result_confirmation_snapshot_detects_authority_body_swap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _copy_authorities(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "accepted authority base")
    investigation_ref = _git(tmp_path, "rev-parse", "HEAD")
    checker = ProjectAuthorityConsistency(tmp_path)
    monkeypatch.setattr(
        checker,
        "_require_candidate_without_deterministic_drift",
        lambda _candidate: None,
    )
    actual_result: dict = {"long_lived_refs": []}
    actual_result["authority_candidate_snapshot"] = (
        checker.authority_candidate_snapshot(
            actual_result,
            investigation_ref=investigation_ref,
        )
    )

    proof = checker.verify_working_tree_candidate_snapshot(
        actual_result,
        investigation_ref=investigation_ref,
    )
    assert proof["accepted_candidate_snapshot_verified"] is True

    product_path = tmp_path / "docs" / "product" / "definition.yaml"
    product = yaml.safe_load(product_path.read_text(encoding="utf-8"))
    product["title"] = "负责人看到结果后被替换的产品正文"
    product_path.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectAuthorityConsistencyError) as captured:
        checker.verify_working_tree_candidate_snapshot(
            actual_result,
            investigation_ref=investigation_ref,
        )

    assert captured.value.issues


def test_integrated_snapshot_rejects_alignment_that_was_reverted_to_draft(
    tmp_path: Path,
) -> None:
    _copy_authorities(tmp_path)
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "draft alignment after fake adoption")
    integrated_commit = _git(tmp_path, "rev-parse", "HEAD")
    checker = ProjectAuthorityConsistency(tmp_path, observed_ref=integrated_commit)
    candidate = checker.load()
    candidate["candidate_base_observed_commit"] = integrated_commit
    snapshot = checker._build_authority_candidate_snapshot(
        candidate,
        reported_kinds={"implementation_alignment"},
        changed_kinds={"implementation_alignment"},
        revision_metadata_mutable_kinds={"implementation_alignment"},
        baseline_ref_metadata_mutable_kinds={"implementation_alignment"},
        baseline_review_state_mutable=True,
    )

    with pytest.raises(ProjectAuthorityConsistencyError) as captured:
        ProjectAuthorityConsistency(tmp_path).verify_integrated_candidate_snapshot(
            {"authority_candidate_snapshot": snapshot},
            integrated_commit=integrated_commit,
            confirmed_on="2026-08-28",
        )

    assert any(
        "机械定档最终状态" in issue for issue in captured.value.issues
    )


def test_governance_context_comes_from_the_adopted_policy(tmp_path: Path) -> None:
    commit = _committed_authority_fixture(tmp_path)
    context = ProjectAuthorityConsistency(
        tmp_path,
        observed_ref=commit,
    ).governance_context()

    assert context["governance_profile"]["project_engineering_policy_ref"][
        "policy_id"
    ] == "POLICY-1111111111111111"
    assert context["semantic_content_machine_proven"] is False


def test_engineering_governance_context_hides_authority_implementations(
    tmp_path: Path,
) -> None:
    commit = _committed_authority_fixture(tmp_path)
    context = ProjectAuthorityConsistency(
        tmp_path,
        observed_ref=commit,
    ).engineering_governance_context()

    assert context["schema_version"] == (
        "strixnova.engineering-governance-context.v1"
    )
    assert context["domain_model_id"] == "MODEL-1111111111111111"
    assert len(context["domain_fact_locations"]) > 0
    assert context["profile"]["project_authority_paths"] == {
        "project_product_definition_path": "docs/product/definition.yaml",
        "project_domain_model_path": "docs/domain/model.yaml",
        "project_architecture_description_path": "docs/architecture/model.yaml",
        "project_engineering_policy_path": "docs/engineering/policy.yaml",
        "project_implementation_alignment_path": "docs/engineering/alignment.yaml",
    }
    assert len(context["authority_artifacts"]) == 5
    architecture = context["authority_artifacts"]["ARCH-1111111111111111"]
    domain = context["authority_artifacts"]["MODEL-1111111111111111"]
    assert "FACT-1111111111111111" in domain["target_refs"]
    assert "FACT-1111111111111111" not in architecture["target_refs"]
    assert any(
        reference.startswith(
            "baseline:authority:product_definition:PRODUCT-"
        )
        and reference.endswith(":confirmed:current")
        for reference in context["baseline_refs"]
    )
    assert "long_lived_artifacts" not in context
    assert context["semantic_content_machine_proven"] is False
