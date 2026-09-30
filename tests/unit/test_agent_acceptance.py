import json
import queue
from pathlib import Path
import pytest

from scripts import agent_acceptance
from scripts.agent_acceptance import assess_turn


def tool(index, state, name='run_command'):
    return {'event': 'step_update', 'step_update': {
        'conversation_id': 'captured-session', 'step_index': index,
        'step_type': 'tool', 'tool_name': name, 'state': state}}


def result(response='Completed.', **fields):
    return {'event': 'result', 'result': {
        'status': 'SUCCESS', 'response': response, **fields}}


def test_original_waiting_trace_is_not_complete_even_with_success_and_response():
    # Minimized c372c68eeb23 trace: command 98 remains ACTIVE at result.
    events = [tool(98, 'ACTIVE'), tool(100, 'ACTIVE', 'manage_task'),
              tool(100, 'DONE', 'manage_task'), result('正在等待 Strixnova CLI 处理评估结果。')]
    assert assess_turn(events, scenario_reached=False)['tool_flow_complete'] is False


def test_finished_turn_is_not_a_pass_without_scenario_evidence():
    events = [tool(2, 'ACTIVE'), tool(2, 'DONE'), result()]
    assert assess_turn(events)['scenario_passed'] is False
    assert assess_turn(events, scenario_reached=False)['scenario_passed'] is False


def test_finished_tools_and_observed_endpoint_can_pass():
    events = [tool(2, 'ACTIVE'), tool(2, 'DONE'), result()]
    assert assess_turn(events, scenario_reached=True)['scenario_passed'] is True


def test_observed_file_effect_does_not_require_a_second_natural_language_completion_claim():
    events = [tool(2, 'DONE', 'write_to_file'), result('')]
    assert assess_turn(events, scenario_reached=True)['scenario_passed'] is True
    assert assess_turn(events)['scenario_passed'] is False


def test_native_terminal_finish_is_settled_by_the_same_conversation_success():
    events = [tool(3, 'ACTIVE', 'finish'), result('{}', conversation_id='captured-session')]
    assert assess_turn(events, scenario_reached=True)['scenario_passed'] is True
    assert assess_turn([tool(2, 'ACTIVE'), *events], scenario_reached=True)['scenario_passed'] is False
    assert assess_turn(events[:-1], scenario_reached=True)['scenario_passed'] is False


def test_permission_denial_cannot_pass_even_if_endpoint_already_exists():
    events = [result(denied_actions=[{'action': 'command'}])]
    assert assess_turn(events, scenario_reached=True)['scenario_passed'] is False


@pytest.mark.parametrize('variant', ['valid', 'invalid_output', 'different_schema', 'different_session',
                                    'no_expected_schema', 'real_tool_failed', 'no_endpoint', 'late_error'])
def test_final_valid_structured_output_settles_only_earlier_finish_argument_errors(variant):
    schema = {'type': 'object', 'required': ['answer'], 'additionalProperties': False,
              'properties': {'answer': {'type': 'string'}}}
    failed = tool(70, 'ERROR', 'finish')
    failed['step_update']['tool_info'] = {'error': {'type': 'TOOL_ERROR',
        'message': "invalid arguments:\n- missing property 'answer'"}}
    terminal = result(conversation_id='captured-session', json_schema=schema,
                      structured_output={'answer': 'Native corrected output'})
    if variant == 'invalid_output': terminal['result']['structured_output'] = {'wrong': 'field'}
    if variant == 'different_schema': terminal['result']['json_schema'] = {'type': 'object'}
    if variant == 'different_session': terminal['result']['conversation_id'] = 'another-session'
    events = [failed, terminal]
    if variant == 'real_tool_failed': events.insert(0, tool(69, 'ERROR'))
    if variant == 'late_error': events = [terminal, failed]
    verdict = assess_turn(events, scenario_reached=variant != 'no_endpoint',
                          expected_output_schema=None if variant == 'no_expected_schema' else schema)
    assert verdict['scenario_passed'] is (variant == 'valid')
    assert failed['step_update'] in verdict['failed_steps']
    if variant == 'valid': assert verdict['recovered_finish_errors'] == [failed['step_update']]


def test_cancellation_is_not_a_completed_tool_flow():
    events = [tool(2, 'ACTIVE'), tool(2, 'CANCELED'), result()]
    assert assess_turn(events, scenario_reached=True)['tool_flow_complete'] is False


def test_later_completion_settles_the_original_step_without_duplicate_execution():
    events = [tool(2, 'ACTIVE'), result('Waiting.'), tool(2, 'DONE'), result()]
    assert assess_turn(events, scenario_reached=True)['scenario_passed'] is True


def test_reused_step_index_in_another_conversation_does_not_hide_pending_command():
    other = tool(2, 'DONE')
    other['step_update']['conversation_id'] = 'different-session'
    assert assess_turn([tool(2, 'ACTIVE'), other, result()], scenario_reached=True)['scenario_passed'] is False


def test_recovered_timer_conflict_is_retained_without_hiding_a_completed_command():
    events = [tool(2, 'ACTIVE'), tool(3, 'ACTIVE', 'schedule'),
              tool(4, 'ERROR', 'schedule'), tool(2, 'DONE'), tool(3, 'DONE', 'schedule'), result()]
    verdict = assess_turn(events, scenario_reached=True)
    assert verdict['scenario_passed'] is True
    assert len(verdict['wait_tool_errors']) == 1
    assert assess_turn(events, scenario_reached=False)['scenario_passed'] is False


def test_timer_error_never_settles_a_still_running_command():
    events = [tool(2, 'ACTIVE'), tool(3, 'ERROR', 'schedule'), result()]
    assert assess_turn(events, scenario_reached=True)['scenario_passed'] is False


def file_read(index, state, path='D:/fixture/source-catalog.json'):
    event = tool(index, state, 'view_file')
    event['step_update']['tool_info'] = {'parameters': {'AbsolutePath': path}}
    if state == 'ERROR':
        event['step_update']['error'] = {'type': 'TOOL_ERROR',
            'message': 'ContentOffset 40000 exceeds line range size 30278'}
    return event


def test_successful_reread_of_the_same_file_retains_the_recovered_error():
    # Captured 00f29ff12fd9 PRD trace: failed range 16, successful read 18.
    failed = file_read(16, 'ERROR')
    verdict = assess_turn([failed, file_read(18, 'DONE'), result()], scenario_reached=True)
    assert verdict['scenario_passed'] is True
    assert verdict['failed_steps'] == [failed['step_update']]
    assert verdict['recovered_read_errors'] == [failed['step_update']]


def test_other_file_session_or_earlier_success_does_not_recover_a_read():
    failed = file_read(16, 'ERROR')
    other_session = file_read(18, 'DONE')
    other_session['step_update']['conversation_id'] = 'other-session'
    for events in ([failed, file_read(18, 'DONE', 'D:/fixture/other.json')],
                   [failed, other_session], [file_read(15, 'DONE'), failed]):
        assert assess_turn([*events, result()], scenario_reached=True)['scenario_passed'] is False


def test_reread_cannot_hide_denial_cancellation_or_failed_write():
    for failure in [file_read(16, 'CANCELED'), tool(16, 'ERROR', 'write_to_file')]:
        assert assess_turn([failure, file_read(18, 'DONE'), result()],
                           scenario_reached=True)['scenario_passed'] is False
    denied = file_read(16, 'ERROR')
    denied['step_update']['error']['message'] = 'permission check failed: user denied permission'
    assert assess_turn([denied, file_read(18, 'DONE'), result()],
                       scenario_reached=True)['scenario_passed'] is False


class FakeHost:
    """Transport fake only; scene acceptance still uses the real driver policy."""
    def __init__(self, turns):
        self.turns = iter(turns)
        self.lines = queue.Queue()
        self.stdout = self
        self.stdin = self
        self.sent = []

    def __iter__(self):
        while (line := self.lines.get()) is not None:
            yield line

    def write(self, line):
        self.sent.append(json.loads(line)['message']['content'])

    def flush(self):
        for event in next(self.turns, []):
            self.lines.put(json.dumps(event) + '\n')

    def close(self):
        self.lines.put(None)

    def wait(self, timeout):
        return 0


def drive(tmp_path, monkeypatch, host, observer, **options):
    monkeypatch.setattr(agent_acceptance.subprocess, 'Popen', lambda *a, **kw: host)
    return agent_acceptance.run_session(binary=Path('fake-agy'), project=tmp_path,
        prompt='Original task.', evidence=tmp_path/'evidence', observe_endpoint=observer,
        model='test-only', timeout=options.pop('timeout', 5), resume_grace=0, **options)


def test_driver_finishes_after_same_file_reread_without_another_prompt(tmp_path, monkeypatch):
    host = FakeHost([[file_read(16, 'ERROR'), file_read(18, 'DONE'), result()]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': True}, max_continuations=0)
    assert record['mechanical_passed'] is True
    assert len(host.sent) == 1
    assert record['semantic_review'] == 'pending'


def test_driver_continues_neutrally_and_never_sends_observer_business_facts(tmp_path, monkeypatch):
    host = FakeHost([[tool(2, 'ACTIVE'), result('Waiting.')],
                     [tool(2, 'DONE'), result('Finished.')]])
    record = drive(tmp_path, monkeypatch, host,
        lambda: {'reached': True, 'private_business_hint': 'submit VC-002'})
    assert record['mechanical_passed'] is True
    assert host.sent[1:] == [agent_acceptance.NEUTRAL_CONTINUATION]
    assert 'submit VC-002' not in ''.join(host.sent)
    assert record['semantic_review'] == 'pending'


def test_driver_stops_on_denial_without_retrying(tmp_path, monkeypatch):
    host = FakeHost([[result(denied_actions=[{'action': 'command'}])]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': False})
    assert record['outcome'] == 'permission_blocked'
    assert record['mechanical_passed'] is False
    assert len(host.sent) == 1


def test_driver_bounds_neutral_continuation_instead_of_looping_until_green(tmp_path, monkeypatch):
    host = FakeHost([[result('Waiting.')], [result('Waiting.')]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': False}, max_continuations=1)
    assert record['outcome'] == 'continuation_limit'
    assert record['mechanical_passed'] is False
    assert len(host.sent) == 2


def test_driver_records_oracle_failure_instead_of_losing_receipt(tmp_path, monkeypatch):
    host = FakeHost([[result()]])
    def broken_observer():
        raise RuntimeError('read-only observation unavailable')
    record = drive(tmp_path, monkeypatch, host, broken_observer)
    assert record['outcome'] == 'observer_error'
    assert record['mechanical_passed'] is False
    assert (tmp_path/'evidence/driver-receipt.json').exists()


def test_driver_records_explicit_effort_in_actual_host_arguments(tmp_path, monkeypatch):
    host = FakeHost([[result()]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': True}, effort='high')
    assert record['requested_effort'] == 'high'
    index = record['argv'].index('--effort')
    assert record['argv'][index + 1] == 'high'


def test_driver_resumes_exact_conversation_without_creating_another_project(tmp_path, monkeypatch):
    host = FakeHost([[result()]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': True}, conversation_id='prior-review-session')
    assert '--new-project' not in record['argv']
    assert record['argv'][record['argv'].index('--conversation') + 1] == 'prior-review-session'
    assert record['semantic_review'] == 'pending'


def test_driver_selects_explicit_review_profile_without_changing_model(tmp_path, monkeypatch):
    host = FakeHost([[result()]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': True}, agent_name='document-reviewer')
    assert record['argv'][record['argv'].index('--agent') + 1] == 'document-reviewer'
    assert record['argv'][record['argv'].index('--model') + 1] == 'test-only'


def output_precheck_trace(path='D:/fixture/review.json'):
    missing = file_read(120, 'ERROR', path)
    missing['step_update']['error']['message'] = 'The system cannot find the file specified.'
    written = tool(160, 'DONE', 'write_to_file')
    written['step_update']['tool_info'] = {'parameters': {'TargetFile': path}}
    return missing, written


def test_declared_new_output_probe_can_finish_after_write_and_verified_endpoint():
    missing, written = output_precheck_trace()
    verdict = assess_turn([missing, written, result()], scenario_reached=True,
                          new_output_paths=('D:/fixture/review.json',))
    assert verdict['scenario_passed'] is True
    assert verdict['recovered_output_prechecks'] == [missing['step_update']]
    assert verdict['recovered_read_errors'] == []
    assert verdict['failed_steps'] == [missing['step_update']]


def test_created_file_cannot_hide_missing_input_or_unconfirmed_endpoint():
    missing, written = output_precheck_trace()
    for options in [{}, {'scenario_reached': True},
                    {'scenario_reached': False, 'new_output_paths': ('D:/fixture/review.json',)},
                    {'scenario_reached': True, 'new_output_paths': ('D:/fixture/other.json',)}]:
        assert not assess_turn([missing, written, result()], **options)['tool_flow_complete']


def test_output_probe_does_not_recover_denial_cancel_failed_write_or_other_actor():
    for variant in ['denied', 'canceled', 'failed_write', 'other_actor']:
        missing, written = output_precheck_trace()
        if variant == 'denied':missing['step_update']['error']['message'] += ' permission denied'
        if variant == 'canceled':missing['step_update']['state'] = 'CANCELED'
        if variant == 'failed_write':written['step_update']['state'] = 'ERROR'
        if variant == 'other_actor':written['step_update']['conversation_id'] = 'different-session'
        verdict = assess_turn([missing, written, result()], scenario_reached=True,
                              new_output_paths=('D:/fixture/review.json',))
        assert verdict['scenario_passed'] is False
        assert verdict['recovered_output_prechecks'] == []


def test_session_rejects_existing_or_outside_declared_new_output(tmp_path, monkeypatch):
    existing = tmp_path/'existing.json';existing.write_text('{}')
    for path in [existing, tmp_path.parent/'outside.json']:
        try:
            drive(tmp_path, monkeypatch, FakeHost([]), lambda: {'reached': True}, new_output_paths=(path,))
        except ValueError:
            pass
        else:
            raise AssertionError('Unsafe new-output declaration accepted')


def test_auto_approval_is_per_process_and_recorded(tmp_path, monkeypatch):
    host = FakeHost([[result()]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': True},
                   permission_mode='auto_approve')
    assert '--dangerously-skip-permissions' in record['argv']
    assert record['permission_mode'] == 'auto_approve'
    assert record['os_isolation_verified'] is False


def test_observer_failure_is_a_harness_error_not_a_product_failure(tmp_path, monkeypatch):
    def broken():
        raise ValueError('invalid checker input')
    record = drive(tmp_path, monkeypatch, FakeHost([[result()]]), broken)
    assert record['failure_layer'] == 'harness'


def test_denied_tool_is_an_execution_environment_failure(tmp_path, monkeypatch):
    host = FakeHost([[result(denied_actions=[{'action': 'command'}])]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': False})
    assert record['failure_layer'] == 'execution_environment'


def test_unknown_endpoint_failure_does_not_invent_a_product_diagnosis(tmp_path, monkeypatch):
    record = drive(tmp_path, monkeypatch, FakeHost([[result()]]),
                   lambda: {'reached': False}, max_continuations=0)
    assert record['failure_layer'] == 'undetermined'


@pytest.mark.parametrize('ending', ['deadline', 'normal_eof', 'failed_eof'])
def test_successful_repeated_reads_do_not_prove_an_environment_failure(tmp_path, monkeypatch, ending):
    # Captured UX c1b3af03450c: successful repeated reads, no result/error,
    # deadline, then normal exit. Replay only the terminal facts at the real
    # driver seam; this does not simulate or certify any Agent behaviour.
    class EndHost(FakeHost):
        def flush(self):
            super().flush()
            if ending != 'deadline':
                self.lines.put(None)

        def wait(self, timeout):
            return 1 if ending == 'failed_eof' else 0

    host = EndHost([[file_read(2, 'DONE'), file_read(4, 'DONE'), file_read(6, 'DONE')]])
    record = drive(tmp_path, monkeypatch, host, lambda: {'reached': False},
                   timeout=0.1, max_continuations=0)
    assert record['outcome'] == ('deadline' if ending == 'deadline' else 'host_exited_before_endpoint')
    assert record['mechanical_passed'] is False
    assert record['failure_layer'] == ('execution_environment' if ending == 'failed_eof' else 'undetermined')
    assert record['verdict']['failed_steps'] == []
    assert record['semantic_review'] == 'pending'
    assert len(host.sent) == 1
