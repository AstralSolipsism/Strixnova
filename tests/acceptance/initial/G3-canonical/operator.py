"""Registered G3 development acceptance using the existing native drivers.

Copy this operator script into the new repository's artifacts before execution.
Run prepare and execute through local_validation with --keep-workspace --pin.
It never updates the acceptance catalog or manufactures a semantic verdict.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

import yaml

ROOT = Path.cwd().resolve()
sys.path.insert(0, str(ROOT))
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest


def dump(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def owned(path: Path) -> Path:
    resolved = path.resolve()
    if not resolved.is_relative_to(ROOT/'.artifacts'):
        raise ValueError('Acceptance artifacts must stay inside the registered repository artifacts')
    for node in (path, *path.parents):
        if node == ROOT:
            break
        if node.is_symlink() or node.is_junction():
            raise ValueError('Acceptance paths cannot follow links')
    return resolved


def snapshot(project: Path) -> dict[str,str]:
    return {p.relative_to(project).as_posix(): sha(p) for p in sorted(project.rglob('*'))
            if p.is_file() and '.git' not in p.relative_to(project).parts}


def candidate(path: Path) -> dict:
    value=json.loads(owned(path).read_text(encoding='utf-8'))
    wheel=owned(Path(value['wheel']))
    interpreter=owned(Path(value['installed_python']))
    if sha(wheel)!=value['wheel_sha256'] or not interpreter.is_file():
        raise ValueError('Candidate wheel or installed interpreter changed')
    if interpreter == Path(sys.executable).resolve():
        raise ValueError('Installed interpreter must be separate from source tests')
    result=subprocess.run([str(interpreter),'-I','-c',
        'import json;from strixnova.runtime_identity import runtime_identity;print(json.dumps(runtime_identity()))'],
        capture_output=True,check=True,text=True,encoding='utf-8',timeout=45)
    actual=json.loads(result.stdout)
    for field in ('build_sha256','skill_sha256'):
        if actual[field]!=value[field]:
            raise ValueError('Actual installed identity does not match registered candidate')
    return value


def prepare(args) -> None:
    work=owned(Path(os.environ['STRIXNOVA_VALIDATION_WORK']))
    evidence=owned(Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']))
    definition=json.loads(args.scenario.read_text(encoding='utf-8'))
    if definition['group_id']!='G3':raise ValueError('This operator script only implements G3')
    built=candidate(args.candidate)
    skill=owned(Path(built['installed_skill']))
    if directory_manifest(skill)['sha256']!=built['skill_sha256']:
        raise ValueError('Installed Skill does not match candidate')
    project=work/'project'
    project.mkdir(exist_ok=False)
    subprocess.run(['git','init','--quiet',str(project)],check=True,capture_output=True,timeout=30)
    shutil.copytree(skill,project/'.agents/skills/strixnova')
    for name,text in definition['initial_files'].items():
        target=project/name
        if not target.resolve().is_relative_to(project):raise ValueError('Input path outside fixture')
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(text,encoding='utf-8')
    (project/'AGENTS.md').write_text(
        '# 隔离发现讨论\n\n这是已登记的合成业务题面，仅使用本目录材料。'
        '按 .agents/skills/strixnova/SKILL.md 及适用参考开展用户请求；不读取父目录或其他项目，'
        '不调用子 Agent，不修改全局设置或安装工具。范围外未知按未知说明。'
        '本场景用户当前只授权分析，各条后续消息仍以实际内容为准。\n',encoding='utf-8')
    catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
    cases={c['case_id']:c for c in catalog['cases']}
    criteria=[{key:cases[identity][key] for key in ('case_id','expected_behavior','must_avoid')}
              for identity in definition['case_ids']]
    dump(work/'fixed-scenario.json',definition)
    dump(work/'criteria.json',criteria)
    registration={'project':str(project),'candidate':built,'candidate_manifest':str(args.candidate.resolve()),
        'scenario_sha256':sha(work/'fixed-scenario.json'),'criteria_sha256':sha(work/'criteria.json'),
        'initial_files':snapshot(project),'prepared_at':time.time(),
        'model':definition['author_model'],'reviewer_model':definition['reviewer_model'],
        'permission_mode':definition['permission_mode'],'os_isolation_verified':False,
        'owner_accepted':False,'status':'registered_not_executed'}
    dump(work/'registration.json',registration)
    dump(evidence/'registration.json',registration)
    print(json.dumps({'registration':str(work/'registration.json'),'status':'registered_not_executed'},ensure_ascii=False))


def execute(args) -> None:
    registration_path=owned(args.registration)
    work=registration_path.parent
    info=json.loads(registration_path.read_text(encoding='utf-8'))
    if (work/'execution-started.json').exists():raise ValueError('Registration already used; preserve original attempt')
    built=candidate(Path(info['candidate_manifest']))
    if built!=info['candidate']:raise ValueError('Registered candidate changed')
    definition=json.loads((work/'fixed-scenario.json').read_text(encoding='utf-8'))
    criteria=json.loads((work/'criteria.json').read_text(encoding='utf-8'))
    if sha(work/'fixed-scenario.json')!=info['scenario_sha256'] or sha(work/'criteria.json')!=info['criteria_sha256']:
        raise ValueError('Registered inputs changed')
    project=owned(Path(info['project']))
    if snapshot(project)!=info['initial_files']:raise ValueError('Initial fixture changed')
    evidence=owned(Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']))
    dump(work/'execution-started.json',{'evidence':str(evidence),'started_at':time.time()})
    source_entries={}; output_ids=[]; conversation=None; receipts=[]; endpoints=[]
    protected=dict(info['initial_files'])
    started=time.monotonic()
    for index,turn in enumerate(definition['turns'],1):
        if time.monotonic()-started>=definition['limits']['author_group_timeout_seconds']:
            raise TimeoutError('Registered group time limit reached')
        for name,text in turn.get('add_files',{}).items():
            target=project/name
            if not target.resolve().is_relative_to(project) or target.exists():
                raise ValueError('Current evidence must be a new declared fixture path')
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(text,encoding='utf-8')
            protected[name]=sha(target)
        stage=evidence/f'turn-{index:02d}'
        stage.mkdir()
        (stage/'user-input.txt').write_text(turn['input'],encoding='utf-8')
        dump(stage/'input-bindings.json',protected)
        source_entries[f'user-{index}']={'path':str(stage/'user-input.txt'),'role':'user_input'}
        def observe():
            unchanged=snapshot(project)==protected
            no_state=not (project/'.strixnova').exists()
            return {'reached':unchanged and no_state,'protected_fixture_unchanged':unchanged,
                'no_product_state_observed':no_state,'semantic_acceptance':'pending independent review'}
        prefix='请先读取本目录 AGENTS.md 和 .agents/skills/strixnova/SKILL.md，再处理下面的用户请求。\n\n' if index==1 else ''
        remaining=definition['limits']['author_group_timeout_seconds']-(time.monotonic()-started)
        receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',
            project=project,prompt=prefix+turn['input'],evidence=stage/'execution',observe_endpoint=observe,
            model=info['model'],conversation_id=conversation,
            timeout=min(definition['limits']['author_turn_timeout_seconds'],remaining),
            max_continuations=0,permission_mode=info['permission_mode'])
        response=receipt['last_result'].get('response','')
        (stage/'author-response.md').write_text(response,encoding='utf-8')
        stream=stage/'execution/events.jsonl'
        events=[json.loads(line) for line in stream.read_text(encoding='utf-8').splitlines() if line.strip()]
        dump(stage/'tool-steps.json',assess_turn(events)['tool_steps'])
        source_entries[f'author-{index}']={'path':str(stage/'author-response.md'),'role':'author_response'}
        source_entries[f'tools-{index}']={'path':str(stage/'tool-steps.json'),'role':'author_artifact'}
        output_ids += [f'author-{index}',f'tools-{index}']
        endpoint=observe();dump(stage/'endpoint.json',endpoint)
        receipts.append(receipt);endpoints.append(endpoint)
        if not receipt['mechanical_passed'] or not endpoint['reached']:
            dump(evidence/'group-incomplete.json',{'turn':index,'outcome':receipt['outcome'],'endpoint':endpoint,
                'semantic_content_machine_proven':False,'owner_accepted':False})
            raise RuntimeError('Native turn or fixture boundary did not settle; preserved original attempt')
        conversation=receipt['last_result']['conversation_id']
    for name in protected:
        if name.startswith('materials/'):
            source_entries[name]={'path':str(project/name),'role':'original_input'}
    current_skill=ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova'
    if directory_manifest(current_skill)['sha256']!=built['skill_sha256']:
        raise ValueError('Review Skill no longer matches frozen candidate')
    checks={'all_native_turns_settled':True,'registered_inputs_preserved':True,'no_product_state_observed':True}
    spec={'sources':source_entries,'cases':[dict(case,
        evidence_source_ids=output_ids,verification_scope=definition['scope'],machine_checks=checks) for case in criteria]}
    dump(evidence/'review-spec.json',spec)
    report=run_review(evidence/'review-spec.json',evidence/'independent-review',
        timeout=definition['limits']['independent_review_timeout_seconds'])
    if directory_manifest(current_skill)['sha256']!=built['skill_sha256']:
        raise ValueError('Review source Skill changed during execution')
    summary={'group':'G3','case_ids':definition['case_ids'],'native_turn_count':len(receipts),
        'review_report_valid':report['execution']['report_valid'],
        'cases':[{key:item[key] for key in ('case_id','verdict')} for item in report['cases']],
        'machine_checks':checks,'owner_accepted':False,'os_isolation_verified':False,
        'semantic_content_machine_proven':False,'acceptance_catalog_updated':False}
    dump(evidence/'group-summary.json',summary)
    print(json.dumps(summary,ensure_ascii=False))
    if not report['execution']['report_valid'] or any(item['summary']['status']!='passed' for item in report['cases']):
        raise SystemExit(1)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    phases=parser.add_subparsers(dest='phase',required=True)
    prep=phases.add_parser('prepare')
    prep.add_argument('--candidate',type=Path,required=True)
    prep.add_argument('--scenario',type=Path,required=True)
    run=phases.add_parser('execute')
    run.add_argument('--registration',type=Path,required=True)
    args=parser.parse_args()
    if args.phase=='prepare':prepare(args)
    else:execute(args)
