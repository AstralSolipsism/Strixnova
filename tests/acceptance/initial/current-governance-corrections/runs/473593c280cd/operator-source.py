"""Bound the remaining reference repair to one exact byte replacement."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/6bbae8a5d2e5/evidence/registration.json').read_text(encoding='utf-8'))
prior_root=ROOT/'.artifacts/validation/04a7570f98a9'
assert json.loads((prior_root/'result.json').read_text(encoding='utf-8'))['status']=='passed'
prior=json.loads((prior_root/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert prior['mechanical_passed'] and not prior['verdict']['unsettled_steps']
built=candidate(Path(initial['candidate_registration']));assert built==initial['candidate']
project=Path(initial['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
relative='docs/architecture/architecture-domain-facts.yaml';target=project/relative
before=target.read_bytes();old=b'revision_id: MODELREV-2222222222222222';new=b'revision_id: MODELREV-3333333333333333'
assert before.count(old)==1
expected=before.replace(old,new,1)
protected={}
for base in [project/'docs',project/'src',project/'tests']:
    if base.is_dir():
        for p in base.rglob('*'):
            if p.is_file() and p!=target and '__pycache__' not in p.parts:protected[p.relative_to(project).as_posix()]=sha(p)
protected['src.py']=sha(project/'src.py')
def state(identity):
    p=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(p.stdout)['next']
identities=['WI-20260929-DEC61550','WI-20260929-274215EA']
original_states={i:state(i) for i in identities}
assert original_states[identities[0]]['work_item_version']==12
assert original_states[identities[0]]['current_action']['action_type']=='confirm_engineering_plan'
prompt=(f'继续修订既有待确认候选，仅纠正一个机械版本绑定：{relative} 的 domain_model_ref.revision_id 仍为 MODELREV-2222222222222222，'
 '而实际 docs/architecture/model.yaml 的 domain_model_ref.revision_id 与当前领域候选均为 MODELREV-3333333333333333。'
 '请核对这两个现有文件，仅将该旧修订号替换为3333333333333333的当前修订号，保留其他字节；无需重新读取整套已读材料。'
 '这是当前授权范围的候选引用纠正，不是接受或新的业务决定。不要修改其他文件，不运行写状态命令，不接受或重提方案，不实施代码、不提交Git。完成这一处后停止并如实说明。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');(evidence/'before.yaml').write_bytes(before)
dump(evidence/'registration.json',{'phase':'one-exact-revision-binding-repair','project':str(project),'candidate':built,
    'target':relative,'before_sha256':sha(target),'expected_after_sha256':__import__('hashlib').sha256(expected).hexdigest(),
    'input_sha256':sha(evidence/'user-input.txt'),'protected_files':protected,'original_states':original_states,
    'model':initial['model'],'timeout_seconds':180,'max_neutral_continuations':0,'owner_accepted':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    same=all(sha(project/p)==h for p,h in protected.items())
    unchanged=all(state(i)==s for i,s in original_states.items())
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    exact=target.read_bytes()==expected
    return {'reached':exact and same and unchanged and head==initial['initial_commit'],
            'exact_expected_bytes':exact,'other_files_unchanged':same,'public_states_unchanged':unchanged,
            'head_unchanged':head==initial['initial_commit'],'owner_accepted':False}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=prior['last_result']['conversation_id'],
    timeout=180,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
(evidence/'after.yaml').write_bytes(target.read_bytes())
summary={'mechanical_passed':receipt['mechanical_passed'],**endpoint};dump(evidence/'phase-summary.json',summary)
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
