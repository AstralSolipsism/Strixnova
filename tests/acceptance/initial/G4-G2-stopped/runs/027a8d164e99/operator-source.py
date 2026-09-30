"""One bounded fresh native session resumes the actual accepted direction."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/b3ed58aca29c/evidence/registration.json').read_text(encoding='utf-8'))
project=Path(initial['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json');identifier='WI-20260928-9A2A1BC1'
def public():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier,'--record','direction','--record','direction_confirmation','--max-output-bytes','262144'],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    state=json.loads(result.stdout)['next']
    assert state['reading']['complete'] is True and not state['record_pages']
    return state
before=public();assert before['current_action']['action_type']=='submit_engineering_assessment'
assert before['records']['direction_confirmation']['accepted'] is True
dump(evidence/'initial-public-state.json',before)
prompt=('请接续本隔离工程现有事项 WI-20260928-9A2A1BC1，先读取AGENTS.md和指定Skill及该事项当前公开动作、已确认方向。'
 '方向接受已真实记录，本条没有新的确认或授权扩大，也不要再次询问方向。此前会话未实际提交方案，其中一次只说明将要起草，另一次达到时限；原始记录完整保留。'
 '本条要求实际完成仍在授权内的工程调查、方案候选起草和公开提交，形成可审阅工程方案后再等待负责人。'
 '成员撤回是本项结果，周报由已有相关事项独立交付；共同权威与跨单元约束须在实施前统一。'
 '保持原业务事实，尚不实施业务代码，不把规划当实际候选文件，不记录方案或权威接受、不提交Git。'
 '如确有无法依已有事实完成的实质缺口，明确指出并停止，不编造业务决定或只给未来承诺。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{'phase':'bounded-fresh-resume-of-G4-G2-plan','candidate':built,'project':str(project),
 'work_item_id':identifier,'previous_incomplete_runs':['45c96e481518','225561c9cc68'],'author_model':'gemini-3.1-pro-high','model_availability_verified':'agy models on 2026-09-28','fixed_input':prompt,
 'timeout_seconds':900,'max_neutral_continuations':0,'scope':'Resume same actual item and fixed business facts; no new owner acceptance.',
 'owner_accepted':False,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    state=json.loads(result.stdout)['next']
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==initial['initial_commit'] and all(sha(project/p)==h for p,h in initial['protected_source'].items())
    return {'reached':state['current_action']['action_type']=='confirm_engineering_plan' and unchanged,
     'next':state,'business_source_and_git_unchanged':unchanged,'semantic_readiness':'pending independent plan review'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.1-pro-high',timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'phase':'G4/G2-plan-resume','mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],
 'conversation_id':receipt['last_result'].get('conversation_id'),'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
