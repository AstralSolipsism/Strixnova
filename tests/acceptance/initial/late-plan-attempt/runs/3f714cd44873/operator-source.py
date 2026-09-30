"""One non-accepting correction using observed structural and identity failures."""
from pathlib import Path
import argparse,json,os,shutil,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn

initial=json.loads((ROOT/'.artifacts/validation/6bbae8a5d2e5/evidence/registration.json').read_text(encoding='utf-8'))
parser=argparse.ArgumentParser()
parser.add_argument('--previous-run',default='02c672b89029')
parser.add_argument('--findings-file',type=Path,default=ROOT/'.artifacts/validation/110f9c74ab39/evidence/identity-comparison.json')
parser.add_argument('--timeout-seconds',type=int,choices=[600,900],default=900)
parser.add_argument('--fresh-session',action='store_true')
args=parser.parse_args()
previous=(ROOT/'.artifacts/validation'/args.previous_run).resolve();assert previous.is_relative_to(ROOT/'.artifacts/validation')
settled=json.loads((previous/'result.json').read_text(encoding='utf-8'))
old=json.loads((previous/'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert settled['process_settled'] and old['last_result']['status']=='SUCCESS' and not old['verdict']['unsettled_steps']
diagnostic=args.findings_file.resolve();assert diagnostic.is_relative_to(ROOT/'.artifacts')
finding=json.loads(diagnostic.read_text(encoding='utf-8'))
assert finding['files_and_git_unchanged'] and finding['owner_accepted'] is False
built=candidate(Path(initial['candidate_registration']));assert built==initial['candidate']
project=Path(initial['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
identifier=finding['work_item_id'];secondary_id='WI-20260929-274215EA'
def current(identity):
    call=subprocess.run([built['entrypoint'],'next','--project-dir',str(project),'--work-item-id',identity],capture_output=True,text=True,encoding='utf-8',check=True,timeout=45)
    return json.loads(call.stdout)['next']
before=current(identifier);secondary=current(secondary_id)
assert before['work_item_version']==finding['work_item_version']
assert before['current_action']['action_type']=='confirm_engineering_plan'
assert before['current_action']['confirmation_challenge']['candidate_fingerprint']==finding['candidate_fingerprint']
def business():
    files={}
    for relative in ['src.py','src','tests']:
        path=project/relative
        for p in ([path] if path.is_file() else path.rglob('*') if path.is_dir() else []):
            if p.is_file() and '__pycache__' not in p.parts:files[p.relative_to(project).as_posix()]=sha(p)
    return files
protected=business()
for p in (project/'docs').rglob('*'):assert not p.is_symlink() and not p.is_junction()
shutil.copytree(project/'docs',evidence/'candidate-before')
shutil.copyfile(diagnostic,evidence/'mechanical-findings.json')
shutil.copyfile(project/'.agent-inputs/ea_payload.json',evidence/'assessment-before.json')
prompt=('这是当前隔离验收的机械诊断反馈，没有新的接受、退回决定或业务事实。当前新版方案尚未被接受。'
 '继续原授权范围内的候选修订，并保留原始拒绝和修订历史：用当前公开合同和完整候选读取规则修复下面实际发现的结构、引用、身份增删及修订号问题，四类候选均核对后再提交需要的工程评估修订。'
 '不要猜枚举或字段、不要只核对根索引而漏掉领域来源和架构分文件；缺乏必需事实时明确报告并停止，不发明业务决定。'
 '读取既有 Skill 的领域事实、架构产物及工程政策合同；语义和设计仍由你按原业务事实形成。'
 '工程政策中的DDD采用依据不能靠空路径通过。周报方向仍未接受，只保持既有共享材料和单独交付边界。'
 '保持业务代码、tests和Git HEAD不变，不接受当前或后续方案、不接受四类权威，不实施业务和不提交Git。'
 '修订候选与评估后展示精确差异，停在新的方案待确认位置。\n实际只读诊断：\n'+json.dumps(finding,ensure_ascii=False))
if 'native_review_findings' in finding:
    prompt=('这是已完成独立原生复核的具体问题反馈，没有新的接受或业务事实。当前方案尚未接受。'
      '请复用本会话已有调查，仅按下列两类有来源的问题继续修订当前候选和方案：跨文档精确版本引用（包括PRD组合视图），以及编码前四份实现对齐底账的真实快照和切片操作安排。'
      '保留编码后的再核对安排，按既有合同处理同一路径的操作归属和续作引用，不猜字段。只写真实当前实现的底账，不把尚未实现的模块写成已实现。'
      '不扩大业务范围，不改源码或tests，不接受方案或权威，不提交Git，周报方向仍等待决定。'
      '修正后按完整候选及当前字段核对实际引用，逐项说明已修改的路径与仍有的限制，再停在新的方案待确认位置。'
      '原报告及所有失败保留，不宣称首次通过；若事实不足请明确停止。\n冻结的实际问题与来源：\n'+json.dumps(finding,ensure_ascii=False))
if args.fresh_session:
    prompt=('先读取本隔离工程AGENTS.md、指定Skill和实际公开当前方案。当前是已存在工程中的待确认修订，不是新建项目；原业务事实、已确认方向及调查版本以现有公开记录为准。'
      '之前同账号同模型会话因个人额度结束，此新会话仅接续相同范围，不重发任何接受输入。\n'+prompt)
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{'phase':'bounded-current-governance-structure-correction','project':str(project),'candidate':built,
    'work_item_id':identifier,'before_version':before['work_item_version'],'diagnostic_sha256':sha(diagnostic),
    'fixed_non_accepting_input':prompt,'input_sha256':sha(evidence/'user-input.txt'),'model':initial['model'],
    'timeout_seconds':args.timeout_seconds,'fresh_same_model_session':args.fresh_session,'max_neutral_continuations':0,'owner_accepted':False,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    state=current(identifier);other=current(secondary_id)
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==initial['initial_commit'] and business()==protected
    other_unchanged=other['work_item_version']==secondary['work_item_version'] and other['current_action']==secondary['current_action']
    return {'reached':state['work_item_version']>before['work_item_version'] and state['current_action']['action_type']=='confirm_engineering_plan' and unchanged and other_unchanged,
            'next':state,'business_source_and_git_unchanged':unchanged,'secondary_direction_unchanged':other_unchanged,
            'semantic_readiness':'pending exact mechanical comparison and independent review'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
    evidence=evidence/'execution',observe_endpoint=observe,model=initial['model'],conversation_id=None if args.fresh_session else old['last_result']['conversation_id'],
    timeout=args.timeout_seconds,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
shutil.copytree(project/'docs',evidence/'candidate-after')
shutil.copyfile(project/'.agent-inputs/ea_payload.json',evidence/'assessment-after.json')
summary={'mechanical_passed':receipt['mechanical_passed'],'reached':endpoint['reached'],'no_accepting_input_dispatched':True,'owner_accepted':False}
dump(evidence/'phase-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
