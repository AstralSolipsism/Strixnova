"""Bind externally established execution-stop facts to an exact local scope.

The program verifies the contract, references and bytes. It does not infer
whether an operator's process inspection proves that every child has stopped.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from importlib.resources import files
import json
from pathlib import Path
from typing import Any, Mapping

class ExecutionStopEvidenceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@lru_cache(maxsize=1)
def _schema() -> dict[str, Any]:
    return json.loads(files("strixnova.resources").joinpath("execution-stop-evidence-v1.schema.json").read_text(encoding="utf-8"))


def stop_evidence_contract() -> dict[str, Any]:
    return deepcopy(_schema())


def validate_stop_evidence(value: Any, expected_scope: Mapping[str, Any]) -> dict[str, Any]:
    # Initial offline installation imports maintenance before dependencies are
    # installed. Schema validation is needed only when stop evidence is used.
    from jsonschema import Draft202012Validator

    first = next(Draft202012Validator(_schema()).iter_errors(value), None)
    if first is not None:
        path = ".".join(str(part) for part in first.absolute_path) or "input"
        raise ExecutionStopEvidenceError("execution_stop_evidence_invalid", f"停机证据不符合公开合同：{path}：{first.message}")
    if len(json.dumps(value, ensure_ascii=False).encode("utf-8")) > 32768:
        raise ExecutionStopEvidenceError("execution_stop_evidence_invalid", "一次停机证据描述不能超过 32 KiB")
    if value["scope"] != dict(expected_scope):
        raise ExecutionStopEvidenceError("execution_stop_evidence_stale", "停机证据不属于当前项目、旧程序或未收口操作")
    try:
        observed = datetime.fromisoformat(value["observed_at"])
        if observed.tzinfo is None or observed > datetime.now(timezone.utc):
            raise ValueError
    except (TypeError, ValueError) as error:
        raise ExecutionStopEvidenceError("execution_stop_evidence_invalid", "停机证据时间必须带时区且不能晚于现在") from error
    seen = set()
    for reference in value["evidence_files"]:
        path = Path(reference["path"]).expanduser()
        try:
            if not path.is_absolute() or path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
                raise ValueError
            resolved = str(path.resolve())
            if resolved in seen:
                raise ValueError
            seen.add(resolved)
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != reference["sha256"]:
                raise ExecutionStopEvidenceError("execution_stop_evidence_changed", "外部停机证据文件与记录的内容身份不一致")
        except (OSError, ValueError) as error:
            if isinstance(error, ExecutionStopEvidenceError):
                raise
            raise ExecutionStopEvidenceError("execution_stop_evidence_invalid", "停机依据必须是明确、唯一且不超过 1 MiB 的本地普通文件") from error
    return deepcopy(value)
