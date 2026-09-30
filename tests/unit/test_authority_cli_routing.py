from types import SimpleNamespace

from click.testing import CliRunner

from strixnova import cli


def test_authority_without_kind_uses_the_current_authoring_kind(tmp_path, monkeypatch):
    calls = []
    adapter = SimpleNamespace(
        next_step=lambda _: {'work_item_version': 7, 'current_action': {
            'action_type': 'author_project_authority_candidate', 'authority_kind': 'domain_model'}},
        project_authority_candidate=lambda item, kind, **kwargs: calls.append((item, kind, kwargs)) or {'candidate': kind},
        project_authority_review_candidate=lambda *a, **k: {'wrong_route': True})
    monkeypatch.setattr(cli, '_adapter', lambda _: adapter)
    result = CliRunner().invoke(cli.main, ['authority', '--project-dir', str(tmp_path),
        '--work-item-id', 'WI-20260921-11111111', '--version', '7'])
    assert result.exit_code == 0, result.output
    assert calls == [('WI-20260921-11111111', 'domain_model', {'expected_version': 7})]


def test_authority_review_keeps_the_bundle_read_route(tmp_path, monkeypatch):
    calls = []
    adapter = SimpleNamespace(
        next_step=lambda _: {'current_action': {'action_type': 'review_project_authority_candidates'}},
        project_authority_review_candidate=lambda *a, **k: calls.append('bundle') or {'candidate': 'bundle'})
    monkeypatch.setattr(cli, '_adapter', lambda _: adapter)
    result = CliRunner().invoke(cli.main, ['authority', '--project-dir', str(tmp_path),
        '--work-item-id', 'WI-20260921-11111111', '--version', '7'])
    assert result.exit_code == 0, result.output
    assert calls == ['bundle']


def test_inferred_kind_does_not_replace_the_callers_expected_version(tmp_path, monkeypatch):
    calls = []
    adapter = SimpleNamespace(
        next_step=lambda _: {'work_item_version': 99, 'current_action': {
            'action_type': 'author_project_authority_candidate', 'authority_kind': 'target_architecture'}},
        project_authority_candidate=lambda item, kind, **kwargs: calls.append(kwargs['expected_version']) or {},
        project_authority_review_candidate=lambda *a, **k: {})
    monkeypatch.setattr(cli, '_adapter', lambda _: adapter)
    result = CliRunner().invoke(cli.main, ['authority', '--project-dir', str(tmp_path),
        '--work-item-id', 'WI-20260921-11111111', '--version', '7'])
    assert result.exit_code == 0, result.output
    assert calls == [7]
