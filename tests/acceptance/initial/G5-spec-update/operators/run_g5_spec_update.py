"""Two declared documentation-input changes; no fabricated workflow acceptance."""
from pathlib import Path
import copy
import json
import os
import shutil
import subprocess
import sys
import yaml

ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,snapshot,sha
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review

work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
project=work/'project';project.mkdir();subprocess.run(['git','init','--quiet',str(project)],check=True,capture_output=True)
built=candidate(ROOT/'.artifacts/candidates/initial-guidance/candidate.json')
shutil.copytree(Path(built['installed_skill']),project/'.agents/skills/strixnova')
(project/'inputs').mkdir();(project/'docs/reading').mkdir(parents=True)
base=ROOT/'.artifacts/validation/6ea564151824/work/project'
shutil.copyfile(base/'inputs/recorded-work-item.json',project/'inputs/recorded-work-item.json')
shutil.copyfile(base/'docs/reading/SPEC.md',project/'docs/reading/SPEC.md')
shutil.copyfile(project/'docs/reading/SPEC.md',evidence/'initial-SPEC.md')
history=json.loads((project/'inputs/recorded-work-item.json').read_text(encoding='utf-8'))['history']
decisions=history['records']['decisions']
original_direction=decisions['direction'];original_plan=decisions['engineering']['plan']
proposal=copy.deepcopy(original_direction)
proposal['goal']='在保留区间顺序校验与函数签名的前提下增加单次区间不超过480分钟的候选规则。'
proposal['scope'][1]['statement']='合法区间长度不超过480分钟时仍返回 end-start，函数签名不变。'
proposal['scope'].append({'requirement_id':'DIRREQ-18293A4B5C6D7E8F','statement':'正区间长度大于480分钟时抛出ValueError；恰好480分钟仍接受。'})
proposal['acceptance'][0]['statement']='结束不晚于开始或正区间长度大于480分钟时抛出ValueError；其余正区间返回end-start。'
proposal['acceptance'][0]['requirement_refs'].append('DIRREQ-18293A4B5C6D7E8F')
proposal['acceptance'][0]['behavior']['examples'].extend([
 {'example_id':'DIREX-18293A4B5C6D7E8F','title':'恰好上限仍接受','basis_refs':['direction.requirement:DIRREQ-18293A4B5C6D7E8F'],'given':['start=20','end=500'],'when':'调用duration(20,500)','then':['返回480']},
 {'example_id':'DIREX-293A4B5C6D7E8F90','title':'超过上限拒绝','basis_refs':['direction.requirement:DIRREQ-18293A4B5C6D7E8F'],'given':['start=20','end=501'],'when':'调用duration(20,501)','then':['抛出ValueError']},
])
views=[
 {'scenario_kind':'synthetic_progress_only_projection','work_item_id':history['work_item']['work_item_id'],
  'aggregate_version':20,'status':'completed','progress_note':'控制器预设的投影版本变动，用于文档回归；不是真实事项新增事件。',
  'direction_version':3,'direction':original_direction,'engineering_plan':original_plan,
  'direction_fingerprint':decisions['direction_confirmation']['candidate_fingerprint'],
  'plan_fingerprint':decisions['engineering']['plan_confirmation']['candidate_fingerprint'],
  'semantic_sources_changed':False,'owner_accepted_by_this_input':False},
 {'scenario_kind':'synthetic_unaccepted_direction_revision','work_item_id':history['work_item']['work_item_id'],
  'aggregate_version':21,'direction_version':4,'direction_candidate':proposal,'candidate_status':'draft',
  'accepted_baseline_direction_version':3,'previous_engineering_plan':original_plan,
  'engineering_plan_disposition':'原方案尚未为上限规则重评；新行为的实现、覆盖和接受均待完成。',
  'semantic_sources_changed':True,'owner_accepted_by_this_input':False},
]
prompts=[
 '读取AGENTS与指定Skill。inputs/source-view.json是预先声明的显示层进度回归夹具：事项总版本变化，但原方向与工程方案内容、身份、确认完全未变。请对照真实基线记录判断SPEC应如何更新，仅在有必要时修改docs/reading/SPEC.md，并解释规格依据是否变化。不要把合成进度当真实工作流事件或新的接受。',
 '现已换入第二份预先声明的来源：同一稳定事项的未接受方向候选第4版，实际新增480分钟上限并保留其他稳定身份；原工程方案尚未为新规则重评。请更新SPEC的受影响正文、来源绑定和行为覆盖，区分既有已确认基线与当前未接受候选，保留不受影响身份，并说明旧方案处置和缺口。不要创造已执行测试、新方案或接受记录；仅修改阅读产物。',
]
(project/'AGENTS.md').write_text(f'''# 固定文档变更回归

使用 .agents/skills/strixnova/SKILL.md。inputs/recorded-work-item.json 和初始SPEC来自本轮实际G1记录；source-view.json是明确登记的合成文档输入变化，不是程序写入、负责人接受或新的真实事件。只有docs/reading/SPEC.md可写；不得修改输入、建立事项、运行产品或Git交付，不读取父目录、不调用子Agent。所有Python必须用{sys.executable}，禁止裸python/python3和安装软件。
''',encoding='utf-8')
dump(evidence/'registration.json',{'case_id':'GF-SPEC-UPDATE','candidate':built,'fixed_inputs':prompts,
 'fixed_source_views':views,'synthetic_delta_disclosed':True,'owner_accepted':False,'os_isolation_verified':False,
 'source_origin_run':'6ea564151824','phase_timeouts':[420,600]})
shutil.copyfile(__file__,evidence/'operator-source.py')
sources={'baseline-history':{'path':str(project/'inputs/recorded-work-item.json'),'role':'original_input'},
         'initial-spec':{'path':str(evidence/'initial-SPEC.md'),'role':'original_input'}}
outputs=[];conversation=None
for index,(view,prompt) in enumerate(zip(views,prompts),1):
    stage=evidence/f'turn-{index:02d}';stage.mkdir()
    dump(project/'inputs/source-view.json',view);dump(stage/'source-view.json',view)
    (stage/'user-input.txt').write_text(prompt,encoding='utf-8')
    protected=snapshot(project);protected.pop('docs/reading/SPEC.md')
    def observe():
        current=snapshot(project);current.pop('docs/reading/SPEC.md',None)
        return {'reached':current==protected,'inputs_unchanged':current==protected}
    receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
      evidence=stage/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',conversation_id=conversation,
      timeout=[420,600][index-1],max_continuations=0,permission_mode='auto_approve')
    (stage/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
    events=[json.loads(line) for line in (stage/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    dump(stage/'tool-steps.json',assess_turn(events)['tool_steps']);dump(stage/'endpoint.json',observe())
    shutil.copyfile(project/'docs/reading/SPEC.md',stage/'SPEC.md')
    for name,role in [('source-view.json','original_input'),('user-input.txt','user_input'),('author-response.md','author_response'),('tool-steps.json','author_artifact'),('SPEC.md','author_artifact')]:
        key=f'turn-{index}/{name}';sources[key]={'path':str(stage/name),'role':role}
        if role.startswith('author_'):outputs.append(key)
    if not receipt['mechanical_passed'] or not observe()['reached']:raise SystemExit('Native source-update phase did not settle')
    conversation=receipt['last_result']['conversation_id']
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-SPEC-UPDATE')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'真实基线记录之上的两个公开合成文档输入变更：仅进度与未接受方向修订；不证明工作流新事件、实现或负责人接受。',
 'machine_checks':{'native_phases_settled':True,'frozen_inputs_unchanged':True}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
