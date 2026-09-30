from pathlib import Path
import json
import os
import shutil
import sys

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT))
from scripts.review_antigravity_evidence import reconsider_review

previous = ROOT / '.artifacts/validation/8211ff7aec98/evidence/independent-review'
evidence = Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
sources = json.loads((previous/'sources.json').read_text(encoding='utf-8'))
receipt = json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'))
parsed = receipt['last_result'].get('structured_output')
if parsed is None:
    parsed = json.loads((previous/'review-response.txt').read_text(encoding='utf-8'))
invalid = []
for row in parsed['cases']:
    for ref in row['references']:
        count = len(sources[ref['source_id']]['text'].splitlines(keepends=True))
        if not 1 <= ref['start_line'] <= ref['end_line'] <= count:
            invalid.append({'case_id': row['case_id'], **ref, 'actual_line_count': count})
assert invalid, 'No line-range error found; do not request an unnecessary retry'
feedback = ('上一份报告没有通过引用绑定检查，原因是下列引用越过冻结来源的实际行数。'
            '请重新读取对应编号来源，修正引用并提交原七项完整报告。'
            '不要改动原材料、标准或原报告，也不要为了修复引用而预设通过；'
            '若原理由缺乏支持，应据实修改判断。此次只有引用有效性反馈，不是接受指令。\n'
            + json.dumps(invalid, ensure_ascii=False, indent=2))
shutil.copyfile(__file__, evidence/'operator-source.py')
(evidence/'invalid-references.json').write_text(json.dumps(invalid, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
report = reconsider_review(previous, evidence/'independent-review', feedback, timeout=600)
summary = {'previous_run': '8211ff7aec98', 'execution': report['execution'],
           'cases': [{'case_id': row['case_id'], 'verdict': row['verdict']} for row in report['cases']],
           'catalog_updated': False, 'owner_accepted': False}
(evidence/'reassessment-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(0 if report['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in report['cases']) else 1)
