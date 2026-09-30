"""Ask the same native reviewer to repair invalid coordinates over unchanged evidence."""
from pathlib import Path
import argparse,json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import reconsider_review
p=argparse.ArgumentParser();p.add_argument('--previous-run',required=True);args=p.parse_args()
parent=ROOT/'.artifacts/validation'/args.previous_run/'evidence';previous=parent/'independent-review'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
sources=json.loads((previous/'sources.json').read_text(encoding='utf-8'))
receipt=json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'))
parsed=receipt['last_result'].get('structured_output') or json.loads((previous/'review-response.txt').read_text(encoding='utf-8'))
invalid=[]
for row in parsed['cases']:
    for ref in row['references']:
        lines=len(sources[ref['source_id']]['text'].splitlines(keepends=True))
        if not 1<=ref['start_line']<=ref['end_line']<=lines:invalid.append({'case_id':row['case_id'],**ref,'actual_line_count':lines})
assert invalid,'No coordinate errors found; do not repeat review needlessly'
feedback='原报告未通过引用坐标校验。以下是程序从原冻结来源计算的具体越界；请重新读这些实际编号来源并提交同样标准下的完整报告，不改输入、不预设通过，也不靠改写理由掩盖证据不足。原报告保留。\n'+json.dumps(invalid,ensure_ascii=False,indent=2)
shutil.copyfile(__file__,evidence/'operator-source.py');dump_path=evidence/'invalid-reference-ranges.json'
dump_path.write_text(json.dumps(invalid,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
if (parent/'assessment.json').is_file():shutil.copyfile(parent/'assessment.json',evidence/'assessment.json')
report=reconsider_review(previous,evidence/'independent-review',feedback,timeout=600)
summary={'previous_run':args.previous_run,'execution':report['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in report['cases']],
 'input_and_assessment_changed':False,'authority_files_updated':False,'owner_accepted':False}
(evidence/'review-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if report['execution']['report_valid'] else 1)
