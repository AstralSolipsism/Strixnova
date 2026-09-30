"""Limited repeat with the repository's explicit interpreter constraint."""
from pathlib import Path
import json
import os
import re
import sys
import yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump, snapshot
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest
prior=ROOT/'.artifacts/validation/b609dc22a9dd'
project=prior/'work/project';evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
registration=json.loads((prior/'evidence/registration.json').read_text(encoding='utf-8'))
receipt=json.loads((prior/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert receipt['mechanical_passed']
outputs=registration['allowed_outputs']
previous=evidence/'previous';previous.mkdir()
for name in outputs:
    target=previous/Path(name).name;target.write_bytes((project/name).read_bytes())
(previous/'AGENTS.md').write_bytes((project/'AGENTS.md').read_bytes())
addition=f'\n执行环境：所有 Python 命令必须明确使用 `{sys.executable}`，禁止裸调用 python/python3，不安装或修改系统 Python。\n'
with (project/'AGENTS.md').open('a',encoding='utf-8',newline='\n') as target:target.write(addition)
protected={name:digest for name,digest in snapshot(project).items() if name not in outputs}
prompt=f'执行约束补充，不包含新的业务决定或任何接受：本项目所有 Python 命令必须明确使用 {sys.executable}，不得裸调用 python/python3。原始文档和执行记录已另存。请重新读取更新后的 AGENTS.md，在同一来源、相同覆盖范围和输出位置重新形成 PRD.md 与 DOMAIN.md，并核对稳定身份、草稿状态和全部重要限制；不要修改来源、增加事实或创建事项。如果使用 Python 辅助生成，使用上述解释器。完成后说明实际执行与限制并停止。'
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{'scope':'same reading requirements; explicit Python constraint added after recorded harness omission',
    'prior_run':'b609dc22a9dd','candidate':registration['candidate'],'python':sys.executable,
    'fixed_input':prompt,'protected_inputs':protected,'allowed_outputs':outputs,
    'model':registration['author_model'],'owner_accepted':False,'os_isolation_verified':False})
def observe():
    actual=snapshot(project)
    unchanged={name:digest for name,digest in actual.items() if name not in outputs}==protected
    return {'reached':unchanged and all((project/name).is_file() for name in outputs),
            'inputs_unchanged':unchanged,'semantic_acceptance':'pending independent native review'}
executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=registration['author_model'],
    conversation_id=receipt['last_result']['conversation_id'],timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
steps=assess_turn(events)['tool_steps'];dump(evidence/'tool-steps.json',steps)
bare=[]
for step in steps:
    command=str((step.get('tool_info',{}).get('parameters')or{}).get('CommandLine',''))
    if re.search(r'(?im)(?:^|[;\n])\s*(?:&\s*)?python(?:3)?(?:\s|$)',command):bare.append(command)
endpoint=observe();dump(evidence/'endpoint.json',endpoint)
dump(evidence/'python-boundary.json',{'bare_python_commands':bare,'expected_interpreter':sys.executable,
    'scope':'recorded terminal commands, not arbitrary OS isolation'})
if not executed['mechanical_passed'] or not endpoint['reached'] or bare:raise SystemExit('Constrained reading execution incomplete')
sources={path:{'path':str(project/path),'role':'original_input'} for path in registration['source_paths']}
sources['request']={'path':str(prior/'evidence/user-input.txt'),'role':'user_input'}
sources['environment-correction']={'path':str(evidence/'user-input.txt'),'role':'user_input'}
sources['response']={'path':str(evidence/'author-response.md'),'role':'author_response'}
sources['tools']={'path':str(evidence/'tool-steps.json'),'role':'author_artifact'}
sources['prd']={'path':str(project/outputs[0]),'role':'author_artifact'}
sources['domain']={'path':str(project/outputs[1]),'role':'author_artifact'}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
by_id={row['case_id']:row for row in catalog['cases']}
cases=[]
for identity,name in [('GF-PRD-READING','prd'),('GF-DOMAIN-READING','domain')]:
    cases.append({key:by_id[identity][key] for key in ['case_id','expected_behavior','must_avoid']}|{
        'evidence_source_ids':[name,'response','tools'],
        'verification_scope':'同一完整草稿来源的实际阅读投影；本次补齐明确Python执行约束，保留首次记录，不证明代码实施或真人接受。来源没有历史墓碑，不应新增谱系。',
        'machine_checks':{'native_author_settled':True,'frozen_sources_unchanged':True,'no_bare_python_command_observed':True}})
spec=evidence/'review-spec.json';dump(spec,{'sources':sources,'cases':cases})
assert directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256']==registration['candidate']['skill_sha256']
review=run_review(spec,evidence/'independent-review',timeout=900)
summary={'group':'G5-reading-constrained','report_valid':review['execution']['report_valid'],
    'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
    'semantic_content_machine_proven':False,'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1)
