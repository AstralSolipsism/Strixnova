"""Resolve contradictory verdict/issue fields using the same frozen review inputs."""
from pathlib import Path
import argparse,json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import reconsider_review
parser=argparse.ArgumentParser();parser.add_argument('--previous-run',required=True);args=parser.parse_args()
previous=ROOT/'.artifacts/validation'/args.previous_run/'evidence/independent-review'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
feedback='''报告因“passed同时有未闭合issues”被原绑定器拒绝，原报告及所有输入已冻结保存。请依据同一原始标准和材料重新核对每个case，不预设通过或失败。
本任务审查的是“作者的实现评价是否有根据”，不是要求目标必须implemented。如果作者准确指出真实缺口并给出部分状态，评价本身可以通过；已准确披露的目标局限可列limitations，不能混入表示评价尚需修订的issues。但如果作者把代码已实现仅因宿主测试跳过判为缺实现，或其他职责/证据边界误判，必须按真实影响判needs_revision，不可一面在issues否定评价、一面passed。
特别是上一报告第一项issues明确批评作者混淆代码职责与符号链接测试跳过，却仍给passed，请对照实际合同、源码和作者状态说明作一致判断。其余项也按同一尺度核对。不要仅删issues让格式通过，不改变输入或替作者修复结论；保持全部原范围、引用规则与每case一次。'''
shutil.copyfile(__file__,evidence/'operator-source.py')
report=reconsider_review(previous,evidence/'independent-review',feedback,timeout=600)
summary={'previous_run':args.previous_run,'execution':report['execution'],
 'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in report['cases']],
 'assessment_changed':False,'authority_files_updated':False,'owner_accepted':False}
(evidence/'review-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if report['execution']['report_valid'] else 1)
