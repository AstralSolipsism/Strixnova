"""Native read-only history and goal overview over actual mixed records."""
from pathlib import Path
import hashlib,json,os,shutil,sqlite3,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
setup=ROOT/'.artifacts/validation/e991b516169e'
info=json.loads((setup/'work/fixture.json').read_text(encoding='utf-8'))
project=Path(info['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json');assert built==info['candidate']
scratch=project/'.agent-inputs/g8-read';scratch.mkdir()
original_agents=(project/'AGENTS.md').read_text(encoding='utf-8')
(evidence/'original-AGENTS.md').write_text(original_agents,encoding='utf-8')
(project/'AGENTS.md').write_text(original_agents+'\n仅允许把临时查询输出写入 .agent-inputs/g8-read/ 供分析；其余文件保持不变。\n',encoding='utf-8')
def protected():
    return {p:h for p,h in snapshot(project).items() if not p.startswith('.agent-inputs/g8-read/') and not p.endswith(('.sqlite3-wal','.sqlite3-shm')) and '__pycache__' not in p.split('/')}
def db_identity():
    with sqlite3.connect((project/'.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        names=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        data={name:c.execute('SELECT * FROM "'+name.replace('"','""')+'"').fetchall() for name in names}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,default=lambda x:x.hex() if isinstance(x,bytes) else str(x)).encode('utf-8')).hexdigest()
before=protected();database_before=db_identity()
def actual_records():
    records={}
    for identity in info['work_item_ids']:
        args=[built['entrypoint'],'history','--project-dir',str(project),'--work-item-id',identity,
              '--record','result','--record','decisions','--record','candidates','--record','verifications','--record','delivery','--record','relations','--limit','100']
        result=subprocess.run(args,capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
        records[identity]=json.loads(result.stdout)
    missing=subprocess.run([built['entrypoint'],'history','--project-dir',str(project),'--work-item-id',info['diagnostic_work_item_id'],
      '--record','output:'+info['failed_receipt_id']+':stdout'],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    records['missing-output']=json.loads(missing.stdout)
    return records
dump(evidence/'controller-public-facts.json',actual_records())
dump(evidence/'registration.json',{**info,'model':'gemini-3.8-flash-low','timeout_seconds':600,'os_isolation_verified':False,
 'protected_file_hashes':before,'initial_database_logical_sha256':database_before})
shutil.copyfile(__file__,evidence/'operator-source.py')
for name in ['real-failed-execution.json','real-not-run-record.json','actual-cancellation.json','setup-boundary.json','availability-change.json']:
    shutil.copyfile(setup/'evidence'/name,evidence/name)
(evidence/'user-input.txt').write_text(info['fixed_input'],encoding='utf-8')
def observe():
    same_files=protected()==before;same_db=db_identity()==database_before
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    return {'reached':same_files and same_db and head==info['integration_head'],
     'protected_files_unchanged':same_files,'all_database_table_contents_unchanged':same_db,
     'integration_head_unchanged':head==info['integration_head'],'scope':'Read-only boundaries; actual public-route use and meaning judged independently.'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=info['fixed_input'],
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(s) for s in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
sources={name:{'path':str(evidence/name),'role':role} for name,role in [
 ('user-input.txt','user_input'),('registration.json','original_input'),('controller-public-facts.json','original_input'),
 ('setup-boundary.json','original_input'),('real-failed-execution.json','original_input'),('real-not-run-record.json','original_input'),
 ('actual-cancellation.json','original_input'),('availability-change.json','original_input'),
 ('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]}
for path in scratch.rglob('*'):
    if path.is_file():sources['native-query/'+path.relative_to(scratch).as_posix()]={'path':str(path),'role':'author_artifact'}
outputs=[k for k,v in sources.items() if v['role'].startswith('author_')]
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
by_id={r['case_id']:r for r in catalog['cases']}
cases=[{k:by_id[identity][k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'同一隔离工程的真实已接受交付、未接受/被替代候选、实际失败/未运行/取消和真实输出缺失的只读说明。诊断起始方向/计划为公开合成前提；不证明其语义接受或新的建设。',
 'machine_checks':{'native_read_only_turn_settled':True,'database_and_sources_unchanged':True}}
 for identity in ['GF-MULTI-RESULT-OVERVIEW','GF-HISTORY-INDEPENDENT']]
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
