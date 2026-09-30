"""Standalone pytest reporter loaded only in the explicitly selected test process.

This file imports no Strixnova code. Workers send collection metadata through
xdist; only the controller writes the report. Test results are framework events,
not assertions about the adequacy of their business expectations.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest


_state = None


def pytest_configure(config):
    global _state
    _state = {
        "config": config,
        "collected": set(),
        "deselected": set(),
        "errors": [],
        "results": [],
        "collection_complete": False,
    }


def pytest_collection_finish(session):
    _state["collected"].update(item.nodeid for item in session.items)
    _state["collection_complete"] = True


def pytest_deselected(items):
    _state["deselected"].update(item.nodeid for item in items)


def pytest_collectreport(report):
    if report.failed:
        _state["errors"].append(str(report.nodeid))


def pytest_runtest_logreport(report):
    _state["results"].append({
        "test_id": report.nodeid,
        "phase": report.when,
        "outcome": report.outcome,
        "expected_failure": hasattr(report, "wasxfail"),
    })


@pytest.hookimpl(optionalhook=True)
def pytest_xdist_node_collection_finished(node, ids):
    _state["collected"].update(ids)
    _state["collection_complete"] = True


@pytest.hookimpl(optionalhook=True)
def pytest_testnodedown(node, error):
    metadata = node.workeroutput.get("strixnova_case_collection")
    if isinstance(metadata, dict):
        _state["collected"].update(metadata["collected"])
        _state["deselected"].update(metadata["deselected"])
        _state["errors"].extend(metadata["errors"])
    else:
        _state["errors"].append("worker collection report missing")
    if error:
        _state["errors"].append(str(error))


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session, exitstatus):
    config = session.config
    if hasattr(config, "workerinput"):
        config.workeroutput["strixnova_case_collection"] = {
            "collected": sorted(_state["collected"]),
            "deselected": sorted(_state["deselected"]),
            "errors": _state["errors"],
        }
        return
    path_value = os.environ.get("STRIXNOVA_CASE_REPORT_PATH")
    run_id = os.environ.get("STRIXNOVA_CASE_RUN_ID")
    if not path_value or not run_id:
        return
    report = {
        "schema_version": "strixnova.test-case-report.v1",
        "run_id": run_id,
        "adapter": "pytest",
        "adapter_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "framework_version": pytest.__version__,
        "python_version": sys.version,
        "test_root": str(config.rootpath.resolve()),
        "collection_complete": _state["collection_complete"],
        "session_finished": True,
        "exit_status": int(exitstatus),
        "collected_test_ids": sorted(_state["collected"]),
        "deselected_test_ids": sorted(_state["deselected"]),
        "collection_errors": _state["errors"],
        "results": _state["results"],
    }
    path = Path(path_value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, ensure_ascii=False, sort_keys=True)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)
