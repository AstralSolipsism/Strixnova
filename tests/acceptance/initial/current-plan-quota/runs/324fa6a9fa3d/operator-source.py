"""Use the existing native driver to dispatch only the exact gated direction input."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
parser=argparse.ArgumentParser()
for name in ['initial-run','latest-run','gate-run']:parser.add_argument('--'+name,required=True)
options=parser.parse_args()
def closed(identity):
    base=(ROOT/'.artifacts/validation'/identity).resolve();assert base.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((base/'result.json').read_text(encoding='utf-8'))
    assert result['status']=='passed' and result['process_settled']
    return base/'evidence'
initial=closed(options.initial_run);latest=closed(options.latest_run);gated=closed(options.gate_run)
gate=json.loads((gated/'gate-binding.json').read_text(encoding='utf-8'))
assert gate['fixed_input_dispatch_permitted']
report_path=Path(gate['review_report']).resolve();assert report_path.is_relative_to(gated)
assert sha(report_path)==gate['review_report_sha256']
report=json.loads(report_path.read_text(encoding='utf-8'))
assert report['execution']['report_valid'] and report['execution']['mechanical_passed']
assert len(report['cases'])==1 and report['cases'][0]['summary']['status']=='passed'
registration=json.loads((initial/'registration.json').read_text(encoding='utf-8'))
built=candidate(Path(registration['candidate_registration']));assert built==registration['candidate']==gate['author_candidate']
project=Path(registration['project']).resolve();assert project.is_relative_to(ROOT/'.artifacts/validation')
receipt=json.loads((latest/'execution/driver-receipt.json').read_text(encoding='utf-8'));assert receipt['mechanical_passed']
identifier=gate['work_item_id'];evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
def current():
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],
        capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=current();action=before['current_action']
assert action['action_type']=='confirm_direction' and action['actor']=='user'
assert before['work_item_version']==gate['work_item_version']
assert action['confirmation_challenge']['candidate_fingerprint']==gate['candidate_fingerprint']
prompt='现在理解这份方向说明了，同意这个方向，请继续制定工程方案。'
dump(evidence/'registration.json',{'group':'G4/G2','phase':'plan-after-current-direction-gate',
    'initial_run':options.initial_run,'latest_run':options.latest_run,'gate_run':options.gate_run,
    'project':str(project),'candidate':built,'fixed_owner_input':prompt,
    'input_sha256':hashlib.sha256(prompt.encode('utf-8')).hexdigest(),
    'authority_input_reserved_not_dispatched':registration['fixed_inputs']['accept_authorities'],
    'author_model':registration['model'],'max_neutral_continuations':0,
    'owner_accepted':False,'os_isolation_verified':False})
dump(evidence/'accepted-gate-binding.json',gate);dump(evidence/'before.json',before)
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    state=current()
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    protected=head==registration['initial_commit'] and all(sha(project/p)==h for p,h in registration['protected_source'].items())
    return {'reached':state['current_action']['action_type']=='confirm_engineering_plan' and protected,
            'next':state,'business_source_and_git_unchanged':protected,'semantic_readiness':'pending independent plan review'}
executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=registration['model'],
    conversation_id=receipt['last_result']['conversation_id'],timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'mechanical_passed':executed['mechanical_passed'],'endpoint':endpoint,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if executed['mechanical_passed'] and endpoint['reached'] else 1)
