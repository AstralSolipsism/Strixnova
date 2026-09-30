import json
from pathlib import Path
import sqlite3
import pytest
import yaml
from copy import deepcopy

from strixnova.application_coordinator import ApplicationCoordinatorError
from strixnova.host_adapter import HostAdapterError, LocalHostAdapter
from strixnova.work_item_repositories import repository_phase
from tests.integration.test_multi_repository_planning import accept, plan_item, planning_project, plan_alignment_refresh
from tests.support.project_context import BACKEND, FRONTEND, git
from tests.support.governance_assessment import satisfied_governance_rule_results, refresh_single_slice, semantic_review_fixture
from tests.support.project_baseline import TEST_READER_MODULE_ID




def prepared_item(root: Path, *, verification: bool = False, alignment: bool = False, repository_order=None):
    project = planning_project(root)
    if repository_order is not None:
        project["assessment"]["delivery_plan"]["repository_order"] = repository_order
    if verification:
        for command in project["assessment"]["verification_commands"]:
            command["argv"] = [command["argv"][0], "-c", "from src import value; assert value() == 3"]
    if alignment:
        project['alignment_before'] = plan_alignment_refresh(project)
    adapter, item = plan_item(project)
    item = accept(adapter, item, "engineering_plan")
    for entry in item["data"]["repository_deliveries"]:
        identifier = entry["repository_id"]
        name = "backend-work" if identifier == BACKEND else "frontend-work"
        item = adapter.coordinator.delivery(item["work_item_id"], {
            "repository_id": identifier, "worktree_path": str(root / name),
        }, expected_version=item["version"])["work_item"]
    return project, adapter, adapter.coordinator.authority.get(item["work_item_id"])


def test_preparation_owns_two_worktrees_and_only_one_persisted_execution_collection(tmp_path: Path):
    project, adapter, item = prepared_item(tmp_path)
    assert item["status"] == "implementing"
    entries = item["data"]["repository_deliveries"]
    assert [entry["repository_id"] for entry in entries] == [BACKEND, FRONTEND]
    assert all(repository_phase(entry) == "commit_required" for entry in entries)
    assert git(tmp_path / "backend-work", "rev-parse", "HEAD") == project["back_commit"]
    assert git(tmp_path / "frontend-work", "rev-parse", "HEAD") == project["front_commit"]
    with sqlite3.connect(project["entry"] / "state/.strixnova/authority.sqlite3") as connection:
        raw = json.loads(connection.execute("SELECT data_json FROM work_items").fetchone()[0])
    assert "git" not in raw
    assert "selected_repository_id" not in raw
    assert len(raw["repository_deliveries"]) == 2
    assert not (project["front"] / ".strixnova").exists()
    assert not (project["back"] / ".strixnova").exists()


def test_work_area_creation_recovers_after_native_success_before_authority_writeback(tmp_path: Path, monkeypatch):
    project = planning_project(tmp_path)
    adapter, item = plan_item(project)
    item = accept(adapter, item, 'engineering_plan')
    coordinator = adapter.coordinator
    transition = coordinator.authority.transition
    def interrupted(identifier, action, payload, **kwargs):
        if action == 'record_implementation_started':
            raise RuntimeError('simulated writeback interruption')
        return transition(identifier, action, payload, **kwargs)
    monkeypatch.setattr(coordinator.authority, 'transition', interrupted)
    worktree = tmp_path / 'recover-backend'
    with pytest.raises(RuntimeError, match='writeback interruption'):
        coordinator.delivery(item['work_item_id'], {'repository_id': BACKEND, 'worktree_path': str(worktree)}, expected_version=item['version'])
    current = coordinator.authority.get(item['work_item_id'])
    assert current['data']['pending_effect']['kind'] == 'prepare_work_area'
    assert current['data']['pending_effect']['repository_id'] == BACKEND
    assert git(worktree, 'rev-parse', 'HEAD') == project['back_commit']
    before = git(project['back'], 'worktree', 'list', '--porcelain')
    monkeypatch.setattr(coordinator.authority, 'transition', transition)
    result = coordinator.delivery(item['work_item_id'], {'repository_id': BACKEND}, expected_version=current['version'])
    assert result['steps'] == ['work_area_recovered']
    assert result['work_item']['data']['pending_effect'] is None
    assert result['work_item']['status'] == 'implementation_ready'
    assert git(project['back'], 'worktree', 'list', '--porcelain') == before


@pytest.mark.parametrize('decision', ['preserve', 'discard'])
def test_cancellation_accounts_for_unmerged_work_in_the_other_repository(tmp_path: Path, decision: str):
    project, adapter, item = prepared_item(tmp_path)
    changed = tmp_path / 'frontend-work/src.py'
    changed.write_text('def value():\n    return 42\n', encoding='utf-8')
    if decision == 'preserve':
        (project['front'] / 'strixnova-project.yaml').write_text('broken: [', encoding='utf-8')
        adapter = LocalHostAdapter(project['entry'], project_bindings=project['bindings'])
    current = adapter.coordinator.cancel(item['work_item_id'], {'reason': 'Stop the joint change.'}, expected_version=item['version'])
    assert current['status'] == 'cancelled_changes_pending'
    states = {entry['repository_id']: entry['state'] for entry in current['data']['cancellation']['git_state']['repositories']}
    assert states[FRONTEND]['requires_user_decision'] is True
    assert states[BACKEND]['requires_user_decision'] is False
    final = adapter.coordinator.cancel(item['work_item_id'], {'decision': decision, 'confirm_discard': decision == 'discard'}, expected_version=current['version'])
    assert final['status'] == 'cancelled'
    assert git(project['front'], 'rev-parse', 'HEAD') == project['front_commit']
    assert git(project['back'], 'rev-parse', 'HEAD') == project['back_commit']
    if decision == 'preserve':
        assert '42' in changed.read_text(encoding='utf-8')
    else:
        assert not (tmp_path / 'frontend-work').exists()
        assert not (tmp_path / 'backend-work').exists()
        assert all(entry['git']['cleanup']['safe'] for entry in final['data']['repository_deliveries'])


def test_verification_writeback_recovery_does_not_run_the_command_twice(tmp_path: Path, monkeypatch):
    project = planning_project(tmp_path)
    counter = tmp_path / 'run-count.txt'
    command = project['assessment']['verification_commands'][0]
    command['argv'] = [command['argv'][0], '-c', f"from pathlib import Path; p=Path({str(counter)!r}); p.write_text(p.read_text()+'run\\n' if p.exists() else 'run\\n')"]
    adapter, item = plan_item(project)
    item = accept(adapter, item, 'engineering_plan')
    for identifier, name in ((BACKEND, 'backend-work'), (FRONTEND, 'frontend-work')):
        item = adapter.coordinator.delivery(item['work_item_id'], {'repository_id': identifier, 'worktree_path': str(tmp_path / name)}, expected_version=item['version'])['work_item']
    coordinator = adapter.coordinator
    transition = coordinator.authority.transition
    def interrupt(identifier, action, payload, **kwargs):
        if action == 'record_verification':
            raise OSError('simulated receipt writeback interruption')
        return transition(identifier, action, payload, **kwargs)
    monkeypatch.setattr(coordinator.authority, 'transition', interrupt)
    with pytest.raises(ApplicationCoordinatorError, match='writeback interruption'):
        coordinator.verify(item['work_item_id'], {'command_id': 'VC-001', 'mode': 'run'}, expected_version=item['version'])
    current = coordinator.authority.get(item['work_item_id'])
    assert current['data']['pending_effect']['kind'] == 'verification'
    nonce = current['data']['pending_effect']['intent']['receipt_id']
    assert counter.read_text() == 'run\n'
    monkeypatch.setattr(coordinator.authority, 'transition', transition)
    recovered = coordinator.verify(item['work_item_id'], {'command_id': 'VC-001', 'mode': 'run'}, expected_version=current['version'])
    assert recovered['recovered_execution'] is True
    assert recovered['verification']['receipt_id'] == nonce
    assert recovered['verification']['result'] == 'passed'
    assert recovered['work_item']['data']['pending_effect'] is None
    assert counter.read_text() == 'run\n'


def test_read_only_repository_command_runs_at_the_declared_commit_without_changing_its_checkout(tmp_path: Path):
    project = planning_project(tmp_path)
    assessment = project['assessment']
    assessment['repository_scope']['repositories'][1].update(role='read', target_ref=None)
    assessment['operations'] = assessment['operations'][:1]
    assessment['delivery_plan']['repository_order'] = [FRONTEND]
    assessment['verification_commands'] = [{**assessment['verification_commands'][1], 'argv': [assessment['verification_commands'][1]['argv'][0], '-c', "from src import value; assert value() == 2"]}]
    refresh_single_slice(assessment)
    adapter, item = plan_item(project)
    item = accept(adapter, item, 'engineering_plan')
    item = adapter.coordinator.delivery(item['work_item_id'], {'repository_id': FRONTEND, 'worktree_path': str(tmp_path / 'frontend-work')}, expected_version=item['version'])['work_item']
    (tmp_path / 'frontend-work/src.py').write_text('def value():\n    return 3\n', encoding='utf-8')
    # The selected immutable input deliberately differs from the checkout.
    dirty = 'def value():\n    return 99\n'
    (project['back'] / 'src.py').write_text(dirty, encoding='utf-8')
    refresh_planned_alignment(project, adapter, item)
    before = git(project['back'], 'worktree', 'list', '--porcelain')
    result = adapter.coordinator.verify(item['work_item_id'], {'command_id': 'VC-001', 'mode': 'run'}, expected_version=item['version'])
    assert result['verification']['result'] == 'passed'
    assert result['verification']['inputs_changed_during_execution'] is False
    item = result['work_item']
    item = adapter.coordinator.assess_verification(item['work_item_id'], result['verification']['receipt_id'], {'changed_after': False, 'needs_retest': False, 'rationale': 'Reviewed the immutable dependency assertion.'}, expected_version=item['version'])
    assert len(item['data']['implementation_slice_completions']) == 1
    assert [entry['repository_id'] for entry in item['data']['repository_deliveries']] == [FRONTEND]
    assert (project['back'] / 'src.py').read_text(encoding='utf-8') == dirty
    assert git(project['back'], 'worktree', 'list', '--porcelain') == before


def refresh_planned_alignment(project, adapter, item):
    model = project['alignment_before']
    scopes = [{**deepcopy(model['observation_scopes'][0]), 'repository_id': identifier, 'scope_id': model['observation_scopes'][0]['scope_id'] if identifier == FRONTEND else 'OBSCOPE-2222222222222222'} for identifier in (FRONTEND, BACKEND)]
    source = yaml.safe_load((project['front'] / model['artifact_paths']['source_ownership']).read_text(encoding='utf-8'))
    governed = [{**deepcopy(source['governed_source_scopes'][0]), 'repository_id': identifier, 'scope_id': scopes[index-1]['scope_id']} for index, identifier in enumerate((FRONTEND, BACKEND), 1)]
    prepared = adapter.coordinator.prepare_implementation_alignment(item['work_item_id'], {
        'schema_version': 'strixnova.implementation-alignment-preparation-request.v1',
        'alignment_revision_id': 'ALIGNREV-7777777777777777', 'supersedes_revision_id': model['revision']['revision_id'],
        'observation_scopes': scopes, 'governed_source_scopes': governed,
    }, expected_version=item['version'])
    catalog = []
    cursor = None
    while True:
        page = adapter.coordinator.inspect_implementation_alignment(item['work_item_id'], prepared['preparation_ref'], cursor=cursor, limit=100, expected_version=item['version'])
        catalog.extend(record['value'] for record in page['items'] if record['record_kind'] == 'semantic_decision')
        cursor = page['next_cursor']
        if cursor is None:
            break
    # Read bounded public decision records; source ownership is an explicit
    # fixture Agent judgment, not inferred from the frontend's equal path.
    project['alignment_preparation'] = prepared
    decisions = []
    for decision in catalog:
        if decision['required'] and decision['kind'] == 'source_record':
            previous = deepcopy(source['records'][0])
            previous['target_module_id'] = TEST_READER_MODULE_ID
            decisions.append({'decision_ref': decision['decision_ref'], 'value': {key: previous[key] for key in decision['required_value_fields']}})
        elif decision['required']:
            raise AssertionError(f"Unexpected unreviewed decision: {decision['kind']}")
    adapter.coordinator.write_implementation_alignment_candidate(item['work_item_id'], {
        'schema_version': 'strixnova.implementation-alignment-candidate-decisions.v1', 'preparation_ref': prepared['preparation_ref'],
        'decisions': decisions, 'deviations': [], 'unresolved_items': [],
    }, expected_version=item['version'])


def verified_item(root: Path, *, alignment: bool = False, repository_order=None):
    project, adapter, item = prepared_item(root, verification=True, alignment=alignment, repository_order=repository_order)
    for entry in item["data"]["repository_deliveries"]:
        (Path(entry["git"]["worktree_path"]) / "src.py").write_text("def value():\n    return 3\n", encoding="utf-8")
    if 'alignment_before' in project:
        refresh_planned_alignment(project, adapter, item)
    commands = item["data"]["engineering"]["plan"]["verification_commands"]
    for command in commands:
        result = adapter.coordinator.verify(item["work_item_id"], {"command_id": command["command_id"], "mode": "run"}, expected_version=item["version"])
        assert result["verification"]["result"] == "passed"
        assert result["verification"]["repository_id"] == command["repository_id"]
        item = adapter.coordinator.verify(item["work_item_id"], {
            "command_id": command["command_id"], "mode": "assess", "receipt_id": result["verification"]["receipt_id"],
            "code_change_assessment": {"changed_after": False, "needs_retest": False, "rationale": "Both scoped source inputs remain unchanged after this command."},
        }, expected_version=result["work_item"]["version"])["work_item"]
    return project, adapter, item


def test_commands_execute_in_their_repository_and_complete_one_combined_slice(tmp_path: Path):
    project, adapter, item = verified_item(tmp_path)
    completion, = item["data"]["implementation_slice_completions"]
    assert [entry["operation_ref"] for entry in completion["operation_results"] if entry["operation_ref"] in {"operations[0]", "operations[1]"}] == ["operations[0]", "operations[1]"]
    assert len(completion["operation_results"]) == 8
    assert {(entry["repository_id"], entry["path"]) for entry in completion["owned_path_snapshot"] if entry["path"] == "src.py"} == {(FRONTEND, "src.py"), (BACKEND, "src.py")}
    receipts = item["data"]["verifications"]
    assert len({entry["receipt_id"] for entry in receipts}) == 2
    for entry in receipts:
        assert Path(entry["raw_output_refs"]["stdout"]).is_relative_to(project["entry"] / "state/.strixnova/artifacts")


def presented_item(root: Path, *, repository_order=None):
    project, adapter, item = verified_item(root, alignment=True, repository_order=repository_order)
    receipts = item["data"]["verifications"]
    result = {
        "schema_version": "strixnova.actual-result.v1", "semantic_content_machine_proven": False,
        "review_subject_ref": adapter.read_model.review_subject(item)["subject_ref"],
        "effect_summary": "Both repository implementations return the jointly verified value.",
        "delivered_outcomes": ["Both scoped commands passed against uncommitted content."],
        "deviations": [], "limitations": [],
        "verification_receipt_ids": [entry["receipt_id"] for entry in receipts],
        "long_lived_refs": [{"artifact_id": project['alignment_before']['alignment_model_id'], "artifact_type": "domain_alignment", "path": project['assessment']['authority_change_set']['candidate_authorities'][0]['path'], "relation": "updated"}], "domain_fact_change_results": [], "method_application_results": [],
        "governance_rule_results": satisfied_governance_rule_results(item["data"]["engineering"]["plan"], receipts[0]["receipt_id"]),
    }
    item, coverage = adapter.coordinator.present_actual_result(item["work_item_id"], result, expected_version=item["version"])
    assert coverage["verification_status"] == "passed"
    return project, adapter, item


@pytest.mark.slow
@pytest.mark.parametrize('ending', ['finish', 'cancel_after_first', 'conflict_first', 'conflict_second', 'authorities_first_conflict_second'])
def test_overall_acceptance_checks_both_repositories_then_delivers_in_planned_order(tmp_path: Path, ending: str):
    order = [FRONTEND, BACKEND] if ending == "authorities_first_conflict_second" else [BACKEND, FRONTEND]
    project, adapter, item = presented_item(tmp_path, repository_order=order)
    snapshot = item["data"]["actual_result"]["implementation_candidate_snapshot"]
    assert {entry["repository_id"] for entry in snapshot["repositories"]} == {FRONTEND, BACKEND}
    front_path = tmp_path / "frontend-work/src.py"
    accepted_bytes = front_path.read_bytes()
    front_path.write_text("def value():\n    return 4\n", encoding="utf-8")
    with pytest.raises(HostAdapterError) as failure:
        accept(adapter, item, "actual_result")
    assert getattr(failure.value, "code", None) == "accepted_implementation_candidate_changed"
    assert adapter.coordinator.authority.get(item["work_item_id"])["version"] == item["version"]
    front_path.write_bytes(accepted_bytes)
    item = accept(adapter, item, "actual_result")
    adoption = adapter.next_step(item['work_item_id'], record_refs=['delivery.authority_adoption'])['records']['delivery.authority_adoption']
    assert adoption['accepted_candidate_snapshot_verified'] is True
    assert adoption['blocking_issues'] == []
    confirmation = item["data"]["actual_result_confirmation"]
    item = adapter.coordinator.delivery(item['work_item_id'], {'repository_id': order[0]}, expected_version=item['version'])['work_item']
    assert item['data']['authority_adoption']['ready_for_atomic_commits'] is True
    for identifier in order:
        name = "backend-work" if identifier == BACKEND else "frontend-work"
        root = tmp_path / name
        conflicting = (ending == "conflict_first" and identifier == order[0]) or (ending in {"conflict_second", "authorities_first_conflict_second"} and identifier == order[1])
        target = project['back' if identifier == BACKEND else 'front']
        if conflicting:
            (target / 'src.py').write_text('def value():\n    return 4\n', encoding='utf-8')
            git(target, 'add', 'src.py')
            git(target, 'commit', '-m', 'concurrent target change')
        paths = [operation['path'] for operation in item['data']['engineering']['plan']['operations'] if operation.get('repository_id') == identifier]
        git(root, "add", "--", *paths)
        git(root, "commit", "-m", "accepted repository result")
        item = adapter.coordinator.delivery(item["work_item_id"], {"repository_id": identifier}, expected_version=item["version"])["work_item"]
        if conflicting:
            item = resolve_conflict_delivery(adapter, item, identifier, target, reaccept=ending in {'conflict_second', 'authorities_first_conflict_second'})
            confirmation = item['data']['actual_result_confirmation']
        assert item["data"]["actual_result_confirmation"] == confirmation
        if identifier == order[0]:
            assert item["status"] == "commit_required"
            other = "front" if identifier == BACKEND else "back"
            assert git(project[other], "rev-parse", "HEAD") == project[other + "_commit"]
            if ending == 'cancel_after_first':
                integrated = git(project['back'], 'rev-parse', 'HEAD')
                item = adapter.coordinator.cancel(item['work_item_id'], {'reason': 'Stop the remaining frontend delivery.'}, expected_version=item['version'])
                assert item['status'] == 'cancelled_changes_pending'
                item = adapter.coordinator.cancel(item['work_item_id'], {'decision': 'preserve'}, expected_version=item['version'])
                assert item['status'] == 'cancelled'
                entries = {entry['repository_id']: entry for entry in item['data']['repository_deliveries']}
                assert entries[BACKEND]['git']['integration']['integrated_commit'] == integrated
                assert entries[FRONTEND]['git'].get('integration') is None
                assert git(project['back'], 'rev-parse', 'HEAD') == integrated
                assert (tmp_path / 'frontend-work/src.py').is_file()
                return
    assert item["status"] == "completed"
    assert all(repository_phase(entry) == "completed" for entry in item["data"]["repository_deliveries"])


def resolve_conflict_delivery(adapter, item, identifier, target, *, reaccept=False):
    if adapter.current_action(item['work_item_id'])['action_type'] == 'assess_target_advance':
        item = adapter.submit_current_action_input(item['work_item_id'], {'schema_version': 'strixnova.target-advance-assessment.v1', 'semantic_impact': 'unaffected', 'reason': 'The concurrent target change requires a native merge; the planned outcome is unchanged.'}, expected_version=item['version'])
        item = adapter.coordinator.delivery(item['work_item_id'], {'repository_id': identifier}, expected_version=item['version'])['work_item']
    assert item['status'] == 'integration_conflict'
    commands = item['data']['engineering']['plan']['verification_commands']

    old_result = deepcopy(item['data']['actual_result'])
    item = adapter.submit_current_action_input(item['work_item_id'], {'user_visible_result_changed': reaccept, 'confirmed_direction_or_plan_changed': False, 'reason': 'Resolve the native conflict and review the combined output.', 'retest_command_ids': [entry['command_id'] for entry in commands]}, expected_version=item['version'])
    (target / 'src.py').write_text('def value():\n    return 3\n', encoding='utf-8')
    git(target, 'add', 'src.py')
    for command in commands:
        result = adapter.coordinator.verify(item['work_item_id'], {'command_id': command['command_id'], 'mode': 'run', 'execution_area': 'target' if command['repository_id'] == identifier else 'worktree'}, expected_version=item['version'])
        assert result['verification']['result'] == 'passed'
        item = result['work_item']
        item = adapter.coordinator.assess_verification(item['work_item_id'], result['verification']['receipt_id'], {'changed_after': False, 'needs_retest': False, 'rationale': 'Reviewed both repositories against the resolved combined input.'}, expected_version=item['version'])
    if reaccept:
        for key in ('implementation_candidate_snapshot', 'authority_candidate_snapshot', 'target_verification', 'review_subject'):
            old_result.pop(key, None)
        old_result['verification_receipt_ids'] = [entry['receipt_id'] for entry in item['data']['verifications'][-len(commands):]]
        old_result['governance_rule_results'] = satisfied_governance_rule_results(item['data']['engineering']['plan'], old_result['verification_receipt_ids'][0])
        old_result['review_subject_ref'] = adapter.read_model.review_subject(item)['subject_ref']
        item, _ = adapter.coordinator.present_actual_result(item['work_item_id'], old_result, expected_version=item['version'])
        item = accept(adapter, item, 'actual_result')
        confirmation = item['data']['actual_result_confirmation']
    git(target, 'commit', '-m', 'verified native conflict resolution')
    item = adapter.coordinator.delivery(item['work_item_id'], {'repository_id': identifier}, expected_version=item['version'])['work_item']
    return item
