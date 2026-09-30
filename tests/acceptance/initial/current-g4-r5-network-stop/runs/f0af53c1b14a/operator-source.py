"""Record a byte-checked runtime/Skill refresh without changing scenario state."""
from pathlib import Path
from zipfile import ZipFile
import json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.skill_bundle_manifest import directory_manifest
original_path=ROOT/'.artifacts/validation/6bbae8a5d2e5/evidence/registration.json'
initial=json.loads(original_path.read_text(encoding='utf-8'));old=candidate(Path(initial['candidate_registration']))
new_path=ROOT/'.artifacts/candidates/initial-intake-priority/candidate.json';new=candidate(new_path)
with ZipFile(old['wheel']) as before,ZipFile(new['wheel']) as after:
    original={n:before.read(n) for n in before.namelist() if n.startswith('strixnova/') and n.endswith(('.py','.json'))}
    assert original=={n:after.read(n) for n in after.namelist() if n.startswith('strixnova/') and n.endswith(('.py','.json'))}
project=Path(initial['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
ids=['WI-20260929-DEC61550','WI-20260929-274215EA']
def states(entry):
    data={}
    for identity in ids:
        call=subprocess.run([entry,'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
        data[identity]=json.loads(call.stdout)['next']
    return data
before=states(old['entrypoint']);assert before[ids[0]]['work_item_version']==13 and before[ids[0]]['current_action']['action_type']=='submit_engineering_assessment'
assert before[ids[1]]['current_action']['action_type']=='confirm_direction'
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==old['skill_sha256']
shutil.copyfile(project/'AGENTS.md',evidence/'previous-AGENTS.md');shutil.copytree(project/'.agents/skills/strixnova',evidence/'previous-skill')
instructions=(project/'AGENTS.md').read_text(encoding='utf-8');assert instructions.count(old['entrypoint'])==1
(project/'AGENTS.md').write_text(instructions.replace(old['entrypoint'],new['entrypoint']),encoding='utf-8',newline='\n')
shutil.copytree(Path(new['installed_skill']),project/'.agents/skills/strixnova',dirs_exist_ok=True)
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==new['skill_sha256']
assert states(new['entrypoint'])==before
assert all(sha(project/p)==h for p,h in initial['protected_source'].items())
head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip();assert head==initial['initial_commit']
derived={**initial,'candidate':new,'candidate_registration':str(new_path),'original_registration':str(original_path),
         'original_candidate':old,'environment_refresh_only':True,'runtime_python_and_json_unchanged':True,'public_states_unchanged':True,'owner_accepted':False}
dump(evidence/'registration.json',derived);dump(evidence/'public-states.json',before);shutil.copyfile(__file__,evidence/'operator-source.py')
print(json.dumps({'new_candidate':str(new_path),'version':13,'states_unchanged':True,'business_source_and_head_unchanged':True,'native_calls':0},ensure_ascii=False))
