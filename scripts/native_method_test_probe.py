"""Run a fixture check and preserve exact execution facts, never grade meaning."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
PYTHON=ROOT/'.venv/Scripts/python.exe'
sys.path.insert(0,str(ROOT))
from strixnova.process_supervisor import ProcessExecutionError,ProcessLimits,ProcessPolicy,run_process

def source_hashes(project):
    return {p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for area in ['handover','tests'] for p in (project/area).rglob('*.py') if '__pycache__' not in p.parts}


def project_path(project,relative):
    path=(project/relative).resolve()
    if not path.is_relative_to(project) or path==project:
        raise ValueError('Materials and script must stay inside the declared fixture project')
    return path


def snapshot(project,names,destination):
    hashes={};errors=[]
    for name in names:
        try:
            path=project_path(project,name)
            raw=path.read_bytes()
            copied=destination/name;copied.parent.mkdir(parents=True,exist_ok=True);copied.write_bytes(raw)
            hashes[name]=hashlib.sha256(raw).hexdigest()
        except (OSError,ValueError) as error:
            errors.append({'path':name,'error':type(error).__name__,'message':str(error)})
    return hashes,errors

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path,required=True)
    parser.add_argument('--script',help='Project-relative Python entrypoint; omit to run the existing pytest route.')
    parser.add_argument('--source',action='append',default=[],help='Additional exact project-relative check input.')
    parser.add_argument('--artifact',action='append',default=[],help='Exact output to capture immediately after this command.')
    parser.add_argument('pytest_arguments',nargs=argparse.REMAINDER)
    args=parser.parse_args();project=args.project.resolve()
    if not project.is_relative_to(ROOT/'.artifacts/antigravity-manual'):
        raise ValueError('Checks must run inside the owned native-acceptance fixture area')
    arguments=args.pytest_arguments
    if arguments and arguments[0]=='--':arguments=arguments[1:]
    if args.script:
        entry=project_path(project,args.script)
        if not entry.is_file() or entry.suffix!='.py':
            raise ValueError('Script must be an existing Python file inside the fixture')
        names=[entry.relative_to(project).as_posix(),*args.source]
    else:
        names=[*source_hashes(project),*args.source]
    names=list(dict.fromkeys(project_path(project,name).relative_to(project).as_posix() for name in names))
    artifacts=list(dict.fromkeys(project_path(project,name).relative_to(project).as_posix() for name in args.artifact))
    for name in names:
        if not project_path(project,name).is_file():raise ValueError('Declared source is not a file inside the fixture')
    identifier=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:6]
    evidence=project.parent/'test-runs'/identifier;evidence.mkdir(parents=True)
    generated=evidence/'generated';generated.mkdir()
    work=evidence/'work';work.mkdir()
    before,before_errors=snapshot(project,names,evidence/'before')
    if before_errors:raise ValueError('Cannot snapshot declared inputs before command execution')
    if args.script:
        command=[str(PYTHON),'-B','-X','utf8',str(entry),*arguments]
    else:
        command=[str(PYTHON),'-B','-X','utf8','-m','pytest','-c',str(project/'pytest.ini'),'--rootdir',str(project),
                 *arguments,'--junitxml',str(evidence/'pytest.xml')]
        if not arguments:command.insert(command.index('--junitxml'),'tests')
    started=datetime.now(timezone.utc).isoformat()
    process_error=None
    try:
        result=run_process(command,cwd=project,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',
            STRIXNOVA_PROBE_EVIDENCE=str(generated),STRIXNOVA_PROBE_WORK=str(work)),
            policy=ProcessPolicy.exact('native-fixture-check','Run the exact fixture check, not an Agent.',command),
            limits=ProcessLimits(timeout_seconds=180))
    except ProcessExecutionError as error:
        process_error={'reason':error.reason,'message':str(error)}
        result=error.partial_result
    stdout=result.stdout if result is not None else b''
    stderr=result.stderr if result is not None else b''
    exit_code=result.exit_code if result is not None else None
    (evidence/'stdout.log').write_bytes(stdout);(evidence/'stderr.log').write_bytes(stderr)
    after,source_errors=snapshot(project,names,evidence/'after')
    captured,artifact_errors=snapshot(project,artifacts,evidence/'artifacts')
    generated_hashes={}
    for path in generated.rglob('*'):
        if not path.is_file():continue
        if not path.resolve().is_relative_to(generated):
            artifact_errors.append({'path':str(path),'error':'outside_generated_directory'})
            continue
        generated_hashes[path.relative_to(generated).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    record={'argv':command,'cwd':str(project),'started_at':started,'finished_at':datetime.now(timezone.utc).isoformat(),
        'exit_code':exit_code,'evidence_directory':str(evidence),'execution_kind':'script' if args.script else 'pytest',
        'launcher_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'before_source_hashes':before,'after_source_hashes':after,'inputs_stable':not source_errors and before==after,
        'source_capture_errors':source_errors,'captured_artifact_hashes':captured,'artifact_capture_errors':artifact_errors,
        'generated_artifact_hashes':generated_hashes,'work_directory':str(work),'work_retained_for_acceptance':True,
        'process_error':process_error,'process_settled':not process_error or process_error['reason']!='cleanup_failed',
        'stdout_sha256':hashlib.sha256(stdout).hexdigest(),'stderr_sha256':hashlib.sha256(stderr).hexdigest(),
        'semantic_content_machine_proven':False}
    (evidence/'receipt.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'evidence':str(evidence),'receipt_path':str(evidence/'receipt.json'),'stdout_path':str(evidence/'stdout.log'),
                      'stderr_path':str(evidence/'stderr.log'),'junit_path':None if args.script else str(evidence/'pytest.xml'),
                      'artifact_paths':{name:str(evidence/'artifacts'/name) for name in captured},
                      'generated_paths':{name:str(generated/name) for name in generated_hashes},
                      'exit_code':exit_code,'inputs_stable':record['inputs_stable'],'process_error':process_error,
                      'stdout':stdout.decode('utf-8',errors='replace')[-6500:],
                      'stderr':stderr.decode('utf-8',errors='replace')[-800:]},ensure_ascii=False))
    return exit_code if exit_code and not process_error else 1 if process_error or source_errors or artifact_errors or not record['inputs_stable'] else 0

if __name__=='__main__':raise SystemExit(main())
