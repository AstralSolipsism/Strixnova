"""Deterministic evidence binding for external acceptance, not a semantic judge."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from collections import Counter
import yaml


def source_record(source_id: str, text: str, *, role: str) -> dict:
    """Keep the exact captured text; numbering is only a reviewer read view."""
    return {'source_id': source_id, 'role': role, 'text': text,
            'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest()}


def numbered_source(source: dict) -> str:
    return '\n'.join(f'{i}: {line}' for i, line in enumerate(source['text'].splitlines(), 1))


def declared_source_facts(sources: dict[str, dict]) -> dict:
    """Expose declared states and counts; never infer adoption or meaning."""
    records = []
    for identity, source in sources.items():
        if source['role'] != 'original_input' or not identity.endswith(('.yaml', '.yml', '.json')):
            continue
        value = yaml.safe_load(source['text'])
        if not isinstance(value, dict) or not str(value.get('schema_version', '')).startswith('strixnova.'):
            continue
        row = {'source_id': identity}
        if isinstance(value.get('revision'), dict):
            row['declared_revision'] = deepcopy(value['revision'])
        if isinstance(value.get('capabilities'), list):
            row['capability_count'] = len(value['capabilities'])
        if isinstance(value.get('facts'), list):
            row['fact_count'] = len(value['facts'])
            row['declared_fact_status_counts'] = dict(Counter(str(fact.get('status', 'missing')) for fact in value['facts']))
        if len(row) > 1:
            records.append(row)
    return {'original_input_count': sum(source['role'] == 'original_input' for source in sources.values()),
            'records': records, 'semantic_content_machine_proven': False}


def attach_references(review: dict, sources: dict[str, dict], *, allowed_ids: set[str]) -> dict:
    """Resolve model-supplied locations; the program, not the model, copies text.

    A valid reference is not proof that it supports the reviewer's conclusion.
    Case-specific allowed IDs prevent quoting a question or another response in
    place of this case's actual output. Raw review is never overwritten.
    """
    attached = deepcopy(review)
    references = attached.get('references')
    if not isinstance(references, list) or not references:
        raise ValueError('Review needs source references')
    for ref in references:
        identity = ref.get('source_id')
        if identity not in allowed_ids or identity not in sources:
            raise ValueError('Reference does not belong to this case output')
        source = sources[identity]
        if source['role'] not in {'author_response', 'author_artifact', 'skill_contract'}:
            raise ValueError('Input material cannot substitute for the reviewed output')
        text = source['text']
        if hashlib.sha256(text.encode('utf-8')).hexdigest() != source['sha256']:
            raise ValueError('Source changed after capture')
        start, end = ref.get('start_line'), ref.get('end_line')
        lines = text.splitlines(keepends=True)
        if (type(start) is not int or type(end) is not int
                or not 1 <= start <= end <= len(lines)):
            raise ValueError('Invalid reference line range')
        ref.update(original_text=''.join(lines[start - 1:end]),
                   source_sha256=source['sha256'], source_role=source['role'])
    return attached


def summarize_case(*, machine_checks: dict[str, bool], review: dict | None,
                   execution: dict | None = None) -> dict:
    """Keep check results and a native reviewer's verdict separate."""
    if not machine_checks or any(type(v) is not bool for v in machine_checks.values()):
        raise ValueError('Explicit boolean machine checks required')
    verdict = review.get('verdict') if review else None
    if verdict not in {None, 'passed', 'needs_revision', 'blocked'}:
        raise ValueError('Unknown reviewer verdict')
    layer = None
    if execution is not None and not execution['mechanical_passed']:
        status, layer = 'execution_incomplete', execution['failure_layer']
    elif not all(machine_checks.values()):
        status, layer = 'checks_failed', 'undetermined'
    elif verdict is None:
        status = 'pending_review'
    else:
        status = verdict
        if verdict != 'passed':
            layer = 'reviewer_reported'  # Issues carry the reviewer's diagnosis.
    return {'status': status, 'failure_layer': layer,
            'machine_checks': machine_checks, 'reviewer_verdict': verdict,
            'semantic_content_machine_proven': False, 'owner_accepted': False}


def original_output_hashes(work: Path, project: Path) -> dict[str, str]:
    recorded = json.loads((work/'observations/setup-provenance.json').read_text(encoding='utf-8'))['source_files']
    return {str(project/name):digest for name,digest in recorded.items()
            if name.startswith('.strixnova/artifacts/') and not name.startswith('.strixnova/artifacts/maintenance/')}
