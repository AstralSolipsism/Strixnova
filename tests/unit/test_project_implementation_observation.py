from pathlib import Path

import pytest

from strixnova.git_project_reader import GitProjectReader
from strixnova.implementation_observation import ImplementationObservationError, observe_project_implementation
from strixnova.project_content_snapshot import repository_path_key, split_repository_path_key
from tests.support.project_context import FRONTEND, BACKEND, git, repository
from tests.unit.test_implementation_observation import _scope


def test_project_observation_keeps_equal_paths_and_native_receipts_separate(tmp_path: Path):
    readers, scopes = {}, []
    for index, identifier in enumerate((FRONTEND, BACKEND), 1):
        root = tmp_path / str(index)
        repository(root)
        (root / 'src.py').write_text(f'def value():\n    return {index}\n', encoding='utf-8')
        git(root, 'add', '.')
        git(root, 'commit', '-m', 'observation input')
        readers[identifier] = GitProjectReader(root, observed_ref='HEAD')
        scopes.append({**_scope(f'OBSCOPE-{index:016X}', '.', 'python', ['source_import']), 'repository_id': identifier})
    observation = observe_project_implementation(readers, scopes)
    assert observation['overall_coverage_status'] == 'complete'
    paths = observation['observed_paths']
    assert paths[repository_path_key(FRONTEND, 'src.py')] != paths[repository_path_key(BACKEND, 'src.py')]
    assert {row['repository_id'] for row in observation['nodes']} == {FRONTEND, BACKEND}
    assert len({row['node_id'] for row in observation['nodes']}) == len(observation['nodes'])
    assert len(observation['repository_observations']) == 2
    assert all(row['observation']['observed_revision'] != 'working_tree' for row in observation['repository_observations'])
    git(tmp_path / '1', 'commit', '--allow-empty', '-m', 'same content at another commit')
    newer = observe_project_implementation({FRONTEND: GitProjectReader(tmp_path / '1', observed_ref='HEAD'), BACKEND: readers[BACKEND]}, scopes)
    assert newer['observation_snapshot_sha256'] == observation['observation_snapshot_sha256']
    assert newer['repository_observations'] != observation['repository_observations']
    (tmp_path / '2/src.py').write_text('def value():\n    return 99\n', encoding='utf-8')
    assert observe_project_implementation(readers, scopes) == observation
    with pytest.raises(ImplementationObservationError, match='not explicitly available'):
        observe_project_implementation({FRONTEND: readers[FRONTEND]}, scopes)


@pytest.mark.parametrize('key', ['src.py', 'REPO-wrong:src.py', '_:../outside.py', 'REPO-1111111111111111:C:/outside.py'])
def test_repository_path_index_never_becomes_an_unchecked_filesystem_path(key):
    with pytest.raises((ValueError, RuntimeError)):
        split_repository_path_key(key)
