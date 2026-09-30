"""Return independent findings at the actual direction stage, without acceptance."""
from pathlib import Path
import argparse,json,os,shutil,sqlite3,subprocess,sys
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,sha
from scripts.agent_acceptance import run_session,assess_turn
parser=argparse.ArgumentParser()
for name in ['initial-run','prior-run','review-run']:parser.add_argument('--'+name,required=True)
options=parser.parse_args()
first=(ROOT/'.artifacts/validation'/options.initial_run/'evidence').resolve()
prior=(ROOT/'.artifacts/validation'/options.prior_run/'evidence').resolve()
review_base=(ROOT/'.artifacts/validation'/options.review_run/'evidence').resolve()
for directory in [first,prior,review_base]:
    assert directory.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((directory.parent/'result.json').read_text(encoding='utf-8'))
    assert result['status']=='passed' and result['process_settled']
registration=json.loads((first/'registration.json').read_text(encoding='utf-8'))
built=candidate(Path(registration['candidate_registration']));assert built==registration['candidate']
project=Path(registration['project']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
review=json.loads((review_base/'independent-review/review.json').read_text(encoding='utf-8'));assert review['execution']['report_valid']
findings=[{k:r[k] for k in ['case_id','verdict','reason','issues']} for r in review['cases'] if r['verdict']!='passed']
dump(evidence/'independent-findings.json',findings)
prompt=('以下是独立复核对上一轮实际产物的反馈，不是负责人接受，也没有改变原业务事实。'
 '请继续完成已授权的形成工作：先按当前公开动作处理方向阶段，不跳过方向、工程方案或长期权威确认。'
 '两项业务结果可分别交付，应落实为关联但可各自接受的事项；可以先推进成员撤回这一结果，周报保持另一待办结果，共享权威与跨单元选择在实施前统一。'
 '如完整权威候选的程序化起草需要先确认方向和工程方案，就诚实停在相应真实关口；不要把将来准备写的文件称为已经存在的完整候选。'
 '本轮请修正事项划分和当前方向的可审阅内容，解释必要的共享前提及后续顺序，到需要负责人决定时等待。不要实施业务代码、写确认元数据或提交Git。\n\n'
 +json.dumps(findings,ensure_ascii=False,indent=2))
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
dump(evidence/'registration.json',{'group':'G4','phase':'direction-correction-after-independent-review',
 'candidate':built,'original_fixed_inputs':registration['fixed_inputs'],'feedback':prompt,
 'reason':'Current physical candidates have been reviewed, but actual WorkItems remain at submit_direction with adoption blockers. Correct only the public phase sequence under the original facts; preserve initial missed intake and all review history, dispatch no acceptance.',
 'owner_accepted':False,'os_isolation_verified':False,'project':str(project)})
shutil.copyfile(__file__,evidence/'operator-source.py')
def observe():
    head=subprocess.run(['git','rev-parse','HEAD'],cwd=project,check=True,capture_output=True,text=True).stdout.strip()
    unchanged=head==registration['initial_commit'] and all(sha(project/p)==h for p,h in registration['protected_source'].items())
    with sqlite3.connect((project/'.strixnova/authority.sqlite3').as_uri()+'?mode=ro',uri=True) as c:
        items=[{'work_item_id':r[0],'version':r[1],'status':r[2]} for r in c.execute('SELECT work_item_id,version,status FROM work_items ORDER BY work_item_id')]
    return {'reached':unchanged,'business_source_and_git_unchanged':unchanged,'work_items':items}
previous=json.loads((prior/'execution/driver-receipt.json').read_text(encoding='utf-8'));assert previous['mechanical_passed']
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=observe,model=registration['model'],
 conversation_id=previous['last_result']['conversation_id'],timeout=600,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint,'acceptance_dispatched':False},ensure_ascii=False))
raise SystemExit(0 if receipt['mechanical_passed'] and endpoint['reached'] else 1)
