import hashlib
import json

from scripts.acceptance_evidence import original_output_hashes


def test_business_output_guard_uses_recorded_bytes_and_excludes_mutable_maintenance(tmp_path):
    project, work = tmp_path/'project', tmp_path/'work'
    output = project/'.strixnova/artifacts/WI-A/VR-A.stdout.log'
    journal = project/'.strixnova/artifacts/maintenance/operation-A.json'
    output.parent.mkdir(parents=True)
    journal.parent.mkdir(parents=True)
    output.write_bytes(b'original execution output')
    journal.write_bytes(b'operation started')
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    recorded = {output.relative_to(project).as_posix():digest,
                journal.relative_to(project).as_posix():hashlib.sha256(journal.read_bytes()).hexdigest()}
    (work/'observations').mkdir(parents=True)
    (work/'observations/setup-provenance.json').write_text(json.dumps({'source_files':recorded}), encoding='utf-8')
    journal.write_bytes(b'operation completed')
    expected = original_output_hashes(work, project)
    assert expected == {str(output):digest}
    assert hashlib.sha256(output.read_bytes()).hexdigest() == expected[str(output)]
    output.write_bytes(b'changed evidence')
    assert original_output_hashes(work, project) == expected
    assert hashlib.sha256(output.read_bytes()).hexdigest() != expected[str(output)]
