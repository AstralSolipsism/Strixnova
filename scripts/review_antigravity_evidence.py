"""One native semantic review of captured outputs; never retype original quotes."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.acceptance_evidence import source_record, numbered_source, declared_source_facts, attach_references, summarize_case
from scripts.agent_acceptance import run_session
from scripts.skill_bundle_manifest import directory_manifest


def review_schema(cases: list[dict]) -> dict:
    case_ids = [case['case_id'] for case in cases]
    # Supply the same output identities that the binder accepts. Original
    # criteria remain readable context, not evidence of the author's result.
    source_ids = list(dict.fromkeys(identity for case in cases for identity in case['evidence_source_ids']))
    reference = {'type': 'object', 'additionalProperties': False,
        'required': ['source_id', 'start_line', 'end_line'], 'properties': {
            'source_id': {'type': 'string', 'enum': source_ids},
            'start_line': {'type': 'integer', 'minimum': 1},
            'end_line': {'type': 'integer', 'minimum': 1}}}
    case = {'type': 'object', 'additionalProperties': False,
        'required': ['case_id', 'verdict', 'reason', 'references', 'issues', 'limitations'],
        'properties': {'case_id': {'type': 'string', 'enum': case_ids},
            'verdict': {'type': 'string', 'enum': ['passed', 'needs_revision', 'blocked']},
            'reason': {'type': 'string'}, 'limitations': {'type': 'array', 'items': {'type': 'string'}},
            'references': {'type': 'array', 'minItems': 1, 'items': reference},
            'issues': {'type': 'array', 'items': {'type': 'object', 'additionalProperties': False,
                'required': ['category', 'description'], 'properties': {
                    'category': {'type': 'string', 'enum': ['agent_output', 'product_behavior', 'undetermined']},
                    'description': {'type': 'string'}}}}}}
    return {'type': 'object', 'additionalProperties': False, 'required': ['cases'],
        'properties': {'cases': {'type': 'array', 'minItems': len(case_ids),
                               'maxItems': len(case_ids), 'items': case}}}


def run_review(spec_path: Path, output: Path, *, timeout: int = 600) -> dict:
    spec = json.loads(spec_path.read_text(encoding='utf-8'))
    cases = spec['cases']
    ids = [c['case_id'] for c in cases]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Unique case IDs required')
    # This prevents accidentally selecting the development root as cwd. It is
    # an operator guard, not a claim that the native process cannot escape cwd.
    output = output.resolve()
    if not output.is_relative_to(ROOT / '.artifacts'):
        raise ValueError('Review output must be a new artifacts directory')
    output.mkdir(parents=True, exist_ok=False)
    project = output / 'project'
    project.mkdir()
    # The CLI host discovers Git independently of Agent instructions. Without
    # a local repository it can scan the parent development checkout before
    # the first Agent event. Bound that discovery to the copied review inputs.
    git_env = {key: value for key, value in os.environ.items()
               if key not in {'GIT_DIR', 'GIT_WORK_TREE', 'GIT_COMMON_DIR'}}
    subprocess.run(['git', 'init', '--quiet', str(project)], env=git_env,
                   check=True, capture_output=True, timeout=30)
    detected = subprocess.run(['git', '-C', str(project), 'rev-parse', '--show-toplevel'],
                              env=git_env, check=True, capture_output=True,
                              text=True, encoding='utf-8', timeout=30)
    if Path(detected.stdout.strip()).resolve() != project:
        raise ValueError('Review repository discovery escaped its input directory')
    (output / 'repository-boundary.json').write_text(json.dumps({
        'project': str(project), 'git_root': str(project),
        'parent_repository_discovery_prevented': True,
        'os_isolation_verified': False}, indent=2), encoding='utf-8')
    sources = {}
    for identity, entry in spec['sources'].items():
        path = Path(entry['path']).resolve()
        if not path.is_relative_to(ROOT):
            raise ValueError('Source is outside the authorized repository')
        sources[identity] = source_record(identity, path.read_text(encoding='utf-8'), role=entry['role'])
    for case in cases:
        if not case['evidence_source_ids'] or not set(case['evidence_source_ids']) <= sources.keys():
            raise ValueError('Case output references are incomplete')
    skill = ROOT / 'strixnova/src/strixnova/resources/agent-skill/strixnova'
    shutil.copytree(skill, project / '.agents/skills/strixnova')
    # Keep the index small and every supplied path directly readable. Embedding
    # whole documents as escaped JSON strings forced the Agent to extract them
    # into temporary files, introducing failed reads and unnecessary writes.
    materials = project / 'sources'
    materials.mkdir()
    source_view = []
    for index, source in enumerate(sources.values(), 1):
        path = materials / f'{index:04d}.txt'
        path.write_text(numbered_source(source), encoding='utf-8')
        source_view.append({k: v for k, v in source.items() if k != 'text'} |
                           {'path': str(path.resolve()),
                            'line_count': len(source['text'].splitlines())})
    (project / 'sources.json').write_text(json.dumps(source_view, ensure_ascii=False, indent=2), encoding='utf-8')
    (project / 'criteria.json').write_text(json.dumps(cases, ensure_ascii=False, indent=2), encoding='utf-8')
    facts = declared_source_facts(sources)
    (project / 'source-facts.json').write_text(json.dumps(facts, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    (output / 'sources.json').write_text(json.dumps(sources, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'spec.json').write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
    protected = {p.relative_to(project).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                 for p in project.rglob('*') if p.is_file() and '.git' not in p.relative_to(project).parts}
    (output / 'input-manifest.json').write_text(json.dumps({
        'source_files': protected, 'skill_manifest': directory_manifest(skill)}, indent=2), encoding='utf-8')
    evidence = output / 'execution'
    def observe():
        unchanged = all((project / name).is_file() and
                        hashlib.sha256((project / name).read_bytes()).hexdigest() == digest
                        for name, digest in protected.items())
        return {'reached': unchanged, 'review_inputs_unchanged': unchanged,
                'scope': 'transport and source integrity only; structured review checked after return'}
    prompt = (
        f'你是独立Antigravity验收审阅者。本次唯一审阅目录是 {project}。'
        f'先读取 {project / ".agents/skills/strixnova/SKILL.md"}，再读取 {project / "criteria.json"} 与 {project / "sources.json"}。'
        'sources.json是材料索引，按各项path读取已附行号的文件；source_id仅为引用身份，不是本夹具文件路径。'
        '材料已经齐备，不需要导出临时文件、运行Git、建立事项或调用项目工作流；仅按本次criteria审阅冻结材料。'
        f'{project / "source-facts.json"} 提供程序从原始结构直接提取的数量和声明状态；不要自行猜测采用状态，也不必在理由中重抄统计数字。'
        '区分来源中的草稿、已确认、历史和被取代内容，忠实核对其含义；已有通过意见不约束你本次的独立判断。'
        '逐项对照原标准、实际输入和实际答复或产物给出判断；所有材料的role明确区分问题、原始来源和作者输出。'
        '先从原标准和输入识别实质承诺及适用的失败/恢复分支，再分别对应实际产物、执行观察和缺口。'
        '通过数量、覆盖标签、作者自述或另一个passed不能证明这些承诺已被覆盖；范围内缺失的路径不能改称范围外系统的未验证限制。'
        '如某标准要求实际执行、状态改变或文件结果，而材料只有操作说明，必须判blocked或needs_revision，不能以说明正确代替执行。'
        '判断严格限于verification_scope，不得把对话样例、规约结构或引用存在升级为完整工作流、用户接受或产品认证。'
        '你可以读取本夹具文件或使用只读终端；不访问父目录、其他项目，不改文件、不安装工具、不启动子Agent。'
        '最终只返回规定的JSON，不写报告文件。references只填source_id与起止行号；每项只能引用其evidence_source_ids。'
        '不要复制原文或提供quote字段，程序会从冻结来源直接提取。reason是你的语义判断，用自己的话解释。'
        '引用存在并不代表理由成立，仍需你审阅含义；issues明确区分Agent输出缺陷、已观察产品行为缺陷和原因未明。'
        '没有证据就说明缺口，不补造通过。每个case_id恰好一次。完成后停止。'
    )
    receipt = run_session(binary=Path(os.environ['LOCALAPPDATA']) / 'agy/bin/agy.exe',
        project=project, prompt=prompt, evidence=evidence, observe_endpoint=observe,
        model='gemini-3.8-flash-low', timeout=timeout, max_continuations=0,
        permission_mode='auto_approve', json_schema=review_schema(cases))
    raw = receipt['last_result'].get('response', '')
    (output / 'review-response.txt').write_text(raw, encoding='utf-8')
    report = report_from_receipt(spec, sources, receipt)
    (output / 'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def report_from_receipt(spec: dict, sources: dict, receipt: dict) -> dict:
    """Bind a native verdict to frozen sources without judging its meaning."""
    cases = spec['cases']
    ids = [case['case_id'] for case in cases]
    raw = receipt['last_result'].get('response', '')
    report = {'execution': {'mechanical_passed': receipt['mechanical_passed'],
                           'failure_layer': receipt['failure_layer'], 'outcome': receipt['outcome']},
              'cases': [], 'source_facts': declared_source_facts(sources), 'catalog_updated': False, 'semantic_content_machine_proven': False}
    if receipt['mechanical_passed']:
        try:
            parsed = receipt['last_result'].get('structured_output')
            if parsed is None:
                text = raw.strip()
                if text.startswith('```json') and text.endswith('```'):
                    text = text[7:-3].strip()
                parsed = json.loads(text)
            rows = parsed['cases']
            if len(rows) != len(ids) or {row['case_id'] for row in rows} != set(ids):
                raise ValueError('Reviewer case coverage does not match request')
            by_id = {c['case_id']: c for c in cases}
            for row in rows:
                case = by_id[row['case_id']]
                bound = attach_references(row, sources, allowed_ids=set(case['evidence_source_ids']))
                if row['verdict'] == 'passed' and row['issues']:
                    raise ValueError('Passed verdict with unresolved issues')
                bound['verification_scope'] = case['verification_scope']
                bound['summary'] = summarize_case(machine_checks={**case.get('machine_checks', {}),
                    'review_inputs_unchanged': receipt['final_observation']['review_inputs_unchanged'],
                    'references_resolved': True}, review=row, execution=receipt)
                report['cases'].append(bound)
        except (ValueError, KeyError, TypeError) as error:
            report['execution'].update(failure_layer='harness_or_review_format', report_valid=False,
                                       error=str(error))
    report['execution']['report_valid'] = len(report['cases']) == len(ids)
    return report


def reconsider_review(previous: Path, output: Path, feedback: str, *, timeout: int = 600) -> dict:
    """Resume the same native reviewer over unchanged evidence, retaining history."""
    previous, output = previous.resolve(), output.resolve()
    if not previous.is_relative_to(ROOT / '.artifacts') or not output.is_relative_to(ROOT / '.artifacts'):
        raise ValueError('Reconsideration must use owned artifacts')
    project = previous / 'project'
    spec = json.loads((previous / 'spec.json').read_text(encoding='utf-8'))
    sources = json.loads((previous / 'sources.json').read_text(encoding='utf-8'))
    protected = json.loads((previous / 'input-manifest.json').read_text(encoding='utf-8'))['source_files']
    def observe():
        same = all((project / name).is_file() and hashlib.sha256((project / name).read_bytes()).hexdigest() == digest
                   for name, digest in protected.items())
        return {'reached':same, 'review_inputs_unchanged':same}
    if not observe()['reached']:
        raise ValueError('Frozen review inputs changed')
    if spec['cases'] != json.loads((project / 'criteria.json').read_text(encoding='utf-8')):
        raise ValueError('Frozen review criteria changed')
    index = {row['source_id']:row for row in json.loads((project / 'sources.json').read_text(encoding='utf-8'))}
    if set(index) != set(sources) or any(source['sha256'] != index[identity]['sha256'] or
            hashlib.sha256(source['text'].encode('utf-8')).hexdigest() != source['sha256'] or
            Path(index[identity]['path']).read_text(encoding='utf-8') != numbered_source(source)
            for identity, source in sources.items()):
        raise ValueError('Frozen source records changed')
    prior = json.loads((previous / 'execution/driver-receipt.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True, exist_ok=False)
    (output / 'feedback.txt').write_text(feedback, encoding='utf-8')
    prompt = (f'继续你此前的独立审阅。原始报告已保存，不修改它或任何输入。本次仍只读 {project} 中的冻结材料。'
        '以下反馈是需要重新核对的问题，不预设通过或失败；请对照原criteria、实际来源与答复重新给出判断。'
        '若有不支持的断言，应列为问题并按原标准处理，不用改写审阅理由掩盖作者答复缺陷。'
        '不要补查外部文件或执行工作流。保留原验证范围、引用规则及JSON结构；理由不要求重抄原文。\n\n' + feedback)
    receipt = run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe', project=project,
        prompt=prompt, evidence=output/'execution', observe_endpoint=observe, model='gemini-3.8-flash-low',
        conversation_id=prior['last_result']['conversation_id'], timeout=timeout, max_continuations=0,
        permission_mode='auto_approve', json_schema=review_schema(spec['cases']))
    (output/'review-response.txt').write_text(receipt['last_result'].get('response',''), encoding='utf-8')
    report = report_from_receipt(spec, sources, receipt)
    report['supersedes_review'] = str(previous/'review.json')
    (output/'review.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--spec', type=Path)
    selection.add_argument('--reconsider', type=Path)
    parser.add_argument('--feedback-file', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--timeout', type=int, default=600)
    args = parser.parse_args()
    if args.reconsider:
        if not args.feedback_file:
            parser.error('--reconsider requires --feedback-file')
        report = reconsider_review(args.reconsider, args.output, args.feedback_file.read_text(encoding='utf-8'), timeout=args.timeout)
    else:
        if args.feedback_file:
            parser.error('--feedback-file requires --reconsider')
        report = run_review(args.spec, args.output, timeout=args.timeout)
    print(json.dumps({'output': str(args.output), 'execution': report['execution'],
        'cases': [{k: c[k] for k in ('case_id', 'verdict')} for c in report['cases']]}, ensure_ascii=False))
    return 0 if report['execution']['report_valid'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
