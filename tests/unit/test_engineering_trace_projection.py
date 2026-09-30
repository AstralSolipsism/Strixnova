from __future__ import annotations

from tests.support.project_configuration import configure_repository

from copy import deepcopy
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from strixnova.engineering_trace_projection import (
    EngineeringTraceProjection,
    EngineeringTraceProjectionError,
)
from tests.support.project_baseline import (
    TEST_DOMAIN_MODEL_ID,
    TEST_TERM_FACT_ID,
    adopt_portable_ddd,
    portable_project_baseline,
)


def _git(repo: Path, *args: str) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _write_yaml(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(value, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


class _AuthorityFixture:
    def __init__(self, items: list[dict], histories: dict[str, list[dict]]) -> None:
        self._items = {item["work_item_id"]: item for item in items}
        self._histories = histories

    def get(self, identifier: str) -> dict:
        return deepcopy(self._items[identifier])

    def list(self) -> list[dict]:
        return deepcopy(list(self._items.values()))

    def history(self, identifier: str) -> list[dict]:
        return deepcopy(self._histories[identifier])


def _event(
    work_item_id: str,
    version: int,
    event_type: str,
    payload: dict,
) -> dict:
    return {
        "work_item_id": work_item_id,
        "version": version,
        "event_type": event_type,
        "payload": payload,
        "sequence": version,
        "recorded_at": f"2026-08-26T00:00:{version:02d}Z",
    }


def _domain_reference(commit: str) -> dict[str, str]:
    return {
        "schema_version": "strixnova.domain-fact-reference.v1",
        "authority_kind": "project_domain_model",
        "model_id": TEST_DOMAIN_MODEL_ID,
        "fact_id": TEST_TERM_FACT_ID,
        "observed_commit": commit,
    }


def _repository(tmp_path: Path) -> tuple[dict, dict[str, str], str]:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="trace-project",
        artifacts=[],
    )
    identities = adopt_portable_ddd(tmp_path, baseline)
    _write_yaml(tmp_path / "docs/engineering/baseline.yaml", baseline)
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "adopt current authorities")
    _git(tmp_path, "branch", "-M", "main")
    return baseline, identities, _git(tmp_path, "rev-parse", "main")


def _completed_item(commit: str) -> tuple[dict, list[dict]]:
    reference = _domain_reference(commit)
    assessment = {
        "domain_fact_changes": [
            {
                "disposition": "update",
                "target_ref": reference,
                "lineage": [],
            }
        ],
        "method_applications": [
            {
                "domain_fact_refs": [reference],
            }
        ],
        "operations": [
            {
                "action": "modify",
                "path": "docs/domain/model.yaml",
                "long_lived_artifact": {
                    "artifact_id": "DOMAIN-MODEL-001",
                    "artifact_type": "domain_model",
                },
            }
        ],
    }
    actual_result = {
        "long_lived_refs": [
            {
                "artifact_id": "DOMAIN-MODEL-001",
                "artifact_type": "domain_model",
                "path": "docs/domain/model.yaml",
                "relation": "updated",
            }
        ],
        "domain_fact_change_results": [
            {
                "target_ref": reference,
                "outcome": "realized",
                "limitations": [],
            }
        ],
        "method_application_results": [
            {
                "method_id": "ddd",
            }
        ],
    }
    item = {
        "work_item_id": "WI-TRACE",
        "status": "completed",
        "version": 8,
        "current_action": None,
        "data": {
            "engineering": {"assessment": assessment, "plan": {}},
            "actual_result": actual_result,
            "verifications": [
                {
                    "schema_version": "strixnova.verification-summary.v1",
                    "receipt_id": "VR-TRACE",
                    "command_id": "VC-001",
                    "result": "passed",
                }
            ],
            "git": {
                "result_commits": [commit],
                "integration": {
                    "result_commits": [commit],
                    "integrated_commit": commit,
                },
            },
        },
    }
    history = [
        _event(
            "WI-TRACE",
            1,
            "submit_engineering_assessment",
            {"assessment": assessment},
        ),
        _event(
            "WI-TRACE",
            2,
            "present_actual_result",
            {"actual_result": actual_result},
        ),
    ]
    return item, history


def test_projection_resolves_a_moving_integration_ref_for_every_query(
    tmp_path: Path,
) -> None:
    baseline, _identities, initial_commit = _repository(tmp_path)
    projection = EngineeringTraceProjection(
        tmp_path,
        authority=_AuthorityFixture([], {}),
    )

    initial_fact = projection.for_fact(TEST_TERM_FACT_ID)
    initial_baseline = projection.for_artifact(baseline["baseline_id"])

    (tmp_path / "README.md").write_text("later adopted change\n", encoding="utf-8")
    _git(tmp_path, "add", "README.md")
    _git(tmp_path, "commit", "-m", "advance local integration branch")
    advanced_commit = _git(tmp_path, "rev-parse", "main")

    advanced_fact = projection.for_fact(TEST_TERM_FACT_ID)
    assert advanced_commit != initial_commit
    assert initial_fact["at_commit"] == initial_commit
    assert advanced_fact["at_commit"] == advanced_commit
    assert advanced_fact["fact"]["fact_id"] == TEST_TERM_FACT_ID
    assert initial_baseline["artifact_status"] == "current"


def test_trace_separates_current_records_audit_history_and_adoption_claims(
    tmp_path: Path,
) -> None:
    baseline, _identities, commit = _repository(tmp_path)
    completed, history = _completed_item(commit)
    replanning = {
        "work_item_id": "WI-REPLAN",
        "status": "replanning_required",
        "version": 3,
        "current_action": None,
        "data": {},
    }
    replanning_history = [
        _event(
            "WI-REPLAN",
            1,
            "submit_engineering_assessment",
            {"assessment": completed["data"]["engineering"]["assessment"]},
        )
    ]
    authority = _AuthorityFixture(
        [completed, replanning],
        {"WI-TRACE": history, "WI-REPLAN": replanning_history},
    )
    projection = EngineeringTraceProjection(tmp_path, authority=authority)

    current = projection.for_work_item("WI-TRACE", at_commit=commit)
    assert {
        "governed_by",
        "domain_fact_reference",
        "long_lived_output_reference",
        "verification_receipt",
        "result_commit",
        "local_integration_receipt",
    }.issubset({edge["edge_kind"] for edge in current["edges"]})
    assert all(edge["provenance"] for edge in current["edges"])
    assert current["persisted_cache"] is False
    assert current["write_interface"] is False

    assert projection.for_work_item(
        "WI-REPLAN", mode="current", at_commit=commit
    )["edges"] == []
    audit = projection.for_work_item(
        "WI-REPLAN", mode="audit", at_commit=commit
    )
    assert {edge["provenance"]["source_kind"] for edge in audit["edges"]} >= {
        "authority_event"
    }

    fact_trace = projection.for_fact(TEST_TERM_FACT_ID, at_commit=commit)
    assert fact_trace["fact_status"] == "current"
    assert fact_trace["implementation_alignment"]["domain_fact_id"] == (
        TEST_TERM_FACT_ID
    )
    output_trace = projection.for_artifact("DOMAIN-MODEL-001", at_commit=commit)
    assert output_trace["artifact_status"] == "recorded_output"
    formal_trace = projection.for_artifact(baseline["baseline_id"], at_commit=commit)
    assert formal_trace["artifact_status"] == "current"
    assert all(
        edge["adopted_at_query_commit"] in {True, False, None}
        for edge in current["edges"]
    )


def test_trace_rejects_unknown_mode_and_missing_version_binding(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    projection = EngineeringTraceProjection(
        tmp_path,
        authority=_AuthorityFixture([], {}),
    )
    with pytest.raises(EngineeringTraceProjectionError) as invalid_mode:
        projection.for_fact(TEST_TERM_FACT_ID, mode="latest")
    assert invalid_mode.value.code == "invalid_trace_mode"

    with pytest.raises(EngineeringTraceProjectionError) as missing_ref:
        projection.for_fact(TEST_TERM_FACT_ID)
    assert missing_ref.value.code == "integration_ref_required"
