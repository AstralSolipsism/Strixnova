"""Capture only the exact host artifact named in this completed native write."""
from pathlib import Path
import hashlib,json,os,shutil
root=Path.cwd().resolve()
run=root/'.artifacts/validation/b885ddd5fe09'
result=json.loads((run/'result.json').read_text(encoding='utf-8'))
assert result['status']=='passed' and result['process_settled']
receipt=json.loads((run/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
writes=[s for s in receipt['verdict']['tool_steps'] if s['tool_name']=='write_to_file' and s['state']=='DONE']
assert len(writes)==1
path=Path(writes[0]['tool_info']['parameters']['TargetFile']).resolve()
brain=Path(os.environ['USERPROFILE'])/'.gemini/antigravity-cli/brain'
assert path.is_relative_to(brain.resolve()) and path.name=='authority-candidate-package.md'
assert len(path.relative_to(brain.resolve()).parts)==2 and path.is_file()
assert all(not p.is_symlink() and not p.is_junction() for p in [path,path.parent])
body=path.read_bytes();digest=hashlib.sha256(body).hexdigest()
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
(evidence/path.name).write_bytes(body)
record={'native_run':'b885ddd5fe09','step_index':writes[0]['step_index'],'original_path':str(path),
        'captured_name':path.name,'sha256':digest,'bytes':len(body),
        'conversation_id':receipt['last_result']['conversation_id'],
        'scope':'Exact file named in the completed native write; not four repository authority files and not an acceptance.',
        'semantic_content_machine_proven':False,'owner_accepted':False}
(evidence/'artifact-provenance.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
assert hashlib.sha256(path.read_bytes()).hexdigest()==digest
shutil.copyfile(__file__,evidence/'operator-source.py')
print(json.dumps({key:record[key] for key in ['native_run','step_index','bytes','sha256','scope']},ensure_ascii=False))
