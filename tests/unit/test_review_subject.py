from pathlib import Path
import pytest

from strixnova.work_item_read_model import WorkItemReadModel
from strixnova.actual_result import ACTUAL_RESULT_SCHEMA, ActualResultError, validate_actual_result
from tests.support.project_context import git, repository


def review_item(project: Path):
    repository(project)
    (project / "app.py").write_text("value = 1\n", encoding="utf-8")
    git(project, "add", ".")
    git(project, "commit", "-m", "review baseline")
    return {
        "work_item_id": "WI-review-subject", "version": 7, "status": "implementing",
        "data": {
            "direction": {"goal": "Preserve behavior"},
            "engineering": {"plan": {"plan_id": "PLAN-review", "operations": [{"action": "modify", "path": "app.py"}], "verification_commands": []}},
            "git": {"repository": str(project), "worktree_path": str(project)},
            "verifications": [],
        },
    }


def test_review_subject_changes_when_code_changes_without_a_work_item_transition(tmp_path):
    project = tmp_path / "repo"
    item = review_item(project)
    reader = WorkItemReadModel(project)
    before = reader.review_subject(item)
    (project / "app.py").write_text("value = 2\n", encoding="utf-8")
    after = reader.review_subject(item)
    assert before["subject_ref"] != after["subject_ref"]
    assert before["plan_id"] == after["plan_id"]
    assert item["version"] == 7


def test_review_subject_is_stable_and_does_not_include_management_state(tmp_path):
    project = tmp_path / "repo"
    item = review_item(project)
    reader = WorkItemReadModel(project)
    before = reader.review_subject(item)
    state = project / ".strixnova"
    state.mkdir()
    (state / "unrelated-state.json").write_text("{}", encoding="utf-8")
    after = reader.review_subject(item)
    assert before == after
    assert after["semantic_content_machine_proven"] is False
    assert not after["writes_performed"]


def test_unbound_exploration_binds_only_the_selected_directory_inside_another_repo(tmp_path):
    parent = tmp_path / "outer"
    repository(parent)
    outside = parent / "outside.txt"
    outside.write_text("not an input", encoding="utf-8")
    project = parent / "independent-inputs"
    project.mkdir()
    source = project / "source.txt"
    source.write_text("current input", encoding="utf-8")
    item = {"work_item_id": "WI-nested-exploration", "status": "exploring", "data": {
        "direction": {"goal": "Read only the explicit input directory"},
        "engineering": {"plan": {"plan_id": "PLAN-readonly", "operations": []}},
    }}
    reader = WorkItemReadModel(project)
    before = reader.review_subject(item)
    outside.write_text("outer repository changed", encoding="utf-8")
    assert reader.review_subject(item) == before
    source.write_text("changed input", encoding="utf-8")
    assert reader.review_subject(item)["subject_ref"] != before["subject_ref"]
    assert not (project / ".git").exists()


def result_payload():
    return {"schema_version": ACTUAL_RESULT_SCHEMA, "effect_summary": "Reviewed the actual result",
            "delivered_outcomes": ["Behavior implemented"], "deviations": [], "limitations": [],
            "verification_receipt_ids": [], "long_lived_refs": [], "method_application_results": [],
            "governance_rule_results": [], "semantic_content_machine_proven": False}


def test_result_without_the_reviewed_content_identity_is_rejected():
    with pytest.raises(ActualResultError):
        validate_actual_result(result_payload(), {"verification_status": "not_required", "latest_receipt_ids": {}}, planned_verification_targets=[])


@pytest.mark.parametrize("changed", [False, True])
def test_result_keeps_the_identity_from_before_review_instead_of_rebinding_it(tmp_path, changed):
    project = tmp_path / "repo"
    item = review_item(project)
    reader = WorkItemReadModel(project)
    reviewed = reader.review_subject(item)
    payload = {**result_payload(), "review_subject_ref": reviewed["subject_ref"]}
    if changed:
        (project / "app.py").write_text("value = 2\n", encoding="utf-8")
    current = reader.review_subject(item)
    kwargs = {"planned_verification_targets": [], "expected_review_subject_ref": current["subject_ref"]}
    coverage = {"verification_status": "not_required", "latest_receipt_ids": {}}
    if changed:
        with pytest.raises(ActualResultError) as error:
            validate_actual_result(payload, coverage, **kwargs)
        assert error.value.code == "review_subject_changed"
    else:
        result = validate_actual_result(payload, coverage, **kwargs)
        assert result["review_subject_ref"] == reviewed["subject_ref"]
        assert result["semantic_content_machine_proven"] is False


def test_read_dependency_uses_its_declared_commit_not_its_later_working_tree(tmp_path):
    from strixnova.git_project_reader import GitProjectReader
    from strixnova.project_content_snapshot import review_subject

    project, dependency = tmp_path / "project", tmp_path / "dependency"
    item = review_item(project)
    review_item(dependency)
    commit = git(dependency, "rev-parse", "HEAD")
    readers = {None: GitProjectReader(project), "REPO-2222222222222222": GitProjectReader(dependency, observed_ref=commit)}
    before = review_subject(item, readers)
    (dependency / "app.py").write_text("local unrelated change\n", encoding="utf-8")
    after = review_subject(item, readers)
    assert before["subject_ref"] == after["subject_ref"]


def test_new_integrated_rules_invalidate_review_even_when_worktree_code_is_unchanged(tmp_path):
    from tests.support.review_context import review_project, read_yaml, write_yaml
    from tests.support.project_configuration import configure_repository
    from tests.support.project_context import FRONTEND

    project, worktree = tmp_path / "project", tmp_path / "worktree"
    basis = review_project(project)
    configure_repository(project, integration_ref="main")
    git(project, "add", ".")
    git(project, "commit", "-m", "declare integrated rules")
    git(project, "worktree", "add", "-b", "work", str(worktree))
    item = {"work_item_id": "WI-rules", "version": 7, "status": "implementing", "data": {
        "selected_repository_id": FRONTEND,
        "engineering": {"plan": {"plan_id": "PLAN-rules", "investigation_ref": basis, "operations": []}},
        "git": {"repository": str(project), "worktree_path": str(worktree)},
    }}
    reader = WorkItemReadModel(project)
    before = reader.review_subject(item)
    policy = read_yaml(project, "docs/engineering/policy.yaml")
    next(iter(policy["policy_statements"].values())).append("Apply this new rule at implementation review.")
    write_yaml(project, "docs/engineering/policy.yaml", policy)
    git(project, "add", ".")
    git(project, "commit", "-m", "update integrated rule content")
    after = reader.review_subject(item)
    assert before["content_snapshot"] == after["content_snapshot"]
    assert before["subject_ref"] != after["subject_ref"]
