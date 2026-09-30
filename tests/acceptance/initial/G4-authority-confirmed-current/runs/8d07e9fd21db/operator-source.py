"""Review the actual plan content and observed execution limits before acceptance."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump
from scripts.review_antigravity_evidence import run_review
parser=argparse.ArgumentParser()
for name in ['initial-run','author-run','direction-gate-run','work-item-id','assessment-path']:
    parser.add_argument('--'+name,required=True)
parser.add_argument('--prior-author-run')
parser.add_argument('--structural-check-run')
parser.add_argument('--binding-repair-run')
parser.add_argument('--previous-passed-review-run')
args=parser.parse_args()
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
first=(ROOT/'.artifacts/validation'/args.initial_run/'evidence').resolve()
author=(ROOT/'.artifacts/validation'/args.author_run/'evidence').resolve()
gate=(ROOT/'.artifacts/validation'/args.direction_gate_run/'evidence/gate-binding.json').resolve()
assert all(p.is_relative_to(ROOT/'.artifacts/validation') for p in [first,author,gate])
registration=json.loads((first/'registration.json').read_text(encoding='utf-8'))
completed=json.loads((author.parent/'result.json').read_text(encoding='utf-8'))
assert completed['status']=='passed' and completed['process_settled']
built=candidate(Path(registration['candidate_registration']));assert built==registration['candidate']
project=Path(registration['project']);identifier=args.work_item_id
assessment=(project/args.assessment_path).resolve()
assert assessment.is_relative_to(project) and assessment.is_file()
call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier,
 '--record','engineering.plan','--record','repository_deliveries','--max-output-bytes','1048576'],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
state=json.loads(call.stdout)['next'];assert state['reading']['complete'] and not state['record_pages']
assert state['current_action']['action_type']=='confirm_engineering_plan'
dump(evidence/'complete-plan.json',state)
submitted=json.loads(assessment.read_text(encoding='utf-8-sig'))
assessment_ref=state['records']['engineering.plan']['assessment_ref']
assert submitted['assessment_id']==assessment_ref['assessment_id']
assert submitted['assessment_revision']==assessment_ref['assessment_revision'],'Submitted assessment path does not match actual public plan revision'
structural=None
if args.structural_check_run:
    check_root=(ROOT/'.artifacts/validation'/args.structural_check_run).resolve()
    assert check_root.is_relative_to(ROOT/'.artifacts/validation')
    check_result=json.loads((check_root/'result.json').read_text(encoding='utf-8'))
    assert check_result['status']=='passed' and check_result['process_settled']
    structural=json.loads((check_root/'evidence/identity-comparison.json').read_text(encoding='utf-8'))
    assert structural['work_item_version']==state['work_item_version']
    assert structural['candidate_fingerprint']==state['current_action']['confirmation_challenge']['candidate_fingerprint']
    assert len(structural['results'])==4
    assert not structural.get('authority_chain_issues')
    for row in structural['results']:
        assert not row.get('candidate_read_errors') and not row.get('undeclared_additions') and not row.get('undeclared_removals')
        assert row['actual_status']=='ready_for_confirmation'
        assert row['planned_revision_id'] is None or row['planned_revision_id']==row['actual_revision_id']
        assert hashlib.sha256((project/row['path']).read_bytes()).hexdigest()==row['sha256']
history=subprocess.run([built['entrypoint'],'history','--project-dir',str(project),'--work-item-id',identifier,'--record','decisions'],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
dump(evidence/'complete-decisions.json',json.loads(history.stdout))
receipt=json.loads((author/'execution/driver-receipt.json').read_text(encoding='utf-8'))
steps=json.loads((author/'tool-steps.json').read_text(encoding='utf-8'))
prior_author=None
prior_receipt=None
if args.prior_author_run:
    prior_author=(ROOT/'.artifacts/validation'/args.prior_author_run/'evidence').resolve()
    assert prior_author.is_relative_to(ROOT/'.artifacts/validation')
    prior_result=json.loads((prior_author.parent/'result.json').read_text(encoding='utf-8'))
    assert prior_result['process_settled']
    prior_receipt=json.loads((prior_author/'execution/driver-receipt.json').read_text(encoding='utf-8'))
    assert not prior_receipt['verdict']['unsettled_steps']
    steps=json.loads((prior_author/'tool-steps.json').read_text(encoding='utf-8'))+steps
bare=[]
for step in steps:
    command=(step.get('tool_info',{}).get('parameters') or {}).get('CommandLine','')
    if re.search(r'(?m)^\s*(?:&\s+)?python(?:3)?(?:\.exe)?\s',command):
        bare.append({'step_index':step['step_index'],'command':command})
dump(evidence/'execution-boundaries.json',{'original_mechanical_passed':receipt['mechanical_passed'],
 'latest_author_run':args.author_run,'prior_author_run':args.prior_author_run,
 'prior_author_outcome':prior_receipt['outcome'] if prior_receipt else None,
 'prior_author_mechanical_passed':prior_receipt['mechanical_passed'] if prior_receipt else None,
 'original_failed_steps':receipt['verdict']['failed_steps'],'unsettled_steps':receipt['verdict']['unsettled_steps'],
 'bare_python_commands_observed':bare,'no_system_python_test_claim':True,
 'scope':'Observed commands and transport facts only. A candidate reaching confirmation is not semantic readiness.'})
sources={'fixed-business-inputs':{'path':str(first/'registration.json'),'role':'original_input'},
 'current-agents':{'path':str(project/'AGENTS.md'),'role':'original_input'},
 'prior-direction-gate':{'path':str(gate),'role':'original_input'},
 'prior-plan-rejection':{'path':str(ROOT/'.artifacts/validation/f36774893e76/evidence/independent-review/review.json'),'role':'original_input'},
 'plan':{'path':str(evidence/'complete-plan.json'),'role':'author_artifact'},
 'decisions':{'path':str(evidence/'complete-decisions.json'),'role':'author_artifact'},
 'author-response':{'path':str(author/'author-response.md'),'role':'author_response'},
 'author-tools':{'path':str(author/'tool-steps.json'),'role':'author_artifact'},
 'execution-boundaries':{'path':str(evidence/'execution-boundaries.json'),'role':'author_artifact'},
 'submitted-assessment':{'path':str(assessment),'role':'author_artifact'}}
if prior_author:
    for name in ['user-input.txt','tool-steps.json','endpoint.json','author-response.md']:
        sources['prior-current-author/'+name]={'path':str(prior_author/name),'role':'author_artifact'}
if structural:
    sources['current-structural-comparison']={'path':str(check_root/'evidence/identity-comparison.json'),'role':'author_artifact'}
if args.binding_repair_run:
    repair=(ROOT/'.artifacts/validation'/args.binding_repair_run/'evidence').resolve()
    assert repair.is_relative_to(ROOT/'.artifacts/validation')
    endpoint=json.loads((repair/'endpoint.json').read_text(encoding='utf-8'))
    assert endpoint['reached'] and endpoint['exact_expected_bytes'] and endpoint['public_states_unchanged']
    for name in ['registration.json','before.yaml','after.yaml','endpoint.json','tool-steps.json','author-response.md']:
        sources['exact-binding-repair/'+name]={'path':str(repair/name),'role':'author_artifact'}
if args.previous_passed_review_run:
    previous=(ROOT/'.artifacts/validation'/args.previous_passed_review_run/'evidence').resolve()
    assert previous.is_relative_to(ROOT/'.artifacts/validation')
    for name in ['complete-plan.json','independent-review/review.json']:
        sources['previous-passed-plan/'+name]={'path':str(previous/name),'role':'original_input'}
    previous_plan=json.loads((previous/'complete-plan.json').read_text(encoding='utf-8'))['records']['engineering.plan']
    current_plan=state['records']['engineering.plan']
    delta={'changed_top_level_fields':[key for key in sorted(set(previous_plan)|set(current_plan)) if previous_plan.get(key)!=current_plan.get(key)],
           'scope':'Exact JSON value differences only. Prior semantic conclusions are original evidence, not automatic approval of changed content.'}
    dump(evidence/'plan-delta.json',delta)
    sources['plan-delta']={'path':str(evidence/'plan-delta.json'),'role':'author_artifact'}
for p in (project/'docs').rglob('*'):
    if p.is_file() and p.suffix in {'.yaml','.md'}:sources['current-project/'+p.relative_to(project).as_posix()]={'path':str(p),'role':'author_artifact' if structural else 'original_input'}
case={'case_id':'G4-G2-ENGINEERING-PLAN-READY',
 'expected_behavior':'完整方案应忠实承接已确认成员撤回方向及原固定业务事实：可信会话身份与归属、待审状态限制、幂等/审计、并发互斥、丢失响应查询、本地终端交互；共享四类权威和目标架构需按原请求真正修订，计划覆盖必要实现对齐与最后验证，周报单独交付。清楚交代实现/验证路径、关键取舍和未验证边界。',
 'must_avoid':'通过新增未纳入既有范围的源码文件来绕过已明确要求的权威与实现对齐工作；把程序接收JSON当作语义正确，遗漏关键事实或把模拟身份/内存状态夸称完整安全与恢复。不能把多个失败后提交说成一次性通过；裸Python调用违反已给定执行约束也必须保留，不把其结果当合法测试证据。',
 'evidence_source_ids':['plan','decisions','author-response','author-tools','execution-boundaries','submitted-assessment'],
 'verification_scope':'当前实际方案的独立内容审阅和投递条件检查；本次不修复候选、不追认初轮工具错误或违反环境约束，也不代表真人接受。',
 'machine_checks':{'complete_public_plan_captured':True,'confirmation_still_pending':True}}
cases=[case]
if prior_author:
    case['evidence_source_ids'] += [identity for identity in sources if identity.startswith('prior-current-author/')]
candidate_files={}
if structural:
    candidate_files={p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (project/'docs').rglob('*') if p.is_file()}
    cases.append({'case_id':'G4-CURRENT-AUTHORITY-CONTENT-READY',
      'expected_behavior':'逐类审阅当前实际产品定义、领域模型、目标架构和工程政策完整候选，核对原固定业务事实、共享跨单元关系、术语与引用一致、DDD采用依据、当前撤回范围与独立周报边界。实现对齐保留真实草稿和待实施状态。候选材料已存在，不能只凭作者自述或机械结构通过认定语义就绪。',
      'must_avoid':'把候选内容就绪当成已有负责人接受、四类公开展示或八视角复核已经完成；忽略当前文件与计划的实质矛盾；把待实施说成已实现；丢弃之前失败。',
      'evidence_source_ids':['plan','author-response','current-structural-comparison',*[identity for identity in sources if identity.startswith('current-project/')]],
      'verification_scope':'仅当前实际候选内容的独立就绪检查。之后仍须完成公开展示和程序要求的复核，核对文件字节与实际确认挑战后，才允许转交已登记的测试接受输入。',
      'machine_checks':{'full_current_candidate_readers_passed':True,'declared_identity_differences_match':True}})
dump(evidence/'gate-spec.json',{'sources':sources,'cases':cases});shutil.copyfile(__file__,evidence/'operator-source.py')
review=run_review(evidence/'gate-spec.json',evidence/'independent-review',timeout=900)
semantic_ready=review['execution']['report_valid'] and len(review['cases'])==len(cases) and all(row['summary']['status']=='passed' and not row['issues'] for row in review['cases'])
if candidate_files:assert all(hashlib.sha256((project/relative).read_bytes()).hexdigest()==digest for relative,digest in candidate_files.items())
ready=semantic_ready and receipt['mechanical_passed'] and not bare
challenge=state['current_action']['confirmation_challenge']
binding={'phase':'G4-G2-plan','work_item_id':identifier,'work_item_version':state['work_item_version'],
 'candidate_kind':challenge['candidate_kind'],'candidate_fingerprint':challenge['candidate_fingerprint'],
 'review_report':str(evidence/'independent-review/review.json'),
 'review_report_sha256':hashlib.sha256((evidence/'independent-review/review.json').read_bytes()).hexdigest(),
 'independent_semantic_ready':semantic_ready,'original_author_mechanically_settled':receipt['mechanical_passed'],
 'bare_python_call_count':len(bare),'fixed_input_dispatch_permitted':ready,'owner_accepted':False}
if structural:
    binding.update(authority_content_independently_ready=semantic_ready,authority_candidate_files=candidate_files,
                   authority_acceptance_dispatched=False,authority_public_presentation_and_review_still_required=True)
dump(evidence/'gate-binding.json',binding);print(json.dumps(binding,ensure_ascii=False))
raise SystemExit(0 if ready else 1)
