"""External Agent acceptance driver; never part of the Strixnova runtime."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from jsonschema import SchemaError, ValidationError, validate


NEUTRAL_CONTINUATION = (
    '请继续原来已授权的请求。先收取尚未结束操作的真实结果，'
    '不要重复已提交的操作；到达原请求要求的停止位置后说明实际结果。'
)
HOST_WAIT_GUIDANCE = (
    '宿主执行说明：若工具转为后台执行，查询状态不等于等待完成。'
    '请使用宿主提供的实际等待或唤醒工具（例如 schedule），'
    '收到真实完成结果后继续。不能仅用一段“正在等待”的回答代替等待。'
)


def assess_turn(events: list[dict], *, scenario_reached: bool | None = None,
                new_output_paths: tuple[str, ...] = (),
                expected_output_schema: dict | None = None) -> dict:
    """Classify transport completion independently of a read-only scenario oracle.

    This checks mechanical evidence, never the meaning of an Agent's answer.
    Keys include conversation identity because step indices can be reused.
    """
    results = [event['result'] for event in events if event.get('event') == 'result']
    last = results[-1] if results else {}
    steps = {}
    positions = {}
    for position, event in enumerate(events):
        step = event.get('step_update', {})
        if step.get('step_type') == 'tool':
            key = (step.get('conversation_id'), step.get('step_index'))
            steps[key] = {**steps.get(key, {}), **step}
            positions[key] = position
    # The native structured-output finish tool can remain ACTIVE in the event
    # stream because its successful result terminates that same conversation.
    # This is protocol completion, not evidence that any external tool settled.
    terminal_steps = [step for step in steps.values()
                      if step.get('tool_name') == 'finish' and step.get('state') == 'ACTIVE'
                      and last.get('status') == 'SUCCESS' and last.get('conversation_id')
                      and step.get('conversation_id') == last['conversation_id']]
    unsettled = [step for step in steps.values() if step.get('state') not in
                 {'DONE', 'CANCELED', 'CANCELLED', 'ERROR', 'FAILED'} and step not in terminal_steps]
    failed = [step for step in steps.values() if step.get('state') in
              {'CANCELED', 'CANCELLED', 'ERROR', 'FAILED'}]
    # A rejected duplicate timer does not undo the command whose completed
    # output it was waiting for. Keep this diagnostic; do not confuse it with
    # an unresolved/cancelled command or with endpoint evidence.
    wait_errors = [step for step in failed if step.get('state') == 'ERROR'
                   and step.get('tool_name') in {'schedule', 'wait', 'wait_5_seconds', 'manage_task', 'command_status'}]
    def file_read_key(step):
        if step.get('tool_name') != 'view_file':
            return None
        path = step.get('tool_info', {}).get('parameters', {}).get('AbsolutePath')
        if isinstance(path, str) and path:
            return step.get('conversation_id'), path
        return None

    def position_of(step):
        return positions[(step.get('conversation_id'), step.get('step_index'))]

    recovered_finish_errors = []
    if (expected_output_schema is not None and last.get('status') == 'SUCCESS'
        and last.get('conversation_id') and last.get('json_schema') == expected_output_schema
        and 'structured_output' in last):
        try:
            validate(last['structured_output'], expected_output_schema)
        except (ValidationError, SchemaError):
            pass
        else:
            result_position = max(index for index, event in enumerate(events) if event.get('event') == 'result')
            # finish only formats a response; its invalid-argument attempts do
            # not perform external actions. Keep them in failed_steps while a
            # later same-session, schema-validated terminal output settles the
            # protocol. Real tool failures and semantic judgments stay separate.
            recovered_finish_errors = [step for step in failed
                if step.get('state') == 'ERROR' and step.get('tool_name') == 'finish'
                and step.get('conversation_id') == last['conversation_id']
                and position_of(step) < result_position
                and (step.get('tool_info', {}).get('error') or {}).get('message', '').startswith('invalid arguments:')]

    recovered_reads = []
    recovered_output_prechecks = []
    output_paths = {os.path.normcase(os.path.normpath(path)) for path in new_output_paths}
    for step in failed:
        identity = file_read_key(step)
        error = step.get('error') or step.get('tool_info', {}).get('error') or {}
        message = json.dumps(error, ensure_ascii=False).casefold()
        denied = any(word in message for word in (
            'permission check failed', 'denied permission', 'permission denied', 'access denied',
            'access is denied', 'not authorized', 'unauthorized', 'forbidden', '拒绝访问'))
        if step.get('state') != 'ERROR' or identity is None or denied:
            continue
        # A later completed read of this exact file settles a bad range/read.
        # Other paths or sessions are not evidence of recovery. This says
        # nothing about the correctness or coverage of the resulting prose.
        if any(other.get('state') == 'DONE' and file_read_key(other) == identity
               and position_of(other) > position_of(step) for other in steps.values()):
            recovered_reads.append(step)
        elif (scenario_reached is True and os.path.normcase(os.path.normpath(identity[1])) in output_paths
              and any(word in message for word in ('cannot find the file specified', 'no such file or directory', 'file not found'))):
            # An expected new report was probed before creation, then actually
            # written. This does NOT count as reading a previously missing input.
            for other in steps.values():
                target = other.get('tool_info', {}).get('parameters', {}).get('TargetFile')
                if (other.get('state') == 'DONE' and other.get('tool_name') == 'write_to_file'
                    and other.get('conversation_id') == identity[0] and isinstance(target, str)
                    and os.path.normcase(os.path.normpath(target)) == os.path.normcase(os.path.normpath(identity[1]))
                    and position_of(other) > position_of(step)):
                    recovered_output_prechecks.append(step)
                    break
    blocking_failures = [step for step in failed
                         if step not in wait_errors and step not in recovered_reads
                         and step not in recovered_output_prechecks and step not in recovered_finish_errors]
    turn_returned = bool(last.get('status') == 'SUCCESS' and not last.get('denied_actions'))
    completed = turn_returned and not unsettled and not blocking_failures
    return {'turn_returned': turn_returned, 'tool_flow_complete': completed,
            'tool_steps': list(steps.values()),
            'terminal_protocol_steps': terminal_steps,
            'unsettled_steps': unsettled, 'failed_steps': failed,
            'wait_tool_errors': wait_errors,
            'recovered_read_errors': recovered_reads,
            'recovered_output_prechecks': recovered_output_prechecks,
            'recovered_finish_errors': recovered_finish_errors,
            'scenario_endpoint_reached': scenario_reached,
            'scenario_passed': completed and scenario_reached is True}


def run_session(*, binary: Path, project: Path, prompt: str, evidence: Path,
                observe_endpoint: Callable[[], dict], model: str,
                timeout: float = 900, max_continuations: int = 2,
                resume_grace: float = 25, effort: str | None = None,
                conversation_id: str | None = None, agent_name: str | None = None,
                new_output_paths: tuple[Path, ...] = (),
                permission_mode: str = 'host_default', json_schema: dict | None = None) -> dict:
    """Keep the host alive until a verified endpoint or a bounded failure.

    The observer may only read state. Its findings are never sent to the Agent.
    A fixed neutral continuation contains no scene-specific steps or answers.
    """
    if permission_mode not in {'host_default', 'auto_approve'}:
        raise ValueError('Unsupported permission mode')
    evidence.mkdir(parents=True, exist_ok=True)
    fresh_outputs = []
    for path in new_output_paths:
        resolved = path.resolve()
        if not resolved.is_relative_to(project.resolve()):
            raise ValueError('New outputs must be inside the scenario project')
        if resolved.exists():
            raise ValueError('New output already exists at session start')
        fresh_outputs.append(str(resolved))
    full_prompt = HOST_WAIT_GUIDANCE + '\n\n' + prompt
    (evidence / 'prompt.txt').write_text(full_prompt, encoding='utf-8')
    selection = ['--conversation', conversation_id] if conversation_id else ['--new-project']
    argv = [str(binary), *selection, '--model', model,
            '--input-format', 'stream-json', '--output-format', 'stream-json',
            '--print-timeout', f'{int(timeout)}s', '--log-file', str(evidence / 'host.log')]
    if effort is not None:
        if effort not in {'low', 'medium', 'high'}:
            raise ValueError('Unsupported reasoning effort')
        argv += ['--effort', effort]
    if agent_name is not None:
        argv += ['--agent', agent_name]
    if permission_mode == 'auto_approve':
        argv += ['--dangerously-skip-permissions']
    if json_schema is not None:
        schema_path = evidence / 'response-schema.json'
        schema_path.write_text(json.dumps(json_schema, ensure_ascii=False), encoding='utf-8')
        argv += ['--json-schema', str(schema_path.resolve())]
    events, observations, continuations = [], [], []
    incoming: queue.Queue = queue.Queue()
    started = time.monotonic()
    last_result_at = None
    outcome = 'deadline'
    protocol_errors = []
    forced = False
    result = {}
    def observe_safely():
        try:
            observed = observe_endpoint()
            if not isinstance(observed, dict) or not isinstance(observed.get('reached'), bool):
                raise ValueError('Endpoint observer must return a boolean reached field')
            return observed
        except Exception as error:
            return {'reached': False, 'observer_error': f'{type(error).__name__}: {error}'}

    environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    environment.pop('PYTHONPATH', None)
    with (evidence / 'stderr.txt').open('w', encoding='utf-8') as err:
        process = subprocess.Popen(argv, cwd=project, env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
            text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)

        def read_output():
            for line in process.stdout:
                incoming.put((time.monotonic()-started, line))
            incoming.put((time.monotonic()-started, None))

        def send(message):
            process.stdin.write(json.dumps({'event': 'user', 'message': {'content': message}},
                                           ensure_ascii=False) + '\n')
            process.stdin.flush()

        reader = threading.Thread(target=read_output, daemon=True)
        reader.start()
        send(full_prompt)
        try:
            with (evidence / 'events.jsonl').open('w', encoding='utf-8') as output:
                while time.monotonic()-started < timeout:
                    try:
                        elapsed, line = incoming.get(timeout=1)
                    except queue.Empty:
                        line = ''
                    if line is None:
                        outcome = 'host_exited_before_endpoint'
                        break
                    if line:
                        output.write(line)
                        output.flush()
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            protocol_errors.append(line)
                            outcome = 'invalid_event_stream'
                            break
                        events.append(event)
                        if event.get('event') == 'result':
                            result = event['result']
                            last_result_at = time.monotonic()
                            if result.get('denied_actions'):
                                outcome = 'permission_blocked'
                                break
                            if result.get('status') != 'SUCCESS':
                                outcome = 'host_error'
                                break
                            # Only determine eligibility here. The read-only
                            # observer must still confirm the actual endpoint
                            # before output prechecks can be reported recovered.
                            mechanical = assess_turn(events, scenario_reached=True if fresh_outputs else None,
                                                     new_output_paths=tuple(fresh_outputs), expected_output_schema=json_schema)
                            if mechanical['tool_flow_complete']:
                                observed = observe_safely()
                                observations.append({'elapsed': elapsed, **observed})
                                if observed.get('observer_error'):
                                    outcome = 'observer_error'
                                    break
                                if observed.get('reached') is True:
                                    outcome = 'endpoint_observed'
                                    break
                    if last_result_at and time.monotonic()-last_result_at >= resume_grace:
                        if len(continuations) >= max_continuations:
                            outcome = 'continuation_limit'
                            break
                        continuations.append({'elapsed': time.monotonic()-started,
                                              'prompt': NEUTRAL_CONTINUATION})
                        send(NEUTRAL_CONTINUATION)
                        last_result_at = None
        finally:
            try:
                process.stdin.close()
            except (OSError, BrokenPipeError):
                pass
            try:
                code = process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                forced = True
                process.terminate()
                code = process.wait(timeout=15)
            reader.join(timeout=5)
    final_observation = observe_safely()
    verdict = assess_turn(events, scenario_reached=final_observation.get('reached'),
                          new_output_paths=tuple(fresh_outputs), expected_output_schema=json_schema)
    record = {'outcome': outcome, 'exit_code': code, 'forced_termination': forced,
              'duration_seconds': round(time.monotonic()-started, 2),
              'verdict': verdict, 'final_observation': final_observation,
              'observations': observations, 'continuations': continuations,
              'human_business_intervention': False, 'semantic_review': 'pending',
              'protocol_errors': protocol_errors, 'last_result': result,
              'model': model, 'argv': argv}
    record['requested_effort'] = effort or 'host_default'
    record['permission_mode'] = permission_mode
    # A fixture directory and an approval flag are not an OS sandbox.
    record['os_isolation_verified'] = False
    record['mechanical_passed'] = (outcome == 'endpoint_observed' and code == 0
                                  and not forced and verdict['scenario_passed'])
    record['failure_layer'] = (
        None if record['mechanical_passed'] else
        'harness' if outcome in {'observer_error', 'invalid_event_stream'} else
        'execution_environment' if outcome in {'permission_blocked', 'host_error'}
        or (outcome == 'host_exited_before_endpoint' and code != 0) else
        # Budget expiry or normal exit without an endpoint establishes only
        # incompletion. It does not establish a platform or permission cause.
        'undetermined')
    (evidence / 'driver-receipt.json').write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
    return record
