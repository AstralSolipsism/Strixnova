from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner
import pytest
import yaml

from strixnova.application_coordinator import ApplicationCoordinator, ApplicationCoordinatorError
from strixnova.cli import main
from strixnova.project_authority_consistency import ProjectAuthorityConsistency, ProjectAuthorityConsistencyError
from strixnova.project_context import ProjectContextResolver
from strixnova.project_engineering_baseline import ProjectEngineeringBaseline
from strixnova.work_item_read_model import WorkItemReadModel
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.project_baseline import portable_project_baseline
from tests.support.project_configuration import configuration_document
from tests.support.project_context import BACKEND, FRONTEND, PROJECT, git, repository, tree_bytes


def split_project(root: Path) -> dict:
    entry, front, back = root / "entry", root / "front", root / "back"
    entry.mkdir()
    front.mkdir()
    (front / "src.py").write_text("value = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(front, baseline_id="split authorities", artifacts=[])
    repository(back)
    for source in (front / "docs").rglob("*"):
        if source.is_file():
            target = back / source.relative_to(front)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    git(back, "add", ".")
    git(back, "commit", "-m", "backend authority bundle")
    back_commit = git(back, "rev-parse", "HEAD")
    for kind in ("product_definition", "domain_model", "target_architecture"):
        baseline["authority_refs"][kind].update(repository_id=BACKEND, ref=back_commit)
    baseline_path = front / "docs/engineering/baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False), encoding="utf-8")
    configuration = configuration_document(integration_ref="main")
    configuration["repositories"].extend([
        {"repository_id": BACKEND, "owner_project_id": PROJECT, "purpose": "后端及其长期材料"},
        {"repository_id": "REPO-4444444444444444", "owner_project_id": PROJECT, "purpose": "本次不需检出的成员"},
    ])
    (front / "strixnova-project.yaml").write_text(yaml.safe_dump(configuration, allow_unicode=True, sort_keys=False), encoding="utf-8")
    # A path-only fallback to the front repository must fail this fixture.
    (front / baseline["authority_refs"]["product_definition"]["path"]).write_text("wrong repository copy\n", encoding="utf-8")
    git(front, "add", ".")
    git(front, "commit", "-m", "project locator and pinned adoption")
    front_commit = git(front, "rev-parse", "HEAD")
    bindings = {
        "schema_version": "strixnova.project-bindings.v1", "project_id": PROJECT,
        "configuration": {"repository_id": FRONTEND},
        "management_root": "state-not-created",
        "repositories": [{"repository_id": FRONTEND, "path": "../front"}, {"repository_id": BACKEND, "path": "../back"}],
    }
    return dict(entry=entry, front=front, back=back, baseline=baseline, bindings=bindings,
                front_commit=front_commit, back_commit=back_commit)


def test_split_authorities_use_one_context_and_exact_independent_commits(tmp_path: Path) -> None:
    project = split_project(tmp_path)
    product_path = project["back"] / project["baseline"]["authority_refs"]["product_definition"]["path"]
    product_path.write_text("unrelated newer branch content\n", encoding="utf-8")
    git(project["back"], "add", ".")
    git(project["back"], "commit", "-m", "advance backend independently")
    before = tree_bytes(tmp_path)
    context = ProjectContextResolver(project["entry"]).configured(
        bindings=project["bindings"], observed_ref=project["front_commit"],
    )
    baseline = ProjectEngineeringBaseline(project["entry"], shared_context=context)
    checker = ProjectAuthorityConsistency(project["entry"], shared_baseline=baseline)
    result = checker.load()
    assert checker.baseline_reader.context is context
    assert result["structurally_consistent"] is True
    assert result["authority_content_refs"]["product_definition"]["repository_id"] == BACKEND
    assert result["authority_content_refs"]["product_definition"]["observed_commit"] == project["back_commit"]
    assert result["authority_content_refs"]["engineering_policy"]["observed_commit"] == project["front_commit"]
    assert result["ready_for_stage_completion"] is False
    catalog = checker.domain_routing_catalog()
    assert catalog["repository_id"] == BACKEND
    assert catalog["observed_commit"] == project["back_commit"]
    assert tree_bytes(tmp_path) == before
    assert not (project["entry"] / "state-not-created").exists()


def test_governance_profile_reuses_the_policy_repository_and_commit(tmp_path: Path) -> None:
    project = split_project(tmp_path)
    reference = project["baseline"]["authority_refs"]["engineering_policy"]
    reference.update(repository_id=BACKEND, ref=project["back_commit"])
    baseline_path = project["front"] / "docs/engineering/baseline.yaml"
    baseline_path.write_text(yaml.safe_dump(project["baseline"]), encoding="utf-8")
    (project["front"] / reference["path"]).write_text("wrong repository policy\n", encoding="utf-8")
    git(project["front"], "add", ".")
    git(project["front"], "commit", "-m", "pin policy in backend")
    (project["back"] / reference["path"]).write_text("newer unselected policy\n", encoding="utf-8")
    git(project["back"], "add", ".")
    git(project["back"], "commit", "-m", "advance backend policy")
    before = tree_bytes(tmp_path)
    context = ProjectContextResolver(project["entry"]).configured(
        bindings=project["bindings"], observed_ref="HEAD",
    )
    checker = ProjectAuthorityConsistency(project["entry"], shared_context=context)
    profile = checker.governance_context()["governance_profile"]
    assert profile["project_engineering_policy_ref"]["observed_commit"] == project["back_commit"]
    assert profile["project_engineering_policy_ref"]["revision_id"] == reference["revision_id"]
    assert tree_bytes(tmp_path) == before


def test_cross_repository_adoption_requires_an_explicit_commit(tmp_path: Path) -> None:
    project = split_project(tmp_path)
    path = project["front"] / "docs/engineering/baseline.yaml"
    project["baseline"]["authority_refs"]["product_definition"]["ref"] = None
    path.write_text(yaml.safe_dump(project["baseline"]), encoding="utf-8")
    git(project["front"], "add", ".")
    git(project["front"], "commit", "-m", "invalid cross repository version")
    context = ProjectContextResolver(project["entry"]).configured(bindings=project["bindings"], observed_ref="HEAD")
    baseline = ProjectEngineeringBaseline(project["entry"], shared_context=context)
    before = tree_bytes(tmp_path)
    with pytest.raises(ProjectAuthorityConsistencyError) as caught:
        ProjectAuthorityConsistency(project["entry"], shared_baseline=baseline).load()
    assert caught.value.code == "cross_repository_commit_required"
    assert tree_bytes(tmp_path) == before


def test_public_project_status_reads_separated_authorities_without_creating_state(tmp_path: Path, monkeypatch) -> None:
    project = split_project(tmp_path)
    bindings_path = tmp_path / "bindings.json"
    bindings_path.write_text(json.dumps(project["bindings"]), encoding="utf-8")
    before = tree_bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("project authority query created a WorkItem authority")

    monkeypatch.setattr(WorkflowAuthority, "__init__", forbidden)
    result = CliRunner().invoke(main, [
        "--project-bindings", str(bindings_path), "status", "--project-dir", str(project["entry"]),
    ])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["status"]["baseline_id"] == project["baseline"]["baseline_id"]
    assert payload["status"]["authority_content_refs"]["product_definition"]["repository_id"] == BACKEND
    assert payload["status"]["authority_content_refs"]["product_definition"]["observed_commit"] == project["back_commit"]
    assert tree_bytes(tmp_path) == before


def test_unadopted_status_does_not_create_the_configured_management_directory(tmp_path: Path, monkeypatch) -> None:
    project = split_project(tmp_path)
    path = project["front"] / "strixnova-project.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["default_integration_ref"] = None
    path.write_text(yaml.safe_dump(config), encoding="utf-8")
    before = tree_bytes(tmp_path)

    def forbidden(*args, **kwargs):
        raise AssertionError("unadopted read constructed a WorkItem authority")

    monkeypatch.setattr(WorkflowAuthority, "__init__", forbidden)
    status = WorkItemReadModel(project["entry"], project_bindings=project["bindings"]).project_status()
    assert status["authority_scope"] == "unadopted_project"
    assert status["construction"]["total"] == 0
    assert tree_bytes(tmp_path) == before
    assert not (project["entry"] / "state-not-created").exists()


def test_multi_repository_execution_requires_an_existing_work_item_before_side_effects(tmp_path: Path) -> None:
    project = split_project(tmp_path)
    before = tree_bytes(tmp_path)
    coordinator = ApplicationCoordinator(project["entry"], project_bindings=project["bindings"])
    with pytest.raises(ApplicationCoordinatorError) as caught:
        coordinator.delivery("WI-NOT-CREATED", {"target_ref": "main"}, expected_version=1)
    assert caught.value.code == "authority_not_initialized"
    assert tree_bytes(tmp_path) == before


def test_configuration_and_baseline_can_belong_to_different_repositories(tmp_path: Path) -> None:
    project = split_project(tmp_path)
    baseline = project["baseline"]
    for kind in ("engineering_policy", "implementation_alignment"):
        baseline["authority_refs"][kind]["ref"] = project["front_commit"]
    path = project["back"] / "docs/engineering/baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    git(project["back"], "add", ".")
    git(project["back"], "commit", "-m", "baseline in backend repository")
    baseline_commit = git(project["back"], "rev-parse", "HEAD")
    configuration_path = project["front"] / "strixnova-project.yaml"
    configuration = yaml.safe_load(configuration_path.read_text(encoding="utf-8"))
    configuration["engineering_baseline"].update(repository_id=BACKEND, ref=baseline_commit)
    configuration_path.write_text(yaml.safe_dump(configuration), encoding="utf-8")
    git(project["front"], "add", ".")
    git(project["front"], "commit", "-m", "pin separate baseline")
    configuration_commit = git(project["front"], "rev-parse", "HEAD")
    before = tree_bytes(tmp_path)
    reader = WorkItemReadModel(project["entry"], project_bindings=project["bindings"])
    status = reader.project_status()
    assert reader.adopted_project_commit() == configuration_commit
    assert status["configuration_content_ref"]["repository_id"] == FRONTEND
    assert status["configuration_content_ref"]["observed_commit"] == configuration_commit
    assert status["baseline_content_ref"]["repository_id"] == BACKEND
    assert status["baseline_content_ref"]["observed_commit"] == baseline_commit
    assert tree_bytes(tmp_path) == before


def test_existing_item_can_be_cancelled_when_the_current_locator_is_invalid(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    repository(root)
    item = WorkflowAuthority(root).create(title="原事项", raw_request="尚未进入实施")
    config = root / "strixnova-project.yaml"
    config.write_text("invalid: current locator\n", encoding="utf-8")
    result = ApplicationCoordinator(root).cancel(item["work_item_id"], {"reason": "停止本次建设"}, expected_version=item["version"])
    assert result["status"] == "cancelled"
    assert config.read_text(encoding="utf-8") == "invalid: current locator\n"


@pytest.mark.parametrize("location", ["configuration", "authority"])
def test_missing_authority_keeps_pinned_single_repository_metadata_read_only(tmp_path: Path, location: str) -> None:
    (tmp_path / "src.py").write_text("value = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(tmp_path, baseline_id="pinned metadata", artifacts=[])
    path = tmp_path / "docs/engineering/baseline.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "original metadata")
    commit = git(tmp_path, "rev-parse", "HEAD")
    if location == "configuration":
        config_path = tmp_path / "strixnova-project.yaml"
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        config["engineering_baseline"]["ref"] = commit
        config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    else:
        baseline["authority_refs"]["domain_model"]["ref"] = commit
        path.write_text(yaml.safe_dump(baseline), encoding="utf-8")
    assert ProjectAuthorityConsistency(tmp_path).load()["structurally_consistent"] is True
    before = tree_bytes(tmp_path)
    with pytest.raises(ApplicationCoordinatorError) as caught:
        ApplicationCoordinator(tmp_path).delivery("WI-NOT-CREATED", {"target_ref": "main"}, expected_version=1)
    assert caught.value.code == "authority_not_initialized"
    assert tree_bytes(tmp_path) == before
