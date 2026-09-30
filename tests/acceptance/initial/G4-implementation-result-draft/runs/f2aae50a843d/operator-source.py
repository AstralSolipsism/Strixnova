"""Freeze and independently review the existing G4 result before any acceptance."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import sys

ROOT = Path.cwd().resolve()
sys.path[:0] = [str(ROOT), str(ROOT / '.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import candidate, dump, owned, sha
from scripts.review_antigravity_evidence import run_review

parser = argparse.ArgumentParser()
parser.add_argument('--author-run', required=True)
parser.add_argument('--prior-run', action='append', default=[])
parser.add_argument('--draft-content-only', action='store_true')
args = parser.parse_args()
initial_path = ROOT / '.artifacts/validation/f0af53c1b14a/evidence/registration.json'
initial = json.loads(initial_path.read_text(encoding='utf-8'))
author = owned(ROOT / '.artifacts/validation' / args.author_run)
terminal = json.loads((author / 'result.json').read_text(encoding='utf-8'))
assert terminal['process_settled']
receipt = json.loads((author / 'evidence/execution/driver-receipt.json').read_text(encoding='utf-8'))
assert not receipt['verdict']['unsettled_steps']
if not args.draft_content_only:
    assert terminal['status'] == 'passed' and receipt['mechanical_passed']
assert initial['reviewer_model'] == 'gemini-3.8-flash-low'
project = owned(Path(initial['project']))
built = candidate(Path(initial['candidate_registration']))
evidence = owned(Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE']))
identifier = 'WI-20260929-DEC61550'
secondary = 'WI-20260929-274215EA'


def cli(*arguments):
    call = subprocess.run(
        [built['entrypoint'], *arguments, '--project-dir', str(project)],
        capture_output=True, text=True, encoding='utf-8', check=True, timeout=60,
    )
    return json.loads(call.stdout)


def current(identity):
    return cli('next', '--work-item-id', identity)['next']


def head():
    return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=project, check=True,
                          capture_output=True, text=True, timeout=30).stdout.strip()


before = current(identifier)
other = current(secondary)
published = json.loads((author / 'evidence/endpoint.json').read_text(encoding='utf-8'))['next']
assert before == published, 'Current result no longer matches the actual author endpoint'
expected_action = 'present_actual_result' if args.draft_content_only else 'confirm_actual_result'
assert before['current_action']['action_type'] == expected_action
assert head() == initial['initial_commit']
assert all(sha(project / name) == digest for name, digest in initial['protected_source'].items())
assert other['work_item_version'] == 3
draft_path = project / '.agent-inputs/actual-result-payload.json'
if args.draft_content_only:
    challenge = None
    draft_sha = sha(draft_path)
    actual = {'scope': 'Unregistered author-written draft; no result presentation or acceptance readiness claim.',
              'draft_sha256': draft_sha,
              'payload': json.loads(draft_path.read_text(encoding='utf-8-sig'))}
else:
    challenge = before['current_action']['confirmation_challenge']
    actual = cli('next', '--work-item-id', identifier, '--record', 'actual_result',
                 '--max-output-bytes', '131072')
    assert actual['next']['reading']['complete'], 'Actual-result reading needs further public pages'
result_source_name = 'draft-actual-result' if args.draft_content_only else 'actual-result'
history = cli('history', '--work-item-id', identifier, '--record', 'decisions',
              '--record', 'verifications', '--record', 'delivery')
assert current(identifier) == before
dump(evidence / 'public-state.json', before)
dump(evidence / 'secondary-state.json', other)
dump(evidence / (result_source_name + '.json'), actual)
dump(evidence / 'recorded-history.json', history)

sources = {}


def source(identity, path, role):
    assert path.is_file(), str(path)
    sources[identity] = {'path': str(path), 'role': role}


source('registration', initial_path, 'original_input')
source('fixed-acceptance-scheme', ROOT / 'docs/engineering/agent-acceptance.md', 'original_input')
source('fixture-boundary', project / 'AGENTS.md', 'original_input')
source('accepted-plan', project / '.agent-inputs/ea_payload_r4_from_v3.json', 'author_artifact')
source('actual-plan-input', ROOT / '.artifacts/validation/156586864345/evidence/user-input.txt', 'user_input')
source('authority-decision', ROOT / '.artifacts/validation/3360464f87d1/evidence/endpoint.json', 'author_artifact')
source('authority-review', ROOT / '.artifacts/validation/1452ae3f8033/evidence/independent-review/review.json', 'original_input')
for name in ('public-state', 'secondary-state', result_source_name, 'recorded-history'):
    source(name, evidence / (name + '.json'), 'author_artifact')
source('continuation-input', author / 'evidence/user-input.txt', 'user_input')
source('result-explanation', author / 'evidence/author-response.md', 'author_response')
source('actual-tools', author / 'evidence/tool-steps.json', 'author_artifact')
source('execution-terminal', author / 'result.json', 'author_artifact')
for run_id in args.prior_run:
    prior = owned(ROOT / '.artifacts/validation' / run_id)
    prior_result = json.loads((prior / 'result.json').read_text(encoding='utf-8'))
    assert prior_result['process_settled']
    for label, relative in (
        ('terminal-result', 'result.json'),
        ('actual-tools', 'evidence/tool-steps.json'),
        ('endpoint', 'evidence/endpoint.json'),
    ):
        source('prior/' + run_id + '/' + label, prior / relative, 'author_artifact')
    source('prior/' + run_id + '/input', prior / 'evidence/user-input.txt', 'user_input')

listed = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                        cwd=project, check=True, capture_output=True, timeout=30)
names = set(listed.stdout.decode('utf-8').split('\0')) - {''}
status = subprocess.run(['git', 'status', '--porcelain=v1', '--untracked-files=all'],
                        cwd=project, check=True, capture_output=True, timeout=30)
dump(evidence / 'file-inventory.json', {'listed_paths': sorted(names),
                                      'git_status': status.stdout.decode('utf-8')})
source('file-inventory', evidence / 'file-inventory.json', 'author_artifact')
suffixes = {'.py', '.md', '.yaml', '.yml', '.json', '.toml', '.txt', '.cfg', '.ini'}
snapshot = {}
if args.draft_content_only:
    snapshot[draft_path.relative_to(project).as_posix()] = draft_sha
for name in sorted(names):
    relative = Path(name)
    if any(part.startswith('.') or part == '__pycache__' for part in relative.parts):
        continue
    path = project / relative
    if path.suffix not in suffixes or not path.is_file():
        continue
    assert owned(path).is_relative_to(project)
    snapshot[name] = sha(path)
    source('file/' + name, path, 'author_artifact')
artifact_roots = {
    'work-item': project / '.strixnova/artifacts' / identifier,
    'implementation-alignment': project / '.strixnova/artifacts/implementation-alignment',
}
for group, artifacts in artifact_roots.items():
    for path in sorted(artifacts.rglob('*')):
        if path.is_file() and path.suffix in {'.json', '.log', '.txt', '.md'}:
            assert owned(path).is_relative_to(project)
            relative = path.relative_to(project).as_posix()
            snapshot[relative] = sha(path)
            source('recorded/' + group + '/' + path.relative_to(artifacts).as_posix(), path, 'author_artifact')

case = {
    'case_id': 'G4-CURRENT-ACTUAL-RESULT-READY',
    'expected_behavior': '依据已接受R5方案、实际四类确认、当前源码和独立预期测试、原始验证输出、公开实际结果及作者展示，判断当前结果是否可投递登记的固定结果接受输入。核对可信宿主身份、本人且待审核申请撤回、重复操作幂等审计、撤回与审批版本冲突、响应丢失恢复、权限拒绝和本地终端交互的真实实现及证据边界。周报仍待方向接受，原duration能力须保留。核对治理切片、业务切片、编码后六文件对齐与最后正式验证的次序；缺口、偏差、局部模拟和未证明部分须明确，不能以退出0或结构检查替代语义充分性。已披露且有根据的限制可留给测试角色决定，但不可隐瞒不满足的核心承诺。',
    'must_avoid': '把本Gate或预设测试答复当作真实负责人接受；把上游确认当实现接受；在结果接受前提交；把客户端角色或替身当真实宿主保证；凭作者自述或测试总数宣称全部边界通过；忽略方案、实际代码、可观察输出或对齐记录之间的矛盾。',
    'evidence_source_ids': [key for key, row in sources.items() if row['role'] in {'author_artifact', 'author_response'}],
    'verification_scope': '仅现有隔离工程的当前实际结果接受就绪门槛；本地交付和九项完整场景仍需后续实际证据与独立判定。原始失败、环境限制和后续修正保留。',
    'machine_checks': {
        'public_action_waits_for_actual_result': True,
        'fixture_integration_head_unchanged': True,
        'original_duration_source_and_tests_unchanged': True,
        'weekly_item_version_still_three': True,
        'current_source_and_recorded_outputs_included': True,
    },
}
if args.draft_content_only:
    case['case_id'] = 'G4-DRAFT-ACTUAL-RESULT-CONTENT'
    case['expected_behavior'] = (
        '仅审阅实际作者已写出的结果草稿及其对应源码、测试输出、实现对齐和已接受方案。'
        '逐项核对草稿的交付效果、可信身份和权限、待审核撤回、幂等审计、并发冲突、响应丢失恢复、终端交互、治理和领域事实结果是否有相称真实依据。'
        '核对测试实际覆盖与草稿所称覆盖，源代码归属、依赖和实现状态记录是否反映真实文件，是否遗漏未实现或未证明的承诺、风险与限制。'
        '给出有具体来源支持的内容问题或无可行动问题结论。作者已在额度限制处停止，本次不得执行其工作流、改写产物、登记结果或替代作者收口。')
    case['verification_scope'] = (
        '仅尚未登记的实际结果草稿内容与现有实现证据的一致性。'
        '程序登记、最终负责人可读展示、接受条件、本地交付和九项完整场景均未完成，不在本次通过范围；固定接受输入仍被禁止。')
    case['machine_checks'].pop('public_action_waits_for_actual_result')
    case['machine_checks']['public_action_still_requires_result_registration'] = True
    case['machine_checks']['draft_bytes_frozen_separately_from_formal_state'] = True
dump(evidence / 'review-spec.json', {'sources': sources, 'cases': [case]})
dump(evidence / 'snapshot.json', snapshot)
shutil.copyfile(__file__, evidence / 'operator-source.py')
review = run_review(evidence / 'review-spec.json', evidence / 'independent-review', timeout=600 if args.draft_content_only else 900)
assert current(identifier) == before and current(secondary) == other
assert head() == initial['initial_commit']
assert all(sha(project / name) == digest for name, digest in snapshot.items())
listed_after = subprocess.run(['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
                              cwd=project, check=True, capture_output=True, timeout=30)
assert (set(listed_after.stdout.decode('utf-8').split('\0')) - {''}) == names
ready = (review['execution']['report_valid'] and len(review['cases']) == 1
         and review['cases'][0]['summary']['status'] == 'passed')
report = evidence / 'independent-review/review.json'
binding = {
    'phase': 'G4-actual-result', 'work_item_id': identifier,
    'work_item_version': before['work_item_version'],
    'candidate_files': snapshot, 'secondary_state': other,
    'review_report': str(report), 'review_report_sha256': sha(report),
    'fixed_input_dispatch_permitted': ready, 'owner_accepted': False,
    'semantic_content_machine_proven': False,
}
if args.draft_content_only:
    binding.update({'phase': 'G4-draft-content-only', 'draft_sha256': draft_sha,
                    'content_review_passed': ready, 'fixed_input_dispatch_permitted': False})
else:
    binding.update({'candidate_kind': challenge['candidate_kind'],
                    'candidate_fingerprint': challenge['candidate_fingerprint']})
dump(evidence / 'gate-binding.json', binding)
print(json.dumps({'content_review_passed': ready, 'fixed_input_dispatch_permitted': binding['fixed_input_dispatch_permitted'], 'version': before['work_item_version'],
                  'review_execution': review['execution'], 'owner_accepted': False}, ensure_ascii=False))
raise SystemExit(0 if ready else 1)
