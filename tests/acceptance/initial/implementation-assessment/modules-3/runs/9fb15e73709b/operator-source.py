"""Complete unread responsibility evidence and obey the existing ledger schema."""
from pathlib import Path
import json,os,shutil,sys
from jsonschema import Draft202012Validator
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
info=json.loads((ROOT/'.artifacts/validation/8a9d0d23fafe/work/registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);packet=json.loads((project/'inputs/packet.json').read_text(encoding='utf-8'))
previous=ROOT/'.artifacts/validation/482e835cf090/evidence';evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
prior=json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'))
shutil.copyfile(project/'assessment.json',evidence/'previous-assessment.json')
schema=json.loads((ROOT/'strixnova/src/strixnova/resources/project-implementation-alignment-v1.schema.json').read_text(encoding='utf-8'))
validator=Draft202012Validator({'$schema':schema['$schema'],'$ref':'#/$defs/responsibility_record','$defs':schema['$defs']})
feedback='''上一轮输出已保存，但assessment.json不是合法JSON，解析在第23行第15列失败。请先修正JSON转义/格式，并按现有底账约束输出：implemented的missing必须为空，其他状态missing和resolution_plan至少一项；列表字段不能使用字符串。
请同时复核两个实质判断：合同“解释确定性缺口”描述可获得的行为，不自动要求独立同名函数；通过稳定异常/错误输出能否满足，应据实际调用与错误内容判断。停止条件也应按编译结果、状态阻断与相关约束的实际语义核对，不能只因不存在名为stop_conditions的单字段就判缺。
建设事项权威的切片依赖、重规划后交付保留、零命令切片等关键部分如尚未读，补读实际控制流；若仍未核实，诚实保留具体未知，不能假定已实现。进程监督已读取的部分无需无关重演。
只更新assessment.json；原源码与合同不改，路径位于inputs/files/。禁止运行产品或测试，所有Python解析必须用完整路径 D:\\AboutDEV\\Strixnova\\.venv\\Scripts\\python.exe。'''
(evidence/'user-input.txt').write_text(feedback,encoding='utf-8');dump(evidence/'registration.json',{**info,'previous_attempt':'482e835cf090','fixed_feedback':feedback})
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
