"""Reuse the actual completed G1 commit for one isolated first-intake check."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.skill_bundle_manifest import directory_manifest

original=json.loads((ROOT/'.artifacts/validation/6bbae8a5d2e5/evidence/registration.json').read_text(encoding='utf-8'))
built=candidate(Path(original['candidate_registration']));assert built==original['candidate']
source=Path(original['project']).resolve();assert source.is_relative_to(ROOT/'.artifacts/validation')
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
project=(work/'project').resolve();assert project.is_relative_to(ROOT/'.artifacts/validation') and not project.exists()
env={k:v for k,v in os.environ.items() if k not in {'GIT_DIR','GIT_WORK_TREE','GIT_COMMON_DIR'}}
def git(*args,cwd=None):
    return subprocess.run(['git','-c','core.fsmonitor=false',*args],cwd=cwd,env=env,check=True,capture_output=True,text=True,encoding='utf-8',timeout=60).stdout.strip()
assert git('rev-parse','refs/heads/main',cwd=source)==original['initial_commit']
# Both paths are explicit local owned fixtures. No network, remote push, or new business commit.
git('-c','core.hooksPath='+str(work/'disabled-hooks'),'clone','--quiet','--local','--no-hardlinks','--single-branch','--branch','main','--no-tags',str(source),str(project))
assert git('rev-parse','HEAD',cwd=project)==original['initial_commit']
git('remote','remove','origin',cwd=project)
hooks=project/'.git/disabled-hooks';hooks.mkdir()
for key,value in [('core.hooksPath',str(hooks)),('core.fsmonitor','false'),('core.autocrlf','false')]:git('config','--local',key,value,cwd=project)
assert not (project/'.strixnova').exists(),'Do not copy existing authority history'
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova')
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==built['skill_sha256']
old_inputs=source/'.agent-inputs/g4-fixed';inputs=project/'.agent-inputs/g4-fixed';inputs.mkdir(parents=True)
for relative,expected in original['background_files'].items():
    assert sha(source/relative)==expected
    shutil.copyfile(source/relative,inputs/Path(relative).name)
instructions=f'''# 登记的独立首次登记复验

本工程复用本轮真实完成的小修复 Git 版本；初始 confirmed 权威仍是原登记的合成前提。当前没有任何新请求对应的 WorkItem，不能把原修复结果接受当作新请求授权。

读取 .agents/skills/strixnova/SKILL.md。公开入口 `{built['entrypoint']}`；所有 Python 必须用 `{sys.executable}`，禁止裸 python/python3，不安装软件，不访问父目录或别的工程，不读 Strixnova 私有实现，不调用子Agent。当前仅允许调查、登记当前请求和只读澄清；不修改业务源码、测试、工程文档或Git，不确认候选，不实施代码。临时请求放在 .agent-inputs/。本次到需要负责人提供实质事实时停止，不编造同意。
'''
(project/'AGENTS.md').write_text(instructions,encoding='utf-8',newline='\n')
tracked=git('ls-files',cwd=project).splitlines()
protected={relative:sha(project/relative) for relative in tracked if relative!='AGENTS.md'}
assert all(protected[relative]==digest for relative,digest in original['protected_source'].items())
registration={'phase':'GF-CONCRETE-INCOMPLETE-targeted-first-intake','project':str(project),'candidate':built,
 'candidate_registration':original['candidate_registration'],'source_fixture':str(source),'source_commit':original['initial_commit'],
 'fixed_input':original['fixed_inputs']['start'],'fixed_input_sha256':hashlib.sha256(original['fixed_inputs']['start'].encode('utf-8')).hexdigest(),
 'protected_files':protected,'initial_authority_database_absent':True,'model':original['model'],
 'reviewer_model':original['reviewer_model'],'timeout_seconds':420,'owner_accepted':False,'os_isolation_verified':False,
 'scope':'Only first-request intake before clarification. No full G1/G4 replay, implementation, candidate acceptance or delivery.'}
dump(work/'registration.json',registration);dump(evidence/'registration.json',registration)
shutil.copyfile(__file__,evidence/'operator-source.py')
print(json.dumps({'project':str(project),'commit':original['initial_commit'],'protected_files':len(protected),'new_native_calls':0},ensure_ascii=False))
