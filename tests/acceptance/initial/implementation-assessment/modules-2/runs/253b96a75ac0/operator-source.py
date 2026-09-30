"""Native semantic authorship and independent review of a frozen module packet."""
from pathlib import Path
import argparse,json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
parser=argparse.ArgumentParser();parser.add_argument('--registration',type=Path,required=True);args=parser.parse_args()
info=json.loads(args.registration.read_text(encoding='utf-8'));project=Path(info['project'])
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
packet=json.loads((project/'inputs/packet.json').read_text(encoding='utf-8'))
ids=set(info['target_ids']);owned={row['path']:row['target_module_id'] for t in packet['targets'] for row in t['ownership_candidates']}
prompt='''读取AGENTS.md、inputs/packet.json，并按其中导航实际阅读相关代码、Schema、测试断言与记录结果。请独立评价这三个当前程序模块承担其目标职责的程度，并在assessment.json写出可复核候选。不要运行程序或测试，不把测试名称、文件存在或通过数量当充分证据；不要因新仓库尚无Git提交就忽略可直接观察的代码职责，也不得冒充正式Git绑定。

输出一个JSON对象：assessments数组每个目标恰好一次，字段为target_id、target_kind（固定module）、status（implemented/partially_implemented/not_implemented/unknown）、satisfied（具体已支持职责列表）、missing（真实缺口列表）、evidence（每项kind为source/test/artifact/command/inspection，ref为复制来源的原仓库相对路径加可定位行号或真实运行ID/测试node，claim精确限定支持内容）、resolution_plan（字符串数组，单条也用数组）、limitations（字符串数组）。source_ownership数组对packet列出的每个归属候选文件恰好一次，字段为path、target_module_id、current_status（aligned/partially_aligned/drifted/unknown/not_applicable）、rationale。另加owner_accepted=false、semantic_content_machine_proven=false。

源码/断言支持哪些机制，实际运行证明哪些输入结果，Agent/负责人语义哪些尚未证明，必须分开。implemented不等于无缺陷或完整产品验收；若职责本身仍缺必要支持就用部分或未知，并给出真实依据。公开操作含义不自动要求每项都有独立同名方法；校验成功后返回的常量不自动是缺口；其他模块明确承担的协调或决定权不应列为本模块缺实现。未提交Git、未独立记录执行时源码摘要和未证明人类语义通常属于接线/证据边界，必须与实际未实现职责分开。不要为消除unknown而编造覆盖。原仓库路径一律从inputs/files/复制根读取。只写assessment.json，完成后说明关键结论与局限。'''
dump(evidence/'registration.json',{**info,'fixed_input':prompt});(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
shutil.copyfile(__file__,evidence/'operator-source.py')
protected=snapshot(project)
def inspect():
    actual=snapshot(project);actual.pop('assessment.json',None)
    stable=actual==protected
    if not (project/'assessment.json').is_file():return {'reached':False,'inputs_unchanged':stable,'reason':'no assessment output'}
    try:
        result=json.loads((project/'assessment.json').read_text(encoding='utf-8-sig'))
        rows=result['assessments'];ownership=result['source_ownership']
        complete=len(rows)==len(ids) and {r['target_id'] for r in rows}==ids and len(ownership)==len(owned) and {r['path'] for r in ownership}==set(owned)
        shape=all(r['target_kind']=='module' and r['status'] in {'implemented','partially_implemented','not_implemented','unknown'} and
          all(isinstance(r[k],list) for k in ['satisfied','missing','evidence','resolution_plan','limitations']) and r['evidence'] for r in rows)
        shape=shape and all(r['target_module_id']==owned[r['path']] and r['current_status'] in {'aligned','partially_aligned','drifted','unknown','not_applicable'} and r['rationale'] for r in ownership)
        flags=result['owner_accepted'] is False and result['semantic_content_machine_proven'] is False
        return {'reached':bool(stable and complete and shape and flags),'inputs_unchanged':stable,'target_and_source_coverage_complete':complete,'output_shape_valid':bool(shape and flags)}
    except (KeyError,ValueError,TypeError):return {'reached':False,'inputs_unchanged':stable,'reason':'invalid output structure'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=inspect,model=info['author_model'],timeout=900,max_continuations=0,
 permission_mode='auto_approve',new_output_paths=(project/'assessment.json',))
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(s) for s in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=inspect();dump(evidence/'endpoint.json',endpoint)
if (project/'assessment.json').exists():shutil.copyfile(project/'assessment.json',evidence/'assessment.json')
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
sources={'packet':{'path':str(project/'inputs/packet.json'),'role':'original_input'},
 'request':{'path':str(evidence/'user-input.txt'),'role':'user_input'},
 'assessment':{'path':str(evidence/'assessment.json'),'role':'author_artifact'},
 'author-response':{'path':str(evidence/'author-response.md'),'role':'author_response'},
 'author-tools':{'path':str(evidence/'tool-steps.json'),'role':'author_artifact'}}
contract_paths={t['contract_location']['path'] for t in packet['targets']}
actual_output_ids=[]
for entry in packet['files']:
    role='original_input' if entry['path'] in contract_paths else 'author_artifact'
    sources[entry['path']]={'path':str(project/'inputs/files'/entry['path']),'role':role}
    if role=='author_artifact':actual_output_ids.append(entry['path'])
cases=[]
for t in packet['targets']:
    allowed=['assessment','author-response','author-tools',*actual_output_ids]
    cases.append({'case_id':'TARGET-'+t['target_id'],
     'expected_behavior':'逐条核查此模块目标合同的实现评价及其归属文件。状态、已支持职责、缺口、证据和局限须与具体源码、测试断言及记录范围一致；完整代码机制不等于Agent语义效果、Git绑定或真人接受。纠正过度或不足判断，不能因作者写implemented而预设通过。目标合同：'+json.dumps(t['contract'],ensure_ascii=False),
     'must_avoid':'仅凭名称、文件数、结构存在或绿色测试数批准；使用未读代码或过期行号；把执行时未记录的源码摘要当成已记录；把所有未知都一概推给未提交Git或虚构负责人确认。',
     'evidence_source_ids':list(dict.fromkeys(allowed)),
     'verification_scope':'仅此模块当前可见实现及这些归属候选的证据评价，不是完整产品/Agent验收或外部认证。',
     'machine_checks':{'frozen_inputs_unchanged':True,'all_requested_targets_and_sources_present':True}})
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'group':info['group'],'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'authority_files_updated':False,'owner_accepted':False}
dump(evidence/'assessment-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
