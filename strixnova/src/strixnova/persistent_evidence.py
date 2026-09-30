"""Resolve and fingerprint only output files owned by a recorded verification."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping


class EvidenceReferenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def output_path(project: Path, work_item_id: str, receipt_id: str, stream: str, reference: str) -> Path:
    if stream not in {"stdout", "stderr", "cases"} or not isinstance(reference, str):
        raise EvidenceReferenceError("history_evidence_path_invalid", "证据引用格式无效")
    safe_item = "".join(c if c.isalnum() or c in "._-" else "-" for c in work_item_id).strip("-")
    root = project / ".strixnova" / "artifacts" / safe_item
    target = Path(reference)
    if not target.is_absolute():
        target = project / target
    try:
        relative = target.relative_to(root)
        suffix = "cases.json" if stream == "cases" else f"{stream}.log"
        if ".." in relative.parts or len(relative.parts) != 1 or relative.name != f"{receipt_id}.{suffix}":
            raise ValueError
        for path in (project / ".strixnova", project / ".strixnova/artifacts", root, target):
            if path.is_symlink() or path.is_junction():
                raise ValueError
        if not target.resolve().is_relative_to(root.resolve()):
            raise ValueError
    except (ValueError, OSError, RuntimeError) as error:
        raise EvidenceReferenceError("history_evidence_path_invalid", "证据路径不属于当前事项，拒绝读取其他文件") from error
    return target


def capture_outputs(
    project: Path, work_item_id: str, receipt: Mapping[str, Any], *, observation_kind: str, observed_at: str,
) -> list[dict[str, Any]]:
    receipt_id = receipt.get("receipt_id")
    references = receipt.get("raw_output_refs")
    if not isinstance(receipt_id, str) or not receipt_id or not isinstance(references, Mapping):
        raise EvidenceReferenceError("evidence_receipt_invalid", "验证回执缺少持久输出引用")
    references = dict(references)
    case_evidence = receipt.get("case_evidence")
    if isinstance(case_evidence, Mapping):
        references["cases"] = case_evidence.get("report_ref")
    captured = []
    for stream in ("stdout", "stderr", *(("cases",) if isinstance(case_evidence, Mapping) else ())):
        row = {
            "work_item_id": work_item_id, "receipt_id": receipt_id, "stream": stream,
            "relative_path": None, "sha256": None, "size_bytes": None,
            "observation_kind": observation_kind, "observed_at": observed_at, "availability": "not_recorded",
        }
        reference = references.get(stream)
        if reference is not None:
            target = output_path(project, work_item_id, receipt_id, stream, reference)
            row["relative_path"] = target.relative_to(project).as_posix()
            row["availability"] = "missing"
            if target.exists() and not target.is_file():
                raise EvidenceReferenceError("evidence_path_invalid", "原始输出位置不是普通文件")
            if target.is_file():
                with target.open("rb") as source:
                    row["sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
                    row["size_bytes"] = source.tell()
                row["availability"] = "available"
        captured.append(row)
        if stream == "cases" and case_evidence.get("report_sha256") is not None and (
            row["sha256"] != case_evidence["report_sha256"] or row["size_bytes"] != case_evidence["report_size_bytes"]
        ):
            raise EvidenceReferenceError("verification_evidence_changed", "用例报告在读取和持久记录之间改变")
    return captured
