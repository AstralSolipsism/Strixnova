"""Forward one non-accepting correction after the actual G4 formation review."""
from pathlib import Path
import argparse,hashlib,json,os,shutil,sqlite3,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
parser=argparse.ArgumentParser()
for name in ['initial-run','formation-run','review-run','artifact-capture-run']:parser.add_argument('--'+name,required=True)
options=parser.parse_args()
def settled(identity):
    base=(ROOT/'.artifacts/validation'/identity).resolve();assert base.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((base/'result.json').read_text(encoding='utf-8'))
    assert result['process_settled'] and result['status']=='passed'
    return base/'evidence'
initial=settled(options.initial_run);previous=settled(options.formation_run)
review_base=settled(options.review_run);capture=settled(options.artifact_capture_run)
report=json.loads((review_base/'independent-review/review.json').read_text(encoding='utf-8'))
assert report['execution']['report_valid'] and report['execution']['mechanical_passed']
gate=next(r for r in report['cases'] if r['case_id']=='GATE-G4-COMPLETE-AUTHORITY-CANDIDATES')
assert gate['verdict']=='needs_revision'
registration=json.loads((initial/'registration.json').read_text(encoding='utf-8'))
project=Path(registration['project']).resolve();assert project.is_relative_to(ROOT/'.artifacts/validation')
built=candidate(Path(registration['candidate_registration']));assert built==registration['candidate']
receipt=json.loads((previous/'execution/driver-receipt.json').read_text(encoding='utf-8'));assert receipt['mechanical_passed']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
shutil.copytree(project/'docs',evidence/'before-docs')
before={p.relative_to(project).as_posix():sha(p) for p in (project/'docs').rglob('*') if p.is_file()}
artifact=json.loads((capture/'artifact-provenance.json').read_text(encoding='utf-8'))
body=(capture/artifact['captured_name']).read_bytes();assert hashlib.sha256(body).hexdigest()==artifact['sha256']
local_copy=project/'.agent-inputs/g4-fixed/reviewed-source-candidate-package.md'
assert not local_copy.exists();local_copy.write_bytes(body)
(evidence/'source-candidate-package.md').write_bytes(body)
fixed='''独立检查确认，上一轮的候选内容只存在于宿主 Markdown 产物，工程对应文件未写入，而且明确受管请求最初没有先登记事项。这不是对候选的接受。原始漏登记与未落盘记录必须保留，不能改写成首次就通过。
请只完成原请求中尚未完成的实际形成工作：按既有公开 intake/CurrentAction 流程登记受影响事项并形成可定位方向；把已给定业务事实和你已起草的内容落实到项目四类完整候选文件及 PRD 只读组合视图。原始候选材料在 .agent-inputs/g4-fixed/reviewed-source-candidate-package.md，可作为数据参考，不能以其存在代替项目文件就绪。使用既有公开合同核对形状、引用、稳定身份和新修订；遇到真实内容缺口如实说明，不删必需范围来通过检查。
本次只允许事项登记、候选文档和必要配置形成，不接受方向或权威，不写确认元数据，不实施业务源码或测试，不提交 Git。保持原业务事实和不受影响的稳定身份，实现对齐保持草稿。所有 Python 使用 AGENTS.md 指定的完整解释器路径。完成后展示实际文件、当前事项位置和剩余限制，等待独立复核及后续明确决定。'''
(evidence/'user-input.txt').write_text(fixed,encoding='utf-8')
dump(evidence/'registration.json',{**registration,'phase':'bounded-file-formation-correction',
    'previous_formation_run':options.formation_run,'independent_review':str(review_base/'independent-review/review.json'),
    'review_sha256':sha(review_base/'independent-review/review.json'),'fixed_non_accepting_input':fixed,
    'input_sha256':hashlib.sha256(fixed.encode('utf-8')).hexdigest(),'actual_owner_accepted':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
required=['docs/product/definition.yaml','docs/domain/model.yaml','docs/architecture/model.yaml','docs/engineering/policy.yaml']
def observe():
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    protected=head==registration['initial_commit'] and all(sha(project/name)==digest for name,digest in registration['protected_source'].items())
    changed=[name for name in required if (project/name).is_file() and sha(project/name)!=before.get(name)]
    with sqlite3.connect((project/'.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as connection:
        items=list(connection.execute('SELECT work_item_id,version FROM work_items ORDER BY work_item_id'))
    return {'reached':protected and len(changed)==4 and len(items)>1,'business_source_and_git_unchanged':protected,
            'changed_authority_root_paths':changed,'work_item_versions':items,
            'scope':'File changes and registration only; schema, meaning and acceptance remain independent review duties.'}
executed=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=fixed,
    evidence=evidence/'execution',observe_endpoint=observe,model=registration['model'],
    conversation_id=receipt['last_result']['conversation_id'],timeout=900,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(executed['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
shutil.copytree(project/'docs',evidence/'candidate-after');shutil.copyfile(project/'strixnova-project.yaml',evidence/'candidate-config.yaml')
summary={'mechanical_passed':executed['mechanical_passed'],'endpoint':endpoint,'accepting_input_dispatched':False,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if executed['mechanical_passed'] and endpoint['reached'] else 1)
