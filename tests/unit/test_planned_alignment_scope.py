"""Known governed paths require planned alignment work before owner acceptance."""
from pathlib import Path
import json

import pytest
from click.testing import CliRunner

from strixnova.application_coordinator import ApplicationCoordinator
from strixnova.cli import main
from strixnova.engineering_governance import EngineeringGovernanceError
from strixnova.workflow_authority import WorkflowAuthority
from tests.integration.test_local_git_lifecycle import _adopt_portable_test_project, _git
from tests.support.project_context import repository
from tests.support.governance_assessment import assessment_fixture
from tests.integration.test_workflow_cli import (
    _invoke, _submit, _confirm, _direction, _direction_context_binding, _bind_assessment,
)
from tests.integration.test_multi_repository_planning import planning_project
from strixnova.host_adapter import LocalHostAdapter
from strixnova.project_context import ProjectContextResolver


@pytest.fixture
def adopted_project(tmp_path: Path):
    project = tmp_path / 'project'
    repository(project)
    (project / 'src.py').write_text('def value():\n    return 1\n', encoding='utf-8')
    _adopt_portable_test_project(project, baseline_id='planned-alignment')
    return project, _git(project, 'rev-parse', 'HEAD')


def candidate(commit, path='src.py'):
    return {'investigation_ref': commit,
        'change_context': {'formal_implementation': True, 'change_kind': 'modify_existing'},
        'operations': [{'action': 'modify', 'path': path, 'repository_id': 'REPO-1111111111111111'}]}


def test_governed_source_omission_is_rejected_before_writing_any_state(adopted_project):
    project, commit = adopted_project
    coordinator = ApplicationCoordinator(project)
    with pytest.raises(EngineeringGovernanceError, match='实现对齐'):
        coordinator._require_planned_source_alignment(candidate(commit))
    assert _git(project, 'rev-parse', 'HEAD') == commit
    assert _git(project, 'status', '--porcelain') == ''


def test_public_assessment_rejects_missing_alignment_without_advancing_candidate(adopted_project):
    project, commit = adopted_project
    runner = CliRunner()
    current = _invoke(runner, project, 'intake', '--input', json.dumps({
        'title': 'Bounded source change', 'request': 'Change the local source under existing rules'}))['next']
    identifier = current['work_item_id']
    current = _submit(runner, project, identifier, current['work_item_version'],
        _direction('Bounded source change', decision_context=_direction_context_binding(runner, project, identifier)))
    current = _confirm(runner, project, identifier, current['work_item_version'], 'direction')
    assessment = assessment_fixture(project)
    assessment['investigation_ref'] = commit
    assessment['source_references'][0]['observed_ref'] = commit
    _bind_assessment(assessment, current)
    before = WorkflowAuthority(project).get(identifier)
    result = runner.invoke(main, ['submit', '--project-dir', str(project), '--work-item-id', identifier,
        '--version', str(current['work_item_version']), '--input', json.dumps(assessment)])
    assert result.exit_code == 1
    response = json.loads(result.output)
    assert response['error']['code'] == 'application_use_case_rejected'
    assert '受管源码' in response['error']['message']
    assert WorkflowAuthority(project).get(identifier) == before


def test_alignment_operation_satisfies_only_the_presence_check(adopted_project):
    project, commit = adopted_project
    assessment = candidate(commit)
    assessment['operations'].append({'action': 'modify', 'path': 'docs/engineering/alignment.yaml',
        'repository_id': 'REPO-1111111111111111',
        'long_lived_artifact': {'artifact_type': 'domain_alignment', 'artifact_id': 'ALIGNMODEL-1111111111111111'}})
    # Existing assessment validators still check authority identity, all ledger
    # paths and slice ownership; this check does not replace them.
    ApplicationCoordinator(project)._require_planned_source_alignment(assessment)


def test_paths_outside_recorded_behavior_scope_do_not_force_alignment(adopted_project):
    project, commit = adopted_project
    ApplicationCoordinator(project)._require_planned_source_alignment(candidate(commit, 'README.md'))


def test_scope_is_read_from_the_investigation_commit(adopted_project):
    project, commit = adopted_project
    # A working-tree edit cannot erase the adopted scope used by this plan.
    (project / 'docs/engineering/source-ownership.yaml').write_text('invalid draft', encoding='utf-8')
    with pytest.raises(EngineeringGovernanceError, match='src.py'):
        ApplicationCoordinator(project)._require_planned_source_alignment(candidate(commit))


@pytest.mark.parametrize('operation_index,required', [(0, True), (1, False)])
def test_equal_paths_in_other_repositories_do_not_inherit_the_authority_scope(tmp_path, operation_index, required):
    project = planning_project(tmp_path)
    adapter = LocalHostAdapter(project['entry'], project_bindings=project['bindings'])
    assessment = project['assessment']
    assessment['operations'] = [assessment['operations'][operation_index]]
    with ProjectContextResolver(project['entry']).operation(project['bindings']):
        if required:
            with pytest.raises(EngineeringGovernanceError, match='受管源码'):
                adapter.coordinator._require_planned_source_alignment(assessment)
        else:
            adapter.coordinator._require_planned_source_alignment(assessment)


@pytest.mark.parametrize('context', [
    {'formal_implementation': False, 'change_kind': 'modify_existing'},
    {'formal_implementation': True, 'change_kind': 'create_project'},
])
def test_non_delivery_and_first_adoption_keep_their_existing_routes(tmp_path, context):
    ApplicationCoordinator(tmp_path)._require_planned_source_alignment({
        'change_context': context, 'operations': [], 'investigation_ref': 'working_tree'})
