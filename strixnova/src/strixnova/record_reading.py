"""Stateless, exact, bounded views of already-public action records."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
import json
import re
from typing import Any

DEFAULT_OUTPUT_BYTES = 4096
MAX_OUTPUT_BYTES = 1024 * 1024


class RecordReadingError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def serialized(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=True, sort_keys=True).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(serialized(value)).hexdigest()


def split_reference(ref: str, allowed: set[str]) -> tuple[str, list[str]]:
    root, marker, pointer = ref.partition('#')
    if marker:
        if not pointer.startswith('/') or re.search(r'~(?![01])', pointer):
            raise RecordReadingError('record_path_invalid', '子引用必须使用返回的 JSON Pointer')
        return root, [part.replace('~1', '/').replace('~0', '~') for part in pointer[1:].split('/')]
    if ref in allowed:
        return ref, []
    parents = [root for root in allowed if ref.startswith(root + '.')]
    if parents:
        root = max(parents, key=len)
        return root, ref[len(root) + 1:].split('.')
    return ref, []


def select(value: Any, parts: list[str]) -> Any:
    for part in parts:
        if isinstance(value, dict) and part in value:
            value = value[part]
        elif isinstance(value, list) and re.fullmatch(r'0|[1-9][0-9]*', part) and int(part) < len(value):
            value = value[int(part)]
        else:
            raise RecordReadingError('record_path_missing', '请求的子记录不存在；请沿返回的引用读取')
    return value


def child_reference(root: str, parts: list[str]) -> str:
    return root + '#/' + '/'.join(part.replace('~', '~0').replace('/', '~1') for part in parts)


def _type(value: Any) -> str:
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'array'
    if isinstance(value, str):
        return 'string'
    return 'scalar'


def bounded_next(base: dict, selections: dict[str, tuple[str, list[str], Any]], *,
                 max_output_bytes: int, cursor: str | None = None,
                 expected_sha256: str | None = None) -> dict:
    """Bound the final CLI envelope, including ASCII escaping and trailing LF.

    Selections contain a public root and its full source value; no private paths
    or state are read here. A cursor is a continuation, never an authorization.
    """
    if isinstance(max_output_bytes, bool) or not isinstance(max_output_bytes, int) or not 512 <= max_output_bytes <= MAX_OUTPUT_BYTES:
        raise RecordReadingError('record_read_budget_invalid', '返回预算必须为 512 到 1048576 字节')
    if (cursor is not None or expected_sha256 is not None) and len(selections) != 1:
        raise RecordReadingError('record_read_scope_invalid', '续读或内容核对每次必须指定一个记录')
    if expected_sha256 is not None and not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise RecordReadingError('record_read_hash_invalid', 'expected-sha256 必须为返回的源记录 SHA-256')
    decoded = None
    if cursor is not None:
        try:
            if len(cursor) > 4096:
                raise ValueError
            decoded = json.loads(base64.urlsafe_b64decode(cursor + '=' * (-len(cursor) % 4)))
            if set(decoded) != {'binding', 'offset'} or type(decoded['offset']) is not int or decoded['offset'] < 0:
                raise ValueError
        except (ValueError, TypeError, UnicodeError) as error:
            raise RecordReadingError('record_read_cursor_invalid', '续读引用无效') from error
    result = deepcopy(base)
    result['records'] = {}
    result['record_pages'] = {}
    result['record_sources'] = {}
    result['reading'] = {'schema_version': 'strixnova.record-reading.v1',
                         'max_output_bytes': max_output_bytes,
                         'complete': not selections, 'unread_refs': list(selections)}

    def fits() -> bool:
        return len(serialized({'ok': True, 'next': result})) + 2 <= max_output_bytes

    if not fits():
        raise RecordReadingError('record_read_budget_too_small', '动作元数据或请求引用超出预算；减少批量引用或提高预算')
    for ref, (root, parts, source) in selections.items():
        value = select(source, parts)
        source_hash = digest(source)
        if expected_sha256 is not None and source_hash != expected_sha256:
            raise RecordReadingError('record_read_source_changed', '源记录已变化；重新读取目录，不拼接旧内容')
        binding = digest([base['work_item_id'], base['work_item_version'], root, parts, source_hash])
        start = 0
        if decoded is not None:
            if decoded['binding'] != binding:
                raise RecordReadingError('record_read_source_changed', '记录、事项版本或读取范围已变化；重新读取目录')
            start = decoded['offset']

        def continuation(offset: int, total: int) -> str | None:
            if offset >= total:
                return None
            raw = json.dumps({'binding': binding, 'offset': offset}, separators=(',', ':')).encode()
            return base64.urlsafe_b64encode(raw).decode().rstrip('=')

        result['record_sources'][ref] = {'root_ref': root, 'source_sha256': source_hash}
        result['reading']['unread_refs'].remove(ref)
        if cursor is None:
            result['records'][ref] = deepcopy(value)
            result['reading']['complete'] = not result['reading']['unread_refs'] and not result['record_pages']
            if fits():
                continue
            del result['records'][ref]
        result['reading']['complete'] = False
        kind = _type(value)
        total = len(value) if isinstance(value, (dict, list, str)) else 1
        if start > total:
            raise RecordReadingError('record_read_cursor_invalid', '续读位置超出内容范围')
        page = {'type': kind, 'total_count': total, 'start': start,
                'next_cursor': continuation(start, total), 'unexpanded_refs': []}
        result['record_pages'][ref] = page
        if kind in {'object', 'array'}:
            page['entries'] = []
        elif kind == 'string':
            page['text'] = ''
            page['offset_unit'] = 'unicode_code_point'
        else:
            page['value'] = value
        if not fits():
            del result['record_pages'][ref]
            del result['record_sources'][ref]
            result['reading']['unread_refs'].append(ref)
            if len(selections) == 1:
                raise RecordReadingError('record_read_budget_too_small', '记录元数据无法容纳；提高预算')
            continue
        if kind in {'object', 'array'}:
            # Match canonical hashing: equivalent object key orders must have
            # identical page offsets even when a source's insertion order changes.
            entries = sorted(value.items()) if kind == 'object' else list(enumerate(value))
            offset = start
            for key, child in entries[start:]:
                child_ref = child_reference(root, [*parts, str(key)])
                entry = {'key' if kind == 'object' else 'index': key,
                         'ref': child_ref, 'type': _type(child), 'value': deepcopy(child)}
                page['entries'].append(entry)
                page['next_cursor'] = continuation(offset + 1, total)
                if not fits():
                    del entry['value']
                    entry['value_omitted'] = True
                    page['unexpanded_refs'].append(child_ref)
                if not fits():
                    page['entries'].pop()
                    if page['unexpanded_refs'] and page['unexpanded_refs'][-1] == child_ref:
                        page['unexpanded_refs'].pop()
                    page['next_cursor'] = continuation(offset, total)
                    break
                offset += 1
            if offset == start and start < total:
                raise RecordReadingError('record_read_budget_too_small', '单条引用无法容纳；提高预算或缩小读取范围')
        elif kind == 'string':
            low, high = start, total
            while low < high:
                middle = (low + high + 1) // 2
                page['text'] = value[start:middle]
                page['next_cursor'] = continuation(middle, total)
                if fits():
                    low = middle
                else:
                    high = middle - 1
            if low == start and start < total:
                raise RecordReadingError('record_read_budget_too_small', '文字片段无法容纳；提高预算')
            page['text'] = value[start:low]
            page['next_cursor'] = continuation(low, total)
        else:
            page['next_cursor'] = None
    if not fits():
        raise RecordReadingError('record_read_budget_too_small', '返回预算不足；缩小读取范围')
    return result
