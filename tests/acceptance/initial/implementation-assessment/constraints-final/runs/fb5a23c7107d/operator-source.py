"""Clarify assessment validity while preserving the author's partial result."""
from pathlib import Path
import json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import reconsider_review

previous=ROOT/'.artifacts/validation/568a174e0aa0/evidence'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
result=json.loads((previous.parent/'result.json').read_text(encoding='utf-8'))
assert result['process_settled'] and result['status']=='failed'
report=json.loads((previous/'independent-review/review.json').read_text(encoding='utf-8'))
assert report['execution']['report_valid']
assert [row['case_id'] for row in report['cases'] if row['summary']['status']!='passed']==['TARGET-CONSTRAINT-3FA770501B6147B4']
assessment=json.loads((previous/'assessment.json').read_text(encoding='utf-8'))
row=next(row for row in assessment['assessments'] if row['target_id']=='CONSTRAINT-3FA770501B6147B4')
assert row['status']=='partially_implemented' and row['missing'] and row['resolution_plan']
feedback=('请核对原评审对象是否被混淆，原冻结材料和判据不变，不预设通过。原 expected_behavior 要求评价的状态、缺口和局限与证据一致，并未要求每个目标必须 implemented。'
 '你对 TARGET-CONSTRAINT-3FA770501B6147B4 的理由明确说作者实事求是地保留 partially_implemented、两个 skipped 和补验要求；但又仅因这些真实缺口存在，把这份评价本身判为 needs_revision。'
 '请区分“评价候选是否准确”与“该约束是否已经完整满足”。作者原 partial、missing、resolution_plan 和 skipped 记录均保持，不修改作者结论、不运行测试，也不把未验证说成通过。'
 '若评价本身仍有不准确、过度或不足之处，请指出具体字段和来源并保持 needs_revision；若其准确，复核通过只表示可以登记该部分状态，绝不表示该约束完整通过。'
 '只针对这一处判据理解进行复核；同一冻结材料下其他八项已有结论可沿用，不必重读所有文件。仍返回原九项完整报告并保留全部原始报告。')
(evidence/'reviewer-feedback.txt').write_text(feedback,encoding='utf-8')
for name in ['assessment.json','registration.json']:
    shutil.copyfile(previous/name,evidence/name)
shutil.copyfile(__file__,evidence/'operator-source.py')
review=reconsider_review(previous/'independent-review',evidence/'independent-review',feedback,timeout=480)
summary={'previous_run':'568a174e0aa0','execution':review['execution'],
         'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
         'author_partial_result_unchanged':True,'owner_accepted':False}
(evidence/'assessment-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
