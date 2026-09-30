"""Prepare fresh protocol inputs for deterministic tests, never semantic proof.

Existing references are preserved so stale-reference regression tests exercise
the public rejection instead of silently rebinding an old result.
"""
from copy import deepcopy
import json

from strixnova.actual_result import ACTUAL_RESULT_SCHEMA
from strixnova.host_adapter import LocalHostAdapter


def bind_subject(project, identifier, payload, *, bindings=None):
    result = deepcopy(payload)
    if result.get("schema_version") != ACTUAL_RESULT_SCHEMA or "review_subject_ref" in result:
        return result
    adapter = LocalHostAdapter(project, project_bindings=bindings)
    reference = "engineering.review_subject#/subject_ref"
    response = adapter.next_step(identifier, record_refs=[reference], max_output_bytes=4096)
    result["review_subject_ref"] = response["records"][reference]
    return result


def bind_subject_arguments(project, arguments):
    result = list(arguments)
    if "--input" not in result or "--work-item-id" not in result:
        return result
    index = result.index("--input") + 1
    try:
        payload = json.loads(result[index])
    except (ValueError, TypeError):
        return result
    if not isinstance(payload, dict) or payload.get("schema_version") != ACTUAL_RESULT_SCHEMA:
        return result
    identifier = result[result.index("--work-item-id") + 1]
    bindings = json.loads(result[result.index("--bindings") + 1]) if "--bindings" in result else None
    result[index] = json.dumps(bind_subject(project, identifier, payload, bindings=bindings), ensure_ascii=False)
    return result
