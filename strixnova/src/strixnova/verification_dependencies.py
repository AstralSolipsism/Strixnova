"""Versioned service/artifact observations from the approved command's output."""

from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any


MARKER = 'STRIXNOVA_DEPENDENCY_EVIDENCE='


def normalize_dependency_checks(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise ValueError('dependency_checks must be an array')
    result, identifiers = [], set()
    fields = {'dependency_id', 'kind', 'expected_version', 'expected_contract_sha256', 'environment', 'max_age_seconds'}
    for entry in value:
        if not isinstance(entry, Mapping) or set(entry) != fields:
            raise ValueError('Each dependency check requires identity, kind, version, contract, environment and freshness')
        identifier = entry['dependency_id']
        if not isinstance(identifier, str) or re.fullmatch(r'[A-Za-z][A-Za-z0-9._:-]{0,127}', identifier) is None or identifier in identifiers:
            raise ValueError('Dependency identities must be valid and unique within a command')
        if entry['kind'] not in {'service', 'artifact'} or any(not isinstance(entry[key], str) or not entry[key].strip() for key in ('expected_version', 'environment')):
            raise ValueError('Dependency kind, version and environment must be explicit')
        if not isinstance(entry['expected_contract_sha256'], str) or re.fullmatch('[0-9a-f]{64}', entry['expected_contract_sha256']) is None:
            raise ValueError('Dependency contract must use an exact SHA-256')
        age = entry['max_age_seconds']
        if not (type(age) is int and 1 <= age <= 604800) and not (entry['kind'] == 'artifact' and age is None):
            raise ValueError('Service observations need an explicit finite freshness window')
        identifiers.add(identifier)
        result.append(dict(entry))
    return result


def collect_dependency_evidence(checks: Sequence[Mapping[str, Any]], stdout: bytes, *, observed_at: str) -> dict[str, Any]:
    reports: dict[str, tuple[dict[str, Any], int, str]] = {}
    malformed = []
    for index, line in enumerate(stdout.decode('utf-8', errors='replace').splitlines(), 1):
        if not line.startswith(MARKER):
            continue
        raw = line[len(MARKER):]
        try:
            if len(raw.encode('utf-8')) > 65536:
                raise ValueError
            value = json.loads(raw)
            required = {'schema_version', 'dependency_id', 'version', 'contract_sha256', 'environment', 'evidence_refs'}
            if not isinstance(value, dict) or set(value) != required or value['schema_version'] != 'strixnova.dependency-observation.v1':
                raise ValueError
            identifier = value['dependency_id']
            if not isinstance(identifier, str) or identifier in reports:
                raise ValueError
            if not isinstance(value['evidence_refs'], list) or not value['evidence_refs'] or any(not isinstance(ref, str) or not ref.strip() for ref in value['evidence_refs']):
                raise ValueError
            reports[identifier] = (value, index, hashlib.sha256(raw.encode('utf-8')).hexdigest())
        except (ValueError, TypeError, KeyError):
            malformed.append(index)
    records = []
    expected_ids = {entry['dependency_id'] for entry in checks}
    for check in checks:
        found = reports.get(check['dependency_id'])
        observation, line_number, digest = found if found is not None else (None, None, None)
        matches = observation is not None and all(observation.get(actual) == check[expected] for actual, expected in (('version', 'expected_version'), ('contract_sha256', 'expected_contract_sha256'), ('environment', 'environment')))
        records.append({
            'dependency_id': check['dependency_id'], 'kind': check['kind'],
            'status': 'matched' if matches else 'missing' if observation is None else 'mismatch',
            'observed_at': observed_at, 'max_age_seconds': check['max_age_seconds'],
            'observation': observation, 'stdout_line': line_number, 'report_sha256': digest,
        })
    return {
        'schema_version': 'strixnova.verification-dependency-evidence.v1',
        'status': 'complete' if not malformed and not (set(reports) - expected_ids) and all(entry['status'] == 'matched' for entry in records) else 'blocked',
        'records': records, 'malformed_stdout_lines': malformed,
        'unplanned_dependency_ids': sorted(set(reports) - expected_ids),
        'source_scope': 'observations_from_approved_command_stdout',
        'source_code_coverage_proven': False, 'semantic_content_machine_proven': False,
    }


def validate_dependency_evidence(evidence: Any, checks: Sequence[Mapping[str, Any]]) -> None:
    if not isinstance(evidence, Mapping) or evidence.get('schema_version') != 'strixnova.verification-dependency-evidence.v1' or evidence.get('semantic_content_machine_proven') is not False or evidence.get('source_code_coverage_proven') is not False:
        raise ValueError('Dependency evidence must preserve its observation and source-coverage boundary')
    records = evidence.get('records')
    if not isinstance(records, list) or len(records) != len(checks):
        raise ValueError('Dependency evidence must cover exactly the planned checks')
    matched = True
    for check, record in zip(checks, records, strict=True):
        if not isinstance(record, Mapping) or any(record.get(key) != check[key] for key in ('dependency_id', 'kind', 'max_age_seconds')):
            raise ValueError('Dependency evidence is bound to different requirements')
        observation = record.get('observation')
        matches = isinstance(observation, Mapping) and all(observation.get(actual) == check[expected] for actual, expected in (('version', 'expected_version'), ('contract_sha256', 'expected_contract_sha256'), ('environment', 'environment')))
        if record.get('status') != ('matched' if matches else 'missing' if observation is None else 'mismatch'):
            raise ValueError('Dependency evidence status does not follow its observed facts')
        matched = matched and matches
    complete = matched and not evidence.get('malformed_stdout_lines') and not evidence.get('unplanned_dependency_ids')
    if evidence.get('status') != ('complete' if complete else 'blocked'):
        raise ValueError('Dependency evidence summary contradicts its observations')


def dependency_evidence_stale(evidence: Mapping[str, Any], *, now: datetime | None = None) -> bool:
    if evidence.get('status') != 'complete':
        return False
    current = now or datetime.now(timezone.utc)
    for record in evidence.get('records', []):
        age = record.get('max_age_seconds')
        if age is None:
            continue
        try:
            observed = datetime.fromisoformat(str(record['observed_at']).replace('Z', '+00:00'))
            if observed.tzinfo is None or (current - observed).total_seconds() < 0 or (current - observed).total_seconds() > age:
                return True
        except (ValueError, KeyError, TypeError):
            return True
    return False
