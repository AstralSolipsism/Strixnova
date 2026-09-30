from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3

import pytest

from strixnova.work_item_relations import WORK_ITEM_RELATION_TYPES
from strixnova.workflow_authority import (
    AuthorityConflict,
    AuthorityNotInitialized,
    InvalidTransition,
    WorkflowAuthority,
    WorkflowAuthorityError,
    _initial_data,
    _reduce,
)


def _direction(relations: list[dict] | None = None) -> dict:
    direction = {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
        "goal": "减少测试等待时间",
        "scope": [
            {
                "requirement_id": "DIRREQ-1111111111111111",
                "statement": "测试结构和执行策略可被优化",
            }
        ],
        "non_goals": ["删除必要行为覆盖"],
        "constraints": [
            {
                "constraint_id": "DIRCON-2222222222222222",
                "statement": "Python 命令使用项目 venv",
            }
        ],
        "acceptance": [
            {
                "acceptance_id": "DIRACC-3333333333333333",
                "statement": "快速套件和全量套件报告真实耗时",
                "requirement_refs": ["DIRREQ-1111111111111111"],
                "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
            }
        ],
        "tradeoffs": ["不设置人为秒数门槛"],
    }
    if relations is not None:
        direction["work_item_relations"] = relations
    return direction


def _stable_direction(relations: list[dict] | None = None) -> dict:
    return _direction(relations)


def _confirmation_payload(
    authority: WorkflowAuthority,
    work_item_id: str,
    *,
    accepted: bool = True,
    correction: str = "需要修正候选内容",
) -> dict[str, str]:
    challenge = authority.get(work_item_id)["current_action"][
        "confirmation_challenge"
    ]
    user_confirmation = (
        "同意当前候选，可以继续。"
        if accepted
        else correction
    )
    return {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": user_confirmation,
        "agent_decision": {
            "decision": "accept" if accepted else "request_changes",
            "reason": "负责人明确接受当前候选" if accepted else correction,
        },
    }


@pytest.mark.parametrize(
    ("action", "status", "payload", "expected_code"),
    [
        (
            "record_project_authority_decision_bundle",
            "implementing",
            {"project_authority_decisions": [{}]},
            "project_authority_confirmation_not_claimed",
        ),
        (
            "record_authority_adoption",
            "commit_required",
            {"authority_adoption": {}},
            "authority_adoption_not_claimed",
        ),
    ],
)
def test_authority_finalize_reducers_require_a_matching_pending_effect(
    action: str,
    status: str,
    payload: dict,
    expected_code: str,
) -> None:
    data = _initial_data("测试副作用占位门")

    with pytest.raises(InvalidTransition) as captured:
        _reduce(
            status,
            data,
            action,
            payload,
            work_item_id="WI-TEST",
            work_item_version=1,
        )

    assert captured.value.code == expected_code
    assert data["pending_effect"] is None


@pytest.mark.parametrize(
    ("action", "status", "pending_effect", "payload", "expected_code"),
    [
        (
            "record_project_authority_decision_bundle",
            "implementing",
            {
                "kind": "project_authority_confirmation",
                "intent": {"decisions": [], "candidate_fingerprints": []},
            },
            {"project_authority_decisions": [{}]},
            "project_authority_confirmation_intent_mismatch",
        ),
        (
            "record_authority_adoption",
            "commit_required",
            {"kind": "authority_adoption", "intent": {}},
            {"authority_adoption": {}},
            "authority_adoption_intent_mismatch",
        ),
    ],
)
def test_authority_finalize_reducers_reject_a_mismatched_pending_intent(
    action: str,
    status: str,
    pending_effect: dict,
    payload: dict,
    expected_code: str,
) -> None:
    data = _initial_data("测试副作用意图绑定")
    data["pending_effect"] = pending_effect

    with pytest.raises(InvalidTransition) as captured:
        _reduce(
            status,
            data,
            action,
            payload,
            work_item_id="WI-TEST",
            work_item_version=1,
        )

    assert captured.value.code == expected_code
    assert data["pending_effect"] == pending_effect


def test_project_authority_review_reducer_rejects_an_unstructured_review() -> None:
    data = _initial_data("测试候选复核结构")

    with pytest.raises(InvalidTransition) as captured:
        _reduce(
            "implementing",
            data,
            "record_project_authority_review",
            {"project_authority_review": {}},
            work_item_id="WI-TEST",
            work_item_version=1,
        )

    assert captured.value.code == "project_authority_review_invalid"
    assert data["project_authority_reviews"] == []


def test_reads_before_intake_do_not_initialize_local_state(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)

    assert authority.list() == []
    assert authority.revision() == {
        "schema_version": "strixnova.authority-revision.v1",
        "revision": 0,
        "updated_at": None,
    }
    with pytest.raises(AuthorityNotInitialized) as caught:
        authority.get("WI-NOT-CREATED")

    assert caught.value.code == "authority_not_initialized"
    assert not (tmp_path / ".strixnova").exists()


def test_invalid_intake_does_not_leave_an_empty_authority(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)

    with pytest.raises(InvalidTransition):
        authority.create(title="", raw_request="有效请求")

    assert not (tmp_path / ".strixnova").exists()


def test_authority_owns_one_current_state_and_one_event_history(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(
        title="优化测试时间",
        raw_request="测试太慢，需要彻底分析和优化。",
    )

    assert created["status"] == "discussion"
    assert created["version"] == 1
    assert authority.get(created["work_item_id"])["current_action"][
        "action_type"
    ] == "submit_direction"

    proposed = authority.transition(
        created["work_item_id"],
        "submit_direction",
        {
            "direction": _direction(),
            "ready_for_confirmation": True,
        },
        expected_version=1,
    )
    assert proposed["status"] == "awaiting_direction_confirmation"
    assert proposed["version"] == 2
    action = authority.get(created["work_item_id"])["current_action"]
    challenge = action.pop("confirmation_challenge")
    assert action == {
        "schema_version": "strixnova.current-action.v1",
        "work_item_id": created["work_item_id"],
        "work_item_version": 2,
        "action_type": "confirm_direction",
        "actor": "user",
        "intent": "confirm",
        "input_kind": "direction_confirmation",
        "input_contract_ref": "input.contract:confirm_direction",
        "record_refs": ["direction", "project.direction_context"],
        "conditional_record_refs": [],
        "blocking_facts": [],
    }
    assert challenge["candidate_kind"] == "direction"
    assert challenge["decision_label"] == "当前展示的方向"
    assert challenge["decision_interpreter"] == "coding_agent"
    assert "accept_text" not in challenge

    confirmed = authority.transition(
        created["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, created["work_item_id"]),
        expected_version=2,
    )
    assert confirmed["status"] == "needs_engineering_assessment"
    recorded = confirmed["data"]["direction_confirmation"]
    assert recorded["schema_version"] == "strixnova.user-confirmation.v1"
    assert recorded["accepted"] is True
    assert recorded["candidate_kind"] == "direction"
    assert recorded["candidate_fingerprint"] == challenge[
        "candidate_fingerprint"
    ]
    assert recorded["decision_label"] == "当前展示的方向"
    assert "confirmation_token" not in recorded
    assert recorded["user_confirmation"] == "同意当前候选，可以继续。"
    assert recorded["semantic_content_machine_proven"] is False
    assert recorded["direction_version"] == 3
    assert [item["event_type"] for item in authority.history(
        created["work_item_id"]
    )] == [
        "work_item_created",
        "submit_direction",
        "confirm_direction",
    ]
    authority_entries = {
        path.name for path in (tmp_path / ".strixnova").iterdir()
    }
    assert {".gitignore", "authority.sqlite3"} <= authority_entries
    assert authority_entries <= {
        ".gitignore",
        "artifacts",
        "authority.sqlite3",
        "authority.sqlite3-shm",
        "authority.sqlite3-wal",
    }


def test_confirmable_direction_accepts_stable_item_identities(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(
        title="稳定方向身份",
        raw_request="方向条目在修订后仍需可追溯。",
    )

    proposed = authority.transition(
        item["work_item_id"],
        "submit_direction",
        {
            "direction": _stable_direction(),
            "ready_for_confirmation": True,
        },
        expected_version=item["version"],
    )

    assert proposed["data"]["direction"] == _stable_direction()


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        (
            lambda direction: direction["scope"][0].update(
                {"requirement_id": "DIRREQ-not-stable"}
            ),
            "direction_item_invalid",
        ),
        (
            lambda direction: direction["scope"].append(
                deepcopy(direction["scope"][0])
            ),
            "direction_item_duplicate",
        ),
    ],
)
def test_confirmable_direction_rejects_invalid_item_identities_without_write(
    tmp_path: Path,
    mutate,
    expected_code: str,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="身份格式", raw_request="拒绝不稳定身份")
    direction = _stable_direction()
    mutate(direction)
    history_before = authority.history(item["work_item_id"])

    with pytest.raises(InvalidTransition) as captured:
        authority.transition(
            item["work_item_id"],
            "submit_direction",
            {"direction": direction, "ready_for_confirmation": True},
            expected_version=item["version"],
        )

    assert captured.value.code == expected_code
    assert authority.get(item["work_item_id"])["version"] == item["version"]
    assert authority.history(item["work_item_id"]) == history_before


def test_confirmable_direction_rejects_unknown_requirement_reference(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="引用闭合", raw_request="拒绝未知需求引用")
    direction = _stable_direction()
    direction["acceptance"][0]["requirement_refs"] = [
        "DIRREQ-AAAAAAAAAAAAAAAA"
    ]

    with pytest.raises(InvalidTransition) as captured:
        authority.transition(
            item["work_item_id"],
            "submit_direction",
            {"direction": direction, "ready_for_confirmation": True},
            expected_version=item["version"],
        )

    assert captured.value.code == "direction_requirement_ref_unknown"


def test_confirmable_direction_requires_acceptance_coverage_for_every_requirement(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="需求覆盖", raw_request="每条需求均可验收")
    direction = _stable_direction()
    direction["scope"].append(
        {
            "requirement_id": "DIRREQ-AAAAAAAAAAAAAAAA",
            "statement": "新增方向需求",
        }
    )

    with pytest.raises(InvalidTransition) as captured:
        authority.transition(
            item["work_item_id"],
            "submit_direction",
            {"direction": direction, "ready_for_confirmation": True},
            expected_version=item["version"],
        )

    assert captured.value.code == "direction_requirement_uncovered"


def test_confirmable_direction_rejects_positional_elements(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="拒绝位置合同", raw_request="只接受稳定身份")
    direction = _stable_direction()
    direction.update(
        {
            "schema_version": "strixnova.direction-decision.v1",
            "scope": ["无稳定身份的需求"],
            "constraints": ["无稳定身份的约束"],
            "acceptance": ["无稳定身份的验收"],
        }
    )

    recorded_before = authority.get(item["work_item_id"])
    with pytest.raises(InvalidTransition) as captured:
        authority.transition(
            item["work_item_id"],
            "submit_direction",
            {"direction": direction, "ready_for_confirmation": True},
            expected_version=item["version"],
        )

    assert captured.value.code == "invalid_payload"
    assert authority.get(item["work_item_id"]) == recorded_before


def test_confirmed_direction_identity_can_continue_but_cannot_revive(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="身份生命周期", raw_request="追踪方向修订")
    original = _stable_direction()
    original["scope"].append(
        {
            "requirement_id": "DIRREQ-4444444444444444",
            "statement": "第二条需求",
        }
    )
    original["acceptance"].append(
        {
            "acceptance_id": "DIRACC-5555555555555555",
            "statement": "第二条需求可验收",
            "requirement_refs": ["DIRREQ-4444444444444444"],
            "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
        }
    )
    item = authority.transition(
        item["work_item_id"],
        "submit_direction",
        {"direction": original, "ready_for_confirmation": True},
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )

    clarified = deepcopy(original)
    clarified["scope"] = list(reversed(clarified["scope"]))
    clarified["acceptance"] = list(reversed(clarified["acceptance"]))
    clarified["scope"][0]["statement"] = "第二条需求（措辞澄清）"
    item = authority.transition(
        item["work_item_id"],
        "revise_direction",
        {
            "direction": clarified,
            "ready_for_confirmation": True,
            "invalidation_issues": ["方向修订使旧工程方案失效。"],
        },
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )

    reduced = deepcopy(clarified)
    reduced["scope"] = [
        entry
        for entry in reduced["scope"]
        if entry["requirement_id"] != "DIRREQ-4444444444444444"
    ]
    reduced["acceptance"] = [
        entry
        for entry in reduced["acceptance"]
        if entry["acceptance_id"] != "DIRACC-5555555555555555"
    ]
    item = authority.transition(
        item["work_item_id"],
        "revise_direction",
        {
            "direction": reduced,
            "ready_for_confirmation": True,
            "invalidation_issues": ["第二条需求退出当前方向。"],
        },
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )
    history_before = authority.history(item["work_item_id"])

    with pytest.raises(InvalidTransition) as captured:
        authority.transition(
            item["work_item_id"],
            "revise_direction",
            {
                "direction": clarified,
                "ready_for_confirmation": True,
                "invalidation_issues": ["错误地尝试复活已退出身份。"],
            },
            expected_version=item["version"],
        )

    assert captured.value.code == "direction_item_reused"
    assert authority.get(item["work_item_id"])["version"] == item["version"]
    assert authority.history(item["work_item_id"]) == history_before


def test_agent_declared_split_uses_new_ids_without_program_semantic_guessing(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(
        title="方向需求拆分",
        raw_request="把一项方向需求拆为两个可分别验收的结果。",
    )
    original = _stable_direction()
    item = authority.transition(
        item["work_item_id"],
        "submit_direction",
        {"direction": original, "ready_for_confirmation": True},
        expected_version=item["version"],
    )
    item = authority.transition(
        item["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=item["version"],
    )

    split = deepcopy(original)
    split["scope"] = [
        {
            "requirement_id": "DIRREQ-4444444444444444",
            "statement": "测试结构可以单独优化",
        },
        {
            "requirement_id": "DIRREQ-5555555555555555",
            "statement": "执行策略可以单独优化",
        },
    ]
    split["acceptance"] = [
        {
            "acceptance_id": "DIRACC-6666666666666666",
            "statement": "测试结构优化结果可判断",
            "requirement_refs": ["DIRREQ-4444444444444444"],
            "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
        },
        {
            "acceptance_id": "DIRACC-7777777777777777",
            "statement": "执行策略优化结果可判断",
            "requirement_refs": ["DIRREQ-5555555555555555"],
            "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
        },
    ]
    proposed = authority.transition(
        item["work_item_id"],
        "revise_direction",
        {
            "direction": split,
            "ready_for_confirmation": True,
            "invalidation_issues": [
                "智能编码代理判断原需求发生语义拆分并使用新身份。"
            ],
        },
        expected_version=item["version"],
    )

    assert proposed["status"] == "awaiting_direction_confirmation"
    assert proposed["data"]["direction"] == split
    assert proposed["data"]["direction_item_history"] == {
        "active_ids": [
            "DIRACC-3333333333333333",
            "DIRCON-2222222222222222",
            "DIRREQ-1111111111111111",
        ],
        "retired_ids": [],
    }

    confirmed = authority.transition(
        item["work_item_id"],
        "confirm_direction",
        _confirmation_payload(authority, item["work_item_id"]),
        expected_version=proposed["version"],
    )
    history = confirmed["data"]["direction_item_history"]
    assert set(history["active_ids"]) == {
        "DIRCON-2222222222222222",
        "DIRREQ-4444444444444444",
        "DIRREQ-5555555555555555",
        "DIRACC-6666666666666666",
        "DIRACC-7777777777777777",
    }
    assert set(history["retired_ids"]) == {
        "DIRREQ-1111111111111111",
        "DIRACC-3333333333333333",
    }


@pytest.mark.parametrize("relation_type", sorted(WORK_ITEM_RELATION_TYPES))
def test_confirmable_direction_atomically_records_each_valid_relation_type(
    tmp_path: Path,
    relation_type: str,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    target = authority.create(title="前置事项", raw_request="先完成基础能力")
    source = authority.create(title="后续事项", raw_request="延续已有能力")
    relation = {
        "target_work_item_id": target["work_item_id"],
        "relation_type": relation_type,
        "reason": "后续事项复用前置事项建立的本地接口。",
    }
    target_history_before = authority.history(target["work_item_id"])

    proposed = authority.transition(
        source["work_item_id"],
        "submit_direction",
        {
            "direction": _direction([relation]),
            "ready_for_confirmation": True,
        },
        expected_version=source["version"],
    )

    assert proposed["data"]["direction"]["work_item_relations"] == [
        relation
    ]
    unchanged_target = authority.get(target["work_item_id"])
    assert unchanged_target["version"] == target["version"]
    assert authority.history(target["work_item_id"]) == target_history_before


def test_invalid_work_item_relations_are_typed_and_leave_no_side_effects(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    target = authority.create(title="有效目标", raw_request="目标事项")
    target_id = target["work_item_id"]
    attempts = [
        (
            "work_item_relation_target_not_found",
            lambda _source_id: [
                {
                    "target_work_item_id": "WI-NOT-FOUND",
                    "relation_type": "related_to",
                    "reason": "目标不存在。",
                }
            ],
        ),
        (
            "work_item_relation_self_reference",
            lambda source_id: [
                {
                    "target_work_item_id": source_id,
                    "relation_type": "related_to",
                    "reason": "不能指向自身。",
                }
            ],
        ),
        (
            "work_item_relation_duplicate",
            lambda _source_id: [
                {
                    "target_work_item_id": target_id,
                    "relation_type": "depends_on",
                    "reason": "第一次声明。",
                },
                {
                    "target_work_item_id": target_id,
                    "relation_type": "depends_on",
                    "reason": "同类型同目标重复。",
                },
            ],
        ),
        (
            "work_item_relation_type_invalid",
            lambda _source_id: [
                {
                    "target_work_item_id": target_id,
                    "relation_type": "blocks",
                    "reason": "未批准的调度类型。",
                }
            ],
        ),
        (
            "work_item_relation_invalid",
            lambda _source_id: [
                {
                    "target_work_item_id": True,
                    "relation_type": "related_to",
                    "reason": "布尔值不能伪装成事项 ID。",
                }
            ],
        ),
        (
            "work_item_relation_invalid",
            lambda _source_id: [
                {
                    "target_work_item_id": target_id,
                    "relation_type": 7,
                    "reason": "数字不能伪装成关系类型。",
                }
            ],
        ),
        (
            "work_item_relation_invalid",
            lambda _source_id: [
                {
                    "target_work_item_id": target_id,
                    "relation_type": "part_of",
                    "reason": {"fake": "program semantics"},
                }
            ],
        ),
    ]

    for expected_code, relations_for in attempts:
        source = authority.create(title="关系源", raw_request="声明关系")
        source_id = source["work_item_id"]
        history_before = authority.history(source_id)

        with pytest.raises(InvalidTransition) as caught:
            authority.transition(
                source_id,
                "submit_direction",
                {
                    "direction": _direction(relations_for(source_id)),
                    "ready_for_confirmation": True,
                },
                expected_version=source["version"],
            )

        assert caught.value.code == expected_code
        assert authority.get(source_id)["version"] == source["version"]
        assert authority.history(source_id) == history_before

    assert authority.get(target_id)["version"] == target["version"]
    assert len(authority.history(target_id)) == 1


def test_replan_relation_change_requires_direction_reconfirmation(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    first_target = authority.create(title="原大事项", raw_request="原始方向")
    second_target = authority.create(title="新大事项", raw_request="修正方向")
    source = authority.create(title="子事项", raw_request="重新确定归属")
    source_id = source["work_item_id"]
    original_relation = {
        "target_work_item_id": first_target["work_item_id"],
        "relation_type": "part_of",
        "reason": "最初判断属于原大事项。",
    }
    item = authority.transition(
        source_id,
        "submit_direction",
        {
            "direction": _direction([original_relation]),
            "ready_for_confirmation": True,
        },
        expected_version=source["version"],
    )
    item = authority.transition(
        source_id,
        "confirm_direction",
        _confirmation_payload(authority, source_id),
        expected_version=item["version"],
    )
    item = authority.transition(
        source_id,
        "submit_engineering_assessment",
        {
            "assessment": {"assessment_id": "EA-ORIGINAL"},
            "plan": {"change_context": {"formal_implementation": True}},
        },
        expected_version=item["version"],
    )
    item = authority.transition(
        source_id,
        "confirm_engineering_plan",
        _confirmation_payload(authority, source_id),
        expected_version=item["version"],
    )
    item = authority.transition(
        source_id,
        "request_replan",
        {"reasons": ["新事实改变了事项归属。"]},
        expected_version=item["version"],
    )
    revised_relation = {
        "target_work_item_id": second_target["work_item_id"],
        "relation_type": "part_of",
        "reason": "新事实表明它属于新大事项。",
    }

    proposed = authority.transition(
        source_id,
        "submit_direction",
        {
            "direction": _direction([revised_relation]),
            "ready_for_confirmation": True,
        },
        expected_version=item["version"],
    )

    assert proposed["status"] == "awaiting_direction_confirmation"
    assert proposed["data"]["direction_confirmation"] is None
    assert proposed["data"]["direction"]["work_item_relations"] == [
        revised_relation
    ]
    confirmed = authority.transition(
        source_id,
        "confirm_direction",
        _confirmation_payload(authority, source_id),
        expected_version=proposed["version"],
    )
    assert confirmed["status"] == "needs_engineering_assessment"
    assert authority.get(source_id)["current_action"]["action_type"] == (
        "submit_engineering_assessment"
    )


def test_invalid_or_stale_transition_changes_neither_state_nor_history(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="事项", raw_request="建设一个能力")
    identifier = created["work_item_id"]

    with pytest.raises(AuthorityConflict) as missing_version:
        authority.transition(
            identifier,
            "submit_direction",
            {
                "direction": _direction(),
                "ready_for_confirmation": True,
            },
            expected_version=0,
        )
    assert missing_version.value.code == "expected_version_required"

    with pytest.raises(InvalidTransition):
        authority.transition(
            identifier,
            "confirm_direction",
            {"accepted": True, "summary": "不应成功"},
            expected_version=1,
        )
    with pytest.raises(AuthorityConflict):
        authority.transition(
            identifier,
            "submit_direction",
            {
                "direction": _direction(),
                "ready_for_confirmation": True,
            },
            expected_version=99,
        )

    assert authority.get(identifier)["version"] == 1
    assert len(authority.history(identifier)) == 1


def test_direction_can_be_partial_only_until_coding_agent_marks_it_confirmable(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="方向", raw_request="先帮我弄清楚")
    identifier = created["work_item_id"]

    partial = authority.transition(
        identifier,
        "submit_direction",
        {
            "direction": {"goal": "仍需澄清范围"},
            "ready_for_confirmation": False,
            "blockers": ["用户尚未说明不做什么"],
        },
        expected_version=1,
    )
    assert partial["status"] == "discussion"
    assert partial["data"]["blockers"] == ["用户尚未说明不做什么"]

    with pytest.raises(InvalidTransition):
        authority.transition(
            identifier,
            "submit_direction",
            {
                "direction": {"goal": "仍需澄清范围"},
                "ready_for_confirmation": True,
            },
            expected_version=partial["version"],
        )


@pytest.mark.parametrize("bad_blockers", [False, 0, "", {}])
def test_direction_blockers_never_coerce_a_wrong_json_type(
    tmp_path: Path,
    bad_blockers: object,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="方向", raw_request="拒绝伪造阻断原因")

    with pytest.raises(InvalidTransition):
        authority.transition(
            created["work_item_id"],
            "submit_direction",
            {
                "direction": {"goal": "仍需澄清范围"},
                "ready_for_confirmation": False,
                "blockers": bad_blockers,
            },
            expected_version=created["version"],
        )

    unchanged = authority.get(created["work_item_id"])
    assert unchanged["version"] == created["version"]
    assert len(authority.history(created["work_item_id"])) == 1


def test_engineering_assessment_and_plan_are_recorded_atomically(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    item = authority.create(title="工程评估", raw_request="形成可确认方案")
    identifier = item["work_item_id"]
    item = authority.transition(
        identifier,
        "submit_direction",
        {"direction": _direction(), "ready_for_confirmation": True},
        expected_version=item["version"],
    )
    item = authority.transition(
        identifier,
        "confirm_direction",
        _confirmation_payload(authority, identifier),
        expected_version=item["version"],
    )
    item = authority.transition(
        identifier,
        "submit_engineering_assessment",
        {
            "assessment": {"assessment_id": "EA-001"},
            "plan": {"plan_id": "EP-001"},
        },
        expected_version=item["version"],
    )

    assert item["status"] == "awaiting_plan_confirmation"
    assert item["data"]["engineering"]["assessment"] == {
        "assessment_id": "EA-001"
    }
    assert item["data"]["engineering"]["plan"] == {"plan_id": "EP-001"}
    assert item["data"]["blockers"] == []


def test_event_write_failure_rolls_back_current_state(tmp_path: Path) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="事项", raw_request="建设一个能力")
    identifier = created["work_item_id"]

    with sqlite3.connect(authority.database_path) as connection:
        connection.execute(
            """
            CREATE TRIGGER fail_semantic_event
            BEFORE INSERT ON events
            WHEN NEW.event_type = 'submit_direction'
            BEGIN
                SELECT RAISE(ABORT, 'simulated event failure');
            END
            """
        )

    with pytest.raises(sqlite3.IntegrityError):
        authority.transition(
            identifier,
            "submit_direction",
            {
                "direction": _direction(),
                "ready_for_confirmation": True,
            },
            expected_version=1,
        )

    assert authority.get(identifier)["status"] == "discussion"
    assert authority.get(identifier)["version"] == 1
    assert len(authority.history(identifier)) == 1


def test_different_work_items_can_progress_from_separate_instances(
    tmp_path: Path,
) -> None:
    first = WorkflowAuthority(tmp_path).create(
        title="事项一",
        raw_request="建设事项一",
    )
    second = WorkflowAuthority(tmp_path).create(
        title="事项二",
        raw_request="建设事项二",
    )

    def progress(identifier: str) -> dict:
        return WorkflowAuthority(tmp_path).transition(
            identifier,
            "submit_direction",
            {
                "direction": _direction(),
                "ready_for_confirmation": True,
            },
            expected_version=1,
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(progress, [first["work_item_id"], second["work_item_id"]]))

    assert {item["status"] for item in results} == {
        "awaiting_direction_confirmation"
    }
    assert len(WorkflowAuthority(tmp_path).list()) == 2


def test_read_only_lookup_preserves_artifacts_without_an_authority_database(
    tmp_path: Path,
) -> None:
    strixnova_root = tmp_path / ".strixnova"
    artifact = strixnova_root / "artifacts" / "implementation-alignment" / "snapshot.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"generated":true}\n')
    before = {
        path.relative_to(strixnova_root): path.read_bytes()
        for path in strixnova_root.rglob("*")
        if path.is_file()
    }

    assert WorkflowAuthority(tmp_path).list() == []

    assert {
        path.relative_to(strixnova_root): path.read_bytes()
        for path in strixnova_root.rglob("*")
        if path.is_file()
    } == before
    assert not (strixnova_root / "authority.sqlite3").exists()


def test_artifacts_without_database_do_not_authorize_initialization(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / ".strixnova" / "artifacts" / "retained.json"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b'{"retained":true}\n')

    with pytest.raises(WorkflowAuthorityError) as caught:
        WorkflowAuthority(tmp_path).initialize()

    assert caught.value.code == "unsupported_authority_format"
    assert artifact.read_bytes() == b'{"retained":true}\n'
    assert not (tmp_path / ".strixnova" / "authority.sqlite3").exists()
    assert not (tmp_path / ".strixnova" / ".gitignore").exists()


@pytest.mark.parametrize(
    "orphan_name",
    ["authority.sqlite3-wal", "delivery-activities.sqlite3", "current"],
)
def test_read_only_lookup_still_rejects_orphaned_state_beside_artifacts(
    tmp_path: Path,
    orphan_name: str,
) -> None:
    strixnova_root = tmp_path / ".strixnova"
    (strixnova_root / "artifacts").mkdir(parents=True)
    orphan = strixnova_root / orphan_name
    orphan.write_bytes(b"unclassified state")

    with pytest.raises(WorkflowAuthorityError) as caught:
        WorkflowAuthority(tmp_path).list()

    assert caught.value.code == "unsupported_authority_format"
    assert orphan.read_bytes() == b"unclassified state"


def test_read_only_lookup_does_not_treat_an_artifact_file_as_a_directory(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / ".strixnova" / "artifacts"
    artifact.parent.mkdir()
    artifact.write_bytes(b"unknown state")

    with pytest.raises(WorkflowAuthorityError) as caught:
        WorkflowAuthority(tmp_path).list()

    assert caught.value.code == "unsupported_authority_format"
    assert artifact.read_bytes() == b"unknown state"


def test_unknown_managed_directories_are_preserved_and_rejected(tmp_path: Path) -> None:
    unknown = tmp_path / ".strixnova" / "external-cache"
    unknown.mkdir(parents=True)

    with pytest.raises(WorkflowAuthorityError):
        WorkflowAuthority(tmp_path).initialize()
    assert unknown.is_dir()

    second_project = tmp_path / "another-unclassified-project"
    external_state = second_project / ".strixnova" / "unrecognized-state"
    external_state.mkdir(parents=True)
    payload = external_state / "data.json"
    payload.write_text("{}\n", encoding="utf-8")
    with pytest.raises(WorkflowAuthorityError) as captured:
        WorkflowAuthority(second_project).initialize()
    assert captured.value.code == "unsupported_authority_format"
    assert "unrecognized-state" in str(captured.value)
    assert payload.read_text(encoding="utf-8") == "{}\n"


@pytest.mark.parametrize(
    "schema_version",
    ["0", "1", "2", "999", "01", " 1", "+1", "unknown"],
)
def test_unsupported_database_is_rejected_before_any_local_write(
    tmp_path: Path,
    schema_version: str,
) -> None:
    strixnova_root = tmp_path / ".strixnova"
    strixnova_root.mkdir()
    database = strixnova_root / "authority.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('schema_version', ?)",
            (schema_version,),
        )
    original = database.read_bytes()

    with pytest.raises(WorkflowAuthorityError) as captured:
        WorkflowAuthority(tmp_path).initialize()

    assert captured.value.code == "unsupported_authority_format"
    assert database.read_bytes() == original
    assert not (strixnova_root / ".gitignore").exists()


def test_create_rejects_unrecognized_format_before_opening_a_write_transaction(
    tmp_path: Path,
) -> None:
    strixnova_root = tmp_path / ".strixnova"
    strixnova_root.mkdir()
    database = strixnova_root / "authority.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO metadata(key, value) VALUES ('schema_version', '999')"
        )
    original = database.read_bytes()

    with pytest.raises(WorkflowAuthorityError) as captured:
        WorkflowAuthority(tmp_path).create(title="新事项", raw_request="继续建设")

    assert captured.value.code == "unsupported_authority_format"
    assert database.read_bytes() == original
    assert not (strixnova_root / "authority.sqlite3-wal").exists()
    assert not (strixnova_root / "authority.sqlite3-shm").exists()
    assert not (strixnova_root / ".gitignore").exists()


@pytest.mark.parametrize("database_kind", ["missing_version", "damaged"])
def test_invalid_database_is_rejected_without_rewriting_it(
    tmp_path: Path,
    database_kind: str,
) -> None:
    strixnova_root = tmp_path / ".strixnova"
    strixnova_root.mkdir()
    database = strixnova_root / "authority.sqlite3"
    if database_kind == "missing_version":
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
    else:
        database.write_bytes(b"not-a-sqlite-database\x00")
    original = database.read_bytes()

    with pytest.raises(WorkflowAuthorityError) as captured:
        WorkflowAuthority(tmp_path).create(title="新事项", raw_request="继续建设")

    assert captured.value.code == "unsupported_authority_format"
    assert database.read_bytes() == original
    assert not (strixnova_root / ".gitignore").exists()
    assert not (strixnova_root / "authority.sqlite3-wal").exists()
    assert not (strixnova_root / "authority.sqlite3-shm").exists()


def test_destructive_cancel_resolution_needs_explicit_confirmation(
    tmp_path: Path,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="事项", raw_request="建设一个能力")
    pending = authority.transition(
        created["work_item_id"],
        "cancel_work_item",
        {"has_unmerged_work": True, "reason": "用户停止建设"},
        expected_version=1,
    )
    assert pending["status"] == "cancelled_changes_pending"
    assert authority.get(created["work_item_id"])["current_action"][
        "actor"
    ] == "user"

    with pytest.raises(InvalidTransition):
        authority.transition(
            created["work_item_id"],
            "resolve_cancelled_work",
            {"decision": "discard", "details": {}},
            expected_version=2,
        )

    with pytest.raises(InvalidTransition):
        authority.transition(
            created["work_item_id"],
            "claim_external_effect",
            {
                "kind": "cancel_discard",
                "intent": {
                    "decision": "discard",
                    "details": {},
                    "destructive_confirmed": False,
                },
            },
            expected_version=2,
        )
    claimed = authority.transition(
        created["work_item_id"],
        "claim_external_effect",
        {
            "kind": "cancel_discard",
            "intent": {
                "decision": "discard",
                "details": {"reason": "明确放弃草稿"},
                "destructive_confirmed": True,
            },
        },
        expected_version=2,
    )
    assert authority.get(created["work_item_id"])["current_action"][
        "action_type"
    ] == "resume_cancel_discard"
    with pytest.raises(AuthorityConflict):
        WorkflowAuthority(tmp_path).transition(
            created["work_item_id"],
            "claim_external_effect",
            {
                "kind": "cancel_discard",
                "intent": {
                    "decision": "discard",
                    "details": {},
                    "destructive_confirmed": True,
                },
            },
            expected_version=2,
        )
    completed = authority.transition(
        created["work_item_id"],
        "resolve_cancelled_work",
        {
            "decision": "discard",
            "details": {},
            "destructive_confirmed": True,
        },
        expected_version=claimed["version"],
    )
    assert completed["status"] == "cancelled"
    assert completed["data"]["pending_effect"] is None


@pytest.mark.parametrize("bad_value", [False, 0, "", []])
def test_external_effect_and_cancel_details_reject_wrong_object_types(
    tmp_path: Path,
    bad_value: object,
) -> None:
    authority = WorkflowAuthority(tmp_path)
    created = authority.create(title="事项", raw_request="拒绝伪造外部副作用")

    with pytest.raises(InvalidTransition):
        authority.transition(
            created["work_item_id"],
            "claim_external_effect",
            {"kind": "cancel_cleanup", "intent": bad_value},
            expected_version=created["version"],
        )

    pending = authority.transition(
        created["work_item_id"],
        "cancel_work_item",
        {"has_unmerged_work": True, "reason": "用户停止建设"},
        expected_version=created["version"],
    )
    with pytest.raises(InvalidTransition):
        authority.transition(
            created["work_item_id"],
            "resolve_cancelled_work",
            {"decision": "preserve", "details": bad_value},
            expected_version=pending["version"],
        )

    unchanged = authority.get(created["work_item_id"])
    assert unchanged["version"] == pending["version"]


def _authority_at_integration_conflict(
    project: Path,
) -> tuple[WorkflowAuthority, str]:
    authority = WorkflowAuthority(project)
    item = authority.create(title="冲突事项", raw_request="验证冲突闭环")
    identifier = item["work_item_id"]
    transitions = [
        (
            "submit_direction",
            {"direction": _direction(), "ready_for_confirmation": True},
        ),
        ("confirm_direction", {"accepted": True, "summary": "方向确认"}),
        (
            "submit_engineering_assessment",
            {
                "assessment": {"id": "assessment"},
                "plan": {"id": "plan", "plan_id": "PLAN-CONFLICT"},
            },
        ),
        (
            "confirm_engineering_plan",
            {"accepted": True, "summary": "方案确认"},
        ),
        (
            "record_implementation_started",
            {
                "git": {
                    "schema_version": "strixnova.git-work-area.v1",
                    "work_ref": "strixnova/conflict",
                }
            },
        ),
        (
            "record_verification",
            {
                "verification": {
                    "receipt_id": "VR-1",
                    "command_id": "VC-001",
                    "result": "passed",
                    "code_change_assessment": {
                        "changed_after": False,
                        "needs_retest": False,
                        "rationale": "冲突前验证后没有继续修改代码。",
                    },
                }
            },
        ),
        (
            "present_actual_result",
            {"actual_result": {"effect_summary": "原结果"}},
        ),
        (
            "confirm_actual_result",
            {"accepted": True, "summary": "结果确认"},
        ),
        ("record_result_commits", {"commits": ["a" * 40]}),
        (
            "claim_external_effect",
            {"kind": "integrate", "intent": {"merge_strategy": "no_ff"}},
        ),
        (
            "record_local_integration",
            {
                "outcome": "conflict",
                "integration": {
                    "outcome": "conflict",
                    "conflict_entries": ["UU shared.txt"],
                },
                "blockers": ["git_conflict"],
            },
        ),
    ]
    version = 1
    for action, payload in transitions:
        if action in {
            "confirm_direction",
            "confirm_engineering_plan",
            "confirm_actual_result",
        }:
            payload = _confirmation_payload(authority, identifier)
        item = authority.transition(
            identifier,
            action,
            payload,
            expected_version=version,
        )
        version = item["version"]
    assert item["status"] == "integration_conflict"
    return authority, identifier


@pytest.mark.parametrize("bad_blockers", [False, 0, "", {}])
def test_integration_conflict_blockers_reject_wrong_json_types(
    tmp_path: Path,
    bad_blockers: object,
) -> None:
    authority, identifier = _authority_at_integration_conflict(tmp_path)
    current = authority.get(identifier)

    with pytest.raises(InvalidTransition):
        authority.transition(
            identifier,
            "record_local_integration",
            {
                "outcome": "conflict",
                "integration": {"outcome": "conflict"},
                "blockers": bad_blockers,
            },
            expected_version=current["version"],
        )

    assert authority.get(identifier)["version"] == current["version"]


def test_preserved_conflict_result_requires_agent_judgement_and_retest(
    tmp_path: Path,
) -> None:
    authority, identifier = _authority_at_integration_conflict(tmp_path)

    decided = authority.transition(
        identifier,
        "record_conflict_resolution",
        {
            "user_visible_result_changed": False,
            "confirmed_direction_or_plan_changed": False,
            "reason": "只解决相同内容的 Git 行级冲突。",
            "retest_command_ids": ["VC-001"],
        },
        expected_version=authority.get(identifier)["version"],
    )
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "verify_after_git_conflict"
    )
    with pytest.raises(InvalidTransition):
        authority.transition(
            identifier,
            "record_local_integration",
            {
                "outcome": "integrated",
                "integration": {
                    "outcome": "integrated",
                    "result_commits": ["a" * 40],
                    "integrated_commit": "c" * 40,
                },
            },
            expected_version=decided["version"],
        )

    still_stale = authority.transition(
        identifier,
        "record_verification",
        {
            "verification": {
                "receipt_id": "VR-STILL-STALE",
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": {
                    "changed_after": True,
                    "needs_retest": True,
                    "rationale": "复测后又发生相关代码变化。",
                },
            }
        },
        expected_version=decided["version"],
    )
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "verify_after_git_conflict"
    )

    verified = authority.transition(
        identifier,
        "record_verification",
        {
            "verification": {
                "receipt_id": "VR-AFTER-CONFLICT",
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "复测后没有继续修改代码。",
                },
            }
        },
        expected_version=still_stale["version"],
    )
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "complete_git_merge"
    )
    with pytest.raises(InvalidTransition):
        authority.transition(
            identifier,
            "record_local_integration",
            {
                "outcome": "integrated",
                "integration": {
                    "outcome": "integrated",
                    "result_commits": ["f" * 40],
                    "integrated_commit": "c" * 40,
                },
            },
            expected_version=verified["version"],
        )
    integrated = authority.transition(
        identifier,
        "record_local_integration",
        {
            "outcome": "integrated",
            "integration": {
                "outcome": "integrated",
                "result_commits": ["a" * 40],
                "integrated_commit": "c" * 40,
            },
        },
        expected_version=verified["version"],
    )
    assert integrated["status"] == "cleanup_required"


def test_no_applicable_conflict_command_uses_an_explicit_file_snapshot(
    tmp_path: Path,
) -> None:
    authority, identifier = _authority_at_integration_conflict(tmp_path)
    snapshot = {
        "schema_version": "strixnova.implementation-candidate-snapshot.v1",
        "plan_id": "PLAN-CONFLICT",
        "comparison_base_commit": "b" * 40,
        "paths": [
            {
                "path": "shared.txt",
                "state": "file",
                "sha256": "c" * 64,
            }
        ],
        "changed_paths": ["shared.txt"],
        "semantic_content_machine_proven": False,
    }

    decided = authority.transition(
        identifier,
        "record_conflict_resolution",
        {
            "user_visible_result_changed": False,
            "confirmed_direction_or_plan_changed": False,
            "reason": "本次冲突没有适用验证命令，使用精确文件快照复核。",
            "retest_command_ids": [],
            "implementation_candidate_snapshot": snapshot,
        },
        expected_version=authority.get(identifier)["version"],
    )

    assert decided["status"] == "integration_conflict"
    assert decided["data"]["git"]["conflict_resolution"][
        "implementation_candidate_snapshot"
    ] == snapshot
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "complete_git_merge"
    )


def test_conflict_plan_change_returns_to_the_same_target_conflict_context(
    tmp_path: Path,
) -> None:
    authority, identifier = _authority_at_integration_conflict(tmp_path)
    replanning = authority.transition(
        identifier,
        "record_conflict_resolution",
        {
            "user_visible_result_changed": True,
            "confirmed_direction_or_plan_changed": True,
            "reason": "冲突暴露了方案缺口，需要重新规划。",
            "retest_command_ids": ["VC-001"],
        },
        expected_version=authority.get(identifier)["version"],
    )
    assert replanning["status"] == "replanning_required"

    assessed = authority.transition(
        identifier,
        "submit_engineering_assessment",
        {
            "assessment": {"id": "assessment-2"},
            "plan": {"id": "plan-2", "plan_id": "PLAN-CONFLICT-2"},
        },
        expected_version=replanning["version"],
    )
    confirmed = authority.transition(
        identifier,
        "confirm_engineering_plan",
        _confirmation_payload(authority, identifier),
        expected_version=assessed["version"],
    )

    assert confirmed["status"] == "implementing"
    original = replanning["data"]["git"]
    current = confirmed["data"]["git"]
    assert all(current.get(key) == original.get(key) for key in ("repository", "worktree_path", "work_ref", "target_ref"))
    assert current["conflict_resolution"]["replanned_in_plan_id"] == "PLAN-CONFLICT-2"
    assert current["conflict_resolution"]["requires_reassessment"] is False


def test_negative_conflict_retest_requires_result_reconfirmation(
    tmp_path: Path,
) -> None:
    authority, identifier = _authority_at_integration_conflict(tmp_path)
    decided = authority.transition(
        identifier,
        "record_conflict_resolution",
        {
            "user_visible_result_changed": False,
            "confirmed_direction_or_plan_changed": False,
            "reason": "冲突解决没有改变预期效果，但需要复测。",
            "retest_command_ids": ["VC-001"],
        },
        expected_version=authority.get(identifier)["version"],
    )
    failed = authority.transition(
        identifier,
        "record_verification",
        {
            "verification": {
                "receipt_id": "VR-FAILED-AFTER-CONFLICT",
                "command_id": "VC-001",
                "result": "failed",
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "失败后没有继续修改代码。",
                },
            }
        },
        expected_version=decided["version"],
    )
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "present_actual_result_after_conflict"
    )
    with pytest.raises(InvalidTransition):
        authority.transition(
            identifier,
            "record_local_integration",
            {
                "outcome": "integrated",
                "integration": {
                    "outcome": "integrated",
                    "result_commits": ["a" * 40],
                    "integrated_commit": "c" * 40,
                },
            },
            expected_version=failed["version"],
        )
    presented = authority.transition(
        identifier,
        "present_actual_result",
        {"actual_result": {"effect_summary": "冲突复测失败，能力受限。"}},
        expected_version=failed["version"],
    )
    confirmed = authority.transition(
        identifier,
        "confirm_actual_result",
        _confirmation_payload(authority, identifier),
        expected_version=presented["version"],
    )
    assert confirmed["status"] == "integration_conflict"
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "complete_git_merge"
    )


def test_changed_conflict_result_reopens_result_before_any_new_commit(
    tmp_path: Path,
) -> None:
    authority, identifier = _authority_at_integration_conflict(tmp_path)

    reopened = authority.transition(
        identifier,
        "record_conflict_resolution",
        {
            "user_visible_result_changed": True,
            "confirmed_direction_or_plan_changed": False,
            "reason": "冲突解决改变了用户看到的输出。",
            "retest_command_ids": ["VC-001"],
        },
        expected_version=authority.get(identifier)["version"],
    )

    assert reopened["status"] == "integration_conflict"
    assert reopened["data"]["actual_result"] is None
    assert reopened["data"]["actual_result_confirmation"] is None
    assert [
        receipt["receipt_id"]
        for receipt in reopened["data"]["verifications"]
    ] == ["VR-1"]
    assert reopened["data"]["git"]["result_commits"] == ["a" * 40]
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "verify_after_git_conflict"
    )

    verified = authority.transition(
        identifier,
        "record_verification",
        {
            "verification": {
                "receipt_id": "VR-CHANGED-CONFLICT",
                "command_id": "VC-001",
                "result": "passed",
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "复测后没有继续修改代码。",
                },
            }
        },
        expected_version=reopened["version"],
    )
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "present_actual_result_after_conflict"
    )
    presented = authority.transition(
        identifier,
        "present_actual_result",
        {"actual_result": {"effect_summary": "冲突后的新结果"}},
        expected_version=verified["version"],
    )
    confirmed = authority.transition(
        identifier,
        "confirm_actual_result",
        _confirmation_payload(authority, identifier),
        expected_version=presented["version"],
    )
    assert confirmed["status"] == "integration_conflict"
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "complete_git_merge"
    )

    integrated = authority.transition(
        identifier,
        "record_local_integration",
        {
            "outcome": "integrated",
            "integration": {
                "outcome": "integrated",
                    "result_commits": ["a" * 40],
                "integrated_commit": "c" * 40,
            },
        },
        expected_version=confirmed["version"],
    )
    assert integrated["status"] == "cleanup_required"
