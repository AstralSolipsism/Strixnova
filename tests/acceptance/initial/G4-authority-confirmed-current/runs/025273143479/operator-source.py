"""Continue the existing accepted implementation; do not resend any decision."""
from pathlib import Path
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
initial=json.loads((ROOT/'.artifacts/validation/f0af53c1b14a/evidence/registration.json').read_text(encoding='utf-8'))
prior=ROOT/'.artifacts/validation/3360464f87d1'
result=json.loads((prior/'result.json').read_text(encoding='utf-8'));assert result['process_settled']
receipt=json.loads((prior/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert receipt['last_result']['status']=='SUCCESS' and not receipt['verdict']['unsettled_steps']
project=Path(initial['project']);built=candidate(Path(initial['candidate_registration']));evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
identifier='WI-20260929-DEC61550';secondary='WI-20260929-274215EA'
def public(identity):
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=public(identifier);other=public(secondary)
assert before['work_item_version']==24 and before['current_action']['action_type']=='complete_implementation_slice'
restore=project/'.agent-inputs/reviewed-prd-restore.md';assert not restore.exists()
source=prior/'evidence/candidate-before/product/prd.md';assert source.is_file()
shutil.copyfile(source,restore);shutil.copyfile(source,evidence/'reviewed-prd-restore.md')
prompt=(f'继续已接受的R5工程方案，事项{identifier}版本24。此前固定方案接受已明确允许本临时工程内实施与验证，四类上游候选也已由程序确认；本条没有新的接受或授权扩大，不要重复确认或再次要求实施许可。'
 '当前SLICE-001是治理文档与编码前真实记录，不是业务代码切片；完成后按依赖进入业务实现切片，再完成编码后对齐与正式验证。'
 '前轮为确认暂时移除了PRD，原已审阅内容现保存在 .agent-inputs/reviewed-prd-restore.md；按方案内已声明的PRD操作恢复docs/product/prd.md，并根据已经发生的确认更新只读来源状态，不重新改写四类已确认正文。'
 f'AGENTS.md被恢复成基线版本，当前本轮实际入口仍是 {built["entrypoint"]}，Python为 {sys.executable}。这是已记录的环境信息，不要为换入口再制造未声明的AGENTS.md改动。'
 '保持原duration源代码和测试不变、周报仍待方向决定，按公开CurrentAction与输入合同完成其余授权实施和验证。'
 '遇真实问题如实报告，不伪造通过或自行接受实际结果；禁止Git提交、合入或远端操作。到实际结果候选已展示且等待负责人决定时停止。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
dump(evidence/'registration.json',{'phase':'continue-existing-authorized-G4-implementation','project':str(project),'candidate':built,
 'work_item_id':identifier,'before':before,'secondary_before':other,'fixed_non_accepting_input':prompt,
 'input_sha256':sha(evidence/'user-input.txt'),'restored_input_sha256':sha(restore),'prior_plan_permission_run':'156586864345',
 'actual_authority_decision_run':'3360464f87d1','model':initial['model'],'timeout_seconds':900,'max_continuations':0,'owner_accepted':False})
def observe():
    state=public(identifier);other_now=public(secondary)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    stable=all(sha(project/path)==digest for path,digest in initial['protected_source'].items())
    other_same=other_now['work_item_version']==other['work_item_version'] and other_now['current_action']==other['current_action']
    return {'reached':state['current_action']['action_type']=='confirm_actual_result' and head==initial['initial_commit'] and stable and other_same,
            'next':state,'head_unchanged':head==initial['initial_commit'],'existing_duration_source_and_tests_unchanged':stable,
            'secondary_direction_unchanged':other_same,'actual_result_acceptance_dispatched':False,'owner_accepted':False}
executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=receipt['last_result']['conversation_id'],
    timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'mechanical_passed':executed['mechanical_passed'],'reached':endpoint['reached'],'new_acceptance_dispatched':False,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if executed['mechanical_passed'] and endpoint['reached'] else 1)
