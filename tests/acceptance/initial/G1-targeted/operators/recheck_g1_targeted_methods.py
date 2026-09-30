"""Two bounded native rechecks; not a replay of the completed Git lifecycle."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate, dump, snapshot
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest

work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
built=candidate(ROOT/'.artifacts/candidates/initial-guidance/candidate.json')
project=work/'project';project.mkdir()
subprocess.run(['git','init','--quiet',str(project)],check=True,capture_output=True)
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova')
state=json.loads((ROOT/'.artifacts/validation/10bdc29a6a23/evidence/before.json').read_text(encoding='utf-8'))
dump(project/'direction-candidate.json',state)
source='''def duration(start: int, end: int) -> int:
    """Return the duration between integer minute marks."""
    return end - start
'''
test='''from src import duration


def test_valid_interval_keeps_its_duration():
    assert duration(10, 60) == 50
'''
(project/'src.py').write_text(source,encoding='utf-8',newline='\n')
(project/'tests').mkdir();(project/'tests/test_duration.py').write_text(test,encoding='utf-8',newline='\n')
(project/'AGENTS.md').write_text(f'''# 定点方法复验

这是已登记的两个定点场景，不重演整套项目治理或交付。使用本目录 .agents/skills/strixnova/SKILL.md 及适用指引。direction-candidate.json 是先前真实程序形成、当时尚未接受的方向快照，本场景把它作为首次展示的明确输入；不是新的真实事项状态，不调用CLI确认或创建事项，不执行Git交付。

第一段仅读取并向负责人说明当前候选，不能改文件或代签决定。第二段只有收到明确输入后才授权修改 src.py 与 tests/test_duration.py；这是已有方案内 test-first 方法的定点实现，不代表负责人对真实重构的接受。所有Python命令必须用 {sys.executable}，禁止裸python/python3或安装系统依赖。不访问父目录或其他项目，不调用子Agent。
''',encoding='utf-8',newline='\n')
prompts=[
 '请读取 AGENTS.md、指定 Skill 和 direction-candidate.json。程序已形成一个待决定的完整方向，我还没有看到它的说明。请向我说明当前需要决定的内容并等待我的后续答复。',
 '第二个独立的定点任务：当前小组件仍会接受结束不大于开始的区间。本次明确选择现有 test-first 路线，授权仅在此隔离工程修复这个真实业务缺陷并验证；合法返回与函数签名不变。使用指定解释器，不创建事项或执行Git交付，最后说明实际取得的开发反馈与限制。',
]
ids=['GF-CONFIRM-DIRECTION-EXPLANATION','GF-TEST-FEEDBACK']
dump(evidence/'registration.json',{'group':'G1-targeted-method-rechecks','case_ids':ids,'candidate':built,
    'fixed_inputs':prompts,'fixture_inputs':snapshot(project),'python':sys.executable,
    'scope':'first explanation and explicitly selected test-first route only',
    'model':'gemini-3.8-flash-low','author_timeout_seconds':[360,600],
    'prior_failed_review':'f891ecde76cd','owner_accepted':False,'os_isolation_verified':False})
sources={};case_outputs={}
for index,(identity,prompt) in enumerate(zip(ids,prompts),1):
    stage=evidence/f'turn-{index:02d}';stage.mkdir()
    (stage/'user-input.txt').write_text(prompt,encoding='utf-8')
    frozen=snapshot(project)
    allowed=set() if index==1 else {'src.py','tests/test_duration.py'}
    protected={name:digest for name,digest in frozen.items() if name not in allowed and '__pycache__' not in Path(name).parts and '.pytest_cache' not in Path(name).parts}
    for name in ['src.py','tests/test_duration.py','direction-candidate.json']:
        target=stage/'before'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((project/name).read_bytes())
        sources[f'before-{index}-{name}']={'path':str(target),'role':'original_input'}
    def observe():
        actual=snapshot(project)
        selected={name:digest for name,digest in actual.items() if name not in allowed and '__pycache__' not in Path(name).parts and '.pytest_cache' not in Path(name).parts}
        unchanged=selected==protected
        changed=index==1 or (project/'src.py').read_text(encoding='utf-8')!=source
        return {'reached':unchanged and changed,'protected_inputs_unchanged':unchanged,'requested_outputs_changed':changed,
                'semantic_acceptance':'pending independent native review'}
    receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
        evidence=stage/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',
        timeout=360 if index==1 else 600,max_continuations=0,permission_mode='auto_approve')
    (stage/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
    events=[json.loads(line) for line in (stage/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    dump(stage/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(stage/'endpoint.json',endpoint)
    sources[f'user-{index}']={'path':str(stage/'user-input.txt'),'role':'user_input'}
    sources[f'author-{index}']={'path':str(stage/'author-response.md'),'role':'author_response'}
    sources[f'tools-{index}']={'path':str(stage/'tool-steps.json'),'role':'author_artifact'}
    case_outputs[identity]=[f'author-{index}',f'tools-{index}']
    if not receipt['mechanical_passed'] or not endpoint['reached']:raise SystemExit('Targeted native phase did not settle')
    for name in ['src.py','tests/test_duration.py']:
        target=stage/'after'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((project/name).read_bytes())
        sources[f'after-{index}-{name}']={'path':str(target),'role':'author_artifact'}
        case_outputs[identity].append(f'after-{index}-{name}')
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
by_id={case['case_id']:case for case in catalog['cases']}
cases=[]
for identity in ids:
    cases.append({key:by_id[identity][key] for key in ['case_id','expected_behavior','must_avoid']}|{
        'evidence_source_ids':case_outputs[identity],
        'verification_scope':'初次说明和明确选择test-first的定点方法行为；保留原G1失败，不追认旧轨迹为通过，不证明新的完整Git交付或真人接受。红测必须来自真实业务断言且发生在源码修复前。',
        'machine_checks':{'native_phase_settled':True,'protected_inputs_unchanged':True}})
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
assert directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256']==built['skill_sha256']
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'group':'G1-targeted-method-rechecks','report_valid':review['execution']['report_valid'],
    'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
    'semantic_content_machine_proven':False,'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1)
