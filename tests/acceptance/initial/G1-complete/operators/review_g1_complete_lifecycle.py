from pathlib import Path
import json
import os
import subprocess
import sys
import yaml
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import run_review
phases={
 'direction':'8d987875922b','reexplain':'10bdc29a6a23','plan':'702661803a72',
 'progress':'0770243f9985','implementation':'03f5f073f451','delivery':'59ab96de72e5',
}
ids=['GF-COMM-AUTONOMOUS-PROGRESS','GF-COMM-RESUME-QUESTION','GF-CLEAR-BOUNDED','GF-PACE-SAME-CONTRACT',
 'GF-CONFIRM-DIRECTION-EXPLANATION','GF-CONFIRM-PLAN-EXPLANATION','GF-CONFIRM-RESULT-EXPLANATION',
 'GF-CONFIRM-REEXPLAIN-SAME-CANDIDATE','GF-CONFIRM-HIDE-INTERNAL-FIELDS','GF-TEST-FEEDBACK','GF-METHODS-SMALL-CHANGE','GF-UX-SKIP']
fixture=ROOT/'.artifacts/validation/f0addbc9966a/work/fixture.json'
info=json.loads(fixture.read_text(encoding='utf-8'));project=Path(info['project']);built=info['candidate']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
sources={'fixture-assumptions':{'path':str(fixture),'role':'original_input'}}
outputs=[]
for phase,run_id in phases.items():
    base=ROOT/'.artifacts/validation'/run_id
    result=json.loads((base/'result.json').read_text(encoding='utf-8'))
    assert result['status']=='passed' and result['process_settled']
    for name,role in [('user-input.txt','user_input'),('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]:
        identity=phase+'/'+name
        sources[identity]={'path':str(base/'evidence'/name),'role':role}
        if role!='user_input':outputs.append(identity)
identifier=json.loads((ROOT/'.artifacts/validation/59ab96de72e5/evidence/endpoint.json').read_text(encoding='utf-8'))['next']['work_item_id']
args=[built['entrypoint'],'history','--project-dir',str(project),'--work-item-id',identifier,'--limit','100']
for record in ['result','decisions','verifications','delivery','events']:args+=['--record',record]
history=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',check=True,timeout=60)
(evidence/'recorded-history.json').write_text(history.stdout,encoding='utf-8')
sources['final-recorded-history']={'path':str(evidence/'recorded-history.json'),'role':'author_artifact'};outputs.append('final-recorded-history')
for relative in ['src.py','tests/test_duration.py','docs/engineering/alignment.yaml','docs/engineering/target-responsibilities.yaml','docs/engineering/baseline.yaml']:
    sources['final/'+relative]={'path':str(project/relative),'role':'author_artifact'};outputs.append('final/'+relative)
for path in sorted((project/'.strixnova/artifacts'/identifier).glob('*')):
    if path.is_file() and path.suffix in {'.json','.txt','.log'}:
        identity='output/'+path.name;sources[identity]={'path':str(path),'role':'author_artifact'};outputs.append(identity)
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
rows={row['case_id']:row for row in catalog['cases']}
cases=[]
for identity in ids:
    row={key:rows[identity][key] for key in ['case_id','expected_behavior','must_avoid']}
    scope='同一真实隔离事项的完整轨迹；起始权威是明确的合成前提，后续负责人输入为预登记固定角色输入，不代表真人理解或真实重构接受。阶段Gate仅证明当时投递条件，不能替代本项判定。'
    if identity=='GF-TEST-FEEDBACK':
        scope+=' 必须从工具执行时序核对针对性测试是否在修复前实际因业务预期失败；最后测试通过或源代码存在不能补算红测。'
    if identity.startswith('GF-CONFIRM-'):
        scope+=' 分别检查首次主动展示与后续重述；不能用被询问后补充的内容抹去首次展示的真实缺口。'
    row.update(evidence_source_ids=outputs,verification_scope=scope,
        machine_checks={'all_native_phases_settled':True,'actual_fixture_item_completed':True})
    cases.append(row)
spec=evidence/'review-spec.json';spec.write_text(json.dumps({'sources':sources,'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
review=run_review(spec,evidence/'independent-review',timeout=900)
summary={'group':'G1','report_valid':review['execution']['report_valid'],
    'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
    'semantic_content_machine_proven':False,'actual_owner_accepted':False,'catalog_updated':False}
(evidence/'group-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1)
