"""Correct escaped-string matching from preserved events; no native phase is replayed."""
from pathlib import Path
import base64,json,os,shutil,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,sha
from scripts.agent_acceptance import assess_turn
from scripts.review_antigravity_evidence import run_review
first=ROOT/'.artifacts/validation/7c5f90ac0b8f/evidence'
reload=ROOT/'.artifacts/validation/e08db35bb295/evidence'
info=json.loads((first/'registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);installation=Path(info['installation_root']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
selected=json.loads((installation/'active.json').read_text(encoding='utf-8'));runtime=selected['runtime']
old=json.loads((reload/'execution/driver-receipt.json').read_text(encoding='utf-8'))
events=[json.loads(s) for s in (reload/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
transport=assess_turn(events);assert transport['tool_flow_complete'] and old['exit_code']==0 and not old['forced_termination']
assert old['final_observation']['project_files_unchanged']
matching=[]
for step in transport['tool_steps']:
    command=(step.get('tool_info',{}).get('parameters') or {}).get('CommandLine','')
    if step['tool_name']=='run_command' and step['state']=='DONE' and runtime['entrypoint'].casefold() in command.casefold() and ' history ' in command:
        matching.append({'step_index':step['step_index'],'command':command})
assert matching,'Actual raw command does not show selected entry history use'
corrected=assess_turn(events,scenario_reached=True);assert corrected['scenario_passed']
dump(evidence/'observer-correction.json',{'original_run':'e08db35bb295','original_outcome':old['outcome'],
 'original_endpoint':old['final_observation'],'correction':'Compare the actual unescaped CommandLine value, not JSON serialization that doubles Windows backslashes.',
 'raw_events_sha256':sha(reload/'execution/events.jsonl'),'matching_actual_commands':matching,
 'corrected_transport_and_endpoint_passed':True,'native_execution_repeated':False,'semantic_content_machine_proven':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
call=subprocess.run([runtime['entrypoint'],'upgrade','status','--project-dir',str(project),'--upgrade-id',selected['upgrade_id']],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
status=json.loads(call.stdout);assert status['upgrade']['state']=='completed';dump(evidence/'final-status.json',status)
saved=json.loads(Path(info['operation_record']).read_bytes())
assert base64.b64decode(saved['original_record_base64'])==(first/'original-start-record.json').read_bytes()
assert sha(Path(info['business_output']))==info['business_output_sha256']
dump(evidence/'preservation-check.json',{'original_start_preserved':True,'business_output_unchanged':True,
 'target_build_sha256':runtime['build_sha256'],'target_skill_sha256':runtime['skill_sha256'],
 'scope':'One declared fixture and named output; no rerun of the business command or maintenance.'})
sources={};outputs=[]
for phase,base in [('check',first/'check'),('recover-update',first/'recover-update'),('reload',reload)]:
    for name,role in [('user-input.txt','user_input'),('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]:
        key=phase+'/'+name;sources[key]={'path':str(base/name),'role':role}
        if role.startswith('author_'):outputs.append(key)
for name in ['registration.json','owned-process-exit.json','owned_interrupted_writer.py','interrupted-operations.json','original-start-record.json','initial-history.json']:
    sources['original/'+name]={'path':str(first/name),'role':'original_input'}
for base,names in [(first,['target-history.json','selected-runtime.json']),(evidence,['final-status.json','preservation-check.json','observer-correction.json'])]:
    for name in names:sources[name]={'path':str(base/name),'role':'author_artifact'};outputs.append(name)
for path in (project/'.actor-evidence').iterdir():sources['stop-material/'+path.name]={'path':str(path),'role':'original_input'}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-UPGRADE-UNCLOSED-EXECUTION')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'实际原生预检阻断、停止证据恢复、同格式安装切换与新会话显式加载。包装器先误用新输出检查，后将Windows路径与JSON转义字符串比较；原失败均保留，第三阶段未重演，只对实际原始事件纠正确定性判断。',
 'machine_checks':{'actual_native_tool_flows_settled':True,'corrected_entrypoint_check_supported_by_raw_commands':True,
 'original_start_and_business_output_preserved':True,'target_selected_and_maintenance_closed':True}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'observer_corrected_from_preserved_events':True,'native_execution_repeated':False,'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
