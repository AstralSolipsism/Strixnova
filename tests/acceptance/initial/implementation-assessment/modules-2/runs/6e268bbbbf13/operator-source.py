"""Complete unread responsibility evidence and obey the existing ledger schema."""
from pathlib import Path
import json,os,shutil,sys
from jsonschema import Draft202012Validator
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
info=json.loads((ROOT/'.artifacts/validation/ce36d674de61/work/registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);packet=json.loads((project/'inputs/packet.json').read_text(encoding='utf-8'))
previous=ROOT/'.artifacts/validation/253b96a75ac0/evidence';evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
prior=json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'))
review=json.loads((previous/'independent-review/review.json').read_text(encoding='utf-8'))
shutil.copyfile(project/'assessment.json',evidence/'previous-assessment.json');shutil.copyfile(previous/'independent-review/review.json',evidence/'previous-review.json')
schema=json.loads((ROOT/'strixnova/src/strixnova/resources/project-implementation-alignment-v1.schema.json').read_text(encoding='utf-8'))
validator=Draft202012Validator({'$schema':schema['$schema'],'$ref':'#/$defs/responsibility_record','$defs':schema['$defs']})
feedback='''独立复核保留了跨权威检查和命令适配的代码结论，但拒绝直接认定应用协调器完整：你承认未读4个关键支持实现及behavior-examples.md，多项归属仍unknown。请在同一冻结材料中实际阅读这些实现和关键阻断路径后再评价，不能只根据委托调用推断完整实现；如果预算内证据仍不足，保留unknown/部分及具体未核实点。
另需遵守现有底账语义/格式：implemented时missing必须为空；其他状态missing与resolution_plan均需至少一条。验证时源码摘要未单独记录、Git未提交、其他模块职责等应与实际缺失职责分开，不要把明确的证据边界写成“缺实现”又同时给implemented。satisfied/missing/evidence/resolution_plan/limitations必须都是数组。
请核对所有三个模块，修正assessment.json，不预设任何目标通过。所有原文件在inputs/files/下，输入不可改，不运行产品/测试。任何Python解析只能用 D:\\AboutDEV\\Strixnova\\.venv\\Scripts\\python.exe。'''
(evidence/'user-input.txt').write_text(feedback,encoding='utf-8');dump(evidence/'registration.json',{**info,'previous_attempt':'253b96a75ac0','fixed_feedback':feedback})
shutil.copyfile(__file__,evidence/'operator-source.py')
protected=snapshot(project);protected.pop('assessment.json')
ids=set(info['target_ids']);owned={r['path']:r['target_module_id'] for t in packet['targets'] for r in t['ownership_candidates']}
def inspect():
    current=snapshot(project);current.pop('assessment.json',None)
    try:
        x=json.loads((project/'assessment.json').read_text(encoding='utf-8-sig'))
        complete=len(x['assessments'])==len(ids) and {r['target_id'] for r in x['assessments']}==ids and len(x['source_ownership'])==len(owned) and {r['path'] for r in x['source_ownership']}==set(owned)
        for row in x['assessments']:
            record={k:row[k] for k in ['target_id','target_kind','status','satisfied','missing','evidence','resolution_plan']};record['deviation_ids']=[]
            validator.validate(record);assert isinstance(row['limitations'],list)
        flags=x['owner_accepted'] is False and x['semantic_content_machine_proven'] is False
        return {'reached':current==protected and complete and flags,'inputs_unchanged':current==protected,'existing_ledger_record_schema_valid':True}
    except Exception as error:return {'reached':False,'inputs_unchanged':current==protected,'error':str(error)[:700]}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=feedback,
 evidence=evidence/'execution',observe_endpoint=inspect,model=info['author_model'],conversation_id=prior['last_result']['conversation_id'],
 timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(s) for s in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=inspect();dump(evidence/'endpoint.json',endpoint)
shutil.copyfile(project/'assessment.json',evidence/'assessment.json')
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
operator=(ROOT/'.artifacts/acceptance/initial/run_target_module_assessment.py').read_text(encoding='utf-8')
marker="sources={'packet':";assert operator.count(marker)==1
exec(compile(marker+operator.split(marker,1)[1],str(ROOT/'.artifacts/acceptance/initial/run_target_module_assessment.py'),'exec'),globals())
