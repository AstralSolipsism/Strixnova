"""One isolated installation and first-use check of a finished offline bundle.

Run through local_validation.py run. No Agent workflow or business adoption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile


def check(bundle: Path) -> dict:
    work = Path(os.environ["STRIXNOVA_VALIDATION_WORK"]).resolve()
    evidence = Path(os.environ["STRIXNOVA_VALIDATION_EVIDENCE"]).resolve()
    bundle = bundle.resolve()
    project = work / "business-project"
    project.mkdir()
    installation = work / "managed-installation"
    skills = work / "host-skills"
    calls = []

    def run(label: str, args: list[str]) -> str:
        response = subprocess.run(args, cwd=project, capture_output=True, timeout=180)
        (evidence / (label + ".stdout.txt")).write_bytes(response.stdout)
        (evidence / (label + ".stderr.txt")).write_bytes(response.stderr)
        calls.append({"label": label, "exit_code": response.returncode})
        if response.returncode:
            raise RuntimeError(label + " failed: " + response.stdout.decode("utf-8", errors="replace") + response.stderr.decode("utf-8", errors="replace"))
        return response.stdout.decode("utf-8")

    def assert_no_project_adoption() -> None:
        for relative in ("strixnova-project.yaml", ".strixnova/authority.sqlite3", ".strixnova/delivery-activities.sqlite3"):
            assert not (project / relative).exists(), relative

    arguments = ["--project-dir", str(project), "--installation-root", str(installation), "--skills-dir", str(skills)]
    installed = json.loads(run("initial-install", [sys.executable, "-I", "-S", str(bundle / "install.py"), *arguments]))
    assert installed["ok"] is True
    result = installed["installation"]
    assert result["status"] == "installed"
    assert result["host_loaded_verified"] is False
    assert result["project_adoption_performed"] is False
    assert_no_project_adoption()
    runtime = result["runtime"]
    runtime_python = runtime["python_path"]
    run("pip-check", [runtime_python, "-I", "-m", "pip", "check"])
    run("native-help", [runtime["entrypoint"], "--help"])
    empty_followups = json.loads(run("native-follow-up-query", [runtime["entrypoint"], "status", "--project-dir", str(project), "--follow-ups"]))
    assert empty_followups["follow_ups"]["total"] == 0
    actual = json.loads(run("installed-identity", [runtime_python, "-I", "-c", "import json;from strixnova.runtime_identity import runtime_identity;print(json.dumps(runtime_identity()))"]))
    assert actual["build_sha256"] == runtime["build_sha256"]
    assert actual["skill_sha256"] == runtime["skill_sha256"]

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    copied = 0
    with ZipFile(bundle / manifest["strixnova_wheel"]) as wheel:
        contract = json.loads(wheel.read("strixnova/resources/runtime-compatibility-v1.json"))
        assert actual["formats"] == contract["formats"]
        for name in wheel.namelist():
            if not name.startswith("strixnova/") or name.endswith("/"):
                continue
            relative = name[len("strixnova/"):]
            assert (Path(runtime["package_path"]) / relative).read_bytes() == wheel.read(name), name
            copied += 1
        prefix = "strixnova/resources/agent-skill/strixnova/"
        for name in wheel.namelist():
            if name.startswith(prefix) and not name.endswith("/"):
                assert (skills / "strixnova" / name[len(prefix):]).read_bytes() == wheel.read(name), name

    repeated = json.loads(run("repeat-install", [sys.executable, "-I", "-S", str(bundle / "install.py"), *arguments]))
    assert repeated["installation"]["status"] == "unchanged"
    assert repeated["installation"]["runtime"] == runtime
    assert len(list((installation / "versions").iterdir())) == 1
    assert_no_project_adoption()

    # Installation readiness includes the first actual request, not only help.
    coordination = {
        path.relative_to(project): path.read_bytes()
        for path in (project / ".strixnova/artifacts/maintenance").iterdir()
        if path.is_file()
    }
    identifiers = []
    for label in ("first-intake", "second-intake"):
        request = json.dumps({"title": label, "request": "Create one isolated first-use fixture item."})
        created = json.loads(run(label, [runtime["entrypoint"], "intake", "--project-dir", str(project), "--input", request]))
        assert created["next"]["current_action"]["input_kind"] == "direction"
        identifiers.append(created["next"]["work_item_id"])
    assert len(set(identifiers)) == 2
    resumed = json.loads(run("read-first-item", [runtime["entrypoint"], "next", "--project-dir", str(project), "--work-item-id", identifiers[0]]))
    assert resumed["next"]["work_item_id"] == identifiers[0]
    assert resumed["next"]["work_item_version"] == 1
    assert all((project / relative).read_bytes() == payload for relative, payload in coordination.items())

    receipt = {
        "schema_version": "strixnova.offline-installation-check.v1", "status": "passed",
        "version": runtime["version"], "authority_format": actual["formats"]["authority"],
        "wheel_sha256": hashlib.sha256((bundle / manifest["strixnova_wheel"]).read_bytes()).hexdigest(),
        "build_sha256": runtime["build_sha256"], "skill_sha256": runtime["skill_sha256"],
        "package_files_matched": copied, "calls": calls,
        "installation_count": 1, "repeat_status": "unchanged",
        "installation_created_project_data": False,
        "project_data_created": True, "first_use_item_count": len(identifiers),
        "bootstrap_material_preserved": True, "host_loaded_verified": False,
        "agent_effectiveness_evaluated": False, "formal_release": False,
    }
    (evidence / "offline-installation.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, type=Path)
    print(json.dumps(check(parser.parse_args().bundle)))
