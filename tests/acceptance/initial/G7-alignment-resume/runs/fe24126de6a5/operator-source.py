"""Native continuation of the prepared draft, preserving its actual identity."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate,dump
from scripts.agent_acceptance import run_session,assess_turn
from scripts.review_antigravity_evidence import run_review
base=ROOT/'.artifacts/validation/acf22f1b3a5c'
info=json.loads((base/'work/fixture.json').read_text(encoding='utf-8'))
project=Path(info['project']);fixture=Path(info['fixture_root']);alignment_root=Path(info['alignment_root'])
built=candidate(ROOT/'.artifacts/candidates/initial-v1/candidate.json');assert built==info['candidate']
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
dump(evidence/'registration.json',{**info,'model':'gemini-3.8-flash-low','timeout_seconds':420,'previous_incomplete_run':'6eae0790eb42',
 'max_neutral_continuations':0,'os_isolation_verified':False})
shutil.copyfile(__file__,evidence/'operator-source.py')
shutil.copytree(base/'evidence/before-alignment',evidence/'before-alignment')
shutil.copyfile(base/'evidence/setup-boundary.json',evidence/'setup-boundary.json')
previous_run=ROOT/'.artifacts/validation/6eae0790eb42/evidence'
previous_receipt=json.loads((previous_run/'execution/driver-receipt.json').read_text(encoding='utf-8'))
assert previous_receipt['verdict']['unsettled_steps']==[]
assert len(previous_receipt['verdict']['failed_steps'])==1
assert previous_receipt['verdict']['failed_steps'][0]['tool_name']=='view_file'
conversation=previous_receipt['last_result']['conversation_id']
shutil.copyfile(previous_run/'author-response.md',evidence/'previous-response.md')
dump(evidence/'previous-execution-boundary.json',{'original_run':'6eae0790eb42','outcome':previous_receipt['outcome'],
 'failed_steps':previous_receipt['verdict']['failed_steps'],'unsettled_steps':[],
 'scope':'Original missing-file read remains a failed attempt. This recheck neither creates that missing file nor erases the error.'})
prompt=('上一轮实际草稿检查记录已保留，其中读取不存在的 implementation-alignment.md 返回错误，不能计作成功读取。'
 '请只沿 SKILL.md 现有索引读取实际参考，重新核对原事项的准备/检查结果及草稿边界；没有任何新的业务事实或接受。'
 '不得创建那个不存在的参考文件或别名，不重做业务实现或验证，不改修订身份与前驱，不提交。'
 '仅对现有草稿作这一有限复核并说明实际结果。当前事项为 '+info['work_item_id']+'。')
(evidence/'user-input.txt').write_text(prompt,encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def observe():
    model=yaml.safe_load((alignment_root/info['model_path']).read_text(encoding='utf-8'))
    revision=model['revision'];identity=revision==info['alignment_revision']
    sources={str(p):sha(p) for name in ['front','back','frontend-work','backend-work'] for p in (fixture/name).rglob('*.py') if '.agents' not in p.parts}
    unchanged=sources==info['source_files']
    heads=all(subprocess.run(['git','rev-parse','HEAD'],cwd=p,check=True,capture_output=True,text=True).stdout.strip()==h for p,h in info['integration_heads'].items())
    same_counter=Path(info['counter_path']).read_text()==info['counter_expected']
    return {'reached':identity and unchanged and heads and same_counter,'same_draft_revision_and_predecessor':identity,
     'source_inventory_and_bytes_unchanged':unchanged,'integration_heads_unchanged':heads,'verification_counter_unchanged':same_counter,
     'alignment_revision':revision,'scope':'Boundary checks only; actual operation-binding investigation and continuation require native review.'}
receipt=run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe',project=project,prompt=prompt,
 evidence=evidence/'execution',observe_endpoint=observe,model='gemini-3.8-flash-low',conversation_id=conversation,timeout=420,max_continuations=0,permission_mode='auto_approve')
(evidence/'author-response.md').write_text(receipt['last_result'].get('response',''),encoding='utf-8')
events=[json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json',assess_turn(events)['tool_steps']);endpoint=observe();dump(evidence/'endpoint.json',endpoint)
for relative in info['alignment_paths']:
    target=evidence/'after-alignment'/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(alignment_root/relative,target)
if not receipt['mechanical_passed'] or not endpoint['reached']:
    print(json.dumps({'mechanical_passed':receipt['mechanical_passed'],'endpoint':endpoint},ensure_ascii=False));raise SystemExit(1)
sources={name:{'path':str(evidence/name),'role':role} for name,role in [('registration.json','original_input'),
 ('setup-boundary.json','original_input'),('user-input.txt','user_input'),('author-response.md','author_response'),
 ('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]}
outputs=['author-response.md','tool-steps.json','endpoint.json']
for group,role in [('before-alignment','original_input'),('after-alignment','author_artifact')]:
    for p in (evidence/group).rglob('*'):
        if p.is_file():
            key=p.relative_to(evidence).as_posix();sources[key]={'path':str(p),'role':role}
            if role=='author_artifact':outputs.append(key)
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
case=next(r for r in catalog['cases'] if r['case_id']=='GF-GUIDANCE-ALIGNMENT-DRAFT')
criteria={k:case[k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'预配置真实草稿的公开绑定调查和原修订续作，根Python源码未迁移；初始语义判断是公开合成前提，不证明完整实现接受。',
 'machine_checks':{k:endpoint[k] for k in ['same_draft_revision_and_predecessor','source_inventory_and_bytes_unchanged','integration_heads_unchanged','verification_counter_unchanged']}}
dump(evidence/'review-spec.json',{'sources':sources,'cases':[criteria]})
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=600)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'owner_accepted':False,'catalog_updated':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(r['summary']['status']=='passed' for r in review['cases']) else 1)
