"""Ask the real evaluator to distinguish target gaps from boundaries and integration duties."""
from pathlib import Path
import json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
info=json.loads((ROOT/'.artifacts/validation/30d2bb4dd8d8/work/registration.json').read_text(encoding='utf-8'))
project=Path(info['project']);packet=json.loads((project/'inputs/packet.json').read_text(encoding='utf-8'))
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
shutil.copyfile(project/'assessment.json',evidence/'previous-assessment.json');shutil.copyfile(__file__,evidence/'operator-source.py')
prompt='''请重新核对已有评价的以下具体疑点，原候选和原报告保留，不预设改为implemented：
1. 目标合同列举的是外部可获得的操作含义，是否真的要求每项都必须有一个同名独立函数？构造+load已经校验、project_direction_context已经返回护栏时，请找出合同明确缺失的行为，而不是仅以API组织形态判缺。
2. 你已注明“Git绑定是新仓库阶段限制，不是代码缺陷”“Agent语义不由程序证明”，却又把这些列入每个模块的missing。请区分当前模块实现缺口、待完成项目接线、验证证据边界及明确不负责的内容，不能据此把所有模块一概判不完整。
3. 架构load在返回前执行_validate_graph；通过之后返回direct_dependency_graph_acyclic=True是否符合已验证不变量？请据控制流判断，不能仅因返回字面量就认定缺口。
4. 跨仓库全局协调、跨权威事实覆盖、负责人语义接受分别由哪些合同承担？本模块的not_responsible_for和invariants如何限定其责任？不能把明确分工给其他模块的责任当作本模块缺实现。

请对照inputs/files/中的实际文件及packet的精确合同逐项判断。若保留缺口，说明代码具体违反的合同和来源；如果原判断超出合同，明确修正。resolution_plan仍为字符串数组，输入文件不变，只更新assessment.json。全部Python解析只能使用 D:\AboutDEV\Strixnova\.venv\Scripts\python.exe，不运行产品/测试。'''
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');dump(evidence/'registration.json',{**info,'scope_correction':prompt,'previous_attempt':'57de97292fb5'})
protected=snapshot(project);protected.pop('assessment.json')
ids=set(info['target_ids']);owned={r['path']:r['target_module_id'] for t in packet['targets'] for r in t['ownership_candidates']}
def inspect():
    current=snapshot(project);current.pop('assessment.json',None)
    try:
        x=json.loads((project/'assessment.json').read_text(encoding='utf-8-sig'))
        valid=len(x['assessments'])==len(ids) and {r['target_id'] for r in x['assessments']}==ids and {r['path'] for r in x['source_ownership']}==set(owned)
        valid=valid and all(isinstance(r['resolution_plan'],list) and r['evidence'] for r in x['assessments']) and x['owner_accepted'] is False and x['semantic_content_machine_proven'] is False
        return {'reached':bool(current==protected and valid),'inputs_unchanged':current==protected,'output_shape_valid':bool(valid)}
    except (ValueError,KeyError,TypeError):return {'reached':False,'inputs_unchanged':current==protected}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=inspect,model=info['author_model'],conversation_id='81519713-fe65-40c9-ba4f-bdf553cf6814',
 timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(s) for s in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if s.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=inspect();dump(evidence/'endpoint.json',endpoint)
shutil.copyfile(project/'assessment.json',evidence/'assessment.json')
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
sources={'packet':{'path':str(project/'inputs/packet.json'),'role':'original_input'},
 'request':{'path':str(evidence/'user-input.txt'),'role':'user_input'},'previous-assessment':{'path':str(evidence/'previous-assessment.json'),'role':'original_input'},
 'assessment':{'path':str(evidence/'assessment.json'),'role':'author_artifact'},'author-response':{'path':str(evidence/'author-response.md'),'role':'author_response'}}
contract_paths={t['contract_location']['path'] for t in packet['targets']}
output_ids=['assessment','author-response']
for entry in packet['files']:
    role='original_input' if entry['path'] in contract_paths else 'author_artifact'
    sources[entry['path']]={'path':str(project/'inputs/files'/entry['path']),'role':role}
    if role=='author_artifact':output_ids.append(entry['path'])
cases=[{'case_id':'TARGET-'+t['target_id'],
 'expected_behavior':'依据精确合同与当前源码复核这个模块及归属文件的实现评价。公开操作含义不自动等于必须各有独立方法；代码成功校验后的常量不自动是缺口；项目未提交Git、测试哈希缺失、Agent语义/负责人接受和其他模块明确承担的职责不能自动等同本模块缺实现。也不能因收到这条澄清就假定implemented；真正未满足的职责必须具体指出。合同：'+json.dumps(t['contract'],ensure_ascii=False),
 'must_avoid':'仅凭候选状态、API外形、绿色数量或笼统验证限制作实现结论；引用合同输入代替实际实现；把合理分工误判遗漏或把实际缺口移入limitations来掩盖。',
 'evidence_source_ids':output_ids,'verification_scope':'该模块的当前实现和归属评价，独立于整个仓库采用、Agent效果或外部认证。',
 'machine_checks':{'frozen_inputs_unchanged':True,'requested_target_present':True}} for t in packet['targets']]
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'group':info['group'],'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'authority_files_updated':False,'owner_accepted':False}
dump(evidence/'assessment-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
