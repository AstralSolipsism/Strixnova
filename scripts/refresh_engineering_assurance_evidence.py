"""Refresh only deterministic hashes in a pre-authored assurance candidate.

The script deliberately cannot add evidence, change claims, choose rule status,
close gaps, or revise authority bindings. Those remain reviewable semantic work.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import subprocess
from typing import Any, Mapping

import yaml

from strixnova.git_project_reader import (
    GitProjectReader,
    GitProjectReaderError,
    repository_relative_path,
)


DEFAULT_PATH = "docs/engineering/assurance/model.yaml"


def _load(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("工程保障评估必须包含对象")
    return value


def _head(project: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout.strip()


def refresh(
    project_dir: str | Path,
    expected_revision_id: str,
    *,
    assurance_path: str = DEFAULT_PATH,
) -> dict[str, Any]:
    """Refresh exact evidence hashes while preserving every semantic field."""

    project = Path(project_dir).expanduser().resolve()
    relative_assurance_path = repository_relative_path(
        assurance_path,
        "assurance_path",
    )
    path = project / relative_assurance_path
    value = _load(path)
    if value.get("assurance_revision_id") != expected_revision_id:
        raise ValueError("工程保障修订身份与调用方预期不一致")
    raw_evidence = value.get("evidence")
    if not isinstance(raw_evidence, list) or not raw_evidence:
        raise ValueError("工程保障候选必须先由 Agent 编写非空证据清单")

    reader = GitProjectReader(project)
    seen_ids: set[str] = set()
    refreshed: list[dict[str, Any]] = []
    try:
        for index, raw in enumerate(raw_evidence):
            if not isinstance(raw, Mapping):
                raise ValueError(f"evidence[{index}] 必须是对象")
            item = dict(raw)
            evidence_id = item.get("evidence_id")
            if not isinstance(evidence_id, str) or not evidence_id:
                raise ValueError(f"evidence[{index}].evidence_id 必须非空")
            if evidence_id in seen_ids:
                raise ValueError(f"工程保障证据身份重复：{evidence_id}")
            seen_ids.add(evidence_id)
            evidence_path = repository_relative_path(
                item.get("path"),
                f"evidence[{index}].path",
            )
            item["path"] = evidence_path
            refreshed.append(item)
        hashes: dict[str, str] = {}
        for evidence_path, content in reader.iter_canonical_files(
            [item["path"] for item in refreshed], "工程保障证据"
        ):
            content.decode("utf-8", errors="strict")
            hashes[evidence_path] = hashlib.sha256(content).hexdigest()
        for item in refreshed:
            item["sha256"] = hashes[item["path"]]
    except (GitProjectReaderError, UnicodeError) as error:
        raise ValueError(str(error)) from error

    value["evidence_base_commit"] = _head(project)
    value["evidence"] = refreshed
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return {
        "assurance_revision_id": expected_revision_id,
        "evidence_base_commit": value["evidence_base_commit"],
        "evidence_records": len(refreshed),
        "semantic_fields_changed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    parser.add_argument("--expected-revision-id", required=True)
    parser.add_argument("--assurance-path", default=DEFAULT_PATH)
    arguments = parser.parse_args()
    result = refresh(
        arguments.project_root,
        arguments.expected_revision_id,
        assurance_path=arguments.assurance_path,
    )
    print(yaml.safe_dump(result, allow_unicode=True, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
