"""Dispatch the fixed direction acceptance only after the native gate passed."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.agent_acceptance import run_session, assess_turn
initial=ROOT/'.artifacts/validation/8d987875922b/evidence'
last=ROOT/'.artifacts/validation/10bdc29a6a23/evidence'
gate_path=ROOT/'.artifacts/validation/399803e83f85/evidence/gate-binding.json'
gate=json.loads(gate_path.read_text(encoding='utf-8'))
assert gate['fixed_input_dispatch_permitted']
report_path=Path(gate['review_report'])
assert hashlib.sha256(report_path.read_bytes()).hexdigest()==gate['review_report_sha256']
report=json.loads(report_path.read_text(encoding='utf-8'))
assert report['execution']['report_valid'] and report['cases'][0]['summary']['status']=='passed'
definition=json.loads((initial/'registration.json').read_text(encoding='utf-8'))
info=json.loads(Path(definition['fixture']).read_text(encoding='utf-8'))
receipt=json.loads((last/'execution/driver-receipt.json').read_text(encoding='utf-8'))
project=Path(info['project']);built=definition['candidate'];identifier=gate['work_item_id']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
def dump(name,value):(evidence/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def current():
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=current();action=before['current_action']
assert before['work_item_version']==gate['work_item_version']
assert action['action_type']=='confirm_direction' and action['confirmation_challenge']['candidate_fingerprint']==gate['candidate_fingerprint']
original_source=(project/'src.py').read_bytes()
prompt=definition['fixed_owner_inputs']['accept_direction']
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');dump('accepted-gate-binding.json',gate);dump('before.json',before)
def observe():
    state=current()
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==info['initial_commit'] and (project/'src.py').read_bytes()==original_source
    return {'reached':state['current_action'].get('action_type')=='confirm_engineering_plan' and unchanged,
            'next':state,'implementation_not_started':unchanged,'semantic_acceptance':'pending independent plan review'}
executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=definition['model'],
    conversation_id=receipt['last_result']['conversation_id'],timeout=600,max_continuations=1,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump('tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump('endpoint.json',endpoint)
dump('phase-summary.json',{'phase':'plan','mechanical_passed':executed['mechanical_passed'],'endpoint_reached':endpoint['reached'],'actual_owner_accepted':False})
print(json.dumps({'phase':'plan','mechanical_passed':executed['mechanical_passed'],'endpoint_reached':endpoint['reached']},ensure_ascii=False))
raise SystemExit(0 if executed['mechanical_passed'] and endpoint['reached'] else 1)
