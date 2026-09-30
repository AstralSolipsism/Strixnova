import copy
import json
import subprocess
from pathlib import Path
from scripts.acceptance_evidence import declared_source_facts

import pytest

from scripts.acceptance_evidence import source_record, attach_references, summarize_case
from scripts import review_antigravity_evidence as reviewer


def test_program_attaches_exact_original_instead_of_asking_agent_to_copy():
    source = source_record('answer-A', '**原文**\n另一行。\n', role='author_response')
    review = {'case_id': 'A', 'verdict': 'passed', 'reason': '这是理解后的表述，不必与原文相同。',
              'references': [{'source_id': 'answer-A', 'start_line': 1, 'end_line': 2}]}
    original = copy.deepcopy(review)
    attached = attach_references(review, {'answer-A': source}, allowed_ids={'answer-A'})
    assert attached['references'][0]['original_text'] == '**原文**\n另一行。\n'
    assert attached['references'][0]['source_sha256'] == source['sha256']
    assert attached['reason'] == review['reason']
    assert review == original


@pytest.mark.parametrize('reference', [
    {'source_id': 'question-A', 'start_line': 1, 'end_line': 1},
    {'source_id': 'answer-B', 'start_line': 1, 'end_line': 1},
    {'source_id': 'answer-A', 'start_line': 0, 'end_line': 1},
    {'source_id': 'answer-A', 'start_line': 1, 'end_line': 9},
    {'source_id': 'answer-A', 'start_line': True, 'end_line': 1},
])
def test_wrong_source_or_invalid_range_cannot_support_this_case(reference):
    sources = {i: source_record(i, 'text', role='author_response')
               for i in ['question-A', 'answer-A', 'answer-B']}
    with pytest.raises(ValueError):
        attach_references({'references': [reference]}, sources, allowed_ids={'answer-A'})


def test_modified_source_cannot_reuse_old_identity():
    source = source_record('A', 'old', role='author_response')
    source['text'] = 'new'
    with pytest.raises(ValueError, match='changed'):
        attach_references({'references': [{'source_id': 'A', 'start_line': 1, 'end_line': 1}]},
                          {'A': source}, allowed_ids={'A'})


def test_allowlist_mistake_cannot_turn_a_question_into_author_evidence():
    with pytest.raises(ValueError, match='Input material'):
        attach_references({'references': [{'source_id': 'Q', 'start_line': 1, 'end_line': 1}]},
                          {'Q': source_record('Q', 'question', role='user_input')}, allowed_ids={'Q'})


def test_machine_success_does_not_create_semantic_acceptance():
    assert summarize_case(machine_checks={'unchanged': True}, review=None)['status'] == 'pending_review'


def test_reviewer_pass_cannot_hide_failed_actual_effect():
    value = summarize_case(machine_checks={'original_preserved': False}, review={'verdict': 'passed'})
    assert value['status'] == 'checks_failed'
    assert value['failure_layer'] == 'undetermined'
    assert value['reviewer_verdict'] == 'passed'


def test_semantic_revision_remains_reviewers_judgement():
    value = summarize_case(machine_checks={'unchanged': True}, review={'verdict': 'needs_revision'})
    assert value['status'] == 'needs_revision'
    assert value['semantic_content_machine_proven'] is False


@pytest.mark.parametrize('variant', ['valid', 'wrong_source', 'duplicate', 'failed_effect'])
def test_review_transport_binds_locations_without_copying_or_judging_prose(tmp_path, monkeypatch, variant):
    monkeypatch.setattr(reviewer, 'ROOT', tmp_path)
    subprocess.run(['git', 'init', '--quiet', str(tmp_path)], check=True, capture_output=True)
    skill = tmp_path / 'strixnova/src/strixnova/resources/agent-skill/strixnova'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('fixture instructions', encoding='utf-8')
    original = tmp_path / 'answer.txt'
    original.write_text('原始答复。\n第二行。', encoding='utf-8')
    question = tmp_path / 'question.txt'
    question.write_text('Original criteria, not the author output.', encoding='utf-8')
    spec = {'sources': {'A': {'path': str(original), 'role': 'author_response'},
                        'Q': {'path': str(question), 'role': 'user_input'}}, 'cases': [{
        'case_id': 'CASE-A', 'evidence_source_ids': ['A'], 'verification_scope': 'fixture response only',
        'expected_behavior': 'test protocol', 'must_avoid': 'test protocol',
        'machine_checks': {'actual_effect': variant != 'failed_effect'}}]}
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(spec), encoding='utf-8')
    def native_transport(**kwargs):
        detected = subprocess.run(['git', '-C', str(kwargs['project']), 'rev-parse', '--show-toplevel'],
                                  check=True, capture_output=True, text=True, encoding='utf-8')
        assert Path(detected.stdout.strip()).resolve() == kwargs['project'].resolve()
        assert kwargs['permission_mode'] == 'auto_approve'
        assert kwargs['model'] == 'gemini-3.8-flash-low'
        assert 'quote' not in json.dumps(kwargs['json_schema'])
        reference = kwargs['json_schema']['properties']['cases']['items']['properties']['references']['items']
        assert reference['properties']['source_id']['enum'] == ['A']
        assert kwargs['observe_endpoint']()['reached']
        source_index = json.loads((kwargs['project'] / 'sources.json').read_text(encoding='utf-8'))
        material = source_index[0]
        assert material['source_id'] == 'A'
        assert 'numbered_text' not in material
        assert Path(material['path']).is_absolute()
        assert (kwargs['project'] / material['path']).read_text(encoding='utf-8') == '1: 原始答复。\n2: 第二行。'
        assert material['line_count'] == 2
        row = {'case_id': 'CASE-A', 'verdict': 'passed', 'reason': '独立措辞。',
               'issues': [], 'limitations': [], 'references': [{
                   'source_id': 'X' if variant == 'wrong_source' else 'A', 'start_line': 1, 'end_line': 1}]}
        return {'mechanical_passed': True, 'failure_layer': None, 'outcome': 'endpoint_observed',
                'final_observation': {'review_inputs_unchanged': True},
                'last_result': {'response': '', 'structured_output': {'cases': [row, row] if variant == 'duplicate' else [row]}}}
    monkeypatch.setattr(reviewer, 'run_session', native_transport)
    report = reviewer.run_review(spec_path, tmp_path / '.artifacts/review')
    assert report['catalog_updated'] is False
    if variant in {'wrong_source', 'duplicate'}:
        assert report['execution']['report_valid'] is False
    else:
        row = report['cases'][0]
        assert row['references'][0]['original_text'] == '原始答复。\n'
        assert row['reason'] == '独立措辞。'
        assert row['summary']['semantic_content_machine_proven'] is False
        assert row['summary']['status'] == ('checks_failed' if variant == 'failed_effect' else 'passed')
def test_source_counts_and_declared_states_come_from_structured_input_not_review_prose():
    sources = {
        'product.yaml': source_record('product.yaml', 'schema_version: strixnova.project-product-definition.v1\nrevision:\n  status: draft\ncapabilities: [{capability_id: C1}, {capability_id: C2}]\n', role='original_input'),
        'facts.yaml': source_record('facts.yaml', 'schema_version: strixnova.project-domain-source.v1\nfacts: [{fact_id: F1, status: confirmed}, {fact_id: F2, status: retired}]\n', role='original_input'),
        'response': source_record('response', 'Everything is confirmed and there are 99 capabilities.', role='author_response'),
    }
    facts = declared_source_facts(sources)
    assert facts['original_input_count'] == 2
    assert facts['records'][0]['declared_revision']['status'] == 'draft'
    assert facts['records'][0]['capability_count'] == 2
    assert facts['records'][1]['declared_fact_status_counts'] == {'confirmed': 1, 'retired': 1}
    assert facts['semantic_content_machine_proven'] is False


def test_reconsideration_keeps_the_original_review_and_uses_its_frozen_sources(tmp_path, monkeypatch):
    monkeypatch.setattr(reviewer, 'ROOT', tmp_path)
    skill = tmp_path / 'strixnova/src/strixnova/resources/agent-skill/strixnova'
    skill.mkdir(parents=True)
    (skill / 'SKILL.md').write_text('fixture only', encoding='utf-8')
    answer = tmp_path / 'answer.txt'
    answer.write_text('An unsupported cause claim.', encoding='utf-8')
    question = tmp_path / 'question.txt'
    question.write_text('Original criteria only.', encoding='utf-8')
    spec = {'sources': {'answer': {'path': str(answer), 'role': 'author_response'},
                        'question': {'path': str(question), 'role': 'user_input'}}, 'cases': [{
        'case_id': 'CASE-REVIEW', 'evidence_source_ids': ['answer'], 'expected_behavior': 'Match recorded facts',
        'must_avoid': 'Invent causes', 'verification_scope': 'frozen answer only', 'machine_checks': {'input_preserved': True}}]}
    spec_path = tmp_path / 'spec.json'
    spec_path.write_text(json.dumps(spec), encoding='utf-8')
    calls = []
    def native_transport(**kwargs):
        calls.append(kwargs)
        reference = kwargs['json_schema']['properties']['cases']['items']['properties']['references']['items']
        assert reference['properties']['source_id']['enum'] == ['answer']
        verdict = 'passed' if len(calls) == 1 else 'needs_revision'
        row = {'case_id': 'CASE-REVIEW', 'verdict': verdict, 'reason': 'Native test transport response',
               'issues': [] if verdict == 'passed' else [{'category':'agent_output','description':'Cause unsupported'}],
               'limitations': [], 'references': [{'source_id':'answer','start_line':1,'end_line':1}]}
        receipt = {'mechanical_passed': True, 'failure_layer': None, 'outcome': 'endpoint_observed',
                   'final_observation': kwargs['observe_endpoint'](),
                   'last_result': {'conversation_id':'native-review-fixture','response':'','structured_output':{'cases':[row]}}}
        kwargs['evidence'].mkdir(parents=True)
        (kwargs['evidence']/'driver-receipt.json').write_text(json.dumps(receipt), encoding='utf-8')
        return receipt
    monkeypatch.setattr(reviewer, 'run_session', native_transport)
    prior = tmp_path / '.artifacts/prior'
    reviewer.run_review(spec_path, prior)
    old = (prior/'review.json').read_bytes()
    revised = reviewer.reconsider_review(prior, tmp_path/'.artifacts/correction', 'Check the recorded error, without presuming a verdict.')
    assert calls[-1]['conversation_id'] == 'native-review-fixture'
    assert calls[-1]['project'] == prior/'project'
    assert revised['cases'][0]['verdict'] == 'needs_revision'
    assert (prior/'review.json').read_bytes() == old
    (prior/'project/sources/0001.txt').write_text('changed', encoding='utf-8')
    with pytest.raises(ValueError, match='changed'):
        reviewer.reconsider_review(prior, tmp_path/'.artifacts/rejected', 'Recheck')
    assert len(calls) == 2
