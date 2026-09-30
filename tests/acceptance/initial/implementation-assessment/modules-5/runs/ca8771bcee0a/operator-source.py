"""Freeze additional real collaborator context without changing target contracts or code."""
from pathlib import Path
import argparse,ast,hashlib,json,os,shutil,sys,xml.etree.ElementTree as ET
ROOT=Path.cwd().resolve()
parser=argparse.ArgumentParser();parser.add_argument('--registration',type=Path,required=True);parser.add_argument('--kind',choices=['guidance','verification'],required=True);args=parser.parse_args()
previous=json.loads(args.registration.read_text(encoding='utf-8'));project=Path(previous['project'])
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
packet_file=project/'inputs/packet.json';before=packet_file.read_bytes();packet=json.loads(before)
assert hashlib.sha256(before).hexdigest()==previous['packet_sha256']
shutil.copyfile(packet_file,evidence/'previous-packet.json');shutil.copyfile(__file__,evidence/'operator-source.py')
common=['strixnova/src/strixnova/application_coordinator.py','tests/integration/test_multi_repository_execution.py']
extra=common+([
 'strixnova/src/strixnova/project_authority_consistency.py','strixnova/src/strixnova/project_authority_decision.py',
 'strixnova/src/strixnova/project_engineering_assurance.py','strixnova/src/strixnova/engineering_change_planning.py',
 'strixnova/src/strixnova/implementation_alignment_preparation.py','strixnova/src/strixnova/recoverable_document_transaction.py',
 'strixnova/src/strixnova/yaml_metadata_patch.py','tests/integration/test_history_cli.py',
 'tests/unit/test_engineering_change_planning.py','tests/unit/test_implementation_alignment_preparation.py',
] if args.kind=='guidance' else [
 'strixnova/src/strixnova/project_maintenance.py','tests/unit/test_test_case_evidence.py','tests/integration/test_behavior_example_cli.py'])
by_path={r['path']:r for r in packet['files']};added=[]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
for relative in extra:
    path=ROOT/relative;assert path.is_file() and not path.is_symlink() and not path.is_junction()
    if relative in by_path:
        assert sha(path)==by_path[relative]['sha256'];continue
    dest=project/'inputs/files'/relative;dest.parent.mkdir(parents=True,exist_ok=True);assert not dest.exists();shutil.copyfile(path,dest)
    entry={'path':relative,'read_path':'inputs/files/'+relative,'sha256':sha(path),'line_count':len(path.read_text(encoding='utf-8').splitlines()),'bytes':path.stat().st_size}
    packet['files'].append(entry);by_path[relative]=entry;added.append(relative)
outcomes={}
for run in ['d0856323c4b6','7aaf327a1ccb','f5e20647248e','c1dfd12d2187','30608175d9f5']:
    path=ROOT/'.artifacts/validation'/run/'evidence/pytest.xml'
    if not path.exists():continue
    for index,node in enumerate(ET.parse(path).getroot().iter('testcase')):
        key=node.attrib.get('classname','')+'::'+node.attrib.get('name','')
        status='failed' if node.find('failure') is not None or node.find('error') is not None else 'skipped' if node.find('skipped') is not None else 'passed'
        outcomes.setdefault(key,[]).append({'run_id':run,'junit_testcase_index':index,'node':key,'outcome':status})
supplemental=[]
for relative in extra:
    if not relative.startswith('tests/'):continue
    path=ROOT/relative;class_name=relative.removesuffix('.py').replace('/','.')
    for node in ast.parse(path.read_text(encoding='utf-8')).body:
        if not isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)) or not node.name.startswith('test_'):continue
        identity=relative+'::'+node.name
        if identity in packet['test_definitions']:continue
        matches=[r for key,rows in outcomes.items() if key==class_name+'::'+node.name or key.startswith(class_name+'::'+node.name+'[') for r in rows]
        packet['test_definitions'][identity]={'path':relative,'qualified_name':node.name,'start_line':node.lineno,'end_line':node.end_lineno,
          'current_file_sha256':sha(path),'recorded_executions':matches,'source_at_execution_hash':'not independently captured by JUnit; no exact-byte coverage inference'}
        supplemental.append(identity)
packet['material_root']='inputs/files';packet['context_supplement']={'kind':args.kind,'added_source_paths':added,'additional_test_definitions':supplemental,
 'scope':'Collaborator and assertion context only; target contracts, production ownership and previous code bytes are unchanged. A test need not be production-owned to support a boundary.'}
packet_file.write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for entry in packet['files']:assert sha(ROOT/entry['path'])==entry['sha256']
registration={**previous,'input_manifest':packet['files'],'packet_sha256':sha(packet_file),
 'previous_registration':str(args.registration.resolve()),'previous_packet_sha256':hashlib.sha256(before).hexdigest(),
 'context_supplement':packet['context_supplement']}
for path in [work/'registration.json',evidence/'registration.json']:path.write_text(json.dumps(registration,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'registration':str(work/'registration.json'),'added_files':len(added),'additional_test_definitions':len(supplemental),'targets_changed':False},ensure_ascii=False))
