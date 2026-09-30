from __future__ import annotations

from pathlib import Path

import yaml

from tests.support.project_context import FRONTEND, PROJECT, git


def configuration_document(
    *, project_id: str = PROJECT, repository_id: str = FRONTEND,
    baseline_path: str = "docs/engineering/baseline.yaml", integration_ref=None,
) -> dict:
    return {
        "schema_version": "strixnova.project-config.v1",
        "project_id": project_id,
        "repository_id": repository_id,
        "repositories": [{"repository_id": repository_id, "owner_project_id": project_id, "purpose": "隔离测试仓库"}],
        "engineering_baseline": {"repository_id": repository_id, "path": baseline_path, "ref": None},
        "default_integration_ref": integration_ref,
    }


def configure_repository(
    project: Path, *, baseline_path: str = "docs/engineering/baseline.yaml",
    integration_ref=None, project_id: str | None = None, repository_id: str | None = None,
) -> dict:
    """Explicitly prepare an isolated Git fixture and its current locator."""

    project.mkdir(parents=True, exist_ok=True)
    if not (project / ".git").exists():
        git(project, "init", "-b", "main")
        git(project, "config", "user.name", "Strixnova Configuration Test")
        git(project, "config", "user.email", "configuration@example.invalid")
        git(project, "config", "core.autocrlf", "false")
    baseline_file = project / baseline_path
    if baseline_file.is_file():
        baseline = yaml.safe_load(baseline_file.read_text(encoding="utf-8"))
        baseline = baseline if isinstance(baseline, dict) else {}
        references = baseline.get("authority_refs") or {}
        recorded_ids = {reference.get("repository_id") for reference in references.values() if isinstance(reference, dict)} - {None}
        if repository_id is None and len(recorded_ids) == 1:
            repository_id = recorded_ids.pop()
        if project_id is None:
            project_id = (baseline.get("project") or {}).get("project_id")
    configuration = configuration_document(
        project_id=project_id or PROJECT, repository_id=repository_id or FRONTEND,
        baseline_path=baseline_path, integration_ref=integration_ref,
    )
    (project / "strixnova-project.yaml").write_text(yaml.safe_dump(configuration, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return configuration
