"""Complete unread responsibility evidence and obey the existing ledger schema."""
from pathlib import Path
import json,os,shutil,sys
from jsonschema import Draft202012Validator
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
info=json.loads((ROOT/'.artifacts/validation/50cca29ed341/work/registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);packet=json.loads((project/'inputs/packet.json').read_text(encoding='utf-8'))
previous=ROOT/'.artifacts/validation/912a4896fb46/evidence';evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
prior=json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'))
shutil.copyfile(project/'assessment.json',evidence/'previous-assessment.json')
schema=json.loads((ROOT/'strixnova/src/strixnova/resources/project-implementation-alignment-v1.schema.json').read_text(encoding='utf-8'))
validator=Draft202012Validator({'$schema':schema['$schema'],'$ref':'#/$defs/responsibility_record','$defs':schema['$defs']})
feedback='''原输出和执行记录已保存，但assessment.json在第23行第257列不是合法JSON。请只做这次有界修正：使用 D:\\AboutDEV\\Strixnova\\.venv\\Scripts\\python.exe 的 json.dump 正确序列化字符串，避免自然语言里的引号破坏JSON，并以json.load回读确认格式。不得用裸python/python3/py。
继续按原合同与现有证据判断，不为通过改变结论。implemented要求missing=[]；其他状态missing与resolution_plan均至少一条，所有列表字段都用数组。证据局限、其他模块职责和未完成的项目Git接线要与当前代码缺口分开。归属未读取时据实记录unknown；不能在关键文件未读时宣称整个模块完整。
只写assessment.json，输入文件保持不变；实际代码在inputs/files/下。不要执行产品、测试或Git写入。完成后说明修正与剩余局限。'''
(evidence/'user-input.txt').write_text(feedback,encoding='utf-8');dump(evidence/'registration.json',{**info,'previous_attempt':'912a4896fb46','fixed_feedback':feedback})
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
