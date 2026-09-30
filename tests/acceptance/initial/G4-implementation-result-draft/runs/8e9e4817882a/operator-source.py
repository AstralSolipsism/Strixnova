"""Resume a settled bounded run at its actual state, without a new decision."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,owned,sha
from scripts.agent_acceptance import run_session,assess_turn
parser=argparse.ArgumentParser()
parser.add_argument('--prior-run',required=True)
parser.add_argument('--expected-version',type=int,required=True)
options=parser.parse_args()
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
prior=owned(ROOT/'.artifacts/validation'/options.prior_run)
result=json.loads((prior/'result.json').read_text(encoding='utf-8'));assert result['process_settled']
receipt=json.loads((prior/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert not receipt['verdict']['unsettled_steps']
events=[json.loads(line) for line in (prior/'evidence/execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
conversations={row['conversation_id'] for row in events if row.get('event')=='init'}
assert len(conversations)==1
conversation=next(iter(conversations))
project=owned(Path(initial['project']));built=candidate(Path(initial['candidate_registration']))
evidence=owned(Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']))
identifier='WI-20260929-DEC61550';secondary='WI-20260929-274215EA'

def current(identity):
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']

before=current(identifier);other=current(secondary)
assert before['work_item_version']==options.expected_version
assert before['work_item_status']=='implementing'
assert before['current_action']['action_type'] in {'assess_verification_change','complete_implementation_slice','implement_and_verify'}
assert other['work_item_version']==3
prompt=(f'继续同一隔离工程的已接受R5方案，事项{identifier}当前版本{options.expected_version}。上一轮因单次调用到时结束，原始错误与已完成产物都保留；本条没有新的接受决定或授权扩大。'
 '先读取当前公开动作与已有回执，沿用仍有效的材料和验证结果，完成剩余的验证后置判断、当前切片、编码后实际对齐和必要最终验证，展示真实结果、偏差与限制，停在等待实际结果确认。'
 '不要重复已完成的方向、方案或四项权威确认；实际结果尚未接受，禁止提交、合入或远端操作。'
 '原duration源码和测试保持不变，周报事项仍待方向决定。已写入的新业务代码按既有方案核对，范围不扩展。'
 f'当前已登记入口为{built["entrypoint"]}，业务验证Python为{sys.executable}，保留现有AGENTS正文。遇真实阻断如实停止，不伪造通过。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
shutil.copytree(project/'docs',evidence/'candidate-before')
dump(evidence/'registration.json',{'phase':'continue-current-G4-implementation','project':str(project),'candidate':built,
    'prior_run':options.prior_run,'prior_outcome':receipt.get('outcome'),'before':before,'secondary_before':other,
    'fixed_non_accepting_input':prompt,'input_sha256':sha(evidence/'user-input.txt'),'conversation_id':conversation,
    'model':initial['model'],'timeout_seconds':600,'max_continuations':0,'owner_accepted':False})

def observe():
    state=current(identifier);other_now=current(secondary)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True,timeout=30).stdout.strip()
    stable=all(sha(project/path)==digest for path,digest in initial['protected_source'].items())
    other_same=other_now['work_item_version']==other['work_item_version'] and other_now['current_action']==other['current_action']
    return {'reached':state['current_action']['action_type']=='confirm_actual_result' and head==initial['initial_commit'] and stable and other_same,
            'next':state,'head_unchanged':head==initial['initial_commit'],'existing_duration_source_and_tests_unchanged':stable,
            'secondary_direction_unchanged':other_same,'actual_result_acceptance_dispatched':False,'owner_accepted':False}

executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=conversation,
    timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'mechanical_passed':executed['mechanical_passed'],'reached':endpoint['reached'],'new_acceptance_dispatched':False,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if executed['mechanical_passed'] and endpoint['reached'] else 1)
