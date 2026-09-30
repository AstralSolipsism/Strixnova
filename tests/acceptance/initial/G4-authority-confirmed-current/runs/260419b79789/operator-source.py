"""Continue actual pending authority review without repeating acceptance."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
prior=ROOT/'.artifacts/validation/156586864345'
result=json.loads((prior/'result.json').read_text(encoding='utf-8'));assert result['process_settled'] and result['status']=='failed'
old=json.loads((prior/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert old['outcome']=='deadline' and not old['verdict']['failed_steps'] and not old['verdict']['unsettled_steps']
conversations={s['conversation_id'] for s in old['verdict']['tool_steps'] if s.get('conversation_id')};assert len(conversations)==1
project=Path(initial['project']);built=candidate(Path(initial['candidate_registration']));evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
identifier='WI-20260929-DEC61550';secondary='WI-20260929-274215EA'
def public(identity):
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(result.stdout)['next']
before=public(identifier);other_before=public(secondary)
assert before['work_item_version']==21 and before['current_action']['action_type']=='review_project_authority_candidates'
assert other_before['current_action']['action_type']=='confirm_direction'
def business():
    found={}
    for relative in ['src.py','src','tests']:
        p=project/relative
        for f in ([p] if p.is_file() else p.rglob('*') if p.is_dir() else []):
            if f.is_file() and '__pycache__' not in f.parts:found[f.relative_to(project).as_posix()]=sha(f)
    return found
protected=business();shutil.copytree(project/'docs',evidence/'candidate-before')
prompt=('继续本会话已有事项WI-20260929-DEC61550。R5方案接受及四类候选逐类展示已经实际完成，当前版本21、动作review_project_authority_candidates。'
 '不要重发方案接受，也不要重复已经完成的展示。上一调用到达时限前已按程序报错修正底账中的partial/not_started等不合法枚举。'
 '请复用已读材料，先按当前公开合同核对刚写的底账，读取完整候选复核包，按真实文件完成八视角复核并实际提交；通过后完整展示候选包及限制，停止等待负责人决定。'
 '保留此前错误，不把字段修正当成已通过复核。不接受四类候选、不修改周报方向、不写业务源码或tests、不提交Git。遇实质未决事实则明确停止，不虚构。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
dump(evidence/'registration.json',{'phase':'bounded-authority-review-continuation','project':str(project),'candidate':built,
 'fixed_non_accepting_input':prompt,'input_sha256':sha(evidence/'user-input.txt'),'before':before,'secondary_before':other_before,
 'model':initial['model'],'timeout_seconds':600,'max_continuations':0,'owner_accepted':False})
def observe():
    state=public(identifier);other=public(secondary)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    stable=business()==protected and head==initial['initial_commit']
    other_same=other['work_item_version']==other_before['work_item_version'] and other['current_action']==other_before['current_action']
    return {'reached':state['current_action']['action_type']=='confirm_project_authority_candidates' and stable and other_same,
            'next':state,'business_source_and_git_unchanged':stable,'secondary_direction_unchanged':other_same,'owner_accepted':False}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=conversations.pop(),
    timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
shutil.copytree(project/'docs',evidence/'candidate-after')
summary={'mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],'authority_acceptance_dispatched':False,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
