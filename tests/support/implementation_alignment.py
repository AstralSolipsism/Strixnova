"""Small, self-contained projects for alignment behavior tests.

The saved external receipt is synthetic test input. No external provider is
executed and no live Strixnova repository snapshot is used as an expectation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import yaml

from strixnova.implementation_observation import observe_project_implementation
from strixnova.git_project_reader import GitProjectReader
from strixnova.project_content_snapshot import repository_path_key
from tests.support.project_context import FRONTEND
from strixnova.project_implementation_alignment import ProjectImplementationAlignment
from tests.support.project_baseline import portable_project_baseline


def write_yaml(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")


def isolated_alignment(
    project: Path, *, recorded_external: bool = False,
) -> ProjectImplementationAlignment:
    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=project, check=True, capture_output=True,
            text=True, encoding="utf-8",
        ).stdout.strip()

    project.mkdir(parents=True, exist_ok=True)
    (project / ".gitattributes").write_text("* text=auto eol=lf\n", encoding="utf-8")
    (project / "src.py").write_bytes(b"VALUE = 1\n")
    git("init", "-q", "-b", "main")
    git("config", "user.name", "Strixnova Test")
    git("config", "user.email", "strixnova@example.invalid")
    git("add", ".gitattributes", "src.py")
    git("commit", "-q", "-m", "fixed behavior fixture")
    commit = git("rev-parse", "HEAD")
    baseline = portable_project_baseline(project, baseline_id="alignment-behavior", artifacts=[])
    baseline["code_version"]["repositories"][0]["base_commit"] = commit
    baseline["review_state"] = {"required": False, "reasons": [], "affected_authority_kinds": []}
    write_yaml(project / "docs/engineering/baseline.yaml", baseline)
    refs = baseline["authority_refs"]
    path = project / refs["implementation_alignment"]["path"]
    model = yaml.safe_load(path.read_text(encoding="utf-8"))
    model["code_snapshot"]["repositories"][0]["base_commit"] = commit
    reader = GitProjectReader(project)
    reader.bind_repository_identity(FRONTEND)
    readers = {FRONTEND: reader}
    observed = observe_project_implementation(readers, model["observation_scopes"])
    assert observed["overall_coverage_status"] == "complete"
    assert not observed["relations"]
    model["observation_coverage"] = {
        "contract_version": observed["schema_version"],
        "overall_status": observed["overall_coverage_status"],
        "source_manifest_sha256": observed["source_manifest_sha256"],
        "observation_snapshot_sha256": observed["observation_snapshot_sha256"],
        "observed_paths": observed["observed_paths"],
        "records": observed["coverage"],
        "provider_receipts": observed["provider_receipts"],
    }
    if recorded_external:
        for record in model["observation_coverage"]["records"]:
            record["execution_mode"] = "authorized_tool"
        for receipt in model["observation_coverage"]["provider_receipts"]:
            receipt["execution_mode"] = "authorized_tool"
    source_key = repository_path_key(FRONTEND, "src.py")
    source_hash = observed["observed_paths"][source_key]
    model["code_snapshot"]["governed_source_manifest_sha256"] = hashlib.sha256(
        f"{source_key}:{source_hash}\n".encode("utf-8")
    ).hexdigest()
    ownership_path = project / model["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["sha256"] = source_hash
    write_yaml(ownership_path, ownership)
    write_yaml(path, model)
    return ProjectImplementationAlignment(
        project, refs["implementation_alignment"]["path"],
        domain_model_path=refs["domain_model"]["path"],
        architecture_description_path=refs["target_architecture"]["path"],
        shared_reader=reader, repository_readers=readers,
    )


def observation_coverage(project: Path, alignment: dict, *, observed_ref: str | None = None) -> dict:
    """Observe one repository member using the same composite contract as production."""
    identifiers = {scope["repository_id"] for scope in alignment["observation_scopes"]}
    if len(identifiers) != 1:
        raise ValueError("This fixture helper requires one physical repository member")
    identifier = next(iter(identifiers))
    reader = GitProjectReader(project, observed_ref=observed_ref)
    if identifier is not None:
        reader.bind_repository_identity(identifier)
    observation = observe_project_implementation({identifier: reader}, alignment["observation_scopes"])
    return {
        "contract_version": observation["schema_version"],
        "overall_status": observation["overall_coverage_status"],
        "source_manifest_sha256": observation["source_manifest_sha256"],
        "observation_snapshot_sha256": observation["observation_snapshot_sha256"],
        "observed_paths": observation["observed_paths"],
        "records": observation["coverage"],
        "provider_receipts": observation["provider_receipts"],
    }
