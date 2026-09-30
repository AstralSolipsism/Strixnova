"""Reassess five observed cases after edition-label-only corrections."""
from pathlib import Path
import json,os,shutil,sys,yaml
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.check_guided_formation_acceptance import check_catalog
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
expected={'GF-CLEAR-BOUNDED','GF-CONFIRM-PLAN-EXPLANATION','GF-CONFIRM-HIDE-INTERNAL-FIELDS','GF-TEST-FEEDBACK','GF-METHODS-SMALL-CHANGE'}
assert {r['case_id'] for r in check_catalog()['cases'] if r['evidence_state']=='stale'}==expected
groups={'G1':ROOT/'tests/acceptance/initial/G1-complete/runs/f891ecde76cd/independent-review',
        'targeted':ROOT/'tests/acceptance/initial/G1-targeted/runs/d8a2eeaa19bd/independent-review'}
sources={};specs={}
for group,base in groups.items():
    captured=json.loads((base/'sources.json').read_text(encoding='utf-8'));specs[group]=json.loads((base/'spec.json').read_text(encoding='utf-8'))
    folder=work/group;folder.mkdir()
    for index,(key,value) in enumerate(captured.items()):
        path=folder/f'{index:04d}.txt';path.write_text(value['text'],encoding='utf-8',newline='\n')
        sources[group+'/'+key]={'path':str(path),'role':value['role']}
old=json.loads((ROOT/'.artifacts/candidates/initial-guidance/candidate.json').read_text(encoding='utf-8'))
for name in ['architecture-artifact-contracts','authority-authoring','domain-fact-contracts']:
    for group,path in [('previous',Path(old['installed_skill'])/'references'/f'{name}.md'),
                       ('current',ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova/references'/f'{name}.md')]:
        sources[group+'/'+name]={'path':str(path),'role':'skill_contract'}
sources['prior-confirmation-reassessment']={'path':str(ROOT/'tests/acceptance/initial/confirmation-reassessment/runs/08830523eea9/independent-review/review.json'),'role':'original_input'}
boundary='只改正十处紧随不变 .v1 合同标识的中文旧版号括注，三个随包参考及中文审阅副本同步。程序、结构标识、字段、操作要求未改。本次不重演作者行为；原作者Skill身份保留。请逐项对照原行为、原要求与当前文字判断证据能否继续支持，不能仅因声称是文字修正而预设通过。如需要新行为证据，判blocked或needs_revision。先前首次解释与红测失败仍不被本次追认，红测使用另一次实际定点复验。'
(evidence/'boundary.txt').write_text(boundary,encoding='utf-8');sources['boundary']={'path':str(evidence/'boundary.txt'),'role':'user_input'}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'));by_id={r['case_id']:r for r in catalog['cases']}
cases=[]
for identity in sorted(expected):
    group='targeted' if identity=='GF-TEST-FEEDBACK' else 'G1'
    original=next(r for r in specs[group]['cases'] if r['case_id']==identity)
    cases.append({k:by_id[identity][k] for k in ['case_id','expected_behavior','must_avoid']}|{
     'evidence_source_ids':[group+'/'+k for k in original['evidence_source_ids']],
     'verification_scope':'依据当前 v1 中文版号修正重新审阅原生行为证据的适用性；不是重新执行或真人接受。',
     'machine_checks':{'original_native_records_preserved':True,'before_and_after_contract_texts_available':True}})
(evidence/'review-spec.json').write_text(json.dumps({'sources':sources,'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
shutil.copyfile(__file__,evidence/'operator-source.py')
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'reviewer_skill_sha256':directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256'],
 'behavior_replayed':False,'owner_accepted':False,'catalog_updated':False}
(evidence/'group-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
