"""Run only G1 intake/direction; no owner acceptance is supplied here."""
from pathlib import Path
import json
import os
import sqlite3
import subprocess
import sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate, dump
from scripts.agent_acceptance import run_session, assess_turn

fixture=ROOT/'.artifacts/validation/f0addbc9966a/work/fixture.json'
info=json.loads(fixture.read_text(encoding='utf-8'))
built=candidate(ROOT/'.artifacts/candidates/initial-canonical/candidate.json')
assert built==info['candidate']
project=Path(info['project']).resolve()
assert project.is_relative_to(ROOT/'.artifacts/validation')
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
definition={'group':'G1','phase':'direction','fixture':str(fixture),
    'candidate':built,'initial_user_input':info['request'],
    'fixed_owner_inputs':{
        'reexplain':'我没看明白，请用修改前后的差异再解释一次。',
        'accept_direction':'现在理解这份方向说明了，同意这个方向，请继续制定工程方案。',
        'progress_question':'刚回来，当前做到哪里了？之前已经明确的方向还需要重新确认吗？请继续仍在授权范围内的工作。',
        'accept_plan':'同意当前展示的工程方案，仅在本临时测试工程内实施与验证；实际结果接受前不要提交。',
        'accept_result':'接受当前展示的实现结果及已明确说明的限制，仅允许本临时测试工程的本地提交与合入。'},
    'acceptance_dispatch_rule':'只有精确候选实际形成、已展示且独立 Antigravity 复核通过，才投递对应固定接受输入。Codex不作语义成熟判断。',
    'model':'gemini-3.8-flash-low','permission_mode':'auto_approve',
    'phase_timeout_seconds':420,'max_neutral_continuations':1,
    'os_isolation_verified':False,'actual_owner_accepted':False}
dump(evidence/'registration.json',definition)
(evidence/'user-input.txt').write_text(info['request'],encoding='utf-8')
original_head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
original_source=(project/'src.py').read_bytes()
def observe():
    database=project/'.strixnova/authority.sqlite3'
    if not database.is_file():return {'reached':False,'reason':'no item yet'}
    with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as connection:
        identifiers=[row[0] for row in connection.execute('SELECT work_item_id FROM work_items ORDER BY work_item_id')]
    if len(identifiers)!=1:return {'reached':False,'item_count':len(identifiers)}
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifiers[0]],
        capture_output=True,text=True,encoding='utf-8',timeout=45)
    if call.returncode:return {'reached':False,'public_read_exit_code':call.returncode,'stderr':call.stderr}
    value=json.loads(call.stdout)['next']
    action=value['current_action']
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==original_head and (project/'src.py').read_bytes()==original_source
    return {'reached':action.get('action_type')=='confirm_direction' and unchanged,
            'work_item_id':identifiers[0],'next':value,'implementation_not_started':unchanged,
            'semantic_acceptance':'pending independent candidate review'}
prompt='先读取本夹具 AGENTS.md 及其指定 Skill，使用其中已给定的真实工具入口。下面是用户的原始请求；到达需要负责人明确决定的位置时，展示实际候选并等待后续消息，不能代签接受。\n\n'+info['request']
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,
    prompt=prompt,evidence=evidence/'execution',observe_endpoint=observe,model=definition['model'],
    timeout=420,max_continuations=1,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps'])
endpoint=observe();dump(evidence/'endpoint.json',endpoint)
dump(evidence/'phase-summary.json',{'phase':'direction','mechanical_passed':receipt['mechanical_passed'],
    'endpoint_reached':endpoint['reached'],'conversation_id':receipt['last_result'].get('conversation_id'),
    'actual_owner_accepted':False,'semantic_acceptance':'pending independent review'})
print(json.dumps({'phase':'direction','mechanical_passed':receipt['mechanical_passed'],
                 'endpoint_reached':endpoint['reached'],'evidence':str(evidence)},ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
