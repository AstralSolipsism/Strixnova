"""Use existing native author/review drivers for the existing assurance schema."""
from copy import deepcopy
from pathlib import Path
import argparse, hashlib, json, os, shutil, sys
from jsonschema import Draft202012Validator

ROOT = Path.cwd().resolve()
sys.path[:0] = [str(ROOT), str(ROOT / '.artifacts/acceptance/initial')]
from run_initial_discovery_acceptance import dump, snapshot
from scripts.agent_acceptance import run_session, assess_turn
from scripts.review_antigravity_evidence import run_review

parser = argparse.ArgumentParser()
parser.add_argument('--registration', required=True, type=Path)
args = parser.parse_args()
registration = json.loads(args.registration.read_text(encoding='utf-8'))
project = Path(registration['project'])
packet_path = project / 'inputs/packet.json'
assert hashlib.sha256(packet_path.read_bytes()).hexdigest() == registration['packet_sha256']
packet = json.loads(packet_path.read_text(encoding='utf-8'))
files = {row['evidence_id']: row for row in packet['files']}
rules = {row['rule_id']: row for row in packet['rules']}
for row in files.values():
    assert hashlib.sha256((project / row['read_path']).read_bytes()).hexdigest() == row['sha256'], 'Frozen input changed: '+row['path']
    assert hashlib.sha256((ROOT / row['path']).read_bytes()).hexdigest() == row['sha256'], 'Current input changed: '+row['path']
official = json.loads((project / 'inputs/files/strixnova/src/strixnova/resources/project-engineering-assurance-v1.schema.json').read_text(encoding='utf-8'))
definitions = deepcopy(official['$defs'])
definitions['rule_assessment']['properties']['rule_id'] = {'enum': list(rules)}
definitions['rule_assessment']['properties']['evidence_ids']['items'] = {'enum': list(files)}
claim = {'type': 'object', 'additionalProperties': False, 'required': ['evidence_id', 'claim', 'limitations'],
         'properties': {'evidence_id': {'enum': list(files)}, 'claim': {'type': 'string', 'minLength': 1},
                        'limitations': {'type': 'array', 'items': {'type': 'string'}}}}
schema = {'type': 'object', 'additionalProperties': False, '$defs': definitions,
          'required': ['rule_assessments', 'evidence_claims', 'unresolved_items', 'owner_accepted', 'semantic_content_machine_proven'],
          'properties': {'rule_assessments': {'type': 'array', 'minItems': 7, 'maxItems': 7, 'items': {'$ref': '#/$defs/rule_assessment'}},
                         'evidence_claims': {'type': 'array', 'items': claim},
                         'unresolved_items': {'type': 'array', 'items': {'type': 'string'}},
                         'owner_accepted': {'const': False}, 'semantic_content_machine_proven': {'const': False}}}
# Send only referenced definitions. Unused repository path schemas use Python
# regex lookaheads that the native host's RE2 schema parser cannot accept.
reachable = {}
def collect_references(node):
    if isinstance(node, dict):
        reference = node.get('$ref', '')
        if reference.startswith('#/$defs/'):
            key = reference.removeprefix('#/$defs/')
            if key not in reachable:
                reachable[key] = definitions[key]
                collect_references(definitions[key])
        for key, value in node.items():
            if key != '$defs':collect_references(value)
    elif isinstance(node, list):
        for value in node:collect_references(value)
collect_references(schema)
schema['$defs'] = reachable
Draft202012Validator.check_schema(schema)
evidence = Path(os.environ['STRIXNOVA_VALIDATION_EVIDENCE'])
prompt = f'''读取 AGENTS.md 和 inputs/packet.json，按 read_path 实际查看相关证据。请逐项评价 Strixnova 初始候选对现有七条内部工程规则的适用性与满足程度。
仅使用各规则当前 strixnova_interpretation、evidence_expectations 及项目政策，不猜测外部标准正文，不宣称外部认证。评价对象是本次项目建设，不是程序是否含有同名治理功能，也不是隔离业务样例本身的质量。
通过最终结构化输出提交每条规则恰好一次。source_ids 保持对应规则真实来源。evidence_ids 只引用 packet.files 中实际读取的条目；在 evidence_claims 为每个被引用 ID 给出精确支持内容及局限，不抄文件数或绿色数量代替论证。文件路径、摘要和证据 ID 由程序按冻结清单机械关联，你决定 claim、适用性、状态、gaps、remediation_actions 和 limitations。
必须区分实际命令结果、Agent 固定输入行为、负责人接受和 Git 绑定。原始全量失败及后续定点修复分别说明。以冻结目录、最新验证状态和对应原始结果为准，不把目录中仍待验的项目算作通过，也不把旧的停止记录当成之后步骤永远未发生。不要把新仓库无Git基线一概当所有规则均未实现，也不得编造已提交、已采用或真实接受。satisfied 必须有范围相符的真实证据，证据不充分时如实保留部分、未知或缺口。
所有文件只读，不写 assessment.json 或临时脚本，不运行产品、测试、安装或Git写入，不访问父目录或调用子Agent。必要解析只能使用完整解释器 {sys.executable}。保持简洁、逐项可审阅，不预设通过。'''
dump(evidence/'registration.json', {**registration, 'fixed_input': prompt})
dump(evidence/'output-schema.json', schema)
(evidence/'user-input.txt').write_text(prompt, encoding='utf-8')
shutil.copyfile(__file__, evidence/'operator-source.py')
protected = snapshot(project)
def observe():
    return {'reached': snapshot(project) == protected, 'frozen_inputs_unchanged': snapshot(project) == protected}
receipt = run_session(binary=Path(os.environ['LOCALAPPDATA'])/'agy/bin/agy.exe', project=project, prompt=prompt,
                      evidence=evidence/'execution', observe_endpoint=observe, model=registration['author_model'],
                      timeout=900, max_continuations=0, permission_mode='auto_approve', json_schema=schema)
(evidence/'author-response.md').write_text(receipt['last_result'].get('response', ''), encoding='utf-8')
events = [json.loads(line) for line in (evidence/'execution/events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
dump(evidence/'tool-steps.json', assess_turn(events, expected_output_schema=schema)['tool_steps'])
dump(evidence/'endpoint.json', observe())
assert receipt['mechanical_passed'] and observe()['reached'], 'Native execution did not settle with unchanged inputs'
value = receipt['last_result']['structured_output']
Draft202012Validator(schema).validate(value)
assert {row['rule_id'] for row in value['rule_assessments']} == set(rules)
assert all(set(row['source_ids']) == set(rules[row['rule_id']]['source_ids']) for row in value['rule_assessments'])
used = {identity for row in value['rule_assessments'] for identity in row['evidence_ids']}
claims = {row['evidence_id']: row for row in value['evidence_claims']}
assert len(claims) == len(value['evidence_claims']) and set(claims) == used
dump(evidence/'assessment.json', value)
materialized = [{**{key: files[identity][key] for key in ['evidence_id', 'evidence_kind', 'path', 'sha256', 'receipt_id']},
                 'claim': row['claim'], 'limitations': row['limitations']} for identity, row in claims.items()]
for row in materialized:
    Draft202012Validator({'$ref': '#/$defs/evidence', '$defs': official['$defs']}).validate(row)
dump(evidence/'assurance-sections.json', {'rule_assessments': value['rule_assessments'], 'evidence': materialized,
                                      'unresolved_items': value['unresolved_items'], 'semantic_content_machine_proven': False})
sources = {'packet': {'path': str(packet_path), 'role': 'original_input'},
           'request': {'path': str(evidence/'user-input.txt'), 'role': 'user_input'},
           'assessment': {'path': str(evidence/'assessment.json'), 'role': 'author_artifact'},
           'author-tools': {'path': str(evidence/'tool-steps.json'), 'role': 'author_artifact'}}
sources.update({identity: {'path': str(project/row['read_path']), 'role': 'author_artifact'} for identity, row in files.items()})
cases = [{'case_id': identity, 'expected_behavior': '据当前内部规则、真实项目材料及原始结果复核本条评价。明确区分代码机制、建设证据、Agent与负责人接受；所有状态、适用性、引用、缺口和范围必须有来源支持。规则：'+json.dumps(rule, ensure_ascii=False),
          'must_avoid': '用同名程序功能替代本项目建设证据；只凭数量或文档存在批准；把仍待验项目、无Git绑定或未取得负责人接受称为完成；推断外部标准认证；按预定结果评价。',
          'evidence_source_ids': ['assessment', 'author-tools', *files],
          'verification_scope': '仅判断这份内部规则评价是否准确且有证据；真实的部分、未满足或待验状态可以被如实登记，复核通过不把它们升级为已满足。不宣称完整候选、外部认证或负责人接受。',
          'machine_checks': {'frozen_inputs_unchanged': True, 'all_seven_rules_present': True, 'evidence_ids_and_hashes_bound': True}}
         for identity, rule in rules.items()]
dump(evidence/'review-spec.json', {'sources': sources, 'cases': cases})
review = run_review(evidence/'review-spec.json', evidence/'independent-review', timeout=900)
summary = {'execution': review['execution'], 'cases': [{'case_id': row['case_id'], 'verdict': row['verdict']} for row in review['cases']],
           'authority_files_updated': False, 'owner_accepted': False}
dump(evidence/'assessment-summary.json', summary)
print(json.dumps(summary, ensure_ascii=False))
raise SystemExit(0 if review['execution']['report_valid'] and all(row['summary']['status'] == 'passed' for row in review['cases']) else 1)
