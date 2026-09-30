from __future__ import annotations

from importlib.resources import files
import json

from jsonschema import Draft202012Validator
import pytest
from referencing import Registry, Resource

from strixnova import engineering_governance
from strixnova.current_action import current_action_for
from strixnova.engineering_governance import (
    compile_engineering_plan,
    validate_assessment,
)
from strixnova.project_authority_progress import (
    authority_confirmation_challenge,
    project_authority_plan_ref,
)
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.project_engineering_policy import load_base_governance_profile
from strixnova.process_supervisor import (
    MAX_PROCESS_INPUT_BYTES,
    MAX_PROCESS_OUTPUT_BYTES,
)
from strixnova.workflow_authority import AUTHORITY_SCHEMA_VERSION, WorkflowAuthority
from tests.support.governance_assessment import (
    assessment_fixture,
    direction_fixture,
)


def _runtime_contract_registry() -> Registry:
    root = files("strixnova.resources")
    entries = []
    for resource_path in root.iterdir():
        if not resource_path.name.endswith(".schema.json"):
            continue
        contents = json.loads(resource_path.read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents)
        entries.append((resource_path.name, resource))
        entries.append((contents["$id"], resource))
    return Registry().with_resources(entries)


def _accept_current_candidate(
    authority: WorkflowAuthority,
    work_item_id: str,
) -> dict[str, str]:
    challenge = authority.get(work_item_id)["current_action"][
        "confirmation_challenge"
    ]
    return {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": "I accept the displayed candidate.",
        "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
    }


def test_every_shipped_json_contract_parses_and_every_schema_is_valid() -> None:
    root = files("strixnova.resources")
    resources = sorted(
        item for item in root.iterdir() if item.name.endswith(".json")
    )

    assert resources
    for resource in resources:
        value = json.loads(resource.read_text(encoding="utf-8"))
        assert isinstance(value, dict), resource.name
        if resource.name.endswith(".schema.json"):
            Draft202012Validator.check_schema(value)
            assert isinstance(value.get("$id"), str) and value["$id"]


def test_external_provider_resource_ceilings_match_every_runtime_surface() -> None:
    root = files("strixnova.resources")
    for name in (
        "engineering-assessment-v1.schema.json",
        "engineering-plan-v1.schema.json",
    ):
        schema = json.loads(root.joinpath(name).read_text(encoding="utf-8"))
        limits = schema["$defs"]["external_observation_limits"]
        assert limits["properties"]["max_input_bytes"]["maximum"] == (
            MAX_PROCESS_INPUT_BYTES
        )
        assert limits["properties"]["max_output_bytes"]["maximum"] == (
            MAX_PROCESS_OUTPUT_BYTES
        )
    assert engineering_governance._MAX_PROVIDER_INPUT_BYTES == (
        MAX_PROCESS_INPUT_BYTES
    )
    assert engineering_governance._MAX_PROVIDER_OUTPUT_BYTES == (
        MAX_PROCESS_OUTPUT_BYTES
    )


def test_only_current_first_version_contracts_are_shipped() -> None:
    resources = list(files("strixnova.resources").iterdir())
    schemas = [item for item in resources if item.name.endswith(".schema.json")]
    assert schemas
    for schema in schemas:
        assert schema.name.endswith("-v1.schema.json"), schema.name
        identity = json.loads(schema.read_text(encoding="utf-8"))["$id"]
        assert identity.startswith("strixnova.") and identity.endswith(".v1"), identity
    assert not any(item.name.startswith(("agent-run-", "product-contract-", "domain-implementation-alignment-")) for item in resources)


def test_alignment_application_input_contracts_resolve_against_current_authority() -> None:
    root = files("strixnova.resources")
    registry = _runtime_contract_registry()
    preparation_schema = json.loads(
        root.joinpath(
            "implementation-alignment-preparation-request-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    preparation_validator = Draft202012Validator(
        preparation_schema,
        registry=registry,
    )
    revision = {
        "schema_version": (
            "strixnova.implementation-alignment-preparation-request.v1"
        ),
        "alignment_revision_id": "ALIGNREV-2222222222222222",
        "supersedes_revision_id": "ALIGNREV-1111111111111111",
    }
    assert preparation_validator.is_valid(revision)
    assert not preparation_validator.is_valid(
        {**revision, "observation_scopes": []}
    )

    decisions_schema = json.loads(
        root.joinpath(
            "implementation-alignment-candidate-decisions-v1.schema.json"
        ).read_text(encoding="utf-8")
    )
    decisions_validator = Draft202012Validator(
        decisions_schema,
        registry=registry,
    )
    digest = "a" * 64
    assert decisions_validator.is_valid(
        {
            "schema_version": (
                "strixnova.implementation-alignment-candidate-decisions.v1"
            ),
            "preparation_ref": {
                "schema_version": (
                    "strixnova.implementation-alignment-preparation-ref.v1"
                ),
                "artifact_kind": "preparations",
                "artifact_id": "ALIGNPREP-AAAAAAAAAAAAAAAA",
                "path": (
                    ".strixnova/artifacts/implementation-alignment/"
                    f"preparations/{digest}.json"
                ),
                "content_sha256": digest,
            },
            "decisions": [],
            "deviations": [],
            "unresolved_items": [],
        }
    )


def test_fresh_work_item_uses_the_agent_run_free_authority_contract(
    tmp_path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(
        title="新合同事项",
        raw_request="验证废止合同不再进入当前权威。",
    )

    assert AUTHORITY_SCHEMA_VERSION == "1"
    assert item["schema_version"] == "strixnova.work-item.v1"
    assert authority.get(item["work_item_id"])["current_action"][
        "schema_version"
    ] == "strixnova.current-action.v1"
    assert "agent_run" not in item["data"]


def test_fresh_runtime_work_item_matches_the_shipped_schema(tmp_path) -> None:
    root = files("strixnova.resources")
    work_item_schema = json.loads(
        root.joinpath("work-item-v1.schema.json").read_text(encoding="utf-8")
    )
    engineering_schema = work_item_schema["properties"]["data"]["properties"][
        "engineering"
    ]
    assert engineering_schema["additionalProperties"] is False
    assert engineering_schema["properties"]["assessment"]["oneOf"][0]["$ref"] == (
        "engineering-assessment-v1.schema.json"
    )
    assert engineering_schema["properties"]["plan"]["oneOf"][0]["$ref"] == (
        "engineering-plan-v1.schema.json"
    )

    authority = WorkflowAuthority(tmp_path)
    created = authority.create(
        title="运行实例合同",
        raw_request="验证真实 WorkItem 与 CurrentAction 符合公开格式。",
    )
    runtime_item = authority.get(created["work_item_id"])

    Draft202012Validator(
        work_item_schema,
        registry=_runtime_contract_registry(),
    ).validate(runtime_item)


@pytest.mark.parametrize("with_examples", [False, True])
def test_runtime_work_item_with_current_assessment_and_plan_matches_shipped_schema(
    tmp_path,
    with_examples,
) -> None:
    direction = direction_fixture()
    if with_examples:
        from tests.support.behavior_examples import behavior
        direction["acceptance"][0]["behavior"] = behavior()
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(
        title="完整工程数据合同",
        raw_request="验证当前工程评估、方案与事项合同完整衔接。",
    )
    work_item_id = item["work_item_id"]
    item = authority.transition(
        work_item_id,
        "submit_direction",
        {"direction": direction, "ready_for_confirmation": True},
        expected_version=item["version"],
    )
    item = authority.transition(
        work_item_id,
        "confirm_direction",
        _accept_current_candidate(authority, work_item_id),
        expected_version=item["version"],
    )
    direction_version = item["data"]["direction_confirmation"][
        "direction_version"
    ]
    assessment_source = assessment_fixture(
        tmp_path,
        work_item_id=work_item_id,
        direction_version=direction_version,
    )
    if with_examples:
        from tests.support.behavior_examples import case_config
        assessment_source["verification_commands"][0]["case_report"] = case_config(["test_behavior.py::test_other_remains"], bound=False)
    candidate_context = ProjectAuthorityConsistency(
        tmp_path
    ).engineering_candidate_context(assessment_source)
    profile = load_base_governance_profile()
    assessment = validate_assessment(
        assessment_source,
        project_dir=tmp_path,
        candidate_context=candidate_context,
        work_item_id=work_item_id,
        direction=direction,
        direction_version=direction_version,
        profile=profile,
    )
    plan = compile_engineering_plan(
        assessment_source,
        project_dir=tmp_path,
        candidate_context=candidate_context,
        work_item_id=work_item_id,
        direction=direction,
        direction_version=direction_version,
        profile=profile,
    )
    item = authority.transition(
        work_item_id,
        "submit_engineering_assessment",
        {"assessment": assessment, "plan": plan},
        expected_version=item["version"],
    )

    runtime_item = authority.get(work_item_id)
    schema = json.loads(
        files("strixnova.resources")
        .joinpath("work-item-v1.schema.json")
        .read_text(encoding="utf-8")
    )

    assert item["data"]["engineering"]["assessment"]["schema_version"] == (
        "strixnova.engineering-assessment.v1"
    )
    assert item["data"]["engineering"]["plan"]["schema_version"] == (
        "strixnova.engineering-plan.v1"
    )
    Draft202012Validator(
        schema,
        registry=_runtime_contract_registry(),
    ).validate(runtime_item)


def test_authority_current_action_matches_the_shipped_schema() -> None:
    root = files("strixnova.resources")
    schema = json.loads(
        root.joinpath("current-action-v1.schema.json").read_text(
            encoding="utf-8"
        )
    )
    item = {
        "work_item_id": "WI-SCHEMA-AUTHORITY",
        "status": "implementing",
        "version": 7,
        "data": {
            "engineering": {
                "plan_confirmation": {
                    "accepted": True,
                    "candidate_fingerprint": "sha256:" + "2" * 64,
                },
                "plan": {
                    "plan_id": "PLAN-EA-1111111111111111-R1",
                    "assessment_ref": {
                        "work_item_id": "WI-SCHEMA-AUTHORITY",
                        "assessment_id": "EA-1111111111111111",
                        "assessment_revision": 1,
                    },
                    "operations": [
                        {
                            "path": "docs/product/definition.yaml",
                            "long_lived_artifact": {
                                "artifact_id": "PRODUCT-1111111111111111",
                                "artifact_type": "product_governance",
                            },
                        }
                    ],
                    "implementation_slices": [
                        {
                            "slice_id": "SLICE-001",
                            "operation_refs": ["operations[0]"],
                            "depends_on": [],
                            "verification_command_ids": [],
                        }
                    ],
                    "verification_commands": [],
                }
            },
            "git": {"work_ref": "strixnova/WI-SCHEMA-AUTHORITY"},
            "verifications": [],
            "implementation_slice_completions": [],
            "project_authority_presentations": [],
            "project_authority_decisions": [],
            "blockers": [],
        },
    }

    action = current_action_for(item)

    assert action is not None
    Draft202012Validator(schema).validate(action)

    candidate = {
        "schema_version": "strixnova.project-authority-candidate.v1",
        "authority_kind": "product_definition",
        "artifact_id": "PRODUCT-1111111111111111",
        "revision_id": "REVISION-1111111111111111",
        "path": "docs/product/definition.yaml",
        "owner_id": "OWNER-1111111111111111",
        "plan_ref": project_authority_plan_ref(item),
        "upstream_authority_refs": [],
        "governed_paths": ["docs/product/definition.yaml"],
        "content_sha256": "1" * 64,
        "semantic_content_machine_proven": False,
    }
    challenge = authority_confirmation_challenge(item, candidate)
    item["version"] += 1
    item["data"]["project_authority_presentations"] = [
        {
            "schema_version": "strixnova.project-authority-presentation.v1",
            "authority_kind": "product_definition",
            "candidate": candidate,
            "confirmation_challenge": challenge,
            "presented_at": "2026-08-28T00:00:00Z",
            "presented_at_work_item_version": item["version"],
            "semantic_content_machine_proven": False,
        }
    ]

    review_action = current_action_for(item)

    assert review_action is not None
    assert review_action["action_type"] == "review_project_authority_candidates"
    Draft202012Validator(schema).validate(review_action)


def test_preparation_can_use_the_current_repository_but_persisted_scopes_are_explicit() -> None:
    root = files("strixnova.resources")
    registry = _runtime_contract_registry()
    scope = {
        "scope_id": "OBSCOPE-1111111111111111", "root": "src.py",
        "languages": ["python"], "required_relation_kinds": ["source_import"],
        "configurations": ["default"], "exclusions": [],
        "provider_options": {"python_package_name": "src"},
    }
    request = {
        "schema_version": "strixnova.implementation-alignment-preparation-request.v1",
        "alignment_revision_id": "ALIGNREV-1111111111111111", "supersedes_revision_id": None,
        "observation_scopes": [scope],
        "governed_source_scopes": [{
            "scope_id": scope["scope_id"], "root": "src.py", "included_path_patterns": ["."],
            "included_node_kinds": ["source_file"], "exclusion_policy": "No implicit exclusions",
        }],
    }
    contract = json.loads(root.joinpath("implementation-alignment-preparation-request-v1.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator(contract, registry=registry).validate(request)
    persisted = {"$ref": "project-implementation-alignment-v1.schema.json#/$defs/observation_scope"}
    validator = Draft202012Validator(persisted, registry=registry)
    assert not validator.is_valid(scope)
    validator.validate({**scope, "repository_id": "REPO-1111111111111111"})
