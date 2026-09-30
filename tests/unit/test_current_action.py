from strixnova.current_action import (
    current_action_for,
    direction_revision_action_for,
)
from strixnova.project_authority_progress import (
    _candidate_review_ref,
    _canonical_sha256,
    authority_confirmation_challenge,
    project_authority_plan_ref,
)


def _implementing(receipt: dict) -> dict:
    return {
        "work_item_id": "WI-CURRENT-ACTION",
        "status": "implementing",
        "version": 7,
        "data": {
            "engineering": {
                "plan": {
                    "verification_commands": [
                        {"command_id": "VC-001"}
                    ]
                }
            },
            "git": {"work_ref": "strixnova/WI-CURRENT-ACTION"},
            "verifications": [receipt],
            "blockers": [],
        },
    }


def test_current_action_requests_the_pending_receipt_and_its_execution_context() -> None:
    action = current_action_for(
        _implementing(
            {
                "receipt_id": "VR-001",
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": None,
            }
        )
    )

    assert action is not None
    assert action["action_type"] == "assess_verification_change"
    assert action["intent"] == "verify"
    assert action["record_refs"] == ["verifications:VR-001", "engineering.execution_context"]


def test_current_action_names_the_exact_confirmed_command_record() -> None:
    item = _implementing({})
    item["data"]["verifications"] = []

    action = current_action_for(item)

    assert action is not None
    assert action["action_type"] == "implement_and_verify"
    assert action["record_refs"] == [
        "engineering.plan.verification_commands",
        "git",
        "engineering.execution_context",
        "engineering.review_subject",
    ]


def test_direction_context_drift_projects_one_recoverable_direction_action() -> None:
    item = {
        "work_item_id": "WI-DIRECTION-DRIFT",
        "status": "needs_engineering_assessment",
        "version": 4,
        "data": {
            "direction": {"goal": "保留原目标"},
            "direction_confirmation": {"accepted": True},
            "engineering": {"plan": {"plan_id": "PLAN-OLD"}},
            "blockers": [],
        },
    }

    action = direction_revision_action_for(
        item,
        ["方向决定绑定的产品上下文已经过期，请重新读取当前决定上下文"],
    )

    assert action["action_type"] == "revise_direction"
    assert action["actor"] == "coding_agent"
    assert action["input_kind"] == "direction"
    assert action["record_refs"] == [
        "request",
        "direction",
        "direction_confirmation",
        "engineering.plan",
        "project.direction_context",
    ]
    assert action["blocking_facts"] == [
        "direction_context_invalid:方向决定绑定的产品上下文已经过期，请重新读取当前决定上下文"
    ]


def test_current_action_guides_missing_upstream_authority_before_slice() -> None:
    item = _implementing({})
    item["data"]["verifications"] = []
    item["data"]["engineering"].update(
        {
            "plan_confirmation": {
                "accepted": True,
                "candidate_fingerprint": "sha256:" + "2" * 64,
            },
            "plan": {
                "plan_id": "PLAN-EA-2222222222222222-R1",
                "assessment_ref": {
                    "work_item_id": item["work_item_id"],
                    "assessment_id": "EA-2222222222222222",
                    "assessment_revision": 1,
                },
                "operations": [
                    {
                        "path": "docs/product/definition.yaml",
                        "long_lived_artifact": {
                            "artifact_id": "PRODUCT-2222222222222222",
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
            },
        }
    )

    action = current_action_for(item)

    assert action is not None
    assert action["action_type"] == "author_project_authority_candidate"
    assert action["intent"] == "authority"
    assert action["authority_kind"] == "product_definition"
    assert action["blocking_facts"] == [
        "project_authority_decision_required:product_definition"
    ]


def test_current_action_separates_candidate_presentation_from_bundle_confirmation() -> None:
    item = _implementing({})
    item["data"]["verifications"] = []
    item["data"]["engineering"].update(
        {
            "plan_confirmation": {
                "accepted": True,
                "candidate_fingerprint": "sha256:" + "2" * 64,
            },
            "plan": {
                "plan_id": "PLAN-EA-2222222222222222-R1",
                "assessment_ref": {
                    "work_item_id": item["work_item_id"],
                    "assessment_id": "EA-2222222222222222",
                    "assessment_revision": 1,
                },
                "operations": [
                    {
                        "path": "docs/product/definition.yaml",
                        "long_lived_artifact": {
                            "artifact_id": "PRODUCT-2222222222222222",
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
            },
        }
    )
    candidate = {
        "schema_version": "strixnova.project-authority-candidate.v1",
        "authority_kind": "product_definition",
        "artifact_id": "PRODUCT-2222222222222222",
        "revision_id": "REVISION-2222222222222222",
        "path": "docs/product/definition.yaml",
        "owner_id": "OWNER-2222222222222222",
        "plan_ref": project_authority_plan_ref(item),
        "upstream_authority_refs": [],
        "governed_paths": ["docs/product/definition.yaml"],
        "content_sha256": "2" * 64,
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

    action = current_action_for(item)

    assert action is not None
    assert action["action_type"] == "review_project_authority_candidates"
    assert action["intent"] == "authority"
    assert action["authority_kinds"] == ["product_definition"]
    assert "confirmation_challenges" not in action

    item["version"] += 1
    reviewed_candidate = {
        "authority_kind": "product_definition",
        "artifact_id": candidate["artifact_id"],
        "revision_id": candidate["revision_id"],
        "path": candidate["path"],
        "content_sha256": candidate["content_sha256"],
        "governed_paths": candidate["governed_paths"],
    }
    reviewed_ref = _candidate_review_ref(reviewed_candidate)
    candidate_bundle = {
        "schema_version": "strixnova.project-authority-review-bundle.v1",
        "plan_ref": project_authority_plan_ref(item),
        "candidates": [reviewed_candidate],
        "reviewed_refs": [reviewed_ref],
        "semantic_content_machine_proven": False,
    }
    candidate_bundle["content_sha256"] = _canonical_sha256(candidate_bundle)
    item["data"]["project_authority_reviews"] = [
        {
            "schema_version": "strixnova.project-authority-review.v1",
            "plan_ref": project_authority_plan_ref(item),
            "presentation_fingerprints": [
                challenge["candidate_fingerprint"]
            ],
            "candidate_bundle": candidate_bundle,
            "semantic_review": {
                "schema_version": "strixnova.semantic-review.v1",
                "reviewed_refs": [reviewed_ref],
            },
            "semantic_content_machine_proven": False,
        }
    ]

    action = current_action_for(item)

    assert action is not None
    assert action["action_type"] == "confirm_project_authority_candidates"
    assert action["confirmation_challenges"] == [challenge]


def test_current_action_moves_to_actual_result_when_verification_is_current() -> None:
    action = current_action_for(
        _implementing(
            {
                "receipt_id": "VR-001",
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "验证后没有相关修改。",
                },
            }
        )
    )

    assert action is not None
    assert action["action_type"] == "present_actual_result"
    assert action["intent"] == "delivery"
    assert action["record_refs"] == ["engineering.plan", "verifications", "engineering.execution_context", "engineering.review_subject"]


def test_current_action_focuses_the_first_ready_implementation_slice() -> None:
    item = _implementing({})
    item["data"]["verifications"] = []
    item["data"]["engineering"]["plan"].update(
        {
            "verification_commands": [
                {"command_id": "VC-001"},
                {"command_id": "VC-002"},
            ],
            "implementation_slices": [
                {
                    "slice_id": "SLICE-001",
                    "depends_on": [],
                    "verification_command_ids": ["VC-001"],
                },
                {
                    "slice_id": "SLICE-002",
                    "depends_on": ["SLICE-001"],
                    "verification_command_ids": ["VC-002"],
                },
            ],
        }
    )

    first = current_action_for(item)

    assert first is not None
    assert first["record_refs"][0] == (
        "engineering.plan.implementation_slice:SLICE-001"
    )

    item["data"]["verifications"] = [
        {
            "receipt_id": "VR-001",
            "command_id": "VC-001",
            "result": "passed",
            "code_change_assessment": {
                "changed_after": False,
                "needs_retest": False,
                "rationale": "验证后没有相关修改。",
            },
        }
    ]
    second = current_action_for(item)

    assert second is not None
    assert second["record_refs"][0] == (
        "engineering.plan.implementation_slice:SLICE-002"
    )


def test_zero_command_slice_must_be_explicitly_completed_before_actual_result() -> None:
    item = _implementing({})
    item["data"]["verifications"] = []
    item["data"]["engineering"]["plan"] = {
        "verification_commands": [],
        "implementation_slices": [
            {
                "slice_id": "SLICE-001",
                "depends_on": [],
                "verification_command_ids": [],
            }
        ],
    }

    current = current_action_for(item)
    assert current is not None
    assert current["action_type"] == "complete_implementation_slice"
    assert current["record_refs"][0].endswith("SLICE-001")

    item["data"]["implementation_slice_completions"] = [
        {
            "schema_version": "strixnova.implementation-slice-completion.v1",
            "slice_id": "SLICE-001",
            "completion_summary": "已完成无命令切片。",
            "semantic_content_machine_proven": False,
        }
    ]
    completed = current_action_for(item)
    assert completed is not None
    assert completed["action_type"] == "present_actual_result"


def test_assessed_failed_slice_reports_without_fabricating_dependents() -> None:
    item = _implementing({})
    item["data"]["engineering"]["plan"].update(
        {
            "verification_commands": [{"command_id": "VC-001"}],
            "implementation_slices": [
                {
                    "slice_id": "SLICE-001",
                    "depends_on": [],
                    "verification_command_ids": ["VC-001"],
                },
                {
                    "slice_id": "SLICE-002",
                    "depends_on": ["SLICE-001"],
                    "verification_command_ids": [],
                },
            ],
        }
    )
    item["data"]["verifications"] = [
        {
            "receipt_id": "VR-001",
            "command_id": "VC-001",
            "result": "failed",
            "code_change_assessment": {
                "changed_after": False,
                "needs_retest": False,
                "rationale": "失败已完成评估。",
            },
        }
    ]

    action = current_action_for(item)

    assert action is not None
    assert action["action_type"] == "present_actual_result"


def test_fully_assessed_failed_slice_can_be_reported_as_actual_result() -> None:
    item = _implementing({})
    item["data"]["engineering"]["plan"]["implementation_slices"] = [
        {
            "slice_id": "SLICE-001",
            "depends_on": [],
            "verification_command_ids": ["VC-001"],
        }
    ]
    item["data"]["verifications"] = [
        {
            "receipt_id": "VR-001",
            "command_id": "VC-001",
            "result": "not_run",
            "code_change_assessment": {
                "changed_after": False,
                "needs_retest": False,
                "rationale": "未运行原因和影响已经评估。",
            },
        }
    ]

    action = current_action_for(item)

    assert action is not None
    assert action["action_type"] == "present_actual_result"


def test_commit_action_requires_the_accepted_authority_adoption_record() -> None:
    action = current_action_for(
        {
            "work_item_id": "WI-AUTHORITY-ADOPTION",
            "status": "commit_required",
            "version": 12,
            "data": {
                "actual_result_confirmation": {"accepted": True},
                "git": {"work_ref": "strixnova/WI-AUTHORITY-ADOPTION"},
                "blockers": [],
            },
        }
    )

    assert action is not None
    assert action["action_type"] == "create_atomic_commits"
    assert action["record_refs"] == [
        "actual_result_confirmation",
        "delivery.authority_adoption",
        "git",
        "repository_deliveries",
    ]
