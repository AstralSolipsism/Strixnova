"""Execute only first intake and independently review its actual ordering."""
from pathlib import Path
import argparse,json,os,shutil,sqlite3,subprocess,sys
import yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
p=argparse.ArgumentParser();p.add_argument('--registration',type=Path,required=True);args=p.parse_args()
registration=args.registration.resolve();assert registration.is_relative_to(ROOT/'.artifacts/validation')
info=json.loads(registration.read_text(encoding='utf-8'));project=Path(info['project']).resolve()
assert project.is_relative_to(ROOT/'.artifacts/validation')
built=candidate(Path(info['candidate_registration']));assert built==info['candidate']
assert not (project/'.strixnova/authority.sqlite3').exists()
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
prompt=info['fixed_input'];(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
shutil.copyfile(registration,evidence/'registration.json');shutil.copyfile(project/'AGENTS.md',evidence/'fixture-AGENTS.md')
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    database=project/'.strixnova/authority.sqlite3';identifiers=[]
    if database.is_file():
        with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as c:
            identifiers=[r[0] for r in c.execute('SELECT work_item_id FROM work_items ORDER BY work_item_id')]
    unchanged=all(sha(project/relative)==digest for relative,digest in info['protected_files'].items())
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    return {'reached':bool(identifiers) and unchanged and head==info['source_commit'],
            'work_item_ids':identifiers,'protected_files_unchanged':unchanged,'head_unchanged':head==info['source_commit'],
            'scope':'Only actual existence and preserved source; intake-before-clarification ordering requires native review.'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=info['model'],timeout=420,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
states={}
for identity in endpoint['work_item_ids']:
    result=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    states[identity]=json.loads(result.stdout)['next']
dump(evidence/'public-states.json',states)
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
item=next(row for row in catalog['cases'] if row['case_id']=='GF-CONCRETE-INCOMPLETE')
case={k:item[k] for k in ['case_id','expected_behavior','must_avoid']}
case.update(evidence_source_ids=['author-response','author-tools','raw-events','actual-endpoint','public-states'],
    verification_scope='本次既有业务工程、尚无当前请求事项的首次登记和实质澄清。Git版本来自已完成G1，但本副本没有复制历史数据库；明确此初态差异，原G4漏登记失败仍保留，本次不追认原失败或证明任意历史状态下可靠。',
    machine_checks={'actual_new_work_items_exist':True,'protected_source_and_git_unchanged':True})
sources={'fixed-input':{'path':str(evidence/'user-input.txt'),'role':'user_input'},
         'fixture':{'path':str(evidence/'registration.json'),'role':'original_input'},
         'fixture-instructions':{'path':str(evidence/'fixture-AGENTS.md'),'role':'original_input'},
         'author-response':{'path':str(evidence/'author-response.md'),'role':'author_response'},
         'author-tools':{'path':str(evidence/'tool-steps.json'),'role':'author_artifact'},
         'raw-events':{'path':str(evidence/'execution/events.jsonl'),'role':'author_artifact'},
         'actual-endpoint':{'path':str(evidence/'endpoint.json'),'role':'author_artifact'},
         'public-states':{'path':str(evidence/'public-states.json'),'role':'author_artifact'},
         'original-failure':{'path':str(ROOT/'.artifacts/validation/fca48acdf6d8/evidence/independent-review/review.json'),'role':'original_input'}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[case]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=420)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
         'original_failure_preserved':True,'initial_history_database_not_copied':True,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
