"""Native SPEC projection and read-only PRD review on actual frozen records."""
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
input_root=project/'inputs';input_root.mkdir()
history=ROOT/'.artifacts/validation/f891ecde76cd/evidence/recorded-history.json'
shutil.copyfile(history,input_root/'recorded-work-item.json')
old_project=ROOT/'.artifacts/validation/b609dc22a9dd/work/project'
shutil.copytree(old_project/'docs',input_root/'project-docs')
(project/'docs/reading').mkdir(parents=True)
(project/'AGENTS.md').write_text(f'''# 冻结文档工作

按 .agents/skills/strixnova/SKILL.md 的适用方法，仅使用本目录材料。inputs/recorded-work-item.json 是已真实记录的固定隔离事项历史，inputs/project-docs 是另一组完整草稿阅读材料；二者分别标明来源和状态，不混为同一产品。只允许创建 docs/reading/SPEC.md；PRD审阅只在答复中报告，不修改PRD或任何输入。不创建事项或使用程序管理自身，不访问父目录，不调用子Agent。所有Python命令明确使用 {sys.executable}，禁止裸python/python3，不安装软件。
''',encoding='utf-8',newline='\n')
prompts=[
 '读取 AGENTS.md 与指定 Skill。请根据 inputs/recorded-work-item.json 中实际已记录的方向、方案、来源与版本，在 docs/reading/SPEC.md 形成一份可阅读的工程规格。明确需求、约束、验收与方案处置，区分行为与技术实现，准确绑定稳定身份。事项已经执行的进度只作进度事实，不替代规格含义或原确认；不创造第二份权威，不修改输入。完成文档后说明范围与限制。',
 '第二个独立只读任务：请对 inputs/project-docs/reading/PRD.md 作实际内容审阅，对照它所引用的完整产品、领域、目标架构及工程政策草稿。核查具体取舍、可判断完成条件、遗漏、冲突和候选状态，说明问题或无可行动问题的依据及影响。不要只核对标题，不修改文档，不把草稿当已采用，也不把未知判为就绪。',
]
ids=['GF-SPEC-READING','GF-PRD-REVIEW']
dump(evidence/'registration.json',{'group':'G5-spec-and-prd-review','case_ids':ids,'candidate':built,
    'fixed_inputs':prompts,'initial_files':snapshot(project),'python':sys.executable,
    'author_model':'gemini-3.8-flash-low','reviewer_model':'gemini-3.8-flash-low',
    'timeout_seconds':[600,600],'owner_accepted':False,'os_isolation_verified':False})
sources={};case_outputs={};conversation=None
protected=snapshot(project)
for index,(identity,prompt) in enumerate(zip(ids,prompts),1):
    stage=evidence/f'turn-{index:02d}';stage.mkdir()
    (stage/'user-input.txt').write_text(prompt,encoding='utf-8')
    def observe():
        actual=snapshot(project)
        if index==1:actual.pop('docs/reading/SPEC.md',None)
        unchanged=actual==protected
        exists=(project/'docs/reading/SPEC.md').is_file()
        return {'reached':unchanged and exists,'input_files_unchanged':unchanged,
                'semantic_acceptance':'pending independent native review'}
    receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
        evidence=stage/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',
        conversation_id=conversation,timeout=600,max_continuations=0,permission_mode='auto_approve',
        new_output_paths=(project/'docs/reading/SPEC.md',) if index==1 else ())
    (stage/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
    events=[json.loads(line) for line in (stage/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    dump(stage/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(stage/'endpoint.json',endpoint)
    if not receipt['mechanical_passed'] or not endpoint['reached']:raise SystemExit('Native document phase did not settle')
    sources[f'user-{index}']={'path':str(stage/'user-input.txt'),'role':'user_input'}
    sources[f'author-{index}']={'path':str(stage/'author-response.md'),'role':'author_response'}
    sources[f'tools-{index}']={'path':str(stage/'tool-steps.json'),'role':'author_artifact'}
    case_outputs[identity]=[f'author-{index}',f'tools-{index}']
    conversation=receipt['last_result']['conversation_id'];protected=snapshot(project)
sources['recorded-work-item']={'path':str(input_root/'recorded-work-item.json'),'role':'original_input'}
for path in sorted((input_root/'project-docs').rglob('*')):
    if path.is_file() and path.suffix in {'.yaml','.md'}:
        sources['original/'+path.relative_to(input_root).as_posix()]={'path':str(path),'role':'original_input'}
sources['spec']={'path':str(project/'docs/reading/SPEC.md'),'role':'author_artifact'}
case_outputs['GF-SPEC-READING'].append('spec')
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
by_id={row['case_id']:row for row in catalog['cases']}
cases=[]
for identity in ids:
    cases.append({key:by_id[identity][key] for key in ['case_id','expected_behavior','must_avoid']}|{
        'evidence_source_ids':case_outputs[identity],
        'verification_scope':'真实固定事项记录的规格阅读投影，以及完整草稿PRD的实际只读内容审阅；两套来源独立，不证明新的业务实施或真人接受。',
        'machine_checks':{'native_phase_settled':True,'inputs_unchanged':True}})
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
assert directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256']==built['skill_sha256']
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'group':'G5-spec-and-prd-review','report_valid':review['execution']['report_valid'],
    'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
    'semantic_content_machine_proven':False,'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1)
