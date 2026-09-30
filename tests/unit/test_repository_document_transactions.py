from pathlib import Path
import hashlib
import json
import subprocess
import sys
import tempfile
import os

import pytest

from strixnova.recoverable_document_transaction import DocumentTransactionError, recover_document_transactions, replace_documents
from strixnova.yaml_metadata_patch import build_yaml_patch_transaction, apply_yaml_patch_transaction, YamlMetadataPatchError
from tests.support.project_context import FRONTEND, BACKEND


def test_current_recovery_obeys_explicit_targets_and_preserves_rejected_journal(tmp_path: Path):
    allowed = tmp_path / 'authority.yaml'
    unrelated = tmp_path / 'unrelated.yaml'
    allowed.write_bytes(b'unchanged\n')
    unrelated.write_bytes(b'replacement\n')
    transaction = tmp_path / 'transactions/txn-scope'
    transaction.mkdir(parents=True)
    backup = transaction / 'original'
    backup.write_bytes(b'original\n')
    journal = transaction / 'journal.json'
    journal.write_text(json.dumps({
        'schema_version': 'strixnova.recoverable-document-transaction.v1',
        'state': 'replacing',
        'entries': [{
            'target': str(unrelated),
            'backup': 'transactions/txn-scope/original',
            'original_sha256': hashlib.sha256(backup.read_bytes()).hexdigest(),
            'replacement_sha256': hashlib.sha256(unrelated.read_bytes()).hexdigest(),
        }],
    }), encoding='utf-8')
    original_journal = journal.read_bytes()

    with pytest.raises(DocumentTransactionError) as rejected:
        recover_document_transactions(transaction.parent, tmp_path, allowed_targets=[allowed])
    assert rejected.value.code == 'document_transaction_path_invalid'
    assert allowed.read_bytes() == b'unchanged\n'
    assert unrelated.read_bytes() == b'replacement\n'
    assert journal.read_bytes() == original_journal
    assert backup.read_bytes() == b'original\n'

    assert recover_document_transactions(transaction.parent, tmp_path, allowed_targets=[unrelated]) == 1
    assert unrelated.read_bytes() == b'original\n'
    assert not transaction.exists()


def test_yaml_transaction_binds_equal_paths_to_exact_repository_roots(tmp_path: Path):
    roots = {FRONTEND: tmp_path / 'front', BACKEND: tmp_path / 'back'}
    for root in roots.values():
        root.mkdir()
        (root / 'authority.yaml').write_text('revision:\n  status: draft\n', encoding='utf-8')
    changes = {(identifier, 'authority.yaml'): {('revision', 'status'): 'confirmed'} for identifier in roots}
    transaction = build_yaml_patch_transaction(tmp_path, changes, repository_roots=roots)
    wrong = {FRONTEND: roots[BACKEND], BACKEND: roots[FRONTEND]}
    with pytest.raises(YamlMetadataPatchError, match='不一致'):
        apply_yaml_patch_transaction(tmp_path, transaction, repository_roots=wrong)
    assert all('draft' in (root / 'authority.yaml').read_text() for root in roots.values())
    apply_yaml_patch_transaction(tmp_path, transaction, repository_roots=roots)
    assert apply_yaml_patch_transaction(tmp_path, transaction, repository_roots=roots) == {}
    assert all('confirmed' in (root / 'authority.yaml').read_text() for root in roots.values())


def test_separated_document_recovery_requires_the_original_explicit_targets(tmp_path: Path):
    management = tmp_path / 'management'
    management.mkdir()
    targets = [tmp_path / 'front/authority.yaml', tmp_path / 'back/authority.yaml']
    for target in targets:
        target.parent.mkdir()
        target.write_bytes(b'old\n')
    transactions = management / 'transactions'
    script = '''
import os,sys
from pathlib import Path
import strixnova.recoverable_document_transaction as module
root=Path(sys.argv[1]); targets=[root/'front/authority.yaml',root/'back/authority.yaml']
original=module.os.replace
def interrupt(source,target):
    original(source,target)
    if Path(source).name.startswith('replacement-') and Path(target)==targets[0]: os._exit(91)
module.os.replace=interrupt
module.replace_documents([(target,b'new\\n') for target in targets], recovery_root=root/'management',transaction_root=root/'management/transactions',allowed_targets=targets)
'''
    crashed = subprocess.run([sys.executable, '-c', script, str(tmp_path)], capture_output=True)
    assert crashed.returncode == 91, crashed.stderr
    with pytest.raises(DocumentTransactionError, match='恢复范围'):
        recover_document_transactions(transactions, management, allowed_targets=[targets[0]])
    assert targets[0].read_bytes() == b'new\n'
    assert targets[1].read_bytes() == b'old\n'
    targets[1].write_bytes(b'third party\n')
    with pytest.raises(DocumentTransactionError, match='第三方'):
        recover_document_transactions(transactions, management, allowed_targets=targets)
    assert targets[1].read_bytes() == b'third party\n'
    targets[1].write_bytes(b'old\n')
    assert recover_document_transactions(transactions, management, allowed_targets=targets) == 1
    assert all(target.read_bytes() == b'old\n' for target in targets)


def test_document_replacement_and_rollback_work_across_real_volumes(tmp_path: Path):
    base = Path(os.environ.get('LOCALAPPDATA', tempfile.gettempdir())) / 'Temp' if os.name == 'nt' else Path(tempfile.gettempdir())
    if not base.is_dir():
        pytest.skip('The host temporary directory is unavailable')
    with tempfile.TemporaryDirectory(prefix='strixnova-cross-volume-', dir=base) as directory:
        external = Path(directory).resolve()
        assert external.is_relative_to(base.resolve())
        if external.drive.lower() == tmp_path.drive.lower():
            pytest.skip('A second writable volume is unavailable on this host')
        targets = [tmp_path / 'local.yaml', external / 'foreign.yaml']
        for target in targets:
            target.write_bytes(b'original\n')
        def reject():
            raise ValueError('candidate not accepted')
        with pytest.raises(ValueError, match='not accepted'):
            replace_documents([(target, b'candidate\n') for target in targets], recovery_root=tmp_path, allowed_targets=targets, validate_replaced=reject)
        assert all(target.read_bytes() == b'original\n' for target in targets)
        replace_documents([(target, b'candidate\n') for target in targets], recovery_root=tmp_path, allowed_targets=targets)
        assert all(target.read_bytes() == b'candidate\n' for target in targets)
