"""Read actual earlier failed-run evidence without inferring unobserved causes."""
from pathlib import Path
import json,os,shutil,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump,snapshot
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
work=Path(os.environ['STRIXNOVA_VALIDATION_WORK']);evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
project=ROOT/'.artifacts/validation/d9b9a293fe4c/work/project'
assert project.is_dir() and (project/'.git').is_dir() and not (project/'AGENTS.md').exists()
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json')
from scripts.skill_bundle_manifest import directory_manifest
assert directory_manifest(project/'.agents/skills/strixnova')['sha256']==built['skill_sha256']
inputs=project/'inputs';assert inputs.is_dir()
origin=ROOT/'.artifacts/validation/d0856323c4b6'
for name in ['result.json','stdout.log','stderr.log']:shutil.copyfile(origin/name,inputs/name)
shutil.copyfile(origin/'evidence/pytest.xml',inputs/'pytest.xml')
(project/'AGENTS.md').write_text(f'''# 只读历史运行说明

这是较早一次真实运行的冻结输出，不是当前项目状态；没有提供后续修复或复验材料。使用 .agents/skills/strixnova/SKILL.md 中适用沟通指引，只读 inputs/ 文件并答复。不得重跑命令、修改文件、建立事项、访问父目录中的当前源码或调用子Agent。需要解析数据时只用 {sys.executable}，禁止裸python/python3和安装工具。
''',encoding='utf-8')
prompt='请只依据这份当时冻结的真实运行记录，向负责人说明哪些已有通过证据、哪些明确失败或跳过、失败的直接观察与尚未证实的根因分别是什么，并给出下一步具体诊断动作和执行者。不要把部分通过写成完成，不要把未知猜成环境问题，也不要无依据建议原样重跑。本次仅分析这些记录，不实施修复或测试；后续发生过什么尚未提供。'
dump(evidence/'registration.json',{'case_id':'GF-COMM-UNKNOWN-FAILURE','candidate':built,'fixed_input':prompt,
 'source_run_id':'d0856323c4b6','initial_files':snapshot(project),'scope':'Historical output communication only; not current source acceptance.',
 'owner_accepted':False,'os_isolation_verified':False,'timeout_seconds':420})
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8');shutil.copyfile(__file__,evidence/'operator-source.py')
protected=snapshot(project)
def observe():return {'reached':snapshot(project)==protected,'all_inputs_unchanged':snapshot(project)==protected}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',timeout=420,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);dump(evidence/'endpoint.json',observe())
if not receipt['mechanical_passed'] or not observe()['reached']:raise SystemExit('Readonly historical analysis did not settle')
sources={name:{'path':str(evidence/name),'role':role} for name,role in [('user-input.txt','user_input'),
 ('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]}
for path in inputs.iterdir():sources['original/'+path.name]={'path':str(path),'role':'original_input'}
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-COMM-UNKNOWN-FAILURE')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':['author-response.md','tool-steps.json','endpoint.json'],
 'verification_scope':'针对实际旧一轮失败输出的只读状态沟通，不评价当前源码、后续修复或真实负责人理解。',
 'machine_checks':{'native_response_settled':True,'all_inputs_unchanged':True}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
