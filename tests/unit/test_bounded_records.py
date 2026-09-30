import json
from pathlib import Path

from click.testing import CliRunner
import pytest

from strixnova.cli import main
from strixnova.host_adapter import HostAdapterError, LocalHostAdapter
from strixnova.workflow_authority import WorkflowAuthority
from strixnova.record_reading import RecordReadingError, bounded_next, digest


def setup_item(path, text='request'):
    item = WorkflowAuthority(path).create(title='Bounded read', raw_request=text)
    return LocalHostAdapter(path), item['work_item_id']


def call(path, identifier, *args):
    result = CliRunner().invoke(main, ['next', '--project-dir', str(path),
        '--work-item-id', identifier, *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)['next'], result.output


def test_allowed_parent_can_be_read_as_an_exact_child(tmp_path):
    adapter, identifier = setup_item(tmp_path)
    result = adapter.next_step(identifier, record_refs=['request.raw_request'])
    assert result['records']['request.raw_request'] == 'request'
    with pytest.raises(HostAdapterError) as error:
        adapter.next_step(identifier, record_refs=['request_secret.raw_request'])
    assert error.value.code == 'record_not_available_for_action'


def test_cli_default_never_dumps_an_oversized_record(tmp_path):
    _, identifier = setup_item(tmp_path, 'important ' * 3000)
    result, output = call(tmp_path, identifier, '--record', 'request')
    assert len(output.encode('utf-8')) <= 4096
    assert 'request' not in result['records']
    assert result['record_pages']['request']['unexpanded_refs']


def test_long_unicode_text_round_trips_without_cutting_json(tmp_path):
    original = ('中文🙂\\"\n' * 1200) + 'FINAL_REQUIRED_CONDITION'
    adapter, identifier = setup_item(tmp_path, original)
    root, output = call(tmp_path, identifier, '--record', 'request', '--max-output-bytes', '3072')
    entry = next(e for e in root['record_pages']['request']['entries'] if e['key'] == 'raw_request')
    ref = entry['ref']
    cursor = None
    chunks = []
    while True:
        args = ['--record', ref, '--max-output-bytes', '3072']
        if cursor:
            args += ['--cursor', cursor]
        page, output = call(tmp_path, identifier, *args)
        assert len(output.encode('utf-8')) <= 3072
        if ref in page['records']:
            chunks.append(page['records'][ref])
            break
        record = page['record_pages'][ref]
        chunks.append(record['text'])
        cursor = record['next_cursor']
        if cursor is None:
            break
    assert ''.join(chunks) == original


def test_input_contract_exposes_readable_schema_children(tmp_path):
    _, identifier = setup_item(tmp_path)
    result, _ = call(tmp_path, identifier)
    ref = result['current_action']['input_contract_ref']
    result, output = call(tmp_path, identifier, '--record', ref)
    assert len(output.encode('utf-8')) <= 4096
    while True:
        entries = result['record_pages'][ref]['entries']
        child = next((e['ref'] for e in entries if e['key'] == 'payload_schema'), None)
        if child:
            break
        cursor = result['record_pages'][ref]['next_cursor']
        assert cursor is not None
        result, output = call(tmp_path, identifier, '--record', ref, '--cursor', cursor)
        assert len(output.encode('utf-8')) <= 4096
    result, output = call(tmp_path, identifier, '--record', child)
    assert child in result['records'] or child in result['record_pages']


def test_too_small_budget_has_explicit_failure_not_truncated_output(tmp_path):
    adapter, identifier = setup_item(tmp_path)
    with pytest.raises(HostAdapterError) as error:
        adapter.next_step(identifier, record_refs=['request'], max_output_bytes=32)
    assert error.value.code == 'record_read_budget_invalid'


def base(version=1):
    return {'work_item_id': 'WI-20260921-00000000', 'work_item_version': version,
            'current_action': {'record_refs': ['plan']}, 'records': {}}


def test_array_pages_include_last_rule_and_every_item_exactly_once():
    values = [{'rule': f'RULE-{i}', 'body': 'must obey ' * 8} for i in range(80)]
    cursor = None
    found = []
    while True:
        page = bounded_next(base(), {'plan': ('plan', [], values)},
                            max_output_bytes=1800, cursor=cursor)
        assert len(json.dumps({'ok': True, 'next': page}, ensure_ascii=True, sort_keys=True).encode()) + 2 <= 1800
        record = page['record_pages']['plan']
        for entry in record['entries']:
            if 'value' in entry:
                found.append(entry['value'])
            else:
                child = bounded_next(base(), {entry['ref']: ('plan', [str(entry['index'])], values)},
                                     max_output_bytes=1800)
                found.append(child['records'][entry['ref']])
        cursor = record['next_cursor']
        if cursor is None:
            break
    assert found == values


@pytest.mark.parametrize('changed', ['version', 'content', 'scope'])
def test_cursor_rejects_changed_source_version_or_scope(changed):
    original = ['long content ' * 10 for _ in range(100)]
    page = bounded_next(base(), {'plan': ('plan', [], original)}, max_output_bytes=1400)
    cursor = page['record_pages']['plan']['next_cursor']
    value = original + ['new'] if changed == 'content' else original
    ref = 'another' if changed == 'scope' else 'plan'
    with pytest.raises(RecordReadingError) as error:
        bounded_next(base(2 if changed == 'version' else 1), {ref: (ref, [], value)},
                     max_output_bytes=1400, cursor=cursor)
    assert error.value.code == 'record_read_source_changed'


def test_child_content_hash_is_bound_to_the_same_parent_source():
    with pytest.raises(RecordReadingError) as error:
        bounded_next(base(), {'plan#/a': ('plan', ['a'], {'a': 1, 'b': 3})},
                     max_output_bytes=1500, expected_sha256=digest({'a': 1, 'b': 2}))
    assert error.value.code == 'record_read_source_changed'


def test_batches_share_one_budget_and_expose_unreturned_references():
    selection = {f'r{i}': (f'r{i}', [], 'payload ' * 500) for i in range(4)}
    page = bounded_next(base(), selection, max_output_bytes=1600)
    assert set(page['records']) | set(page['record_pages']) | set(page['reading']['unread_refs']) == set(selection)
    assert len(json.dumps({'ok': True, 'next': page}, ensure_ascii=True, sort_keys=True).encode()) + 2 <= 1600


def test_pointer_escaping_missing_and_null_are_distinct(tmp_path):
    adapter, identifier = setup_item(tmp_path)
    with pytest.raises(HostAdapterError) as error:
        adapter.next_step(identifier, record_refs=['request#/nonexistent'])
    assert error.value.code == 'record_path_missing'
    result = bounded_next(base(), {'plan#/a~1b/~0x': ('plan', ['a/b', '~x'], {'a/b': {'~x': None}})}, max_output_bytes=1500)
    assert result['records']['plan#/a~1b/~0x'] is None


def test_reading_is_side_effect_free_and_version_guard_is_enforced(tmp_path):
    adapter, identifier = setup_item(tmp_path, 'hello ' * 2000)
    before = adapter.coordinator.authority.get(identifier)
    adapter.next_step(identifier, record_refs=['request'], max_output_bytes=2048)
    assert adapter.coordinator.authority.get(identifier) == before
    with pytest.raises(HostAdapterError) as error:
        adapter.next_step(identifier, record_refs=['request'], max_output_bytes=2048, expected_version=999)
    assert error.value.code == 'record_read_source_changed'


def test_equal_content_with_reordered_object_keys_keeps_stable_page_offsets():
    source = {f'key-{i:03}': 'content ' * 15 for i in range(30)}
    reordered = dict(reversed(list(source.items())))
    first = bounded_next(base(), {'plan': ('plan', [], source)}, max_output_bytes=1600)
    cursor = first['record_pages']['plan']['next_cursor']
    normal = bounded_next(base(), {'plan': ('plan', [], source)}, max_output_bytes=1600, cursor=cursor)
    reordered_page = bounded_next(base(), {'plan': ('plan', [], reordered)}, max_output_bytes=1600, cursor=cursor)
    assert reordered_page == normal
