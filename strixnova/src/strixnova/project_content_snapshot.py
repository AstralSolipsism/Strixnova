"""Repository-qualified, content-addressed inputs without project state writes."""

from collections.abc import Mapping, Sequence
import hashlib
import json
import re
from typing import Any

from strixnova.git_project_reader import GitProjectReader, repository_relative_path


def repository_path_key(repository_id: str | None, path: str) -> str:
    """Encode a two-part identity for JSON object indexes, never for file I/O."""
    if repository_id is not None and re.fullmatch(r"REPO-[0-9A-F]{16}", repository_id) is None:
        raise ValueError("Invalid repository identity")
    return f"{repository_id or '_'}:{repository_relative_path(path, 'repository path')}"


def split_repository_path_key(value: str) -> tuple[str | None, str]:
    identifier, separator, path = value.partition(":")
    if not separator or (identifier != "_" and (not identifier.startswith("REPO-") or len(identifier) != 21 or any(character not in "0123456789ABCDEF" for character in identifier[5:]))):
        raise ValueError("Invalid repository-qualified path index")
    return None if identifier == "_" else identifier, repository_relative_path(path, "repository path")


def content_fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def review_subject(work_item: Mapping[str, Any], readers: Mapping[str | None, GitProjectReader], *, authority_basis: Mapping[str, Any] | None = None, canonical_unbound: bool = True) -> dict[str, Any]:
    """Bind an Agent's later result to content obtained before its review.

    This proves identity within declared inputs, not the completeness of the
    selected scope, actual reading, or the correctness of the Agent's judgment.
    """
    data = work_item.get("data") or {}
    engineering = data.get("engineering") or {}
    plan = engineering.get("plan") or {}
    if not plan:
        raise ValueError("审阅对象需要当前工程方案")
    repositories = []
    for identifier, reader in sorted(readers.items(), key=lambda pair: pair[0] or ""):
        paths = set(reader.tracked_paths())
        for operation in plan.get("operations") or []:
            if operation.get("repository_id") != identifier:
                continue
            for field in ("path", "to_path"):
                path = operation.get(field)
                if path:
                    paths.update(reader.tracked_paths(path) or [path])
        repositories.append(capture_repository_content(identifier, reader, sorted(paths), canonical=identifier is not None or canonical_unbound))
    receipts = [{key: value for key, value in receipt.items() if not key.startswith("_")} for receipt in data.get("verifications") or []]
    subject = {
        "schema_version": "strixnova.review-subject.v1",
        "work_item_id": work_item.get("work_item_id"),
        "plan_id": plan.get("plan_id"),
        "plan_sha256": content_fingerprint(plan),
        "direction_sha256": content_fingerprint(data.get("direction")),
        "assessment_sha256": content_fingerprint(engineering.get("assessment")),
        "authority_decisions_sha256": content_fingerprint(data.get("project_authority_decisions") or []),
        "authority_reviews_sha256": content_fingerprint(data.get("project_authority_reviews") or []),
        "authority_basis": dict(authority_basis or {}),
        "verification_receipts_sha256": content_fingerprint(receipts),
        "content_snapshot": compose_content_snapshot(str(plan.get("plan_id") or ""), repositories),
        "semantic_content_machine_proven": False,
        "writes_performed": False,
    }
    return {**subject, "subject_ref": "review-subject:" + content_fingerprint(subject)}


def continued_verification_paths(
    plan: Mapping[str, Any], receipts: Sequence[Mapping[str, Any]],
    completions: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str | None, set[str]]]:
    """Keep completed prerequisites valid for an approved final alignment refresh.

    Only the exact receipts that completed every prerequisite may retain their
    historical proof for transferred paths. The refresh slice's own receipts
    still bind all current inputs; no receipt or stored fingerprint is changed.
    """
    slices = {item['slice_id']: item for item in plan.get('implementation_slices') or []}
    refreshes = [item for item in slices.values() if item.get('continued_operation_refs')]
    if len(refreshes) != 1:
        return {}
    refresh = refreshes[0]
    ancestors: set[str] = set()
    pending = list(refresh.get('depends_on') or [])
    while pending:
        identifier = pending.pop()
        if identifier not in slices or identifier == refresh['slice_id']:
            return {}
        if identifier not in ancestors:
            ancestors.add(identifier)
            pending.extend(slices[identifier].get('depends_on') or [])
    completed = {item.get('slice_id'): item for item in completions
                 if item.get('schema_version') == 'strixnova.implementation-slice-completion.v1'
                 and item.get('semantic_content_machine_proven') is False}
    latest = {item.get('command_id'): item for item in receipts}
    command_ids: set[str] = set()
    for identifier in ancestors:
        completion = completed.get(identifier)
        if completion is None:
            return {}
        required = set(slices[identifier].get('verification_command_ids') or [])
        if any(command_id not in latest or latest[command_id].get('result') != 'passed'
               or latest[command_id].get('inputs_changed_during_execution') is True
               or (latest[command_id].get('code_change_assessment') or {}).get('needs_retest') is not False
               for command_id in required):
            return {}
        if set(completion.get('source_receipt_ids') or []) != {latest[command_id].get('receipt_id') for command_id in required}:
            return {}
        command_ids.update(required)
    paths: dict[str | None, set[str]] = {}
    operations = plan.get('operations') or []
    owned = {reference for identifier in ancestors for reference in slices[identifier].get('operation_refs') or []}
    for reference in refresh['continued_operation_refs']:
        match = re.fullmatch(r'operations\[(\d+)\]', reference)
        if reference not in owned or match is None or int(match[1]) >= len(operations):
            return {}
        operation = operations[int(match[1])]
        paths.setdefault(operation.get('repository_id'), set()).update(
            operation[field] for field in ('path', 'to_path') if operation.get(field)
        )
    return {identifier: paths for identifier in command_ids}


def verification_snapshot_matches(
    expected: Mapping[str, Any], current: Mapping[str, Any],
    continued_paths: Mapping[str | None, set[str]],
) -> bool:
    if not continued_paths:
        return expected == current

    def retained(value):
        repositories = []
        for entry in value.get('repositories') or []:
            if entry.get('content_sha256') != content_fingerprint(entry.get('paths')):
                return None
            remaining = [path for path in entry['paths'] if path['path'] not in continued_paths.get(entry['repository_id'], set())]
            repositories.append({**entry, 'paths': remaining, 'content_sha256': content_fingerprint(remaining)})
        original = {'repositories': value.get('repositories'), 'dependencies': value.get('dependencies')}
        if value.get('content_sha256') != content_fingerprint(original):
            return None
        selected = {**value, 'repositories': repositories}
        selected['content_sha256'] = content_fingerprint({'repositories': repositories, 'dependencies': value.get('dependencies')})
        return selected

    retained_expected, retained_current = retained(expected), retained(current)
    return retained_expected is not None and retained_expected == retained_current


def verification_input_paths(plan: Mapping[str, Any], command: Mapping[str, Any], repository_id: str | None, reader: GitProjectReader) -> set[str]:
    """Bind a command to its declared inputs and preceding slice dependencies.

    A later slice's exclusive paths are not inputs to an earlier slice unless
    its case report explicitly declares them. Other existing files remain
    conservative inputs when no case-level input list is available.
    """
    declared = (command.get("case_report") or {}).get("input_paths")
    if declared and repository_id == command.get("repository_id"):
        paths: set[str] = set()
        for path in declared:
            children = reader.tracked_paths(path)
            paths.update(children or [path])
        return paths
    slices = {value["slice_id"]: value for value in plan.get("implementation_slices") or []}
    included = {identifier for identifier, value in slices.items() if command.get("command_id") in value.get("verification_command_ids", [])}
    pending = list(included)
    while pending:
        for dependency in slices[pending.pop()].get("depends_on", []):
            if dependency not in included:
                included.add(dependency)
                pending.append(dependency)
    owned = {reference for identifier in included for field in ("operation_refs", "continued_operation_refs") for reference in slices[identifier].get(field, [])}
    planned, relevant = set(), set()
    for index, operation in enumerate(plan.get("operations") or []):
        if operation.get("repository_id") != repository_id:
            continue
        paths = {str(path) for path in (operation.get("path"), operation.get("to_path")) if path}
        planned.update(paths)
        if not included or f"operations[{index}]" in owned:
            relevant.update(paths)
    return (set(reader.tracked_paths()) | relevant) - (planned - relevant)


def capture_repository_content(repository_id: str | None, reader: GitProjectReader, paths: Sequence[str] | None = None, *, canonical: bool = True) -> dict[str, Any]:
    selected = sorted(set(reader.tracked_paths() if paths is None else paths))
    selected = [path for path in selected if path.split("/", 1)[0] not in {".git", ".strixnova"}]
    existing = [path for path in selected if reader.exists(path)]
    contents = dict(reader.iter_canonical_files(existing, "project content input")) if canonical else {path: reader.read_bytes(path, "project content input") for path in existing}
    entries = []
    for path in selected:
        exists = path in contents
        entries.append({
            "path": path, "state": "file" if exists else "absent",
            "sha256": hashlib.sha256(contents[path]).hexdigest() if exists else "",
        })
    return {
        "repository_id": repository_id, "paths": entries,
        "content_sha256": content_fingerprint(entries),
    }


def compose_content_snapshot(plan_id: str, repositories: Sequence[Mapping[str, Any]], *, dependencies: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    inputs = {"repositories": list(repositories), "dependencies": list(dependencies)}
    identifiers = [entry["repository_id"] for entry in repositories]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("A content snapshot cannot contain duplicate repository identities")
    return {
        "schema_version": "strixnova.project-content-snapshot.v1", "plan_id": plan_id,
        **inputs, "content_sha256": content_fingerprint(inputs),
        "semantic_content_machine_proven": False,
    }


def snapshot_observations(expected: Mapping[str, Any] | None, current: Mapping[str, Any] | None) -> dict[str, Any]:
    """Compare captured scope, without deciding relevance or retest necessity."""
    def index(snapshot):
        if not isinstance(snapshot, Mapping) or snapshot.get("schema_version") != "strixnova.project-content-snapshot.v1":
            return None
        repositories = snapshot.get("repositories")
        if not isinstance(repositories, list) or snapshot.get("content_sha256") != content_fingerprint({"repositories": repositories, "dependencies": snapshot.get("dependencies")}):
            return None
        result = {}
        for repository in repositories:
            paths = repository.get("paths")
            if not isinstance(paths, list) or repository.get("content_sha256") != content_fingerprint(paths):
                return None
            for path in paths:
                key = repository_path_key(repository.get("repository_id"), path["path"])
                if key in result:
                    return None
                result[key] = path
        return result
    before, after = index(expected), index(current)
    changed, unchanged, uncaptured = [], [], []
    if before is not None and after is not None:
        for path in sorted(before.keys() | after.keys()):
            if path not in before or path not in after:
                uncaptured.append(path)
            elif before[path] == after[path]:
                unchanged.append(path)
            else:
                changed.append(path)
    else:
        uncaptured = sorted((before or {}).keys() | (after or {}).keys())
    return {"scope": "captured_inputs_only", "comparison_available": before is not None and after is not None,
            "expected_content_sha256": expected["content_sha256"] if before is not None else None,
            "observed_content_sha256": current["content_sha256"] if after is not None else None,
            "changed": changed, "unchanged": unchanged, "uncaptured": uncaptured,
            "outside_captured_scope": "unknown", "semantic_content_machine_proven": False,
            "agent_judgment_required": ["relevance", "assertion_sufficiency", "external_dependencies", "needs_retest"]}
