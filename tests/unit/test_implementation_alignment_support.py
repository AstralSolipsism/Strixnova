from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess
import sys

import pytest

import strixnova.recoverable_document_transaction as transaction_module
from strixnova.implementation_alignment_preparation import (
    _atomic_dump_many,
    _endpoint_module,
    _governed_hashes,
    _ownership,
)
from strixnova.recoverable_document_transaction import (
    recover_document_transactions,
)


def _git(project: Path, *arguments: str) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
    )


def test_atomic_dump_many_rolls_back_every_replaced_document(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    targets = [tmp_path / f"document-{index}.yaml" for index in range(6)]
    for index, target in enumerate(targets):
        target.write_text(f"original: {index}\n", encoding="utf-8")
    original_bytes = {target: target.read_bytes() for target in targets}
    original_replace = transaction_module.os.replace
    next_replacements = 0

    def fail_third_next(source, target):
        nonlocal next_replacements
        if Path(source).name.startswith("replacement-"):
            next_replacements += 1
            if next_replacements == 3:
                raise OSError("injected third replacement failure")
        return original_replace(source, target)

    monkeypatch.setattr(transaction_module.os, "replace", fail_third_next)

    with pytest.raises(OSError, match="third replacement"):
        _atomic_dump_many(
            [
                (target, {"updated": index})
                for index, target in enumerate(targets)
            ]
        )

    assert {target: target.read_bytes() for target in targets} == original_bytes
    assert not list(tmp_path.glob("*.next"))
    assert not list(tmp_path.glob("*.rollback"))


def test_document_transaction_recovers_after_a_hard_process_exit(
    tmp_path: Path,
) -> None:
    targets = [tmp_path / f"document-{index}.yaml" for index in range(6)]
    for index, target in enumerate(targets):
        target.write_text(f"original: {index}\n", encoding="utf-8")
    original = {target: target.read_bytes() for target in targets}
    script = """
import os
from pathlib import Path
import sys
import strixnova.recoverable_document_transaction as transaction

root = Path(sys.argv[1])
targets = [root / f"document-{index}.yaml" for index in range(6)]
real_replace = transaction.os.replace
replacement_count = 0

def terminate_after_third_replacement(source, target):
    global replacement_count
    if Path(source).name.startswith("replacement-"):
        replacement_count += 1
        result = real_replace(source, target)
        if replacement_count == 3:
            os._exit(91)
        return result
    return real_replace(source, target)

transaction.os.replace = terminate_after_third_replacement
transaction.replace_documents(
    [(target, f"updated: {index}\\n".encode()) for index, target in enumerate(targets)]
)
"""

    crashed = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        cwd=Path(__file__).parents[2],
        capture_output=True,
        check=False,
    )

    assert crashed.returncode == 91, crashed.stderr.decode(errors="replace")
    assert {target: target.read_bytes() for target in targets} != original
    transaction_root = (
        tmp_path / ".strixnova" / "artifacts" / "document-transactions"
    )
    assert recover_document_transactions(transaction_root, tmp_path) == 1
    assert {target: target.read_bytes() for target in targets} == original
    assert not list(transaction_root.glob("txn-*"))


def test_refresh_resolves_a_go_package_directory_to_one_owned_module() -> None:
    relation = {
        "target_path": "src/pkg",
        "target_node_kind": "package",
    }
    owners = {
        "src/pkg/a.go": {"target_module_id": "MODULE-1111111111111111"},
        "src/pkg/b.go": {"target_module_id": "MODULE-1111111111111111"},
    }

    assert _endpoint_module(relation, "target", owners) == (
        "MODULE-1111111111111111"
    )


def test_governed_hashes_use_future_git_blob_bytes(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")
    (tmp_path / ".gitattributes").write_text(
        "* text=auto eol=lf\n",
        encoding="utf-8",
    )
    source = tmp_path / "behavior.py"
    source.write_bytes(b"VALUE = 1\r\n")

    assert _governed_hashes(
        tmp_path,
        [
            {
                "root": "behavior.py",
                "included_path_patterns": ["."],
            }
        ],
    ) == {
        "behavior.py": hashlib.sha256(b"VALUE = 1\n").hexdigest()
    }


def test_governed_hashes_reject_overlapping_scopes_independent_of_order(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    source = tmp_path / "src" / "pkg" / "behavior.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    scopes = [
        {
            "scope_id": "OBSCOPE-1111111111111111",
            "root": "src",
            "included_path_patterns": ["**/*.py"],
        },
        {
            "scope_id": "OBSCOPE-2222222222222222",
            "root": "src/pkg",
            "included_path_patterns": ["*.py"],
        },
    ]

    for ordered in (scopes, list(reversed(scopes))):
        with pytest.raises(ValueError, match="必须且只能属于一个"):
            _governed_hashes(tmp_path, ordered)


def test_refresh_preserves_agent_authored_ownership_status_and_reason(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    source = tmp_path / "strixnova" / "src" / "strixnova" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")
    current = {
        "governed_source_scopes": [
            {
                "scope_id": "OBSCOPE-1111111111111111",
                "root": "strixnova/src/strixnova",
                "included_path_patterns": ["*.py", "**/*.py"],
            }
        ],
        "records": [
            {
                "scope_id": "OBSCOPE-1111111111111111",
                "path": "strixnova/src/strixnova/feature.py",
                "sha256": "0" * 64,
                "language_id": "python",
                "node_kind": "source_file",
                "disposition": "owned",
                "target_module_id": "MODULE-1111111111111111",
                "implementation_stage_id": "ARCHSTAGE-1111111111111111",
                "current_status": "partially_aligned",
                "deviation_ids": ["DEVIATION-1111111111111111"],
                "rationale": "由智能编码代理根据真实职责形成的判断。",
            }
        ]
    }

    records, _hashes = _ownership(tmp_path, current)

    assert records[0]["current_status"] == "partially_aligned"
    assert records[0]["deviation_ids"] == ["DEVIATION-1111111111111111"]
    assert records[0]["rationale"] == "由智能编码代理根据真实职责形成的判断。"
    assert records[0]["sha256"] != "0" * 64


def test_refresh_rejects_new_file_without_agent_authored_ownership(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    source = tmp_path / "strixnova" / "src" / "strixnova" / "new_file.py"
    source.parent.mkdir(parents=True)
    source.write_text("VALUE = 1\n", encoding="utf-8")

    with pytest.raises(ValueError):
        _ownership(
            tmp_path,
            {
                "governed_source_scopes": [
                    {
                        "scope_id": "OBSCOPE-1111111111111111",
                        "root": "strixnova/src/strixnova",
                        "included_path_patterns": ["*.py", "**/*.py"],
                    }
                ],
                "records": [],
            },
        )
