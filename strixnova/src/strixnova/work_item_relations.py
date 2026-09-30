"""Semantic trace relations between WorkItems.

The confirmed direction of the source WorkItem owns each relation fact.  This
module validates that small contract and derives bidirectional read views; it
does not create a second persistence, scheduling, or conflict authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any
from strixnova.follow_ups import FollowUpError, normalize_ref, ref_key


WORK_ITEM_RELATION_SCHEMA = "strixnova.work-item-relation.v1"
WORK_ITEM_RELATION_TYPES = frozenset(
    {"related_to", "part_of", "depends_on", "follows_up", "supersedes"}
)


class WorkItemRelationError(ValueError):
    """A typed relation-contract failure for the Authority boundary."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise WorkItemRelationError(
            "work_item_relation_invalid",
            f"{field} 必须是字符串",
        )
    result = value.strip()
    if not result:
        raise WorkItemRelationError(
            "work_item_relation_invalid",
            f"{field} 不能为空",
        )
    return result


def normalize_work_item_relations(
    value: Any,
    *,
    source_work_item_id: str,
) -> list[dict[str, Any]]:
    """Validate and normalize the relations declared by one source WorkItem."""

    if not isinstance(value, list):
        raise WorkItemRelationError(
            "work_item_relation_invalid",
            "direction.work_item_relations 必须是数组",
        )
    source_id = _required_text(source_work_item_id, "source_work_item_id")
    required = {"target_work_item_id", "relation_type", "reason"}
    identities: set[tuple[str, str]] = set()
    normalized: list[dict[str, str]] = []
    for index, relation in enumerate(value):
        field = f"direction.work_item_relations[{index}]"
        if not isinstance(relation, Mapping):
            raise WorkItemRelationError(
                "work_item_relation_invalid",
                f"{field} 必须是对象",
            )
        missing = sorted(required - set(relation))
        extra = sorted(set(relation) - required - {"follow_up_refs"})
        if missing:
            raise WorkItemRelationError(
                "work_item_relation_invalid",
                f"{field} 缺少字段：" + ", ".join(missing),
            )
        if extra:
            raise WorkItemRelationError(
                "work_item_relation_invalid",
                f"{field} 包含未知字段：" + ", ".join(extra),
            )
        target_id = _required_text(
            relation.get("target_work_item_id"),
            f"{field}.target_work_item_id",
        )
        relation_type = _required_text(
            relation.get("relation_type"),
            f"{field}.relation_type",
        )
        reason = _required_text(relation.get("reason"), f"{field}.reason")
        if relation_type not in WORK_ITEM_RELATION_TYPES:
            raise WorkItemRelationError(
                "work_item_relation_type_invalid",
                f"{field}.relation_type 无效：{relation_type}",
            )
        if target_id == source_id:
            raise WorkItemRelationError(
                "work_item_relation_self_reference",
                "WorkItem 不能关联自身",
            )
        identity = (relation_type, target_id)
        if identity in identities:
            raise WorkItemRelationError(
                "work_item_relation_duplicate",
                (
                    "WorkItem 关系重复："
                    f"{relation_type}/{target_id}"
                ),
            )
        identities.add(identity)
        refs = relation.get("follow_up_refs", [])
        if not isinstance(refs, list) or (refs and relation_type != "follows_up"):
            raise WorkItemRelationError("follow_up_relation_invalid", "精确跟进引用只能用于 follows_up 关系")
        try:
            refs = [normalize_ref(ref) for ref in refs]
        except FollowUpError as error:
            raise WorkItemRelationError(error.code, str(error)) from error
        if any(ref["work_item_id"] != target_id for ref in refs) or len({ref_key(ref) for ref in refs}) != len(refs):
            raise WorkItemRelationError("follow_up_relation_invalid", "跟进引用必须唯一指向关系目标事项")
        normalized.append(
            {
                "target_work_item_id": target_id,
                "relation_type": relation_type,
                "reason": reason,
                **({"follow_up_refs": refs} if refs else {}),
            }
        )
    return normalized


def relation_target_ids(relations: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return distinct target IDs in declaration order."""

    return list(
        dict.fromkeys(str(relation["target_work_item_id"]) for relation in relations)
    )


def build_work_item_relation_views(
    work_items: Sequence[Mapping[str, Any]],
) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Derive source-declared and target-referenced read views."""

    by_id = {str(item["work_item_id"]): item for item in work_items}
    views: dict[str, dict[str, list[dict[str, Any]]]] = {
        identifier: {"declared": [], "referenced_by": []}
        for identifier in by_id
    }
    for source_id, source in by_id.items():
        data = source.get("data")
        data = data if isinstance(data, Mapping) else {}
        confirmation = data.get("direction_confirmation")
        if not isinstance(confirmation, Mapping) or (
            confirmation.get("accepted") is not True
        ):
            continue
        direction = data.get("direction")
        direction = direction if isinstance(direction, Mapping) else {}
        raw_relations = direction.get("work_item_relations")
        if raw_relations is None:
            continue
        relations = normalize_work_item_relations(
            raw_relations,
            source_work_item_id=source_id,
        )
        for relation in relations:
            target_id = relation["target_work_item_id"]
            target = by_id.get(target_id)
            if target is None:
                continue
            edge = {
                "source_work_item_id": source_id,
                "target_work_item_id": target_id,
                "relation_type": relation["relation_type"],
                "reason": relation["reason"],
                **({"follow_up_refs": deepcopy(relation["follow_up_refs"])} if relation.get("follow_up_refs") else {}),
            }
            views[source_id]["declared"].append(
                {
                    **edge,
                    "related_work_item": _related_work_item(target),
                }
            )
            views[target_id]["referenced_by"].append(
                {
                    **edge,
                    "related_work_item": _related_work_item(source),
                }
            )
    for relation_view in views.values():
        relation_view["declared"].sort(key=_relation_sort_key)
        relation_view["referenced_by"].sort(key=_relation_sort_key)
    return views


def empty_work_item_relation_view() -> dict[str, list[dict[str, Any]]]:
    return {"declared": [], "referenced_by": []}


def _related_work_item(item: Mapping[str, Any]) -> dict[str, str]:
    return {
        "work_item_id": str(item["work_item_id"]),
        "title": str(item["title"]),
        "status": str(item["status"]),
    }


def _relation_sort_key(relation: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(relation["relation_type"]),
        str(relation["source_work_item_id"]),
        str(relation["target_work_item_id"]),
    )


__all__ = [
    "WORK_ITEM_RELATION_SCHEMA",
    "WORK_ITEM_RELATION_TYPES",
    "WorkItemRelationError",
    "build_work_item_relation_views",
    "empty_work_item_relation_view",
    "normalize_work_item_relations",
    "relation_target_ids",
]
