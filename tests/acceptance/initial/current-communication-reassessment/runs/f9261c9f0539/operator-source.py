"""Run an already registered evidence review after the native service is available."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sys

ROOT=Path.cwd().resolve();sys.path.insert(0,str(ROOT))
from scripts.review_antigravity_evidence import run_review

parser=argparse.ArgumentParser();parser.add_argument('--preparation-run',required=True);args=parser.parse_args()
base=(ROOT/'.artifacts/validation'/args.preparation_run).resolve()
assert base.is_relative_to(ROOT/'.artifacts/validation')
prepared=json.loads((base/'result.json').read_text(encoding='utf-8'))
assert prepared['status']=='passed' and prepared['process_settled'] and not prepared['workspace_removed']
registration=json.loads((base/'evidence/registration.json').read_text(encoding='utf-8'))
spec_path=base/'evidence/review-spec.json'
assert hashlib.sha256(spec_path.read_bytes()).hexdigest()==registration['spec_sha256']
spec=json.loads(spec_path.read_text(encoding='utf-8'))
assert sorted(row['case_id'] for row in spec['cases'])==registration['cases']
for row in registration['original_sources']+registration['delta_sources']:
    source=Path(spec['sources'][row['source_id']]['path'])
    assert hashlib.sha256(source.read_bytes()).hexdigest()==row['sha256']
    if row['source_id'].startswith('current/'):
        assert hashlib.sha256((ROOT/row['path']).read_bytes()).hexdigest()==row['sha256']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
shutil.copyfile(__file__,evidence/'operator-source.py')
shutil.copyfile(base/'evidence/registration.json',evidence/'preparation-registration.json')
review=run_review(spec_path,evidence/'independent-review',timeout=900)
summary={'preparation_run':args.preparation_run,'execution':review['execution'],
         'cases':[{'case_id':row['case_id'],'verdict':row['verdict']} for row in review['cases']],
         'behavior_replayed':False,'catalog_updated':False,'owner_accepted':False}
(evidence/'review-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] else 1)
