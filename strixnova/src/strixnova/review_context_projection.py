"""Read-only review inputs assembled from existing authorities and exact code scopes."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from copy import deepcopy
from importlib.resources import files
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError
from strixnova.project_authority_consistency import ProjectAuthorityConsistency, ProjectAuthorityConsistencyError
from strixnova.project_content_snapshot import capture_repository_content, content_fingerprint
from strixnova.project_context import ProjectContext, ProjectContextError, ProjectContextResolver
from strixnova.project_engineering_baseline import ProjectEngineeringBaseline, ProjectEngineeringBaselineError
from strixnova.project_implementation_alignment import ProjectImplementationAlignment
from strixnova.schema_error_reporting import schema_error_message
from strixnova.workflow_authority import WorkflowAuthority, WorkflowAuthorityError


class ReviewContextError(ValueError):
    """The requested review scope cannot be interpreted without guessing."""

    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def review_context_contract() -> dict[str, Any]:
    return json.loads(files("strixnova.resources").joinpath("review-context-v1.schema.json").read_text(encoding="utf-8"))


def _validate(value: Mapping[str, Any]) -> dict[str, Any]:
    errors = sorted(Draft202012Validator(review_context_contract()).iter_errors(value), key=lambda error: str(list(error.absolute_path)))
    if errors:
        raise ReviewContextError("review_context_input_invalid", "审阅上下文输入不符合合同", details=[{
            "path": ".".join(str(part) for part in error.absolute_path),
            "reason": schema_error_message(error),
        } for error in errors])
    request = deepcopy(dict(value))
    ids = [item["repository_id"] for item in request["repositories"]]
    if len(ids) != len(set(ids)):
        raise ReviewContextError("review_repository_duplicate", "同一仓库只能选择一个待审版本")
    return request


def _gap(code: str, message: str, **location: Any) -> dict[str, Any]:
    return {"code": code, "message": message, **location}


class ReviewContextProjection:
    """A per-query composition with no WorkItem, filesystem, or lifecycle writes."""

    def __init__(self, project_dir: str | Path) -> None:
        self.project = Path(project_dir).expanduser().resolve()

    def read(self, value: Mapping[str, Any]) -> dict[str, Any]:
        request = _validate(value)
        try:
            return self._read(request)
        except ReviewContextError:
            raise
        except (ProjectContextError, GitProjectReaderError) as error:
            raise ReviewContextError(error.code, str(error), details=error.details) from error
        except (ProjectEngineeringBaselineError, ProjectAuthorityConsistencyError) as error:
            raise ReviewContextError("review_basis_invalid", str(error), details=error.issues) from error

    def _read(self, request: dict[str, Any]) -> dict[str, Any]:
        resolver = ProjectContextResolver(self.project)
        live = resolver.configured(bindings=request.get("bindings"), use_execution_bindings=False)
        result: dict[str, Any] = {
            "schema_version": "strixnova.review-context.v1", "mode": request["mode"],
            "project_id": live.project_id if live is not None else None,
            "requested_scope": deepcopy(request["repositories"]),
            "repositories": [], "changes": [], "selected_module_ids": [],
            "selection_reasons": [], "basis": None, "sources": {},
            "product_guardrails": None, "engineering_policy": None,
            "architecture": None, "domain_facts": None,
            "implementation": {"source_ownership": [], "actual_dependencies": [], "target_responsibilities": [], "deviations": []},
            "files": [], "work_item_context": None, "gaps": [],
            "status": "partial", "writes_performed": False,
            "semantic_content_machine_proven": False, "review_performed": False,
        }
        gaps = result["gaps"]
        if live is None:
            gaps.append(_gap("project_configuration_missing", "项目尚无可用定位声明；未猜测仓库身份或采用规则"))
            return self._finish(result, request)

        readers, changes, scopes = self._target_readers(live, request, gaps)
        result["repositories"] = scopes
        result["changes"] = changes
        seeds: dict[tuple[str, str], set[str]] = {}
        for change in changes:
            for key in ("old_path", "path"):
                if change.get(key):
                    seeds.setdefault((change["repository_id"], change[key]), set()).add("changed_" + key)

        basis_ref = request.get("basis_ref") or (live.configuration or {}).get("default_integration_ref")
        checker = None
        basis: dict[str, Any] = {"authorities": {}, "sources": {}, "gaps": [], "baseline": None}
        if basis_ref is None:
            gaps.append(_gap("review_basis_ref_missing", "未指定规则依据版本，项目也没有默认集成引用；仍提供明确的待审代码范围"))
        else:
            context = resolver.configured(bindings=request.get("bindings"), observed_ref=basis_ref, use_execution_bindings=False)
            if context is None:
                gaps.append(_gap("review_basis_configuration_missing", "所选依据提交尚无当前项目定位声明"))
            else:
                if context.project_id != live.project_id:
                    raise ReviewContextError("review_project_identity_conflict", "规则依据与待审范围不是同一个项目")
                baseline_repository_id = context.configuration["engineering_baseline"]["repository_id"]
                baseline_repository = next(item for item in context.repositories if item.repository_id == baseline_repository_id)
                if baseline_repository.availability in {"missing", "not_bound"}:
                    gaps.append(_gap("baseline_repository_unavailable", "基线所在仓库当前不可读取；仍返回明确的待审代码", repository_id=baseline_repository_id, reason=baseline_repository.issue_code))
                else:
                    checker = ProjectAuthorityConsistency(self.project, shared_context=context)
                    basis = checker.review_basis()
                    result["basis"] = {
                        "configuration_commit": context.configuration_reader.observed_commit,
                        "baseline_id": (basis["baseline"] or {}).get("baseline_id"),
                        "baseline_path": checker.baseline_reader.locate().relative_to(checker.baseline_reader.project).as_posix(),
                        "baseline_commit": checker.observed_commit,
                    }
                    result["sources"] = basis["sources"]
                    gaps.extend(basis["gaps"])

        authorities = basis["authorities"]
        product = authorities.get("product_definition")
        if product is not None:
            result["product_guardrails"] = {key: deepcopy(product[key]) for key in (
                "product_id", "revision", "purpose", "capabilities", "non_goals", "constraints",
            )}
        if checker is not None:
            result["engineering_policy"] = checker.review_policy_materials()
        for kind, source in basis["sources"].items():
            if source["status"] != {"revision_status": "confirmed", "adoption_status": "current"}:
                gaps.append(_gap("authority_not_current", "材料尚未确认采用为当前约定，不能用作已确认规则", authority_kind=kind))

        alignment = authorities.get("implementation_alignment", {})
        alignment_repository = basis["sources"].get("implementation_alignment", {}).get("repository_id")
        ownership = alignment.get("source_ownership", [])
        owners = {(item.get("repository_id") or alignment_repository, item["path"]): item for item in ownership}
        if request["mode"] == "modules" and alignment:
            for identifier, reader in readers.items():
                if alignment.get("schema_version") != "strixnova.project-implementation-alignment.v1" and identifier != alignment_repository:
                    continue
                for path in reader.tracked_paths():
                    if (identifier, path) not in owners and ProjectImplementationAlignment.is_behavior_path(alignment, path, repository_id=identifier):
                        seeds.setdefault((identifier, path), set()).add("unassigned_governed_source")
        selected = set(request.get("module_ids", []))
        reasons = result["selection_reasons"]
        reasons.extend({"module_id": identifier, "reason": "explicit_module"} for identifier in sorted(selected))
        for (repository_id, path), path_reasons in sorted(seeds.items()):
            record = owners.get((repository_id, path))
            if record is not None and record.get("target_module_id"):
                module_id = record["target_module_id"]
                selected.add(module_id)
                reasons.append({"module_id": module_id, "reason": "recorded_source_ownership", "repository_id": repository_id, "path": path})
            else:
                authority_kinds = [kind for kind, source in basis["sources"].items() if source["repository_id"] == repository_id and any(item["path"] == path for item in source["files"])]
                if authority_kinds:
                    reasons.append({"reason": "changed_authority_material", "repository_id": repository_id, "path": path, "authority_kinds": authority_kinds})
                    gaps.append(_gap("authority_change_requires_review", "本次修改了规则材料；当前依据仍是原精确版本，新内容须独立审阅", repository_id=repository_id, path=path))
                    if "domain_model" in authority_kinds:
                        source_file = next(item for item in basis["sources"]["domain_model"]["files"] if item["path"] == path)
                        architecture = authorities.get("target_architecture", {})
                        fact_ids = set(source_file.get("fact_ids", []))
                        if "fact_ids" not in source_file:
                            selected.update(item["module_id"] for item in architecture.get("modules", []))
                        else:
                            for disposition in architecture.get("domain_fact_dispositions", []):
                                if disposition["domain_fact_id"] in fact_ids:
                                    if disposition.get("primary_module_id"):
                                        selected.add(disposition["primary_module_id"])
                                    selected.update(disposition["collaborator_module_ids"])
                else:
                    gaps.append(_gap("source_ownership_unknown", "变化文件没有可用的模块归属；由 Agent 调查，不据文件名猜测", repository_id=repository_id, path=path))

        architecture = authorities.get("target_architecture")
        if architecture is not None:
            known = {item["module_id"] for item in architecture["modules"]}
            for identifier in sorted(selected - known):
                gaps.append(_gap("module_unknown", "所选依据中不存在该目标模块", module_id=identifier))
            selected &= known
            # A changed architectural artifact can alter any relationship, so
            # read its complete target rather than selecting by path spelling.
            if any("target_architecture" in item.get("authority_kinds", []) for item in reasons):
                selected.update(known)
            if checker is not None:
                materials = checker.select_review_materials(sorted(selected))
                result["architecture"] = materials["architecture"]
                result["domain_facts"] = materials["domain_facts"]
                gaps.extend(materials["gaps"])
        elif request.get("module_ids"):
            gaps.append(_gap("architecture_unavailable", "无法把指定模块展开为可靠架构资料"))
        result["selected_module_ids"] = sorted(selected)

        selected_owners = [item for item in ownership if item.get("target_module_id") in selected or (item.get("repository_id") or alignment_repository, item["path"]) in seeds]
        for item in selected_owners:
            key = (item.get("repository_id") or alignment_repository, item["path"])
            if key[0] is not None:
                seeds.setdefault(key, set()).add("recorded_module_source")
        dependencies = [item for item in alignment.get("actual_dependencies", []) if item.get("source_module_id") in selected or item.get("target_module_id") in selected]
        for item in dependencies:
            identifier = item.get("repository_id") or alignment_repository
            for field in ("source_path", "target_path"):
                if identifier is not None and item.get(field):
                    seeds.setdefault((identifier, item[field]), set()).add("recorded_dependency_" + field)
            if item.get("resolution_status") in {"unresolved", "ambiguous"}:
                gaps.append(_gap("dependency_unresolved", "已有依赖观察存在未解析或歧义，不能证明调用关系完整", repository_id=identifier, relation_id=item.get("relation_id")))
        responsibility_ids = set(selected)
        if result["architecture"] is not None:
            responsibility_ids.update(item["relationship_id"] for item in result["architecture"]["relationships"])
            responsibility_ids.update(item["constraint_id"] for item in result["architecture"]["constraints"])
        responsibilities = [item for item in alignment.get("target_responsibilities", []) if item.get("target_id") in responsibility_ids or item.get("responsibility_id") in responsibility_ids]
        deviation_ids = {identifier for record in [*selected_owners, *dependencies, *responsibilities] for identifier in record.get("deviation_ids", [])}
        result["implementation"] = {
            "source_ownership": deepcopy(selected_owners),
            "actual_dependencies": deepcopy(dependencies),
            "target_responsibilities": deepcopy(responsibilities),
            "deviations": [deepcopy(item) for item in alignment.get("deviations", []) if item.get("deviation_id") in deviation_ids],
            "observation_scope": "recorded_basis_only", "current_dependency_analysis_performed": False,
        }
        self._work_item(live, request, result)
        self._files(readers, seeds, owners, request, result)
        # Re-read worktree inputs after assembly. A batch must not silently mix
        # versions when a user edits a file while context is being collected.
        for snapshot in result.get("content_snapshots", []):
            reader = readers[snapshot["repository_id"]]
            if reader.observed_commit is None:
                current = capture_repository_content(snapshot["repository_id"], reader, [item["path"] for item in snapshot["paths"]])
                if current != snapshot:
                    raise ReviewContextError("review_content_changed", "待审工作树在读取期间变化，请重新取得材料")
        if request["mode"] == "changes":
            for scope in scopes:
                identifier = scope["repository_id"]
                reader = readers[identifier]
                if reader.observed_commit is None:
                    repeated = reader.changes_from(scope["base_commit"])["entries"]
                    original = [{key: item[key] for key in ("status", "old_path", "path")} for item in changes if item["repository_id"] == identifier]
                    if repeated != original:
                        raise ReviewContextError("review_change_scope_changed", "工作树变化清单在读取期间变化，请重新取得材料")
        return self._finish(result, request)

    @staticmethod
    def _target_readers(context: ProjectContext, request: dict[str, Any], gaps: list[dict[str, Any]]) -> tuple[dict[str, GitProjectReader], list[dict[str, Any]], list[dict[str, Any]]]:
        readers = {}
        changes = []
        scopes = []
        for selected in request["repositories"]:
            identifier = selected["repository_id"]
            repository = next((item for item in context.repositories if item.repository_id == identifier), None)
            if repository is not None and repository.availability in {"missing", "not_bound"}:
                gaps.append(_gap(repository.issue_code or "repository_unavailable", "指定待审仓库当前不可读取", repository_id=identifier))
                continue
            repository = context.repository(identifier)
            reader = GitProjectReader.for_repository(repository.scope, observed_ref=selected["ref"])
            readers[identifier] = reader
            scope = {"repository_id": identifier, "observed_commit": reader.observed_commit, "scope": "git_commit" if reader.observed_commit is not None else "working_tree"}
            if request["mode"] == "changes":
                delta = reader.changes_from(selected["base_ref"])
                scope["base_commit"] = delta["base_commit"]
                changes.extend({**item, "repository_id": identifier, "base_commit": delta["base_commit"], "target_commit": delta["target_commit"]} for item in delta["entries"])
            scopes.append(scope)
        return readers, changes, scopes

    @staticmethod
    def _work_item(context: ProjectContext, request: dict[str, Any], result: dict[str, Any]) -> None:
        identifier = request.get("work_item_id")
        if identifier is None:
            return
        try:
            item = WorkflowAuthority(context.management_root, project_id=context.project_id).get(identifier)
        except WorkflowAuthorityError as error:
            result["gaps"].append(_gap(error.code, str(error), work_item_id=identifier))
            return
        data = item.get("data") or {}
        result["work_item_context"] = {
            "work_item_id": item["work_item_id"], "version": item["version"], "status": item["status"],
            "direction": deepcopy(data.get("direction")),
            "engineering": deepcopy(data.get("engineering")),
            "actual_result": deepcopy(data.get("actual_result")),
            "verifications": deepcopy(data.get("verifications", [])),
            "source": "stored_work_item_version", "current_verification_performed": False,
        }

    @staticmethod
    def _files(readers: dict[str, GitProjectReader], seeds: dict[tuple[str, str], set[str]], owners: dict, request: dict[str, Any], result: dict[str, Any]) -> None:
        gaps = result["gaps"]
        maximum = request.get("max_files", 100)
        # Changed files come before related context. Omitted paths remain explicit.
        ordered = sorted(seeds, key=lambda key: (not any(value.startswith("changed_") for value in seeds[key]), key))
        result["omitted_files"] = [{"repository_id": key[0], "path": key[1]} for key in ordered[maximum:]]
        if result["omitted_files"]:
            gaps.append(_gap("file_budget_exceeded", "文件预算不足；未展开文件列于 omitted_files", count=len(result["omitted_files"])))
        selected = ordered[:maximum]
        snapshots = []
        for identifier, reader in sorted(readers.items()):
            paths = []
            for repo, path in selected:
                if repo != identifier:
                    continue
                if reader.path_scope_exists(path) and not reader.exists(path):
                    gaps.append(_gap("context_path_is_directory", "依赖端点是目录，需继续定位具体代码", repository_id=repo, path=path))
                    continue
                paths.append(path)
            if paths:
                snapshots.append(capture_repository_content(identifier, reader, paths))
        result["content_snapshots"] = snapshots
        identities = {(snapshot["repository_id"], item["path"]): item for snapshot in snapshots for item in snapshot["paths"]}
        remaining = request.get("max_content_bytes", 65536)
        for key in selected:
            identifier, path = key
            reader = readers.get(identifier)
            if reader is None:
                gaps.append(_gap("repository_not_selected", "关联代码仓库未指定可用待审版本，不隐式读取最新分支", repository_id=identifier, path=path))
                continue
            identity = identities.get(key)
            if identity is None:
                continue
            record: dict[str, Any] = {**identity, "repository_id": identifier, "ref": reader.observed_commit, "scope": "git_commit" if reader.observed_commit is not None else "working_tree", "reasons": sorted(seeds[key])}
            owner = owners.get(key)
            if owner is not None:
                record["recorded_module_id"] = owner.get("target_module_id")
                record["recorded_sha256"] = owner.get("sha256")
                record["recorded_observation_current"] = identity["state"] == "file" and identity["sha256"] == owner.get("sha256")
                if not record["recorded_observation_current"]:
                    gaps.append(_gap("recorded_observation_stale", "文件与已登记观察不同；归属及依赖只作历史调查线索", repository_id=identifier, path=path))
            if identity["state"] == "file" and remaining:
                content = reader.content_window(path, limit=min(remaining, 16384), expected_sha256=identity["sha256"])
                raw = base64.b64decode(content["content_base64"])
                remaining -= len(raw)
                record.update({"content_base64": content["content_base64"], "returned_bytes": len(raw), "size_bytes": content["size_bytes"], "next_offset": content["next_offset"]})
                try:
                    record["text"] = raw.decode("utf-8")
                except UnicodeDecodeError:
                    record["text"] = None
                if content["next_offset"] is not None:
                    gaps.append(_gap("content_window_partial", "仅提供部分原字节，可按摘要继续读取", repository_id=identifier, path=path, next_offset=content["next_offset"]))
            elif identity["state"] == "file":
                gaps.append(_gap("content_budget_exceeded", "内容预算不足，保留精确引用和摘要供继续读取", repository_id=identifier, path=path))
            result["files"].append(record)

    @staticmethod
    def _finish(result: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        def size() -> int:
            return len(json.dumps(result, ensure_ascii=True, sort_keys=True).encode("utf-8"))

        maximum = request.get("max_output_bytes", 262144)
        if size() > maximum:
            for item in reversed(result["files"]):
                if "content_base64" not in item:
                    continue
                for key in ("content_base64", "text", "returned_bytes", "next_offset"):
                    item.pop(key, None)
                item["content_omitted"] = True
                if size() <= maximum - 512:
                    break
            result["gaps"].append(_gap("output_budget_exceeded", "返回预算不足，部分内联内容已省略，精确引用仍保留"))
        if size() > maximum - 512:
            # Do not silently remove project guardrails or declared constraints.
            raise ReviewContextError("review_output_budget_too_small", "来源、范围和规则无法在返回预算内完整表达，请缩小范围或提高 max_output_bytes", details={"required_bytes": size(), "max_output_bytes": maximum})
        unique = {json.dumps(item, ensure_ascii=True, sort_keys=True): item for item in result["gaps"]}
        result["gaps"] = list(unique.values())
        result["status"] = "partial" if result["gaps"] else "available"
        result["context_sha256"] = content_fingerprint(result)
        return result


def render_review_context(value: Mapping[str, Any]) -> str:
    """Render the same structured facts; never produce review findings."""

    sections = ["# 审阅上下文", "", "本材料只提供依据和线索，不表示已完成审阅或证明代码正确。", ""]
    for title, key in (
        ("范围与版本", "repositories"), ("规则依据", "basis"), ("资料来源", "sources"),
        ("本次变化", "changes"), ("项目护栏", "product_guardrails"), ("工程政策", "engineering_policy"),
        ("选择依据", "selection_reasons"), ("架构约定", "architecture"), ("领域事实", "domain_facts"),
        ("历史实现观察", "implementation"), ("关联事项", "work_item_context"),
        ("未展开文件", "omitted_files"), ("缺口与限制", "gaps"),
    ):
        sections.extend([f"## {title}", "", "```json", json.dumps(value.get(key), ensure_ascii=False, indent=2), "```", ""])
    for item in value.get("files", []):
        sections.extend([f"## {item['repository_id']} / {item['path']}", "", "```json", json.dumps({key: content for key, content in item.items() if key not in {"content_base64", "text"}}, ensure_ascii=False, indent=2), "```", ""])
        if item.get("text") is not None:
            fence = "`" * max(3, max((len(part) for part in item["text"].splitlines() if part and set(part) == {"`"}), default=0) + 1)
            sections.extend([fence, item["text"], fence, ""])
        elif item.get("content_base64"):
            sections.extend(["原字节（Base64）：", item["content_base64"], ""])
    return "\n".join(sections)
