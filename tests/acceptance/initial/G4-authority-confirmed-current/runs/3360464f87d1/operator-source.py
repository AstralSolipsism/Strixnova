"""Forward exact registered authority decision, then the already accepted plan."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
gate_root=ROOT/'.artifacts/validation/1452ae3f8033';author_root=ROOT/'.artifacts/validation/260419b79789'
for root in [gate_root,author_root]:
    result=json.loads((root/'result.json').read_text(encoding='utf-8'));assert result['status']=='passed' and result['process_settled']
gate=json.loads((gate_root/'evidence/gate-binding.json').read_text(encoding='utf-8'))
assert gate['fixed_input_dispatch_permitted'] and sha(Path(gate['review_report']))==gate['review_report_sha256']
report=json.loads(Path(gate['review_report']).read_text(encoding='utf-8'))
assert report['execution']['report_valid'] and all(r['summary']['status']=='passed' and not r['issues'] for r in report['cases'])
prior=json.loads((author_root/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'));assert prior['mechanical_passed']
project=Path(initial['project']);built=candidate(Path(initial['candidate_registration']));assert built==initial['candidate']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']);identifier=gate['work_item_id'];secondary='WI-20260929-274215EA'
def public(identity):
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=public(identifier);other=public(secondary)
assert before['work_item_version']==gate['work_item_version'] and before['current_action']['action_type']=='confirm_project_authority_candidates'
assert before['current_action']['confirmation_challenges']==gate['confirmation_challenges']
assert all(sha(project/path)==digest for path,digest in gate['candidate_files'].items())
bundle_call=subprocess.run([built['entrypoint'],'authority','--project-dir',str(project),'--work-item-id',identifier,'--version',str(before['work_item_version'])],capture_output=True,text=True,encoding='utf-8',check=True,timeout=60)
bundle=json.loads(bundle_call.stdout);assert bundle['candidate_bundle']['content_sha256']==gate['candidate_bundle_sha256']
assert public(identifier)==before
prompt=initial['fixed_inputs']['accept_authorities']
assert prompt in (ROOT/'docs/engineering/agent-acceptance.md').read_text(encoding='utf-8')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'before.json',before);dump(evidence/'secondary-before.json',other)
shutil.copytree(project/'docs',evidence/'candidate-before');shutil.copyfile(__file__,evidence/'operator-source.py')
dump(evidence/'registration.json',{'phase':'G4-authority-acceptance-and-implementation','project':str(project),'candidate':built,
 'work_item_id':identifier,'secondary_work_item_id':secondary,'fixed_owner_input':prompt,'input_sha256':sha(evidence/'user-input.txt'),
 'accepted_gate':gate,'plan_implementation_permission_origin':'registered R5 plan acceptance after independent gate9b7d1edc70b2',
 'model':initial['model'],'timeout_seconds':900,'max_neutral_continuations':0,'owner_accepted':False,'os_isolation_verified':False})
def observe():
    state=public(identifier);other_now=public(secondary)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    protected=all(sha(project/path)==digest for path,digest in initial['protected_source'].items())
    other_same=other_now['work_item_version']==other['work_item_version'] and other_now['current_action']==other['current_action']
    return {'reached':state['current_action']['action_type']=='confirm_actual_result' and head==initial['initial_commit'] and protected and other_same,
            'next':state,'head_unchanged':head==initial['initial_commit'],'existing_duration_source_and_tests_unchanged':protected,
            'secondary_direction_unchanged':other_same,'actual_result_acceptance_dispatched':False,'owner_accepted':False}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=prior['last_result']['conversation_id'],
    timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
shutil.copytree(project/'docs',evidence/'candidate-after')
summary={'mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],'actual_result_acceptance_dispatched':False,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
