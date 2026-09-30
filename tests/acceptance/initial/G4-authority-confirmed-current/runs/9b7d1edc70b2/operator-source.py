"""Fix the one native reference over unchanged material; rebind exact readiness."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import reconsider_review
previous=ROOT/'.artifacts/validation/8d07e9fd21db/evidence'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
gate=json.loads((previous/'gate-binding.json').read_text(encoding='utf-8'))
original=json.loads((previous/'independent-review/review.json').read_text(encoding='utf-8'))
assert original['execution']['error']=='Invalid reference line range'
sources=json.loads((previous/'independent-review/sources.json').read_text(encoding='utf-8'))
receipt=json.loads((previous/'independent-review/execution/driver-receipt.json').read_text(encoding='utf-8'))
raw=receipt['last_result'].get('structured_output') or json.loads(receipt['last_result']['response'])
invalid=[]
for row in raw['cases']:
    for ref in row['references']:
        count=len(sources[ref['source_id']]['text'].splitlines(keepends=True))
        if not 1<=ref['start_line']<=ref['end_line']<=count:invalid.append({'case_id':row['case_id'],**ref,'actual_lines':count})
assert len(invalid)==1
feedback=('原报告的一个引用超出冻结文件行数，导致整份报告不能绑定。请核对下面的来源ID和真实行号，仍返回原两项完整报告。'
 'author-response是最新只读修正回复，只有18行；之前完整方案展示另有独立来源，不要混用来源名或行号。原材料、标准和报告都保留，不预设通过；只有原理由确不受证据支持时才如实更正判断。'
 '\n'+json.dumps(invalid,ensure_ascii=False))
(evidence/'reference-feedback.txt').write_text(feedback,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
review=reconsider_review(previous/'independent-review',evidence/'independent-review',feedback,timeout=420)
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
project=Path(initial['project']);built=initial['candidate']
call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',gate['work_item_id']],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
state=json.loads(call.stdout)['next']
assert state['work_item_version']==gate['work_item_version'] and state['current_action']['confirmation_challenge']['candidate_fingerprint']==gate['candidate_fingerprint']
assert all(hashlib.sha256((project/path).read_bytes()).hexdigest()==digest for path,digest in gate['authority_candidate_files'].items())
ready=review['execution']['report_valid'] and len(review['cases'])==2 and all(row['summary']['status']=='passed' and not row['issues'] for row in review['cases'])
gate.update(review_report=str(evidence/'independent-review/review.json'),review_report_sha256=hashlib.sha256((evidence/'independent-review/review.json').read_bytes()).hexdigest(),
            independent_semantic_ready=ready,authority_content_independently_ready=ready,fixed_input_dispatch_permitted=ready,
            supersedes_invalid_reference_gate=str(previous/'gate-binding.json'),owner_accepted=False)
(evidence/'gate-binding.json').write_text(json.dumps(gate,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'report_valid':review['execution']['report_valid'],'ready':ready,'work_item_version':gate['work_item_version'],'owner_accepted':False},ensure_ascii=False))
raise SystemExit(0 if ready else 1)
