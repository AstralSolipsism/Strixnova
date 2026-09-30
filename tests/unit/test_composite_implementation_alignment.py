from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
import yaml

from strixnova.git_project_reader import GitProjectReader
from strixnova.implementation_observation import observe_project_implementation
from strixnova.project_content_snapshot import repository_path_key
from strixnova.project_implementation_alignment import ProjectImplementationAlignment, ProjectImplementationAlignmentError
from tests.support.project_baseline import portable_project_baseline
from tests.support.project_context import BACKEND, FRONTEND, git, repository


def composite_alignment(root: Path):
    front, back = root / 'front', root / 'back'
    for project in (front, back):
        repository(project)
        (project / 'src.py').write_text('def value():\n    return 1\n', encoding='utf-8')
    baseline = portable_project_baseline(front, baseline_id='composite observation', artifacts=[])
    for project in (front, back):
        git(project, 'add', '.')
        git(project, 'commit', '-m', 'original observation inputs')
    path = front / baseline['authority_refs']['implementation_alignment']['path']
    model = yaml.safe_load(path.read_text(encoding='utf-8'))
    documents = {key: yaml.safe_load((front / relative).read_text(encoding='utf-8')) for key, relative in model['artifact_paths'].items()}
    scope = model['observation_scopes'][0]
    scope['repository_id'] = FRONTEND
    second = {**deepcopy(scope), 'scope_id': 'OBSCOPE-2222222222222222', 'repository_id': BACKEND}
    model['observation_scopes'].append(second)
    source = documents['source_ownership']
    source['governed_source_scopes'][0]['repository_id'] = FRONTEND
    source['governed_source_scopes'].append({**deepcopy(source['governed_source_scopes'][0]), 'scope_id': second['scope_id'], 'repository_id': BACKEND})
    readers = {FRONTEND: GitProjectReader(front), BACKEND: GitProjectReader(back)}
    for identifier, reader in readers.items():
        reader.bind_repository_identity(identifier)
    original = source['records'][0]
    source['records'] = []
    hashes = {}
    for identifier, selected_scope in ((FRONTEND, scope), (BACKEND, second)):
        digest = hashlib.sha256(readers[identifier].read_canonical_bytes('src.py')).hexdigest()
        source['records'].append({**deepcopy(original), 'repository_id': identifier, 'scope_id': selected_scope['scope_id'], 'path': 'src.py', 'sha256': digest})
        hashes[repository_path_key(identifier, 'src.py')] = digest
    observation = observe_project_implementation(readers, model['observation_scopes'])
    model['observation_coverage'] = {
        'contract_version': observation['schema_version'], 'overall_status': observation['overall_coverage_status'],
        'source_manifest_sha256': observation['source_manifest_sha256'], 'observation_snapshot_sha256': observation['observation_snapshot_sha256'],
        'observed_paths': observation['observed_paths'], 'records': observation['coverage'], 'provider_receipts': observation['provider_receipts'],
    }
    model['code_snapshot']['repositories'] = [{'repository_id': identifier, 'base_commit': reader.resolve_commit('HEAD'), 'worktree_state': 'dirty'} for identifier, reader in readers.items()]
    model['code_snapshot']['governed_source_manifest_sha256'] = hashlib.sha256(''.join(f'{key}:{digest}\n' for key, digest in sorted(hashes.items())).encode()).hexdigest()
    documents['actual_dependencies']['observation_contract_version'] = observation['schema_version']
    assert observation['relations'] == []
    documents['actual_dependencies']['records'] = []
    path.write_text(yaml.safe_dump(model, sort_keys=False), encoding='utf-8')
    for key, document in documents.items():
        (front / model['artifact_paths'][key]).write_text(yaml.safe_dump(document, sort_keys=False), encoding='utf-8')
    def loader():
        return ProjectImplementationAlignment(front, baseline['authority_refs']['implementation_alignment']['path'],
            domain_model_path=baseline['authority_refs']['domain_model']['path'],
            architecture_description_path=baseline['authority_refs']['target_architecture']['path'],
            shared_reader=readers[FRONTEND], repository_readers=readers)
    return front, back, model, loader


def test_composite_alignment_distinguishes_equal_owned_paths_and_detects_backend_drift(tmp_path: Path):
    front, back, model, loader = composite_alignment(tmp_path)
    assert len(loader().load()['source_ownership']) == 2
    assert loader().drift()['passed'] is True
    (back / 'src.py').write_text('def value():\n    return 2\n', encoding='utf-8')
    drift = loader().drift()
    assert drift['passed'] is False
    assert any(f'{BACKEND}:src.py' in failure for failure in drift['failures'])
    assert not any(f'{FRONTEND}:src.py' in failure for failure in drift['failures'])


def test_source_repository_must_match_its_declared_scope(tmp_path: Path):
    front, back, model, loader = composite_alignment(tmp_path)
    path = front / model['artifact_paths']['source_ownership']
    document = yaml.safe_load(path.read_text(encoding='utf-8'))
    document['records'][1]['repository_id'] = FRONTEND
    path.write_text(yaml.safe_dump(document), encoding='utf-8')
    with pytest.raises(ProjectImplementationAlignmentError, match='repository|重复'):
        loader().load()
