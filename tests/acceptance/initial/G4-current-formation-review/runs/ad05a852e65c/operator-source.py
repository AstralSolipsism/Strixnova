"""Review observed G4 behavior and actual candidate existence before any acceptance."""
from pathlib import Path
import argparse,json,os,shutil,sys,yaml
ROOT=Path.cwd().resolve();sys.path[:0]=[str(ROOT),str(ROOT/'.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump
from scripts.review_antigravity_evidence import run_review
evidence=Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
parser=argparse.ArgumentParser()
for key in ['initial-run','clarification-run','formation-run']:parser.add_argument('--'+key,required=True)
parser.add_argument('--artifact-capture-run')
options=parser.parse_args()
first=(ROOT/'.artifacts/validation'/options.initial_run/'evidence').resolve()
clarification=(ROOT/'.artifacts/validation'/options.clarification_run/'evidence').resolve()
later=(ROOT/'.artifacts/validation'/options.formation_run/'evidence').resolve()
for directory in [first,clarification,later]:
    assert directory.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((directory.parent/'result.json').read_text(encoding='utf-8'))
    assert result['process_settled']
for directory in [first,later]:
    assert json.loads((directory.parent/'result.json').read_text(encoding='utf-8'))['status']=='passed'
for directory in [first,clarification/'clarify_read_only',later]:
    receipt=json.loads((directory/'execution/driver-receipt.json').read_text(encoding='utf-8'))
    endpoint=json.loads((directory/'endpoint.json').read_text(encoding='utf-8'))
    assert receipt['mechanical_passed'] and endpoint['business_source_and_git_unchanged']
assert json.loads((clarification/'clarify_read_only/endpoint.json').read_text(encoding='utf-8'))['read_only_correction_preserved']
assert (later/'candidate-after').is_dir()
before_docs=clarification/'before-docs'
definition=json.loads((first/'registration.json').read_text(encoding='utf-8'))
project=Path(definition['project']).resolve();assert project.is_relative_to(ROOT/'.artifacts/validation')

sources={};outputs=[]
for group,base in [('initial',first),('correction',clarification/'clarify_read_only'),('formation',later)]:
    for name,role in [('user-input.txt','user_input'),('author-response.md','author_response'),('tool-steps.json','author_artifact'),('endpoint.json','author_artifact')]:
        key=group+'/'+name;sources[key]={'path':str(base/name),'role':role}
        if role.startswith('author_'):outputs.append(key)
for group,base,role in [('before',before_docs,'original_input'),('candidate',later/'candidate-after','author_artifact')]:
    for path in sorted(base.rglob('*')):
        if path.is_file():
            key=group+'/'+path.relative_to(base).as_posix();sources[key]={'path':str(path),'role':role}
            if role=='author_artifact':outputs.append(key)
changed=[];unchanged=[]
for p in (later/'candidate-after').rglob('*'):
    if not p.is_file():continue
    rel=p.relative_to(later/'candidate-after');before=before_docs/rel
    (unchanged if before.is_file() and before.read_bytes()==p.read_bytes() else changed).append(rel.as_posix())
dump(evidence/'file-comparison.json',{'changed_or_created':sorted(changed),'unchanged':sorted(unchanged),
 'scope':'Byte identity only; no semantic conclusion or acceptance dispatch.'})
sources['actual-file-comparison']={'path':str(evidence/'file-comparison.json'),'role':'author_artifact'};outputs.append('actual-file-comparison')
sources['registration']={'path':str(first/'registration.json'),'role':'original_input'}
sources['execution-boundary']={'path':str(project/'AGENTS.md'),'role':'original_input'}
sources['quota-failure']={'path':str(clarification/'form_candidates/execution/driver-receipt.json'),'role':'original_input'}
sources['formation-continuity']={'path':str(later/'continuity-context.json'),'role':'original_input'}
if options.artifact_capture_run:
    capture=(ROOT/'.artifacts/validation'/options.artifact_capture_run).resolve()
    assert capture.is_relative_to(ROOT/'.artifacts/validation')
    result=json.loads((capture/'result.json').read_text(encoding='utf-8'))
    assert result['status']=='passed' and result['process_settled']
    provenance=json.loads((capture/'evidence/artifact-provenance.json').read_text(encoding='utf-8'))
    assert provenance['native_run']==options.formation_run
    sources['host-candidate-package']={'path':str(capture/'evidence'/provenance['captured_name']),'role':'author_artifact'}
    sources['host-artifact-provenance']={'path':str(capture/'evidence/artifact-provenance.json'),'role':'author_artifact'}
    outputs+=['host-candidate-package','host-artifact-provenance']
    boundary='宿主产物是单独 Markdown，项目候选前后文件字节比较另行提供。可以评价宿主产物中的内容，但不能把嵌入代码块当成相应项目路径已写入的文件，文件存在、公开接线和语义就绪分别核对。不得仅因文件未写入而捏造宿主产物中没有相应内容；也不得因此允许对旧文件投递新候选接受。'
    (evidence/'artifact-boundary.txt').write_text(boundary,encoding='utf-8')
    sources['artifact-boundary']={'path':str(evidence/'artifact-boundary.txt'),'role':'user_input'}
ids=['GF-CONCRETE-INCOMPLETE','GF-MULTIPLE-RESULTS','GF-CROSS-UNIT-ARCHITECTURE','GF-UPSTREAM-CORRECTION',
     'GF-PD-AUTHORITY-CORRECTION','GF-PRD-FORMATION','GF-PRD-CORRECTION','GF-DOMAIN-LANGUAGE-CORRECTION']
catalog=yaml.safe_load((ROOT/'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
by_id={row['case_id']:row for row in catalog['cases']}
cases=[{k:by_id[identity][k] for k in ['case_id','expected_behavior','must_avoid']}|{
 'evidence_source_ids':outputs,'verification_scope':'实际初次形成、只读术语纠正及随后候选起草；当前尚未投递任何新接受输入，实际存在的文件与口头规划必须分开。',
 'machine_checks':{'native_phases_settled':True,'source_and_git_boundaries_preserved':True}} for identity in ids]
cases.append({'case_id':'GATE-G4-COMPLETE-AUTHORITY-CANDIDATES',
 'expected_behavior':'用于固定接受输入的四类完整候选文件必须实际存在、各有新修订且可定位，内容覆盖已给定事实、引用闭合并已向负责人展示；实现对齐保持真实草稿。逐类独立检查完整性与语义一致性，仅规划清单或旧文件链接不能替代候选。',
 'must_avoid':'在候选未形成、身份不符、仍有重大矛盾或必要下游处置缺失时允许转交接受；把作者自述或PRD字段当实际模型文件。',
 'evidence_source_ids':outputs,'verification_scope':'当前完整包的独立语义就绪检查；不证明任何真实负责人接受。',
 'machine_checks':{'frozen_candidate_files_captured':True}})
dump(evidence/'review-spec.json',{'sources':sources,'cases':cases})
shutil.copyfile(__file__,evidence/'operator-source.py')
review=run_review(evidence/'review-spec.json',evidence/'independent-review',timeout=900)
summary={'execution':review['execution'],'cases':[{'case_id':r['case_id'],'verdict':r['verdict']} for r in review['cases']],
 'acceptance_input_dispatched':False,'catalog_updated':False,'owner_accepted':False}
dump(evidence/'group-summary.json',summary);print(json.dumps(summary,ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] else 1)
