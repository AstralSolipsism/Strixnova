from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sys
from threading import Thread

from strixnova.verification_dependencies import dependency_evidence_stale
from strixnova.verification_runner import VerificationRunner, normalize_verification_commands
from tests.support.verification_approval import approval_expectations, approved_verification_request


def test_service_evidence_requires_actual_version_contract_and_environment(tmp_path: Path):
    state = {'version': 'build-42', 'environment': 'fixture-staging', 'contract': b'{"endpoint":"/value","type":"integer"}'}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body = state['contract'] if self.path == '/contract' else json.dumps({'version': state['version'], 'environment': state['environment']}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        check = {'dependency_id': 'backend-api', 'kind': 'service', 'expected_version': state['version'], 'expected_contract_sha256': hashlib.sha256(state['contract']).hexdigest(), 'environment': state['environment'], 'max_age_seconds': 60}
        code = f"import json,hashlib,urllib.request; u={url!r}; m=json.load(urllib.request.urlopen(u+'/version',timeout=2)); c=urllib.request.urlopen(u+'/contract',timeout=2).read(); print('STRIXNOVA_DEPENDENCY_EVIDENCE='+json.dumps(dict(schema_version='strixnova.dependency-observation.v1',dependency_id='backend-api',version=m['version'],contract_sha256=hashlib.sha256(c).hexdigest(),environment=m['environment'],evidence_refs=[u+'/version',u+'/contract'])))"
        command = normalize_verification_commands([{'argv':[sys.executable,'-c',code], 'cwd':'.', 'run_kind':'integration_test', 'covers':['AC-001'], 'reason':'Observe the deployed dependency without backend source.', 'dependency_checks':[check]}])[0]
        approved = approved_verification_request(command, work_item_id='WI-SERVICE-EVIDENCE')
        runner = VerificationRunner(tmp_path, artifact_root=tmp_path / 'evidence')
        good = runner.run(approved, **approval_expectations(approved), limitations=[])
        assert good['result'] == 'passed'
        assert good['dependency_evidence']['status'] == 'complete'
        assert good['dependency_evidence']['source_code_coverage_proven'] is False
        observed = datetime.fromisoformat(good['dependency_evidence']['records'][0]['observed_at'].replace('Z','+00:00'))
        assert dependency_evidence_stale(good['dependency_evidence'], now=observed + timedelta(seconds=61)) is True
        for field, wrong in [('version', None), ('version', 'build-43'), ('environment', 'another-environment'), ('contract', b'changed contract')]:
            original = state[field]
            state[field] = wrong
            bad = runner.run(approved, **approval_expectations(approved), limitations=[])
            assert bad['result'] == 'blocked'
            assert bad['dependency_evidence']['status'] == 'blocked'
            state[field] = original
        address_only = {**command, 'argv':[sys.executable, '-c', f"import urllib.request; print(urllib.request.urlopen({url!r},timeout=2).status)"]}
        shallow = approved_verification_request(address_only, work_item_id='WI-SERVICE-EVIDENCE')
        missing = runner.run(shallow, **approval_expectations(shallow), limitations=[])
        assert missing['exit_code'] == 0
        assert missing['result'] == 'blocked'
        assert missing['dependency_evidence']['records'][0]['status'] == 'missing'
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
