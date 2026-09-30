from copy import deepcopy
from pathlib import Path

import pytest

from strixnova.actual_result import ActualResultError, validate_actual_result
from strixnova.application_coordinator import ApplicationCoordinator
from strixnova.engineering_change_planning import implementation_slice_progress
from strixnova.git_project_reader import GitProjectReader
from strixnova.project_content_snapshot import capture_repository_content, verification_input_paths
from strixnova.workflow_authority import _reduce, InvalidTransition
from strixnova.work_item_repositories import previous_integrations
from tests.support.project_context import FRONTEND, BACKEND, git, repository
from tests.unit.test_project_authority_decision import _ready_product_project
from strixnova.project_authority_decision import project_authority_candidate, build_project_authority_confirmation_transaction, apply_project_authority_confirmation_transaction, confirmed_project_authority_snapshot
from strixnova.project_context import ProjectContextResolver
import yaml


@pytest.mark.parametrize('linked', [False, True])
def test_unbound_mechanical_paths_use_the_same_native_repository_only(tmp_path, linked):
    from strixnova.implementation_candidate_evidence import ImplementationCandidateEvidence
    from tests.support.project_configuration import configuration_document
    from tests.support.project_context import PROJECT
    root = tmp_path / 'repository'
    repository(root)
    configuration = configuration_document(integration_ref='main')
    configuration['repositories'].append({'repository_id': BACKEND, 'owner_project_id': PROJECT, 'purpose': 'Unbound other member'})
    (root / 'strixnova-project.yaml').write_text(yaml.safe_dump(configuration), encoding='utf-8')
    git(root, 'add', 'strixnova-project.yaml')
    git(root, 'commit', '-m', 'declaration')
    worktree = tmp_path / 'worktree' if linked else root
    if linked:
        git(root, 'worktree', 'add', '-b', 'change', str(worktree))
    item = {'data': {
        'selected_repository_id': None,
        'git': {'repository': str(root), 'worktree_path': str(worktree)},
        'authority_adoption': {'baseline_path': 'docs/baseline.yaml', 'baseline_repository_id': FRONTEND, 'authority_updates': []},
        'actual_result': {
            'authority_candidate_snapshot': {'authority_repositories': {'implementation_alignment': FRONTEND}},
            'long_lived_refs': [{'artifact_type': 'domain_alignment', 'path': 'docs/alignment.yaml'}],
        },
    }}
    original = deepcopy(item)
    assert ImplementationCandidateEvidence.mechanical_authority_paths(item) == ['docs/alignment.yaml', 'docs/baseline.yaml']
    assert item == original
    item['data']['authority_adoption']['baseline_repository_id'] = BACKEND
    item['data']['actual_result']['authority_candidate_snapshot']['authority_repositories']['implementation_alignment'] = BACKEND
    assert ImplementationCandidateEvidence.mechanical_authority_paths(item) == []


def test_later_slice_changes_do_not_invalidate_preceding_slice_inputs(tmp_path):
    tmp_path = tmp_path / 'project'
    repository(tmp_path)
    for path in ('a.py', 'b.py', 'shared.py'):
        (tmp_path / path).write_text('value = 1\n')
    git(tmp_path, 'add', '.')
    git(tmp_path, 'commit', '-m', 'slice inputs')
    plan = {'plan_id': 'PLAN-1', 'operations': [
        {'repository_id': FRONTEND, 'path': path} for path in ('a.py', 'b.py')
    ], 'implementation_slices': [
        {'slice_id': 'S1', 'operation_refs': ['operations[0]'], 'depends_on': [], 'verification_command_ids': ['V1']},
        {'slice_id': 'S2', 'operation_refs': ['operations[1]'], 'depends_on': ['S1'], 'verification_command_ids': ['V2']},
    ]}
    command = {'command_id': 'V1', 'repository_id': FRONTEND}
    def snapshot():
        reader = GitProjectReader(tmp_path)
        return capture_repository_content(FRONTEND, reader, sorted(verification_input_paths(plan, command, FRONTEND, reader)))
    before = snapshot()
    (tmp_path / 'b.py').write_text('value = 2\n')
    assert snapshot() == before
    receipt = {'command_id': 'V1', 'result': 'passed', 'code_change_assessment': {'needs_retest': False}}
    assert implementation_slice_progress(plan, [receipt])['current_slice_id'] == 'S2'
    (tmp_path / 'shared.py').write_text('value = 2\n')
    assert snapshot() != before
    command['case_report'] = {'input_paths': ['b.py']}
    before = snapshot()
    (tmp_path / 'b.py').write_text('value = 3\n')
    assert snapshot() != before


def test_result_references_use_the_planned_repository_even_with_equal_paths(tmp_path):
    front, back = tmp_path / 'front', tmp_path / 'back'
    front.mkdir(); back.mkdir()
    (front / 'contract.md').write_text('frontend result')
    (back / 'contract.md').write_text('unrelated backend result')
    value = {'schema_version': "strixnova.actual-result.v1", "review_subject_ref": "review-subject:" + "a" * 64, 'effect_summary': 'Joint result',
             'delivered_outcomes': ['Frontend contract created'], 'deviations': [], 'limitations': [],
             'verification_receipt_ids': [], 'long_lived_refs': [{'artifact_id': 'DOC-1', 'artifact_type': 'interface', 'path': 'contract.md', 'relation': 'introduced'}],
             'method_application_results': [], 'governance_rule_results': [], 'semantic_content_machine_proven': False}
    operations = [{'repository_id': FRONTEND, 'action': 'create', 'path': 'contract.md', 'long_lived_artifact': {'artifact_id': 'DOC-1', 'artifact_type': 'interface'}}]
    def check():
        return validate_actual_result(value, {'verification_status': 'not_required', 'latest_receipt_ids': {}}, repository_readers={FRONTEND: GitProjectReader(front), BACKEND: GitProjectReader(back)}, planned_operations=operations, planned_verification_targets=[])
    result = check()
    assert result['long_lived_refs'][0]['repository_id'] == FRONTEND
    (front / 'contract.md').unlink()
    with pytest.raises(ActualResultError, match='contract.md') as error:
        check()
    assert error.value.code == 'long_lived_artifact_missing'
    value['long_lived_refs'][0]['repository_id'] = BACKEND
    with pytest.raises(ActualResultError) as error:
        check()
    assert error.value.code == 'long_lived_repository_mismatch'


def test_replan_cannot_drop_a_repository_with_unclosed_work():
    scope = {'project_id': 'PROJECT-1111111111111111', 'repositories': [
        {'repository_id': identifier, 'role': 'modify', 'investigation_ref': 'a'*40, 'target_ref': 'main'} for identifier in (FRONTEND, BACKEND)
    ]}
    data = {'engineering': {'plan': {'plan_id': 'OLD', 'repository_scope': scope}}, 'repository_deliveries': [
        {'repository_id': identifier, 'git': {'work_ref': 'strixnova/item', 'repository': identifier}} for identifier in (FRONTEND, BACKEND)
    ]}
    new_plan = {'plan_id': 'NEW', 'repository_scope': scope, 'operations': [{'repository_id': BACKEND, 'path': 'src.py'}]}
    with pytest.raises(InvalidTransition) as error:
        _reduce('replanning_required', data, 'submit_engineering_assessment', {'assessment': {}, 'plan': new_plan}, work_item_id='WI-1', work_item_version=10)
    assert error.value.code == 'repository_scope_has_unclosed_execution'
    assert len(data['repository_deliveries']) == 2


def test_new_attempt_in_a_completed_repository_keeps_its_original_integration():
    scope = {'project_id': 'PROJECT-1111111111111111', 'repositories': [
        {'repository_id': identifier, 'role': 'modify', 'investigation_ref': 'a'*40, 'target_ref': 'main'} for identifier in (FRONTEND, BACKEND)
    ]}
    original = {'schema_version': 'strixnova.git-work-area.v1', 'work_ref': 'strixnova/old', 'base_commit': 'a'*40, 'repository': 'front', 'integration': {'integrated_commit': 'b'*40}, 'cleanup': {'safe': True}}
    data = {'engineering': {'plan': {'plan_id': 'OLD', 'repository_scope': scope}}, 'git': {}, 'repository_deliveries': [
        {'plan_id': 'OLD', 'repository_id': FRONTEND, 'git': original},
        {'plan_id': 'OLD', 'repository_id': BACKEND, 'git': {'work_ref': 'strixnova/back', 'repository': 'back'}},
    ]}
    status, replanning = _reduce('commit_required', data, 'request_replan', {'reasons': ['The joint outcome needs another frontend change.']}, work_item_id='WI-1', work_item_version=10)
    plan = {'plan_id': 'NEW', 'repository_scope': scope, 'operations': [{'repository_id': identifier, 'path': 'src.py'} for identifier in (FRONTEND, BACKEND)]}
    status, planned = _reduce(status, replanning, 'submit_engineering_assessment', {'assessment': {}, 'plan': plan}, work_item_id='WI-1', work_item_version=11)
    assert status == 'awaiting_plan_confirmation'
    entries = {entry['repository_id']: entry for entry in planned['repository_deliveries']}
    assert not entries[FRONTEND].get('git')
    assert entries[BACKEND]['git']['work_ref'] == 'strixnova/back'
    assert previous_integrations(planned)[0]['integration']['integrated_commit'] == 'b'*40
    assert planned['superseded_deliveries'][0]['repository_deliveries'][0]['git'] == original


def test_authority_confirmation_writes_only_the_qualified_body_and_separate_baseline(tmp_path):
    front, back = tmp_path / 'front', tmp_path / 'back'
    front.mkdir()
    item, product_path = _ready_product_project(front)
    repository(back)
    relative = product_path.relative_to(front).as_posix()
    destination = back / relative
    destination.parent.mkdir(parents=True)
    destination.write_bytes(product_path.read_bytes())
    misleading = b'unrelated same-name frontend file\n'
    product_path.write_bytes(misleading)
    config_path = front / 'strixnova-project.yaml'
    config = yaml.safe_load(config_path.read_text(encoding='utf-8'))
    config['repositories'].append({'repository_id': BACKEND, 'owner_project_id': config['project_id'], 'purpose': 'Authority body'})
    config_path.write_text(yaml.safe_dump(config), encoding='utf-8')
    baseline_path = front / 'docs/engineering/baseline.yaml'
    baseline = yaml.safe_load(baseline_path.read_text(encoding='utf-8'))
    baseline['authority_refs']['product_definition'].update(repository_id=BACKEND, ref=None)
    baseline_path.write_text(yaml.safe_dump(baseline), encoding='utf-8')
    item['data']['engineering']['plan']['operations'][0]['repository_id'] = BACKEND
    bindings = {'schema_version': 'strixnova.project-bindings.v1', 'project_id': config['project_id'], 'management_root': '.',
                'configuration': {'repository_id': config['repository_id']}, 'repositories': [
                    {'repository_id': config['repository_id'], 'path': str(front)}, {'repository_id': BACKEND, 'path': str(back)}]}
    with ProjectContextResolver(front).operation(bindings):
        candidate = project_authority_candidate(front, item, 'product_definition')
        assert candidate['repository_id'] == BACKEND
        transaction = build_project_authority_confirmation_transaction(front, item, [{'candidate': candidate, 'accepted': True}], confirmed_on='2026-09-15')
        assert {entry['repository_id'] for entry in transaction['entries']} == {config['repository_id'], BACKEND}
        apply_project_authority_confirmation_transaction(front, transaction)
        confirmed = confirmed_project_authority_snapshot(front, item, candidate)
    assert confirmed['confirmed_on'] == '2026-09-15'
    assert yaml.safe_load(destination.read_text())['revision']['status'] == 'confirmed'
    assert product_path.read_bytes() == misleading
