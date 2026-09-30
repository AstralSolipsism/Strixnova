import json
from pathlib import Path
import sqlite3

from strixnova.work_item_history import WorkItemHistory
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.project_context import FRONTEND, BACKEND, git, repository
from tests.support.history_records import ITEM_ID, history_item, write_history


def test_history_resolves_equal_artifact_paths_in_their_recorded_repositories(tmp_path: Path):
    management = tmp_path / 'state'
    management.mkdir()
    authority = WorkflowAuthority(management)
    item = {'work_item_id': ITEM_ID}
    data = history_item(management)
    deliveries, references, expected = [], [], {}
    for identifier, name, body in ((FRONTEND, 'front', 'frontend result'), (BACKEND, 'back', 'backend result')):
        root = tmp_path / name
        repository(root)
        (root / 'result.md').write_text(body, encoding='utf-8')
        git(root, 'add', '.')
        git(root, 'commit', '-m', 'recorded result')
        commit = git(root, 'rev-parse', 'HEAD')
        deliveries.append({'repository_id': identifier, 'plan_id': 'PLAN-RECORDED', 'git': {'repository': str(root), 'result_commits': [commit], 'integration': {'integrated_commit': commit}, 'cleanup': {'safe': True}}})
        references.append({'repository_id': identifier, 'artifact_id': name, 'artifact_type': 'interface', 'path': 'result.md', 'relation': 'updated'})
        expected[identifier] = body
    data.pop('git', None)
    data['repository_deliveries'] = deliveries
    data['actual_result'] = {'long_lived_refs': references}
    data['actual_result_confirmation'] = {'accepted': True, 'user_confirmation': 'Fixed joint-result fixture'}
    events = [{"event_type": "record_local_integration", "payload": {"repository_id": row["repository_id"], "integration": row["git"]["integration"]}} for row in deliveries]
    write_history(management, items=[{"work_item_id": ITEM_ID, "title": "Recorded joint result", "status": "completed", "data": data, "delivery_events": events}])
    before = authority.database_path.read_bytes()
    history = WorkItemHistory(management)
    result = history.query(work_item_id=item['work_item_id'], records=('delivery', 'artifact:0', 'artifact:1'))
    for index, identifier in enumerate((FRONTEND, BACKEND)):
        artifact = result['records'][f'artifact:{index}']
        assert artifact['availability'] == 'available'
        assert artifact['repository_id'] == identifier
        assert artifact['text'] == expected[identifier]
    assert len(result['records']['delivery']['repositories']) == 2
    assert all(commit['availability'] == 'available' for row in result['records']['delivery']['repositories'] for commit in row['commits'])
    assert authority.database_path.read_bytes() == before
