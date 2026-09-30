import hashlib
import json
from pathlib import Path
import sys

import pytest

from scripts import native_method_test_probe as probe


def fixture_project(tmp_path, monkeypatch):
    monkeypatch.setattr(probe, 'ROOT', tmp_path)
    monkeypatch.setattr(probe, 'PYTHON', Path(sys.executable), raising=False)
    project = tmp_path / '.artifacts/antigravity-manual/fixture/project'
    (project / 'output').mkdir(parents=True)
    (project / 'evidence').mkdir()
    return project


def invoke(monkeypatch, project, *arguments):
    monkeypatch.setattr(sys, 'argv', ['native_method_test_probe.py', '--project', str(project), *arguments])
    return probe.main()


def receipts(project):
    rows = [json.loads(path.read_text(encoding='utf-8'))
            for path in (project.parent / 'test-runs').glob('*/receipt.json')]
    return sorted(rows, key=lambda row: row['started_at'])


def test_real_script_runs_preserve_each_actual_entry_and_overwritten_result(tmp_path, monkeypatch):
    project = fixture_project(tmp_path, monkeypatch)
    script = project / 'output/check.py'
    first_source = "from pathlib import Path\nimport os, sys\nPath('evidence/result.txt').write_text(sys.argv[1])\n(Path(os.environ['STRIXNOVA_PROBE_EVIDENCE']) / 'result.txt').write_text(sys.argv[1])\nprint('observed:' + sys.argv[1])\nraise SystemExit(1 if sys.argv[1] == 'failed' else 0)\n"
    script.write_text(first_source, encoding='utf-8')
    first_bytes = script.read_bytes()
    args = ['--script', 'output/check.py', '--artifact', 'evidence/result.txt', '--']
    assert invoke(monkeypatch, project, *args, 'failed') == 1
    first = receipts(project)[0]
    first_dir = Path(first['evidence_directory'])
    script.write_text(first_source + '# new candidate\n', encoding='utf-8')
    assert invoke(monkeypatch, project, *args, 'passed') == 0
    second = receipts(project)[1]
    assert first['argv'][4] == str(script)
    assert first['exit_code'] == 1 and second['exit_code'] == 0
    assert first['before_source_hashes']['output/check.py'] == hashlib.sha256(first_bytes).hexdigest()
    assert first['before_source_hashes'] != second['before_source_hashes']
    assert (first_dir / 'before/output/check.py').read_text() == first_source
    assert (first_dir / 'artifacts/evidence/result.txt').read_text() == 'failed'
    assert (first_dir / 'generated/result.txt').read_text() == 'failed'
    assert (Path(second['evidence_directory']) / 'generated/result.txt').read_text() == 'passed'
    assert (Path(second['evidence_directory']) / 'artifacts/evidence/result.txt').read_text() == 'passed'
    assert first['semantic_content_machine_proven'] is False


def test_real_input_drift_or_deletion_does_not_erase_completed_command_evidence(tmp_path, monkeypatch):
    project = fixture_project(tmp_path, monkeypatch)
    (project / 'first.txt').write_text('before')
    (project / 'second.txt').write_text('retained before run')
    (project / 'output/check.py').write_text("from pathlib import Path\nPath('first.txt').write_text('after')\nPath('second.txt').unlink()\nprint('command completed')\n")
    assert invoke(monkeypatch, project, '--script', 'output/check.py', '--source', 'first.txt', '--source', 'second.txt') == 1
    row, = receipts(project)
    assert row['exit_code'] == 0
    assert row['inputs_stable'] is False
    assert row['before_source_hashes']['first.txt'] != row['after_source_hashes']['first.txt']
    assert 'second.txt' not in row['after_source_hashes']
    assert row['source_capture_errors']
    saved = Path(row['evidence_directory'])
    assert (saved / 'before/second.txt').read_text() == 'retained before run'
    assert 'command completed' in (saved / 'stdout.log').read_text()


def test_outside_material_is_rejected_before_launch(tmp_path, monkeypatch):
    project = fixture_project(tmp_path, monkeypatch)
    (project / 'output/check.py').write_text("raise RuntimeError('must not run')")
    outside = project.parent / 'outside.txt'
    outside.write_text('not a declared project input')
    with pytest.raises(ValueError, match='inside'):
        invoke(monkeypatch, project, '--script', 'output/check.py', '--source', '../outside.txt')
    assert not list((project.parent / 'test-runs').glob('*/receipt.json'))


def test_existing_pytest_route_keeps_junit_and_original_source_scope(tmp_path, monkeypatch):
    project = fixture_project(tmp_path, monkeypatch)
    (project / 'pytest.ini').write_text('[pytest]\n')
    (project / 'tests').mkdir()
    (project / 'tests/test_example.py').write_text('def test_value():\n    assert 1 + 1 == 2\n')
    assert invoke(monkeypatch, project, '--', '-q', 'tests') == 0
    row, = receipts(project)
    assert '-m' in row['argv'] and 'pytest' in row['argv']
    assert set(row['before_source_hashes']) == {'tests/test_example.py'}
    assert (Path(row['evidence_directory']) / 'pytest.xml').is_file()
    assert row['inputs_stable'] is True
