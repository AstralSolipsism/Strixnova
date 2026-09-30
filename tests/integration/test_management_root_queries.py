import json

import pytest
from click.testing import CliRunner

from strixnova.cli import main
from strixnova.delivery_activity import DeliveryActivityAuthority
from strixnova.host_adapter import LocalHostAdapter
from strixnova.work_item_read_model import WorkItemReadModel
from tests.integration.test_multi_repository_planning import planning_project
from tests.unit.test_delivery_activity import _plan


@pytest.fixture
def managed_project(tmp_path):
    project = planning_project(tmp_path)
    path = tmp_path / 'bindings.json'
    path.write_text(json.dumps(project['bindings']), encoding='utf-8')
    runner = CliRunner()
    args = ['--project-bindings', str(path)]
    result = runner.invoke(main, [*args, 'intake', '--project-dir', str(project['entry']), '--input', json.dumps({'title': 'Managed entry', 'request': 'Read the same recorded facts from every public route.'})])
    assert result.exit_code == 0, result.output
    identifier = json.loads(result.output)['next']['work_item_id']
    management = project['entry'] / 'state'
    activity = DeliveryActivityAuthority(management).plan(_plan(), work_item_id=identifier, work_item_version=1, engineering_plan_id='PLAN-QUERY')
    return project, runner, args, identifier, activity


def test_next_list_uses_the_same_management_root_as_intake(managed_project):
    project, runner, args, identifier, _ = managed_project
    result = runner.invoke(main, [*args, 'next', '--project-dir', str(project['entry'])])
    assert result.exit_code == 0, result.output
    assert [item['work_item_id'] for item in json.loads(result.output)['work_items']] == [identifier]


def test_next_list_before_intake_does_not_create_management_storage(tmp_path):
    project = planning_project(tmp_path)
    path = tmp_path / 'bindings.json'
    path.write_text(json.dumps(project['bindings']), encoding='utf-8')
    result = CliRunner().invoke(main, ['--project-bindings', str(path), 'next', '--project-dir', str(project['entry'])])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)['work_items'] == []
    assert not (project['entry'] / 'state').exists()


def test_activity_list_and_detail_read_the_written_management_store(managed_project):
    project, _, _, _, activity = managed_project
    adapter = LocalHostAdapter(project['entry'], project_bindings=project['bindings'])
    assert [value['activity_id'] for value in adapter.delivery_activities()['activities']] == [activity['activity_id']]
    assert adapter.delivery_activity(activity['activity_id'])['activity'] == activity


def test_trace_reads_authorities_from_repositories_and_events_from_management(managed_project):
    project, _, _, identifier, activity = managed_project
    reader = WorkItemReadModel(project['entry'], project_bindings=project['bindings'])
    trace = reader.engineering_trace_for_work_item(identifier, mode='audit')
    assert trace['work_item']['work_item_id'] == identifier
    assert [value['activity_id'] for value in trace['external_activities']] == [activity['activity_id']]
    assert not (project['entry'] / '.strixnova/authority.sqlite3').exists()
    assert not (project['entry'] / '.strixnova/delivery-activities.sqlite3').exists()
