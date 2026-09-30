"""Public, progressively readable input contracts for each current action."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from importlib.resources import files
import json
from typing import Any

from strixnova.confirmation_protocol import (
    ConfirmationProtocolError,
    confirmation_input_schema,
)


INPUT_CONTRACT_SCHEMA = "strixnova.input-contract.v1"
_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

_TEXT = {"type": "string", "minLength": 1}
_BOOLEAN = {"type": "boolean"}
_STRING_LIST = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
}
_CODE_CHANGE_ASSESSMENT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["changed_after", "needs_retest", "rationale"],
    "properties": {
        "changed_after": _BOOLEAN,
        "needs_retest": _BOOLEAN,
        "rationale": _TEXT,
    },
}


class PublicInputContractError(ValueError):
    """A projected current action has no exact public input contract."""


def _object_schema(
    *,
    required: Iterable[str] = (),
    properties: Mapping[str, Any] | None = None,
    schema_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "$schema": _SCHEMA_DIALECT,
        "type": "object",
        "additionalProperties": False,
        "required": list(required),
        "properties": deepcopy(dict(properties or {})),
    }
    if schema_id is not None:
        result["$id"] = schema_id
    return result


def _load_schema(name: str) -> dict[str, Any]:
    resource = files("strixnova.resources").joinpath(name)
    if not resource.is_file():
        raise PublicInputContractError(f"公开输入合同缺少结构资源：{name}")
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise PublicInputContractError(f"公开输入合同结构资源不是对象：{name}")
    return value


def _local_schema_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        ref = value.get("$ref")
        if isinstance(ref, str):
            document = ref.partition("#")[0]
            if (
                document
                and "://" not in document
                and "/" not in document
                and "\\" not in document
                and document.endswith(".json")
            ):
                refs.add(document)
        for item in value.values():
            refs.update(_local_schema_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.update(_local_schema_refs(item))
    return refs


def _schema_bundle(names: Iterable[str]) -> dict[str, dict[str, Any]]:
    pending = list(dict.fromkeys(names))
    documents: dict[str, dict[str, Any]] = {}
    while pending:
        name = pending.pop(0)
        if name in documents:
            continue
        document = _load_schema(name)
        documents[name] = document
        pending.extend(sorted(_local_schema_refs(document) - set(documents)))
    return documents


def _direction_submission_schema() -> tuple[dict[str, Any], list[str]]:
    schema = _object_schema(
        schema_id="strixnova.direction-submission.v1",
        required=("direction", "ready_for_confirmation", "blockers"),
        properties={
            "direction": {"$ref": "direction-decision-v1.schema.json"},
            "ready_for_confirmation": _BOOLEAN,
            "blockers": _STRING_LIST,
        },
    )
    schema["allOf"] = [
        {
            "if": {
                "properties": {"ready_for_confirmation": {"const": True}},
                "required": ["ready_for_confirmation"],
            },
            "then": {"properties": {"blockers": {"maxItems": 0}}},
            "else": {"properties": {"blockers": {"minItems": 1}}},
        }
    ]
    return schema, ["direction-decision-v1.schema.json"]


def _confirmation_schema(
    action: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    challenge = action.get("confirmation_challenge")
    if not isinstance(challenge, Mapping):
        raise PublicInputContractError("用户确认动作缺少当前候选的语义决定文本或内部绑定")
    try:
        return confirmation_input_schema(challenge), []
    except ConfirmationProtocolError as error:
        raise PublicInputContractError(str(error)) from error


def _authority_confirmation_bundle_schema(
    action: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    challenges = action.get("confirmation_challenges")
    authority_kinds = action.get("authority_kinds")
    if (
        not isinstance(challenges, list)
        or not challenges
        or not isinstance(authority_kinds, list)
        or len(authority_kinds) != len(challenges)
    ):
        raise PublicInputContractError("长期权威确认动作缺少完整候选包口令")
    decision_schemas: list[dict[str, Any]] = []
    for index, challenge in enumerate(challenges):
        if not isinstance(challenge, Mapping):
            raise PublicInputContractError("长期权威候选包口令结构无效")
        try:
            decision = confirmation_input_schema(challenge)
        except ConfirmationProtocolError as error:
            raise PublicInputContractError(str(error)) from error
        branches: list[dict[str, Any]] = []
        for branch in decision.get("oneOf") or []:
            if not isinstance(branch, Mapping):
                continue
            normalized = deepcopy(dict(branch))
            properties = deepcopy(dict(normalized.get("properties") or {}))
            properties["authority_kind"] = {
                "const": str(authority_kinds[index])
            }
            normalized["properties"] = properties
            normalized["required"] = [
                "authority_kind",
                *[
                    field
                    for field in normalized.get("required") or []
                    if field != "authority_kind"
                ],
            ]
            branches.append(normalized)
        decision_schemas.append({"oneOf": branches})
    return (
        _object_schema(
            schema_id="strixnova.project-authority-confirmation-bundle.v1",
            required=("decisions",),
            properties={
                "decisions": {
                    "type": "array",
                    "minItems": len(decision_schemas),
                    "maxItems": len(decision_schemas),
                    "prefixItems": decision_schemas,
                    "items": False,
                }
            },
        ),
        [],
    )


def _begin_implementation_schema() -> tuple[dict[str, Any], list[str]]:
    return (
        _object_schema(
            schema_id="strixnova.begin-implementation-input.v1",
            required=(),
            properties={
                "repository_id": {"type": ["string", "null"], "pattern": "^REPO-[0-9A-F]{16}$"},
                "target_ref": _TEXT,
                "worktree_path": _TEXT,
                "merge_strategy": {"enum": ["no_ff", "ff_only"]},
            },
        ),
        [],
    )


def _verification_schema() -> tuple[dict[str, Any], list[str]]:
    common = {
        "command_id": _TEXT,
        "execution_area": {"enum": ["worktree", "target"]},
        "limitations": _STRING_LIST,
    }
    run = _object_schema(
        required=("command_id", "mode"),
        properties={**common, "mode": {"const": "run"}},
    )
    not_run = _object_schema(
        required=("command_id", "mode", "not_run_reason"),
        properties={
            **common,
            "mode": {"const": "not_run"},
            "not_run_reason": _TEXT,
            "code_change_assessment": _CODE_CHANGE_ASSESSMENT,
        },
    )
    return (
        {
            "$schema": _SCHEMA_DIALECT,
            "$id": "strixnova.verification-input.v1",
            "oneOf": [run, not_run],
        },
        [],
    )


def _verification_assessment_schema() -> tuple[dict[str, Any], list[str]]:
    return (
        _object_schema(
            schema_id="strixnova.verification-assessment-input.v1",
            required=(
                "command_id",
                "mode",
                "receipt_id",
                "code_change_assessment",
            ),
            properties={
                "command_id": _TEXT,
                "mode": {"const": "assess"},
                "receipt_id": _TEXT,
                "code_change_assessment": _CODE_CHANGE_ASSESSMENT,
            },
        ),
        [],
    )


def _conflict_resolution_schema() -> tuple[dict[str, Any], list[str]]:
    return (
        _object_schema(
            schema_id="strixnova.conflict-resolution-input.v1",
            required=(
                "user_visible_result_changed",
                "confirmed_direction_or_plan_changed",
                "reason",
                "retest_command_ids",
            ),
            properties={
                "user_visible_result_changed": _BOOLEAN,
                "confirmed_direction_or_plan_changed": _BOOLEAN,
                "reason": _TEXT,
                "retest_command_ids": {
                    "type": "array",
                    "uniqueItems": True,
                    "items": _TEXT,
                },
            },
        ),
        [],
    )


def _cancel_decision_schema() -> tuple[dict[str, Any], list[str]]:
    return (
        _object_schema(
            schema_id="strixnova.cancellation-decision-input.v1",
            required=("decision", "details", "confirm_discard"),
            properties={
                "decision": {"enum": ["preserve", "transfer", "discard"]},
                "details": {"type": "object"},
                "confirm_discard": _BOOLEAN,
            },
        ),
        [],
    )


def _empty_schema(schema_id: str) -> tuple[dict[str, Any], list[str]]:
    return _object_schema(schema_id=schema_id), []


def _merge_schema(schema_id: str) -> tuple[dict[str, Any], list[str]]:
    return (
        _object_schema(
            schema_id=schema_id,
            properties={"merge_strategy": {"enum": ["no_ff", "ff_only"]}},
        ),
        [],
    )


def _resource_schema(name: str) -> tuple[dict[str, Any], list[str]]:
    return _load_schema(name), sorted(_local_schema_refs(_load_schema(name)))


def _replan_schema() -> tuple[dict[str, Any], list[str]]:
    direction, _ = _direction_submission_schema()
    schema = {
        "$schema": _SCHEMA_DIALECT,
        "$id": "strixnova.replanning-input.v1",
        "oneOf": [
            direction,
            {"$ref": "engineering-assessment-v1.schema.json"},
        ],
    }
    return schema, [
        "direction-decision-v1.schema.json",
        "engineering-assessment-v1.schema.json",
    ]


def _contract_schema_for(
    action: Mapping[str, Any],
) -> tuple[dict[str, Any], list[str], list[str]]:
    action_type = str(action.get("action_type") or "").strip()
    if action_type == "submit_direction":
        schema, roots = _direction_submission_schema()
        return schema, roots, [
            "先读取 project.direction_context 的完整当前产品目的、能力和全部护栏，再调查项目中可查明的事实；不要把文件、测试或架构等调查工作转给用户。",
            "相关能力、每条护栏的适用性、理由、假设和重开条件由智能编码代理形成；程序只校验版本、合法引用、唯一覆盖和失效，不会判断这些语义是否正确。",
            "凡是会实质改变目标、范围、非目标、约束、取舍或验收且尚未由用户回答的决定，都必须保留为阻断项；不得把推荐答案预填成可确认事实。",
            "只有所有实质性用户决定都已明确时，ready_for_confirmation 才能为 true；否则必须为 false 并列出具体 blockers。",
        ]
    if action_type == "revise_direction":
        schema, roots = _direction_submission_schema()
        return schema, roots, [
            "已保存方向绑定的产品决定上下文已经机械失效；先读取 direction、direction_confirmation、engineering.plan 和最新 project.direction_context，说明精确变化及其下游影响。",
            "只重新调查和澄清真正受失效事实影响的决定；仍有依据的用户决定继续沿用，不要求用户重述完整历史。",
            "相关能力、全部护栏逐项处置、理由、假设和重开条件仍由智能编码代理形成；程序只校验当前版本、合法引用、唯一覆盖和失效关系。",
            "提交一份完整修订方向；若仍有会实质改变目标、范围、非目标、约束、取舍或验收的未决决定，ready_for_confirmation 必须为 false 并列出具体 blockers。",
        ]
    if action_type in {
        "confirm_direction",
        "confirm_engineering_plan",
        "confirm_actual_result",
    }:
        schema, roots = _confirmation_schema(action)
        authorization_boundary = {
            "confirm_direction": (
                "方向确认只授权按当前方向继续调查并形成完整工程方案；"
                "不授权修改源码、提交 Git、推送、发布或部署。"
            ),
            "confirm_engineering_plan": (
                "工程方案确认只授权按当前方案在本地实施并验证；"
                "不代表实际结果已被接受，也不授权提交 Git、推送、发布或部署。"
            ),
            "confirm_actual_result": (
                "实际结果确认只接受已经展示的本轮实施与验证事实，并授权按项目交付规则"
                "组织本地 Git 提交、合入和清理；不授权远程推送、正式发布或部署。"
            ),
        }[action_type]
        return schema, roots, [
            "先主动把 record_refs 指向的完整候选解释到用户可以做决定：说明当前状态与问题、接受后会变成什么、产品与用户效果、工程逻辑、主要影响和风险、仍未知的内容、推荐结论，以及这次确认授权和不授权什么。按候选复杂度调整篇幅，不套固定标题，也不要先倾倒系统字段、文件清单或百分比。",
            authorization_boundary,
            "用自然语言询问用户是否接受当前完整候选，不要求固定口令或修改前缀。智能编码代理根据完整展示及后续答复判断是否明确接受；agent_decision 记录 accept 或 request_changes 及 reason，用户不填写这些内部字段。",
            "用户对澄清问题、推荐方案或业务取舍的回答只解决该问题，不等于确认随后形成的完整方向卡、工程方案卡或实际结果卡。",
            "如果用户表示没看懂或继续提问，继续解释同一候选并保持当前确认动作；不得调用 confirm，也不得改变候选、事项版本或确认绑定。只有用户提出会实质改变候选内容的纠正时，才按退回处理并进入修订。",
            "user_confirmation 必须逐字复制用户在看见当前完整候选后的新消息，保留标点、空白和附带条件；不得代签、拼造、复用更早答复或把沉默当作接受。有条件接受或要求修改不能接受原候选；指向不清时先澄清，不提交确认。",
            "提交时机械带入当前 CurrentAction 的 candidate_fingerprint。程序只检查候选、版本、状态和记录结构，保存用户原话与 Agent 判断；不判断用户意图、解释是否清楚、用户是否理解或候选语义是否正确。退回后重新读取当前动作。",
        ]
    if action_type == "submit_engineering_assessment":
        schema, roots = _resource_schema("engineering-assessment-v1.schema.json")
        return schema, roots, [
            "先读取 record_refs 中的已确认方向和方向确认；conditional_record_refs 不是必读清单。",
            "逐项安排当前方向的验收、约束与本轮风险：已由 verification_commands.covers 覆盖的条目不重复填写；其他条目在 verification_reviews 中明确 agent_review、existing_evidence 或 not_verified 及依据。没有命令仍须说明逐项目标的处置。",
            "先用 status 判断项目是否已经采用长期权威。baseline_id 或 observed_commit 为空表示新项目：若本事项会修改或交付任何仓库文件，change_context.change_kind 必须为 create_project，并在评估中一次声明六个权威位置、计划创建项目配置、工程基线和五类长期权威；方案确认前只规划，不要抢先创建或猜写这些文件，也不要读取任何 project.* 条件引用。只有明确不产生仓库交付的 A0 事项可以不建立长期权威。",
            "首次接入由智能编码代理调查并复用已有资料，按项目规模形成满足合同的完整基础内容，不要求负责人填表。已采用项目的小改动沿用有效权威，只安排受影响内容的更新；不为每次事项重建基础资料或强制生成 PRD、SPEC 等阅读产物。",
            "计划操作命中调查提交中已采用实现对齐的受管源码范围时，必须规划实现对齐更新及其根文件、四份底账和工程基线；程序在评估提交和方案接受前按仓库身份与登记路径检查，业务含义或模块职责未变不能代替源码观察更新。程序不判断新的源码归属和语义对齐是否正确。",
            "新项目方案若要求在编码前检查负责人已接受但尚未提交的长期权威候选，精确验证命令必须使用 strixnova status --working-tree；默认 status 只读不可变本地集成版本，不能证明工作树候选已采用。工作树候选检查只证明确定性结构和引用，不证明语义。",
            "已有正式项目先读 project.engineering；只有方法采用状态与当前真实影响相交时才渐进读取领域目录，只有当前设计或对齐判断确实需要时才读取架构和实现对齐。",
            "只要方案会修改或交付仓库文件，change_context.formal_implementation 就必须为 true；false 只适用于明确受管但不产生仓库交付的结果，不是智能编码代理调查项目的模式。",
            "正式实施的 investigation_ref 指向配置仓库不可变提交；repository_scope 明确本次各仓库的身份、modify/read 角色、各自调查提交及修改仓库本地目标分支。所需仓库须已绑定，外部依赖只能读取；不把配置提交替代其他仓库的版本。",
            "操作、来源、验证命令及有路径的 ADR、领域事实变更和外部观察计划使用 repository_id 与内部路径；范围唯一时程序可以补全省略的身份。多仓库交付的 repository_order 恰好覆盖各修改仓库；切片通过事项内唯一引用组织依赖，只有一个整体方案确认。",
            "多仓库方案接受后，按 CurrentAction 准备各仓库工作区、实施和验证；整体实际结果接受后，再按已确认顺序逐仓库交付。repository_deliveries 中的规划责任不代表对应执行已经完成。SourceReference 的 observed_ref 必须是实际 working_tree 或可解析提交，不得编造调查标签。",
            "普通工程事实的 evidence_refs 只能使用 direction 或 source_references 中已声明的 reference_id；已有正式项目还可原样使用 project.engineering 返回的 baseline_refs。不得把 direction_confirmation、文件路径或临时说明当作证据引用。",
            "architecture（架构）、interface（接口）或 data（数据）被列为 affected（受影响）或 unknown（未知）时，基础治理要求真实的方案取舍、设计决定和 ADR（架构决策记录）候选判断；不能只写影响结论。",
            "修订当前已采用的产品、领域、目标架构或实现对齐时，必须提交 authority_change_set（权威变更集），精确绑定这四类当前修订、候选修订、具体变化和所有必需下游处置；它不是新的长期权威，新项目首次完整建模不得使用它绕过全量候选。",
            "产品范围、领域或架构被列为 affected（受影响）或 unknown（未知），或存在权威变更集时，必须提交 semantic_review（语义复核），完整覆盖八个审查视角；影响程度和内容由智能编码代理判断，程序不得声称语义已被机器证明。",
            "semantic_review（语义复核）中需要项目负责人决定的发现，只能引用已确认方向或项目基线中的已确认决定；来源材料、文件证据和智能编码代理自己的结论都不能冒充负责人决定。",
            "正式实施必须用 implementation_slices（实施切片）让每项文件操作和验证命令只归属一个切片，并声明上游追溯、前置关系、并行条件、完成标准和恢复办法；简单事项可以只有一个切片。",
            "必须提交 owner_view（负责人视图）：decision_support 用自然语言说明当前问题、为何重要、影响、推荐、替代选择、不处理后果、下一步和最多五个必要问题；engineering_context 保留产品与领域变化、架构责任、实施顺序、风险、验证和未知；程序只检查结构，不判断这些语义是否正确。",
            "不得编造项目事实、验证结果、领域采用或用户决定；无法证明的内容进入未知项、限制或阻断。",
            "提交的 direction_version 必须来自已接受的方向确认记录。",
        ]
    if action_type == "revise_engineering_plan":
        schema, roots = _replan_schema()
        return schema, roots, [
            "根据当前 blockers 判断应修订方向还是完整工程评估；只提交其中一个完整合同。",
            "上游方向改变时先修订方向并重新确认；方向未改变时提交完整的新工程评估修订。",
            "先判断失效事实属于产品、领域、目标架构、工程方案还是当前实现；只退回真正失效的上游层，并重做其全部受影响下游、语义审查和实施切片。",
        ]
    if action_type == "begin_implementation":
        schema, roots = _begin_implementation_schema()
        return schema, roots, [
            "target_ref 必须是要接收最终本地合入的现有本地引用。",
            "本动作只创建隔离工作区，不代表已实施、已验证或已交付。",
        ]
    if action_type == "author_project_authority_candidate":
        schema, roots = _empty_schema("strixnova.project-authority-presentation.v1")
        return schema, roots, [
            "按 authority_kind 和已确认方案先起草或修订这一类完整长期权威候选；程序只检查结构、精确引用和上游确认，不编写语义正文。",
            "候选必须达到 ready_for_confirmation（等待确认）状态，再使用公开 authority 命令且不传 --input；省略 --authority-kind 时程序使用当前动作的 authority_kind，也可显式传入该种类。程序会记录一次不可混同于确认的独立展示事件并前进事项版本。",
            "候选文件尚不存在或结构未闭合时保持本动作，继续补齐候选；不得把读取失败冒充负责人退回。",
        ]
    if action_type == "review_project_authority_candidates":
        schema, roots = _resource_schema(
            "project-authority-review-submission-v1.schema.json"
        )
        return schema, roots, [
            "逐一读取完整候选包中的产品、领域、目标架构、工程政策和实现对齐规范正文，按八个视角形成只读语义复核；程序只校验结构、精确候选引用和正文散列，不替代智能编码代理判断语义。",
            "semantic_review.reviewed_refs 必须精确覆盖当前动作提供的五类候选正文身份；任何候选正文变化都会使本复核失效并要求重新复核。",
            "未闭合的高影响发现仍会阻断；允许进入实施的低、中影响开放发现必须在后续实际结果限制中逐项保留。",
            "使用公开 authority 命令一次提交这份复核；本动作不请求也不记录项目负责人决定。",
        ]
    if action_type == "confirm_project_authority_candidates":
        schema, roots = _authority_confirmation_bundle_schema(action)
        return schema, roots, [
            "上一事项版本已经记录完整候选展示；本动作只处理同一指纹的项目负责人独立决定。",
            "集中解释各类已展示候选的内容与独立接受范围，允许负责人用一条自然答复逐类决定，或明确接受整包。不要求固定口令、前缀、内部字段或重复接受未变化内容。",
            "使用公开 authority 命令一次提交完整 decisions；优先使用固定上下文的 action 接口，由程序带入每项 candidate_fingerprint；已有原始消息来源通过 user-message-file 或结构化接口传入，user_confirmation 原样保存，agent_decision 分别记录该候选的 accept 或 request_changes 及 reason。同一答复明确覆盖整包时各项保留同一原话；遗漏、附条件或指向不清时先修订或澄清，不补造接受或扩大授权。",
            "程序会按产品、领域、目标架构、工程政策的依赖顺序原子复核并机械写入确认元数据；任一候选或上游绑定变化都会使整包停止并恢复文件。",
        ]
    if action_type == "complete_implementation_slice":
        schema = _object_schema(
            schema_id="strixnova.implementation-slice-completion.v1",
            required=(
                "schema_version",
                "slice_id",
                "completion_summary",
                "semantic_content_machine_proven",
            ),
            properties={
                "schema_version": {
                    "const": "strixnova.implementation-slice-completion.v1"
                },
                "slice_id": _TEXT,
                "completion_summary": _TEXT,
                "semantic_content_machine_proven": {"const": False},
            },
        )
        return schema, [], [
            "本入口只适用于工程方案明确没有验证命令的当前实施切片。",
            "先完成当前切片的全部计划操作并按完成标准人工复核，再提交真实完成摘要。",
            "程序会先检查累计工作树路径，后续切片路径或计划外路径仍会被拒绝。",
            "本记录不证明文档或工程语义正确，semantic_content_machine_proven 必须为 false。",
        ]
    if action_type in {
        "investigate_and_report",
        "present_actual_result",
        "present_actual_result_after_conflict",
    }:
        schema, roots = _resource_schema("actual-result-v1.schema.json")
        roots.append("replan-request-v1.schema.json")
        return schema, roots, [
            "只报告实际发生的结果、真实验证回执、偏差和限制；未运行内容不得写成已通过。",
            "审阅前读取 engineering.review_subject，提交其 subject_ref 为 review_subject_ref；代码、方案或声明输入变化时必须重新核对，不能在提交时给旧结论补认新身份。",
            "实际结果必须逐项回应工程方案要求，并引用当前事项已有的真实证据。",
            "命令目标从已确认 covers 与当前回执派生。非命令目标和每个自动化行为例子的断言充分性审阅，都必须逐项提交 verification_review_results，区分 Agent 审阅支持、未获支持与未核验；target_verification 是程序派生摘要，不能替换它来宣称语义已证明。",
            "明确延期承诺写入 follow_up_items，绑定本结果 limitations 中的具体条目、责任、日期或业务复查条件及完成标准；接受限制而结束跟进使用 accepted_limitation。普通证明边界文字不自动生成跟进事项。",
            "方向通过 follows_up 的 follow_up_refs 承接原问题后，必须逐项提交 follow_up_results，绑定原事项、结果展示版本、条目身份和刚查询的 expected_version。仅有后续事项完成不代表原问题解决，处置须等待实际结果接受。",
            "必须逐项闭合工程方案中的适用治理规则；满足要有证据，部分满足、不满足或未知要同时保留缺口和纠偏，且不得声称机器证明语义或外部认证。",
            "向项目负责人展示时按关注点说明目的、产品与领域变化、架构责任、实际实施顺序、最高影响风险、真实验证与可观察效果、未知与限制，以及当前唯一决定；不得照抄方案中的未来时负责人视图。",
            "若实际改动超出已确认 operations（文件操作），不得把计划漂移藏进实际结果：误改应恢复；必要改动应通过当前 submit（提交）入口提交 strixnova.replan-request.v1（重新规划请求第一版），进入重新规划后再读取原工程评估并形成完整修订。",
        ]
    if action_type in {
        "implement_and_verify",
        "investigate_and_verify",
        "verify_after_git_conflict",
        "implement_and_verify_conflict_resolution",
    }:
        schema, roots = _verification_schema()
        return schema, roots, [
            "command_id 必须取自当前工程方案列出的验证命令；程序只运行该精确已确认命令。",
            "当前动作包含实施切片引用时，先读取该切片，只实施其文件操作并只运行分配给该切片的验证命令；前置切片未完成时不得提前执行后续切片。",
            "程序会在运行或评估验证前核对累计 Git（版本管理系统）改动；如果出现只属于后续切片的路径，会要求恢复提前改动或重新规划，不能靠先改完再补回执绕过顺序。",
            "如果出现不属于任何已确认工程操作的路径，程序会单独报告 unplanned_repository_change（计划外仓库改动）；验证产生的缓存等一次性副产物应精确清理，误改应恢复，必要的持久改动必须先重新规划。",
            "run 完成后必须重新读取当前动作，并单独提交验证后代码变化判断。",
            "不能运行时使用 not_run 并给出真实原因和限制，不得伪造通过。",
        ]
    if action_type == "assess_verification_change":
        schema, roots = _verification_assessment_schema()
        return schema, roots, [
            "读取当前动作列出的精确验证回执，检查命令完成后相关代码是否变化以及是否需要重跑。",
            "评估前先检查工作树；验证命令产生且不属于工程操作的缓存等一次性副产物应精确清理。程序不会自动删除，也不会把它们误称为后续切片实现。",
            "该判断由智能编码代理基于真实版本状态提交，程序不得代为推断。",
        ]
    if action_type == "create_atomic_commits":
        schema, roots = _merge_schema("strixnova.commit-delivery-input.v1")
        return schema, roots, [
            "先读取 delivery.authority_adoption（交付阶段权威采用记录），然后调用一次 delivery（交付命令）并提交空对象；需要机械定档时由程序只更新实现对齐及工程基线的精确元数据，并返回新的建设事项版本，智能编码代理不得手工改写这些字段。",
            "记录中的 accepted_candidate_snapshot_verified 必须为 true；若 blocking_issues "
            "提示‘已接受实际结果之后发生正文变化’，只能恢复到已接受快照，或重新规划、"
            "重新验证并形成新的实际结果，不得覆盖快照或继续提交。",
            "普通 ActualResult（实际结果）确认只能授权机械采用精确 ImplementationAlignment（实现对齐）候选，不能确认或采用 ProductDefinition（产品定义）、DomainModel（领域模型）、TargetArchitecture（目标架构）或 EngineeringPolicy（工程政策）；这些长期权威必须在实施前通过独立决定完成确认和采用。",
            "如果 delivery（交付命令）返回 authority_adoption_finalized（权威采用已定档），重新读取 CurrentAction（当前动作），使用返回的新版本继续；任何 blocking_issues（阻断问题）都不得由智能编码代理擅自改元数据消除。",
            "先在事项隔离工作区内组织只包含已确认实际结果的原子本地提交；不得推送远程。",
            "提交完成后调用 delivery；程序将核对结果提交并推进本地合入。",
        ]
    if action_type == "integrate_target":
        schema, roots = _merge_schema("strixnova.integration-input.v1")
        return schema, roots, [
            "调用 delivery 只执行当前事项已经授权的本地合入；不得执行远程操作。",
        ]
    if action_type == "complete_git_merge":
        schema, roots = _empty_schema("strixnova.complete-merge-input.v1")
        return schema, roots, [
            "先在目标工作树完成当前原生 Git 冲突合并提交，再调用 delivery 记录真实结果。",
            "不得跳过冲突复测或伪造合并提交。",
        ]
    if action_type == "cleanup_work_area":
        schema, roots = _empty_schema("strixnova.cleanup-input.v1")
        return schema, roots, [
            "调用 delivery 只清理当前事项已经完成本地合入的受管工作区和分支。",
        ]
    if action_type == "resolve_git_conflict":
        schema, roots = _conflict_resolution_schema()
        return schema, roots, [
            "检查真实冲突解决内容，明确是否改变用户可见结果或已确认方向、方案。",
            "retest_command_ids 只列工程方案中确实受冲突解决影响的验证命令；"
            "没有适用命令时可为空数组，但仍必须接受精确文件快照复核。",
        ]
    if action_type == "assess_target_advance":
        schema, roots = _resource_schema("target-advance-assessment-v1.schema.json")
        return schema, roots, [
            "比较调查版本与当前目标版本，只判断目标推进是否影响已确认方向或工程方案。",
            "语义受影响时必须触发重规划，不得绕过版本变化继续实施。",
        ]
    if action_type == "decide_cancelled_work":
        schema, roots = _cancel_decision_schema()
        return schema, roots, [
            "由用户选择保留、转移或丢弃未合入工作；智能编码代理不得代替用户决定。",
            "丢弃是破坏性操作，只有用户明确同意时 confirm_discard 才能为 true。",
        ]
    if action_type == "resume_integrate":
        schema, roots = _empty_schema("strixnova.resume-integration-input.v1")
        return schema, roots, [
            "读取 pending_effect 和 git 记录后调用 delivery；程序只恢复同一个已占位的本地合入。",
        ]
    if action_type == "resume_prepare_work_area":
        schema, roots = _empty_schema("strixnova.resume-work-area-input.v1")
        return schema, roots, ["读取原 pending_effect 后调用 delivery；沿用精确仓库、目标和位置核对实际 Git 工作区，不另建分支。"]
    if action_type == "resume_verification":
        schema = _object_schema(schema_id="strixnova.resume-verification-input.v1", required=("command_id", "mode"), properties={"command_id": _TEXT, "mode": {"const": "run"}})
        return schema, [], ["使用原命令身份调用 verify，接收已保存回执而不重复执行；缺少回执保留未知，未收口进程先通过现有维护入口核验停止。"]
    if action_type == "resume_cleanup":
        schema, roots = _empty_schema("strixnova.resume-cleanup-input.v1")
        return schema, roots, [
            "读取 pending_effect 和 git 记录后调用 delivery；程序只恢复同一个已占位的安全清理。",
        ]
    if action_type == "resume_cancel_cleanup":
        schema = _object_schema(
            schema_id="strixnova.resume-cancel-cleanup-input.v1",
            required=("reason",),
            properties={"reason": _TEXT},
        )
        return schema, [], [
            "从 pending_effect 复制原取消原因后调用 cancel；不得改变已经占位的取消意图。",
        ]
    if action_type == "resume_cancel_discard":
        schema, roots = _cancel_decision_schema()
        return schema, roots, [
            "从 pending_effect 复制原丢弃决定后调用 cancel；不得扩大丢弃范围。",
        ]
    raise PublicInputContractError(f"当前动作缺少公开输入合同：{action_type}")


def input_contract_for(action: Mapping[str, Any]) -> dict[str, Any]:
    """Return the exact public payload contract for one projected action."""

    action_type = str(action.get("action_type") or "").strip()
    input_kind = str(action.get("input_kind") or "").strip()
    intent = str(action.get("intent") or "").strip()
    contract_ref = str(action.get("input_contract_ref") or "").strip()
    expected_ref = f"input.contract:{action_type}"
    if not action_type or not input_kind or contract_ref != expected_ref:
        raise PublicInputContractError("CurrentAction（当前动作）的输入合同引用无效")
    command = (
        "authority"
        if action_type
        in {
            "author_project_authority_candidate",
            "confirm_project_authority_candidates",
        }
        else intent
    )
    if command not in {
        "submit",
        "confirm",
        "delivery",
        "verify",
        "cancel",
        "authority",
    }:
        raise PublicInputContractError(f"当前动作没有可公开的命令意图：{intent}")
    payload_schema, root_names, specific_instructions = _contract_schema_for(
        action
    )
    documents = _schema_bundle(root_names)
    recovery_routes: list[dict[str, Any]] = []
    if action_type in {
        "investigate_and_report",
        "present_actual_result",
        "present_actual_result_after_conflict",
    }:
        recovery_routes.append(
            {
                "trigger_code": "unplanned_repository_change",
                "command": "submit",
                "payload_schema": {
                    "$ref": "replan-request-v1.schema.json"
                },
                "instructions": [
                    "误改应恢复并重新验证；实现已确认责任所必需的改动不得删除或隐瞒。",
                    "必要改动使用当前事项和当前版本提交重新规划请求；进入重新规划后读取原工程评估，形成包含新增路径的完整修订。",
                ],
            }
        )
        recovery_routes.append({
            "trigger_code": "review_subject_changed",
            "command": "delivery",
            "payload_schema": {"$ref": "actual-result-v1.schema.json"},
            "instructions": [
                "通过 next 读取 engineering.review_subject，核对发生变化的代码、规则或证据；不得只给旧结论替换新身份。",
                "在原有范围内完成受影响复核后提交新的实际结果；若方案已失效，沿既有 replan 路径处理。",
            ],
        })
    instructions = [
        "命令必须使用当前动作给出的 work_item_id（事项标识）和 work_item_version（事项版本）；写入后复用返回的 next；未返回 next 时再读取当前动作，不复用旧版本。",
        "payload（输入载荷）必须符合本合同；不得读取安装包内部源码、内部 Schema（结构契约）或测试夹具来猜字段。",
        *specific_instructions,
    ]
    return {
        "schema_version": INPUT_CONTRACT_SCHEMA,
        "contract_ref": contract_ref,
        "action_type": action_type,
        "input_kind": input_kind,
        "intent": intent,
        "command": command,
        "payload_schema": deepcopy(payload_schema),
        "referenced_schemas": deepcopy(documents),
        "recovery_routes": recovery_routes,
        "instructions": instructions,
    }


__all__ = [
    "INPUT_CONTRACT_SCHEMA",
    "PublicInputContractError",
    "input_contract_for",
]
