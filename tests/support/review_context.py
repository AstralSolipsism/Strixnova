"""Fixed review projects, independent of the Strixnova working tree."""

from __future__ import annotations

from pathlib import Path
import yaml

from tests.support.project_baseline import portable_project_baseline, TEST_MODULE_ID
from tests.support.project_context import FRONTEND, git


def write_yaml(project: Path, path: str, value: dict) -> None:
    target = project / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def read_yaml(project: Path, path: str) -> dict:
    return yaml.safe_load((project / path).read_text(encoding="utf-8"))


def review_project(project: Path) -> str:
    project.mkdir(parents=True, exist_ok=True)
    baseline = portable_project_baseline(project, baseline_id="review-context", artifacts=[])
    write_yaml(project, "docs/engineering/baseline.yaml", baseline)
    git(project, "add", ".")
    git(project, "commit", "-m", "fixed review basis")
    return git(project, "rev-parse", "HEAD")


def request(basis: str, *, mode: str = "changes", ref: str | None = None) -> dict:
    selected = {"repository_id": FRONTEND, "ref": ref}
    value = {"schema_version": "strixnova.review-context-request.v1", "mode": mode, "basis_ref": basis, "repositories": [selected]}
    if mode == "changes":
        selected["base_ref"] = basis
    else:
        value["module_ids"] = [TEST_MODULE_ID]
    return value


def project_with_extended_policy(project: Path) -> tuple[str, dict]:
    review_project(project)
    policy = read_yaml(project, "docs/engineering/policy.yaml")
    (project / "docs/conventions.md").write_text("Keep generated output separate.\n", encoding="utf-8")
    policy["project_sources"].append({
        "source_id": "SOURCE-LAYOUT", "title": "Layout convention",
        "path": "docs/conventions.md", "status": "current", "usage": "Project file placement",
    })
    rule = {
        "rule_id": "PROJECT-LAYOUT", "topic": "File placement", "source_ids": ["SOURCE-LAYOUT"],
        "always_for_formal_implementation": True, "impact_dimensions": ["architecture"],
        "minimum_assurance": "A0", "required_information_kinds": ["operation"],
        "strixnova_interpretation": "Keep generated output outside authored source.",
        "evidence_expectations": ["Refer to the declared placement check and its actual receipt."],
    }
    policy["rule_extensions"].append(rule)
    write_yaml(project, "docs/engineering/policy.yaml", policy)
    git(project, "add", ".")
    git(project, "commit", "-m", "record project convention")
    return git(project, "rev-parse", "HEAD"), rule
