"""Two fixed native code-review turns; fixture edits are controller inputs."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys

import yaml

ROOT=Path.cwd().resolve()
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'.artifacts/acceptance/initial'))
from run_initial_discovery_acceptance import candidate, dump, snapshot, owned
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest

GOOD='''def duration(start: int, end: int) -> int:
    if end <= start:
        raise ValueError("end must be greater than start")
    return end - start
'''
BAD=GOOD.replace('return end - start','return start - end')
WORKING=BAD.replace('    return start - end','    print("debug", start, end)\n    return start - end')
FIRST='请按 review-base 到当前工作树的完整范围做只读代码审阅：范围包括该点之后已提交的变化、未提交变化和未跟踪的新文件。先读取 requirements.md 与 standards.md，再核对实际代码；报告确实可行动的需求或规范问题及依据。不要修代码，不创建建设事项。'
SECOND='夹具已提供修正后的实际代码。请重新读取并审阅 review-base 到当前工作树的同一完整范围，逐项核对先前问题是否仍存在。只有当前还有问题才报告；没有可行动问题就明确说明，不为凑数提出改动。仍只读，不创建建设事项。'
CASES=['GF-CODE-REVIEW-SCOPE','GF-CODE-REVIEW-CORRECTION']


def main():
    work=owned(Path(os.environ['STRIXNOVA_VALIDATION_WORK']))
    evidence=owned(Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']))
    built=candidate(ROOT/'.artifacts/candidates/initial-canonical/candidate.json')
    project=work/'project';project.mkdir(exist_ok=False)
    def git(*args):
        return subprocess.run(['git','--no-optional-locks',*args],cwd=project,check=True,
            capture_output=True,text=True,encoding='utf-8',timeout=30).stdout
    git('init','--quiet','-b','main')
    git('config','user.name','Strixnova Acceptance Fixture')
    git('config','user.email','fixture@example.invalid')
    git('config','core.fsmonitor','false')
    git('config','core.autocrlf','false')
    files={
        '.gitignore':'.agents/\n__pycache__/\n',
        '.gitattributes':'* text=auto eol=lf\n',
        'AGENTS.md':'# 隔离代码审阅\n\n这是登记的合成业务代码对照，只读取本目录的代码、需求、规范和 Git 比较范围。遵循 .agents/skills/strixnova/SKILL.md 的适用审阅方法。不修改文件或 Git 状态，不执行代码、不安装软件、不创建事项，不访问父目录或其他项目，不调用子 Agent。\n',
        'requirements.md':'# 预约时长小组件\n\n这是隔离验收的合成需求。调用方提供整数分钟刻度。duration(start, end) 在 end 严格大于 start 时返回正的 end-start；不合法顺序抛出 ValueError。此变更新增 reservation_limits.py，以 MAX_RESERVATION_MINUTES=120 暴露配置常量；本次不要求 duration 执行该上限，也不增加类型或日期格式转换。\n',
        'standards.md':'# 本项目规范\n\n库函数不得向标准输出写诊断或调试信息。审阅应对照实际需求与当前候选，指出可行动缺陷；不要求重构既有正确代码，不把历史上已修复的问题继续报作当前缺陷。\n',
        'src.py':GOOD,
    }
    for name,body in files.items():(project/name).write_text(body,encoding='utf-8')
    git('add','--',*files)
    git('commit','--quiet','-m','base fixture')
    git('tag','review-base')
    base_commit=git('rev-parse','HEAD').strip()
    (project/'src.py').write_text(BAD,encoding='utf-8')
    git('add','--','src.py');git('commit','--quiet','-m','committed candidate fixture')
    (project/'src.py').write_text(WORKING,encoding='utf-8')
    (project/'reservation_limits.py').write_text('MAX_RESERVATION_MINUTES = 60\n',encoding='utf-8')
    shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova')
    def git_state():
        return {'head':git('rev-parse','HEAD').strip(),'index':git('ls-files','--stage','-z'),
                'references':git('show-ref')}
    locked_git=git_state()
    catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
    criteria={case['case_id']:case for case in catalog['cases'] if case['case_id'] in CASES}
    dump(evidence/'registration.json',{'group':'G6','case_ids':CASES,'candidate':built,
        'base_commit':base_commit,'git_state':locked_git,'initial_files':snapshot(project),
        'fixed_inputs':[FIRST,SECOND],'fixed_correction':{'src.py':GOOD,'reservation_limits.py':'MAX_RESERVATION_MINUTES = 120\n'},
        'correction_actor':'controller fixture update; not evidence of Agent implementation',
        'author_model':'gemini-3.8-flash-low','reviewer_model':'gemini-3.8-flash-low',
        'permission_mode':'auto_approve','author_turn_timeout_seconds':360,'max_continuations':0,
        'review_timeout_seconds':600,'os_isolation_verified':False,'owner_accepted':False})
    print('Registered fixed G6 inputs and actual Git comparison states.',flush=True)
    sources={};case_outputs={};conversation=None
    for index,prompt in enumerate([FIRST,SECOND],1):
        if index==2:
            (project/'src.py').write_text(GOOD,encoding='utf-8')
            (project/'reservation_limits.py').write_text('MAX_RESERVATION_MINUTES = 120\n',encoding='utf-8')
        stage=evidence/f'turn-{index:02d}';stage.mkdir()
        frozen=snapshot(project)
        dump(stage/'input-bindings.json',frozen)
        (stage/'user-input.txt').write_text(prompt,encoding='utf-8')
        sources[f'user-{index}']={'path':str(stage/'user-input.txt'),'role':'user_input'}
        inputs=stage/'inputs';inputs.mkdir()
        for name in ['src.py','reservation_limits.py','requirements.md','standards.md']:
            shutil.copyfile(project/name,inputs/name)
            sources[f'input-{index}-{name}']={'path':str(inputs/name),'role':'original_input'}
        (inputs/'comparison.diff').write_text(git('diff','review-base','--'),encoding='utf-8')
        sources[f'comparison-{index}']={'path':str(inputs/'comparison.diff'),'role':'original_input'}
        def observe():
            unchanged=snapshot(project)==frozen
            git_unchanged=git_state()==locked_git
            return {'reached':unchanged and git_unchanged,'input_files_unchanged':unchanged,
                    'logical_git_state_unchanged':git_unchanged,'semantic_acceptance':'pending independent native review'}
        prefix='先读取 AGENTS.md 和 .agents/skills/strixnova/SKILL.md，再处理用户请求。\n\n' if index==1 else ''
        receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',
            project=project,prompt=prefix+prompt,evidence=stage/'execution',observe_endpoint=observe,
            model='gemini-3.8-flash-low',conversation_id=conversation,timeout=360,
            max_continuations=0,permission_mode='auto_approve')
        (stage/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
        events=[json.loads(line) for line in (stage/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        dump(stage/'tool-steps.json',assess_turn(events)['tool_steps'])
        endpoint=observe();dump(stage/'endpoint.json',endpoint)
        sources[f'author-{index}']={'path':str(stage/'author-response.md'),'role':'author_response'}
        sources[f'tools-{index}']={'path':str(stage/'tool-steps.json'),'role':'author_artifact'}
        case_outputs[CASES[index-1]]=[f'author-{index}',f'tools-{index}']
        if not receipt['mechanical_passed'] or not endpoint['reached']:
            raise RuntimeError('Native review turn or readonly boundary did not settle; preserve this attempt')
        conversation=receipt['last_result']['conversation_id']
    skill=ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova'
    assert directory_manifest(skill)['sha256']==built['skill_sha256']
    spec={'sources':sources,'cases':[{**{key:criteria[identity][key] for key in ['case_id','expected_behavior','must_avoid']},
        'evidence_source_ids':case_outputs[identity],
        'verification_scope':'两套真实字节及同一完整 Git 比较范围下的只读审阅行为；修正由固定夹具步骤提供，不证明 Agent 自主实施或负责人接受。',
        'machine_checks':{'native_turns_settled':True,'inputs_and_logical_git_state_unchanged':True}}
        for identity in CASES]}
    dump(evidence/'review-spec.json',spec)
    review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
    assert directory_manifest(skill)['sha256']==built['skill_sha256']
    summary={'group':'G6','case_ids':CASES,'review_report_valid':review['execution']['report_valid'],
        'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
        'semantic_content_machine_proven':False,'owner_accepted':False,'os_isolation_verified':False,
        'acceptance_catalog_updated':False}
    dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
    return 0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1


if __name__=='__main__':raise SystemExit(main())
