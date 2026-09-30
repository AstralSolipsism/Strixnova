from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import run_review

initial=ROOT/'.artifacts/validation/8d987875922b/evidence'
latest=ROOT/'.artifacts/validation/10bdc29a6a23/evidence'
run_result=json.loads((latest.parent/'result.json').read_text(encoding='utf-8'))
assert run_result['status']=='passed' and run_result['process_settled']
definition=json.loads((initial/'registration.json').read_text(encoding='utf-8'))
info=json.loads(Path(definition['fixture']).read_text(encoding='utf-8'))
state=json.loads((latest/'endpoint.json').read_text(encoding='utf-8'))['next']
project=Path(info['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
action=state['current_action'];challenge=action['confirmation_challenge']
assert action['action_type']=='confirm_direction' and action['actor']=='user'
head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
assert head==info['initial_commit']
original=subprocess.run(['git','show',head+':src.py'],cwd=project,check=True,capture_output=True).stdout
assert (project/'src.py').read_bytes()==original
sources={
 'request':{'path':str(initial/'user-input.txt'),'role':'user_input'},
 'question':{'path':str(latest/'user-input.txt'),'role':'user_input'},
 'fixture':{'path':definition['fixture'],'role':'original_input'},
 'product':{'path':str(project/'docs/product/definition.yaml'),'role':'original_input'},
 'source':{'path':str(project/'src.py'),'role':'original_input'},
 'initial-explanation':{'path':str(initial/'author-response.md'),'role':'author_response'},
 'current-explanation':{'path':str(latest/'author-response.md'),'role':'author_response'},
 'actual-candidate':{'path':str(latest/'endpoint.json'),'role':'author_artifact'},
 'initial-tools':{'path':str(initial/'tool-steps.json'),'role':'author_artifact'},
 'current-tools':{'path':str(latest/'tool-steps.json'),'role':'author_artifact'},
}
spec={'sources':sources,'cases':[{
 'case_id':'G1-DIRECTION-READY',
 'expected_behavior':'当前已展示的完整方向与公开候选一致，能在不发明关键业务决定的前提下进入制定方案：非法顺序拒绝、合法返回与函数签名保持，范围和授权边界清楚；用户可理解修改前后及其效果。说明按这个小修复的真实复杂度组织，不强迫编造风险或固定标题。当前仍等待负责人后续明确接受，代码与Git尚未实施。',
 'must_avoid':'把结构正确或候选存在当成语义成熟；把固定角色输入预当授权；省略会改变决定的缺口。本关口只评当前投递条件，不用改好的重述替代完整场景对初轮主动解释的评价。',
 'evidence_source_ids':['initial-explanation','current-explanation','actual-candidate','initial-tools','current-tools'],
 'verification_scope':'仅决定是否满足已批准固定方向接受输入的投递条件；不是G1完整通过或真人理解/接受。',
 'machine_checks':{'direction_candidate_waits_for_owner':True,'same_candidate_and_version_after_question':True,'source_and_git_unchanged':True},
 }]}
spec_path=evidence/'gate-spec.json';spec_path.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
review=run_review(spec_path,evidence/'independent-review',timeout=600)
ready=review['execution']['report_valid'] and len(review['cases'])==1 and review['cases'][0]['summary']['status']=='passed'
binding={'phase':'direction','work_item_id':state['work_item_id'],'work_item_version':state['work_item_version'],
         'candidate_kind':challenge['candidate_kind'],'candidate_fingerprint':challenge['candidate_fingerprint'],
         'review_report':str(evidence/'independent-review/review.json'),
         'review_report_sha256':hashlib.sha256((evidence/'independent-review/review.json').read_bytes()).hexdigest(),
         'fixed_input_dispatch_permitted':ready,'actual_owner_accepted':False,'semantic_content_machine_proven':False}
(evidence/'gate-binding.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(binding,ensure_ascii=False))
raise SystemExit(0 if ready else 1)
