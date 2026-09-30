"""Registered continuation of the completed G1 business fixture, without acceptance."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys

ROOT=Path.cwd().resolve()
sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate, dump, sha
from scripts.agent_acceptance import run_session, assess_turn
from scripts.skill_bundle_manifest import directory_manifest

parser=argparse.ArgumentParser()
parser.add_argument('--fixture',type=Path,required=True)
parser.add_argument('--completed-run',required=True)
parser.add_argument('--review-run',required=True)
parser.add_argument('--author-model',choices=['gemini-3.8-flash-low','claude-opus-4-6-thinking'],required=True)
options=parser.parse_args()
fixture=options.fixture.resolve();assert fixture.is_relative_to(ROOT/'.artifacts/validation')
fixture_info=json.loads(fixture.read_text(encoding='utf-8'))
completed=(ROOT/'.artifacts/validation'/options.completed_run).resolve()
reviewed=(ROOT/'.artifacts/validation'/options.review_run).resolve()
for base in [completed,reviewed]:
    assert base.is_relative_to(ROOT/'.artifacts/validation')
    settled=json.loads((base/'result.json').read_text(encoding='utf-8'))
    assert settled['status']=='passed' and settled['process_settled']
completed_state=json.loads((completed/'evidence/endpoint.json').read_text(encoding='utf-8'))
assert completed_state['next']['work_item_status']=='completed'
review=json.loads((reviewed/'evidence/independent-review/review.json').read_text(encoding='utf-8'))
assert review['execution']['report_valid'] and review['execution']['mechanical_passed']
assert {row['case_id'] for row in review['cases']}=={'GF-CLEAR-BOUNDED','GF-PACE-SAME-CONTRACT','GF-METHODS-SMALL-CHANGE'}
assert all(row['summary']['status']=='passed' and not row['issues'] for row in review['cases'])
review_sources=json.loads((reviewed/'evidence/independent-review/sources.json').read_text(encoding='utf-8'))
assert review_sources['fixture-assumptions']['text']==fixture.read_text(encoding='utf-8')
assert review_sources['delivery/endpoint.json']['text']==(completed/'evidence/endpoint.json').read_text(encoding='utf-8')
author_model=options.author_model


evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK'])
project=Path(fixture_info['project']).resolve();assert project.is_relative_to(ROOT/'.artifacts/validation')
built=candidate(Path(fixture_info['candidate_registration']));assert built==fixture_info['candidate']
for identity,value in review_sources.items():
    if identity.startswith('final/'):
        assert (project/identity.removeprefix('final/')).read_text(encoding='utf-8')==value['text']
assert project.is_dir() and (project/'.git').is_dir()
assert directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256']==built['skill_sha256']
previous=evidence/'fixture-before';previous.mkdir()
shutil.copyfile(project/'AGENTS.md',previous/'AGENTS.md')
shutil.copytree(project/'.agents/skills/strixnova',previous/'skill')
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova',dirs_exist_ok=True)
instructions=f'''# 登记的隔离业务工程

本工程是已完成一项区间修复的隔离夹具，既有初始 confirmed 权威是公开的合成起始前提，后续流程是本轮实际执行记录。新请求按其实际授权处理，不能把旧结果接受当作新授权。

读取 .agents/skills/strixnova/SKILL.md。公开工具入口为 `{built['entrypoint']}`；所有 Python 调用必须用 `{sys.executable}`，禁止裸 python/python3，不安装软件，不读 Strixnova 私有实现，不访问父目录或别的项目，不调用子 Agent。临时请求放在 .agent-inputs/。当前只允许调查、登记事项、起草和解释文档；业务代码、测试、Git 提交和远程操作尚未授权。长期权威的确认元数据只能由公开程序在实际收到明确决定后写入。
'''
(project/'AGENTS.md').write_text(instructions,encoding='utf-8',newline='\n')
inputs=project/'.agent-inputs/g4-fixed';inputs.mkdir(exist_ok=False)
background='''# 当前可读事实

本工程既有目标是纯函数预约区间校验，已完成修复；取消申请与周报都是新产品范围，尚未实现。
拟议扩展涉及成员服务与运营汇总两个单元。成员服务负责人说“成员可取消自己的申请”，运营方说“审批决定的结果不得由成员直接改写”。目前“申请”是待审核还是已生效预约，口头说明存在冲突，不能由代码命名决定业务含义。
另一个技术上下文里，“下载请求”只是一次读取周报的传输动作，不等同于申请预约。
request_projection.py 是本轮预置的待审源码样本：把所有申请显示成已生效预约。它不是经过验收的实现，也不构成领域权威；当前项目尚无这些业务接口。
'''
(inputs/'background.md').write_text(background,encoding='utf-8',newline='\n')
(inputs/'request_projection.py').write_text('def display_request(record):\n    return {"label": "已生效预约", "id": record["id"]}\n',encoding='utf-8',newline='\n')
fixed={
 'start':'请先读取本工程 AGENTS.md、指定 Skill 和 .agent-inputs/g4-fixed/background.md。我要把现有组件扩展为预约申请工具：成员能取消自己的申请，负责人能下载每周汇总。这两个结果都需要，但可以分别交付。请开始形成工作，具体业务含义还有缺口；到需要我明确的关键事实时提出问题，先不实施代码，也不替我确认候选。',
 'clarify_read_only':'先澄清一个前提：这里的申请是待审核的预约申请，不是已经生效的预约。成员只可撤回自己仍待审核的申请；已批准的预约需要由审批人另行处理，本轮不做该处理。下载请求只是传输动作，不能和预约申请合并成一个领域对象。请这轮只读解释这项纠正，指出哪些旧推断、权威含义和给定源码样本受影响，区分代码偏离与尚未核实的内容；暂时不要修改候选文件。',
 'form_candidates':'请把刚才明确的纠正正式落实到产品、领域、目标架构和工程政策的完整候选，以及对应 PRD 和受影响的事项方向；保留不受影响的稳定身份，逐项说明旧含义和下游处置。补充固定业务事实：一名成员只能操作本人申请；身份来自可信宿主会话，不信任传入角色或所有者字段；只允许待审核状态撤回；重复撤回返回相同结果且不重复记审计；撤回与审批并发时只允许一个版本成功；响应丢失后可查询实际状态；审计保留操作者、原状态、新状态和操作身份。周报仅负责人可读，按本地已指定的自然周统计当前状态，不含成员私人联系方式；暂不实现自动发送、缴费或已批准预约的取消。两个单元必须共用申请身份、状态含义和决定权，不能各自定义。界面先限定为本地终端交互，不增加网页或网络服务。这些是候选的业务输入，不是对候选的接受。先完成实际可审阅文件，解释完整包和限制，等我决定；实现对齐保持草稿，不实施业务代码，不提交。',
 'accept_authorities':'接受当前完整展示的产品定义、领域模型、目标架构和工程政策四项候选；实现对齐仍保持草稿，实际结果另行处理。',
}
registration={'group':'G4','project':str(project),'candidate':built,'candidate_registration':fixture_info['candidate_registration'],'fixed_inputs':fixed,
 'g1_fixture':str(fixture),'completed_g1_run':options.completed_run,'reviewed_g1_run':options.review_run,
 'fixed_inputs_sha256':hashlib.sha256(json.dumps(fixed,ensure_ascii=False,sort_keys=True).encode('utf-8')).hexdigest(),
 'model':author_model,'reviewer_model':'gemini-3.8-flash-low','timeout_seconds':600,
 'scope':'Existing G1 fixture, new proposed product scope; only formation and authority decisions after independent gate.',
 'acceptance_dispatch_rule':'Only after complete real candidates, public identities and independent native readiness review; never inferred by controller.',
 'owner_accepted':False,'os_isolation_verified':False,
 'initial_commit':subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip(),
 'protected_source':{p:sha(project/p) for p in ['src.py','tests/test_duration.py']},
 'background_files':{p.relative_to(project).as_posix():sha(p) for p in inputs.iterdir()}}
dump(evidence/'registration.json',registration)
shutil.copyfile(__file__,evidence/'operator-source.py')
(evidence/'user-input.txt').write_text(fixed['start'],encoding='utf-8')
def observe():
    current=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=current==registration['initial_commit'] and all(sha(project/name)==digest for name,digest in registration['protected_source'].items())
    with sqlite3.connect((project/'.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        items=[row[0] for row in c.execute('SELECT work_item_id FROM work_items ORDER BY work_item_id')]
    return {'reached':unchanged,'business_source_and_git_unchanged':unchanged,'work_item_ids':items,
            'endpoint_scope':'Native response returned with source and Git boundaries preserved; formation semantics require independent review.'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=fixed['start'],
 evidence=evidence/'execution',observe_endpoint=observe,model=author_model,timeout=600,
 max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps'])
endpoint=observe();dump(evidence/'endpoint.json',endpoint)
summary={'phase':'G4-start','execution_settled':receipt['mechanical_passed'],'endpoint':endpoint,
 'conversation_id':receipt['last_result'].get('conversation_id'),'owner_accepted':False,'semantic_verdict':'pending'}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
