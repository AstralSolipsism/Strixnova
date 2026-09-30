"""Add real diagnostic receipts/cancellation to the existing completed business fixture."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'strixnova/src'),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from strixnova.host_adapter import LocalHostAdapter
from tests.support.governance_assessment import direction_fixture,exploration_assessment,bind_assessment_to_work_item

project=ROOT/'.artifacts/validation/f0addbc9966a/work/project'
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json')
adapter=LocalHostAdapter(project)
head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
protected={p:sha(project/p) for p in ['src.py','tests/test_duration.py']}
setup={'scope':'Controller-preconfigured diagnostic direction/plan is a disclosed synthetic starting assumption, not semantic/owner acceptance. Subsequent failed command, not-run receipt, cancellation and missing-output condition are actual program/file operations. Existing G1 accepted delivery and G4 unaccepted/superseded plans are untouched.',
 'fixed_initial_acceptance':'接受这份固定隔离诊断前提；不代表真实负责人或本轮行为验收。',
 'diagnostic_request':'仅在本隔离样例产生一次真实失败诊断记录和一次明确未运行记录，再取消该诊断分支；不修改业务源码。',
 'cancel_reason':'固定历史读取场景：诊断分支到此结束，保留已经生成的失败与未运行记录。',
 'missing_output_rule':'Preserve the exact failed stdout outside the managed project, then remove only that owned original file. Leave an explicitly unrelated current same-name file in a separate inputs directory.',
 'owner_accepted':False,'semantic_content_machine_proven':False}
dump(evidence/'setup-boundary.json',setup);shutil.copyfile(__file__,evidence/'operator-source.py')
item=adapter.coordinator.intake(title='预约工具固定诊断分支',raw_request=setup['diagnostic_request'])
dump(evidence/'created-item.json',item)
ctx=adapter.next_step(item['work_item_id'],record_refs=['project.direction_context'])['records']['project.direction_context']
direction=direction_fixture()
direction.update(goal='保留一次真实失败与一次未运行的诊断事实，随后结束本诊断分支。',non_goals=['不修改产品或业务实现，不把诊断记录当作业务验收。'],tradeoffs=['只生成受控的状态样本，不尝试修复真实产品功能。'])
direction['scope'][0]['statement']='在固定隔离工程记录实际诊断命令结果，按事实区分失败、未运行和取消。'
direction['acceptance'][0]['statement']='保留真实退出码、输出、未运行原因和取消状态，不虚构通过。'
direction['decision_context']={'context_ref':ctx['context_ref'],'capability_refs':[ctx['capability_catalog'][0]['capability_ref']],
 'guardrail_dispositions':[{'guardrail_ref':g['guardrail_ref'],'disposition':'applies','reason':'只处理固定诊断记录，不改变既有业务边界。'} for g in ctx['guardrails']], 'assumptions':[]}
direction['work_item_relations']=[{'relation_type':'related_to','target_work_item_id':'WI-20260928-9CA7291C','reason':'对同一预约工具演进目标的固定诊断记录；关系不代表组合接受。'}]
item=adapter.submit_direction(item['work_item_id'],{'direction':direction,'ready_for_confirmation':True},expected_version=item['version'])
def synthetic_accept(item,kind):
    challenge=adapter.current_action(item['work_item_id'])['confirmation_challenge']
    return adapter.confirm(item['work_item_id'],kind,candidate_fingerprint=challenge['candidate_fingerprint'],
      user_confirmation=setup['fixed_initial_acceptance'],agent_decision={'decision':'accept','reason':'预配置的合成诊断前提；不作为真实负责人或本轮Agent验收。'},expected_version=item['version'])
item=synthetic_accept(item,'direction')
scratch=work/'assessment-template';scratch.mkdir()
assessment=exploration_assessment(scratch)
assessment['assessment_id']='EA-HISTORY-DIAGNOSTIC-001'
assessment.pop('verification_not_required_reason',None)
assessment['verification_reviews']=[]
assessment['verification_commands']=[
 {'argv':[sys.executable,'-c','import sys; print("controlled diagnostic failure"); sys.exit(7)'],'cwd':'.','run_kind':'targeted_test',
  'covers':['direction.acceptance:DIRACC-3333333333333333','direction.constraint:DIRCON-2222222222222222'],'reason':'运行已登记的受控失败命令，记录真实失败而非伪造回执。'},
 {'argv':[sys.executable,'-c','print("this registered command is intentionally not run")'],'cwd':'.','run_kind':'targeted_test',
  'covers':['direction.acceptance:DIRACC-3333333333333333'],'reason':'本固定诊断明确留作未运行分支。'},
]
bind_assessment_to_work_item(assessment,item)
dump(evidence/'synthetic-assessment.json',assessment)
item=adapter.submit_engineering_assessment(item['work_item_id'],assessment,expected_version=item['version'])
item=synthetic_accept(item,'engineering_plan')
dump(evidence/'prepared-diagnostic-state.json',item)
commands=item['data']['engineering']['plan']['verification_commands'];assert len(commands)==2
first=adapter.coordinator.verify(item['work_item_id'],{'command_id':commands[0]['command_id'],'mode':'run'},expected_version=item['version'])
assert first['verification']['result']=='failed' and first['verification']['exit_code']==7
item=first['work_item'];dump(evidence/'real-failed-execution.json',first)
second=adapter.coordinator.verify(item['work_item_id'],{'command_id':commands[1]['command_id'],'mode':'not_run','reason':'本次固定诊断明确不执行此命令；不是环境故障，也不是通过。'},expected_version=item['version'])
assert second['verification']['result']=='not_run';item=second['work_item'];dump(evidence/'real-not-run-record.json',second)
item=adapter.coordinator.cancel(item['work_item_id'],{'reason':setup['cancel_reason']},expected_version=item['version'])
assert item['status']=='cancelled';dump(evidence/'actual-cancellation.json',item)
reference=first['verification']['raw_output_refs']['stdout'];output=Path(reference)
if not output.is_absolute():output=project/output
output=output.resolve();assert output.is_relative_to(project/'.strixnova/artifacts') and output.is_file() and not output.is_symlink()
original=output.read_bytes();preserved=evidence/'withheld-original-stdout.log';preserved.write_bytes(original)
assert preserved.read_bytes()==original
output.unlink()
current=project/'.agent-inputs/g8-current-files';current.mkdir()
(current/output.name).write_text('CURRENT UNRELATED FILE: this is not the historical diagnostic stdout.\n',encoding='utf-8')
dump(evidence/'availability-change.json',{'registered_path':str(output),'original_sha256':hashlib.sha256(original).hexdigest(),
 'original_preserved_as':str(preserved),'managed_original_missing':not output.exists(),'unrelated_current_file':str(current/output.name)})
assert all(sha(project/p)==h for p,h in protected.items())
assert subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()==head
shutil.copyfile(project/'AGENTS.md',evidence/'previous-AGENTS.md')
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova',dirs_exist_ok=True)
(project/'AGENTS.md').write_text(f'''# 固定历史与整体进度只读查询

本工程是本轮隔离业务样例；原区间修复记录来自真实原生流程，后续申请/周报候选未被接受。固定诊断分支的起始方向/计划是已公开的合成前提，但失败命令、未运行回执和取消是本轮实际执行；这些都不是实际负责人对真实Strixnova项目的接受。
使用 .agents/skills/strixnova/SKILL.md 和真实存在的history-and-upgrade.md。入口为 `{built['entrypoint']}`。当前只读查询，不能按CurrentAction推进、创建事项、修改文件、直接读私有数据库或提交Git，不访问其他项目，不调用子Agent。所有Python（包括JSON处理）必须用 `{sys.executable}`，禁止裸python/python3/py。原输出只按公开history返回的ref读取，不能拿当前同名文件当历史证据。
''',encoding='utf-8')
fixed='请围绕“完善预约工具”这一阅读用目标，使用现有公开历史与关系查询说明：区间校验修复、成员撤回、周报、固定诊断分别形成了什么，哪些结果已接受并交付、哪些候选被替代或仍未接受、哪个分支取消了；核查已记录的通过、失败和未运行，以及原始证据现在是否可取。明确目标还缺什么和哪些判断没有证据。只读，不推进当前动作、不新建事项，不把关联关系说成整体接受或完成百分比，不用当前同名文件替代旧输出。'
info={'group':'G8','project':str(project),'candidate':built,'fixed_input':fixed,
 'work_item_ids':['WI-20260928-9CA7291C','WI-20260928-9A2A1BC1','WI-20260928-DB4C76AE',item['work_item_id']],
 'diagnostic_work_item_id':item['work_item_id'],'failed_receipt_id':first['verification']['receipt_id'],
 'not_run_receipt_id':second['verification']['receipt_id'],'original_output_missing':str(output),
 'source_files':protected,'integration_head':head,'synthetic_diagnostic_preconditions_disclosed':True,'owner_accepted':False}
dump(work/'fixture.json',info);dump(evidence/'fixture.json',info)
print(json.dumps({'fixture':str(work/'fixture.json'),'diagnostic_item':item['work_item_id'],'failed_exit_code':7,'not_run_recorded':True,'cancelled':True,'native_history_acceptance_started':False},ensure_ascii=False))
