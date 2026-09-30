"""Actual PRD/domain reading outputs from frozen current design sources."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import sys
import hashlib
import yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate, dump, snapshot
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest

work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']).resolve()
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']).resolve()
assert work.is_relative_to(ROOT/'.artifacts/validation')
built=candidate(ROOT/'.artifacts/candidates/initial-canonical/candidate.json')
project=work/'project';project.mkdir()
subprocess.run(['git','init','--quiet',str(project)],check=True,capture_output=True)
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova')
source_paths=[]
for folder in ['docs/product','docs/domain','docs/architecture']:
    source_paths.extend(sorted((ROOT/folder).rglob('*.yaml')))
source_paths.append(ROOT/'docs/engineering/policy.yaml')
for path in source_paths:
    relative=path.relative_to(ROOT)
    target=project/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(path,target)
(project/'AGENTS.md').write_text('''# 冻结阅读验收

仅在本目录读取提供的当前候选，按 .agents/skills/strixnova/SKILL.md 的适用方法形成阅读文档。来源仍是各自权威，草稿不等于采用。本场景不使用程序管理其自身，不运行业务CLI、不创建事项、不修改任何来源；只允许生成 docs/reading/PRD.md 与 docs/reading/DOMAIN.md。不要访问父目录或其他项目，不安装软件，不调用子Agent。
''',encoding='utf-8',newline='\n')
outputs=['docs/reading/PRD.md','docs/reading/DOMAIN.md']
(project/'docs/reading').mkdir(parents=True)
prompt='请先读取 AGENTS.md 和指定 Skill。资料已经足够，不需要重新访谈。请以当前产品定义、完整领域来源、目标架构和工程政策为依据，实际生成 docs/reading/PRD.md 与 docs/reading/DOMAIN.md，供项目负责人连续阅读。保留来源状态、稳定身份、关系、场景、限制、例外与未决边界；阅读文档不成为第二份权威，也不声称实现或采用已经完成。不要修改来源或创建建设事项。完成两个文件后说明实际范围与限制并停止。'
fixed=snapshot(project)
registration={'group':'G5-reading','case_ids':['GF-PRD-READING','GF-DOMAIN-READING'],'candidate':built,
    'input_files':fixed,'source_paths':[path.relative_to(ROOT).as_posix() for path in source_paths],
    'prompt':prompt,'allowed_outputs':outputs,'author_model':'gemini-3.8-flash-low',
    'reviewer_model':'gemini-3.8-flash-low','author_timeout_seconds':900,'review_timeout_seconds':900,
    'permission_mode':'auto_approve','os_isolation_verified':False,'actual_owner_accepted':False}
dump(evidence/'registration.json',registration)
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
def observe():
    actual=snapshot(project)
    remaining={name:digest for name,digest in actual.items() if name not in outputs}
    unchanged=remaining==fixed
    present=all((project/name).is_file() and (project/name).stat().st_size>0 for name in outputs)
    return {'reached':unchanged and present,'frozen_inputs_unchanged':unchanged,'both_outputs_present':present,
            'semantic_acceptance':'pending independent native review'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=registration['author_model'],timeout=900,
    max_continuations=1,new_output_paths=tuple(project/name for name in outputs),permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps'])
endpoint=observe();dump(evidence/'endpoint.json',endpoint)
if not receipt['mechanical_passed'] or not endpoint['reached']:
    raise SystemExit('Native author or input boundary incomplete; retain original evidence')
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
criteria={row['case_id']:row for row in catalog['cases']}
sources={path.relative_to(ROOT).as_posix():{'path':str(project/path.relative_to(ROOT)),'role':'original_input'} for path in source_paths}
sources['request']={'path':str(evidence/'user-input.txt'),'role':'user_input'}
sources['response']={'path':str(evidence/'author-response.md'),'role':'author_response'}
sources['tools']={'path':str(evidence/'tool-steps.json'),'role':'author_artifact'}
sources['prd']={'path':str(project/outputs[0]),'role':'author_artifact'}
sources['domain']={'path':str(project/outputs[1]),'role':'author_artifact'}
assert directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256']==built['skill_sha256']
cases=[]
for identity,output in [('GF-PRD-READING','prd'),('GF-DOMAIN-READING','domain')]:
    row=criteria[identity]
    cases.append({key:row[key] for key in ['case_id','expected_behavior','must_avoid']} | {
        'evidence_source_ids':[output,'response','tools'],
        'verification_scope':'当前完整草稿材料的实际阅读投影及来源忠实性；不证明权威采用、代码实现或负责人接受。现有模型没有历史墓碑，应诚实保留该状态，不新增谱系。',
        'machine_checks':{'native_author_settled':True,'frozen_sources_unchanged':True,'outputs_created':True}})
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'group':'G5-reading','review_report_valid':review['execution']['report_valid'],
    'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
    'semantic_content_machine_proven':False,'actual_owner_accepted':False,'acceptance_catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1)
