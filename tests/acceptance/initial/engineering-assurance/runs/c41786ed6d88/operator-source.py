"""Recheck only out-of-range references over the original frozen assessment."""
from pathlib import Path
import json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import reconsider_review
previous=ROOT/'.artifacts/validation/5625d6bad9a3/evidence'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
sources=json.loads((previous/'independent-review/sources.json').read_text(encoding='utf-8'))
receipt=json.loads((previous/'independent-review/execution/driver-receipt.json').read_text(encoding='utf-8'))
raw=receipt['last_result'].get('structured_output') or json.loads(receipt['last_result']['response'])
invalid=[]
for row in raw['cases']:
    for ref in row['references']:
        count=len(sources[ref['source_id']]['text'].splitlines(keepends=True))
        if not 1<=ref['start_line']<=ref['end_line']<=count:
            invalid.append({'case_id':row['case_id'],**ref,'actual_line_count':count})
assert invalid
feedback=('原七项复核未通过引用绑定，以下引用超出冻结来源的实际行数。请只重读这些具体来源并纠正引用，仍返回七项完整报告。'
 '原标准、材料、作者评价和原报告均保留，不重跑作者或测试。七项作者状态均为 partially_satisfied，其缺口和限制不得升级为已满足。'
 '不预设通过；若原理由确有来源不支持，可如实修订判断并指出原因。\n'+json.dumps(invalid,ensure_ascii=False))
(evidence/'reference-feedback.txt').write_text(feedback,encoding='utf-8')
for name in ['assessment.json','assurance-sections.json','registration.json']:
    shutil.copyfile(previous/name,evidence/name)
shutil.copyfile(__file__,evidence/'operator-source.py')
review=reconsider_review(previous/'independent-review',evidence/'independent-review',feedback,timeout=480)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
         'original_author_assessment_unchanged':True,'new_author_calls':0,'owner_accepted':False}
(evidence/'assessment-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
