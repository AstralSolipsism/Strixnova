from pathlib import Path
import json
import os
import subprocess
import sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.agent_acceptance import run_session, assess_turn

prior=ROOT/'.artifacts/validation/8d987875922b/evidence'
registration=json.loads((prior/'registration.json').read_text(encoding='utf-8'))
endpoint=json.loads((prior/'endpoint.json').read_text(encoding='utf-8'))
receipt=json.loads((prior/'execution/driver-receipt.json').read_text(encoding='utf-8'))
info=json.loads(Path(registration['fixture']).read_text(encoding='utf-8'))
project=Path(info['project']);built=registration['candidate'];identifier=endpoint['work_item_id']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
def dump(name,value):(evidence/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def current():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier,'--record','direction'],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(result.stdout)['next']
before=current();expected=before['current_action']['confirmation_challenge']['candidate_fingerprint']
assert before['current_action']['action_type']=='confirm_direction'
assert expected==endpoint['next']['current_action']['confirmation_challenge']['candidate_fingerprint']
prompt=registration['fixed_owner_inputs']['reexplain']
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump('before.json',before)
def observe():
    state=current();action=state['current_action']
    same=state['work_item_version']==before['work_item_version'] and action.get('action_type')=='confirm_direction' and action.get('confirmation_challenge',{}).get('candidate_fingerprint')==expected
    return {'reached':same,'same_candidate_and_version':same,'next':state,'semantic_acceptance':'pending independent review'}
executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=registration['model'],
    conversation_id=receipt['last_result']['conversation_id'],timeout=300,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump('tool-steps.json',assess_turn(events)['tool_steps']);after=observe();dump('endpoint.json',after)
dump('phase-summary.json',{'phase':'reexplain','mechanical_passed':executed['mechanical_passed'],'same_candidate_and_version':after['reached'],'actual_owner_accepted':False})
print(json.dumps({'phase':'reexplain','mechanical_passed':executed['mechanical_passed'],'same_candidate_and_version':after['reached']},ensure_ascii=False))
raise SystemExit(0 if executed['mechanical_passed'] and after['reached'] else 1)
