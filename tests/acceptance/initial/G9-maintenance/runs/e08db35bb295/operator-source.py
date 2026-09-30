"""Finish only the previously unstarted read-only load phase; never repeat maintenance."""
from pathlib import Path
import base64,json,os,shutil,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,sha,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest
original=ROOT/'.artifacts/validation/7c5f90ac0b8f/evidence'
info=json.loads((original/'registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);installation=Path(info['installation_root']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
selected=json.loads((installation/'active.json').read_text(encoding='utf-8'));runtime=selected['runtime']
assert runtime['build_sha256']==info['target_candidate']['build_sha256']
for phase in ['check','recover-update']:
    result=json.loads((original/phase/'execution/driver-receipt.json').read_text(encoding='utf-8'))
    assert result['mechanical_passed'] and json.loads((original/phase/'endpoint.json').read_text(encoding='utf-8'))['reached']
assert not (original/'reload/execution/events.jsonl').exists(),'Do not restart a possibly running load phase'
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==runtime['skill_sha256']
dump(evidence/'registration.json',{**info,'resume_scope':'Only the unstarted load phase; first outer attempt failed on incorrect new-output precondition, not on maintenance.',
 'previous_run':'7c5f90ac0b8f','selected_runtime':selected})
shutil.copyfile(__file__,evidence/'operator-source.py')
prompt=info['fixed_inputs']['reload'];(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
protected=snapshot(project)
def observe():
    entries=[];path=evidence/'execution/events.jsonl'
    if path.exists():entries=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    tools=assess_turn(entries)['tool_steps']
    invoked=any(runtime['entrypoint'].lower() in json.dumps(s,ensure_ascii=False).lower() and 'history' in json.dumps(s,ensure_ascii=False) for s in tools)
    unchanged=snapshot(project)==protected
    return {'reached':invoked and unchanged,'actual_selected_entry_history_used':invoked,'project_files_unchanged':unchanged,
       'matching_skill_sha256':directory_manifest(project/'.agents/skills/strixnova')['sha256']}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',timeout=300,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(s) for s in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
call=subprocess.run([runtime['entrypoint'],'upgrade','status','--project-dir',str(project),'--upgrade-id',selected['upgrade_id']],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
status=json.loads(call.stdout);assert status['upgrade']['state']=='completed';dump(evidence/'final-status.json',status)
saved=json.loads(Path(info['operation_record']).read_bytes())
assert base64.b64decode(saved['original_record_base64'])==(original/'original-start-record.json').read_bytes()
assert sha(Path(info['business_output']))==info['business_output_sha256']
dump(evidence/'preservation-check.json',{'original_start_preserved':True,'business_output_unchanged':True,'business_command_repeated':False,
 'source_skill_sha256':info['source_candidate']['skill_sha256'],'new_session_skill_sha256':runtime['skill_sha256'],
 'host_scope':'One fresh conversation explicitly read matching Skill; ordinary automatic loading remains unverified.'})
sources={};outputs=[]
for phase,base in [('check',original/'check'),('recover-update',original/'recover-update'),('reload',evidence)]:
    for name,role in [('user-input.txt','user_input'),('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]:
        identity=phase+'/'+name;sources[identity]={'path':str(base/name),'role':role}
        if role.startswith('author_'):outputs.append(identity)
for name in ['registration.json','owned-process-exit.json','owned_interrupted_writer.py','interrupted-operations.json','original-start-record.json','initial-history.json']:
    sources['original/'+name]={'path':str(original/name),'role':'original_input'}
for base,names in [(original,['target-history.json','selected-runtime.json']),(evidence,['final-status.json','preservation-check.json'])]:
    for name in names:sources[name]={'path':str(base/name),'role':'author_artifact'};outputs.append(name)
for path in (project/'.actor-evidence').iterdir():sources['stop-material/'+path.name]={'path':str(path),'role':'original_input'}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-UPGRADE-UNCLOSED-EXECUTION')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'一个真实当前格式中断操作的预检阻断、真实停止材料恢复、同格式程序/Skill安装更新及新会话显式加载；无旧格式迁移或普通宿主变更。外层包装器最初错误单独保留。',
 'machine_checks':{'three_native_phases_settled':True,'original_start_and_business_output_preserved':True,'target_identity_matches':True}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
