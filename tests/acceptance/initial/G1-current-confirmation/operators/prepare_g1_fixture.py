"""Create one coherent, current-format business fixture for native lifecycle tests."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import yaml

ROOT=Path.cwd().resolve()
sys.path[:0]=[str(ROOT),str(ROOT/'strixnova/src')]
from tests.support.project_baseline import portable_project_baseline, TEST_MODULE_ID, TEST_READER_MODULE_ID, TEST_CONTEXT_FACT_ID, TEST_INVARIANT_FACT_ID, TEST_CAPABILITY_ID
from tests.support.project_context import FRONTEND
from strixnova.git_project_reader import GitProjectReader
from strixnova.implementation_observation import observe_project_implementation
from strixnova.project_authority_consistency import ProjectAuthorityConsistency

parser=argparse.ArgumentParser()
parser.add_argument('--candidate',type=Path,required=True)
args=parser.parse_args()
candidate_path=args.candidate.resolve()
assert candidate_path.is_relative_to(ROOT/'.artifacts/candidates')
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']).resolve()
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']).resolve()
assert work.is_relative_to(ROOT/'.artifacts/validation')
project=work/'project';project.mkdir()
built=json.loads(candidate_path.read_text(encoding='utf-8'))
assert hashlib.sha256(Path(built['wheel']).read_bytes()).hexdigest()==built['wheel_sha256']
def git(*args):
    return subprocess.run(['git',*args],cwd=project,check=True,capture_output=True,text=True,encoding='utf-8').stdout.strip()
def read(path):return yaml.safe_load((project/path).read_text(encoding='utf-8'))
def write(path,value):
    target=project/path;target.parent.mkdir(parents=True,exist_ok=True)
    target.write_text(yaml.safe_dump(value,allow_unicode=True,sort_keys=False),encoding='utf-8',newline='\n')
git('init','--quiet','-b','main')
for key,value in [('user.name','Strixnova Acceptance Fixture'),('user.email','fixture@example.invalid'),('core.fsmonitor','false'),('core.autocrlf','false')]:git('config',key,value)
hooks=project/'.git/disabled-hooks';hooks.mkdir();git('config','core.hooksPath',str(hooks))
(project/'.gitattributes').write_text('* text=auto eol=lf\n',encoding='utf-8',newline='\n')
(project/'.gitignore').write_text('.strixnova/\n.agents/\n.agent-inputs/\n__pycache__/\n.pytest_cache/\n',encoding='utf-8',newline='\n')
(project/'src.py').write_text('''def duration(start: int, end: int) -> int:
    """Return the duration between integer minute marks."""
    return end - start
''',encoding='utf-8',newline='\n')
(project/'tests').mkdir()
(project/'tests/test_duration.py').write_text('''from src import duration


def test_valid_interval_keeps_its_duration():
    assert duration(10, 60) == 50
''',encoding='utf-8',newline='\n')
(project/'README.md').write_text('''# 预约区间小组件

输入为调用方提供的整数分钟刻度。duration(start, end) 保留现有函数签名：合法区间返回 end-start；end 不大于 start 时必须抛出 ValueError。本组件不解释日期、时区或日历，不持久化预约，不提供界面或远程服务。

当前实现遗漏了不合法顺序的拒绝，已有测试只覆盖合法区间。这是本轮固定的已知缺陷，不要求扩展为新功能。
''',encoding='utf-8',newline='\n')
git('add','--','.gitattributes','.gitignore','src.py','tests/test_duration.py','README.md')
git('commit','--quiet','-m','business fixture source')
origin=git('rev-parse','HEAD')
baseline=portable_project_baseline(project,baseline_id='native-booking-fixture',artifacts=[])
baseline['project']['title']='预约区间小组件'
for row in baseline['code_version']['repositories']:row.update(base_commit=origin,worktree_state='dirty')
baseline['review_state']={'required':True,'reasons':['已知的非法区间拒绝分支尚未实现；修复时同步实现对齐。'],'affected_authority_kinds':['implementation_alignment','code_version']}
write('docs/engineering/baseline.yaml',baseline)
product=read('docs/product/definition.yaml')
product.update(title='预约区间小组件',purpose='提供可重复使用的整数分钟区间校验与时长计算。')
product['primary_users'][0].update(title='调用组件的业务开发者',description='在登记预约前取得合法的区间时长或明确拒绝。')
product['problems'][0]['statement']='不合法的时间顺序不能作为有效预约区间继续使用。'
product['desired_outcomes'][0]['statement']='合法区间返回原有时长，不合法顺序得到 ValueError。'
product['capabilities'][0].update(title='预约区间校验',description='通过 duration(start, end) 校验整数刻度顺序并返回时长。')
product['non_goals'][0]['statement']='不增加日期转换、时区、界面、持久化或远程服务。'
product['constraints'][0]['statement']='保持函数签名和合法区间的既有返回行为。'
product['success_criteria'][0]['statement']='合法区间仍返回 end-start；结束不晚于开始时稳定拒绝。'
write('docs/product/definition.yaml',product)
domain=read('docs/domain/model.yaml');domain.update(title='预约区间领域',purpose='表达区间顺序与时长计算的现有业务边界。');write('docs/domain/model.yaml',domain)
source=read('docs/domain/sources/core.yaml')
source['facts'][0].update(title='预约区间校验上下文',content={'responsibility':'校验给定整数分钟刻度的顺序并计算时长。','decisions':['结束刻度必须严格晚于开始刻度。'],'excluded_responsibilities':['不解释日期、时区或日历，不负责保存预约。']})
source['facts'].append({'fact_id':TEST_INVARIANT_FACT_ID,'status':'confirmed','title':'合法区间必须有正时长','kind':'domain_invariant','product_capability_ids':[TEST_CAPABILITY_ID],'scope_fact_ids':[TEST_CONTEXT_FACT_ID],'dependency_fact_ids':[TEST_CONTEXT_FACT_ID],'content':{'statement':'end 必须严格大于 start；合法时长为 end-start，不合法顺序抛出 ValueError。','protected_fact_ids':[TEST_CONTEXT_FACT_ID]}})
write('docs/domain/sources/core.yaml',source)
architecture=read('docs/architecture/model.yaml');architecture.update(title='预约区间小组件架构',purpose='以一个纯函数模块承载现有区间校验。');write('docs/architecture/model.yaml',architecture)
paths=architecture['artifact_paths']
modules=read(paths['modules']);modules['modules']=modules['modules'][:1]
module=modules['modules'][0];module.update(title='区间校验',responsibility='校验区间顺序并返回时长。',not_responsible_for=['不保存预约，不处理日期或界面。'])
module['public_interface'].update(title='区间函数',operations=[{'name':'duration(start, end)','meaning':'返回合法区间的时长；不合法顺序拒绝。'}]);write(paths['modules'],modules)
relationships=read(paths['relationships']);relationships['relationships']=[];write(paths['relationships'],relationships)
constraints=read(paths['constraints']);constraint=constraints['constraints'][0]
constraint.update(title='函数边界',statement='保持函数签名，合法输入返回值不变；不写入外部状态。',applies_to_module_ids=[TEST_MODULE_ID],verification_methods=[{'method_type':'behavior_acceptance','description':'用真实函数调用检查合法返回与不合法顺序拒绝。'}]);write(paths['constraints'],constraints)
dispositions=read(paths['domain_fact_dispositions']);dispositions['dispositions'].append({**dispositions['dispositions'][0],'domain_fact_id':TEST_INVARIANT_FACT_ID});write(paths['domain_fact_dispositions'],dispositions)
stages=read(paths['implementation_stages']);stages['stages'][0].update(title='当前组件',module_ids=[TEST_MODULE_ID],entry_conditions=['固定测试前提中的当前产品与领域边界已给出。'],completion_conditions=['既有区间边界全部按行为证据实现。']);write(paths['implementation_stages'],stages)
policy=read('docs/engineering/policy.yaml')
policy['method_adoptions'][0].update(status='not_adopted',reason='此固定小组件没有采用 DDD；不因方法名称扩大一次局部修复。',adopted_technique_ids=[])
policy['policy_statements']['testing']=['以真实断言检查函数行为；开发反馈与正式验证记录分别说明。']
policy['verification_command_policy']['allowed_programs']=[{'program':sys.executable,'purpose':'在本隔离工程运行已声明的 pytest 验证。','argument_policy':'exact_plan_only'}]
assert 'agy' in policy['verification_command_policy']['forbidden_agent_program_names']
write('docs/engineering/policy.yaml',policy)
alignment=read('docs/engineering/alignment.yaml')
alignment['code_snapshot']['repositories'][0].update(base_commit=origin,worktree_state='dirty')
reader=GitProjectReader(project);reader.bind_repository_identity(FRONTEND)
observed=observe_project_implementation({FRONTEND:reader},alignment['observation_scopes'])
alignment['observation_coverage']={'contract_version':observed['schema_version'],'overall_status':observed['overall_coverage_status'],'source_manifest_sha256':observed['source_manifest_sha256'],'observation_snapshot_sha256':observed['observation_snapshot_sha256'],'observed_paths':observed['observed_paths'],'records':observed['coverage'],'provider_receipts':observed['provider_receipts']}
alignment['code_snapshot']['observed_on']='2026-09-28'
# Preserve the original finalized fixture: this is a known implementation gap,
# recorded in responsibility/baseline, rather than an open design decision.
alignment['unresolved_items']=[]
write('docs/engineering/alignment.yaml',alignment)
responsibility_path=alignment['artifact_paths']['target_responsibilities']
responsibilities=read(responsibility_path)
responsibilities['records']=[row for row in responsibilities['records'] if row['target_id'] not in {TEST_READER_MODULE_ID,'RELATION-1111111111111111'}]
for row in responsibilities['records']:
    if row['target_kind']=='module':
        row.update(status='partially_implemented',satisfied=['合法输入时长计算已经存在。'],missing=['非法顺序仍未拒绝。'],resolution_plan=['实施本次明确修复并保留断言证据。'])
write(responsibility_path,responsibilities)
ownership_path=alignment['artifact_paths']['source_ownership'];ownership=read(ownership_path)
ownership['records'][0].update(current_status='partially_aligned',rationale='固定起始状态已知缺少非法顺序拒绝；不把合成前提当作本轮验收。')
write(ownership_path,ownership)
for path in (project/'docs').rglob('*.yaml'):
    value=read(path.relative_to(project).as_posix())
    if isinstance(value.get('revision'),dict):value['revision']['confirmed_on']='2026-09-28'
    write(path.relative_to(project).as_posix(),value)
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova')
(project/'.agent-inputs').mkdir()
(project/'AGENTS.md').write_text(f'''# 登记的隔离业务工程

这是固定验收夹具。起始权威的 confirmed 状态是公开的合成测试前提，不代表真实负责人曾接受这些文件；本轮方向、方案和结果仍按正常公开流程等待后续明确输入。

使用本目录 .agents/skills/strixnova/SKILL.md。工具入口为 `{built['entrypoint']}`；业务验证解释器为 `{sys.executable}`，已经有 pytest。不得安装到系统 Python，不读取 Strixnova 私有实现来猜合同，不访问父目录或其他项目，不调用子 Agent。临时请求写在已忽略的 .agent-inputs/。测试中的本地 Git 操作仅限本工程，真实结果接受前不提交，远程操作始终不在范围内。
''',encoding='utf-8',newline='\n')
git('add','--','strixnova-project.yaml','docs','AGENTS.md')
git('commit','--quiet','-m','configured synthetic business authorities')
consistency=ProjectAuthorityConsistency(project).load_working_tree_candidate(None)
assert consistency['structurally_consistent']
assert not (project/'.strixnova').exists()
request='预约区间函数在结束刻度不大于开始刻度时仍返回结果。请修复这个明确缺陷：这些情况抛出 ValueError，合法区间保持原有返回值，函数签名不变。'
info={'group':'G1','project':str(project),'candidate':built,'verification_python':sys.executable,
      'candidate_registration':str(candidate_path),'candidate_registration_sha256':hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
      'policy_sha256':hashlib.sha256((project/'docs/engineering/policy.yaml').read_bytes()).hexdigest(),
      'forbidden_agent_program_names':policy['verification_command_policy']['forbidden_agent_program_names'],
      'initial_commit':git('rev-parse','HEAD'),'source_origin':origin,'request':request,
      'fixture_states_are_synthetic_assumptions':True,'actual_owner_accepted':False,
      'structural_consistency_checked':True,'semantic_content_machine_proven':False}
for target in [work/'fixture.json',evidence/'fixture.json']:target.write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'fixture':str(work/'fixture.json'),'project':str(project),'structurally_consistent':True,'native_execution_started':False},ensure_ascii=False))
