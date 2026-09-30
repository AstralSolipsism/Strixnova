"""Run a prepared document scenario; native reviews use the shared review path."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import sys
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review
from scripts.skill_bundle_manifest import directory_manifest


def probe_operations(events: list[dict], *, files: set[str], line_count: int) -> dict:
    """Check native terminal-call evidence, not the Agent's completion text."""
    def normalize(value):
        return os.path.normcase(os.path.normpath(value.strip()))
    expected = {normalize(value) for value in files}
    listed = counted = False
    for step in assess_turn(events).get('tool_steps', []):
        if step.get('tool_name') != 'run_command' or step.get('state') != 'DONE':
            continue
        info = step.get('tool_info') or {}
        if step.get('error') or info.get('error'):
            continue
        command = str((info.get('parameters') or {}).get('CommandLine') or '').casefold()
        output = str(info.get('output') or '')
        if 'get-childitem' in command and 'measure-object' in command:
            listed |= output.strip() == str(len(expected))
        if 'get-content' in command and 'source-index.txt' in command and 'measure-object' in command:
            counted |= output.strip() == str(line_count)
    return {'directory_query_observed': listed, 'line_count_observed': counted}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--permission-probe', action='store_true')
    parser.add_argument('--review-document', action='store_true')
    parser.add_argument('--attempt', type=int, default=1)
    args = parser.parse_args()
    if args.permission_probe and args.review_document:
        parser.error('Choose a permission probe or document review, not both')
    if args.attempt < 1:
        parser.error('attempt must be positive')
    project = args.workspace.resolve()
    if not project.is_relative_to(ROOT / '.artifacts/antigravity-manual') or project.name != 'project':
        raise ValueError('Only a prepared acceptance fixture is allowed')
    work = project.parent
    manifest = json.loads((work / 'input-manifest.json').read_text(encoding='utf-8'))
    scenario = manifest.get('scenario', 'GF-PRD-READING')
    if scenario not in {'GF-PRD-READING', 'GF-DOMAIN-READING'} and not (args.permission_probe and scenario == 'PERMISSION-PROBE'):
        raise ValueError('Unsupported reading scenario')
    document = 'DOMAIN.md' if scenario == 'GF-DOMAIN-READING' else 'PRD.md'
    label = 'permission-probe' if args.permission_probe else 'review-execution' if args.review_document else 'execution'
    evidence = work / (label if args.attempt == 1 else f'{label}-{args.attempt}')
    def sources_unchanged():
        inputs = {**manifest['source_files'], **manifest.get('generated_input_files', {})}
        unchanged = all((project / name).is_file() and
                   hashlib.sha256((project / name).read_bytes()).hexdigest() == digest
                   for name, digest in inputs.items())
        skill = manifest.get('skill_manifest')
        return unchanged and (skill is None or directory_manifest(project / '.agents/skills/strixnova')['sha256'] == skill['sha256'])
    if args.review_document:
        if not sources_unchanged():
            raise ValueError('Original sources changed')
        catalog = yaml.safe_load((ROOT / 'tests/acceptance/guided-formation-cases.yaml').read_text(encoding='utf-8'))
        case = next(c for c in catalog['cases'] if c['case_id'] == scenario)
        sources = {name: {'path': str(project / name), 'role': 'original_input'}
                   for name in manifest['source_files']}
        sources['candidate'] = {'path': str(project / 'docs/reading' / document), 'role': 'author_artifact'}
        spec = {'sources': sources, 'cases': [{
            'case_id': scenario, 'expected_behavior': case['expected_behavior'],
            'must_avoid': case['must_avoid'], 'evidence_source_ids': ['candidate'],
            'verification_scope': '原始来源与实际阅读文档双向语义核对，不证明业务工作流或负责人接受。',
            'machine_checks': {'original_sources_unchanged': True}}]}
        spec_path = work / f'review-spec-{args.attempt}.json'
        if spec_path.exists():
            raise ValueError('Review specification already exists; use a new attempt')
        spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding='utf-8')
        report = run_review(spec_path, evidence, timeout=1200)
        print(json.dumps(report['execution'], ensure_ascii=False))
        return 0 if report['execution']['report_valid'] else 1
    evidence.mkdir(exist_ok=False)
    outputs = project / 'docs/reading'
    outputs.mkdir(parents=True, exist_ok=True)
    required = ['permission-probe.txt'] if args.permission_probe else [document, 'run-report.md']
    if any((outputs / name).exists() for name in required):
        raise ValueError('Expected fresh output paths')
    (evidence / 'permission-plan.json').write_text(json.dumps({
        'mode': 'auto_approve', 'scope': 'this CLI process',
        'settings_modified': False, 'os_isolation_verified': False,
        'model': 'gemini-3.8-flash-low'}, indent=2), encoding='utf-8')
    prompt = (work / 'prompt.txt').read_text(encoding='utf-8')
    probe_files = {str(path.resolve()) for name in ('docs', '.agents') for path in (project / name).rglob('*') if path.is_file()}
    probe_line_count = len((project / 'source-index.txt').read_text(encoding='utf-8').splitlines()) if args.permission_probe else 0
    if args.permission_probe:
        prompt = ('这是权限通路检查，不是业务验收。不调用子Agent。请实际执行以下只读终端操作：\n'
            'Get-ChildItem -Path docs, .agents -Recurse -File | Measure-Object | Select-Object -ExpandProperty Count\n'
            'Get-Content -Path source-index.txt | Measure-Object -Line | Select-Object -ExpandProperty Lines\n'
            '然后用文件工具在 docs/reading/permission-probe.txt 写入 PERMISSION_PROBE_OK。'
            '操作限本夹具，不读父目录。失败如实报告，不把输出存在当成操作已执行。完成后结束。')
    def observe():
        unchanged = sources_unchanged()
        complete = all((outputs / name).is_file() and (outputs / name).stat().st_size > 0 for name in required)
        if args.permission_probe and complete:
            complete = (outputs / 'permission-probe.txt').read_text(encoding='utf-8').strip() == 'PERMISSION_PROBE_OK'
        probes = {}
        if args.permission_probe:
            stream = evidence / 'events.jsonl'
            events = [json.loads(line) for line in stream.read_text(encoding='utf-8').splitlines() if line.strip()] if stream.exists() else []
            probes = probe_operations(events, files=probe_files, line_count=probe_line_count)
            complete = complete and all(probes.values())
        return {'reached': unchanged and complete, 'sources_unchanged': unchanged,
                'outputs_present': complete, **probes, 'semantic_acceptance': 'pending'}
    print('Running Antigravity Gemini 3.8 Flash Low with per-process auto-approval.', flush=True)
    print('Evidence: ' + str(evidence), flush=True)
    receipt = run_session(binary=Path(os.environ['LOCALAPPDATA']) / 'agy/bin/agy.exe',
        project=project, prompt=prompt, evidence=evidence, observe_endpoint=observe,
        model='gemini-3.8-flash-low', timeout=180 if args.permission_probe else 1200,
        max_continuations=0 if args.permission_probe else 1,
        new_output_paths=tuple(outputs / name for name in required), permission_mode='auto_approve')
    (evidence / 'response.md').write_text(receipt['last_result'].get('response', ''), encoding='utf-8')
    final_check = observe()
    (evidence / 'endpoint-check.json').write_text(json.dumps(final_check, ensure_ascii=False, indent=2), encoding='utf-8')
    complete = receipt['mechanical_passed'] and final_check['reached']
    print(json.dumps({'outcome': receipt['outcome'], 'tool_execution_complete': complete,
        'acceptance': 'pending', 'scope': 'permission_probe_only' if args.permission_probe else scenario,
        'evidence': str(evidence)}, ensure_ascii=False))
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
