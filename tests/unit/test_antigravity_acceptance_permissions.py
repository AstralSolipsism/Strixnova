"""The old command-spelling allowlist is retired; exercise the actual entrypoint."""
import json
from pathlib import Path
import sys
import pytest

from scripts import run_antigravity_acceptance as runner


def test_document_entrypoint_uses_per_run_permissions_without_accessing_home(tmp_path, monkeypatch):
    project = tmp_path / '.artifacts/antigravity-manual/test/project'
    project.mkdir(parents=True)
    (project.parent / 'input-manifest.json').write_text(json.dumps({'source_files': {}}))
    (project.parent / 'prompt.txt').write_text('fixture prompt')
    (project / 'source-index.txt').write_text('source.md\n')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['runner', '--workspace', str(project), '--permission-probe'])
    def forbidden_home():
        raise AssertionError('Must not edit per-user permission settings')
    monkeypatch.setattr(Path, 'home', forbidden_home)
    def fake_run(**kwargs):
        assert kwargs['permission_mode'] == 'auto_approve'
        assert kwargs['model'] == 'gemini-3.8-flash-low'
        assert 'Get-ChildItem -Path docs, .agents' in kwargs['prompt']
        assert '\nGet-Content -Path source-index.txt' in kwargs['prompt']
        assert not kwargs['observe_endpoint']()['reached']
        (project / 'docs/reading/permission-probe.txt').write_text('PERMISSION_PROBE_OK')
        events = [
            {'event': 'step_update', 'step_update': {'conversation_id': 'probe', 'step_index': index,
                'step_type': 'tool', 'tool_name': 'run_command', 'state': 'DONE',
                'tool_info': {'parameters': {'CommandLine': command}, 'output': output}}}
            for index, (command, output) in enumerate([
                ('Get-ChildItem -Path docs, .agents -Recurse -File | Measure-Object | Select-Object -ExpandProperty Count', '0\n'),
                ('Get-Content -Path source-index.txt | Measure-Object -Line | Select-Object -ExpandProperty Lines', '1\n'),
            ])]
        events.append({'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'done'}})
        (kwargs['evidence'] / 'events.jsonl').write_text('\n'.join(json.dumps(event) for event in events) + '\n')
        return {'last_result': {'response': 'done'}, 'outcome': 'endpoint_observed', 'mechanical_passed': True}
    monkeypatch.setattr(runner, 'run_session', fake_run)
    assert runner.main() == 0
    plan = json.loads((project.parent / 'permission-probe/permission-plan.json').read_text())
    assert plan['settings_modified'] is False
    assert plan['os_isolation_verified'] is False


def test_permission_marker_without_terminal_calls_is_not_a_pass(tmp_path, monkeypatch):
    project = tmp_path / '.artifacts/antigravity-manual/probe/project'
    project.mkdir(parents=True)
    (project.parent / 'input-manifest.json').write_text(json.dumps({'source_files': {}}))
    (project.parent / 'prompt.txt').write_text('probe')
    (project / 'source-index.txt').write_text('source.md\n')
    monkeypatch.setattr(runner, 'ROOT', tmp_path)
    monkeypatch.setattr(sys, 'argv', ['runner', '--workspace', str(project), '--permission-probe'])
    def only_wrote_a_marker(**kwargs):
        (project / 'docs/reading/permission-probe.txt').write_text('PERMISSION_PROBE_OK')
        (kwargs['evidence'] / 'events.jsonl').write_text(json.dumps({'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'done'}}) + '\n')
        return {'last_result': {'response': 'done'}, 'outcome': 'endpoint_observed', 'mechanical_passed': True}
    monkeypatch.setattr(runner, 'run_session', only_wrote_a_marker)
    assert runner.main() == 1


@pytest.mark.parametrize('missing', ['directory', 'count', 'wrong_output', 'error'])
def test_probe_does_not_infer_execution_from_a_partial_or_failed_trace(missing):
    rows = [
        {'event': 'step_update', 'step_update': {'conversation_id': 'probe', 'step_index': index,
         'step_type': 'tool', 'tool_name': 'run_command', 'state': 'DONE',
         'tool_info': {'parameters': {'CommandLine': command}, 'output': output}}}
        for index, (command, output) in enumerate([
            ('Get-ChildItem -Recurse | Measure-Object', '1\n'),
            ('Get-Content source-index.txt | Measure-Object -Line', '2\n'),
        ])]
    if missing == 'directory': rows.pop(0)
    elif missing == 'count': rows.pop()
    elif missing == 'wrong_output': rows[1]['step_update']['tool_info']['output'] = '99\n'
    else: rows[1]['step_update']['state'] = 'ERROR'
    rows.append({'event': 'result', 'result': {'status': 'SUCCESS', 'response': 'done'}})
    observed = runner.probe_operations(rows, files={'C:/fixture/docs/source.md'}, line_count=2)
    assert not all(observed.values())
