"""Native reassessment of unchanged observed behavior against clarified guidance."""
from pathlib import Path
import json
import os
import sys
import yaml
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.check_guided_formation_acceptance import check_catalog
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest

work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
check=check_catalog();stale={row['case_id'] for row in check['cases'] if row['evidence_state']=='stale'}
expected={'GF-COMM-DETAIL-AND-CLOSURE','GF-CLEAR-BOUNDED','GF-CONFIRM-PLAN-EXPLANATION',
          'GF-CONFIRM-RESULT-EXPLANATION','GF-CONFIRM-REEXPLAIN-SAME-CANDIDATE',
          'GF-CONFIRM-HIDE-INTERNAL-FIELDS','GF-METHODS-SMALL-CHANGE'}
assert stale==expected
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
by_id={row['case_id']:row for row in catalog['cases']}
groups={
 'G3':ROOT/'tests/acceptance/initial/G3-canonical/review',
 'G1':ROOT/'tests/acceptance/initial/G1-complete/runs/f891ecde76cd/independent-review',
}
sources={};old_specs={}
for group,base in groups.items():
    captured=json.loads((base/'sources.json').read_text(encoding='utf-8'))
    old_specs[group]=json.loads((base/'spec.json').read_text(encoding='utf-8'))
    directory=work/group;directory.mkdir()
    for index,(identity,source) in enumerate(captured.items()):
        path=directory/f'{index:04d}.txt';path.write_text(source['text'],encoding='utf-8',newline='\n')
        sources[group+'/'+identity]={'path':str(path),'role':source['role']}
old_candidate=json.loads((ROOT/'.artifacts/candidates/initial-canonical/candidate.json').read_text(encoding='utf-8'))
old_guide=Path(old_candidate['installed_skill'])/'references/confirmation-and-cancel.md'
new_guide=ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova/references/confirmation-and-cancel.md'
sources['previous-guide']={'path':str(old_guide),'role':'original_input'}
sources['current-guide']={'path':str(new_guide),'role':'skill_contract'}
notice='本次是已观察原生行为的证据重评。确认指引增加了“首次询问前解释，而非列字段；比较当前与拟议结果并交代重要取舍与未知”的明确说明。请你独立判断原行为是否满足当前要求，不能因修改被称作澄清就预设通过。原作者实际使用旧Skill，未声称加载了新副本；本次不重演行为，不追认另两项已失败的初轮要求。若本项需要新的作者行为才能证明，判blocked或needs_revision。'
(evidence/'reassessment-boundary.txt').write_text(notice,encoding='utf-8')
sources['reassessment-boundary']={'path':str(evidence/'reassessment-boundary.txt'),'role':'user_input'}
cases=[]
for identity in sorted(stale):
    group='G3' if identity=='GF-COMM-DETAIL-AND-CLOSURE' else 'G1'
    old=next(row for row in old_specs[group]['cases'] if row['case_id']==identity)
    row={key:by_id[identity][key] for key in ['case_id','expected_behavior','must_avoid']}
    row.update(evidence_source_ids=[group+'/'+name for name in old['evidence_source_ids']]+['current-guide'],
        verification_scope='针对当前确认指引审阅原始已观察行为的符合性与证据可复用性；保留原作者旧Skill身份，不证明作者重新执行或真人接受。',
        machine_checks={'original_native_records_preserved':True,'previous_and_current_guidance_provided':True})
    cases.append(row)
spec=evidence/'review-spec.json';spec.write_text(json.dumps({'sources':sources,'cases':cases},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
review=run_review(spec,evidence/'independent-review',timeout=900)
summary={'scope':'native evidence reassessment, not replay','report_valid':review['execution']['report_valid'],
    'original_author_skill_sha256':old_candidate['skill_sha256'],
    'reviewer_skill_sha256':directory_manifest(ROOT/'strixnova/src/strixnova/resources/agent-skill/strixnova')['sha256'],
    'cases':[{key:row[key] for key in ['case_id','verdict']} for row in review['cases']],
    'semantic_content_machine_proven':False,'owner_accepted':False,'catalog_updated':False}
(evidence/'reassessment-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status']=='passed' for row in review['cases']) else 1)
