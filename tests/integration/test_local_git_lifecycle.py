from __future__ import annotations

from tests.support.implementation_alignment import observation_coverage as current_observation_coverage

from tests.support.project_context import FRONTEND

from tests.support.project_configuration import configure_repository

from collections.abc import Callable
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from click.testing import CliRunner
import pytest
import yaml

from strixnova.cli import main
from strixnova.git_project_reader import GitProjectReader
from strixnova.git_workspace import GitWorkspace
from strixnova.host_adapter import LocalHostAdapter
from strixnova.implementation_observation import observe_implementation
from strixnova.project_authority_consistency import ProjectAuthorityConsistency
from strixnova.verification_runner import (
    VerificationRunner,
    normalize_verification_commands,
)
from strixnova.work_item_read_model import WorkItemReadModel
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.governance_assessment import (
    add_capability_adr_assessment,
    assessment_fixture,
    bind_assessment_to_work_item,
    new_project_adr_assessment,
    refresh_single_slice,
    semantic_review_fixture,
    satisfied_governance_rule_results,
)
from tests.support.project_baseline import (
    TEST_ALIGNMENT_ID,
    TEST_CONTEXT_FACT_ID,
    TEST_DOMAIN_MODEL_ID,
    TEST_TERM_FACT_ID,
    adopt_portable_ddd,
    portable_project_baseline,
)


pytestmark = pytest.mark.slow


def _git(repo: Path, *arguments: str) -> str:
    environment = dict(os.environ)
    environment["GIT_TERMINAL_PROMPT"] = "0"
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return completed.stdout.strip()


def _observation_coverage(project: Path, alignment: dict, *, observed_ref: str | None = None) -> dict:
    return current_observation_coverage(project, alignment, observed_ref=observed_ref)


def _observation_coverage_for_content(alignment: dict, content: str) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        project = Path(directory)
        _git(project, "init", "-b", "main")
        (project / "src.py").write_text(content, encoding="utf-8")
        _git(project, "add", "src.py")
        return _observation_coverage(project, alignment)


def _invoke(runner: CliRunner, project: Path, *arguments: str) -> dict:
    from tests.support.review_subject import bind_subject_arguments
    values = list(arguments)
    command = values[0]

    def take(option: str, default: str | None = None) -> str | None:
        if option not in values:
            return default
        index = values.index(option)
        value = values[index + 1]
        del values[index : index + 2]
        return value

    def take_flag(option: str) -> bool:
        if option not in values:
            return False
        values.remove(option)
        return True

    if command == "intake":
        payload = {"title": take("--title"), "request": take("--request")}
        values.extend(["--input", json.dumps(payload, ensure_ascii=False)])
    elif command == "confirm":
        take("--kind")
        accepted = take_flag("--accepted")
        rejected = take_flag("--rejected")
        work_item_id = values[values.index("--work-item-id") + 1]
        challenge = WorkflowAuthority(project).get(work_item_id)[
            "current_action"
        ]["confirmation_challenge"]
        summary = str(take("--summary") or "需要修正候选内容")
        user_confirmation = (
            "同意当前候选，可以继续。"
            if accepted and not rejected
            else summary
        )
        payload = {
            "candidate_fingerprint": challenge["candidate_fingerprint"],
            "user_confirmation": user_confirmation,
            "agent_decision": {
                "decision": "accept" if accepted and not rejected else "request_changes",
                "reason": "负责人明确接受当前候选" if accepted and not rejected else summary,
            },
        }
        values.extend(["--input", json.dumps(payload, ensure_ascii=False)])
    elif command == "delivery":
        raw_payload = take("--input")
        payload = json.loads(raw_payload) if raw_payload is not None else {}
        for option, field in (
            ("--target-ref", "target_ref"),
            ("--worktree-path", "worktree_path"),
            ("--merge-strategy", "merge_strategy"),
        ):
            selected = take(option)
            if selected is not None:
                payload[field] = selected
        values.extend(["--input", json.dumps(payload, ensure_ascii=False)])
    elif command == "verify":
        payload = json.loads(str(take("--input")))
        payload["command_id"] = take("--command-id")
        execution_area = take("--execution-area")
        if execution_area is not None:
            payload["execution_area"] = execution_area
        values.extend(["--input", json.dumps(payload, ensure_ascii=False)])
    elif command == "cancel":
        reason = take("--reason")
        decision = take("--decision")
        if reason is not None:
            payload = {"reason": reason}
        else:
            payload = {
                "decision": decision,
                "details": json.loads(str(take("--details", "{}"))),
                "confirm_discard": take_flag("--confirm-discard"),
            }
        values.extend(["--input", json.dumps(payload, ensure_ascii=False)])
    result = runner.invoke(
        main,
        bind_subject_arguments(project, [*values, "--project-dir", str(project)]),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output.strip())
    next_step = payload.get("next")
    if isinstance(next_step, dict) and next_step.get("work_item_id"):
        payload["work_item"] = WorkflowAuthority(project).get(
            next_step["work_item_id"]
        )
    return payload


def _direction_context_binding(
    runner: CliRunner,
    project: Path,
    work_item_id: str,
) -> dict:
    context = _invoke(
        runner,
        project,
        "next",
        "--work-item-id",
        work_item_id,
        "--record",
        "project.direction_context",
    )["next"]["records"]["project.direction_context"]
    if context["context_ref"] is None:
        return {
            "context_ref": None,
            "capability_refs": [],
            "guardrail_dispositions": [],
            "assumptions": [],
        }
    return {
        "context_ref": context["context_ref"],
        "capability_refs": [
            context["capability_catalog"][0]["capability_ref"]
        ],
        "guardrail_dispositions": [
            {
                "decision_ref": guardrail["decision_ref"],
                "disposition": "applies",
                "reason": "本集成场景继续遵守这项已确认产品护栏。",
            }
            for guardrail in context["guardrails"]
        ],
        "assumptions": [],
    }


def _mark_upstream_authorities_ready(
    project: Path,
    baseline: dict,
    *,
    kinds: tuple[str, ...] = (
        "product_definition",
        "domain_model",
        "target_architecture",
        "engineering_policy",
    ),
) -> None:
    for kind in kinds:
        root = project / baseline["authority_refs"][kind]["path"]
        document = yaml.safe_load(root.read_text(encoding="utf-8"))
        document["revision"].update(
            {
                "status": "ready_for_confirmation",
                "confirmed_by_owner_id": None,
                "confirmed_on": None,
            }
        )
        root.write_text(
            yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        baseline["authority_refs"][kind]["revision_id"] = document[
            "revision"
        ]["revision_id"]
        baseline["authority_refs"][kind]["status"] = {
            "revision_status": "ready_for_confirmation",
            # The working-tree baseline is a proposal layered over the
            # currently adopted baseline.  It may point at the candidate
            # revision, but it must not pretend the adoption event already
            # changed before the owner decision is recorded.
            "adoption_status": "current",
        }
    if "domain_model" in kinds:
        for path in sorted(
            (project / "docs" / "domain" / "sources").glob("*.yaml")
        ):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            for fact in document.get("facts") or []:
                if fact.get("status") != "retired":
                    fact["status"] = "ready_for_confirmation"
            path.write_text(
                yaml.safe_dump(document, allow_unicode=True, sort_keys=False),
                encoding="utf-8",
            )
    affected_kinds = list(kinds)
    affected_kinds.extend(
        kind
        for kind, reference in baseline["authority_refs"].items()
        if kind not in affected_kinds
        and (
            reference.get("status", {}).get("adoption_status")
            == "under_review"
            or reference.get("status", {}).get("revision_status")
            != "confirmed"
        )
    )
    baseline["review_state"] = {
        "required": True,
        "reasons": ["上游长期权威候选等待独立负责人确认。"],
        "affected_authority_kinds": affected_kinds,
    }
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    if baseline_path.exists():
        baseline_path.write_text(
            yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )


def _adopt_portable_test_project(project: Path, *, baseline_id: str) -> dict:
    """Create and commit a drift-free adopted authority chain for formal work."""

    baseline = portable_project_baseline(
        project,
        baseline_id=baseline_id,
        artifacts=[],
    )
    identities = adopt_portable_ddd(project, baseline)
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(project, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')

    _git(project, "add", ".")
    _git(project, "commit", "-m", "adopt portable project authorities")
    observation_commit = _git(project, "rev-parse", "HEAD")
    source_digest = hashlib.sha256(
        GitProjectReader(project).read_canonical_bytes(
            "src.py",
            "测试行为文件",
        )
    ).hexdigest()
    alignment_path = project / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    ownership_path = project / alignment["artifact_paths"]["source_ownership"]
    ownership = yaml.safe_load(ownership_path.read_text(encoding="utf-8"))
    ownership["records"][0]["sha256"] = source_digest
    ownership_path.write_text(
        yaml.safe_dump(ownership, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment["code_snapshot"].update(
        {'repositories': [{'repository_id': FRONTEND, 'base_commit': observation_commit, 'worktree_state': 'clean'}], 'governed_source_manifest_sha256': hashlib.sha256(f'{FRONTEND}:src.py:{source_digest}\n'.encode('utf-8')).hexdigest()}
    )
    alignment["observation_coverage"] = _observation_coverage(
        project,
        alignment,
    )
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    baseline["code_version"] = {'repositories': [{'repository_id': FRONTEND, 'base_commit': observation_commit, 'worktree_state': 'clean'}]}
    baseline["review_state"] = {
        "required": False,
        "reasons": [],
        "affected_authority_kinds": [],
    }
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    _git(project, "add", "docs")
    _git(project, "commit", "-m", "bind portable implementation evidence")
    _git(project, "branch", "-M", "main")
    return baseline


def _accept_upstream_authorities(
    runner: CliRunner,
    project: Path,
    item: dict,
    *,
    kinds: tuple[str, ...] = (
        "product_definition",
        "domain_model",
        "target_architecture",
        "engineering_policy",
    ),
) -> dict:
    current = item
    decisions: list[dict[str, str]] = []
    for kind in kinds:
        candidate = _invoke(
            runner,
            project,
            "authority",
            "--work-item-id",
            current["work_item_id"],
            "--authority-kind",
            kind,
            "--version",
            str(current["version"]),
        )
        challenge = candidate["confirmation_challenge"]
        current = WorkflowAuthority(project).get(current["work_item_id"])
        decisions.append(
            {
                "authority_kind": kind,
                "candidate_fingerprint": challenge[
                    "candidate_fingerprint"
                ],
                "user_confirmation": "I accept the displayed candidate.",
                "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
            }
        )
    assert current["current_action"]["action_type"] == (
        "review_project_authority_candidates"
    ), {
        "action_type": current["current_action"]["action_type"],
        "authority_kind": current["current_action"].get("authority_kind"),
        "authority_kinds": current["current_action"].get("authority_kinds"),
        "missing_authority_kinds": current["current_action"].get(
            "missing_authority_kinds"
        ),
    }
    review_candidate = _invoke(
        runner,
        project,
        "authority",
        "--work-item-id",
        current["work_item_id"],
        "--version",
        str(current["version"]),
    )["candidate_bundle"]
    reviewed = _invoke(
        runner,
        project,
        "authority",
        "--work-item-id",
        current["work_item_id"],
        "--input",
        json.dumps(
            {
                "schema_version": (
                    "strixnova.project-authority-review-submission.v1"
                ),
                "semantic_review": semantic_review_fixture(
                    *review_candidate["reviewed_refs"]
                ),
            },
            ensure_ascii=False,
        ),
        "--version",
        str(current["version"]),
    )
    current = WorkflowAuthority(project).get(current["work_item_id"])
    assert reviewed["project_authority_review"]["candidate_bundle"] == (
        review_candidate
    )
    assert current["current_action"]["action_type"] == (
        "confirm_project_authority_candidates"
    )
    current = _invoke(
        runner,
        project,
        "authority",
        "--work-item-id",
        current["work_item_id"],
        "--input",
        json.dumps({"decisions": decisions}, ensure_ascii=False),
        "--version",
        str(current["version"]),
    )["work_item"]
    return current


def _plan_delivery_order_review(assessment: dict, *, target: str = "direction.constraint:DIRCON-2222222222222222") -> None:
    # Running the feature test does not observe confirmation/commit ordering.
    for command in assessment["verification_commands"]:
        command["covers"] = [reference for reference in command["covers"] if reference != target]
    assessment.setdefault("verification_reviews", []).append({
        "target_ref": target, "method": "agent_review",
        "reason": "Review actual verification receipts, the unchanged Git base and the confirmation gates before allowing result commits; disclose later retests still pending.",
        "evidence_refs": ["direction"],
    })


def _delivery_order_review_result(item: dict, *, target: str = "direction.constraint:DIRCON-2222222222222222") -> list[dict]:
    data = item["data"]
    assert _git(Path(data["git"]["worktree_path"]), "rev-parse", "HEAD") == data["git"]["base_commit"]
    assert not (data.get("actual_result_confirmation") or {}).get("accepted")
    receipt = data["verifications"][-1]
    assert receipt["code_change_assessment"]["needs_retest"] is False
    assert receipt["result"] in {"passed", "not_run"}
    return [{
        "target_ref": target,
        "outcome": "supported" if receipt["result"] == "passed" else "not_verified",
        "rationale": (
            "Verification passed while HEAD remains at the original base; no result commit or result acceptance has occurred. The following test assertions exercise the confirmation and premature-commit guards."
            if receipt["result"] == "passed" else
            "HEAD remains at the original base and the receipt explicitly says not_run. The initial result discloses this limitation; conflict-result verification has not happened yet."
        ),
        "evidence_refs": [receipt["receipt_id"]],
    }]


def _start_formal_work_item(
    runner: CliRunner,
    project: Path,
    *,
    title: str,
    assessment: dict,
    worktree_path: Path | None = None,
    constraint_statement: str = "先验证和确认，再形成提交",
) -> dict:
    assessment["investigation_ref"] = "main"
    for reference in assessment["source_references"]:
        if reference.get("observed_ref") == "working_tree":
            reference["observed_ref"] = "main"
    item = _invoke(
        runner,
        project,
        "intake",
        "--title",
        title,
        "--request",
        title,
    )["work_item"]
    identifier = item["work_item_id"]
    decision_context = _direction_context_binding(
        runner,
        project,
        identifier,
    )
    direction = {
        "direction": {
            "schema_version": "strixnova.direction-decision.v1",
            "decision_context": decision_context,
            "goal": title,
            "scope": [
                {
                    "requirement_id": "DIRREQ-1111111111111111",
                    "statement": "工程评估声明的本地改动",
                }
            ],
            "non_goals": ["远程 Git 操作"],
            "constraints": [
                {
                    "constraint_id": "DIRCON-2222222222222222",
                    "statement": constraint_statement,
                }
            ],
            "tradeoffs": ["Git 原生负责分支、合并和内容冲突"],
            "acceptance": [
                {
                    "acceptance_id": "DIRACC-3333333333333333",
                    "statement": "按工程评估中的验证安排报告真实结果",
                    "requirement_refs": ["DIRREQ-1111111111111111"],
                    "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
                }
            ],
        },
        "ready_for_confirmation": True,
    }
    item = _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(direction, ensure_ascii=False),
        "--version",
        str(item["version"]),
    )["work_item"]
    item = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "direction",
        "--accepted",
        "--summary",
        "方向确认",
        "--version",
        str(item["version"]),
    )["work_item"]
    bind_assessment_to_work_item(assessment, item)
    item = _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(assessment, ensure_ascii=False),
        "--version",
        str(item["version"]),
    )["work_item"]
    item = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "engineering_plan",
        "--accepted",
        "--summary",
        "工程方案确认",
        "--version",
        str(item["version"]),
    )["work_item"]
    implement_arguments = [
        "delivery",
        "--work-item-id",
        identifier,
        "--target-ref",
        "main",
        "--version",
        str(item["version"]),
    ]
    if worktree_path is not None:
        implement_arguments.extend(["--worktree-path", str(worktree_path)])
    return _invoke(runner, project, *implement_arguments)["work_item"]


def _item_with_work_area(
    runner: CliRunner,
    project: Path,
    title: str,
) -> tuple[dict, dict]:
    assessment = assessment_fixture(project)
    # Cancellation is independent of source-alignment delivery. Keep the
    # planned operation outside the governed source scope; dirty work is still
    # created below and must be preserved by the cancellation path.
    assessment["operations"][0].update(action="create", path="work-notes.txt")
    assessment["verification_commands"][0]["argv"][0] = sys.executable
    if _git(project, "status", "--porcelain"):
        _git(project, "add", "src.py")
        _git(project, "commit", "-m", "test: add governance source fixture")
    item = _start_formal_work_item(
        runner,
        project,
        title=title,
        assessment=assessment,
    )
    return item, item["data"]["git"]


def _complete_linked_delivery(
    runner: CliRunner,
    project: Path,
    item: dict,
    *,
    changes: dict[str, str],
    long_lived_refs: list[dict] | None = None,
    method_results_factory: Callable[[str], list[dict]] | None = None,
    domain_fact_results_factory: Callable[[str], list[dict]] | None = None,
) -> dict:
    identifier = item["work_item_id"]
    worktree = Path(item["data"]["git"]["worktree_path"])

    def write_change(relative: str, content: str) -> None:
        destination = worktree / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8", newline="")

    plan = item["data"]["engineering"]["plan"]
    change_set = plan.get("authority_change_set")
    candidate_authorities = (
        change_set.get("candidate_authorities") or []
        if isinstance(change_set, dict)
        else []
    )
    planned_authority_kinds = {
        str(candidate["authority_kind"])
        for candidate in candidate_authorities
        if isinstance(candidate, dict)
        and isinstance(candidate.get("authority_kind"), str)
    }
    upstream_kinds = tuple(
        kind
        for kind in (
            "product_definition",
            "domain_model",
            "target_architecture",
            "engineering_policy",
        )
        if kind in planned_authority_kinds
    )
    authority_paths: set[str] = set()
    if planned_authority_kinds:
        base_commit = str(item["data"]["git"]["base_commit"])
        base_reader = ProjectAuthorityConsistency(
            worktree,
            observed_ref=base_commit,
        )
        base_authorities = base_reader.load()
        for kind in planned_authority_kinds:
            authority_paths.update(
                base_reader.authority_governed_paths(
                    base_authorities,
                    kind,
                )
            )
        authority_paths.update(
            str(candidate["path"])
            for candidate in candidate_authorities
            if isinstance(candidate, dict)
            and isinstance(candidate.get("path"), str)
        )
        authority_paths.add("docs/engineering/baseline.yaml")
        for relative, content in changes.items():
            if relative in authority_paths:
                write_change(relative, content)
    else:
        for relative, content in changes.items():
            write_change(relative, content)

    baseline = None
    if upstream_kinds or "implementation_alignment" in planned_authority_kinds:
        baseline = yaml.safe_load(
            (worktree / "docs" / "engineering" / "baseline.yaml").read_text(
                encoding="utf-8"
            )
        )
    if "implementation_alignment" in planned_authority_kinds:
        assert isinstance(baseline, dict)
        alignment_path = worktree / baseline["authority_refs"][
            "implementation_alignment"
        ]["path"]
        alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
        alignment["revision"].update(
            {
                "status": "draft",
                "confirmed_by_owner_id": None,
                "confirmed_on": None,
            }
        )
        alignment_path.write_text(
            yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        baseline["authority_refs"]["implementation_alignment"]["status"] = {
            "revision_status": "draft",
            "adoption_status": "current",
        }
        (worktree / "docs" / "engineering" / "baseline.yaml").write_text(
            yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    if upstream_kinds:
        assert isinstance(baseline, dict)
        _mark_upstream_authorities_ready(
            worktree,
            baseline,
            kinds=upstream_kinds,
        )
        item = _accept_upstream_authorities(
            runner,
            project,
            item,
            kinds=upstream_kinds,
        )
        baseline = yaml.safe_load(
            (worktree / "docs" / "engineering" / "baseline.yaml").read_text(
                encoding="utf-8"
            )
        )
    for relative, content in changes.items():
        if relative not in authority_paths:
            write_change(relative, content)
    executed = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps({"mode": "run", "limitations": []}, ensure_ascii=False),
        "--version",
        str(item["version"]),
    )
    receipt = executed["verification"]
    assessed = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "assess",
                "receipt_id": receipt["receipt_id"],
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "验证后没有继续修改相关实现。",
                },
            },
            ensure_ascii=False,
        ),
        "--version",
        str(executed["work_item"]["version"]),
    )["work_item"]
    awaiting = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(
            {
                "schema_version": "strixnova.actual-result.v1",
                "semantic_content_machine_proven": False,
                "effect_summary": "已完成并验证当前 WorkItem 的确认建设内容。",
                "delivered_outcomes": ["确认的本地能力已经可用。"],
                "deviations": [],
                "limitations": [],
                "verification_receipt_ids": [receipt["receipt_id"]],
                "long_lived_refs": long_lived_refs or [],
                "domain_fact_change_results": (
                    domain_fact_results_factory(receipt["receipt_id"])
                    if domain_fact_results_factory is not None
                    else []
                ),
                "method_application_results": (
                    method_results_factory(receipt["receipt_id"])
                    if method_results_factory is not None
                    else []
                ),
                "governance_rule_results": satisfied_governance_rule_results(
                    item["data"]["engineering"]["plan"],
                    receipt["receipt_id"],
                ),
            },
            ensure_ascii=False,
        ),
        "--version",
        str(assessed["version"]),
    )["work_item"]
    confirmed = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "actual_result",
        "--accepted",
        "--summary",
        "实际结果确认",
        "--version",
        str(awaiting["version"]),
    )["work_item"]
    confirmed, adoption_paths = _finalize_authority_adoption(
        runner,
        project,
        confirmed,
    )
    _git(worktree, "add", "--", *sorted({*changes, *adoption_paths}))
    _git(worktree, "commit", "-m", f"feat: complete {identifier}")
    completed = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--version",
        str(confirmed["version"]),
    )["work_item"]
    if (
        completed["status"] != "completed"
        and isinstance(completed.get("current_action"), dict)
        and completed["current_action"]["action_type"]
        == "assess_target_advance"
    ):
        completed = LocalHostAdapter(project).submit_current_action_input(
            identifier,
            {
                "schema_version": "strixnova.target-advance-assessment.v1",
                "semantic_impact": "unaffected",
                "reason": (
                    "目标分支推进没有改动本事项计划路径，也没有改变已确认结果。"
                ),
            },
            expected_version=completed["version"],
        )
        completed = _invoke(
            runner,
            project,
            "delivery",
            "--work-item-id",
            identifier,
            "--version",
            str(completed["version"]),
        )["work_item"]
    assert completed["status"] == "completed"
    return completed


def _finalize_authority_adoption(
    runner: CliRunner,
    project: Path,
    item: dict,
) -> tuple[dict, list[str]]:
    """Ask the public delivery use case to apply exact authorized metadata."""

    record = _invoke(
        runner,
        project,
        "next",
        "--work-item-id",
        item["work_item_id"],
        "--record",
        "delivery.authority_adoption",
    )["next"]["records"]["delivery.authority_adoption"]
    if record["required"] is not True:
        return item, []
    assert record["blocking_issues"] == []
    changed_paths: set[str] = {
        str(update["path"]) for update in record["authority_updates"]
    }
    for update in record["authority_updates"]:
        assert update["authority_kind"] == "implementation_alignment"
    if record["authority_updates"] or record["baseline_update"] is not None:
        changed_paths.add(str(record["baseline_path"]))
    finalized_result = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        item["work_item_id"],
        "--version",
        str(item["version"]),
    )
    assert finalized_result["steps"] == ["authority_adoption_finalized"]
    finalized_item = finalized_result["work_item"]
    finalized = finalized_item["data"]["authority_adoption"]
    assert finalized["ready_for_atomic_commits"] is True, finalized[
        "blocking_issues"
    ]
    return finalized_item, sorted(changed_paths)


def test_complete_flow_tests_before_confirmation_then_commits_and_merges(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    assessment = assessment_fixture(project)
    assessment["operations"][0].update(
        {"action": "create", "path": "feature.txt"}
    )
    assessment["verification_commands"] = [
        {
            "argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; "
                "assert Path('feature.txt').read_text() == 'ready\\n'",
            ],
            "cwd": ".",
            "run_kind": "targeted_test",
            "covers": [
                "direction.acceptance:DIRACC-3333333333333333",
                "risk_assessments[0]",
            ],
            "reason": "验证未提交工作树中的实际建设效果。",
        }
    ]
    _adopt_portable_test_project(
        project,
        baseline_id="complete-flow-project",
    )
    runner = CliRunner()

    created = _invoke(
        runner,
        project,
        "intake",
        "--title",
        "本地交付",
        "--request",
        "实现并验证一个本地能力。",
    )["work_item"]
    identifier = created["work_item_id"]
    assert _git(project, "status", "--porcelain") == ""
    _finish_complete_flow(runner, project, identifier, assessment)

    historical = runner.invoke(main, ["history", "--project-dir", str(project), "--work-item-id", identifier, "--record", "verifications"])
    assert historical.exit_code == 0, historical.output
    receipt_id = json.loads(historical.output)["history"]["records"]["verifications"]["items"][0]["receipt_id"]
    output_ref = f"output:{receipt_id}:stdout"
    output = runner.invoke(main, ["history", "--project-dir", str(project), "--work-item-id", identifier, "--record", output_ref])
    assert output.exit_code == 0, output.output
    assert json.loads(output.output)["history"]["records"][output_ref]["integrity"] == "verified_since_execution"


def test_new_project_baseline_and_adr_survive_the_complete_git_lifecycle(
    tmp_path: Path,
) -> None:
    project = tmp_path / "greenfield-project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    assessment = new_project_adr_assessment(project)
    # This direction has Git ownership and delivery-order constraints, not the
    # generic fixture's interpreter constraint. Their actual evidence differs.
    for command in assessment["verification_commands"]:
        command["covers"] = [ref for ref in command["covers"] if ref != "direction.constraint:DIRCON-2222222222222222"]
    assessment["verification_commands"][0]["covers"].append("direction.constraint:DIRCON-4444444444444444")
    _plan_delivery_order_review(assessment, target="direction.constraint:DIRCON-5555555555555555")
    _git(project, "add", "src.py")
    _git(project, "commit", "-m", "initial project skeleton")
    _git(project, "branch", "-M", "main")
    assessment["investigation_ref"] = "main"
    assessment["verification_commands"][0]["argv"] = [
        sys.executable,
        "-c",
        (
            "from pathlib import Path; "
            "from strixnova.project_authority_consistency import "
            "ProjectAuthorityConsistency; "
            "state=ProjectAuthorityConsistency('.')"
            ".load_working_tree_candidate_for('main'); "
            "assert state['structurally_consistent']; "
            "assert len(state['baseline']['authority_refs']) == 5; "
            "import subprocess; "
            "root=subprocess.run(['git','rev-parse','--show-toplevel'], check=True, capture_output=True, text=True).stdout.strip(); "
            "assert Path(root).resolve() == Path.cwd().resolve(); "
            "assert all(not ref['path'].startswith('.strixnova/') and Path(ref['path']).is_file() for ref in state['baseline']['authority_refs'].values()); "
            "assert Path('docs/adr/ADR-0100-initial-architecture.md').is_file()"
        ),
    ]
    runner = CliRunner()

    created = _invoke(
        runner,
        project,
        "intake",
        "--title",
        "建立新项目工程基线",
        "--request",
        "为新项目建立 Git 内的长期工程基线并形成初始化 ADR。",
    )["work_item"]
    identifier = created["work_item_id"]

    direction = {
        "direction": {
            "schema_version": "strixnova.direction-decision.v1",
            "decision_context": {"context_ref": None, "capability_refs": [], "guardrail_dispositions": [], "assumptions": []},
            "goal": "建立新项目首个长期工程基线和初始化 ADR",
            "scope": [
                {
                    "requirement_id": "DIRREQ-1111111111111111",
                    "statement": "项目配置",
                },
                {
                    "requirement_id": "DIRREQ-2222222222222222",
                    "statement": "工程基线",
                },
                {
                    "requirement_id": "DIRREQ-3333333333333333",
                    "statement": "初始化架构决定",
                },
            ],
            "non_goals": ["复制源码目录", "远程 Git"],
            "constraints": [
                {
                    "constraint_id": "DIRCON-4444444444444444",
                    "statement": "长期事实由 Git 管理",
                },
                {
                    "constraint_id": "DIRCON-5555555555555555",
                    "statement": "确认实际结果后再提交",
                },
            ],
            "acceptance": [
                {
                    "acceptance_id": "DIRACC-3333333333333333",
                    "statement": "基线和 ADR 在本地主分支可校验读取",
                    "requirement_refs": [
                        "DIRREQ-1111111111111111",
                        "DIRREQ-2222222222222222",
                        "DIRREQ-3333333333333333",
                    ],
                    "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
                }
            ],
            "tradeoffs": ["不在 WorkItem Authority 中复制长期工程正文"],
        },
        "ready_for_confirmation": True,
    }
    awaiting_result = _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(direction, ensure_ascii=False),
        "--version",
        "1",
    )
    direction_confirmed = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "direction",
        "--accepted",
        "--summary",
        "方向确认",
        "--version",
        "2",
    )["work_item"]
    bind_assessment_to_work_item(assessment, direction_confirmed)
    _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(assessment, ensure_ascii=False),
        "--version",
        "3",
    )
    _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "engineering_plan",
        "--accepted",
        "--summary",
        "工程方案确认",
        "--version",
        "4",
    )
    implementing = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--target-ref",
        "main",
        "--version",
        "5",
    )["work_item"]
    assert implementing["data"]["git"]["worktree_mode"] == "in_place"

    baseline = portable_project_baseline(
        project,
        baseline_id="greenfield-project",
        artifacts=[],
    )
    _mark_upstream_authorities_ready(project, baseline)
    adr_path = "docs/adr/ADR-0100-initial-architecture.md"
    baseline_file = project / "docs" / "engineering" / "baseline.yaml"
    baseline_file.parent.mkdir(parents=True, exist_ok=True)
    baseline_file.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_ref = baseline["authority_refs"]["implementation_alignment"]
    alignment_file = project / alignment_ref["path"]
    alignment = yaml.safe_load(alignment_file.read_text(encoding="utf-8"))
    candidate_alignment_revision = "ALIGNREV-5555555555555555"
    alignment["revision"] = {
        "revision_id": candidate_alignment_revision,
        "status": "draft",
        "supersedes_revision_id": alignment_ref["revision_id"],
        "confirmed_by_owner_id": None,
        "confirmed_on": None,
    }
    observation_commit = _git(project, "rev-parse", "HEAD")
    source_digest = hashlib.sha256(
        GitProjectReader(project).read_canonical_bytes(
            "src.py",
            "测试行为文件",
        )
    ).hexdigest()
    governed_manifest = hashlib.sha256(
        f"{FRONTEND}:src.py:{source_digest}\n".encode("utf-8")
    ).hexdigest()
    alignment["code_snapshot"].update(
        {'repositories': [{'repository_id': FRONTEND, 'base_commit': observation_commit, 'worktree_state': 'dirty'}], 'governed_source_manifest_sha256': governed_manifest}
    )
    alignment["observation_coverage"] = _observation_coverage(
        project,
        alignment,
    )
    baseline["code_version"] = {'repositories': [{'repository_id': FRONTEND, 'base_commit': observation_commit, 'worktree_state': 'dirty'}]}
    baseline_file.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_file.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    for supporting_path in alignment["artifact_paths"].values():
        supporting_file = project / supporting_path
        supporting = yaml.safe_load(
            supporting_file.read_text(encoding="utf-8")
        )
        supporting["alignment_revision_id"] = candidate_alignment_revision
        for source_record in supporting.get("records") or []:
            if source_record.get("path") == "src.py" and "sha256" in source_record:
                source_record["sha256"] = source_digest
        supporting_file.write_text(
            yaml.safe_dump(supporting, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    configure_repository(project, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    adr_file = project / adr_path
    adr_file.parent.mkdir(parents=True)
    adr_file.write_text(
        "---\n"
        "adr_id: ADR-0100\n"
        "title: 新项目长期工程事实保存在 Git\n"
        "decision_status: accepted\n"
        "realization_status: realized\n"
        f"originating_work_item: {identifier}\n"
        "realized_by_work_items:\n"
        f"  - {identifier}\n"
        "supersedes: []\n"
        "superseded_by: []\n"
        "---\n\n"
        "# 背景\n\n"
        "新项目需要一处可由 Git 追溯的长期工程事实入口。\n\n"
        "# 决定\n\n"
        "项目配置、工程基线和 ADR 正文保存在 Git，Authority 只保存引用。\n\n"
        "# 后果\n\n"
        "长期事实随项目分支合并，WorkItem 完成后无需保留正文副本。\n",
        encoding="utf-8",
    )

    implementing = _accept_upstream_authorities(
        runner,
        project,
        implementing,
    )
    assert len(implementing["data"]["project_authority_decisions"]) == 4

    executed = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "run",
                "limitations": [],
            },
            ensure_ascii=False,
        ),
        "--version",
        str(implementing["version"]),
    )
    receipt_id = executed["verification"]["receipt_id"]
    assert executed["verification"]["result"] == "passed"
    verified = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "assess",
                "receipt_id": receipt_id,
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "验证后未再修改基线和 ADR。",
                },
            },
            ensure_ascii=False,
        ),
        "--version",
        str(executed["work_item"]["version"]),
    )
    assert _git(project, "status", "--porcelain") != ""

    awaiting_result = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(
            {
                "schema_version": "strixnova.actual-result.v1",
                "semantic_content_machine_proven": False,
                "effect_summary": "新项目首个工程基线和初始化 ADR 已可校验读取。",
                "delivered_outcomes": ["长期工程事实已建立，并仍处于未提交工作树。"],
                "deviations": [],
                "limitations": [],
                "verification_receipt_ids": [receipt_id],
                "long_lived_refs": [
                    {
                        "artifact_id": baseline["authority_refs"][
                            "product_definition"
                        ]["product_id"],
                        "artifact_type": "product_governance",
                        "path": baseline["authority_refs"]["product_definition"][
                            "path"
                        ],
                        "relation": "introduced",
                    },
                    {
                        "artifact_id": baseline["authority_refs"]["domain_model"][
                            "model_id"
                        ],
                        "artifact_type": "domain_model",
                        "path": baseline["authority_refs"]["domain_model"]["path"],
                        "relation": "introduced",
                    },
                    {
                        "artifact_id": baseline["authority_refs"][
                            "target_architecture"
                        ]["architecture_id"],
                        "artifact_type": "architecture",
                        "path": baseline["authority_refs"]["target_architecture"][
                            "path"
                        ],
                        "relation": "introduced",
                    },
                    {
                        "artifact_id": baseline["authority_refs"][
                            "engineering_policy"
                        ]["policy_id"],
                        "artifact_type": "quality_policy",
                        "path": baseline["authority_refs"]["engineering_policy"][
                            "path"
                        ],
                        "relation": "introduced",
                    },
                    {
                        "artifact_id": baseline["authority_refs"][
                            "implementation_alignment"
                        ]["alignment_model_id"],
                        "artifact_type": "domain_alignment",
                        "path": baseline["authority_refs"][
                            "implementation_alignment"
                        ]["path"],
                        "relation": "introduced",
                    },
                    {
                        "artifact_id": "ADR-0100",
                        "artifact_type": "adr",
                        "path": adr_path,
                        "relation": "introduced",
                    },
                ],
                "verification_review_results": _delivery_order_review_result(
                    verified["work_item"], target="direction.constraint:DIRCON-5555555555555555",
                ),
                "method_application_results": [],
                "governance_rule_results": satisfied_governance_rule_results(
                    verified["work_item"]["data"]["engineering"]["plan"],
                    receipt_id,
                ),
            },
            ensure_ascii=False,
        ),
        "--version",
        str(verified["work_item"]["version"]),
    )["work_item"]
    accepted_snapshot = awaiting_result["data"]["actual_result"][
        "authority_candidate_snapshot"
    ]
    assert accepted_snapshot["schema_version"] == (
        "strixnova.authority-candidate-snapshot.v1"
    )
    assert accepted_snapshot["reported_authority_kinds"] == [
        "domain_model",
        "engineering_policy",
        "implementation_alignment",
        "product_definition",
        "target_architecture",
    ]
    assert accepted_snapshot["semantic_content_machine_proven"] is False
    confirmed = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "actual_result",
        "--accepted",
        "--summary",
        "实际结果确认",
        "--version",
        str(awaiting_result["version"]),
    )["work_item"]
    product_file = project / baseline["authority_refs"]["product_definition"][
        "path"
    ]
    accepted_product_bytes = product_file.read_bytes()
    product = yaml.safe_load(accepted_product_bytes.decode("utf-8"))
    product["title"] = "未包含在已接受结果卡中的产品语义"
    product_file.write_text(
        yaml.safe_dump(product, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    polluted_adoption = _invoke(
        runner,
        project,
        "next",
        "--work-item-id",
        identifier,
        "--record",
        "delivery.authority_adoption",
    )["next"]["records"]["delivery.authority_adoption"]
    assert any(
        "已接受实际结果之后发生正文变化" in issue
        for issue in polluted_adoption["blocking_issues"]
    )
    polluted_delivery = runner.invoke(
        main,
        [
            "delivery",
            "--project-dir",
            str(project),
            "--work-item-id",
            identifier,
            "--version",
            str(confirmed["version"]),
        ],
    )
    assert polluted_delivery.exit_code == 1
    assert "accepted_implementation_candidate_changed" in (
        polluted_delivery.output
    )
    product_file.write_bytes(accepted_product_bytes)
    adoption = _invoke(
        runner,
        project,
        "next",
        "--work-item-id",
        identifier,
        "--record",
        "delivery.authority_adoption",
    )["next"]["records"]["delivery.authority_adoption"]
    assert adoption["ready_for_atomic_commits"] is False
    assert adoption["accepted_candidate_snapshot_verified"] is True, adoption
    assert adoption["changed_authority_kinds"] == [
        "domain_model",
        "engineering_policy",
        "implementation_alignment",
        "product_definition",
        "target_architecture",
    ]

    finalized_result = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--version",
        str(confirmed["version"]),
    )
    assert finalized_result["steps"] == ["authority_adoption_finalized"]
    finalized_item = finalized_result["work_item"]
    finalized_adoption = finalized_item["data"]["authority_adoption"]
    assert finalized_adoption["ready_for_atomic_commits"] is True, finalized_adoption
    assert finalized_adoption["authority_updates"] == []
    assert finalized_adoption["baseline_update"] is None
    finalized_alignment = yaml.safe_load(
        alignment_file.read_text(encoding="utf-8")
    )
    finalized_baseline = yaml.safe_load(
        baseline_file.read_text(encoding="utf-8")
    )
    assert finalized_alignment["revision"]["status"] == "confirmed"
    assert finalized_alignment["revision"]["confirmed_on"] == confirmed[
        "data"
    ]["actual_result_confirmation"]["confirmed_at"][:10]
    assert finalized_baseline["authority_refs"]["implementation_alignment"][
        "revision_id"
    ] == candidate_alignment_revision
    assert finalized_baseline["review_state"]["required"] is False
    _git(project, "add", "strixnova-project.yaml", "docs")
    _git(project, "commit", "-m", "docs: establish project engineering baseline")
    result_commit = _git(project, "rev-parse", "HEAD")

    completed = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--version",
        str(finalized_item["version"]),
    )["work_item"]
    assert completed["status"] == "completed"
    assert completed["data"]["git"]["result_commits"] == [result_commit]
    assert _git(project, "branch", "--show-current") == "main"
    assert _git(project, "status", "--porcelain") == ""
    assert not _git(project, "branch", "--list", f"strixnova/{identifier}")

    authorities = ProjectAuthorityConsistency(project).load()
    assert authorities["baseline"]["baseline_id"] == baseline["baseline_id"]
    assert authorities["structurally_consistent"] is True
    assert (project / adr_path).is_file()


def test_add_capability_records_public_interface_and_adr_through_full_lifecycle(
    tmp_path: Path,
) -> None:
    project = tmp_path / "capability-project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    assessment_fixture(project)
    baseline = portable_project_baseline(
        project,
        baseline_id="capability-project",
        artifacts=[],
    )
    baseline_path = project / "docs" / "engineering" / "baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(project, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(project, "add", "src.py", "strixnova-project.yaml", "docs")
    _git(project, "commit", "-m", "establish project baseline")
    _git(project, "branch", "-M", "main")
    observed_commit = _git(project, "rev-parse", "main")
    assessment = add_capability_adr_assessment(
        project,
        baseline=baseline,
        observed_commit=observed_commit,
    )
    runner = CliRunner()
    item = _start_formal_work_item(
        runner,
        project,
        title="新增公开读取能力",
        assessment=assessment,
        worktree_path=tmp_path / "capability-worktree",
    )
    identifier = item["work_item_id"]
    adr_path = "docs/adr/ADR-0200-public-capability.md"
    capability_id = "CAPABILITY-2222222222222222"
    capability_fact_id = "FACT-4444444444444444"
    planned_candidates = {
        candidate["authority_kind"]: candidate["revision_id"]
        for candidate in item["data"]["engineering"]["plan"][
            "authority_change_set"
        ]["candidate_authorities"]
    }
    revisions = dict(planned_candidates)

    def authority_value(path: str) -> dict:
        return yaml.safe_load((project / path).read_text(encoding="utf-8"))

    changes: dict[str, str] = {}

    def record_authority(path: str, value: dict) -> None:
        changes[path] = yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
        )

    product_path = baseline["authority_refs"]["product_definition"]["path"]
    product = authority_value(product_path)
    product["revision"].update(
        {
            "revision_id": revisions["product_definition"],
            "supersedes_revision_id": baseline["authority_refs"][
                "product_definition"
            ]["revision_id"],
        }
    )
    product["capabilities"].append(
        {
            "capability_id": capability_id,
            "title": "公开读取能力",
            "description": "通过稳定公开接口返回可验证的当前值。",
            "outcome_ids": ["OUTCOME-1111111111111111"],
        }
    )
    record_authority(product_path, product)

    domain_path = baseline["authority_refs"]["domain_model"]["path"]
    domain = authority_value(domain_path)
    domain["revision"].update(
        {
            "revision_id": revisions["domain_model"],
            "supersedes_revision_id": baseline["authority_refs"][
                "domain_model"
            ]["revision_id"],
        }
    )
    domain["product_definition_ref"]["revision_id"] = revisions[
        "product_definition"
    ]
    record_authority(domain_path, domain)
    for collection_path in domain["root_collection_paths"]:
        collection = authority_value(collection_path)
        collection["model_revision_id"] = revisions["domain_model"]
        record_authority(collection_path, collection)
        for source_record in collection["sources"]:
            source_path = source_record["path"]
            source = authority_value(source_path)
            source["model_revision_id"] = revisions["domain_model"]
            source["facts"].append(
                {
                    "fact_id": capability_fact_id,
                    "status": "confirmed",
                    "title": "公开读取能力",
                    "kind": "term",
                    "product_capability_ids": [capability_id],
                    "scope_fact_ids": [TEST_CONTEXT_FACT_ID],
                    "dependency_fact_ids": [],
                    "content": {
                        "term": "公开读取能力",
                        "definition": "通过稳定公开接口返回可验证当前值的产品能力。",
                    },
                }
            )
            record_authority(source_path, source)

    architecture_path = baseline["authority_refs"]["target_architecture"][
        "path"
    ]
    architecture = authority_value(architecture_path)
    architecture["revision"].update(
        {
            "revision_id": revisions["target_architecture"],
            "supersedes_revision_id": baseline["authority_refs"][
                "target_architecture"
            ]["revision_id"],
        }
    )
    architecture["domain_model_ref"]["revision_id"] = revisions[
        "domain_model"
    ]
    record_authority(architecture_path, architecture)
    for name, path in architecture["artifact_paths"].items():
        artifact = authority_value(path)
        artifact["architecture_revision_id"] = revisions[
            "target_architecture"
        ]
        if isinstance(artifact.get("domain_model_ref"), dict):
            artifact["domain_model_ref"]["revision_id"] = revisions[
                "domain_model"
            ]
        if name == "domain_fact_dispositions":
            artifact["dispositions"].append(
                {
                    "domain_fact_id": capability_fact_id,
                    "disposition_type": "primary_module",
                    "primary_module_id": "MODULE-1111111111111111",
                    "collaborator_module_ids": [],
                    "relationship_ids": [],
                    "constraint_ids": ["CONSTRAINT-1111111111111111"],
                    "rationale": "公开读取能力由测试应用模块主要承载。",
                }
            )
        record_authority(path, artifact)

    source_content = "def value():\n    return 1\n\n\ndef read_value():\n    return 'ready'\n"
    source_digest = hashlib.sha256(source_content.encode("utf-8")).hexdigest()
    governed_manifest = hashlib.sha256(
        f"{FRONTEND}:src.py:{source_digest}\n".encode("utf-8")
    ).hexdigest()
    changes["src.py"] = source_content

    alignment_path = baseline["authority_refs"]["implementation_alignment"][
        "path"
    ]
    alignment = authority_value(alignment_path)
    alignment["revision"].update(
        {
            "revision_id": revisions["implementation_alignment"],
            "supersedes_revision_id": baseline["authority_refs"][
                "implementation_alignment"
            ]["revision_id"],
        }
    )
    alignment["domain_model_ref"]["revision_id"] = revisions["domain_model"]
    alignment["architecture_ref"]["revision_id"] = revisions[
        "target_architecture"
    ]
    alignment["code_snapshot"].update(
        {'repositories': [{'repository_id': FRONTEND, 'base_commit': observed_commit, 'worktree_state': 'dirty'}], 'governed_source_manifest_sha256': governed_manifest}
    )
    alignment["observation_coverage"] = _observation_coverage_for_content(
        alignment,
        source_content,
    )
    record_authority(alignment_path, alignment)
    for name, path in alignment["artifact_paths"].items():
        artifact = authority_value(path)
        artifact["alignment_revision_id"] = revisions[
            "implementation_alignment"
        ]
        if name == "source_ownership":
            artifact["records"][0]["sha256"] = source_digest
        record_authority(path, artifact)

    revised_baseline = yaml.safe_load(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False)
    )
    for kind, revision_id in revisions.items():
        revised_baseline["authority_refs"][kind]["revision_id"] = revision_id
    revised_baseline["code_version"] = {'repositories': [{'repository_id': FRONTEND, 'base_commit': observed_commit, 'worktree_state': 'dirty'}]}
    record_authority("docs/engineering/baseline.yaml", revised_baseline)
    changes["docs/public-interface.md"] = (
        "# 公开接口\n\n`read_value()` 返回当前可验证值。\n"
    )
    changes[adr_path] = (
        "---\n"
        "adr_id: ADR-0200\n"
        "title: 公开读取能力边界\n"
        "decision_status: accepted\n"
        "realization_status: realized\n"
        f"originating_work_item: {identifier}\n"
        "realized_by_work_items:\n"
        f"  - {identifier}\n"
        "supersedes: []\n"
        "superseded_by: []\n"
        "---\n\n"
        "# 决定\n\n公开读取能力通过稳定接口提供，并由完整权威链约束。\n"
    )

    fact_ref = assessment["domain_fact_changes"][0]["target_ref"]

    def domain_fact_results(receipt_id: str) -> list[dict]:
        return [
            {
                "target_ref": fact_ref,
                "outcome": "realized",
                "evidence_refs": [receipt_id],
                "limitations": [],
            }
        ]

    completed = _complete_linked_delivery(
        runner,
        project,
        item,
        changes=changes,
        long_lived_refs=[
            {
                "artifact_id": reference[identity_field],
                "artifact_type": artifact_type,
                "path": reference["path"],
                "relation": "updated",
            }
            for reference, identity_field, artifact_type in (
                (
                    baseline["authority_refs"]["product_definition"],
                    "product_id",
                    "product_governance",
                ),
                (
                    baseline["authority_refs"]["domain_model"],
                    "model_id",
                    "domain_model",
                ),
                (
                    baseline["authority_refs"]["target_architecture"],
                    "architecture_id",
                    "architecture",
                ),
                (
                    baseline["authority_refs"]["implementation_alignment"],
                    "alignment_model_id",
                    "domain_alignment",
                ),
            )
        ]
        + [
            {
                "artifact_id": "IFACE-001",
                "artifact_type": "interface",
                "path": "docs/public-interface.md",
                "relation": "introduced",
            },
            {
                "artifact_id": "ADR-0200",
                "artifact_type": "adr",
                "path": adr_path,
                "relation": "introduced",
            },
        ],
        domain_fact_results_factory=domain_fact_results,
    )

    assert completed["data"]["engineering"]["plan"]["assurance_band"] == "A3"
    main_commit = _git(project, "rev-parse", "main")
    authorities = ProjectAuthorityConsistency(project).load()
    assert authorities["structurally_consistent"] is True
    assert authorities["product_definition"]["revision"]["revision_id"] == (
        revisions["product_definition"]
    )
    assert authorities["domain_catalog"]["revision"]["revision_id"] == revisions[
        "domain_model"
    ]
    read_model = WorkItemReadModel(project)
    fact = read_model.project_domain_fact(capability_fact_id)
    assert fact["product_capability_ids"] == [capability_id]
    adr_trace = read_model.engineering_trace_for_artifact(
        "ADR-0200",
        at_commit=main_commit,
    )
    assert adr_trace["artifact_status"] == "recorded_output"
    assert any(
        edge["source"].get("work_item_id") == identifier
        and edge["edge_kind"] == "long_lived_output_reference"
        for edge in adr_trace["edges"]
    )


def test_plain_language_work_item_completes_a_formal_domain_fact_change(
    tmp_path: Path,
) -> None:
    """The user never handles Fact IDs; the Agent-facing assessment does."""

    project = tmp_path / "domain-change-project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    assessment = assessment_fixture(project)
    baseline = portable_project_baseline(
        project,
        baseline_id="domain-change-project",
        artifacts=[],
    )
    identities = adopt_portable_ddd(project, baseline)
    baseline_path = project / "docs/engineering/baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(project, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(project, "add", ".")
    _git(project, "commit", "-m", "adopt project domain model")
    _git(project, "branch", "-M", "main")
    observed_commit = _git(project, "rev-parse", "main")

    fact_ref = {
        "schema_version": "strixnova.domain-fact-reference.v1",
        "authority_kind": "project_domain_model",
        "model_id": TEST_DOMAIN_MODEL_ID,
        "fact_id": TEST_TERM_FACT_ID,
        "observed_commit": observed_commit,
    }
    source_path = identities["source_path"]
    assessment["assessment_id"] = "EA-DOMAIN-PLAIN-LANGUAGE"
    assessment["source_references"] = [
        {
            "reference_id": "SRC-DOMAIN-TERM",
            "path": source_path,
            "line_start": 1,
            "line_end": 5,
            "observed_ref": "working_tree",
            "epistemic_status": "observed",
        }
    ]
    assessment["impact_scope"] = {
        "affected": [
            {
                "dimension": "domain",
                "reason": "需要校正项目对建设事项的长期定义。",
                "evidence_refs": ["SRC-DOMAIN-TERM"],
            },
            {
                "dimension": "testing",
                "reason": "领域定义变化需要验证规范正文可被读取。",
                "evidence_refs": ["SRC-DOMAIN-TERM"],
            },
        ],
        "unknown": [],
        "unaffected": [
            "user_behavior",
            "product_scope",
            "architecture",
            "interface",
            "data",
            "security_privacy",
            "quality_performance",
            "operations_deployment",
            "compatibility_migration",
            "documentation_support",
        ],
    }
    assessment["risk_assessments"] = [
        {
            "statement": "领域定义与规范正文不一致会让后续事项误解 WorkItem。",
            "likelihood": "low",
            "consequence": "medium",
            "reversibility": "easy",
            "uncertainty": "low",
            "external_assurance_required": False,
            "mitigation": "直接读取修改后的规范 Fact 正文进行验证。",
            "evidence_refs": ["SRC-DOMAIN-TERM"],
        }
    ]
    assessment["design_decisions"] = [
        {
            "statement": "保留 WorkItem Fact 身份，只校正其规范含义。",
            "rationale": "语义未被新概念替代，稳定身份应继续有效。",
            "evidence_refs": ["SRC-DOMAIN-TERM"],
        }
    ]
    assessment["operations"] = [
        {
            "action": "modify",
            "path": source_path,
            "reason": "把通俗愿望落实为项目唯一规范领域正文。",
            "evidence_refs": ["SRC-DOMAIN-TERM"],
            "implements": ["design_decisions[0]"],
        }
    ]
    domain_model_path = baseline["authority_refs"]["domain_model"]["path"]
    architecture_path = baseline["authority_refs"]["target_architecture"]["path"]
    alignment_path = baseline["authority_refs"]["implementation_alignment"]["path"]
    authority_documents = {
        domain_model_path: (
            TEST_DOMAIN_MODEL_ID,
            "domain_model",
        ),
        architecture_path: (
            baseline["authority_refs"]["target_architecture"]["architecture_id"],
            "architecture",
        ),
        alignment_path: (
            TEST_ALIGNMENT_ID,
            "domain_alignment",
        ),
    }
    domain_model = yaml.safe_load(
        (project / domain_model_path).read_text(encoding="utf-8")
    )
    architecture = yaml.safe_load(
        (project / architecture_path).read_text(encoding="utf-8")
    )
    alignment = yaml.safe_load(
        (project / alignment_path).read_text(encoding="utf-8")
    )
    supporting_authority_paths = [
        *domain_model["root_collection_paths"],
        *architecture["artifact_paths"].values(),
        *alignment["artifact_paths"].values(),
    ]
    for path, (artifact_id, artifact_type) in authority_documents.items():
        assessment["operations"].append(
            {
                "action": "modify",
                "path": path,
                "reason": "更新完整项目权威链的修订绑定。",
                "evidence_refs": ["SRC-DOMAIN-TERM"],
                "implements": ["design_decisions[0]"],
                "long_lived_artifact": {
                    "artifact_id": artifact_id,
                    "artifact_type": artifact_type,
                },
            }
        )
    for path in supporting_authority_paths:
        assessment["operations"].append(
            {
                "action": "modify",
                "path": path,
                "reason": "同步完整权威修订的从属产物绑定。",
                "evidence_refs": ["SRC-DOMAIN-TERM"],
                "implements": ["design_decisions[0]"],
            }
        )
    assessment["operations"].append(
        {
            "action": "modify",
            "path": "docs/engineering/baseline.yaml",
            "reason": "同步项目工程基线中的精确权威修订引用。",
            "evidence_refs": ["SRC-DOMAIN-TERM"],
            "implements": ["design_decisions[0]"],
        }
    )
    assessment["method_applications"] = [
        {
            "method_id": "ddd",
            "decision": "applied",
            "purpose": "使用统一语言技术校正建设事项定义。",
            "evidence_refs": ["SRC-DOMAIN-TERM"],
            "baseline_refs": ["engineering-policy:method:ddd"],
            "domain_fact_refs": [fact_ref],
            "planned_uses": [
                {
                    "use_id": "DDD-USE-DOMAIN-TERM",
                    "stage": "domain_analysis",
                    "technique_ids": ["ubiquitous_language"],
                    "purpose": "让 WorkItem 的项目级含义更容易理解。",
                    "target_refs": ["impact_scope.affected[0]"],
                    "evidence_refs": ["SRC-DOMAIN-TERM"],
                }
            ],
        }
    ]
    assessment["domain_fact_changes"] = [
        {
            "disposition": "update",
            "target_ref": fact_ref,
            "source_path": source_path,
            "reason": "含义澄清保留原 Fact 身份。",
            "evidence_refs": ["SRC-DOMAIN-TERM"],
            "lineage": [],
        }
    ]
    expected_content = (
        "WorkItem 是由用户确认方向、方案和实际结果的一次建设事项。"
    )
    assessment["verification_commands"] = [
        {
            "argv": [
                sys.executable,
                "-c",
                (
                    "from pathlib import Path; import yaml; "
                    f"value=yaml.safe_load(Path('{source_path}').read_text(encoding='utf-8')); "
                    f"fact=next(item for item in value['facts'] if item['fact_id']=='{TEST_TERM_FACT_ID}'); "
                    f"assert fact['content']['definition']=={expected_content!r}"
                ),
            ],
            "cwd": ".",
            "run_kind": "acceptance_test",
            "covers": [
                "direction.acceptance:DIRACC-3333333333333333",
                "risk_assessments[0]",
            ],
            "reason": "直接验证新的规范领域正文。",
        }
    ]

    new_domain_revision = "MODELREV-4444444444444444"
    new_architecture_revision = "ARCHREV-4444444444444444"
    new_alignment_revision = "ALIGNREV-4444444444444444"

    def authority_value(path: str) -> dict:
        return yaml.safe_load((project / path).read_text(encoding="utf-8"))

    changed_authorities: dict[str, str] = {}

    def record_authority(path: str, value: dict) -> None:
        changed_authorities[path] = yaml.safe_dump(
            value,
            allow_unicode=True,
            sort_keys=False,
        )

    revised_domain_model = authority_value(domain_model_path)
    revised_domain_model["revision"].update(
        {
            "revision_id": new_domain_revision,
            "supersedes_revision_id": baseline["authority_refs"]["domain_model"][
                "revision_id"
            ],
        }
    )
    record_authority(domain_model_path, revised_domain_model)
    for collection_path in revised_domain_model["root_collection_paths"]:
        collection = authority_value(collection_path)
        collection["model_revision_id"] = new_domain_revision
        record_authority(collection_path, collection)

    source = authority_value(source_path)
    source["model_revision_id"] = new_domain_revision
    next(
        fact
        for fact in source["facts"]
        if fact["fact_id"] == TEST_TERM_FACT_ID
    )["content"]["definition"] = expected_content
    record_authority(source_path, source)

    revised_architecture = authority_value(architecture_path)
    revised_architecture["revision"].update(
        {
            "revision_id": new_architecture_revision,
            "supersedes_revision_id": baseline["authority_refs"][
                "target_architecture"
            ]["revision_id"],
        }
    )
    revised_architecture["domain_model_ref"]["revision_id"] = (
        new_domain_revision
    )
    record_authority(architecture_path, revised_architecture)
    for path in revised_architecture["artifact_paths"].values():
        artifact = authority_value(path)
        artifact["architecture_revision_id"] = new_architecture_revision
        if isinstance(artifact.get("domain_model_ref"), dict):
            artifact["domain_model_ref"]["revision_id"] = new_domain_revision
        record_authority(path, artifact)

    revised_alignment = authority_value(alignment_path)
    revised_alignment["revision"].update(
        {
            "revision_id": new_alignment_revision,
            "supersedes_revision_id": baseline["authority_refs"][
                "implementation_alignment"
            ]["revision_id"],
        }
    )
    revised_alignment["domain_model_ref"]["revision_id"] = new_domain_revision
    revised_alignment["architecture_ref"]["revision_id"] = (
        new_architecture_revision
    )
    source_digest = hashlib.sha256(
        GitProjectReader(project, observed_ref=observed_commit).read_bytes(
            "src.py",
            "测试行为文件",
        )
    ).hexdigest()
    revised_alignment["code_snapshot"].update(
        {'repositories': [{'repository_id': FRONTEND, 'base_commit': observed_commit, 'worktree_state': 'dirty'}], 'governed_source_manifest_sha256': hashlib.sha256(f'{FRONTEND}:src.py:{source_digest}\n'.encode('utf-8')).hexdigest()}
    )
    revised_alignment["observation_coverage"] = _observation_coverage(
        project,
        revised_alignment,
        observed_ref=observed_commit,
    )
    record_authority(alignment_path, revised_alignment)
    for name, path in revised_alignment["artifact_paths"].items():
        artifact = authority_value(path)
        artifact["alignment_revision_id"] = new_alignment_revision
        if name == "source_ownership":
            artifact["records"][0]["sha256"] = source_digest
        record_authority(path, artifact)

    revised_baseline = authority_value("docs/engineering/baseline.yaml")
    revised_baseline["authority_refs"]["domain_model"]["revision_id"] = (
        new_domain_revision
    )
    revised_baseline["authority_refs"]["target_architecture"]["revision_id"] = (
        new_architecture_revision
    )
    revised_baseline["authority_refs"]["implementation_alignment"][
        "revision_id"
    ] = new_alignment_revision
    revised_baseline["code_version"] = {'repositories': [{'repository_id': FRONTEND, 'base_commit': observed_commit, 'worktree_state': 'dirty'}]}
    record_authority("docs/engineering/baseline.yaml", revised_baseline)

    authority_rows = (
        (
            "product_definition",
            baseline["authority_refs"]["product_definition"],
            "product_id",
            None,
        ),
        (
            "domain_model",
            baseline["authority_refs"]["domain_model"],
            "model_id",
            new_domain_revision,
        ),
        (
            "target_architecture",
            baseline["authority_refs"]["target_architecture"],
            "architecture_id",
            new_architecture_revision,
        ),
        (
            "implementation_alignment",
            baseline["authority_refs"]["implementation_alignment"],
            "alignment_model_id",
            new_alignment_revision,
        ),
    )
    assessment["authority_change_set"] = {
        "schema_version": "strixnova.authority-change-set.v1",
        "change_set_id": "AUTHCHANGE-6666666666666666",
        "work_item_id": assessment["direction_ref"]["work_item_id"],
        "base_authorities": [
            {
                "authority_kind": kind,
                "artifact_id": reference[identity_field],
                "revision_id": reference["revision_id"],
                "path": reference["path"],
                "status": reference["status"]["revision_status"],
                "observed_commit": observed_commit,
            }
            for kind, reference, identity_field, _candidate_revision in authority_rows
        ],
        "candidate_authorities": [
            {
                "authority_kind": kind,
                "artifact_id": reference[identity_field],
                "revision_id": candidate_revision,
                "path": reference["path"],
                "status": "draft",
                "supersedes_revision_id": reference["revision_id"],
                "adoption_effect": "not_adopted",
            }
            for kind, reference, identity_field, candidate_revision in authority_rows
            if candidate_revision is not None
        ],
        "changes": [
            {
                "change_id": f"AUTHOP-{index:03d}",
                "authority_kind": kind,
                "operation": "modify",
                "target_ref": (
                    TEST_TERM_FACT_ID
                    if kind == "domain_model"
                    else str(reference[identity_field])
                ),
                "summary": "校正领域术语后同步修订该层长期权威。",
                "evidence_refs": ["SRC-DOMAIN-TERM"],
            }
            for index, (
                kind,
                reference,
                identity_field,
                candidate_revision,
            ) in enumerate(authority_rows[1:], start=1)
        ],
        "downstream_dispositions": [
            {
                "source_authority_kind": "domain_model",
                "target_authority_kind": "target_architecture",
                "disposition": "revise",
                "reason": "领域术语修订需要目标架构重新绑定精确领域版本。",
            },
            {
                "source_authority_kind": "domain_model",
                "target_authority_kind": "implementation_alignment",
                "disposition": "revise",
                "reason": "领域术语修订需要实现对齐重新绑定精确领域版本。",
            },
            {
                "source_authority_kind": "target_architecture",
                "target_authority_kind": "implementation_alignment",
                "disposition": "revise",
                "reason": "架构修订需要实现对齐重新绑定精确架构版本。",
            },
        ],
        "semantic_content_machine_proven": False,
    }
    assessment["semantic_review"] = semantic_review_fixture(
        "SRC-DOMAIN-TERM",
        "authority_change_set",
    )
    assessment["owner_view"]["decision_support"].update(
        {
            "current_problem": "把建设事项的领域含义校正为项目统一语言。",
            "why_it_matters": "术语漂移会让架构和实现锚定错误含义。",
            "impact": "领域修订及其架构、实现对齐引用同步变化。",
            "recommendation": "先修订领域，再同步全部下游权威绑定。",
            "alternatives": ["保留旧定义并放弃本次语义校正。"],
            "no_action_consequence": "建设事项继续使用与项目不一致的术语。",
            "next_step": "确认方案后按上游到下游顺序实施。",
            "necessary_questions": [],
        }
    )
    assessment["owner_view"]["engineering_context"].update(
        {
            "product_and_domain_change": "产品范围不变，领域术语定义形成新的完整修订。",
            "architecture_responsibilities": "目标架构和实现对齐只更新精确上游绑定，不新增职责。",
            "implementation_order": "先修订领域，再同步架构与实现对齐，最后执行定义读取验收。",
            "highest_impact_risks": "任一层继续引用旧领域版本都会形成权威链漂移。",
            "verification_and_observation": "读取交付后的正式领域事实并核对新定义。",
            "uncertainties": "没有遗留高影响决定，但语义结论仍由智能编码代理负责。",
        }
    )
    refresh_single_slice(
        assessment,
        purpose="修订领域术语并同步完整下游权威绑定。",
    )

    runner = CliRunner()
    item = _start_formal_work_item(
        runner,
        project,
        title="把建设事项的含义说得更清楚",
        assessment=assessment,
        worktree_path=tmp_path / "domain-change-worktree",
    )

    def method_results(receipt_id: str) -> list[dict]:
        return [
            {
                "method_id": "ddd",
                "use_results": [
                    {
                        "use_id": "DDD-USE-DOMAIN-TERM",
                        "status": "realized",
                        "outcome": "已按项目统一语言校正 WorkItem 定义。",
                        "evidence_refs": [receipt_id],
                    }
                ],
                "deviations": [],
            }
        ]

    def domain_fact_results(receipt_id: str) -> list[dict]:
        return [
            {
                "target_ref": fact_ref,
                "outcome": "realized",
                "evidence_refs": [receipt_id],
                "limitations": [],
            }
        ]

    completed = _complete_linked_delivery(
        runner,
        project,
        item,
        changes=changed_authorities,
        long_lived_refs=[
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "path": path,
                "relation": "updated",
            }
            for path, (artifact_id, artifact_type) in authority_documents.items()
        ],
        method_results_factory=method_results,
        domain_fact_results_factory=domain_fact_results,
    )
    identifier = completed["work_item_id"]
    main_commit = _git(project, "rev-parse", "main")
    read_model = WorkItemReadModel(project)
    fact = read_model.project_domain_fact(TEST_TERM_FACT_ID)
    assert fact["content"]["definition"] == expected_content
    assert fact["_observed_commit"] == main_commit
    trace = read_model.engineering_trace_for_fact(
        TEST_TERM_FACT_ID,
        at_commit=main_commit,
    )
    assert any(
        edge["edge_kind"] == "domain_fact_reference"
        and edge["source"]["work_item_id"] == identifier
        for edge in trace["edges"]
    )
    current_trace = _invoke(
        runner,
        project,
        "next",
        # This lifecycle test inspects the entire trace, not a bounded UI page.
        # The small-budget traversal has separate public-CLI regression coverage.
        "--max-output-bytes",
        "1048576",
        "--work-item-id",
        identifier,
        "--record",
        "engineering.trace.current",
    )["next"]
    audit_trace = _invoke(
        runner,
        project,
        "next",
        "--max-output-bytes",
        "1048576",
        "--work-item-id",
        identifier,
        "--record",
        "engineering.trace.audit",
    )["next"]
    assert current_trace["current_action"] is None
    assert {
        "domain_fact_reference",
        "local_integration_receipt",
    }.issubset({
        edge["edge_kind"]
        for edge in current_trace["records"]["engineering.trace.current"][
            "edges"
        ]
    })
    assert audit_trace["records"]["engineering.trace.audit"]["mode"] == "audit"


def test_two_non_overlapping_work_items_complete_from_parallel_worktrees(
    tmp_path: Path,
) -> None:
    project = tmp_path / "parallel-project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    first_assessment = assessment_fixture(project)
    _adopt_portable_test_project(
        project,
        baseline_id="parallel-project",
    )

    def specialize(assessment: dict, *, suffix: str, path: str) -> None:
        assessment["assessment_id"] = f"EC-PARALLEL-{suffix}"
        assessment["operations"][0].update(
            {
                "action": "create",
                "path": path,
                "reason": f"创建互不相交的文件 {path}。",
            }
        )
        assessment["verification_commands"] = [
            {
                "argv": [
                    sys.executable,
                    "-c",
                    f"import sys; assert sys.version_info[:2] == (3, 12); from pathlib import Path; assert Path('{path}').read_text() == '{suffix.lower()}\\n'",
                ],
                "cwd": ".",
                "run_kind": "acceptance_test",
                "covers": [
                    "direction.acceptance:DIRACC-3333333333333333",
                    "direction.constraint:DIRCON-2222222222222222",
                    "risk_assessments[0]",
                ],
                "reason": f"独立验证 {path} 的建设结果。",
            }
        ]

    specialize(first_assessment, suffix="A", path="a.txt")
    second_assessment = assessment_fixture(project)
    specialize(second_assessment, suffix="B", path="b.txt")
    runner = CliRunner()
    first = _start_formal_work_item(
        runner,
        project,
        title="并行事项 A",
        assessment=first_assessment,
        worktree_path=tmp_path / "parallel-a",
    )
    second = _start_formal_work_item(
        runner,
        project,
        title="并行事项 B",
        assessment=second_assessment,
        worktree_path=tmp_path / "parallel-b",
    )
    assert Path(first["data"]["git"]["worktree_path"]).is_dir()
    assert Path(second["data"]["git"]["worktree_path"]).is_dir()

    first_completed = _complete_linked_delivery(
        runner,
        project,
        first,
        changes={"a.txt": "a\n"},
    )
    second_completed = _complete_linked_delivery(
        runner,
        project,
        second,
        changes={"b.txt": "b\n"},
    )

    assert first_completed["status"] == second_completed["status"] == "completed"
    assert (project / "a.txt").read_text(encoding="utf-8") == "a\n"
    assert (project / "b.txt").read_text(encoding="utf-8") == "b\n"
    assert not _git(project, "branch", "--list", "strixnova/*")


def test_conflict_reverification_waits_for_the_agent_merge_commit(
    tmp_path: Path,
) -> None:
    project = tmp_path / "conflict-project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    (project / "shared.txt").write_text("base\n", encoding="utf-8")
    assessment = assessment_fixture(project)
    assessment["source_references"][0].update(
        {"path": "shared.txt", "line_start": 1, "line_end": 1}
    )
    assessment["operations"][0].update(
        {"action": "modify", "path": "shared.txt"}
    )
    assessment["verification_commands"] = [
        {
            "argv": [
                sys.executable,
                "-c",
                "from pathlib import Path; value=Path('shared.txt').read_text(); "
                "assert value in {'work item\\n', 'resolved\\n'}",
            ],
            "cwd": ".",
            "run_kind": "targeted_test",
            "covers": [
                "direction.acceptance:DIRACC-3333333333333333",
                "risk_assessments[0]",
            ],
            "reason": "验证 WorkItem 结果和冲突解决后的目标工作树。",
        }
    ]
    _adopt_portable_test_project(
        project,
        baseline_id="conflict-project",
    )

    _plan_delivery_order_review(assessment)
    runner = CliRunner()
    item = _start_formal_work_item(
        runner,
        project,
        title="冲突闭环",
        assessment=assessment,
        worktree_path=tmp_path / "conflict-worktree",
        constraint_statement="Disclose an unrun initial verification and obtain acceptance of its limitation before committing; verify the resolved conflict before completing integration.",
    )
    identifier = item["work_item_id"]
    authority = WorkflowAuthority(project)
    area = item["data"]["git"]
    worktree = Path(area["worktree_path"])
    (worktree / "shared.txt").write_text("work item\n", encoding="utf-8")
    (project / "shared.txt").write_text("target\n", encoding="utf-8")
    _git(project, "add", "shared.txt")
    _git(project, "commit", "-m", "change from target")

    initial = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "not_run",
                "not_run_reason": "先确认 WorkItem 结果，再验证冲突后的组合。",
                "limitations": ["目标分支组合尚未形成。"],
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "回执后未继续修改 WorkItem 结果。",
                },
            },
            ensure_ascii=False,
        ),
        "--version",
        str(item["version"]),
    )
    item = initial["work_item"]
    item = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(
            {
                "schema_version": "strixnova.actual-result.v1",
                "semantic_content_machine_proven": False,
                "effect_summary": "WorkItem 分支已经形成待合入结果。",
                "delivered_outcomes": ["shared.txt 已按方案修改。"],
                "deviations": [],
                "limitations": ["合入目标分支后的组合仍需复测。"],
                "verification_receipt_ids": [
                    initial["verification"]["receipt_id"]
                ],
                "long_lived_refs": [],
                "method_application_results": [],
                "verification_review_results": _delivery_order_review_result(item),
                "governance_rule_results": [
                    {
                        "rule_id": rule["rule_id"],
                        "status": "partially_satisfied",
                        "evidence_refs": [
                            initial["verification"]["receipt_id"]
                        ],
                        "gaps": ["合入目标分支后的组合尚未复测。"],
                        "remediation_actions": ["解决冲突后执行组合复测。"],
                        "limitations": ["当前回执明确记录为未运行。"],
                    }
                    for rule in item["data"]["engineering"]["plan"][
                        "applicable_rules"
                    ]
                ],
            },
            ensure_ascii=False,
        ),
        "--version",
        str(item["version"]),
    )["work_item"]
    item = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "actual_result",
        "--accepted",
        "--summary",
        "初始结果确认",
        "--version",
        str(item["version"]),
    )["work_item"]
    _git(worktree, "add", "shared.txt")
    _git(worktree, "commit", "-m", "change from work item")
    item = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--version",
        str(item["version"]),
    )["work_item"]
    if item["current_action"]["action_type"] == "assess_target_advance":
        item = LocalHostAdapter(project).submit_current_action_input(
            identifier,
            {
                "schema_version": "strixnova.target-advance-assessment.v1",
                "semantic_impact": "unaffected",
                "reason": "目标分支只形成预期的同文件合入冲突，不改变已确认结果语义。",
            },
            expected_version=item["version"],
        )
        item = _invoke(
            runner,
            project,
            "delivery",
            "--work-item-id",
            identifier,
            "--version",
            str(item["version"]),
        )["work_item"]
    assert item["status"] == "integration_conflict"
    item = LocalHostAdapter(project).submit_current_action_input(
        identifier,
        {
            "user_visible_result_changed": False,
            "confirmed_direction_or_plan_changed": False,
            "reason": "只保留原本已经确认的效果。",
            "retest_command_ids": ["VC-001"],
        },
        expected_version=item["version"],
    )

    (project / "shared.txt").write_text("resolved\n", encoding="utf-8")
    _git(project, "add", "shared.txt")
    executed = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--execution-area",
        "target",
        "--input",
        json.dumps(
            {
                "mode": "run",
                "limitations": [],
            },
            ensure_ascii=False,
        ),
        "--version",
        str(item["version"]),
    )
    verified = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "assess",
                "receipt_id": executed["verification"]["receipt_id"],
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "复测后没有继续修改冲突解决。",
                },
            },
            ensure_ascii=False,
        ),
        "--version",
        str(executed["work_item"]["version"]),
    )["work_item"]
    conflict_snapshot = verified["data"]["git"]["conflict_resolution"][
        "implementation_candidate_snapshot"
    ]
    assert conflict_snapshot["schema_version"] == (
        "strixnova.implementation-candidate-snapshot.v1"
    )
    assert conflict_snapshot["semantic_content_machine_proven"] is False
    assert conflict_snapshot["paths"] == [
        {
            "path": "shared.txt",
            "state": "file",
            "sha256": hashlib.sha256(b"resolved\n").hexdigest(),
        }
    ]
    assert verified["current_action"]["action_type"] == "complete_git_merge"

    premature = runner.invoke(
        main,
        [
            "delivery",
            "--project-dir",
            str(project),
            "--work-item-id",
            identifier,
            "--version",
            str(verified["version"]),
        ],
    )
    assert premature.exit_code == 1
    assert "merge_commit_required" in premature.output
    assert _git(project, "rev-parse", "-q", "--verify", "MERGE_HEAD")
    assert authority.get(identifier)["current_action"]["action_type"] == (
        "complete_git_merge"
    )

    _git(project, "commit", "--no-edit")
    completed = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--version",
        str(verified["version"]),
    )["work_item"]
    assert completed["status"] == "completed"
    assert completed["data"]["verifications"][0]["result"] == "not_run"
    assert completed["data"]["verifications"][-1]["result"] == "passed"
    assert completed["data"]["actual_result"]["verification_review_results"][0]["outcome"] == "not_verified"
    assert not worktree.exists()
    assert (project / "shared.txt").read_text(encoding="utf-8") == "resolved\n"


def _finish_complete_flow(
    runner: CliRunner,
    project: Path,
    identifier: str,
    assessment: dict,
) -> None:
    _plan_delivery_order_review(assessment)
    assessment["investigation_ref"] = "main"
    decision_context = _direction_context_binding(
        runner,
        project,
        identifier,
    )
    _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(
            {
                "direction": {
                    "schema_version": "strixnova.direction-decision.v1",
                    "decision_context": decision_context,
                    "goal": "交付 feature.txt 表示的本地能力",
                    "scope": [
                        {
                            "requirement_id": "DIRREQ-1111111111111111",
                            "statement": "本地工作树和交付闭环",
                        }
                    ],
                    "non_goals": ["任何远程 Git 操作"],
                    "constraints": [
                        {
                            "constraint_id": "DIRCON-2222222222222222",
                            "statement": "先验证和确认，再形成提交",
                        }
                    ],
                    "acceptance": [
                        {
                            "acceptance_id": "DIRACC-3333333333333333",
                            "statement": "未提交代码能先完成真实验证",
                            "requirement_refs": [
                                "DIRREQ-1111111111111111"
                            ],
                            "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
                        }
                    ],
                    "tradeoffs": ["用户确认后才形成提交"],
                },
                "ready_for_confirmation": True,
            },
            ensure_ascii=False,
        ),
        "--version",
        "1",
    )
    direction_confirmed = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "direction",
        "--accepted",
        "--summary",
        "方向确认",
        "--version",
        "2",
    )["work_item"]
    bind_assessment_to_work_item(assessment, direction_confirmed)
    _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(assessment, ensure_ascii=False),
        "--version",
        "3",
    )
    _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "engineering_plan",
        "--accepted",
        "--summary",
        "工程方案确认",
        "--version",
        "4",
    )
    implementing = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--target-ref",
        "main",
        "--merge-strategy",
        "ff_only",
        "--version",
        "5",
    )["work_item"]
    worktree = Path(implementing["data"]["git"]["worktree_path"])
    base_commit = implementing["data"]["git"]["base_commit"]
    (worktree / "feature.txt").write_text("ready\n", encoding="utf-8")

    executed = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "run",
                "limitations": [],
            },
            ensure_ascii=False,
        ),
        "--version",
        str(implementing["version"]),
    )
    receipt_id = executed["verification"]["receipt_id"]
    assert executed["verification"]["result"] == "passed"
    verified = _invoke(
        runner,
        project,
        "verify",
        "--work-item-id",
        identifier,
        "--command-id",
        "VC-001",
        "--input",
        json.dumps(
            {
                "mode": "assess",
                "receipt_id": receipt_id,
                "code_change_assessment": {
                    "changed_after": False,
                    "needs_retest": False,
                    "rationale": "验证后没有继续修改相关实现。",
                },
            },
            ensure_ascii=False,
        ),
        "--version",
        str(executed["work_item"]["version"]),
    )
    assert _git(worktree, "rev-parse", "HEAD") == base_commit
    assert _git(worktree, "status", "--porcelain") == "?? feature.txt"

    unexpected = worktree / "unplanned.txt"
    unexpected.write_text("not in the confirmed operation\n", encoding="utf-8")
    rejected_result = runner.invoke(
        main,
        [
            "delivery",
            "--work-item-id",
            identifier,
            "--input",
            json.dumps(
                {
                    "schema_version": "strixnova.actual-result.v1",
                    "semantic_content_machine_proven": False,
                    "effect_summary": "工作树内已经生成并验证 feature.txt。",
                    "delivered_outcomes": ["文件内容满足确认的验收。"],
                    "deviations": [],
                    "limitations": [],
                    "verification_receipt_ids": [receipt_id],
                    "long_lived_refs": [],
                    "method_application_results": [],
                    "verification_review_results": _delivery_order_review_result(verified["work_item"]),
                    "governance_rule_results": satisfied_governance_rule_results(
                        verified["work_item"]["data"]["engineering"]["plan"],
                        receipt_id,
                    ),
                },
                ensure_ascii=False,
            ),
            "--version",
            str(verified["work_item"]["version"]),
            "--project-dir",
            str(project),
        ],
    )
    assert rejected_result.exit_code == 1
    rejected_error = json.loads(rejected_result.output)["error"]
    assert rejected_error["code"] == (
        "unplanned_repository_change"
    )
    assert "重新规划" in rejected_error["message"]
    assert rejected_error["details"]["unplanned_paths"] == [
        "unplanned.txt"
    ]
    unexpected.unlink()

    awaiting_result = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--input",
        json.dumps(
            {
                "schema_version": "strixnova.actual-result.v1",
                "semantic_content_machine_proven": False,
                "effect_summary": "工作树内已经生成并验证 feature.txt。",
                "delivered_outcomes": ["文件内容满足确认的验收。"],
                "deviations": [],
                "limitations": [],
                "verification_receipt_ids": [receipt_id],
                "long_lived_refs": [],
                "method_application_results": [],
                "verification_review_results": _delivery_order_review_result(verified["work_item"]),
                "governance_rule_results": satisfied_governance_rule_results(
                    verified["work_item"]["data"]["engineering"]["plan"],
                    receipt_id,
                ),
            },
            ensure_ascii=False,
        ),
        "--version",
        str(verified["work_item"]["version"]),
    )["work_item"]
    assert awaiting_result["status"] == "awaiting_actual_result"
    assert _git(worktree, "rev-parse", "HEAD") == base_commit

    premature = runner.invoke(
        main,
        [
            "delivery",
            "--project-dir",
            str(project),
            "--work-item-id",
            identifier,
            "--version",
            str(awaiting_result["version"]),
        ],
    )
    assert premature.exit_code == 1
    assert "invalid_transition" in premature.output
    assert _git(worktree, "rev-parse", "HEAD") == base_commit

    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "premature result commit")
    result_challenge = awaiting_result["current_action"][
        "confirmation_challenge"
    ]
    rejected_confirmation = runner.invoke(
        main,
        [
            "confirm",
            "--project-dir",
            str(project),
            "--work-item-id",
            identifier,
            "--input",
            json.dumps(
                {
                    "candidate_fingerprint": result_challenge[
                        "candidate_fingerprint"
                    ],
                    "user_confirmation": "I accept the displayed candidate.",
                    "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
                },
                ensure_ascii=False,
            ),
            "--version",
            str(awaiting_result["version"]),
        ],
    )
    assert rejected_confirmation.exit_code == 1
    assert json.loads(rejected_confirmation.output)["error"]["code"] == (
        "premature_result_commit"
    )
    _git(worktree, "reset", "--soft", base_commit)

    confirmed = _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        identifier,
        "--kind",
        "actual_result",
        "--accepted",
        "--summary",
        "实际结果确认",
        "--version",
        str(awaiting_result["version"]),
    )["work_item"]
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "feat: deliver confirmed local result")
    result_commit = _git(worktree, "rev-parse", "HEAD")

    completed = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        identifier,
        "--version",
        str(confirmed["version"]),
    )["work_item"]
    assert completed["data"]["git"]["result_commits"] == [result_commit]
    assert (project / "feature.txt").read_text(encoding="utf-8") == "ready\n"
    assert completed["status"] == "completed"
    assert completed["current_action"] is None
    assert worktree == project
    assert worktree.exists()
    assert _git(project, "branch", "--show-current") == "main"
    assert _git(project, "rev-parse", "HEAD") == result_commit
    assert not _git(project, "branch", "--list", f"strixnova/{identifier}")
    assert _git(project, "status", "--porcelain") == ""


def test_cancel_cleans_only_safe_empty_work_and_preserves_dirty_work(
    tmp_path: Path,
) -> None:
    project = tmp_path / "cancel-project"
    project.mkdir()
    _git(project, "init")
    _git(project, "config", "user.name", "Strixnova Test")
    _git(project, "config", "user.email", "strixnova@example.invalid")
    (project / "tracked.txt").write_text("base\n", encoding="utf-8")
    _git(project, "add", "tracked.txt")
    _git(project, "commit", "-m", "initial")
    _git(project, "branch", "-M", "main")
    assessment_fixture(project)
    _adopt_portable_test_project(
        project,
        baseline_id="cancel-project",
    )
    runner = CliRunner()

    empty_item, empty_area = _item_with_work_area(runner, project, "空事项")
    empty_id = empty_item["work_item_id"]
    cancelled = _invoke(
        runner,
        project,
        "cancel",
        "--work-item-id",
        empty_id,
        "--reason",
        "不再需要",
        "--version",
        str(empty_item["version"]),
    )["work_item"]
    assert cancelled["status"] == "cancelled"
    assert cancelled["data"]["git"]["cleanup"]["safe"] is True
    assert Path(empty_area["worktree_path"]) == project
    assert project.exists()
    assert not _git(project, "branch", "--list", empty_area["work_ref"])

    dirty_item, dirty_area = _item_with_work_area(
        runner,
        project,
        "有草稿事项",
    )
    dirty_id = dirty_item["work_item_id"]
    dirty_tree = Path(dirty_area["worktree_path"])
    (dirty_tree / "draft.txt").write_text("keep me\n", encoding="utf-8")
    pending = _invoke(
        runner,
        project,
        "cancel",
        "--work-item-id",
        dirty_id,
        "--reason",
        "暂停事项",
        "--version",
        str(dirty_item["version"]),
    )["work_item"]
    assert pending["status"] == "cancelled_changes_pending"
    assert dirty_tree.exists()

    preserved = _invoke(
        runner,
        project,
        "cancel",
        "--work-item-id",
        dirty_id,
        "--decision",
        "preserve",
        "--details",
        json.dumps({"owner": "user"}),
        "--version",
        str(pending["version"]),
    )["work_item"]
    assert preserved["status"] == "cancelled"
    assert (dirty_tree / "draft.txt").read_text(encoding="utf-8") == "keep me\n"
    GitWorkspace(project).discard_cancelled_work(
        dirty_area,
        destructive_confirmed=True,
    )
