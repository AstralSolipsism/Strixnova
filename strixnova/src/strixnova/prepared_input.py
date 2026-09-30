"""Mechanical input preparation. Transport snapshots never own workflow state.

The adapter rechecks a preparation against the existing read model before any
use. Semantic fields stay absent until a caller explicitly supplies them.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import hashlib
import json
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from strixnova.confirmation_protocol import attach_confirmation_message
from strixnova.follow_ups import declared_refs
from strixnova.project_authority_progress import current_semantic_reviews


class PreparedInputError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None, payload: Any = None):
        super().__init__(message)
        self.code, self.details, self.payload = code, details, payload


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def result_requirements(current: Mapping[str, Any], coverage: Mapping[str, Any],
                        subject_ref: str) -> tuple[dict, list[dict]]:
    """Enumerate identities already required by the confirmed plan and records."""
    data = current["data"]
    engineering = data["engineering"]
    plan, assessment = engineering["plan"], engineering["assessment"]
    template = {
        "schema_version": "strixnova.actual-result.v1",
        "semantic_content_machine_proven": False,
        "review_subject_ref": subject_ref,
        "verification_receipt_ids": sorted(set(coverage["latest_receipt_ids"].values())),
    }
    rows: list[dict] = []

    def row(kind: str, identity: str, path: list, fixed: dict, source: Any):
        key = f"{kind}:{identity}"
        if any(item["id"] == key for item in rows):
            raise PreparedInputError("preparation_identity_ambiguous", key)
        rows.append({"id": key, "path": path, "fixed": deepcopy(fixed), "source": deepcopy(source)})
        return deepcopy(fixed)

    def append(field: str, kind: str, identity: str, fixed: dict, source: Any):
        values = template.setdefault(field, [])
        values.append(row(kind, identity, [field, len(values)], fixed, source))

    for field in ("domain_fact_change_results", "method_application_results", "governance_rule_results",
                  "semantic_finding_results", "verification_review_results", "long_lived_refs", "follow_up_results"):
        template[field] = []
    for item in assessment.get("domain_fact_changes", []):
        append("domain_fact_change_results", "fact", item["target_ref"]["fact_id"],
               {"target_ref": item["target_ref"]}, item)
    for item in plan.get("applicable_rules", []):
        append("governance_rule_results", "rule", item["rule_id"], {"rule_id": item["rule_id"]}, item)
    for method in assessment.get("method_applications", []):
        if method["decision"] != "applied":
            continue
        index = len(template["method_application_results"])
        path = ["method_application_results", index]
        value = row("method", method["method_id"], path, {"method_id": method["method_id"]}, method)
        value["use_results"] = []
        for use in method.get("planned_uses", []):
            value["use_results"].append(row("use", method["method_id"] + "/" + use["use_id"],
                [*path, "use_results", len(value["use_results"])], {"use_id": use["use_id"]}, use))
        template["method_application_results"].append(value)
    for entry in current_semantic_reviews(current):
        review = entry["review"]
        for finding in review["findings"]:
            if finding["status"] != "resolved":
                append("semantic_finding_results", "finding", review["review_id"] + "/" + finding["finding_id"],
                       {"review_id": review["review_id"], "finding_id": finding["finding_id"]}, finding)
    for target in plan.get("verification_targets", []):
        if target["method"] not in {"command", "examples"} or target.get("example"):
            append("verification_review_results", "verification", target["target_ref"],
                   {"target_ref": target["target_ref"]}, target)
    seen_artifacts = set()
    for operation in plan.get("operations", []):
        artifact = operation.get("long_lived_artifact")
        if not artifact:
            continue
        fixed = {key: artifact[key] for key in ("artifact_id", "artifact_type")}
        fixed["path"] = operation.get("to_path") if operation["action"] == "move" else operation["path"]
        if operation.get("repository_id") is not None:
            fixed["repository_id"] = operation["repository_id"]
        identity = (fixed.get("repository_id"), fixed["artifact_id"], fixed["path"])
        if identity in seen_artifacts:
            continue
        seen_artifacts.add(identity)
        append("long_lived_refs", "artifact", str(len(seen_artifacts)), fixed, operation)
    for index, ref in enumerate(declared_refs(data.get("direction") or {})):
        append("follow_up_results", "follow_up", str(index), {"follow_up_ref": ref}, ref)
    return template, rows


def _schema_defaults(schema: Mapping, documents: Mapping) -> dict:
    """Only protocol constants, never const decision branches or empty answers."""
    if "$ref" in schema:
        ref, _, fragment = schema["$ref"].partition("#")
        if not fragment and ref in documents:
            return _schema_defaults(documents[ref], documents)
    defaults = {}
    for name, prop in schema.get("properties", {}).items():
        if name in {"schema_version", "semantic_content_machine_proven"} and "const" in prop:
            defaults[name] = deepcopy(prop["const"])
    return defaults


def prepare(current: Mapping, contract: Mapping, *, project: str,
            result: tuple[dict, list[dict]] | None = None) -> dict:
    action = current["current_action"]
    template = _schema_defaults(contract["payload_schema"], contract["referenced_schemas"])
    rows = []
    challenge = action.get("confirmation_challenge")
    if challenge:
        template["candidate_fingerprint"] = challenge["candidate_fingerprint"]
    if action["action_type"] == "confirm_project_authority_candidates":
        template["decisions"] = []
        for kind, challenge in zip(action["authority_kinds"], action["confirmation_challenges"], strict=True):
            fixed = {"authority_kind": kind, "candidate_fingerprint": challenge["candidate_fingerprint"]}
            rows.append({"id": "authority:" + kind, "path": ["decisions", len(rows)], "fixed": fixed, "source": challenge})
            template["decisions"].append(deepcopy(fixed))
    if action["action_type"] == "assess_verification_change":
        for key in ("command_id", "receipt_id"):
            if key in action:
                template[key] = action[key]
        template["mode"] = "assess"
    if action["action_type"] == "complete_implementation_slice":
        refs = [ref.partition(":")[2] for ref in action.get("record_refs", []) if ref.startswith("engineering.plan.implementation_slice:")]
        if len(refs) != 1:
            raise PreparedInputError("preparation_slice_ambiguous", "Current action must identify exactly one slice")
        template["slice_id"] = refs[0]
    if result is not None:
        template, rows = result
    context = {
        "schema_version": "strixnova.prepared-input.v1",
        "binding": {"project": project, "work_item_id": current["work_item_id"],
                    "work_item_version": current["version"], "source_sha256": digest(current["data"]),
                    "action": deepcopy(action)},
        "contract": deepcopy(contract), "template": template, "checklist": rows,
    }
    if action["action_type"] in {"submit_direction", "revise_direction", "submit_engineering_assessment", "revise_engineering_plan"}:
        data = current["data"]
        context["revision_bases"] = {}
        if action["action_type"] in {"submit_direction", "revise_direction", "revise_engineering_plan"} and data.get("direction"):
            context["revision_bases"]["direction"] = deepcopy(data["direction"])
        assessment = (data.get("engineering") or {}).get("assessment")
        confirmation = data.get("direction_confirmation") or {}
        if action["action_type"] not in {"submit_direction", "revise_direction"} and assessment and confirmation.get("accepted") is True:
            context["revision_bases"]["assessment"] = deepcopy(assessment)
            context["revision_direction_ref"] = {"work_item_id": current["work_item_id"], "direction_version": confirmation["direction_version"]}
    for row in rows:
        node = _schema_node(contract["payload_schema"], contract["referenced_schemas"], row["path"])
        row["input_schema"] = node
        target = template
        for part in row["path"]:
            target = target[part]
        row["pending_fields"] = [key for key in _required_schema_fields(node) if key not in target]
    context["pending_fields"] = [key for key in _required_schema_fields(_schema_node(contract["payload_schema"], contract["referenced_schemas"], [])) if key not in template]
    context["context_sha256"] = digest(context)
    return context


def check_context(context: Mapping, current_preparation: Mapping) -> None:
    if not isinstance(context, Mapping) or context != current_preparation:
        raise PreparedInputError("prepared_input_stale", "Prepared input changed or no longer matches the reviewed action; prepare and review again")


def evidence_catalog(context: Mapping, fields: Mapping | None = None) -> list[dict]:
    """Typed eligible references. Eligibility never means evidential sufficiency."""
    binding, template = context["binding"], context["template"]
    owner = {key: binding[key] for key in ("work_item_id", "work_item_version")}
    catalog = []
    def add(kind, key, ref, source):
        catalog.append({"kind": kind, "key": key, "ref": ref, "owner": owner, "source": deepcopy(source)})
    for receipt in template.get("verification_receipt_ids", []):
        add("receipt", receipt, receipt, {"receipt_id": receipt})
    for artifact in template.get("long_lived_refs", []):
        add("artifact", artifact["artifact_id"], "artifact:" + artifact["artifact_id"], artifact)
    for field in ("delivered_outcomes", "deviations", "limitations"):
        values = (fields or {}).get(field, [])
        for index, item in enumerate(values if isinstance(values, list) else []):
            add(field, index, f"{field}[{index}]", item)
    return catalog


def assemble(context: Mapping, submission: Mapping, *, user_message: str | None = None) -> dict:
    if not isinstance(submission, Mapping) or set(submission) - {"fields", "answers", "groups", "revision"}:
        raise PreparedInputError("prepared_input_invalid", "Use fields, answers and optional explicitly scoped groups")
    result = deepcopy(context["template"])
    if "revision" in submission:
        revised = revise_prepared(context, submission["revision"])
        for key, value in revised.items():
            if key in result and result[key] != value:
                raise PreparedInputError("prepared_binding_override", "Revision conflicts with the prepared binding")
            result[key] = value
    fields, answers = submission.get("fields", {}), submission.get("answers", {})
    if not isinstance(fields, Mapping) or not isinstance(answers, Mapping):
        raise PreparedInputError("prepared_input_invalid", "fields and answers must be objects")
    if set(fields) & set(result):
        raise PreparedInputError("prepared_binding_override", "Prepared fields cannot be replaced", details=sorted(set(fields) & set(result)))
    result.update(deepcopy(fields))
    answers = deepcopy(dict(answers))
    rows = {item["id"]: item for item in context["checklist"]}
    groups = submission.get("groups", [])
    if not isinstance(groups, list):
        raise PreparedInputError("prepared_input_invalid", "groups must be an array")
    for group in groups:
        if not isinstance(group, Mapping) or set(group) != {"items", "values"} or not isinstance(group["items"], list) or not group["items"]:
            raise PreparedInputError("prepared_input_invalid", "A group needs explicit nonempty items and values")
        for key in group["items"]:
            if not isinstance(key, str) or key not in rows or key in answers:
                raise PreparedInputError("prepared_answer_ambiguous", "Unknown or repeated answer", details=key)
            answers[key] = deepcopy(group["values"])
    if set(answers) - set(rows):
        raise PreparedInputError("prepared_answer_unknown", "Unknown answer identities", details=sorted(set(answers) - set(rows)))
    for key, answer in answers.items():
        if not isinstance(answer, Mapping):
            raise PreparedInputError("prepared_input_invalid", f"Answer {key} must be an object")
        target = result
        for part in rows[key]["path"]:
            target = target[part]
        if set(answer) & set(target):
            raise PreparedInputError("prepared_binding_override", "Answer cannot replace fixed identity or nested checklist", details=key)
        target.update(deepcopy(answer))
    _fill_protocol_fields(context, result)
    catalog = evidence_catalog(context, result)
    by_key = {(item["kind"], str(item["key"])): item["ref"] for item in catalog}
    issues = []
    def resolve(value, path):
        if isinstance(value, dict):
            for key, children in value.items():
                if key not in {"evidence_refs", "limitation_refs"}:
                    resolve(children, [*path, key])
                    continue
                if not isinstance(children, list):
                    continue  # The canonical schema reports the type error.
                for index, ref in enumerate(children):
                    if isinstance(ref, Mapping) and set(ref) == {"kind", "key"}:
                        wire = by_key.get((str(ref["kind"]), str(ref["key"])))
                        if wire is not None:
                            children[index] = wire
                            continue
                    elif isinstance(ref, str) and ref in by_key.values():
                        continue
                    # Only result-stage refs use this catalog; planned sources
                    # remain governed by their existing contract and validators.
                    if context["template"].get("schema_version") == "strixnova.actual-result.v1":
                        issues.append({"path": [*path, key, index], "code": "unknown_result_evidence", "value": ref})
        elif isinstance(value, list):
            for index, child in enumerate(value):
                resolve(child, [*path, index])
    resolve(result, [])
    if issues:
        raise PreparedInputError("prepared_references_invalid", "Evidence is unavailable in this result context", details=issues, payload=result)
    if user_message is not None:
        action = context["binding"]["action"]["action_type"]
        if not (action.startswith("confirm_") or action == "confirm_project_authority_candidates"):
            raise PreparedInputError("confirmation_not_expected", "Raw message attachment is only for explicit confirmation")
        result = attach_confirmation_message(result, user_message)
    return result


def schema_issues(context: Mapping, payload: Mapping) -> list[dict]:
    contract = context["contract"]
    resources = []
    for name, document in contract["referenced_schemas"].items():
        resource = Resource.from_contents(document, default_specification=DRAFT202012)
        resources.append((name, resource))
        if "$id" in document:
            resources.append((document["$id"], resource))
    validator = Draft202012Validator(contract["payload_schema"], registry=Registry().with_resources(resources))
    errors = []
    for error in validator.iter_errors(payload):
        errors.append({"path": list(error.absolute_path), "code": "schema_" + str(error.validator), "message": error.message})
    return errors


def inspect_material(document: Any, pointer: str, max_output_bytes: int = 16384) -> dict:
    """Bound readable output, exposing child pointers instead of silent truncation."""
    if not isinstance(pointer, str) or (pointer and not pointer.startswith("/")):
        raise PreparedInputError("material_pointer_invalid", "Use a JSON pointer")
    if type(max_output_bytes) is not int or not 512 <= max_output_bytes <= 1048576:
        raise PreparedInputError("material_budget_invalid", "Use a 512..1048576 byte budget")
    value = document
    try:
        for part in pointer.split("/")[1:]:
            key = part.replace("~1", "/").replace("~0", "~")
            value = value[int(key)] if isinstance(value, list) else value[key]
    except (KeyError, IndexError, TypeError, ValueError) as error:
        raise PreparedInputError("material_pointer_invalid", "The selected material does not exist") from error
    result = {"pointer": pointer, "value": value, "complete": True, "unexpanded": []}
    def size(item):
        # Bound the larger ASCII transport, even when UTF-8 presentation is used.
        return len(json.dumps(item, ensure_ascii=True, indent=2).encode("utf-8"))
    if size(result) <= max_output_bytes:
        return result
    if not isinstance(value, (dict, list)):
        raise PreparedInputError("material_value_too_large", "Selected scalar exceeds the explicit budget; increase the budget or read the saved file")
    result["value"], result["complete"] = {}, False
    children = value.items() if isinstance(value, dict) else enumerate(value)
    for key, child in children:
        path = pointer + "/" + str(key).replace("~", "~0").replace("/", "~1")
        result["value"][str(key)] = child
        if size(result) > max_output_bytes:
            del result["value"][str(key)]
            result["unexpanded"].append(path)
            if size(result) > max_output_bytes:
                # A huge index also needs explicit narrowing; never return an
                # incomplete list of omitted records as if it were complete.
                raise PreparedInputError("material_index_too_large", "Select a narrower pointer in the saved material")
    return result
def revise_prepared(context: Mapping, revision: Mapping) -> dict:
    """Apply explicit edits to an exact base. Keeping the rest is an Agent claim."""
    if not isinstance(revision, Mapping) or set(revision) != {"kind", "keep_rest", "changes"} or revision["keep_rest"] is not True:
        raise PreparedInputError("revision_keep_required", "Explicit kind, keep_rest=true and changes are required")
    kind = revision["kind"]
    bases = context.get("revision_bases", {})
    if not isinstance(kind, str) or kind not in bases:
        raise PreparedInputError("revision_base_missing", "No exact stored base for this action")
    result = deepcopy(bases[kind])
    changes = revision["changes"]
    if not isinstance(changes, list):
        raise PreparedInputError("revision_invalid", "changes must be an array")
    for change in changes:
        if not isinstance(change, Mapping) or change.get("op") not in {"add", "replace", "remove"}:
            raise PreparedInputError("revision_invalid", "Use explicit add, replace or remove operations")
        expected = {"op", "path"} | ({"value"} if change["op"] != "remove" else set())
        path = change.get("path")
        if set(change) != expected or not isinstance(path, str) or not path.startswith("/"):
            raise PreparedInputError("revision_invalid", "Each change needs an exact JSON pointer")
        parts = [p.replace("~1", "/").replace("~0", "~") for p in path.split("/")[1:]]
        if parts[0] in {"schema_version", "assessment_id", "assessment_revision", "direction_ref"}:
            raise PreparedInputError("prepared_binding_override", "Revision identity is supplied from its frozen base")
        try:
            parent = result
            for part in parts[:-1]:
                parent = parent[int(part)] if isinstance(parent, list) else parent[part]
            key = parts[-1]
            if isinstance(parent, list):
                if change["op"] == "add" and key == "-":
                    parent.append(deepcopy(change["value"]))
                    continue
                index = int(key)
                if index < 0 or index >= len(parent):
                    raise IndexError(index)
                if change["op"] == "remove":
                    del parent[index]
                elif change["op"] == "add":
                    parent.insert(index, deepcopy(change["value"]))
                else:
                    parent[index] = deepcopy(change["value"])
            elif isinstance(parent, dict):
                if (change["op"] == "add") == (key in parent):
                    raise KeyError(key)
                if change["op"] == "remove":
                    del parent[key]
                else:
                    parent[key] = deepcopy(change["value"])
            else:
                raise TypeError("Scalar parent")
        except (KeyError, IndexError, ValueError, TypeError) as error:
            raise PreparedInputError("revision_path_invalid", f"Cannot {change['op']} {path}") from error
    if kind == "assessment":
        result["assessment_revision"] = bases[kind]["assessment_revision"] + 1
        result["direction_ref"] = deepcopy(context["revision_direction_ref"])
        return result
    return {"direction": result}


def _schema_node(schema: Mapping, documents: Mapping, path: list) -> dict:
    """Resolve only structural schema paths, without picking decision branches."""
    document = schema
    node = schema
    for part in [*path, None]:
        visited = set()
        while isinstance(node, Mapping) and "$ref" in node:
            reference = node["$ref"]
            if reference in visited:
                return {}
            visited.add(reference)
            filename, _, fragment = reference.partition("#")
            if filename:
                document = documents.get(filename, {})
            node = document
            for segment in fragment.split("/")[1:]:
                node = node.get(segment.replace("~1", "/").replace("~0", "~"), {})
        if not isinstance(node, Mapping):
            return {}
        if part is None:
            return deepcopy(dict(node))
        if isinstance(part, int):
            prefix = node.get("prefixItems", [])
            node = prefix[part] if part < len(prefix) else node.get("items", {})
        else:
            node = node.get("properties", {}).get(part, {})
    return {}



def _required_schema_fields(node: Mapping) -> list[str]:
    required = set(node.get("required", []))
    branches = node.get("oneOf") or node.get("anyOf")
    if branches:
        required.update(set.intersection(*(set(_required_schema_fields(branch)) for branch in branches)))
    return sorted(required)


def _fill_protocol_fields(context: Mapping, value: Any, path: list | None = None) -> None:
    """Fill known protocol constants inside supplied objects, never decisions."""
    path = path or []
    contract = context["contract"]
    if isinstance(value, dict):
        node = _schema_node(contract["payload_schema"], contract["referenced_schemas"], path)
        for key, fixed in _schema_defaults(node, contract["referenced_schemas"]).items():
            value.setdefault(key, fixed)
        for key, child in value.items():
            _fill_protocol_fields(context, child, [*path, key])
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _fill_protocol_fields(context, child, [*path, index])
