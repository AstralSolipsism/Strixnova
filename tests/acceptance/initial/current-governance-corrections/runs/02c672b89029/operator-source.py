"""Forward the registered plan decision, stopping at the next authority decision."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn

parser=argparse.ArgumentParser()
for key in ['initial-run','author-run','gate-run','secondary-id']:parser.add_argument('--'+key,required=True)
args=parser.parse_args()
directories={key:(ROOT/'.artifacts/validation'/getattr(args,key.replace('-','_'))).resolve() for key in ['initial-run','author-run','gate-run']}
for directory in directories.values():
    assert directory.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((directory/'result.json').read_text(encoding='utf-8'))
    assert result['status']=='passed' and result['process_settled']
initial=json.loads((directories['initial-run']/'evidence/registration.json').read_text(encoding='utf-8'))
gate=json.loads((directories['gate-run']/'evidence/gate-binding.json').read_text(encoding='utf-8'))
assert gate['fixed_input_dispatch_permitted'] and gate['candidate_kind']=='engineering_plan'
assert sha(Path(gate['review_report']))==gate['review_report_sha256']
report=json.loads(Path(gate['review_report']).read_text(encoding='utf-8'))
assert report['execution']['report_valid'] and all(row['summary']['status']=='passed' and not row['issues'] for row in report['cases'])
prior=json.loads((directories['author-run']/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert prior['mechanical_passed'] and not prior['verdict']['unsettled_steps']
built=candidate(Path(initial['candidate_registration']));assert built==initial['candidate']
project=Path(initial['project']).resolve();assert project.is_relative_to(ROOT/'.artifacts/validation')
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']);identifier=gate['work_item_id']

def current(work_item):
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',work_item],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=current(identifier);secondary=current(args.secondary_id)
assert before['work_item_version']==gate['work_item_version']
assert before['current_action']['action_type']=='confirm_engineering_plan'
assert before['current_action']['confirmation_challenge']['candidate_fingerprint']==gate['candidate_fingerprint']
assert secondary['current_action']['action_type']=='confirm_direction'

def business_files():
    files={}
    for relative in ['src.py','src','tests']:
        path=project/relative
        candidates=[path] if path.is_file() else list(path.rglob('*')) if path.is_dir() else []
        for child in candidates:
            if child.is_file() and '__pycache__' not in child.parts:
                files[child.relative_to(project).as_posix()]=sha(child)
    return files
protected=business_files()
assert all(sha(project/path)==digest for path,digest in initial['protected_source'].items())
prompt='同意当前展示的工程方案，仅在本临时测试工程内实施与验证；实际结果接受前不要提交。'
assert prompt in (ROOT/'docs/engineering/agent-acceptance.md').read_text(encoding='utf-8')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'before.json',before);dump(evidence/'secondary-before.json',secondary)
dump(evidence/'registration.json',{'phase':'G4-plan-acceptance-and-authority-preparation','project':str(project),
    'candidate':built,'work_item_id':identifier,'secondary_work_item_id':args.secondary_id,'accepted_plan_gate':gate,
    'fixed_owner_input':prompt,'fixed_owner_input_sha256':sha(evidence/'user-input.txt'),
    'authority_input_reserved_not_dispatched':initial['fixed_inputs']['accept_authorities'],
    'protected_business_files':protected,'model':initial['model'],'timeout_seconds':600,'max_neutral_continuations':0,
    'owner_accepted':False,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')

def observe():
    state=current(identifier);other=current(args.secondary_id)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==initial['initial_commit'] and business_files()==protected
    other_unchanged=other['work_item_version']==secondary['work_item_version'] and other['current_action']==secondary['current_action']
    return {'reached':state['current_action']['action_type']=='confirm_project_authority_candidates' and unchanged and other_unchanged,
            'next':state,'business_source_and_git_unchanged':unchanged,'secondary_direction_unchanged':other_unchanged,
            'semantic_readiness':'pending independent review of actual current authority candidates and their recorded review'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],
    conversation_id=prior['last_result']['conversation_id'],timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'phase':'G4-authority-preparation','mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],
         'authority_acceptance_dispatched':False,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
