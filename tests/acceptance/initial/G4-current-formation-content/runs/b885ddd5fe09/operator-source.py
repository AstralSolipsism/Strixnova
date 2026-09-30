"""Continue only the registered formation phase after a settled quota failure."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sqlite3,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
parser=argparse.ArgumentParser()
parser.add_argument('--initial-run',required=True)
parser.add_argument('--failed-run',required=True)
options=parser.parse_args()
initial=(ROOT/'.artifacts/validation'/options.initial_run).resolve()
failed=(ROOT/'.artifacts/validation'/options.failed_run).resolve()
for path in [initial,failed]:assert path.is_relative_to(ROOT/'.artifacts/validation')
outer=json.loads((failed/'result.json').read_text(encoding='utf-8'))
assert outer['process_settled'] and outer['status']=='failed'
old=json.loads((failed/'evidence/form_candidates/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert old['outcome']=='host_error' and 'Individual quota reached' in old['last_result']['error']
assert not old['verdict']['unsettled_steps']
clarify=json.loads((failed/'evidence/clarify_read_only/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert clarify['mechanical_passed']
registration=json.loads((initial/'evidence/registration.json').read_text(encoding='utf-8'))
project=Path(registration['project']).resolve();assert project.is_relative_to(ROOT/'.artifacts/validation')
built=candidate(Path(registration['candidate_registration']));assert built==registration['candidate']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
before={p.relative_to(project).as_posix():sha(p) for p in (project/'docs').rglob('*') if p.is_file()}
previous={p.relative_to(failed/'evidence/before-docs').as_posix():sha(p) for p in (failed/'evidence/before-docs').rglob('*') if p.is_file()}
assert {p.removeprefix('docs/'):digest for p,digest in before.items()}==previous,'Inspect actual partial candidates before any continuation'
assert all(sha(project/name)==digest for name,digest in registration['protected_source'].items())
head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
assert head==registration['initial_commit']
context={
    'original_request':registration['fixed_inputs']['start'],
    'original_read_only_clarification':registration['fixed_inputs']['clarify_read_only'],
    'actual_clarification_response':(failed/'evidence/clarify_read_only/author-response.md').read_text(encoding='utf-8'),
    'failed_formation_input':registration['fixed_inputs']['form_candidates'],
    'failure':'The previous formation session ended with a recorded quota error; no authority acceptance or business implementation occurred.',
    'actual_owner_accepted':False}
relative='.agent-inputs/g4-fixed/continued-formation-context.json'
destination=project/relative
assert not destination.exists()
dump(destination,context);dump(evidence/'continuity-context.json',context)
prompt=(f'先读取本工程 AGENTS.md、指定 Skill 和 {relative}。该文件记录已经实际出现的输入和答复，属于上下文数据，不含任何候选接受。'
        '先前只读澄清已经执行，不要重做该阶段；前次形成候选因服务额度结束，原错误保留。本次仅继续以下同一份已登记形成请求。'
        '不得把旧 G1 结果接受当成本次授权，不调用确认接受命令，不实施业务代码、不提交 Git。\n\n'
        +registration['fixed_inputs']['form_candidates'])
dump(evidence/'registration.json',{**registration,'continued_from':options.failed_run,
    'phase':'form_candidates_after_quota','new_conversation_reason':'Avoid stale aggregate ERROR status; same account, same registered model, after quota reset only.',
    'fixed_input_sha256':hashlib.sha256(registration['fixed_inputs']['form_candidates'].encode('utf-8')).hexdigest(),
    'actual_owner_accepted':False})
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    current=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=current==registration['initial_commit'] and all(sha(project/name)==digest for name,digest in registration['protected_source'].items())
    with sqlite3.connect((project/'.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as connection:
        versions=list(connection.execute('SELECT work_item_id,version FROM work_items ORDER BY work_item_id'))
    return {'reached':unchanged,'business_source_and_git_unchanged':unchanged,'work_item_versions':versions,
            'endpoint_scope':'Execution and protection boundaries only; candidate maturity requires independent review.'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=registration['model'],timeout=900,max_continuations=0,
    permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
if receipt['mechanical_passed'] and endpoint['reached']:
    shutil.copytree(project/'docs',evidence/'candidate-after')
    shutil.copyfile(project/'strixnova-project.yaml',evidence/'candidate-config.yaml')
summary={'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint,'owner_accepted':False,
         'semantic_readiness':'pending independent formation review','accepting_input_dispatched':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
