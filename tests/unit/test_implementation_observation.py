from __future__ import annotations

import json
import hashlib
from pathlib import Path
import subprocess
import sys

from jsonschema import Draft202012Validator
import pytest

from strixnova.implementation_observation import (
    ExternalObservationProvider,
    ExternalProviderMaterial,
    IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA,
    IMPLEMENTATION_OBSERVATION_SCHEMA,
    ImplementationObservationError,
    implementation_observation_capabilities,
    observe_implementation,
)
from strixnova.process_supervisor import ProcessLimits, ProcessPolicy


PROJECT_ROOT = Path(__file__).parents[2]


def _write(project: Path, relative_path: str, content: str) -> None:
    path = project / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(project: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments],
        cwd=project,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    ).stdout.strip()


def _scope(
    identifier: str,
    root: str,
    language: str,
    relation_kinds: list[str],
    **options: object,
) -> dict[str, object]:
    return {
        "scope_id": identifier,
        "root": root,
        "languages": [language],
        "required_relation_kinds": relation_kinds,
        "configurations": ["default"],
        "exclusions": [],
        "provider_options": options,
    }


def _provider_script(project: Path, name: str, body: str) -> tuple[str, ...]:
    script = project / name
    script.write_text(body, encoding="utf-8")
    return (sys.executable, str(script))


def _external_provider(
    command: tuple[str, ...],
    *,
    limits: ProcessLimits | None = None,
) -> ExternalObservationProvider:
    executable = Path(command[0]).resolve()
    entry_script = Path(command[1]).resolve()
    return ExternalObservationProvider(
        scope_id="OBSCOPE-BBBBBBBBBBBBBBBB",
        language_id="kotlin",
        provider_id="example.kotlin-provider.v1",
        provider_version="1.0.0",
        command=command,
        materials=(
            ExternalProviderMaterial(
                role="executable",
                path=str(executable),
                sha256=hashlib.sha256(executable.read_bytes()).hexdigest(),
                command_argument_index=0,
            ),
            ExternalProviderMaterial(
                role="entry_script",
                path=str(entry_script),
                sha256=hashlib.sha256(entry_script.read_bytes()).hexdigest(),
                command_argument_index=1,
            ),
        ),
        source_globs=("*.kt", "**/*.kt"),
        process_policy=ProcessPolicy.exact(
            "POLICY-kotlin-observation",
            "test exact Kotlin implementation observation",
            command,
        ),
        limits=limits or ProcessLimits(timeout_seconds=5),
    )


def _successful_provider_body() -> str:
    return """\
import hashlib
import json
from pathlib import Path
import sys

request = json.load(sys.stdin)
paths = request["expected_source_paths"]
result = {
    "schema_version": request["requested_output_schema_version"],
    "scope_id": request["scope"]["scope_id"],
    "language_id": request["language_id"],
    "provider_id": request["provider_id"],
    "provider_version": request["provider_version"],
    "status": "complete",
    "supported_relation_kinds": ["source_import"],
    "nodes": [
        {
            "node_key": path,
            "node_kind": "source_file",
            "path": path,
            "external_name": None,
            "display_name": path,
        }
        for path in paths
    ],
    "relations": [],
    "observed_paths": {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
        for path in paths
    },
    "limitations": [],
    "gaps": [],
}
json.dump(result, sys.stdout, sort_keys=True)
"""


def test_external_provider_contract_is_valid_and_shipped_without_drift() -> None:
    documented = (
        PROJECT_ROOT
        / "docs"
        / "implementation-alignment"
        / "contracts"
        / "implementation-observation-provider-v1.schema.json"
    )
    packaged = (
        PROJECT_ROOT
        / "strixnova"
        / "src"
        / "strixnova"
        / "resources"
        / "implementation-observation-provider-v1.schema.json"
    )
    assert documented.read_bytes() == packaged.read_bytes()
    schema = json.loads(packaged.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    assert schema["$id"] == IMPLEMENTATION_OBSERVATION_PROVIDER_SCHEMA


def test_content_snapshot_is_stable_when_unchanged_working_tree_is_committed(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Tests")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _write(tmp_path, "src.py", "VALUE = 1\n")
    scope = _scope(
        "OBSCOPE-CCCCCCCCCCCCCCCC",
        "src.py",
        "python",
        ["source_import"],
        python_package_name="src",
    )
    working_tree = observe_implementation(tmp_path, [scope])
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "commit unchanged observation input")

    immutable = observe_implementation(tmp_path, [scope], observed_ref="HEAD")

    assert working_tree["observed_revision"] == "working_tree"
    assert immutable["observed_revision"] == _git(tmp_path, "rev-parse", "HEAD")
    assert immutable["source_manifest_sha256"] == working_tree[
        "source_manifest_sha256"
    ]
    assert immutable["observation_snapshot_sha256"] == working_tree[
        "observation_snapshot_sha256"
    ]


def test_public_observation_seam_handles_six_language_ecosystems(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "python_pkg/__init__.py", "from python_pkg.domain import evaluate\n")
    _write(tmp_path, "python_pkg/domain.py", "def evaluate():\n    return []\n")

    _write(tmp_path, "rust/Cargo.toml", '[package]\nname = "demo"\nversion = "0.1.0"\n')
    _write(tmp_path, "rust/src/lib.rs", "mod domain;\nuse crate::domain::evaluate;\n")
    _write(tmp_path, "rust/src/domain.rs", "pub fn evaluate() {}\n")

    _write(tmp_path, "go/go.mod", "module example.com/demo\n\ngo 1.22\n")
    _write(tmp_path, "go/main.go", 'package main\nimport "example.com/demo/pkg"\nfunc main() {}\n')
    _write(tmp_path, "go/pkg/value.go", "package pkg\n")

    _write(tmp_path, "ts/a.ts", 'import { value } from "./b";\nexport { value };\n')
    _write(tmp_path, "ts/b.ts", "export const value = 1;\n")
    _write(tmp_path, "ts/package.json", '{"dependencies":{"zod":"^4.0.0"}}\n')

    _write(tmp_path, "cs/A.cs", "using System;\nnamespace Demo;\n")
    _write(
        tmp_path,
        "cs/A.csproj",
        '<Project Sdk="Microsoft.NET.Sdk"><ItemGroup><PackageReference Include="Serilog" Version="4.0.0" /></ItemGroup></Project>\n',
    )

    _write(tmp_path, "cpp/a.cpp", '#include "b.hpp"\nint main() { return 0; }\n')
    _write(tmp_path, "cpp/b.hpp", "#pragma once\n")
    _write(
        tmp_path,
        "cpp/CMakeLists.txt",
        "add_library(core b.hpp)\nadd_executable(app a.cpp)\ntarget_link_libraries(app PRIVATE core)\n",
    )

    scopes = [
        _scope(
            "OBSCOPE-1111111111111111",
            "python_pkg",
            "python",
            ["source_import"],
            python_package_name="python_pkg",
        ),
        _scope(
            "OBSCOPE-2222222222222222",
            "rust",
            "rust",
            ["module_reference", "package_dependency"],
        ),
        _scope(
            "OBSCOPE-3333333333333333",
            "go",
            "go",
            ["package_import", "module_dependency"],
        ),
        _scope(
            "OBSCOPE-4444444444444444",
            "ts",
            "typescript",
            ["source_import", "package_dependency"],
        ),
        _scope(
            "OBSCOPE-5555555555555555",
            "cs",
            "csharp",
            ["namespace_reference", "package_dependency"],
        ),
        _scope(
            "OBSCOPE-6666666666666666",
            "cpp",
            "cpp",
            ["source_include", "build_target_dependency"],
        ),
    ]

    observed = observe_implementation(tmp_path, scopes)

    assert observed["schema_version"] == IMPLEMENTATION_OBSERVATION_SCHEMA
    assert observed["semantic_content_machine_proven"] is False
    assert {item["language_id"] for item in observed["coverage"]} == {
        "python",
        "rust",
        "go",
        "typescript",
        "csharp",
        "cpp",
    }
    statuses = {
        item["language_id"]: item["status"] for item in observed["coverage"]
    }
    assert statuses == {
        "python": "complete",
        "rust": "complete",
        "go": "complete",
        "typescript": "complete",
        "csharp": "partial",
        "cpp": "partial",
    }
    assert any(
        item["relation_kind"] == "source_import"
        and item["resolution_status"] == "resolved_internal"
        for item in observed["relations"]
    )
    assert any(
        item["relation_kind"] == "module_reference"
        and item["resolution_status"] == "resolved_internal"
        for item in observed["relations"]
    )
    assert any(
        item["relation_kind"] == "package_import"
        and item["resolution_status"] == "resolved_internal"
        for item in observed["relations"]
    )
    assert any(
        item["relation_kind"] == "project_reference"
        or item["relation_kind"] == "package_dependency"
        for item in observed["relations"]
    )
    assert any(
        item["relation_kind"] == "build_target_dependency"
        and item["resolution_status"] == "resolved_internal"
        for item in observed["relations"]
    )


def test_observation_is_deterministic_for_the_same_working_tree(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pkg/__init__.py", "from pkg.value import VALUE\n")
    _write(tmp_path, "pkg/value.py", "VALUE = 1\n")
    scope = _scope(
        "OBSCOPE-7777777777777777",
        "pkg",
        "python",
        ["source_import"],
        python_package_name="pkg",
    )

    first = observe_implementation(tmp_path, [scope])
    second = observe_implementation(tmp_path, [scope])

    assert first == second
    assert first["overall_coverage_status"] == "complete"
    assert first["observed_paths"]


def test_python_root_scope_resolves_sibling_and_nested_package_imports(tmp_path: Path) -> None:
    _write(tmp_path, "main.py", "import helper\nfrom pkg import child\n")
    _write(tmp_path, "helper.py", "VALUE = 1\n")
    _write(tmp_path, "pkg/__init__.py", "from . import child\n")
    _write(tmp_path, "pkg/child.py", "VALUE = 2\n")
    _write(tmp_path, "tests/broken.py", "not valid Python !!!\n")
    scope = _scope("OBSCOPE-1212121212121212", ".", "python", ["source_import"])
    scope["exclusions"] = ["tests/**"]
    observed = observe_implementation(tmp_path, [scope])
    nodes = {item["node_id"]: item for item in observed["nodes"]}
    edges = {
        (nodes[item["source_node_id"]]["path"], nodes[item["target_node_id"]]["path"])
        for item in observed["relations"]
    }
    assert ("main.py", "helper.py") in edges
    assert ("main.py", "pkg/child.py") in edges
    assert ("pkg/__init__.py", "pkg/child.py") in edges
    assert "tests/broken.py" not in observed["observed_paths"]
    assert all(not record["gaps"] for record in observed["coverage"])


def test_python_from_package_import_resolves_the_child_module(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pkg/__init__.py", "from . import child\n")
    _write(tmp_path, "pkg/child.py", "VALUE = 1\n")

    observed = observe_implementation(
        tmp_path,
        [
            _scope(
                "OBSCOPE-1212121212121212",
                "pkg",
                "python",
                ["source_import"],
                python_package_name="pkg",
            )
        ],
    )

    nodes = {item["node_id"]: item for item in observed["nodes"]}
    relation = next(item for item in observed["relations"])
    assert relation["observed_name"] == "pkg.child"
    assert nodes[relation["target_node_id"]]["path"] == "pkg/child.py"


def test_go_observation_resolves_multiple_modules_and_local_replace(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "repo/go.work",
        "go 1.22\nuse (\n  ./service\n  ./shared\n)\n",
    )
    _write(
        tmp_path,
        "repo/service/go.mod",
        "module example.com/service\n\n"
        "go 1.22\n\n"
        "require example.com/shared v0.0.0\n"
        "replace example.com/shared => ../shared\n",
    )
    _write(
        tmp_path,
        "repo/service/main.go",
        'package main\nimport "example.com/shared/pkg"\nfunc main() {}\n',
    )
    _write(
        tmp_path,
        "repo/shared/go.mod",
        "module example.com/shared\n\ngo 1.22\n",
    )
    _write(tmp_path, "repo/shared/pkg/value.go", "package pkg\n")

    observed = observe_implementation(
        tmp_path,
        [
            _scope(
                "OBSCOPE-1313131313131313",
                "repo",
                "go",
                ["package_import", "module_dependency"],
            )
        ],
    )

    nodes = {item["node_id"]: item for item in observed["nodes"]}
    assert observed["overall_coverage_status"] == "complete"
    internal = [
        item
        for item in observed["relations"]
        if item["resolution_status"] == "resolved_internal"
    ]
    assert {
        nodes[item["target_node_id"]]["path"] for item in internal
    } >= {"repo/shared/go.mod", "repo/shared/pkg"}


def test_typescript_workspace_packages_remain_internal(
    tmp_path: Path,
) -> None:
    _write(
        tmp_path,
        "web/package.json",
        '{"private":true,"workspaces":["packages/*"]}\n',
    )
    _write(
        tmp_path,
        "web/packages/a/package.json",
        '{"name":"@demo/a","dependencies":{"@demo/b":"workspace:*"}}\n',
    )
    _write(
        tmp_path,
        "web/packages/a/index.ts",
        'import { value } from "@demo/b";\nexport { value };\n',
    )
    _write(
        tmp_path,
        "web/packages/b/package.json",
        '{"name":"@demo/b"}\n',
    )
    _write(tmp_path, "web/packages/b/index.ts", "export const value = 1;\n")

    observed = observe_implementation(
        tmp_path,
        [
            _scope(
                "OBSCOPE-1414141414141414",
                "web",
                "typescript",
                ["source_import", "package_dependency"],
            )
        ],
    )

    assert observed["overall_coverage_status"] == "complete"
    workspace_relations = [
        item
        for item in observed["relations"]
        if item["observed_name"] == "@demo/b"
    ]
    assert workspace_relations
    assert all(
        item["resolution_status"] == "resolved_internal"
        for item in workspace_relations
    )


def test_cmake_targets_on_one_file_keep_distinct_node_identity(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "cpp/a.cpp", "int main() { return 0; }\n")
    _write(tmp_path, "cpp/b.hpp", "#pragma once\n")
    _write(
        tmp_path,
        "cpp/CMakeLists.txt",
        "add_library(core b.hpp)\n"
        "add_executable(app a.cpp)\n"
        "target_link_libraries(app PRIVATE core)\n",
    )

    observed = observe_implementation(
        tmp_path,
        [
            _scope(
                "OBSCOPE-1515151515151515",
                "cpp",
                "cpp",
                ["source_include", "build_target_dependency"],
            )
        ],
    )

    relation = next(
        item
        for item in observed["relations"]
        if item["relation_kind"] == "build_target_dependency"
    )
    nodes = {item["node_id"]: item for item in observed["nodes"]}
    assert relation["source_node_id"] != relation["target_node_id"]
    assert nodes[relation["source_node_id"]]["display_name"] == "app"
    assert nodes[relation["target_node_id"]]["display_name"] == "core"
    assert nodes[relation["source_node_id"]]["path"] == nodes[
        relation["target_node_id"]
    ]["path"]


@pytest.mark.parametrize(
    ("language", "root", "expected_status", "expected_code"),
    [
        ("kotlin", "src", "unavailable", "language_provider_unavailable"),
        ("python", "missing", "failed", "observation_scope_unavailable"),
    ],
)
def test_unavailable_provider_or_scope_never_becomes_empty_success(
    tmp_path: Path,
    language: str,
    root: str,
    expected_status: str,
    expected_code: str,
) -> None:
    _write(tmp_path, "src/readme.txt", "not source\n")
    scope = _scope(
        "OBSCOPE-8888888888888888",
        root,
        language,
        ["source_import"],
    )

    observed = observe_implementation(tmp_path, [scope])

    assert observed["overall_coverage_status"] == expected_status
    assert observed["relations"] == []
    assert expected_code in {
        gap["code"] for gap in observed["coverage"][0]["gaps"]
    }


def test_dynamic_or_unresolved_relationships_remain_visible(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "pkg/__init__.py", "from importlib import import_module\nimport_module(name)\n")
    _write(tmp_path, "web/a.ts", 'import value from "./missing";\n')
    scopes = [
        _scope(
            "OBSCOPE-9999999999999999",
            "pkg",
            "python",
            ["source_import"],
            python_package_name="pkg",
        ),
        _scope(
            "OBSCOPE-AAAAAAAAAAAAAAAA",
            "web",
            "typescript",
            ["source_import"],
        ),
    ]

    observed = observe_implementation(tmp_path, scopes)

    assert observed["overall_coverage_status"] == "partial"
    gap_codes = {
        gap["code"]
        for item in observed["coverage"]
        for gap in item["gaps"]
    }
    assert "python_dynamic_import" in gap_codes
    assert "typescript_relative_import_unresolved" in gap_codes
    assert any(
        item["resolution_status"] == "unresolved"
        for item in observed["relations"]
    )


def test_capability_matrix_does_not_claim_complete_project_semantics() -> None:
    capabilities = implementation_observation_capabilities()

    assert {item["language_id"] for item in capabilities["languages"]} == {
        "python",
        "rust",
        "go",
        "typescript",
        "csharp",
        "cpp",
    }
    assert all(
        item["complete_project_semantics_without_configuration"] is False
        for item in capabilities["languages"]
    )
    assert capabilities["semantic_content_machine_proven"] is False


def test_authorized_external_provider_extends_language_support(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    command = _provider_script(
        tmp_path,
        "provider.py",
        _successful_provider_body(),
    )
    scope = _scope(
        "OBSCOPE-BBBBBBBBBBBBBBBB",
        "kotlin",
        "kotlin",
        ["source_import"],
    )

    observed = observe_implementation(
        tmp_path,
        [scope],
        external_providers=[_external_provider(command)],
        external_execution_authorized=True,
    )

    assert observed["overall_coverage_status"] == "complete"
    assert observed["coverage"][0]["execution_mode"] == "authorized_tool"
    assert observed["coverage"][0]["source_file_count"] == 1
    assert observed["nodes"][0]["path"] == "kotlin/Main.kt"
    assert observed["provider_receipts"][0]["policy_id"] == (
        "POLICY-kotlin-observation"
    )
    assert len(observed["provider_receipts"][0]["command_sha256"]) == 64
    assert len(observed["provider_receipts"][0]["request_sha256"]) == 64


def test_external_provider_node_keys_distinguish_logical_nodes_on_one_path(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    body = """\
import hashlib
import json
from pathlib import Path
import sys

request = json.load(sys.stdin)
path = request["expected_source_paths"][0]
result = {
    "schema_version": request["requested_output_schema_version"],
    "scope_id": request["scope"]["scope_id"],
    "language_id": request["language_id"],
    "provider_id": request["provider_id"],
    "provider_version": request["provider_version"],
    "status": "complete",
    "supported_relation_kinds": ["source_import"],
    "nodes": [
        {
            "node_key": "source",
            "node_kind": "source_file",
            "path": path,
            "external_name": None,
            "display_name": "source",
        },
        {
            "node_key": "logical-target",
            "node_kind": "logical_component",
            "path": path,
            "external_name": None,
            "display_name": "logical target",
        },
    ],
    "relations": [
        {
            "source_node_key": "source",
            "target_node_key": "logical-target",
            "relation_kind": "source_import",
            "observed_name": "logical-target",
            "resolution_status": "resolved_internal",
            "conditions": [],
            "evidence_locations": [{"path": path, "line": 1}],
        }
    ],
    "observed_paths": {
        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    },
    "limitations": [],
    "gaps": [],
}
json.dump(result, sys.stdout, sort_keys=True)
"""
    command = _provider_script(tmp_path, "provider.py", body)
    scope = _scope(
        "OBSCOPE-BBBBBBBBBBBBBBBB",
        "kotlin",
        "kotlin",
        ["source_import"],
    )

    observed = observe_implementation(
        tmp_path,
        [scope],
        external_providers=[_external_provider(command)],
        external_execution_authorized=True,
    )

    assert len(observed["nodes"]) == 2
    relation = observed["relations"][0]
    assert relation["source_node_id"] != relation["target_node_id"]


def test_external_provider_is_not_run_without_call_authorization(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    marker = tmp_path / "provider-ran"
    command = _provider_script(
        tmp_path,
        "provider.py",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
    )
    scope = _scope(
        "OBSCOPE-BBBBBBBBBBBBBBBB",
        "kotlin",
        "kotlin",
        ["source_import"],
    )

    observed = observe_implementation(
        tmp_path,
        [scope],
        external_providers=[_external_provider(command)],
    )

    assert observed["overall_coverage_status"] == "unavailable"
    assert observed["coverage"][0]["execution_mode"] == "not_run"
    assert observed["coverage"][0]["gaps"][0]["code"] == (
        "provider_execution_not_authorized"
    )
    assert not marker.exists()


def test_external_provider_is_not_run_after_a_confirmed_material_changes(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    marker = tmp_path / "provider-ran"
    command = _provider_script(
        tmp_path,
        "provider.py",
        _successful_provider_body(),
    )
    provider = _external_provider(command)
    Path(command[1]).write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
        encoding="utf-8",
    )

    observed = observe_implementation(
        tmp_path,
        [
            _scope(
                "OBSCOPE-BBBBBBBBBBBBBBBB",
                "kotlin",
                "kotlin",
                ["source_import"],
            )
        ],
        external_providers=[provider],
        external_execution_authorized=True,
    )

    assert observed["overall_coverage_status"] == "failed"
    assert observed["coverage"][0]["execution_mode"] == "not_run"
    assert observed["coverage"][0]["gaps"][0]["code"] == (
        "provider_material_changed"
    )
    assert not marker.exists()


def test_external_provider_request_limit_is_a_typed_failed_observation(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    marker = tmp_path / "provider-ran"
    command = _provider_script(
        tmp_path,
        "provider.py",
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('ran')\n",
    )
    scope = _scope(
        "OBSCOPE-BBBBBBBBBBBBBBBB",
        "kotlin",
        "kotlin",
        ["source_import"],
    )

    observed = observe_implementation(
        tmp_path,
        [scope],
        external_providers=[
            _external_provider(
                command,
                limits=ProcessLimits(max_input_bytes=1),
            )
        ],
        external_execution_authorized=True,
    )

    assert observed["overall_coverage_status"] == "failed"
    assert observed["coverage"][0]["gaps"][0]["code"] == (
        "provider_request_input_limit"
    )
    assert not marker.exists()


@pytest.mark.parametrize(
    ("body", "limits", "expected_code"),
    [
        ("raise SystemExit(7)\n", None, "provider_process_nonzero_exit"),
        ("print('not json')\n", None, "provider_output_invalid_json"),
        (
            "import time\ntime.sleep(5)\n",
            ProcessLimits(timeout_seconds=0.05, cleanup_timeout_seconds=1),
            "provider_process_timeout",
        ),
    ],
)
def test_external_provider_failures_never_become_empty_success(
    tmp_path: Path,
    body: str,
    limits: ProcessLimits | None,
    expected_code: str,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    command = _provider_script(tmp_path, "provider.py", body)
    scope = _scope(
        "OBSCOPE-BBBBBBBBBBBBBBBB",
        "kotlin",
        "kotlin",
        ["source_import"],
    )

    observed = observe_implementation(
        tmp_path,
        [scope],
        external_providers=[_external_provider(command, limits=limits)],
        external_execution_authorized=True,
    )

    assert observed["overall_coverage_status"] == "failed"
    assert observed["relations"] == []
    assert observed["coverage"][0]["gaps"][0]["code"] == expected_code


def test_external_provider_output_must_cover_exact_declared_sources(
    tmp_path: Path,
) -> None:
    _write(tmp_path, "kotlin/Main.kt", "fun main() = Unit\n")
    incomplete = _successful_provider_body().replace(
        '"observed_paths": {\n        path: hashlib.sha256(Path(path).read_bytes()).hexdigest()\n        for path in paths\n    },',
        '"observed_paths": {},',
    )
    command = _provider_script(tmp_path, "provider.py", incomplete)
    scope = _scope(
        "OBSCOPE-BBBBBBBBBBBBBBBB",
        "kotlin",
        "kotlin",
        ["source_import"],
    )

    observed = observe_implementation(
        tmp_path,
        [scope],
        external_providers=[_external_provider(command)],
        external_execution_authorized=True,
    )

    assert observed["overall_coverage_status"] == "failed"
    assert observed["coverage"][0]["gaps"][0]["code"] == (
        "provider_output_contract_invalid"
    )


def test_invalid_scope_is_rejected_before_any_observation(tmp_path: Path) -> None:
    with pytest.raises(ImplementationObservationError) as captured:
        observe_implementation(
            tmp_path,
            [
                {
                    "scope_id": "scope",
                    "root": "src",
                    "languages": ["python"],
                    "required_relation_kinds": ["source_import"],
                    "configurations": ["default"],
                    "exclusions": [],
                }
            ],
        )

    assert any("scope_id" in issue for issue in captured.value.issues)
