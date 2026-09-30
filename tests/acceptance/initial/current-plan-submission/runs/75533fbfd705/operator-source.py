"""One bounded fresh native session resumes the actual accepted direction."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
parser=argparse.ArgumentParser()
for name in ['initial-run','previous-run','work-item-id','secondary-id']:parser.add_argument('--'+name,required=True)
parser.add_argument('--timeout-seconds',type=int,choices=[420,900],default=900)
options=parser.parse_args()
initial_path=(ROOT/'.artifacts/validation'/options.initial_run/'evidence/registration.json').resolve()
previous=(ROOT/'.artifacts/validation'/options.previous_run).resolve()
assert initial_path.is_relative_to(ROOT/'.artifacts/validation') and previous.is_relative_to(ROOT/'.artifacts/validation')
result=json.loads((previous/'result.json').read_text(encoding='utf-8'))
old=json.loads((previous/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert result['status']=='failed' and result['process_settled'] and not old['verdict']['unsettled_steps']
conversation=None
if old['outcome']=='host_error':
    assert 'Individual quota reached' in old['last_result']['error']
elif old['outcome']=='deadline':
    assert not old['verdict']['failed_steps']
    observed_ids={step['conversation_id'] for step in old['verdict']['tool_steps'] if step.get('conversation_id')}
    assert len(observed_ids)==1,'Resume requires one recorded conversation and no unsettled tools'
    conversation=observed_ids.pop()
    prior_endpoint=json.loads((previous/'evidence/endpoint.json').read_text(encoding='utf-8'))
    assert prior_endpoint['business_source_and_git_unchanged'] and prior_endpoint['secondary_direction_unchanged']
else:
    raise AssertionError('Only settled quota or deadline interruptions are resumable here')
initial=json.loads(initial_path.read_text(encoding='utf-8'))
project=Path(initial['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
built=candidate(Path(initial['candidate_registration']));assert built==initial['candidate'];identifier=options.work_item_id
def public():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier,'--record','direction','--record','direction_confirmation','--max-output-bytes','262144'],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    state=json.loads(result.stdout)['next']
    assert state['reading']['complete'] is True and not state['record_pages']
    return state
before=public();assert before['current_action']['action_type']=='submit_engineering_assessment'
assert before['records']['direction_confirmation']['accepted'] is True
dump(evidence/'initial-public-state.json',before)
def secondary():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',options.secondary_id],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    return json.loads(result.stdout)['next']
secondary_before=secondary();assert secondary_before['current_action']['action_type']=='confirm_direction'
dump(evidence/'secondary-before.json',secondary_before)
prompt=(f'请接续本隔离工程现有事项 {identifier}，先读取AGENTS.md和指定Skill及该事项当前公开动作、已确认方向。'
 '撤回事项的方向接受已真实记录，本条没有新的确认或授权扩大，不要重发确认。上一会话因个人额度中断，尚未提交工程评估，原始记录完整保留。'
 '本条要求实际完成仍在授权内的工程调查、方案候选起草和公开提交，形成可审阅工程方案后再等待负责人。'
 f'本次已有接受仅绑定撤回事项 {identifier}；周报事项 {options.secondary_id} 仍等待方向决定。上一作者文字称两个方向都已接受与实际记录不符，不得据此确认周报。共同权威与跨单元约束仍须在实施前统一。'
 '保持原业务事实，尚不实施业务代码，不把规划当实际候选文件，不记录方案或权威接受、不提交Git。'
 '如确有无法依已有事实完成的实质缺口，明确指出并停止，不编造业务决定或只给未来承诺。')
if conversation:
    prompt=(f'继续本会话已经授权的撤回事项 {identifier} 工程调查和方案提交。上一调用因15分钟时限结束，未收到最终答复；'
      '工具记录显示你已读过指引和合同、完成调查，并在两次程序拒绝后重新写入 .agent-inputs/ea_payload.json。'
      '沿用本会话已有阅读和实际草稿，不从头重复阅读整套材料；核对当前公开动作，按真实校验结果完成必要修正、实际提交并展示工程方案后等待负责人。'
      '原始拒绝必须保留，不宣称首次通过。若仍有不能依据已知事实解决的实质问题，明确报告并停止，不猜测业务决定。'
      f'本条没有任何新的接受：撤回方向已经确认，不重发；周报事项 {options.secondary_id} 仍待方向决定，不确认它。'
      '不接受方案或四类权威、不实施业务代码、不提交Git。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{'phase':'bounded-fresh-resume-of-G4-G2-plan','candidate':built,'project':str(project),
 'work_item_id':identifier,'secondary_work_item_id':options.secondary_id,'previous_incomplete_run':options.previous_run,'fixed_input':prompt,'author_model':initial['model'],
 'timeout_seconds':options.timeout_seconds,'resume_conversation_id':conversation,'max_neutral_continuations':0,'scope':'Resume same actual item and fixed business facts; no new owner acceptance.',
 'owner_accepted':False,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    state=json.loads(result.stdout)['next']
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==initial['initial_commit'] and all(sha(project/p)==h for p,h in initial['protected_source'].items())
    secondary_now=secondary()
    secondary_unchanged=(secondary_now['work_item_version']==secondary_before['work_item_version'] and secondary_now['current_action']==secondary_before['current_action'])
    return {'reached':state['current_action']['action_type']=='confirm_engineering_plan' and unchanged and secondary_unchanged,
     'next':state,'business_source_and_git_unchanged':unchanged,'secondary_direction_unchanged':secondary_unchanged,'semantic_readiness':'pending independent plan review'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=conversation,timeout=options.timeout_seconds,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'phase':'G4/G2-plan-resume','mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],
 'conversation_id':receipt['last_result'].get('conversation_id'),'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
