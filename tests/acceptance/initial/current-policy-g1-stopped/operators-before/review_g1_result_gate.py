from pathlib import Path
import argparse
import hashlib
import json
import os
import subprocess
import sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import run_review
parser=argparse.ArgumentParser()
parser.add_argument('--initial-run',type=str,required=True)
parser.add_argument('--plan-run',type=str,required=True)
parser.add_argument('--last-run',type=str,required=True)
options=parser.parse_args()
for key,value in vars(options).items():
    if key.endswith('_run'):
        directory=(ROOT/'.artifacts/validation'/value).resolve()
        assert directory.is_relative_to(ROOT/'.artifacts/validation')
        settled=json.loads((directory/'result.json').read_text(encoding='utf-8'))
        assert settled['status']=='passed' and settled['process_settled']
initial=ROOT/'.artifacts/validation'/options.initial_run/'evidence'
latest=ROOT/'.artifacts/validation'/options.last_run/'evidence'
assert json.loads((latest.parent/'result.json').read_text(encoding='utf-8'))['status']=='passed'
definition=json.loads((initial/'registration.json').read_text(encoding='utf-8'))
info=json.loads(Path(definition['fixture']).read_text(encoding='utf-8'))
project=Path(info['project']);built=definition['candidate']
identifier=json.loads((latest/'endpoint.json').read_text(encoding='utf-8'))['next']['work_item_id']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
args=[built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier]
args += ['--record','actual_result']
result=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',check=True,timeout=60)
(evidence/'actual-state.json').write_text(result.stdout,encoding='utf-8')
history_args=[built['entrypoint'],'history','--project-dir',str(project),'--work-item-id',identifier]
for record in ['decisions','verifications','delivery']:history_args += ['--record',record]
history=subprocess.run(history_args,capture_output=True,text=True,encoding='utf-8',check=True,timeout=60)
(evidence/'recorded-history.json').write_text(history.stdout,encoding='utf-8')
state=json.loads(result.stdout)['next'];action=state['current_action'];challenge=action['confirmation_challenge']
assert action['action_type']=='confirm_actual_result'
head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
assert head==info['initial_commit']
sources={
 'execution-boundary':{'path':str(project/'AGENTS.md'),'role':'original_input'},
 'current-policy':{'path':str(project/'docs/engineering/policy.yaml'),'role':'original_input'},
 'request':{'path':str(initial/'user-input.txt'),'role':'user_input'},
 'plan-acceptance':{'path':str(latest/'user-input.txt'),'role':'user_input'},
 'fixture':{'path':definition['fixture'],'role':'original_input'},
 'actual-state':{'path':str(evidence/'actual-state.json'),'role':'author_artifact'},
 'recorded-history':{'path':str(evidence/'recorded-history.json'),'role':'author_artifact'},
 'accepted-plan':{'path':str(ROOT/'.artifacts/validation'/options.plan_run/'evidence/endpoint.json'),'role':'author_artifact'},
 'explanation':{'path':str(latest/'author-response.md'),'role':'author_response'},
 'tools':{'path':str(latest/'tool-steps.json'),'role':'author_artifact'},
}
for name in ['src.py','tests/test_duration.py','docs/engineering/alignment.yaml','docs/engineering/source-ownership.yaml','docs/engineering/target-responsibilities.yaml','docs/engineering/baseline.yaml']:
    sources[name]={'path':str(project/name),'role':'author_artifact'}
for path in sorted((project/'.strixnova/artifacts'/identifier).glob('*')):
    if path.is_file() and path.suffix in {'.json','.log','.txt'}:
        sources['recorded-output:'+path.name]={'path':str(path),'role':'author_artifact'}
spec={'sources':sources,'cases':[{
 'case_id':'G1-RESULT-READY',
 'expected_behavior':'实际结果对照已确认方案、当前代码、测试、原始回执和对齐产物如实说明效果、核验、偏差、风险与限制。非法区间拒绝、合法返回和函数签名保持的声明须有范围相称依据。命令整体通过不能替代原生用例/逐项目标核对；用例标识不匹配或缺口必须真实说明，不可同时把未证实部分宣称全部通过。已经明确展示且有依据的限制可以交由固定负责人角色决定接受，不能隐藏或把程序结构检查当语义证明。当前仍等待结果接受，尚无本地提交。',
 'must_avoid':'用自述、退出0或伪造回执代替实际证据；隐瞒未匹配、未核验或未完成；在输入接受前提交；把本Gate当完整G1或真人接受。',
 'evidence_source_ids':[name for name,value in sources.items() if value['role'] in {'author_response','author_artifact'}],
 'verification_scope':'当前实际结果是否满足已批准固定接受输入的投递条件；完整场景逐项行为另行验收。',
 'machine_checks':{'result_waits_for_owner':True,'integration_head_not_committed':True,'source_outputs_and_public_records_captured':True},
 }]}
spec_path=evidence/'gate-spec.json';spec_path.write_text(json.dumps(spec,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
review=run_review(spec_path,evidence/'independent-review',timeout=600)
ready=review['execution']['report_valid'] and len(review['cases'])==1 and review['cases'][0]['summary']['status']=='passed'
path=evidence/'independent-review/review.json'
binding={'phase':'actual_result','work_item_id':state['work_item_id'],'work_item_version':state['work_item_version'],
 'candidate_kind':challenge['candidate_kind'],'candidate_fingerprint':challenge['candidate_fingerprint'],
 'review_report':str(path),'review_report_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
 'fixed_input_dispatch_permitted':ready,'actual_owner_accepted':False,'semantic_content_machine_proven':False}
(evidence/'gate-binding.json').write_text(json.dumps(binding,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(binding,ensure_ascii=False));raise SystemExit(0 if ready else 1)
