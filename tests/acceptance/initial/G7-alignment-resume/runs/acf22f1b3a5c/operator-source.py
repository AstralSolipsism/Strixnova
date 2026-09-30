"""Reuse the closed recovery fixture to prepare a real existing alignment draft."""
from pathlib import Path
import hashlib,json,os,shutil,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'strixnova/src'),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump
from strixnova.host_adapter import LocalHostAdapter
from tests.integration.test_multi_repository_execution import refresh_planned_alignment
from tests.support.project_context import git
origin=ROOT/'.artifacts/validation/d18b25e5739d'
info=json.loads((origin/'work/fixture.json').read_text(encoding='utf-8'))
recovered=json.loads((ROOT/'.artifacts/validation/0b23590466a6/result.json').read_text(encoding='utf-8'));assert recovered['status']=='passed'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']);work=Path(os.environ['STRIXNOVA_VALIDATION_WORK'])
fixture=Path(info['fixture_root']);entry=Path(info['project']);bindings=json.loads((entry/'bindings.json').read_text(encoding='utf-8'))
adapter=LocalHostAdapter(entry,project_bindings=bindings);item=adapter.coordinator.authority.get(info['work_item_id'])
assert item['data']['pending_effect'] is None
project={'entry':entry,'front':fixture/'front','back':fixture/'back','bindings':bindings,
 'assessment':item['data']['engineering']['assessment']}
baseline=yaml.safe_load((project['front']/'docs/engineering/baseline.yaml').read_text(encoding='utf-8'))
model_path=baseline['authority_refs']['implementation_alignment']['path']
project['alignment_before']=yaml.safe_load((project['front']/model_path).read_text(encoding='utf-8'))
dump(evidence/'setup-boundary.json',{'synthetic_starting_draft':True,
 'scope':'Existing current-format fixture and its actual approved-operation bindings are reused. The starting draft uses the existing deterministic test helper and its explicit synthetic source-ownership choices. It is not semantic acceptance, not a new business implementation, and not a new owner decision.',
 'previous_real_recovery_run':'0b23590466a6','owner_accepted':False,'semantic_content_machine_proven':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
refresh_planned_alignment(project,adapter,item)
current=adapter.coordinator.authority.get(item['work_item_id']);assert current['version']==item['version']
front_work=fixture/'frontend-work';model=yaml.safe_load((front_work/model_path).read_text(encoding='utf-8'))
assert model['revision']['status']=='draft'
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json')
previous=evidence/'previous-environment';previous.mkdir();shutil.copyfile(entry/'AGENTS.md',previous/'AGENTS.md')
shutil.copytree(entry/'.agents/skills/strixnova',previous/'skill')
shutil.copytree(Path(built['installed_skill']),entry/'.agents/skills/strixnova',dirs_exist_ok=True)
(entry/'AGENTS.md').write_text(f'''# 固定对齐草稿恢复

本场景复用已收口的验证恢复夹具。起始方向、方案与当前对齐草稿的语义选择是明确披露的合成测试前提，不表示真人接受或完整实现已验收。只允许检查并继续现有实现对齐草稿；不修改业务源码，不确认、不采用、不提交Git，也不重跑验证。
读取 .agents/skills/strixnova/SKILL.md。公开入口为 `{built['entrypoint']}`，全局参数 `--project-bindings bindings.json`，项目入口为本目录。bindings.json列出的仓库、现有工作区与状态均属于夹具根 {fixture}，允许经公开接口访问；不读取夹具外工程或私有数据库/实现，不调用子Agent。所有Python必须用 {sys.executable}，禁止裸python/python3或安装软件。临时请求放本入口目录。
''',encoding='utf-8')
paths=[model_path,*model['artifact_paths'].values(),'docs/engineering/baseline.yaml']
before=evidence/'before-alignment';before.mkdir()
for relative in paths:
    p=front_work/relative;target=before/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,target)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
details={'group':'G7-alignment','project':str(entry),'fixture_root':str(fixture),'candidate':built,
 'work_item_id':item['work_item_id'],'work_item_version':item['version'],'alignment_root':str(front_work),
 'model_path':model_path,'alignment_revision':model['revision'],'preparation':project['alignment_preparation'],
 'alignment_paths':paths,'source_files':{str(p):sha(p) for p in fixture.rglob('*.py') if '.agents' not in p.parts},
 'integration_heads':{str(project[k]):git(project[k],'rev-parse','HEAD') for k in ['front','back']},
 'counter_path':info['counter_path'],'counter_expected':info['counter_expected'],
 'fixed_input':'上一次已经形成了实现对齐草稿，但检查还没有收口。请核对本事项实际计划、操作归属、已有草稿和源码观察，沿现有草稿继续完成本轮对齐检查与必要候选写入；如有缺口据实留在草稿中。不要移动业务源码、为观察器补包结构、重跑验证或进行Git交付，也不要把草稿当作已接受结果。',
 'synthetic_starting_draft_disclosed':True,'owner_accepted':False,'semantic_content_machine_proven':False}
dump(work/'fixture.json',details);dump(evidence/'fixture.json',details)
print(json.dumps({'fixture':str(work/'fixture.json'),'draft_revision':model['revision'],'source_count':len(details['source_files']),
 'work_item_version_unchanged':True,'native_acceptance_started':False},ensure_ascii=False))
