from __future__ import annotations

from tests.support.project_configuration import configure_repository

import hashlib
from pathlib import Path
import subprocess

import pytest
import yaml

from strixnova.git_project_reader import GitProjectReader
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_engineering_assurance import (
    PROJECT_ENGINEERING_ASSURANCE_SCHEMA,
    ProjectEngineeringAssurance,
    ProjectEngineeringAssuranceError,
)
from strixnova.project_engineering_policy import ProjectEngineeringPolicy
from strixnova.work_item_read_model import WorkItemReadModel
from tests.support.project_baseline import portable_project_baseline


PROJECT_ROOT = Path(__file__).parents[2]


def _git(project: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _write_yaml(project: Path, relative_path: str, value: dict) -> None:
    path = project / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def _project_with_assurance(tmp_path: Path) -> tuple[dict, Path]:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Tests")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    evidence_path = tmp_path / "src.py"
    evidence_path.write_text("VALUE = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="assurance",
        artifacts=[],
    )
    _write_yaml(tmp_path, "docs/engineering/baseline.yaml", baseline)
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "test: create project authorities")
    head = _git(tmp_path, "rev-parse", "HEAD")
    policy_ref = baseline["authority_refs"]["engineering_policy"]
    profile = ProjectEngineeringPolicy(
        tmp_path,
        policy_ref["path"],
    ).governance_profile()
    identity_fields = {
        "product_definition": "product_id",
        "domain_model": "model_id",
        "target_architecture": "architecture_id",
        "engineering_policy": "policy_id",
        "implementation_alignment": "alignment_model_id",
    }
    authority_refs = {
        kind: {
            "path": reference["path"],
            identity_fields[kind]: reference[identity_fields[kind]],
            "revision_id": reference["revision_id"],
            **{key: reference[key] for key in ("repository_id", "ref") if key in reference},
        }
        for kind, reference in baseline["authority_refs"].items()
    }
    evidence_id = "EVIDENCE-1111111111111111"
    assurance = {
        "schema_version": PROJECT_ENGINEERING_ASSURANCE_SCHEMA,
        "assurance_id": "ASSURANCE-1111111111111111",
        "assurance_revision_id": "ASSURANCEREV-1111111111111111",
        "supersedes_revision_id": None,
        "scope": "隔离项目当前内部软件工程保障状态。",
        "authority_refs": authority_refs,
        "governance_profile_ref": {
            "profile_id": profile["profile_id"],
            "profile_version": profile["profile_version"],
            "policy_id": policy_ref["policy_id"],
            "policy_revision_id": policy_ref["revision_id"],
        },
        "evidence_base_commit": head,
        "evidence": [
            {
                "evidence_id": evidence_id,
                "evidence_kind": "repository_file",
                "path": "src.py",
                "sha256": hashlib.sha256(
                    evidence_path.read_text(encoding="utf-8")
                    .replace("\r\n", "\n")
                    .encode("utf-8")
                ).hexdigest(),
                "receipt_id": None,
                "claim": "隔离测试证据文件存在且内容与评估绑定。",
                "limitations": ["只用于结构与证据绑定测试。"],
            }
        ],
        "rule_assessments": [
            {
                "rule_id": rule["rule_id"],
                "source_ids": list(rule["source_ids"]),
                "applicability": "applicable",
                "applicability_reason": "隔离测试覆盖全部规则合同。",
                "status": "satisfied",
                "evidence_ids": [evidence_id],
                "gaps": [],
                "remediation_actions": [],
                "limitations": ["语义正确性不由测试程序证明。"],
            }
            for rule in profile["rules"]
        ],
        "external_assurance": {
            "status": "not_claimed",
            "receipt_evidence_ids": [],
            "limitations": ["没有外部认证或合规回执。"],
        },
        "unresolved_items": [],
        "semantic_content_machine_proven": False,
    }
    assurance_path = tmp_path / "docs/engineering/assurance/model.yaml"
    _write_yaml(
        tmp_path,
        "docs/engineering/assurance/model.yaml",
        assurance,
    )
    return assurance, assurance_path


def test_assurance_matrix_keeps_internal_evidence_and_external_claims_apart(
    tmp_path: Path,
) -> None:
    assurance, _ = _project_with_assurance(tmp_path)

    matrix = ProjectEngineeringAssurance(tmp_path).matrix()

    assert matrix["assurance_id"] == assurance["assurance_id"]
    assert matrix["assurance_revision_id"] == assurance["assurance_revision_id"]
    assert matrix["by_status"] == {"satisfied": 7}
    assert matrix["external_assurance"]["status"] == "not_claimed"
    assert matrix["semantic_content_machine_proven"] is False
    assert matrix["external_assurance_machine_proven"] is False
    assert matrix["projection_is_project_authority"] is False
    assert all(row["sources"] for row in matrix["rule_assessments"])




def test_assurance_rejects_drifted_repository_evidence(tmp_path: Path) -> None:
    _project_with_assurance(tmp_path)
    (tmp_path / "src.py").write_text("VALUE = 2\n", encoding="utf-8")

    with pytest.raises(ProjectEngineeringAssuranceError) as caught:
        ProjectEngineeringAssurance(tmp_path).load()

    assert any("证据内容已漂移" in issue for issue in caught.value.issues)


def test_bulk_evidence_failure_preserves_each_file_diagnostic(tmp_path: Path) -> None:
    assurance, path = _project_with_assurance(tmp_path)
    (tmp_path / "src.py").write_text("VALUE = 2\n", encoding="utf-8")
    (tmp_path / "invalid.bin").write_bytes(b"\xff")
    base = assurance["evidence"][0]
    assurance["evidence"].extend([
        dict(base, evidence_id="EVIDENCE-2222222222222222", path="missing.txt"),
        dict(base, evidence_id="EVIDENCE-3333333333333333", path="invalid.bin"),
    ])
    path.write_text(yaml.safe_dump(assurance, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ProjectEngineeringAssuranceError) as captured:
        ProjectEngineeringAssurance(tmp_path).matrix()
    issues = captured.value.issues
    assert any("内容已漂移：src.py" in issue for issue in issues)
    assert any("missing.txt" in issue for issue in issues)
    assert any("必须是 UTF-8 文本" in issue for issue in issues)


def test_duplicate_evidence_does_not_read_its_ignored_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    assurance, path = _project_with_assurance(tmp_path)
    (tmp_path / "ignored.txt").write_text("not selected evidence\n", encoding="utf-8")
    assurance["evidence"].append(dict(assurance["evidence"][0], path="ignored.txt"))
    path.write_text(yaml.safe_dump(assurance, allow_unicode=True), encoding="utf-8")
    read_paths: list[str] = []
    original = GitProjectReader.read_bytes

    def record_read(self, relative_path, label="项目文件"):
        read_paths.append(relative_path)
        return original(self, relative_path, label)

    monkeypatch.setattr(GitProjectReader, "read_bytes", record_read)
    with pytest.raises(ProjectEngineeringAssuranceError, match="证据身份重复"):
        ProjectEngineeringAssurance(tmp_path).matrix()
    assert "ignored.txt" not in read_paths


def test_assurance_rejects_a_satisfied_rule_without_evidence(
    tmp_path: Path,
) -> None:
    assurance, assurance_path = _project_with_assurance(tmp_path)
    assurance["rule_assessments"][0]["evidence_ids"] = []
    assurance_path.write_text(
        yaml.safe_dump(assurance, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectEngineeringAssuranceError) as caught:
        ProjectEngineeringAssurance(tmp_path).load()

    assert any("满足规则必须引用证据" in issue for issue in caught.value.issues)


def test_assurance_rejects_external_claim_without_external_receipt(
    tmp_path: Path,
) -> None:
    assurance, assurance_path = _project_with_assurance(tmp_path)
    assurance["external_assurance"]["status"] = "claimed_with_receipt"
    assurance_path.write_text(
        yaml.safe_dump(assurance, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    with pytest.raises(ProjectEngineeringAssuranceError) as caught:
        ProjectEngineeringAssurance(tmp_path).load()

    assert any("真实外部回执" in issue for issue in caught.value.issues)


def test_assurance_rejects_mixed_shared_reader_scopes(tmp_path: Path) -> None:
    _project_with_assurance(tmp_path)

    with pytest.raises(ProjectEngineeringAssuranceError) as caught:
        ProjectEngineeringAssurance(
            tmp_path,
            shared_reader=GitProjectReader(tmp_path),
            shared_consistency=ProjectAuthorityConsistency(tmp_path),
        )

    assert any("同一读取范围" in issue for issue in caught.value.issues)


def test_read_model_exposes_assurance_as_a_separate_optional_projection(
    tmp_path: Path,
) -> None:
    _project_with_assurance(tmp_path)
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "test: add assurance projection")

    reader = WorkItemReadModel(tmp_path)
    matrix = reader.project_engineering_assurance()
    status = reader.project_status()

    assert matrix is not None
    assert matrix["projection_is_project_authority"] is False
    assert status["engineering_assurance"]["status"] == "recorded"
    assert status["engineering_assurance"][
        "semantic_content_machine_proven"
    ] is False
