"""Content-addressed manifests and paged JSON components for alignment work."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
from typing import Any


PREPARATION_REF_SCHEMA = "strixnova.implementation-alignment-preparation-ref.v1"
COMPONENT_REF_SCHEMA = "strixnova.implementation-alignment-component-ref.v1"
MANIFEST_LAYOUT_SCHEMA = "strixnova.implementation-alignment-manifest-layout.v1"
CHUNK_SCHEMA = "strixnova.implementation-alignment-json-chunk.v1"
GC_RESULT_SCHEMA = "strixnova.implementation-alignment-gc-result.v1"
PAGE_TARGET_BYTES = 512 * 1024
MAX_CHUNK_BYTES = 8 * 1024 * 1024
MAX_PAGE_ITEMS = 256


class AlignmentArtifactError(ValueError):
    def __init__(self, code: str, message: str, *, details: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise AlignmentArtifactError(
            "alignment_preparation_not_serializable",
            "实现对齐准备包包含不能稳定序列化的内容",
        ) from error


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


class ImplementationAlignmentArtifactStore:
    """Store small manifests and reusable, bounded JSON component pages."""

    _ROOT = PurePosixPath(".strixnova/artifacts/implementation-alignment")
    _PREPARATION_COMPONENT_FIELDS = (
        "baseline",
        "domain_model",
        "architecture_model",
        "architecture",
        "documents",
        "governed_hashes",
        "observation",
        "decision_catalog",
    )
    _CAPTURE_COMPONENT_FIELDS = ("observation",)

    def __init__(self, project: Path) -> None:
        self.project = project.resolve()
        self.root = self.project.joinpath(*self._ROOT.parts)

    def _write_content(self, directory: str, content: bytes) -> tuple[Path, str]:
        digest = hashlib.sha256(content).hexdigest()
        target = self.root / directory / f"{digest}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != content:
                raise AlignmentArtifactError(
                    "alignment_artifact_hash_collision",
                    "内容寻址实现对齐产物发生散列冲突",
                )
            return target, digest
        with tempfile.NamedTemporaryFile(
            mode="wb",
            prefix=f".{target.name}.",
            suffix=".next",
            dir=target.parent,
            delete=False,
        ) as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            temporary = Path(stream.name)
        try:
            os.replace(temporary, target)
            _fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)
        return target, digest

    def _component_ref(self, payload: Mapping[str, Any]) -> dict[str, str]:
        content = _canonical_json(payload)
        if len(content) > MAX_CHUNK_BYTES:
            raise AlignmentArtifactError(
                "alignment_component_too_large",
                "实现对齐组件单页超过 8 MiB；必须继续分块",
                details={"size_bytes": len(content)},
            )
        target, digest = self._write_content("components", content)
        return {
            "schema_version": COMPONENT_REF_SCHEMA,
            "artifact_id": "ALIGNCOMP-" + digest[:16].upper(),
            "path": target.relative_to(self.project).as_posix(),
            "content_sha256": digest,
        }

    @staticmethod
    def _value_payload(value: Any) -> dict[str, Any]:
        return {"schema_version": CHUNK_SCHEMA, "kind": "value", "value": value}

    def _store_value(self, value: Any) -> dict[str, str]:
        direct = self._value_payload(value)
        content = _canonical_json(direct)
        if len(content) <= PAGE_TARGET_BYTES or not isinstance(
            value, (list, dict)
        ):
            return self._component_ref(direct)
        if isinstance(value, list):
            segments: list[dict[str, Any]] = []
            page: list[Any] = []
            for item in value:
                candidate = [*page, item]
                candidate_size = len(_canonical_json(self._value_payload(candidate)))
                if page and (
                    len(page) >= MAX_PAGE_ITEMS
                    or candidate_size > PAGE_TARGET_BYTES
                ):
                    segments.append(
                        {"kind": "page", "ref": self._component_ref(self._value_payload(page))}
                    )
                    page = []
                    candidate = [item]
                    candidate_size = len(
                        _canonical_json(self._value_payload(candidate))
                    )
                if candidate_size > PAGE_TARGET_BYTES:
                    if page:
                        segments.append(
                            {"kind": "page", "ref": self._component_ref(self._value_payload(page))}
                        )
                        page = []
                    segments.append({"kind": "item", "ref": self._store_value(item)})
                else:
                    page = candidate
            if page:
                segments.append(
                    {"kind": "page", "ref": self._component_ref(self._value_payload(page))}
                )
            return self._component_ref(
                {
                    "schema_version": CHUNK_SCHEMA,
                    "kind": "list_segments",
                    "item_count": len(value),
                    "segments": segments,
                }
            )

        pages: list[dict[str, str]] = []
        separate_entries: list[dict[str, Any]] = []
        page_map: dict[str, Any] = {}
        for key in sorted(value, key=str):
            text_key = str(key)
            candidate = {**page_map, text_key: value[key]}
            candidate_size = len(_canonical_json(self._value_payload(candidate)))
            if page_map and (
                len(page_map) >= MAX_PAGE_ITEMS
                or candidate_size > PAGE_TARGET_BYTES
            ):
                pages.append(self._component_ref(self._value_payload(page_map)))
                page_map = {}
                candidate = {text_key: value[key]}
                candidate_size = len(_canonical_json(self._value_payload(candidate)))
            if candidate_size > PAGE_TARGET_BYTES:
                if page_map:
                    pages.append(self._component_ref(self._value_payload(page_map)))
                    page_map = {}
                separate_entries.append(
                    {"key": text_key, "value_ref": self._store_value(value[key])}
                )
            else:
                page_map = candidate
        if page_map:
            pages.append(self._component_ref(self._value_payload(page_map)))
        return self._component_ref(
            {
                "schema_version": CHUNK_SCHEMA,
                "kind": "map_pages",
                "entry_count": len(value),
                "pages": pages,
                "separate_entries": separate_entries,
            }
        )

    def _validated_component_ref(self, reference: Mapping[str, Any]) -> Path:
        if not isinstance(reference, Mapping) or set(reference) != {
            "schema_version",
            "artifact_id",
            "path",
            "content_sha256",
        }:
            raise AlignmentArtifactError(
                "alignment_component_ref_invalid",
                "实现对齐组件引用结构无效",
            )
        digest = str(reference.get("content_sha256") or "")
        expected = (self._ROOT / "components" / f"{digest}.json").as_posix()
        if (
            reference.get("schema_version") != COMPONENT_REF_SCHEMA
            or reference.get("artifact_id") != "ALIGNCOMP-" + digest[:16].upper()
            or reference.get("path") != expected
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise AlignmentArtifactError(
                "alignment_component_ref_invalid",
                "实现对齐组件引用没有绑定内容寻址路径",
            )
        return self.project.joinpath(*PurePosixPath(expected).parts)

    def _read_component(self, reference: Mapping[str, Any]) -> dict[str, Any]:
        target = self._validated_component_ref(reference)
        try:
            content = target.read_bytes()
        except OSError as error:
            raise AlignmentArtifactError(
                "alignment_component_missing",
                "实现对齐组件不存在",
            ) from error
        if hashlib.sha256(content).hexdigest() != reference["content_sha256"]:
            raise AlignmentArtifactError(
                "alignment_component_changed",
                "实现对齐组件内容与引用散列不一致",
            )
        try:
            value = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AlignmentArtifactError(
                "alignment_component_invalid",
                "实现对齐组件不是有效 UTF-8 JSON",
            ) from error
        if not isinstance(value, dict) or value.get("schema_version") != CHUNK_SCHEMA:
            raise AlignmentArtifactError(
                "alignment_component_invalid",
                "实现对齐组件版本无效",
            )
        return value

    def _load_value(self, reference: Mapping[str, Any]) -> Any:
        component = self._read_component(reference)
        kind = component.get("kind")
        if kind == "value" and set(component) == {"schema_version", "kind", "value"}:
            return component["value"]
        if kind == "list_segments":
            result: list[Any] = []
            for segment in component.get("segments") or []:
                if not isinstance(segment, Mapping) or segment.get("kind") not in {
                    "page",
                    "item",
                }:
                    raise AlignmentArtifactError(
                        "alignment_component_invalid",
                        "实现对齐列表分块索引无效",
                    )
                loaded = self._load_value(segment.get("ref"))
                if segment["kind"] == "page":
                    if not isinstance(loaded, list):
                        raise AlignmentArtifactError(
                            "alignment_component_invalid",
                            "实现对齐列表页不是数组",
                        )
                    result.extend(loaded)
                else:
                    result.append(loaded)
            if len(result) != component.get("item_count"):
                raise AlignmentArtifactError(
                    "alignment_component_invalid",
                    "实现对齐列表分块数量不一致",
                )
            return result
        if kind == "map_pages":
            result: dict[str, Any] = {}
            for page_ref in component.get("pages") or []:
                page = self._load_value(page_ref)
                if not isinstance(page, dict) or set(result) & set(page):
                    raise AlignmentArtifactError(
                        "alignment_component_invalid",
                        "实现对齐对象页无效或键重复",
                    )
                result.update(page)
            for entry in component.get("separate_entries") or []:
                if not isinstance(entry, Mapping):
                    raise AlignmentArtifactError(
                        "alignment_component_invalid",
                        "实现对齐对象独立条目无效",
                    )
                key = str(entry.get("key") or "")
                if not key or key in result:
                    raise AlignmentArtifactError(
                        "alignment_component_invalid",
                        "实现对齐对象独立条目键无效或重复",
                    )
                result[key] = self._load_value(entry.get("value_ref"))
            if len(result) != component.get("entry_count"):
                raise AlignmentArtifactError(
                    "alignment_component_invalid",
                    "实现对齐对象分块数量不一致",
                )
            return result
        raise AlignmentArtifactError(
            "alignment_component_invalid",
            "实现对齐组件 kind 无效",
        )

    def store_packet(self, kind: str, value: Mapping[str, Any]) -> dict[str, str]:
        if kind not in {"preparations", "captures"}:
            raise AssertionError(kind)
        fields: Sequence[str] = (
            self._PREPARATION_COMPONENT_FIELDS
            if kind == "preparations"
            else self._CAPTURE_COMPONENT_FIELDS
        )
        manifest = deepcopy(dict(value))
        component_refs: dict[str, dict[str, str]] = {}
        for field in fields:
            if field in manifest:
                component_refs[field] = self._store_value(manifest.pop(field))
        manifest["artifact_layout_schema"] = MANIFEST_LAYOUT_SCHEMA
        manifest["component_refs"] = component_refs
        content = _canonical_json(manifest)
        target, digest = self._write_content(kind, content)
        return {
            "schema_version": PREPARATION_REF_SCHEMA,
            "artifact_kind": kind,
            "artifact_id": (
                "ALIGNPREP-" if kind == "preparations" else "ALIGNCAPTURE-"
            )
            + digest[:16].upper(),
            "path": target.relative_to(self.project).as_posix(),
            "content_sha256": digest,
        }

    def load_packet(
        self,
        reference: Mapping[str, Any],
        *,
        expected_kind: str,
        expected_schema: str,
    ) -> dict[str, Any]:
        if not isinstance(reference, Mapping) or set(reference) != {
            "schema_version",
            "artifact_kind",
            "artifact_id",
            "path",
            "content_sha256",
        }:
            raise AlignmentArtifactError(
                "alignment_preparation_ref_invalid",
                "实现对齐准备引用结构无效",
            )
        digest = str(reference.get("content_sha256") or "")
        expected_path = (self._ROOT / expected_kind / f"{digest}.json").as_posix()
        prefix = "ALIGNPREP-" if expected_kind == "preparations" else "ALIGNCAPTURE-"
        if (
            reference.get("schema_version") != PREPARATION_REF_SCHEMA
            or reference.get("artifact_kind") != expected_kind
            or reference.get("artifact_id") != prefix + digest[:16].upper()
            or reference.get("path") != expected_path
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise AlignmentArtifactError(
                "alignment_preparation_ref_invalid",
                "实现对齐准备引用没有绑定受管内容寻址路径",
            )
        target = self.project.joinpath(*PurePosixPath(expected_path).parts)
        try:
            content = target.read_bytes()
        except OSError as error:
            raise AlignmentArtifactError(
                "alignment_preparation_missing",
                "实现对齐准备包不存在",
            ) from error
        if hashlib.sha256(content).hexdigest() != digest:
            raise AlignmentArtifactError(
                "alignment_preparation_changed",
                "实现对齐准备包内容与引用散列不一致",
            )
        try:
            manifest = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AlignmentArtifactError(
                "alignment_preparation_invalid",
                "实现对齐准备包不是有效 UTF-8 JSON",
            ) from error
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != expected_schema
            or manifest.get("artifact_layout_schema") != MANIFEST_LAYOUT_SCHEMA
            or not isinstance(manifest.get("component_refs"), dict)
        ):
            raise AlignmentArtifactError(
                "alignment_preparation_invalid",
                "实现对齐准备包版本或分块布局无效",
            )
        hydrated = dict(manifest)
        references = hydrated.pop("component_refs")
        hydrated.pop("artifact_layout_schema")
        for field, component_ref in references.items():
            hydrated[str(field)] = self._load_value(component_ref)
        return hydrated

    @staticmethod
    def _digest_name(path: Path, *, artifact_kind: str) -> str:
        digest = path.stem
        if (
            path.suffix != ".json"
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or path.is_symlink()
        ):
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"实现对齐 {artifact_kind} 目录包含非受管文件：{path}",
            )
        return digest

    def _content_files(self, directory: str) -> list[Path]:
        root = self.root / directory
        if not root.exists():
            return []
        if not root.is_dir() or root.is_symlink():
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"实现对齐 {directory} 路径不是受管目录",
            )
        files: list[Path] = []
        for path in sorted(root.iterdir(), key=lambda value: value.name):
            if not path.is_file() or path.is_symlink():
                raise AlignmentArtifactError(
                    "alignment_gc_unsafe",
                    f"实现对齐 {directory} 目录包含非受管条目：{path}",
                )
            self._digest_name(path, artifact_kind=directory)
            files.append(path)
        return files

    def _manifest_component_refs(
        self,
        path: Path,
        *,
        artifact_kind: str,
    ) -> list[Mapping[str, Any]]:
        digest = self._digest_name(path, artifact_kind=artifact_kind)
        try:
            content = path.read_bytes()
        except OSError as error:
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"无法读取实现对齐 {artifact_kind} 清单：{path}",
            ) from error
        if hashlib.sha256(content).hexdigest() != digest:
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"实现对齐 {artifact_kind} 清单散列无效：{path}",
            )
        try:
            manifest = json.loads(content.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as error:
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"实现对齐 {artifact_kind} 清单不是有效 UTF-8 JSON：{path}",
            ) from error
        references = manifest.get("component_refs") if isinstance(manifest, dict) else None
        if (
            not isinstance(manifest, dict)
            or manifest.get("artifact_layout_schema") != MANIFEST_LAYOUT_SCHEMA
            or not isinstance(references, dict)
            or any(not isinstance(value, Mapping) for value in references.values())
        ):
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"实现对齐 {artifact_kind} 清单布局无效：{path}",
            )
        return list(references.values())

    def _reachable_component_digests(
        self,
        references: Sequence[Mapping[str, Any]],
    ) -> set[str]:
        reachable: set[str] = set()
        pending: list[Mapping[str, Any]] = list(references)
        while pending:
            reference = pending.pop()
            target = self._validated_component_ref(reference)
            digest = str(reference["content_sha256"])
            if digest in reachable:
                continue
            component = self._read_component(reference)
            reachable.add(digest)
            kind = component.get("kind")
            if kind == "value":
                if set(component) != {"schema_version", "kind", "value"}:
                    raise AlignmentArtifactError(
                        "alignment_gc_unsafe",
                        f"实现对齐组件 value 布局无效：{target}",
                    )
                continue
            if kind == "list_segments":
                segments = component.get("segments")
                if not isinstance(segments, list):
                    raise AlignmentArtifactError(
                        "alignment_gc_unsafe",
                        f"实现对齐列表组件索引无效：{target}",
                    )
                for segment in segments:
                    if (
                        not isinstance(segment, Mapping)
                        or segment.get("kind") not in {"page", "item"}
                        or not isinstance(segment.get("ref"), Mapping)
                    ):
                        raise AlignmentArtifactError(
                            "alignment_gc_unsafe",
                            f"实现对齐列表组件引用无效：{target}",
                        )
                    pending.append(segment["ref"])
                continue
            if kind == "map_pages":
                pages = component.get("pages")
                entries = component.get("separate_entries")
                if not isinstance(pages, list) or not isinstance(entries, list):
                    raise AlignmentArtifactError(
                        "alignment_gc_unsafe",
                        f"实现对齐对象组件索引无效：{target}",
                    )
                for reference_value in pages:
                    if not isinstance(reference_value, Mapping):
                        raise AlignmentArtifactError(
                            "alignment_gc_unsafe",
                            f"实现对齐对象分页引用无效：{target}",
                        )
                    pending.append(reference_value)
                for entry in entries:
                    if (
                        not isinstance(entry, Mapping)
                        or not isinstance(entry.get("key"), str)
                        or not isinstance(entry.get("value_ref"), Mapping)
                    ):
                        raise AlignmentArtifactError(
                            "alignment_gc_unsafe",
                            f"实现对齐对象独立条目无效：{target}",
                        )
                    pending.append(entry["value_ref"])
                continue
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                f"实现对齐组件 kind 无效：{target}",
            )
        return reachable

    def garbage_collect_orphan_components(
        self,
        *,
        apply: bool,
        expected_orphan_set_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Report or delete only components unreachable from immutable manifests."""

        manifest_files = {
            kind: self._content_files(kind)
            for kind in ("preparations", "captures")
        }
        references: list[Mapping[str, Any]] = []
        for kind, paths in manifest_files.items():
            for path in paths:
                references.extend(
                    self._manifest_component_refs(path, artifact_kind=kind)
                )
        reachable = self._reachable_component_digests(references)
        component_files = self._content_files("components")
        components: dict[str, tuple[Path, int]] = {}
        for path in component_files:
            digest = self._digest_name(path, artifact_kind="components")
            try:
                content = path.read_bytes()
            except OSError as error:
                raise AlignmentArtifactError(
                    "alignment_gc_unsafe",
                    f"无法读取实现对齐组件：{path}",
                ) from error
            if hashlib.sha256(content).hexdigest() != digest:
                raise AlignmentArtifactError(
                    "alignment_gc_unsafe",
                    f"实现对齐组件散列无效：{path}",
                )
            components[digest] = (path, len(content))
        missing = sorted(reachable - set(components))
        if missing:
            raise AlignmentArtifactError(
                "alignment_gc_unsafe",
                "受保留实现对齐清单引用了缺失组件",
                details=missing,
            )
        orphan_digests = sorted(set(components) - reachable)
        orphan_records = [
            {
                "path": components[digest][0].relative_to(self.project).as_posix(),
                "content_sha256": digest,
                "size_bytes": components[digest][1],
            }
            for digest in orphan_digests
        ]
        orphan_set_sha256 = hashlib.sha256(
            _canonical_json(orphan_records)
        ).hexdigest()
        if apply and expected_orphan_set_sha256 != orphan_set_sha256:
            raise AlignmentArtifactError(
                "alignment_gc_preview_required",
                "实际孤立组件集合与已复核 dry-run 不一致；请重新 dry-run",
                details={
                    "actual_orphan_set_sha256": orphan_set_sha256,
                    "actual_orphan_component_count": len(orphan_records),
                },
            )
        deleted_bytes = 0
        if apply:
            for digest in orphan_digests:
                path, size = components[digest]
                path.unlink()
                deleted_bytes += size
            if orphan_digests:
                _fsync_directory(self.root / "components")
        sample = orphan_records[:20]
        return {
            "schema_version": GC_RESULT_SCHEMA,
            "mode": "apply" if apply else "dry_run",
            "preparation_manifest_count": len(manifest_files["preparations"]),
            "capture_manifest_count": len(manifest_files["captures"]),
            "retained_component_count": len(reachable),
            "orphan_component_count": len(orphan_records),
            "orphan_component_bytes": sum(
                int(record["size_bytes"]) for record in orphan_records
            ),
            "orphan_set_sha256": orphan_set_sha256,
            "orphan_component_sample": sample,
            "orphan_component_sample_truncated": len(sample) < len(orphan_records),
            "deleted_component_count": len(orphan_records) if apply else 0,
            "deleted_component_bytes": deleted_bytes,
            "preparations_deleted": 0,
            "captures_deleted": 0,
            "transactions_touched": False,
        }


__all__ = [
    "AlignmentArtifactError",
    "ImplementationAlignmentArtifactStore",
    "GC_RESULT_SCHEMA",
    "MANIFEST_LAYOUT_SCHEMA",
    "MAX_CHUNK_BYTES",
    "PAGE_TARGET_BYTES",
]
