from pathlib import Path
import argparse,hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest
parser=argparse.ArgumentParser()
for name in ['initial-run','latest-run','work-item-id','prd-path']:parser.add_argument('--'+name,required=True)
options=parser.parse_args()
initial=(ROOT/'.artifacts/validation'/options.initial_run/'evidence').resolve()
latest=(ROOT/'.artifacts/validation'/options.latest_run/'evidence').resolve()
for path in [initial,latest]:
    assert path.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((path.parent/'result.json').read_text(encoding='utf-8'))
    assert result['status']=='passed' and result['process_settled']
assert json.loads((latest/'execution/driver-receipt.json').read_text(encoding='utf-8'))['mechanical_passed']
definition=json.loads((initial/'registration.json').read_text(encoding='utf-8'))
built=definition['candidate'];project=Path(definition['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
identifier=options.work_item_id
prd=(project/options.prd_path).resolve();assert prd.is_relative_to(project.resolve()) and prd.is_file()
argv=[built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier,'--record','direction','--record','project.direction_context','--max-output-bytes','1048576']
read=subprocess.run(argv,capture_output=True,text=True,encoding='utf-8',timeout=45,check=True)
state=json.loads(read.stdout)['next'];action=state['current_action'];challenge=action['confirmation_challenge']
assert action['action_type']=='confirm_direction' and action['actor']=='user'
assert state['reading']['complete'] and not state['record_pages']
dump(evidence/'actual-candidate.json',state);dump(evidence/'public-read-command.json',{'argv':argv,'exit_code':read.returncode})
assert subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()==definition['initial_commit']
assert all(hashlib.sha256((project/p).read_bytes()).hexdigest()==h for p,h in definition['protected_source'].items())
sources={'registration':{'path':str(initial/'registration.json'),'role':'original_input'},
 'correction-feedback':{'path':str(latest/'user-input.txt'),'role':'user_input'},
 'current-explanation':{'path':str(latest/'author-response.md'),'role':'author_response'},
 'current-tools':{'path':str(latest/'tool-steps.json'),'role':'author_artifact'},
 'actual-candidate':{'path':str(evidence/'actual-candidate.json'),'role':'author_artifact'},
 'current-prd':{'path':str(prd),'role':'author_artifact'}}
case={'case_id':'G4-DIRECTION-READY',
 'expected_behavior':'当前展示和公开记录的方向一致且能进入工程方案：成员撤回本人待审申请为一个可独立接受结果，周报为关联的独立待办。完整交代身份来自可信会话、归属、状态限制、幂等与审计、并发互斥、响应丢失查询、本地终端限制，以及共享权威须修订的范围和候选当前实际形成及待接受状态。授权只及下一步方案，不把方向确认当实施或结果接受。',
 'must_avoid':'候选内容与展示不符、缺失会改变决定的业务事实、冒充已写成权威，或在独立条件未满足时允许固定接受输入。本关口只检查当前投递条件，不抹去初轮未形成候选的记录。',
 'evidence_source_ids':['current-explanation','current-tools','actual-candidate','current-prd'],
 'verification_scope':'当前方向接受输入的投递条件；不代表完整G4/G2验收或真人接受。',
 'machine_checks':{'public_direction_waits_for_owner':True,'business_source_and_git_unchanged':True}}
dump(evidence/'gate-spec.json',{'sources':sources,'cases':[case]});shutil.copyfile(__file__,evidence/'operator-source.py')
review=run_review(evidence/'gate-spec.json',evidence/'independent-review',timeout=600)
ready=review['execution']['report_valid'] and len(review['cases'])==1 and review['cases'][0]['summary']['status']=='passed'
binding={'phase':'G4-direction','work_item_id':identifier,'work_item_version':state['work_item_version'],
 'candidate_kind':challenge['candidate_kind'],'candidate_fingerprint':challenge['candidate_fingerprint'],
 'review_report':str(evidence/'independent-review/review.json'),
 'review_report_sha256':hashlib.sha256((evidence/'independent-review/review.json').read_bytes()).hexdigest(),
 'author_candidate':built,'reviewer_skill_sha256':directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256'],
 'fixed_input_dispatch_permitted':ready,'actual_owner_accepted':False,'semantic_content_machine_proven':False}
dump(evidence/'gate-binding.json',binding);print(json.dumps(binding,ensure_ascii=False))
raise SystemExit(0 if ready else 1)
