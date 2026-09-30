"""Forward the previously frozen G4 clarification and drafting inputs."""
from pathlib import Path
import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys

ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate, dump, sha
from scripts.agent_acceptance import run_session, assess_turn

parser=argparse.ArgumentParser();parser.add_argument('--initial-run',required=True);options=parser.parse_args()
origin=(ROOT/'.artifacts/validation'/options.initial_run/'evidence').resolve()
assert origin.is_relative_to(ROOT/'.artifacts/validation')
settled=json.loads((origin.parent/'result.json').read_text(encoding='utf-8'));assert settled['status']=='passed' and settled['process_settled']
registration=json.loads((origin/'registration.json').read_text(encoding='utf-8'))
first=json.loads((origin/'execution/driver-receipt.json').read_text(encoding='utf-8'))
assert first['mechanical_passed']
project=Path(registration['project'])
built=candidate(Path(registration['candidate_registration']));assert built==registration['candidate']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
shutil.copyfile(__file__,evidence/'operator-source.py')
dump(evidence/'registration.json',registration)
shutil.copytree(project/'docs',evidence/'before-docs')
conversation=first['last_result']['conversation_id']
def docs_snapshot():return {p.relative_to(project).as_posix():sha(p) for p in (project/'docs').rglob('*') if p.is_file()}
def versions():
    with sqlite3.connect((project/'.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        return list(c.execute('SELECT work_item_id, version FROM work_items ORDER BY work_item_id'))
initial_docs=docs_snapshot();initial_versions=versions()
for phase,limit in [('clarify_read_only',420),('form_candidates',900)]:
    stage=evidence/phase;stage.mkdir()
    prompt=registration['fixed_inputs'][phase]
    (stage/'user-input.txt').write_text(prompt,encoding='utf-8')
    def observe():
        head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
        unchanged=head==registration['initial_commit'] and all(sha(project/name)==digest for name,digest in registration['protected_source'].items())
        readonly=phase!='clarify_read_only' or (docs_snapshot()==initial_docs and versions()==initial_versions)
        return {'reached':unchanged and readonly,'business_source_and_git_unchanged':unchanged,
                'read_only_correction_preserved':readonly,'work_item_versions':versions(),
                'endpoint_scope':'Returned native phase and deterministic boundaries, not semantic maturity or acceptance.'}
    receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
      evidence=stage/'execution',observe_endpoint=observe,model=registration['model'],conversation_id=conversation,
      timeout=limit,max_continuations=0,permission_mode='auto_approve')
    (stage/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
    events=[json.loads(line) for line in (stage/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    dump(stage/'tool-steps.json',assess_turn(events)['tool_steps'])
    endpoint=observe();dump(stage/'endpoint.json',endpoint)
    print(json.dumps({'phase':phase,'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False),flush=True)
    if not receipt['mechanical_passed'] or not endpoint['reached']:raise SystemExit(1)
    conversation=receipt['last_result']['conversation_id']
shutil.copytree(project/'docs',evidence/'candidate-after')
shutil.copyfile(project/'strixnova-project.yaml',evidence/'candidate-config.yaml')
dump(evidence/'phase-summary.json',{'phases':['clarify_read_only','form_candidates'],'conversation_id':conversation,
     'semantic_readiness':'pending independent native gate','owner_accepted':False,'acceptance_input_dispatched':False})
