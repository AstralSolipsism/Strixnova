"""Continue after the real failed command; do not run it twice."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'strixnova/src'),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from strixnova.host_adapter import LocalHostAdapter
project=ROOT/'.artifacts/validation/f0addbc9966a/work/project'
previous=ROOT/'.artifacts/validation/858e4ed186f7/evidence'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']);work=Path(os.environ['STRIXNOVA_VALIDATION_WORK'])
source=json.loads((previous/'real-failed-execution.json').read_text(encoding='utf-8'))
setup=json.loads((previous/'setup-boundary.json').read_text(encoding='utf-8'))
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json')
adapter=LocalHostAdapter(project);item=adapter.coordinator.authority.get(source['work_item']['work_item_id'])
assert item['version']==source['work_item']['version'] and len(item['data']['verifications'])==1
assert item['data']['verifications'][0]['receipt_id']==source['verification']['receipt_id']
head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
protected={p:sha(project/p) for p in ['src.py','tests/test_duration.py']}
commands=item['data']['engineering']['plan']['verification_commands']
shutil.copyfile(__file__,evidence/'operator-source.py')
shutil.copyfile(previous/'real-failed-execution.json',evidence/'real-failed-execution.json')
shutil.copyfile(previous/'setup-boundary.json',evidence/'setup-boundary.json')
second=adapter.coordinator.verify(item['work_item_id'],{'command_id':commands[1]['command_id'],'mode':'not_run',
 'not_run_reason':'本次固定诊断明确不执行此命令；不是环境故障，也不是通过。',
 'limitations':['该命令明确未执行，不能据此判断任何测试或业务是否通过。'],
 'code_change_assessment':{'changed_after':False,'needs_retest':False,
 'rationale':'这是公开登记的未运行诊断分支，未修改业务实现；本记录保持not_run，不提供业务验证通过结论。'}},expected_version=item['version'])
assert second['verification']['result']=='not_run';item=second['work_item'];dump(evidence/'real-not-run-record.json',second)
item=adapter.coordinator.cancel(item['work_item_id'],{'reason':setup['cancel_reason']},expected_version=item['version'])
assert item['status']=='cancelled';dump(evidence/'actual-cancellation.json',item)
output=Path(source['verification']['raw_output_refs']['stdout'])
if not output.is_absolute():output=project/output
output=output.resolve();assert output.is_relative_to(project/'.strixnova/artifacts') and output.is_file() and not output.is_symlink()
for node in [output,*output.parents]:
    if node==project.parent:break
    assert not node.is_symlink() and not node.is_junction()
original=output.read_bytes();copy=evidence/'withheld-original-stdout.log';copy.write_bytes(original);assert copy.read_bytes()==original
output.unlink()
current=project/'.agent-inputs/g8-current-files';current.mkdir()
(current/output.name).write_text('CURRENT UNRELATED FILE: this is not the historical diagnostic stdout.\n',encoding='utf-8')
dump(evidence/'availability-change.json',{'registered_path':str(output),'original_sha256':hashlib.sha256(original).hexdigest(),
 'original_preserved_as':str(copy),'managed_original_missing':not output.exists(),'unrelated_current_file':str(current/output.name)})
assert all(sha(project/p)==h for p,h in protected.items())
assert subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()==head
shutil.copyfile(project/'AGENTS.md',evidence/'previous-AGENTS.md')
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova',dirs_exist_ok=True)
(project/'AGENTS.md').write_text(f'''# 固定历史与整体进度只读查询

本工程是本轮隔离业务样例；区间修复记录来自真实原生流程，后续申请/周报候选未被接受。诊断分支的起始方向/计划是明确合成前提，失败命令、未运行回执和取消则是本轮实际程序执行。固定角色接受不代表真实负责人对Strixnova项目的接受。
使用 .agents/skills/strixnova/SKILL.md 和真实存在的history-and-upgrade.md。入口为 `{built['entrypoint']}`。当前只读，不能依CurrentAction继续建设、创建事项、修改文件、读私有数据库或提交Git，不访问其他项目，不调用子Agent。任何Python必须使用 `{sys.executable}`，禁止裸python/python3/py。原输出只按公开history返回的ref读取，不拿当前同名文件替代历史。
''',encoding='utf-8')
fixed='请围绕“完善预约工具”这一阅读用目标，使用现有公开历史与关系查询说明：区间校验修复、成员撤回、周报、固定诊断分别形成了什么，哪些结果已接受并交付、哪些候选被替代或仍未接受、哪个分支取消了；核查已记录的通过、失败和未运行，以及原始证据现在是否可取。明确目标还缺什么和哪些判断没有证据。只读，不推进当前动作、不新建事项，不把关联关系说成整体接受或完成百分比，不用当前同名文件替代旧输出。'
info={'group':'G8','project':str(project),'candidate':built,'fixed_input':fixed,
 'work_item_ids':['WI-20260928-9CA7291C','WI-20260928-9A2A1BC1','WI-20260928-DB4C76AE',item['work_item_id']],
 'diagnostic_work_item_id':item['work_item_id'],'failed_receipt_id':source['verification']['receipt_id'],
 'not_run_receipt_id':second['verification']['receipt_id'],'original_output_missing':str(output),
 'source_files':protected,'integration_head':head,'synthetic_diagnostic_preconditions_disclosed':True,'owner_accepted':False}
dump(work/'fixture.json',info);dump(evidence/'fixture.json',info)
print(json.dumps({'fixture':str(work/'fixture.json'),'failed_command_repeated':False,'not_run_recorded':True,'cancelled':True,'native_acceptance_started':False},ensure_ascii=False))
