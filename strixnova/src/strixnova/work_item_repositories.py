"""Repository responsibilities owned by the existing WorkItem aggregate."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


_UNSELECTED = object()
_selected_repository: ContextVar[Any] = ContextVar("strixnova_repository_operation", default=_UNSELECTED)


@contextmanager
def repository_operation(repository_id: str | None):
    """Select a repository for one application operation, never a second item."""
    token = _selected_repository.set(repository_id)
    try:
        yield
    finally:
        _selected_repository.reset(token)


def selected_repository(data: Mapping[str, Any], status: str) -> str | None:
    pending = data.get("pending_effect") or {}
    if "repository_id" in pending:
        return pending["repository_id"]
    selected = _selected_repository.get()
    if selected is not _UNSELECTED:
        return selected
    return ordered_repository(data, status)


def ordered_repository(data: Mapping[str, Any], status: str) -> str | None:
    """The aggregate's next repository, independent of a reader's selection."""
    entries = data.get("repository_deliveries") or []
    if status == "implementation_ready":
        entries = [entry for entry in entries if not (entry.get("git") or {}).get("work_ref")]
    else:
        entries = [entry for entry in entries if not (entry.get("git") or {}).get("cleanup", {}).get("safe")] or entries
    if entries:
        return entries[0]["repository_id"]
    return None


def repository_view(data: Mapping[str, Any], status: str, *, repository_id: Any = _UNSELECTED) -> dict[str, Any]:
    """Project the selected Git facts without persisting a duplicate singleton.

    Original snapshots without execution entries retain their recorded git value.
    This is also the only interpretation of old single-repository execution facts.
    """
    projected = deepcopy(dict(data))
    identifier = selected_repository(data, status) if repository_id is _UNSELECTED else repository_id
    entries = data.get("repository_deliveries") or []
    entry = next((entry for entry in entries if entry["repository_id"] == identifier), None)
    projected["selected_repository_id"] = identifier
    if entry is not None:
        projected["git"] = deepcopy(entry.get("git") or {})
        if not projected["git"] and len(entries) == 1 and "git" in data:
            projected["git"] = deepcopy(data["git"])
    elif entries:
        projected["git"] = {}
    return projected


def repository_item(current: Mapping[str, Any], repository_id: str | None) -> dict[str, Any]:
    result = deepcopy(dict(current))
    result["data"] = repository_view(current["data"], str(current["status"]), repository_id=repository_id)
    return result


def persist_repository_view(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return one canonical representation for the next recorded snapshot."""
    result = deepcopy(dict(data))
    identifier = result.pop("selected_repository_id", None)
    entries = result.get("repository_deliveries") or []
    if not entries and (result.get("git") or {}).get("work_ref"):
        plan = (result.get("engineering") or {}).get("plan") or {}
        git = result["git"]
        if plan.get("plan_id"):
            entries = [{
                "schema_version": "strixnova.repository-delivery-responsibility.v1",
                "repository_id": identifier,
                "plan_id": plan["plan_id"],
                "investigation_commit": git.get("base_commit"),
                "target_ref": git.get("target_ref"),
                "operation_refs": [f"operations[{index}]" for index, _ in enumerate(plan.get("operations") or [])],
                "implementation_slice_ids": [entry["slice_id"] for entry in plan.get("implementation_slices") or []],
            }]
            result["repository_deliveries"] = entries
    if entries:
        git = result.pop("git", {})
        entry = next((entry for entry in entries if entry["repository_id"] == identifier), None)
        if entry is not None and git:
            entry["git"] = git
    return result


def repository_phase(entry: Mapping[str, Any]) -> str:
    git = entry.get("git") or {}
    if (git.get("cleanup") or {}).get("safe") is True:
        return "completed"
    integration = git.get("integration") or {}
    if integration.get("outcome") == "conflict" or git.get("conflict_resolution"):
        if not integration.get("integrated_commit"):
            return "integration_conflict"
    if integration.get("integrated_commit"):
        return "cleanup_required"
    if git.get("result_commits"):
        return "integration_required"
    return "commit_required" if git.get("work_ref") else "implementation_ready"


def previous_integrations(data: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project prior completed contributions without reopening their execution."""
    records = {}
    for delivery in data.get("superseded_deliveries") or []:
        for entry in delivery.get("repository_deliveries") or []:
            integration = (entry.get("git") or {}).get("integration") or {}
            commit = integration.get("integrated_commit")
            if commit:
                records[(entry["repository_id"], commit)] = {"repository_id": entry["repository_id"], "plan_id": entry["plan_id"], "integration": deepcopy(integration)}
    return list(records.values())


def planned_repository_deliveries(plan: Mapping[str, Any]) -> list[dict[str, Any]]:
    scope = plan.get("repository_scope")
    if not isinstance(scope, Mapping):
        # Original recorded plans did not contain repository identities.
        return []
    operations = list(plan.get("operations") or [])
    deliveries = []
    for entry in scope["repositories"]:
        if entry["role"] != "modify":
            continue
        identifier = entry["repository_id"]
        references = [
            f"operations[{index}]" for index, operation in enumerate(operations)
            if operation.get("repository_id") == identifier
        ]
        if not references:
            continue
        slices = [
            item["slice_id"] for item in plan.get("implementation_slices") or []
            if set(references).intersection([*item["operation_refs"], *item.get("continued_operation_refs", [])])
        ]
        deliveries.append({
            "schema_version": "strixnova.repository-delivery-responsibility.v1",
            "repository_id": identifier,
            "plan_id": plan["plan_id"],
            "investigation_commit": None if entry["investigation_ref"] == "working_tree" else entry["investigation_ref"],
            "target_ref": entry["target_ref"],
            "operation_refs": references,
            "implementation_slice_ids": slices,
        })
    order = (plan.get("delivery_plan") or {}).get("repository_order") or []
    return sorted(deliveries, key=lambda entry: order.index(entry["repository_id"]) if entry["repository_id"] in order else len(order))


def repository_responsibility_view(item: Mapping[str, Any]) -> dict[str, Any]:
    data = item.get("data") or {}
    plan = (data.get("engineering") or {}).get("plan") or {}
    responsibilities = deepcopy(data.get("repository_deliveries") or [])
    return {
        "schema_version": "strixnova.repository-delivery-responsibility-view.v1",
        "project_id": data.get("project_id"),
        "work_item_id": item["work_item_id"],
        "work_item_version": item["version"],
        "current_plan_id": plan.get("plan_id"),
        "responsibilities": [
            {**entry, "current_plan": entry["plan_id"] == plan.get("plan_id")}
            for entry in responsibilities
        ],
        "scope": "repository_responsibilities_and_execution",
        "execution_facts_included": True,
        "overall_result_confirmation": deepcopy(data.get("actual_result_confirmation")),
    }
