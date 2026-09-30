"""A fixed non-accepting test response after an independent failed gate."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json')
origin=ROOT/'.artifacts/validation/760d2aafadb5/evidence'
gate=json.loads((origin/'gate-binding.json').read_text(encoding='utf-8'))
assert gate['fixed_input_dispatch_permitted'] is False
assert sha(Path(gate['review_report']))==gate['review_report_sha256']
review=json.loads(Path(gate['review_report']).read_text(encoding='utf-8'))
assert review['execution']['report_valid'] and review['cases'][0]['verdict']=='needs_revision'
initial=json.loads((ROOT/'.artifacts/validation/b3ed58aca29c/evidence/registration.json').read_text(encoding='utf-8'))
project=Path(initial['project']);identifier=gate['work_item_id'];evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
def public():
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identifier],capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    return json.loads(call.stdout)['next']
before=public();assert before['work_item_version']==gate['work_item_version']
assert before['current_action']['confirmation_challenge']['candidate_fingerprint']==gate['candidate_fingerprint']
fixed_reply='当前方案没有满足既定要求，我不接受这份方案，请按原要求修订。既定方向与业务事实不变：必须真实规划四类权威、跨单元目标架构和完整实现对齐，不能靠新增隔离源码绕过；补齐身份与归属、状态、幂等审计、并发冲突和响应丢失后查询的实现及验证处置。所有Python调用必须使用本工程AGENTS.md给定的完整解释器路径。仅继续修订尚未接受的工程方案，暂不实施业务代码、不接受权威、不提交Git，并如实保留先前失败。'
dump(evidence/'registration.json',{'group':'G4/G2','phase':'one-bounded-correction-after-independent-rejection',
 'project':str(project),'candidate':built,'candidate_before':gate,'fixed_non_accepting_test_reply':fixed_reply,
 'dispatch_condition':'Exact pending plan identity plus a valid independent needs_revision report. This is a fixed isolated test refusal, adds no consent or business facts, and is not the real project owner decision.',
 'author_model':'gemini-3.1-pro-high','timeout_seconds':900,'max_neutral_continuations':0,
 'owner_accepted':False,'os_isolation_verified':False})
(evidence/'user-input.txt').write_text(fixed_reply,encoding='utf-8')
shutil.copyfile(__file__,evidence/'operator-source.py')
shutil.copyfile(project/'.agent-inputs/assessment.json',evidence/'rejected-assessment.json')
shutil.copyfile(origin/'complete-plan.json',evidence/'rejected-plan.json')
shutil.copyfile(origin/'independent-review/review.json',evidence/'independent-findings.json')
def observe():
    state=public();head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==initial['initial_commit'] and all(sha(project/p)==h for p,h in initial['protected_source'].items())
    changed=state['work_item_version']>before['work_item_version']
    return {'reached':changed and state['current_action']['action_type']=='confirm_engineering_plan' and unchanged,
      'next':state,'business_source_and_git_unchanged':unchanged,'semantic_readiness':'pending independent re-review'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=fixed_reply,
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.1-pro-high',
 conversation_id='8a852742-b3e9-4804-93c0-e9ca312df72b',timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],'conversation_id':receipt['last_result'].get('conversation_id'),
 'no_accepting_input_dispatched':True,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
