"""Read recorded work without applying current engineering decisions."""

from __future__ import annotations

import base64
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from strixnova.workflow_authority import WORK_ITEM_STATES, WorkflowAuthority, WorkflowAuthorityError
from strixnova.persistent_evidence import EvidenceReferenceError, output_path
from strixnova.git_project_reader import GitProjectReader, GitProjectReaderError


class HistoryQueryError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _cursor(value: dict[str, Any]) -> str:
    raw = _json(value)
    return base64.urlsafe_b64encode(_json({"value": value, "sha256": hashlib.sha256(raw).hexdigest()})).decode("ascii")


def _read_cursor(value: str | None, scope: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        if not isinstance(value, str) or len(value) > 4096:
            raise ValueError
        envelope = json.loads(base64.b64decode(value, altchars=b"-_", validate=True))
        content = envelope["value"]
        if envelope["sha256"] != hashlib.sha256(_json(content)).hexdigest() or content["scope"] != scope:
            raise ValueError
        if type(content["revision"]) is not int or content["revision"] < 0:
            raise ValueError
        return content
    except (ValueError, KeyError, TypeError, UnicodeError) as error:
        raise HistoryQueryError("history_cursor_invalid", "续页引用无效或不属于本次查询") from error


def _date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        result = datetime.fromisoformat(value)
        return result.replace(tzinfo=result.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError) as error:
        raise HistoryQueryError("history_time_invalid", "历史时间必须是 ISO 日期或时间") from error


class WorkItemHistory:
    """One bounded, read-only projection over the existing stored facts."""

    def __init__(self, project_dir: str | Path, *, repository_roots: dict[str, Path] | None = None) -> None:
        self.project = Path(project_dir).expanduser().resolve()
        self.authority = WorkflowAuthority(self.project)
        self._git_readers: dict[str, GitProjectReader] = {}
        self._commit_views: dict[str, dict[str, Any]] = {}
        self._result_bindings: dict[tuple[str, int], dict[str, Any]] = {}
        self.repository_roots = dict(repository_roots or {})

    def query(
        self,
        *,
        work_item_id: str | None = None,
        records: tuple[str, ...] = (),
        query: str = "", statuses: tuple[str, ...] = (),
        since: str | None = None, until: str | None = None,
        limit: int = 25, cursor: str | None = None,
        offset: int = 0, byte_count: int = 65536,
    ) -> dict[str, Any]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise HistoryQueryError("history_limit_invalid", "历史页大小必须为 1 到 100")
        if type(offset) is not int or offset < 0 or type(byte_count) is not int or not 1 <= byte_count <= 1024 * 1024:
            raise HistoryQueryError("history_output_range_invalid", "输出位置必须非负，每次读取 1 到 1048576 字节")
        if not isinstance(query, str) or len(query) > 256 or any(state not in WORK_ITEM_STATES for state in statuses):
            raise HistoryQueryError("history_filter_invalid", "历史查询条件无效")
        start, end = _date(since), _date(until)
        if start and end and start >= end:
            raise HistoryQueryError("history_time_invalid", "历史开始时间必须早于结束时间")
        if work_item_id is None:
            if records:
                raise HistoryQueryError("history_item_required", "读取正文需要明确事项 ID")
            scope = hashlib.sha256(_json([str(self.project), query, sorted(statuses), start, end, limit])).hexdigest()
            continuation = _read_cursor(cursor, scope)
            after = continuation.get("after") if continuation else None
            if after is not None and (not isinstance(after, list) or len(after) != 2 or not all(isinstance(x, str) for x in after)):
                raise HistoryQueryError("history_cursor_invalid", "历史续页位置无效")
            page = self.authority.historical_items(
                limit=limit, query=query, statuses=statuses, since=start, until=end,
                after=tuple(after) if after else None,
                expected_revision=continuation["revision"] if continuation else None,
            )
            return {
                "schema_version": "strixnova.work-item-history.v1", "view": "items",
                "snapshot_revision": page["revision"], "items": page["items"],
                "next_cursor": _cursor({"scope": scope, "revision": page["revision"], "after": page["last_key"]}) if page["more"] else None,
            }
        output_continuation = len(records) == 1 and records[0].startswith(("output:", "artifact:"))
        if query or statuses or since or until or (cursor and records not in {("events",), ("verifications",), ("candidates",), ("artifacts",)} and not output_continuation):
            raise HistoryQueryError("history_filter_invalid", "单事项不接受列表筛选，续页需单独读取 events 或 verifications")
        if len(set(records)) != len(records):
            raise HistoryQueryError("history_record_invalid", "历史记录引用不得重复")
        needed: set[str] = set()
        for record in records:
            if record == "request":
                needed.add("raw_request")
            elif record == "result":
                needed.update(("actual_result", "actual_result_confirmation", "superseded_deliveries", "cancellation"))
            elif record == "decisions":
                needed.update(("raw_request", "direction", "direction_confirmation", "engineering", "project_authority_decisions", "authority_adoption", "cancellation"))
            elif record == "delivery" or record == "artifacts" or record.startswith("artifact:"):
                needed.update(("git", "repository_deliveries", "engineering", "actual_result", "actual_result_confirmation"))
            elif record == "relations":
                needed.add("direction")
        item = self.authority.historical_item(work_item_id, include_data=False, fields=tuple(sorted(needed)) if needed else None)
        data = item["data"]
        selected: dict[str, Any] = {}
        for record in records:
            if record == "request":
                selected[record] = {"title": item["title"], "raw_request": data.get("raw_request")}
            elif record == "result":
                confirmation = data.get("actual_result_confirmation")
                selected[record] = {
                    "actual_result": deepcopy(data.get("actual_result")),
                    "confirmation": deepcopy(confirmation),
                    "acceptance_status": "accepted" if isinstance(confirmation, dict) and confirmation.get("accepted") is True
                    else "not_accepted" if data.get("actual_result") is not None else "not_present",
                    "superseded_deliveries": deepcopy(data.get("superseded_deliveries") or []),
                    "cancellation": deepcopy(data.get("cancellation")),
                }
            elif record == "decisions":
                selected[record] = {key: deepcopy(data.get(key)) for key in (
                    "raw_request", "direction", "direction_confirmation", "engineering",
                    "project_authority_decisions", "authority_adoption", "cancellation",
                )}
            elif record.startswith("verification:"):
                selected[record] = self._receipt(item, record.partition(":")[2])
            elif record == "verifications":
                scope = hashlib.sha256(_json([str(self.project), work_item_id, "verifications", limit])).hexdigest()
                continuation = _read_cursor(cursor, scope)
                if continuation and continuation["revision"] != item["version"]:
                    raise HistoryQueryError("history_snapshot_changed", "事项已变化，请重新查询")
                after = continuation.get("after", "") if continuation else ""
                if not isinstance(after, str):
                    raise HistoryQueryError("history_cursor_invalid", "回执续页位置无效")
                page = self.authority.historical_verifications(work_item_id, expected_version=item["version"], limit=limit, after_receipt=after)
                selected[record] = {
                    "items": [{**receipt, "record_ref": f"verification:{receipt['receipt_id']}"} for receipt in page["items"]],
                    "next_cursor": _cursor({"scope": scope, "revision": item["version"], "after": page["last_receipt"]}) if page["more"] else None,
                }
            elif record.startswith("output:"):
                parts = record.split(":")
                if len(parts) != 3 or parts[2] not in {"stdout", "stderr", "cases"}:
                    raise HistoryQueryError("history_record_invalid", "输出引用格式为 output:<回执ID>:stdout、stderr 或 cases")
                selected[record] = self._output(item, self._receipt(item, parts[1])["receipt"], parts[2], offset, byte_count, cursor)
            elif record == "delivery":
                entries = data.get("repository_deliveries") or [{"repository_id": None, "git": data.get("git") or {}}]
                deliveries = []
                for entry in entries:
                    git = entry.get("git") or {}
                    commits = [*list(git.get("result_commits") or []), *(([git['integration']['integrated_commit']]) if (git.get('integration') or {}).get('integrated_commit') else [])]
                    deliveries.append({"repository_id": entry["repository_id"], "recorded_git": deepcopy(git), "commits": [self._commit_status(commit, repository_id=entry["repository_id"], recorded_root=git.get("repository")) for commit in dict.fromkeys(commits)]})
                selected[record] = {"repositories": deliveries} if data.get("repository_deliveries") else {key: value for key, value in deliveries[0].items() if key != "repository_id"}
            elif record == "artifacts" or record.startswith("artifact:"):
                refs = (data.get("actual_result") or {}).get("long_lived_refs") or []
                if not isinstance(refs, list):
                    raise HistoryQueryError("history_data_invalid", "产物引用不是数组")
                if record != "artifacts":
                    try:
                        index = int(record.partition(":")[2])
                        if index < 0 or index >= len(refs):
                            raise ValueError
                    except ValueError as error:
                        raise HistoryQueryError("history_artifact_missing", "该事项没有指定的历史产物") from error
                    selected[record] = self._artifact(item, refs[index], index=index, include_body=True, offset=offset, byte_count=byte_count, cursor=cursor)
                else:
                    scope = hashlib.sha256(_json([str(self.project), work_item_id, "artifacts", limit])).hexdigest()
                    continuation = _read_cursor(cursor, scope)
                    if continuation and continuation["revision"] != item["version"]:
                        raise HistoryQueryError("history_snapshot_changed", "事项已变化，请重新读取产物")
                    start = continuation.get("after", 0) if continuation else 0
                    if type(start) is not int or start < 0:
                        raise HistoryQueryError("history_cursor_invalid", "产物续页位置无效")
                    selected[record] = {
                        "items": [self._artifact(item, reference, index=index) for index, reference in enumerate(refs[start:start + limit], start=start)],
                        "next_cursor": _cursor({"scope": scope, "revision": item["version"], "after": start + limit}) if start + limit < len(refs) else None,
                    }
            elif record == "relations":
                selected[record] = {"declared": deepcopy((data.get("direction") or {}).get("work_item_relations") or [])}
            elif record == "events":
                scope = hashlib.sha256(_json([str(self.project), work_item_id, "events", limit])).hexdigest()
                continuation = _read_cursor(cursor, scope)
                if continuation and continuation["revision"] != item["version"]:
                    raise HistoryQueryError("history_snapshot_changed", "事项已变化，请重新查询事件")
                after = continuation.get("after", 0) if continuation else 0
                if type(after) is not int or after < 0:
                    raise HistoryQueryError("history_cursor_invalid", "历史事件续页位置无效")
                page = self.authority.historical_events(work_item_id, expected_version=item["version"], after_sequence=after, limit=limit)
                selected[record] = {
                    "items": [{**event, "record_ref": f"event:{event['sequence']}"} for event in page["items"]],
                    "next_cursor": _cursor({"scope": scope, "revision": item["version"], "after": page["last_sequence"]}) if page["more"] else None,
                }
            elif record == "candidates" or record.startswith("candidate:"):
                scope = hashlib.sha256(_json([str(self.project), work_item_id, "candidates", limit])).hexdigest()
                continuation = _read_cursor(cursor, scope)
                if continuation and continuation["revision"] != item["version"]:
                    raise HistoryQueryError("history_snapshot_changed", "事项已变化，请重新读取候选")
                after = continuation.get("after", 0) if continuation else 0
                try:
                    sequence = int(record.partition(":")[2]) if record != "candidates" else None
                    if type(after) is not int or after < 0 or (sequence is not None and sequence < 1):
                        raise ValueError
                except ValueError as error:
                    raise HistoryQueryError("history_record_invalid", "候选引用必须包含有效事件序号") from error
                page = self.authority.historical_candidates(work_item_id, expected_version=item["version"], after_sequence=after, limit=limit, sequence=sequence)
                selected[record] = page["items"][0] if sequence is not None else {
                    "items": page["items"],
                    "next_cursor": _cursor({"scope": scope, "revision": item["version"], "after": page["last_sequence"]}) if page["more"] else None,
                    "interpretation": "只使用写入时保存的规范化候选、决定与失效事实，不用当前确认解析器重新解释历史。",
                }
            elif record.startswith("event:"):
                try:
                    sequence = int(record.partition(":")[2])
                    if sequence < 1:
                        raise ValueError
                except ValueError as error:
                    raise HistoryQueryError("history_record_invalid", "事件引用必须包含正整数序号") from error
                event = self.authority.historical_events(work_item_id, expected_version=item["version"], sequence=sequence)["event"]
                try:
                    payload = json.loads(event["payload_json"])
                except (ValueError, TypeError) as error:
                    raise HistoryQueryError("history_data_invalid", "事件原始正文不是有效 JSON") from error
                selected[record] = {**event, "payload": payload, "payload_sha256": hashlib.sha256(event["payload_json"].encode("utf-8")).hexdigest()}
                if event.get("recorded_facts_json") is not None:
                    try:
                        selected[record]["recorded_facts"] = json.loads(event["recorded_facts_json"])
                    except (ValueError, TypeError):
                        selected[record]["recorded_facts_error"] = "history_data_invalid"
            else:
                raise HistoryQueryError("history_record_invalid", f"未知历史记录：{record}")
        return {
            "schema_version": "strixnova.work-item-history.v1",
            "work_item": {key: item[key] for key in (
                "work_item_id", "title", "status", "version", "created_at", "updated_at",
            )},
            "records": selected,
            "scope": "recorded_facts",
            "available_records": ["request", "result", "decisions", "events", "candidates", "verifications", "delivery", "artifacts", "relations"],
            "semantic_content_machine_proven": False,
        }

    def _receipt(self, item: dict[str, Any], receipt_id: str) -> dict[str, Any]:
        if not receipt_id or len(receipt_id) > 256:
            raise HistoryQueryError("history_record_invalid", "必须指定有效回执 ID")
        historical = self.authority.historical_verification(item["work_item_id"], receipt_id, expected_version=item["version"])
        if historical is None:
            raise HistoryQueryError("history_receipt_missing", "该事项没有指定的验证回执")
        receipt = historical["receipt"]
        references = dict(receipt.get("raw_output_refs") or {})
        if isinstance(receipt.get("case_evidence"), dict):
            references["cases"] = receipt["case_evidence"].get("report_ref")
        return {
            **historical,
            "output_record_refs": [f"output:{receipt_id}:{stream}" for stream in ("stdout", "stderr", "cases") if references.get(stream) is not None],
        }

    def _commit_status(self, commit: Any, *, repository_id: str | None = None, recorded_root: str | None = None) -> dict[str, Any]:
        if not isinstance(commit, str) or re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", commit) is None:
            return {"commit": commit, "availability": "invalid_immutable_reference"}
        root = self.repository_roots.get(repository_id) or Path(recorded_root or self.project)
        key = (repository_id, str(root), commit)
        if key not in self._commit_views:
            try:
                reader = GitProjectReader(root, observed_ref=commit)
                self._git_readers[key] = reader
                self._commit_views[key] = {"repository_id": repository_id, "commit": commit, "availability": "available"}
            except GitProjectReaderError as error:
                self._commit_views[key] = {"repository_id": repository_id, "commit": commit, "availability": "missing_commit" if error.code == "git_ref_not_found" else "repository_unavailable", "error_code": error.code}
        return dict(self._commit_views[key])

    def _artifact(
        self, item: dict[str, Any], reference: Any, *, index: int, include_body: bool = False,
        offset: int = 0, byte_count: int = 65536, cursor: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(reference, dict):
            return {"record_ref": f"artifact:{index}", "availability": "invalid_reference"}
        result = {"record_ref": f"artifact:{index}", "reference": deepcopy(reference)}
        entries = item["data"].get("repository_deliveries") or []
        repository_id = reference.get("repository_id")
        if repository_id is None and entries:
            matches = {operation.get("repository_id") for operation in (item['data'].get('engineering', {}).get('plan') or {}).get('operations', []) if (operation.get('long_lived_artifact') or {}).get('artifact_id') == reference.get('artifact_id') and (operation.get('to_path') or operation.get('path')) == reference.get('path')}
            if len(matches) != 1:
                return {**result, 'availability': 'repository_not_recorded'}
            repository_id = matches.pop()
        selected_entry = next((entry for entry in entries if entry['repository_id'] == repository_id), {})
        git = selected_entry.get('git') or item["data"].get("git") or {}
        result['repository_id'] = repository_id
        integration = git.get("integration") or {}
        commits = git.get("result_commits") or []
        key = (item["work_item_id"], item["version"], repository_id)
        confirmation = item["data"].get("actual_result_confirmation") or {}
        if key not in self._result_bindings:
            self._result_bindings[key] = self.authority.historical_result_binding(
                item["work_item_id"], expected_version=item["version"],
                result=item["data"].get("actual_result") or {}, fingerprint=confirmation.get("candidate_fingerprint"),
                repository_id=repository_id,
            )
        binding = self._result_bindings[key]
        commit = binding["commit"]
        result["result_binding"] = binding
        if commit is None:
            return {**result, "availability": "candidate_not_committed" if item["status"] != "completed" else "commit_not_recorded"}
        commit_view = self._commit_status(commit, repository_id=repository_id, recorded_root=git.get('repository'))
        result["observed_commit"] = commit
        if commit_view["availability"] != "available":
            return {**result, **{key: value for key, value in commit_view.items() if key != "commit"}}
        root = self.repository_roots.get(repository_id) or Path(git.get('repository') or self.project)
        reader = self._git_readers[(repository_id, str(root), commit)]
        try:
            exists = reader.exists(reference.get("path"))
            if reference.get("relation") == "removed":
                return {**result, "availability": "removal_not_reflected_at_commit" if exists else "removed_as_recorded"}
            if not exists:
                return {**result, "availability": "missing_path_at_commit"}
            if not include_body:
                return {**result, "availability": "available"}
            content = reader.read_bytes(reference["path"])
        except GitProjectReaderError as error:
            return {**result, "availability": "unreadable", "error_code": error.code}
        digest = hashlib.sha256(content).hexdigest()
        scope = hashlib.sha256(_json([str(self.project), item["work_item_id"], "artifact", index, repository_id, commit, reference["path"], byte_count])).hexdigest()
        continuation = _read_cursor(cursor, scope)
        if continuation:
            if continuation["revision"] != item["version"] or continuation.get("sha256") != digest:
                raise HistoryQueryError("history_snapshot_changed", "历史产物绑定已变化，请重新读取")
            after = continuation.get("after")
            if type(after) is not int or after < 0 or offset not in {0, after}:
                raise HistoryQueryError("history_cursor_invalid", "历史产物续页位置无效")
            offset = after
        chunk = content[offset:offset + byte_count]
        return {
            **result, "availability": "available", "sha256": digest, "size_bytes": len(content),
            "text": chunk.decode("utf-8", errors="replace"), "data_base64": base64.b64encode(chunk).decode("ascii"),
            "offset": offset, "returned_bytes": len(chunk),
            "next_cursor": _cursor({"scope": scope, "revision": item["version"], "sha256": digest, "after": offset + len(chunk)}) if offset + len(chunk) < len(content) else None,
        }

    def _output(self, item: dict[str, Any], receipt: dict[str, Any], stream: str, offset: int, byte_count: int, cursor: str | None = None) -> dict[str, Any]:
        scope = hashlib.sha256(_json([str(self.project), item["work_item_id"], receipt["receipt_id"], stream, byte_count])).hexdigest()
        continuation = _read_cursor(cursor, scope)
        if continuation:
            if continuation["revision"] != item["version"]:
                raise HistoryQueryError("history_snapshot_changed", "事项已变化，请重新读取日志")
            after = continuation.get("after")
            if type(after) is not int or after < 0 or offset not in {0, after} or not isinstance(continuation.get("sha256"), str):
                raise HistoryQueryError("history_cursor_invalid", "日志续页位置或内容身份无效")
            offset = after
        reference = (receipt.get("case_evidence") or {}).get("report_ref") if stream == "cases" else (receipt.get("raw_output_refs") or {}).get(stream)
        result: dict[str, Any] = {"receipt_id": receipt["receipt_id"], "stream": stream, "original_reference": reference}
        if reference is None:
            return {**result, "availability": "not_recorded"}
        if not isinstance(reference, str):
            raise HistoryQueryError("history_evidence_path_invalid", "证据引用格式无效")
        indexed = self.authority.historical_output(item["work_item_id"], receipt["receipt_id"], stream)
        try:
            target = output_path(self.project, item["work_item_id"], receipt["receipt_id"], stream,
                                 indexed["relative_path"] if indexed and indexed.get("relative_path") else reference)
        except EvidenceReferenceError as error:
            raise HistoryQueryError(error.code, str(error)) from error
        if not target.is_file():
            return {**result, "availability": "missing"}
        try:
            with target.open("rb") as source:
                before = os.fstat(source.fileno())
                digest = hashlib.file_digest(source, "sha256").hexdigest()
                if continuation and continuation["sha256"] != digest:
                    raise HistoryQueryError("history_output_changed", "日志内容在翻页期间发生变化，请重新读取")
                source.seek(offset)
                chunk = source.read(byte_count)
                after = os.fstat(source.fileno())
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                return {**result, "availability": "changed_during_read"}
        except OSError:
            return {**result, "availability": "unreadable"}
        if indexed and indexed.get("sha256") and (indexed["sha256"] != digest or indexed["size_bytes"] != before.st_size):
            return {**result, "availability": "hash_mismatch", "expected_sha256": indexed["sha256"], "observed_sha256": digest}
        integrity = "unanchored"
        if indexed and indexed.get("sha256") and indexed.get("observation_kind") == "execution":
            integrity = "verified_since_execution"
        return {
            **result, "availability": "available", "integrity": integrity,
            "observed_sha256": digest, "size_bytes": before.st_size,
            "offset": offset, "returned_bytes": len(chunk),
            "text": chunk.decode("utf-8", errors="replace"),
            "data_base64": base64.b64encode(chunk).decode("ascii"),
            "next_offset": offset + len(chunk) if offset + len(chunk) < before.st_size else None,
            "next_cursor": _cursor({"scope": scope, "revision": item["version"], "sha256": digest, "after": offset + len(chunk)}) if offset + len(chunk) < before.st_size else None,
        }
