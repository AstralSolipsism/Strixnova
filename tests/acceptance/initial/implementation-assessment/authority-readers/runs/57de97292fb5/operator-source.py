"""Clarify copied-source navigation and output shape; preserve the first candidate."""
from pathlib import Path
import json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
previous=ROOT/'.artifacts/validation/6e4aa44bb8e3/evidence'
info=json.loads((ROOT/'.artifacts/validation/30d2bb4dd8d8/work/registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);packet=json.loads((project/'inputs/packet.json').read_text(encoding='utf-8'))
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
shutil.copyfile(project/'assessment.json',evidence/'previous-assessment.json')
shutil.copyfile(__file__,evidence/'operator-source.py')
prompt=('上一轮候选与原始错误已保存。补充明确两个包装约束：packet中的原仓库相对路径，在此冻结工程实际位于 inputs/files/ 下，不能按工程根直接拼路径；'
 'resolution_plan必须是字符串数组，单条计划也用数组。目标合同、原代码、断言和结果数据均未改变。'
 '请核对实际存在的冻结来源路径，修正assessment.json的结构，并复核原结论；不预设implemented，也不为通过改变评价标准。'
 '只写assessment.json，不运行产品或测试。任何Python解析必须用完整路径 D:\\AboutDEV\\Strixnova\\.venv\\Scripts\\python.exe。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{**info,'previous_attempt':'6e4aa44bb8e3','fixed_correction':prompt})
protected=snapshot(project);protected.pop('assessment.json')
ids=set(info['target_ids']);owned={r['path']:r['target_module_id'] for t in packet['targets'] for r in t['ownership_candidates']}
def inspect():
    actual=snapshot(project);actual.pop('assessment.json',None);stable=actual==protected
    try:
        x=json.loads((project/'assessment.json').read_text(encoding='utf-8-sig'))
        complete=len(x['assessments'])==len(ids) and {r['target_id'] for r in x['assessments']}==ids and len(x['source_ownership'])==len(owned) and {r['path'] for r in x['source_ownership']}==set(owned)
        shape=all(r['target_kind']=='module' and r['status'] in {'implemented','partially_implemented','not_implemented','unknown'} and all(isinstance(r[k],list) for k in ['satisfied','missing','evidence','resolution_plan','limitations']) and r['evidence'] for r in x['assessments'])
        shape=shape and all(r['target_module_id']==owned[r['path']] and r['current_status'] in {'aligned','partially_aligned','drifted','unknown','not_applicable'} for r in x['source_ownership'])
        shape=bool(shape and x['owner_accepted'] is False and x['semantic_content_machine_proven'] is False)
        return {'reached':stable and complete and shape,'inputs_unchanged':stable,'target_and_source_coverage_complete':complete,'output_shape_valid':shape}
    except (KeyError,ValueError,TypeError):return {'reached':False,'inputs_unchanged':stable}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=inspect,model=info['author_model'],
 conversation_id='81519713-fe65-40c9-ba4f-bdf553cf6814',timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(s) for s in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=inspect();dump(evidence/'endpoint.json',endpoint)
shutil.copyfile(project/'assessment.json',evidence/'assessment.json')
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
# Reuse the original bounded review construction, not a second review engine.
operator=(ROOT/'.artifacts/acceptance/initial/run_target_module_assessment.py').read_text(encoding='utf-8')
marker="sources={'packet':"
assert operator.count(marker)==1
review_tail=marker+operator.split(marker,1)[1]
exec(compile(review_tail,str(ROOT/'.artifacts/acceptance/initial/run_target_module_assessment.py'),'exec'),globals())
