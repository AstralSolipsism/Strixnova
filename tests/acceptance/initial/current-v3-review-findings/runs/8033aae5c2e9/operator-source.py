"""Fix candidate-output classification without changing native judgments."""
from pathlib import Path
import copy,hashlib,json,os,shutil,sys
ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import report_from_receipt
previous=ROOT/'.artifacts/validation/26a14ab34807/evidence/independent-review'
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
original=json.loads((previous/'review.json').read_text(encoding='utf-8'))
assert original['execution']['error']=='Input material cannot substitute for the reviewed output'
spec=json.loads((previous/'spec.json').read_text(encoding='utf-8'))
sources=json.loads((previous/'sources.json').read_text(encoding='utf-8'))
receipt=json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'))
assert receipt['mechanical_passed']
raw=receipt['last_result'].get('structured_output')
if raw is None:raw=json.loads(receipt['last_result']['response'])
assert len(raw['cases'])==2
fixed=copy.deepcopy(sources);changes=[]
for identity,source in fixed.items():
    assert hashlib.sha256(source['text'].encode('utf-8')).hexdigest()==source['sha256']
    if identity.startswith('current-project/'):
        assert source['role']=='original_input'
        source['role']='author_artifact'
        changes.append({'source_id':identity,'before':'original_input','after':'author_artifact','sha256_unchanged':source['sha256'],
                        'basis':'The second case explicitly reviews these actual candidate files as outputs; their text, identity and references are unchanged.'})
report=report_from_receipt(spec,fixed,receipt)
assert report['execution']['report_valid']
by_id={r['case_id']:r for r in raw['cases']}
for row in report['cases']:
    native=by_id[row['case_id']]
    for key in ['case_id','verdict','reason','issues','limitations']:assert row[key]==native[key]
    for bound,ref in zip(row['references'],native['references'],strict=True):
        assert all(bound[k]==v for k,v in ref.items())
report['supersedes_review']=str(previous/'review.json')
report['mechanical_correction_only']=True
for name in ['review.json','sources.json','spec.json']:shutil.copyfile(previous/name,evidence/('original-'+name))
for name,value in [('review.json',report),('corrected-sources.json',fixed),('source-role-correction.json',{'changes':changes,'native_semantic_fields_unchanged':True,'new_native_calls':0,'owner_accepted':False})]:
    (evidence/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
shutil.copyfile(__file__,evidence/'operator-source.py')
print(json.dumps({'execution':report['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict'],'issues':r['issues']} for r in report['cases']], 'new_native_calls':0},ensure_ascii=False))
