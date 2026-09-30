from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from tests.integration.test_multi_repository_execution import presented_item
from tests.integration.test_multi_repository_planning import accept
from tests.support.governance_assessment import refresh_single_slice, satisfied_governance_rule_results
from tests.support.project_context import FRONTEND, BACKEND, git
from strixnova.work_item_repositories import previous_integrations
from strixnova.application_coordinator import ApplicationCoordinatorError


@pytest.mark.slow
def test_partial_delivery_can_replan_and_modify_the_integrated_repository_again(tmp_path: Path):
    project, adapter, item = presented_item(tmp_path, repository_order=[FRONTEND,BACKEND])
    result = deepcopy(item['data']['actual_result'])
    item = accept(adapter,item,'actual_result')
    item = adapter.coordinator.delivery(item['work_item_id'],{'repository_id':FRONTEND},expected_version=item['version'])['work_item']
    paths=[op['path'] for op in item['data']['engineering']['plan']['operations'] if op['repository_id']==FRONTEND]
    git(tmp_path/'frontend-work','add','--',*paths)
    git(tmp_path/'frontend-work','commit','-m','first accepted frontend contribution')
    item = adapter.coordinator.delivery(item['work_item_id'],{'repository_id':FRONTEND},expected_version=item['version'])['work_item']
    assert item['status']=='commit_required'
    integrated=git(project['front'],'rev-parse','HEAD')
    assert not (tmp_path/'frontend-work').exists()
    item=adapter.request_replan(item['work_item_id'],{'schema_version':'strixnova.replan-request.v1','reasons':['Refactor backend internals while retaining the same joint outcome; refresh the frontend-owned alignment evidence.']},expected_version=item['version'])
    assessment=deepcopy(project['assessment'])
    assessment['assessment_revision']+=1
    assessment['investigation_ref']=integrated
    for entry in assessment['repository_scope']['repositories']:
        if entry['repository_id']==FRONTEND:entry['investigation_ref']=integrated
    for reference in assessment['source_references']:
        if reference['repository_id']==FRONTEND:reference['observed_ref']=integrated
    assessment['operations']=[op for op in assessment['operations'] if not(op['repository_id']==FRONTEND and op['path']=='src.py')]
    baseline=yaml.safe_load((project['front']/'docs/engineering/baseline.yaml').read_text(encoding='utf-8'))
    model_path=baseline['authority_refs']['implementation_alignment']['path']
    model=yaml.safe_load((project['front']/model_path).read_text(encoding='utf-8'))
    change=assessment['authority_change_set']
    change['change_set_id']='AUTHCHANGE-8888888888888888'
    for reference in change['base_authorities']:
        current=baseline['authority_refs'][reference['authority_kind']]
        reference.update(repository_id=current['repository_id'],revision_id=current['revision_id'],observed_commit=current.get('ref') or integrated)
    change['candidate_authorities'][0].update(revision_id='ALIGNREV-8888888888888888',supersedes_revision_id=model['revision']['revision_id'])
    refresh_single_slice(assessment)
    item=adapter.submit_engineering_assessment(item['work_item_id'],assessment,expected_version=item['version'])
    item=accept(adapter,item,'engineering_plan')
    assert item['status']=='implementation_ready'
    assert previous_integrations(item['data'])[0]['integration']['integrated_commit']==integrated
    item=adapter.coordinator.delivery(item['work_item_id'],{'repository_id':FRONTEND,'worktree_path':str(tmp_path/'frontend-work-2')},expected_version=item['version'])['work_item']
    assert item['status']=='implementing'
    (tmp_path/'backend-work/src.py').write_text('def base():\n    return 2\n\ndef value():\n    return base() + 1\n',encoding='utf-8')
    prepared=adapter.coordinator.prepare_implementation_alignment(item['work_item_id'],{'schema_version':'strixnova.implementation-alignment-preparation-request.v1','alignment_revision_id':'ALIGNREV-8888888888888888','supersedes_revision_id':model['revision']['revision_id']},expected_version=item['version'])
    cursor=None
    while True:
        page=adapter.coordinator.inspect_implementation_alignment(item['work_item_id'],prepared['preparation_ref'],cursor=cursor,limit=100,expected_version=item['version'])
        assert not [row for row in page['items'] if row['record_kind']=='semantic_decision' and row['value']['required']], page
        cursor=page['next_cursor']
        if cursor is None:break
    adapter.coordinator.write_implementation_alignment_candidate(item['work_item_id'],{'schema_version':'strixnova.implementation-alignment-candidate-decisions.v1','preparation_ref':prepared['preparation_ref'],'decisions':[],'deviations':[],'unresolved_items':[]},expected_version=item['version'])
    receipts=[]
    for command in item['data']['engineering']['plan']['verification_commands']:
        observed=adapter.coordinator.verify(item['work_item_id'],{'command_id':command['command_id'],'mode':'run'},expected_version=item['version'])
        assert observed['verification']['result']=='passed'
        receipts.append(observed['verification']['receipt_id'])
        item=observed['work_item']
        item=adapter.coordinator.assess_verification(item['work_item_id'],receipts[-1],{'changed_after':False,'needs_retest':False,'rationale':'Reviewed both repositories and the refreshed alignment without further changes.'},expected_version=item['version'])
    for key in ('authority_candidate_snapshot','implementation_candidate_snapshot','target_verification','review_subject'):result.pop(key,None)
    result['verification_receipt_ids']=receipts
    result['governance_rule_results']=satisfied_governance_rule_results(item['data']['engineering']['plan'],receipts[0])
    result['effect_summary']='The joint outcome is unchanged; backend internals and their alignment evidence were revised after the first frontend integration.'
    with pytest.raises(ApplicationCoordinatorError) as stale:
        adapter.coordinator.present_actual_result(item['work_item_id'],result,expected_version=item['version'])
    assert stale.value.code == 'review_subject_changed'
    result['review_subject_ref'] = adapter.read_model.review_subject(item)['subject_ref']
    item,_=adapter.coordinator.present_actual_result(item['work_item_id'],result,expected_version=item['version'])
    item=accept(adapter,item,'actual_result')
    item=adapter.coordinator.delivery(item['work_item_id'],{'repository_id':FRONTEND},expected_version=item['version'])['work_item']
    for identifier,root in ((FRONTEND,tmp_path/'frontend-work-2'),(BACKEND,tmp_path/'backend-work')):
        paths=[op['path'] for op in item['data']['engineering']['plan']['operations'] if op['repository_id']==identifier]
        git(root,'add','--',*paths);git(root,'commit','-m','accepted revised contribution')
        item=adapter.coordinator.delivery(item['work_item_id'],{'repository_id':identifier},expected_version=item['version'])['work_item']
    assert item['status']=='completed'
    assert previous_integrations(item['data'])[0]['integration']['integrated_commit']==integrated
    assert git(project['front'],'merge-base','--is-ancestor',integrated,'HEAD')==''
