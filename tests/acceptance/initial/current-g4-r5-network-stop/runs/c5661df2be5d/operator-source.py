"""Finish the missing owner-facing presentation without changing the candidate."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
prior=ROOT/'.artifacts/validation/cf46a1d79200'
result=json.loads((prior/'result.json').read_text(encoding='utf-8'));assert result['process_settled']
old=json.loads((prior/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert old['outcome']=='deadline' and not old['verdict']['unsettled_steps'] and not old['verdict']['failed_steps']
conversations={s['conversation_id'] for s in old['verdict']['tool_steps'] if s.get('conversation_id')};assert len(conversations)==1
project=Path(initial['project']);built=candidate(Path(initial['candidate_registration']));evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
identifier='WI-20260929-DEC61550'
def public():
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(result.stdout)['next']
before=public();assert before['work_item_version']==14 and before['current_action']['action_type']=='confirm_engineering_plan'
def files():
    found={}
    for relative in ['docs','src','tests','src.py']:
        p=project/relative
        for f in ([p] if p.is_file() else p.rglob('*') if p.is_dir() else []):
            if f.is_file() and '__pycache__' not in f.parts:found[f.relative_to(project).as_posix()]=sha(f)
    return found
protected=files()
prompt=('工程评估已经实际提交成功，当前事项WI-20260929-DEC61550版本14，动作confirm_engineering_plan。上一调用在最终说明返回前达到时限，原始提交和拒绝记录保留。'
 '本次只读当前完整工程方案和已有owner_view，向负责人简洁但完整展示当前方案、相对上版的具体差异、编码前及编码后的底账安排、风险、验证和未实现边界，然后停止等待。'
 '不需要重新调查或重写评估；不修改任何候选文件、不提交命令、不接受或拒绝任何候选，不修改周报、不写业务代码或Git。没有新的接受输入。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');dump(evidence/'registration.json',{'phase':'read-only-plan-presentation','project':str(project),'candidate':built,'before':before,'fixed_input':prompt,'owner_accepted':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    state=public();same=state==before and files()==protected
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    return {'reached':same and head==initial['initial_commit'],'next':state,'candidate_files_and_state_unchanged':same,'business_source_and_git_unchanged':same and head==initial['initial_commit']}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,evidence=evidence/'execution',observe_endpoint=observe,
    model=initial['model'],conversation_id=conversations.pop(),timeout=180,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],'owner_accepted':False};dump(evidence/'phase-summary.json',summary)
print(json.dumps(summary,ensure_ascii=False));raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
