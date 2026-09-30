import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import sys
from threading import Thread

from click.testing import CliRunner

from tests.integration.test_behavior_example_cli import invoke, accept
from tests.support.governance_assessment import direction_fixture, exploration_assessment, satisfied_governance_rule_results
from strixnova.workflow_authority import WorkflowAuthority


def test_frontend_without_backend_source_preserves_known_and_unknown_service_results(tmp_path):
    project = tmp_path / 'frontend'
    project.mkdir()
    (project/'frontend_client.py').write_text("import json,hashlib,urllib.request\ndef observe(url):\n    metadata=json.load(urllib.request.urlopen(url+'/version',timeout=2))\n    contract=urllib.request.urlopen(url+'/contract',timeout=2).read()\n    return dict(schema_version='strixnova.dependency-observation.v1',dependency_id='backend-api',version=metadata['version'],environment=metadata['environment'],contract_sha256=hashlib.sha256(contract).hexdigest(),evidence_refs=[url+'/version',url+'/contract'])\n",encoding='utf-8')
    contract = b'{"endpoint":"/value","type":"integer"}'
    state = {'version':'build-7','environment':'isolated-staging'}
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200);self.end_headers()
            self.wfile.write(contract if self.path=='/contract' else json.dumps(state).encode())
        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    runner=CliRunner()
    try:
        url=f'http://127.0.0.1:{server.server_port}'
        for observed_version in ('build-7',None):
            state['version']=observed_version
            current=invoke(runner,project,'intake',payload={'title':'Observe frontend service dependency','request':'Verify the declared service identity without backend source.'})['next']
            current=invoke(runner,project,'submit',item=current,payload={'direction':direction_fixture(),'ready_for_confirmation':True})['next']
            current=accept(runner,project,current)
            assessment=exploration_assessment(project)
            assessment['direction_ref']={'work_item_id':current['work_item_id'],'direction_version':current['work_item_version']}
            assessment.pop('verification_not_required_reason')
            assessment['verification_reviews']=[]
            assessment['verification_commands']=[{'argv':[sys.executable,'-c',f"import json;from frontend_client import observe;print('STRIXNOVA_DEPENDENCY_EVIDENCE='+json.dumps(observe({url!r})))"], 'cwd':'.','run_kind':'integration_test','covers':['direction.acceptance:DIRACC-3333333333333333','direction.constraint:DIRCON-2222222222222222'],'reason':'Observe actual version, contract bytes and environment through the frontend client.','dependency_checks':[{'dependency_id':'backend-api','kind':'service','expected_version':'build-7','expected_contract_sha256':hashlib.sha256(contract).hexdigest(),'environment':'isolated-staging','max_age_seconds':300}]}]
            current=invoke(runner,project,'submit',item=current,payload=assessment)['next']
            current=accept(runner,project,current)
            current=invoke(runner,project,'verify',item=current,payload={'command_id':'VC-001','mode':'run'})['next']
            receipt=WorkflowAuthority(project).get(current['work_item_id'])['data']['verifications'][-1]
            assert receipt['exit_code']==0
            assert receipt['result']==('passed' if observed_version else 'blocked')
            assert receipt['dependency_evidence']['source_code_coverage_proven'] is False
            current=invoke(runner,project,'verify',item=current,payload={'command_id':'VC-001','mode':'assess','receipt_id':receipt['receipt_id'],'code_change_assessment':{'changed_after':False,'needs_retest':False,'rationale':'The client inputs are unchanged; unknown dependency identity remains explicitly blocked.'}})['next']
            plan=WorkflowAuthority(project).get(current['work_item_id'])['data']['engineering']['plan']
            rules=satisfied_governance_rule_results(plan,receipt['receipt_id'])
            limitations=[] if observed_version else ['The service returned no deployment version; backend source coverage is not established.']
            if limitations:
                for rule in rules:
                    rule.update(status='partially_satisfied',gaps=limitations,remediation_actions=['Obtain an observable deployment version before claiming full verification.'],limitations=limitations)
            current=invoke(runner,project,'delivery',item=current,payload={'schema_version':'strixnova.actual-result.v1','effect_summary':'Observed the dependency through the frontend client.','delivered_outcomes':['Recorded actual service evidence and its limits.'],'deviations':[],'limitations':limitations,'verification_receipt_ids':[receipt['receipt_id']],'long_lived_refs':[],'method_application_results':[],'governance_rule_results':rules,'semantic_content_machine_proven':False})['next']
            current=accept(runner,project,current)
            stored=WorkflowAuthority(project).get(current['work_item_id'])
            assert stored['status']=='completed'
            result=stored['data']['actual_result']
            assert result['target_verification']['status']==('evidence_recorded' if observed_version else 'with_gaps')
        assert not (tmp_path/'backend').exists()
    finally:
        server.shutdown();server.server_close();thread.join(timeout=2)
