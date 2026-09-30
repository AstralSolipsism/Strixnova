"""Observe native public recovery of the real receipt without executing again."""
from pathlib import Path
import hashlib,json,os,shutil,sqlite3,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
base=ROOT/'.artifacts/validation/d18b25e5739d'
info=json.loads((base/'work/fixture.json').read_text(encoding='utf-8'))
project=Path(info['project']);counter=Path(info['counter_path'])
built=candidate(ROOT/'.artifacts/candidates/initial-guidance/candidate.json');assert built==info['candidate']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
dump(evidence/'registration.json',{**info,'author_model':'gemini-3.8-flash-low','reviewer_model':'gemini-3.8-flash-low',
 'timeout_seconds':600,'max_neutral_continuations':1,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
for name in ['before-item.json','actual-interruption.json','original-output-hashes.json','setup-boundary.json']:
    shutil.copyfile(base/'evidence'/name,evidence/name)
(evidence/'user-input.txt').write_text(info['fixed_input'],encoding='utf-8')
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def current():
    with sqlite3.connect((project/'state/.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        version,status,raw=c.execute('SELECT version,status,data_json FROM work_items WHERE work_item_id=?',(info['work_item_id'],)).fetchone()
    return {'version':version,'status':status,'data':json.loads(raw)}
def observe():
    item=current();receipts=[r for r in item['data']['verifications'] if r['receipt_id']==info['receipt_id']]
    unchanged=all(sha(path)==digest for path,digest in info['source_files'].items())
    heads=all(subprocess.run(['git','rev-parse','HEAD'],cwd=path,check=True,capture_output=True,text=True).stdout.strip()==commit for path,commit in info['integration_heads'].items())
    same_counter=counter.read_text()==info['counter_expected']
    recovered=item['data']['pending_effect'] is None and len(receipts)==1
    assessed=recovered and receipts[0].get('code_change_assessment') is not None
    return {'reached':recovered and assessed and unchanged and heads and same_counter,
      'same_original_receipt':recovered,'assessment_present':bool(assessed),'counter_unchanged':same_counter,
      'source_files_unchanged':unchanged,'integration_heads_unchanged':heads,'version':item['version'],
      'status':item['status'],'receipt':receipts[0] if receipts else None}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=info['fixed_input'],
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',timeout=600,
 max_continuations=1,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps'])
endpoint=observe();dump(evidence/'endpoint.json',endpoint);dump(evidence/'after-item.json',current())
print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],'counter':counter.read_text()},ensure_ascii=False),flush=True)
if not receipt['mechanical_passed'] or not endpoint['reached']:raise SystemExit(1)
sources={name:{'path':str(evidence/name),'role':role} for name,role in [
 ('registration.json','original_input'),('setup-boundary.json','original_input'),('before-item.json','original_input'),
 ('actual-interruption.json','original_input'),('user-input.txt','user_input'),('author-response.md','author_response'),
 ('tool-steps.json','author_artifact'),('endpoint.json','author_artifact'),('after-item.json','author_artifact')]}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-GUIDANCE-VERIFICATION-RESUME')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':['author-response.md','tool-steps.json','endpoint.json','after-item.json'],
 'verification_scope':'合成的已确认起始前提之后，一次真实命令及回写中断的原生公开恢复；不证明起始候选语义接受或完整业务交付。',
 'machine_checks':{k:endpoint[k] for k in ['same_original_receipt','assessment_present','counter_unchanged','source_files_unchanged','integration_heads_unchanged']}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'counter':counter.read_text(),'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
