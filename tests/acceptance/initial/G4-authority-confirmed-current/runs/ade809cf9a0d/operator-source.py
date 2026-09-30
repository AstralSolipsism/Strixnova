"""Fresh native session for exact outstanding candidate-reference edits only."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
built=candidate(Path(initial['candidate_registration']));assert built==initial['candidate']
project=Path(initial['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
replacements={
 'docs/domain/model.yaml':[('revision_id: REVISION-2222222222222222','revision_id: REVISION-3333333333333333')],
 'docs/product/prd.md':[
  ('- 产品定义 `REVISION-2222222222222222`（draft）','- 产品定义 `REVISION-3333333333333333`（待确认候选）'),
  ('- 领域模型 `MODELREV-2222222222222222`（draft）','- 领域模型 `MODELREV-3333333333333333`（待确认候选）'),
  ('| 负责人周报 | 按自然周的状态分布统计 + 终端交互 | 当前目标（可独立交付） |','| 负责人周报 | 按自然周的状态分布统计 + 终端交互 | 后续候选；独立事项方向待确认 |')]}
expected={};before_hashes={}
for relative,items in replacements.items():
    body=(project/relative).read_bytes();before_hashes[relative]=sha(project/relative)
    for old,new in items:
        old,new=old.encode('utf-8'),new.encode('utf-8');assert body.count(old)==1,relative
        body=body.replace(old,new,1)
    expected[relative]=body
    saved=evidence/'before'/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(project/relative,saved)
def public(identity):
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(result.stdout)['next']
ids=['WI-20260929-DEC61550','WI-20260929-274215EA'];states={i:public(i) for i in ids}
assert states[ids[0]]['work_item_version']==16 and states[ids[0]]['current_action']['action_type']=='confirm_engineering_plan'
assert states[ids[1]]['current_action']['action_type']=='confirm_direction'
protected={}
for relative in ['docs','src','tests','src.py']:
    base=project/relative
    for p in ([base] if base.is_file() else base.rglob('*') if base.is_dir() else []):
        if p.is_file() and p.relative_to(project).as_posix() not in expected and '__pycache__' not in p.parts:protected[p.relative_to(project).as_posix()]=sha(p)
prompt=('这是既有事项WI-20260929-DEC61550的候选文档整改，不是新建事项，也不是任何接受输入。先读取AGENTS.md和指定Skill。'
 '原固定请求已允许起草和修改产品、领域、架构、政策候选及PRD；这些候选文档不是禁止修改的业务源码。当前方案版本16仍未接受，周报方向仍未接受。'
 '本次只按下面四个已核实的精确替换同步两份候选文档的引用和来源状态。新修订号来自当前真实产品/领域候选，周报待决定来自实际公开状态；不改变业务定义，不确认或重提任何方案，不intake，不修改其他文件、源码、tests或Git。'
 '保持其他字节不变。完成后简要说明修正，并清楚保留仍待独立复核及负责人决定的状态，然后停止。\n'+json.dumps(replacements,ensure_ascii=False,indent=2))
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{'phase':'exact-candidate-reference-correction','project':str(project),'candidate':built,
 'fixed_input':prompt,'input_sha256':sha(evidence/'user-input.txt'),'before_hashes':before_hashes,
 'expected_after_hashes':{p:hashlib.sha256(b).hexdigest() for p,b in expected.items()},'public_before':states,
 'model':initial['model'],'timeout_seconds':240,'max_continuations':0,'owner_accepted':False,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    exact=all((project/p).read_bytes()==body for p,body in expected.items())
    unchanged=all(sha(project/p)==digest for p,digest in protected.items()) and all(public(i)==state for i,state in states.items())
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    return {'reached':exact and unchanged and head==initial['initial_commit'],'exact_expected_edits':exact,
            'other_files_and_states_unchanged':unchanged,'head_unchanged':head==initial['initial_commit'],'owner_accepted':False}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],timeout=240,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
for relative in expected:
    saved=evidence/'after'/relative;saved.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(project/relative,saved)
summary={'mechanical_passed':receipt['mechanical_passed'],**endpoint};dump(evidence/'phase-summary.json',summary)
print(json.dumps(summary,ensure_ascii=False));raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
