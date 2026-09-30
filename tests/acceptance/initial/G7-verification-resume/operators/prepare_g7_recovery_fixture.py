"""Prepare disclosed synthetic starting state and one real interrupted writeback."""
from pathlib import Path
import hashlib,json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'strixnova/src'),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump
from tests.integration.test_multi_repository_planning import planning_project,plan_item,accept
from tests.support.project_context import BACKEND,FRONTEND,git
from strixnova.application_coordinator import ApplicationCoordinatorError

work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
fixture=work/'fixture';fixture.mkdir()
built=candidate(ROOT/'.artifacts/candidates/initial-guidance/candidate.json')
project=planning_project(fixture)
counter=fixture/'run-count.txt'
code='from pathlib import Path; p=Path('+repr(str(counter))+'); p.write_text(p.read_text()+"run\\n" if p.exists() else "run\\n"); print("fixed command completed")'
project['assessment']['verification_commands'][0]['argv']=[sys.executable,'-c',code]
dump(evidence/'setup-boundary.json',{'synthetic_preconfigured_state':True,
 'scope':'The ordinary test-fixture helper supplies already-confirmed directions/plans as explicit starting assumptions. No semantic acceptance of those synthetic inputs is claimed. The acceptance under test begins only after the real command has finished and its authority writeback has been interrupted.',
 'owner_accepted':False,'semantic_content_machine_proven':False,'real_command':[sys.executable,'-c',code],
 'injection_point':'Controller-only OSError immediately before record_verification; no package source or installed file is patched.'})
shutil.copyfile(__file__,evidence/'operator-source.py')
adapter,item=plan_item(project)
item=accept(adapter,item,'engineering_plan')
for identity,name in ((BACKEND,'backend-work'),(FRONTEND,'frontend-work')):
    item=adapter.coordinator.delivery(item['work_item_id'],{'repository_id':identity,'worktree_path':str(fixture/name)},expected_version=item['version'])['work_item']
coordinator=adapter.coordinator;transition=coordinator.authority.transition
def interrupted(identity,action,payload,**kwargs):
    if action=='record_verification':raise OSError('registered fixture interruption after real command receipt')
    return transition(identity,action,payload,**kwargs)
coordinator.authority.transition=interrupted
try:
    coordinator.verify(item['work_item_id'],{'command_id':'VC-001','mode':'run'},expected_version=item['version'])
except ApplicationCoordinatorError as error:
    assert 'registered fixture interruption' in str(error)
    dump(evidence/'actual-interruption.json',{'type':type(error).__name__,'code':error.code,'message':str(error)})
else:raise AssertionError('Writeback did not interrupt')
finally:coordinator.authority.transition=transition
current=coordinator.authority.get(item['work_item_id'])
pending=current['data']['pending_effect'];assert pending['kind']=='verification'
assert counter.read_text()=='run\n'
dump(evidence/'before-item.json',current)
entry=project['entry']
dump(entry/'bindings.json',project['bindings'])
shutil.copytree(Path(built['installed_skill']),entry/'.agents/skills/strixnova')
(entry/'AGENTS.md').write_text(f'''# 固定恢复场景

这是预配置的隔离回写中断夹具；起始方向、方案和确认是公开的合成测试前提，不算本轮真实Agent或负责人接受。仅恢复现有验证并作事实说明；不重建项目、创建事项、修改业务源码、提交Git或做交付。
读取 .agents/skills/strixnova/SKILL.md，使用公开命令 `{built['entrypoint']}`，全局参数 `--project-bindings bindings.json`，项目入口为本目录。bindings.json 中列出的相邻仓库、工作区、run-count.txt及状态目录均属于本登记夹具，可通过公开接口读取；不访问夹具根 {fixture} 之外的工程或私有实现，不调用子Agent。所有Python使用 {sys.executable}，禁止裸python/python3和安装软件。原始执行输出由公开history/verify读取，不读SQLite或伪造回执。
''',encoding='utf-8')
info={'group':'G7-recovery','project':str(entry),'fixture_root':str(fixture),'candidate':built,
 'work_item_id':current['work_item_id'],'work_item_version':current['version'],
 'command_id':'VC-001','receipt_id':pending['intent']['receipt_id'],'counter_path':str(counter),
 'counter_sha256':hashlib.sha256(counter.read_bytes()).hexdigest(),'counter_expected':'run\n',
 'source_files':{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in fixture.rglob('*.py') if '.agents' not in p.parts},
 'integration_heads':{str(project[key]):git(project[key],'rev-parse','HEAD') for key in ['front','back']},
 'fixed_input':'刚才验证调用在回写时中断了。请使用现有公开状态继续这个事项，核对已经完成的那次命令和回执，完成必要的恢复与事后说明；不要重复已经结束的命令，不修改业务实现，也不要进入Git交付。',
 'synthetic_initial_state_disclosed':True,'owner_accepted':False,'semantic_content_machine_proven':False}
dump(work/'fixture.json',info);dump(evidence/'fixture.json',info)
artifact=entry/'state/.strixnova/artifacts'
original_outputs={str(p.relative_to(entry)):hashlib.sha256(p.read_bytes()).hexdigest() for p in artifact.rglob('*') if p.is_file()}
dump(evidence/'original-output-hashes.json',original_outputs)
print(json.dumps({'fixture':str(work/'fixture.json'),'pending_kind':pending['kind'],'receipt_id':info['receipt_id'],
 'counter':counter.read_text(),'raw_output_count':len(original_outputs),'native_acceptance_started':False},ensure_ascii=False))
