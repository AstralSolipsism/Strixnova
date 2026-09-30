from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest

from strixnova.application_coordinator import ApplicationCoordinator
from strixnova.engineering_change_planning import implementation_slice_progress, permitted_slice_operation_paths
from strixnova.project_context import ProjectContextResolver
from strixnova.project_maintenance import MaintenanceError
from strixnova.runtime_upgrade import RuntimeUpgrade
from strixnova.work_item_read_model import WorkItemReadModel
from strixnova.project_content_snapshot import continued_verification_paths, verification_snapshot_matches, capture_repository_content, compose_content_snapshot
from strixnova.test_case_evidence import input_snapshot
from strixnova.git_project_reader import GitProjectReader
from tests.support.project_context import FRONTEND, git, inspect_request, repository


def continuation_item(root):
    repository(root)
    for name in ('alignment.yaml', 'app.py', 'shared.py'):
        (root / name).write_bytes(b'initial\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'slice baseline')
    commands = [{'command_id': name, 'repository_id': FRONTEND} for name in ('V1', 'V2')]
    plan = {
        'plan_id': 'PLAN-REVIEW', 'verification_commands': commands,
        'operations': [{'repository_id': FRONTEND, 'action': 'modify', 'path': name}
                       for name in ('alignment.yaml', 'app.py')],
        'implementation_slices': [
            {'slice_id': 'S1', 'operation_refs': ['operations[0]'], 'depends_on': [], 'verification_command_ids': ['V1']},
            {'slice_id': 'S2', 'operation_refs': ['operations[1]'], 'continued_operation_refs': ['operations[0]'],
             'depends_on': ['S1'], 'verification_command_ids': ['V2']},
        ],
    }
    plan['operations'][0]['long_lived_artifact'] = {'artifact_id': 'ALIGNMODEL-1111111111111111', 'artifact_type': 'domain_alignment'}
    item = {'work_item_id': 'WI-REVIEW', 'status': 'implementing', 'data': {
        'selected_repository_id': FRONTEND, 'engineering': {'plan': plan},
        'git': {'repository': str(root), 'worktree_path': str(root)},
        'verifications': [], 'implementation_slice_completions': [],
    }}
    coordinator = ApplicationCoordinator(root)
    snapshot = coordinator._verification_input_snapshot(item, commands[0])
    item['data']['verifications'] = [{'receipt_id': 'R1', 'command_id': 'V1', 'result': 'passed',
        'repository_id': FRONTEND, 'project_input_snapshot': snapshot,
        'code_change_assessment': {'changed_after': False, 'needs_retest': False}}]
    item['data']['implementation_slice_completions'] = [{
        'schema_version': 'strixnova.implementation-slice-completion.v1', 'slice_id': 'S1',
        'source_receipt_ids': ['R1'], 'semantic_content_machine_proven': False,
    }]
    return coordinator, item


@pytest.mark.parametrize('case_report', [False, True])
def test_approved_continuation_keeps_preceding_slice_complete_in_both_views(tmp_path, case_report):
    coordinator, item = continuation_item(tmp_path / 'repo')
    if case_report:
        command = item['data']['engineering']['plan']['verification_commands'][0]
        command['case_report'] = {'input_paths': ['alignment.yaml', 'shared.py']}
        receipt = item['data']['verifications'][0]
        receipt['project_input_snapshot'] = coordinator._verification_input_snapshot(item, command)
        receipt['case_evidence'] = {'status': 'recorded', 'input_snapshot': input_snapshot(coordinator.project, command['case_report']['input_paths'])}
    original = deepcopy(item)
    (coordinator.project / 'alignment.yaml').write_bytes(b'final alignment\n')
    (coordinator.project / 'app.py').write_bytes(b'implemented\n')
    readers = [coordinator._with_case_input_checks(item)['data']['verifications'],
               WorkItemReadModel(coordinator.project)._verification_receipts(item)]
    for receipts in readers:
        scope = permitted_slice_operation_paths(item['data']['engineering']['plan'], receipts, item['data']['implementation_slice_completions'], repository_id=FRONTEND)
        assert scope['current_slice_id'] == 'S2'
        assert 'app.py' in scope['permitted_paths']
        assert scope['future_paths'] == []
    assert item == original


def test_final_refresh_still_requires_its_own_current_verification(tmp_path):
    coordinator, item = continuation_item(tmp_path / 'repo')
    (coordinator.project / 'alignment.yaml').write_bytes(b'final alignment\n')
    (coordinator.project / 'app.py').write_bytes(b'implemented\n')
    data = item['data']
    command = data['engineering']['plan']['verification_commands'][1]
    data['verifications'].append({'receipt_id': 'R2', 'command_id': 'V2', 'result': 'passed',
        'repository_id': FRONTEND, 'project_input_snapshot': coordinator._verification_input_snapshot(item, command),
        'code_change_assessment': {'changed_after': False, 'needs_retest': False}})
    data['implementation_slice_completions'].append({'schema_version': 'strixnova.implementation-slice-completion.v1',
        'slice_id': 'S2', 'source_receipt_ids': ['R2'], 'semantic_content_machine_proven': False})
    receipts = coordinator._with_case_input_checks(item)['data']['verifications']
    assert implementation_slice_progress(data['engineering']['plan'], receipts, data['implementation_slice_completions'])['status'] == 'completed'
    (coordinator.project / 'alignment.yaml').write_bytes(b'changed after final verification\n')
    receipts = coordinator._with_case_input_checks(item)['data']['verifications']
    assert receipts[1]['_case_input_stale'] is True
    assert implementation_slice_progress(data['engineering']['plan'], receipts, data['implementation_slice_completions'])['current_slice_id'] == 'S2'


def test_continuation_exclusion_does_not_cover_equal_paths_in_another_repository(tmp_path):
    from tests.support.project_context import BACKEND
    coordinator, item = continuation_item(tmp_path / 'repo')
    reader = GitProjectReader(coordinator.project)
    first = capture_repository_content(FRONTEND, reader, ['alignment.yaml'])
    second = capture_repository_content(BACKEND, reader, ['alignment.yaml'])
    snapshot = compose_content_snapshot('PLAN-REVIEW', [first, second])
    (coordinator.project / 'alignment.yaml').write_bytes(b'changed\n')
    live = compose_content_snapshot('PLAN-REVIEW', [first, capture_repository_content(BACKEND, reader, ['alignment.yaml'])])
    data = item['data']
    paths = continued_verification_paths(data['engineering']['plan'], data['verifications'], data['implementation_slice_completions'])['V1']
    assert not verification_snapshot_matches(snapshot, live, paths)
    altered_hash = deepcopy(snapshot)
    altered_hash['content_sha256'] = '0' * 64
    assert not verification_snapshot_matches(altered_hash, snapshot, paths)


@pytest.mark.parametrize('invalid_basis', ['unrelated_input', 'no_completion', 'wrong_receipt', 'not_declared'])
def test_continuation_cannot_hide_other_changes_or_missing_completion(tmp_path, invalid_basis):
    coordinator, item = continuation_item(tmp_path / 'repo')
    (coordinator.project / 'alignment.yaml').write_bytes(b'final alignment\n')
    if invalid_basis == 'unrelated_input':
        (coordinator.project / 'shared.py').write_bytes(b'not authorized by continuation\n')
    elif invalid_basis == 'no_completion':
        item['data']['implementation_slice_completions'] = []
    elif invalid_basis == 'wrong_receipt':
        item['data']['implementation_slice_completions'][0]['source_receipt_ids'] = ['OTHER']
    else:
        item['data']['engineering']['plan']['implementation_slices'][1]['continued_operation_refs'] = []
    receipts = coordinator._with_case_input_checks(item)['data']['verifications']
    assert implementation_slice_progress(item['data']['engineering']['plan'], receipts, item['data']['implementation_slice_completions'])['current_slice_id'] == 'S1'


@pytest.mark.parametrize('explicit_read', [True, False])
def test_read_dependency_materializes_the_replanned_commit_after_prior_integration(tmp_path, explicit_read):
    root = tmp_path / 'repo'
    old = repository(root, b'old deployed version\n')
    (root / 'same.txt').write_bytes(b'new selected version\n')
    git(root, 'add', 'same.txt')
    git(root, 'commit', '-m', 'new dependency version')
    new = git(root, 'rev-parse', 'HEAD')
    coordinator = ApplicationCoordinator(tmp_path)
    coordinator.project_context = ProjectContextResolver(tmp_path).resolve(inspect_request({FRONTEND: 'repo'}))
    item = {'work_item_id': 'WI-READ', 'data': {'selected_repository_id': FRONTEND,
        'git': {'repository': str(root), 'integration': {'integrated_commit': old}},
        'engineering': {'plan': {'plan_id': 'PLAN-NEW', 'repository_scope': {'repositories': [
            {'repository_id': FRONTEND, 'role': 'read' if explicit_read else 'modify', 'investigation_ref': new},
        ]}}}}}
    original = deepcopy(item)
    captured = coordinator._materialize_verification_input(item, 'R-NEW')
    assert (captured / 'same.txt').read_bytes() == (b'new selected version\n' if explicit_read else b'old deployed version\n')
    assert item == original
