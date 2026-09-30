"""Validate exact command policy only; never start any tested command."""
from pathlib import Path
import hashlib, json, os, sys

ROOT=Path.cwd().resolve()
sys.path.insert(0,str(ROOT/'strixnova/src'))
from strixnova.process_supervisor import ProcessPolicy, ProcessExecutionError
from strixnova.project_engineering_policy import REQUIRED_FORBIDDEN_AGENT_PROGRAM_NAMES

binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe'
assert binary.is_file()
commands=[['codex.exe','--version'],[str(binary),'--version'],['powershell.exe','-NoProfile','-Command',str(binary),'--version']]
results=[]
for command in commands:
    policy=ProcessPolicy.exact('known-agent-name-audit','validation_without_execution',command)
    try:
        policy.validate(command)
    except ProcessExecutionError as error:
        outcome={'admitted':False,'reason':error.reason}
    else:
        outcome={'admitted':True,'reason':None}
    results.append({'command':command,**outcome})
sources=['strixnova/src/strixnova/process_supervisor.py','strixnova/src/strixnova/project_engineering_policy.py']
report={'scope':'Exact command policy validation only. No tested command or Agent process was started.',
        'program_started':False,'results':results,
        'required_forbidden_agent_names':sorted(REQUIRED_FORBIDDEN_AGENT_PROGRAM_NAMES),
        'source_files':[{'path':p,'sha256':hashlib.sha256((ROOT/p).read_bytes()).hexdigest()} for p in sources],
        'semantic_content_machine_proven':False}
Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'],'known-agent-policy-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))
