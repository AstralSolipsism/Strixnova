"""Review the actual public authority decision point and updated draft ledgers."""
from pathlib import Path
import hashlib,json,os,shutil,sqlite3,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.review_antigravity_evidence import run_review
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
author=ROOT/'.artifacts/validation/260419b79789';result=json.loads((author/'result.json').read_text(encoding='utf-8'))
assert result['status']=='passed' and result['process_settled']
receipt=json.loads((author/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'));assert receipt['mechanical_passed']
project=Path(initial['project']);built=candidate(Path(initial['candidate_registration']));evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
identifier='WI-20260929-DEC61550'
def current():
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=current();assert before['work_item_version']==22 and before['current_action']['action_type']=='confirm_project_authority_candidates'
assert len(before['current_action']['confirmation_challenges'])==4
call=subprocess.run([built['entrypoint'],'authority','--project-dir',str(project),'--work-item-id',identifier,'--version',str(before['work_item_version'])],capture_output=True,text=True,encoding='utf-8',check=True,timeout=60)
bundle=json.loads(call.stdout);assert bundle['ok'] and bundle['work_item_version']==before['work_item_version']
assert current()==before
submitted=json.loads((project/'.agent-inputs/authority-review-payload.json').read_text(encoding='utf-8-sig'))
database=project/'.strixnova/authority.sqlite3'
with sqlite3.connect(database.as_uri()+'?mode=ro',uri=True) as c:
    version,body=c.execute('SELECT version,data_json FROM work_items WHERE work_item_id=?',(identifier,)).fetchone()
data=json.loads(body);assert version==before['work_item_version']
reviews=data['project_authority_reviews'];stored=reviews[-1]
assert stored['semantic_review']==submitted['semantic_review']
assert submitted['semantic_review']['reviewed_refs']==bundle['candidate_bundle']['reviewed_refs']
assert len(submitted['semantic_review']['checks'])==8
dump(evidence/'public-state.json',before);dump(evidence/'public-bundle.json',bundle)
dump(evidence/'stored-author-review.json',stored)
gate_path=ROOT/'.artifacts/validation/9b7d1edc70b2/evidence/gate-binding.json';prior=json.loads(gate_path.read_text(encoding='utf-8'))
assert prior['authority_content_independently_ready']
candidate_files={p.relative_to(project).as_posix():sha(p) for p in (project/'docs').rglob('*') if p.is_file()}
delta=[p for p,digest in prior['authority_candidate_files'].items() if candidate_files.get(p)!=digest]
dump(evidence/'changed-candidate-paths.json',{'changed_since_independent_content_review':delta,'scope':'Exact bytes only, not semantic approval.'})
sources={
 'request':{'path':str(ROOT/'.artifacts/validation/6bbae8a5d2e5/evidence/registration.json'),'role':'original_input'},
 'prior-readiness':{'path':str(gate_path),'role':'original_input'},
 'prior-native-review':{'path':prior['review_report'],'role':'original_input'},
 'public-state':{'path':str(evidence/'public-state.json'),'role':'author_artifact'},
 'public-bundle':{'path':str(evidence/'public-bundle.json'),'role':'author_artifact'},
 'actual-eight-view-review':{'path':str(evidence/'stored-author-review.json'),'role':'author_artifact'},
 'changes':{'path':str(evidence/'changed-candidate-paths.json'),'role':'author_artifact'},
 'author-response':{'path':str(author/'evidence/author-response.md'),'role':'author_response'},
 'author-tools':{'path':str(author/'evidence/tool-steps.json'),'role':'author_artifact'}}
for relative in candidate_files:sources['candidate/'+relative]={'path':str(project/relative),'role':'author_artifact'}
case={'case_id':'G4-CURRENT-AUTHORITY-DECISION-READY',
 'expected_behavior':'依据实际公开候选包、数据库中已记录的同一八视角复核及作者展示，判断是否可投递已登记的四类整包接受输入。四类候选须完整、语义及引用一致，周报仍单独待方向决定，实际范围不越过撤回；实现对齐保持真实编码前草稿，新增功能未实现不可伪装成已实现。重点检查自上次独立内容复核以来改变的六份工程记录，以及八视角复核的发现和限制是否如实、不掩盖阻断。已明确未变的四类正文可结合前次独立结论复用，不必重复无关调查。',
 'must_avoid':'用程序接收复核代替语义充分性；把真实非阻断限制升级成已实现或已接受；把尚未确认的周报当作已授权实施；忽略当前工程记录与实际源码事实矛盾；伪造外部认证、真人接受或旧失败首次通过。',
 'evidence_source_ids':[key for key,row in sources.items() if row['role'] in {'author_artifact','author_response'}],
 'verification_scope':'仅当前四类候选接受的就绪门槛，不代表业务实现、实际结果接受或正式交付；原报告、枚举错误和后续修正均保留。',
 'machine_checks':{'public_confirm_action_and_four_challenges':True,'actual_stored_review_matches_submitted_payload':True,'review_refs_match_current_bundle':True,'eight_perspectives_present':True}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[case]});shutil.copyfile(__file__,evidence/'operator-source.py')
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
assert current()==before and all(sha(project/path)==digest for path,digest in candidate_files.items())
ready=review['execution']['report_valid'] and len(review['cases'])==1 and review['cases'][0]['summary']['status']=='passed'
binding={'phase':'G4-authority-decision','work_item_id':identifier,'work_item_version':before['work_item_version'],
 'confirmation_challenges':before['current_action']['confirmation_challenges'],'candidate_bundle_sha256':bundle['candidate_bundle']['content_sha256'],
 'candidate_files':candidate_files,'review_report':str(evidence/'independent-review/review.json'),'review_report_sha256':sha(evidence/'independent-review/review.json'),
 'fixed_input_dispatch_permitted':ready,'owner_accepted':False}
dump(evidence/'gate-binding.json',binding);print(json.dumps({'ready':ready,'version':before['work_item_version'],'review_execution':review['execution'],'owner_accepted':False},ensure_ascii=False))
raise SystemExit(0 if ready else 1)
