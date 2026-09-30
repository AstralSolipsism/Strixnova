"""Two maintenance phases and a fresh explicit host-load check using native drivers."""
from pathlib import Path
from datetime import datetime,timezone
import base64,hashlib,json,os,shutil,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest
prep=ROOT/'.artifacts/validation/de0664ac093b/evidence'
info=json.loads((ROOT/'.artifacts/validation/d5ba73f19ec8/work/fixture.json').read_text(encoding='utf-8'))
source=candidate(ROOT/'.artifacts/candidates/initial-guidance/candidate.json');assert source==info['source_candidate']
target=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json');assert target==info['target_candidate']
project=Path(info['project']);installation=Path(info['installation_root']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==source['skill_sha256']
dump(evidence/'registration.json',{**info,'phase_timeouts':[420,900,300],
 'original_source_skill_sha256':source['skill_sha256'],'target_and_reviewer_skill_sha256':target['skill_sha256']})
shutil.copyfile(__file__,evidence/'operator-source.py')
for name in ['owned-process-exit.json','owned_interrupted_writer.py','interrupted-operations.json','original-start-record.json','initial-history.json']:
    shutil.copyfile(prep/name,evidence/name)
original_record=Path(info['operation_record']).read_bytes();assert hashlib.sha256(original_record).hexdigest()==info['original_record_sha256']
def call(entry,*args):
    result=subprocess.run([entry,*args,'--project-dir',str(project)],capture_output=True,text=True,encoding='utf-8',timeout=45)
    return result.returncode,json.loads(result.stdout)
def preserved():return sha(Path(info['business_output']))==info['business_output_sha256']
def native_outputs(stage):
    path=stage/'execution/events.jsonl'
    if not path.is_file():return []
    events=[json.loads(s) for s in path.read_text(encoding='utf-8').splitlines() if s.strip()]
    return assess_turn(events)['tool_steps']
phases=[];conversation=None
def execute(name,prompt,observer,limit,*,fresh=False):
    global conversation
    stage=evidence/name;stage.mkdir()
    (stage/'user-input.txt').write_text(prompt,encoding='utf-8')
    receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
      evidence=stage/'execution',observe_endpoint=lambda:observer(stage),model='gemini-3.8-flash-low',
      conversation_id=None if fresh else conversation,timeout=limit,max_continuations=0,permission_mode='auto_approve',
      new_output_paths=tuple(project/'.agent-inputs'/n for n in ['stop-evidence.json','upgrade-plan.json']))
    (stage/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
    dump(stage/'tool-steps.json',native_outputs(stage));endpoint=observer(stage);dump(stage/'endpoint.json',endpoint)
    phases.append((name,stage,receipt,endpoint))
    print(json.dumps({'phase':name,'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False),flush=True)
    if not receipt['mechanical_passed'] or not endpoint['reached']:raise SystemExit('Native phase did not settle; preserve this attempt')
    conversation=receipt['last_result']['conversation_id']
    return stage
def observe_check(stage):
    native_block=any('upgrade_unclosed_operations' in str(s.get('tool_info',{}).get('output','')) for s in native_outputs(stage))
    unchanged=Path(info['operation_record']).read_bytes()==original_record and preserved() and not installation.exists()
    return {'reached':native_block and unchanged,'native_precheck_reported_unclosed_operation':native_block,
      'original_record_and_output_unchanged':unchanged,'installation_not_created':not installation.exists()}
execute('check',info['fixed_inputs']['check'],observe_check,420)

actor_evidence=project/'.actor-evidence';actor_evidence.mkdir()
for name in ['owned-process-exit.json','owned_interrupted_writer.py','interrupted-operations.json','original-start-record.json']:
    shutil.copyfile(evidence/name,actor_evidence/name)
dump(actor_evidence/'continuous-stop-observation.json',{'observed_at':datetime.now(timezone.utc).isoformat(),
 'owned_process_run':json.loads((evidence/'owned-process-exit.json').read_text(encoding='utf-8')),
 'registered_output_sha256':info['business_output_sha256'],'current_output_sha256':sha(Path(info['business_output'])),
 'operation_start_sha256':sha(Path(info['operation_record'])),
 'facts':'The existing process supervisor returned after the exact owned child exited23, without a cleanup error. The frozen script launches no descendants. The original durable start remains unresolved and the one named business output remains unchanged.',
 'external_truth_machine_proven':False})
def observe_update(stage):
    if not (installation/'active.json').is_file():return {'reached':False,'reason':'target not selected'}
    selected=json.loads((installation/'active.json').read_text(encoding='utf-8'))
    runtime=selected['runtime']
    if runtime['build_sha256']!=target['build_sha256'] or runtime['skill_sha256']!=target['skill_sha256']:
        return {'reached':False,'reason':'selected identity does not match target'}
    code,status=call(runtime['entrypoint'],'upgrade','status','--upgrade-id',selected['upgrade_id'])
    code2,ops=call(runtime['entrypoint'],'upgrade','operations')
    saved=json.loads(Path(info['operation_record']).read_bytes())
    recovered=bool(saved.get('original_record_base64')) and base64.b64decode(saved['original_record_base64'])==original_record
    done=code==0 and status['upgrade']['state']=='completed' and code2==0 and ops['operations']==[] and recovered and preserved()
    return {'reached':done,'target_runtime':runtime,'upgrade_id':selected['upgrade_id'],
     'maintenance_state':status.get('upgrade',{}).get('state'),'unclosed_operation_count':len(ops.get('operations',[])),
     'original_start_preserved':recovered,'business_output_unchanged':preserved()}
execute('recover-update',info['fixed_inputs']['recover_and_update'],observe_update,900)
selected=json.loads((installation/'active.json').read_text(encoding='utf-8'));runtime=selected['runtime']
code,history=call(runtime['entrypoint'],'history','--work-item-id',info['work_item_id'],'--record','request','--record','events')
assert code==0;dump(evidence/'target-history.json',history);dump(evidence/'selected-runtime.json',selected)
assert history['history']['work_item']['work_item_id']==info['work_item_id']
shutil.copyfile(project/'AGENTS.md',evidence/'pre-reload-AGENTS.md')
shutil.copytree(project/'.agents/skills/strixnova',evidence/'pre-reload-skill')
shutil.copytree(Path(runtime['skill_path']),project/'.agents/skills/strixnova',dirs_exist_ok=True)
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==target['skill_sha256']
(project/'AGENTS.md').write_text(f'''# 本轮维护后的显式只读加载

使用 .agents/skills/strixnova/SKILL.md 和实际存在的 history-and-upgrade.md。当前实际入口为 `{runtime['entrypoint']}`；当前build为 `{target['build_sha256']}`，Skill为 `{target['skill_sha256']}`。maintenance-inputs.json保留更新前的原始来源，不代表现在的选中入口。仅读本项目与明确的专用安装根，不执行维护或业务写入，不调用子Agent。全部Python命令，包括JSON处理，必须用 `{sys.executable}`，禁止裸python/python3/py。原事项为 {info['work_item_id']}。本次仅证明本新会话显式读取配套Skill；普通宿主自动加载未检验。
''',encoding='utf-8')
def observe_reload(stage):
    same=preserved() and directory_manifest(project/'.agents/skills/strixnova')['sha256']==target['skill_sha256']
    outputs=native_outputs(stage)
    called=any(runtime['entrypoint'].lower() in json.dumps(s,ensure_ascii=False).lower() and 'history' in json.dumps(s,ensure_ascii=False) for s in outputs)
    return {'reached':same and called,'selected_entry_history_used':called,'business_output_unchanged':preserved(),
      'matching_skill_bytes_present':same,'scope':'Current fresh-session explicit load, not ordinary automatic host loading.'}
execute('reload',info['fixed_inputs']['reload'],observe_reload,300,fresh=True)

sources={};outputs=[]
for name,path,_,_ in phases:
    for filename,role in [('user-input.txt','user_input'),('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]:
        key=name+'/'+filename;sources[key]={'path':str(path/filename),'role':role}
        if role.startswith('author_'):outputs.append(key)
for name in ['registration.json','owned-process-exit.json','owned_interrupted_writer.py','interrupted-operations.json','original-start-record.json','initial-history.json']:
    sources['original/'+name]={'path':str(evidence/name),'role':'original_input'}
for name in ['target-history.json','selected-runtime.json']:
    sources[name]={'path':str(evidence/name),'role':'author_artifact'};outputs.append(name)
for p in actor_evidence.iterdir():sources['stop-material/'+p.name]={'path':str(p),'role':'original_input'}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-UPGRADE-UNCLOSED-EXECUTION')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'一个真实当前格式中断操作的预检阻断、凭真实停止材料公开恢复、同格式程序/Skill安装更新与新会话显式加载；不证明旧格式迁移、普通宿主自动加载或真实负责人接受。',
 'machine_checks':{'native_phases_settled':True,'original_record_and_output_preserved':True,'actual_target_runtime_selected':True}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'source_skill_sha256':source['skill_sha256'],'target_and_reviewer_skill_sha256':target['skill_sha256'],
 'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
