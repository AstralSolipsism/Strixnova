
from tests.support.project_context import FRONTEND
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

from click.testing import CliRunner
import pytest
import yaml

from strixnova.cli import main
from strixnova.git_workspace import GitWorkspace
from strixnova.workflow_authority import WorkflowAuthority
from tests.support.review_subject import bind_subject_arguments
from tests.support.project_configuration import configure_repository
from tests.support.governance_assessment import (
    assessment_fixture,
    exploration_assessment,
)
from tests.support.project_baseline import (
    TEST_INVARIANT_FACT_ID,
    TEST_TERM_FACT_ID,
    adopt_portable_ddd,
    portable_project_baseline,
)


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


def _invoke(runner: CliRunner, project: Path, command: str, *args: str) -> dict:
    result = runner.invoke(
        main,
        bind_subject_arguments(project, [command, *args, "--project-dir", str(project)]),
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output.strip())


def test_intake_rejects_unrecognized_authority_before_touching_git_excludes(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "main")
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
    original_database = database.read_bytes()
    exclude_path = tmp_path / ".git" / "info" / "exclude"
    original_exclude = exclude_path.read_bytes()

    result = CliRunner().invoke(
        main,
        [
            "intake",
            "--input",
            json.dumps({"title": "新事项", "request": "继续建设"}),
            "--project-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    output = json.loads(result.output.strip())
    assert output["error"]["code"] == "unsupported_authority_format"
    assert database.read_bytes() == original_database
    assert exclude_path.read_bytes() == original_exclude
    assert not (strixnova_root / ".gitignore").exists()


def _submit(
    runner: CliRunner,
    project: Path,
    work_item_id: str,
    version: int,
    payload: dict,
) -> dict:
    return _invoke(
        runner,
        project,
        "submit",
        "--work-item-id",
        work_item_id,
        "--version",
        str(version),
        "--input",
        json.dumps(payload, ensure_ascii=False),
    )["next"]


def _confirm(
    runner: CliRunner,
    project: Path,
    work_item_id: str,
    version: int,
    summary: str,
) -> dict:
    del summary
    challenge = WorkflowAuthority(project).get(work_item_id)[
        "current_action"
    ]["confirmation_challenge"]
    return _invoke(
        runner,
        project,
        "confirm",
        "--work-item-id",
        work_item_id,
        "--version",
        str(version),
        "--input",
        json.dumps(
            {
                "candidate_fingerprint": challenge[
                    "candidate_fingerprint"
                ],
                "user_confirmation": "I accept the displayed candidate.",
                "agent_decision": {"decision": "accept", "reason": "The later owner reply accepts this exact candidate."},
            },
            ensure_ascii=False,
        ),
    )["next"]


def _direction(
    goal: str,
    relations: list[dict] | None = None,
    *,
    decision_context: dict | None = None,
) -> dict:
    direction = {
        "schema_version": "strixnova.direction-decision.v1",
        "decision_context": decision_context
        or {
            "context_ref": None,
            "capability_refs": [],
            "guardrail_dispositions": [],
            "assumptions": [],
        },
        "goal": goal,
        "scope": [
            {
                "requirement_id": "DIRREQ-1111111111111111",
                "statement": "本地项目建设",
            }
        ],
        "non_goals": ["远程 Git 操作"],
        "constraints": [
            {
                "constraint_id": "DIRCON-2222222222222222",
                "statement": "先验证和确认，再形成提交",
            }
        ],
        "acceptance": [
            {
                "acceptance_id": "DIRACC-3333333333333333",
                "statement": "如实报告实际效果和限制",
                "requirement_refs": ["DIRREQ-1111111111111111"],
                "behavior": {"applicability": "not_applicable", "reason": "This fixture exercises workflow bookkeeping; behavior examples are covered separately."},
            }
        ],
        "tradeoffs": ["Git 原生管理分支、提交和合并"],
    }
    if relations is not None:
        direction["work_item_relations"] = relations
    return {
        "direction": direction,
        "ready_for_confirmation": True,
    }


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


def _bind_assessment(assessment: dict, current: dict) -> dict:
    assessment["direction_ref"] = {
        "work_item_id": current["work_item_id"],
        "direction_version": current["work_item_version"],
    }
    return assessment


def _complete_a0(
    runner: CliRunner,
    project: Path,
    *,
    title: str,
    request: str,
    goal: str,
    relations: list[dict] | None = None,
) -> dict:
    current = _invoke(
        runner,
        project,
        "intake",
        "--input",
        json.dumps({"title": title, "request": request}, ensure_ascii=False),
    )["next"]
    work_item_id = current["work_item_id"]
    current = _submit(
        runner,
        project,
        work_item_id,
        current["work_item_version"],
        _direction(goal, relations),
    )
    current = _confirm(
        runner,
        project,
        work_item_id,
        current["work_item_version"],
        "方向确认",
    )
    assessment = _bind_assessment(exploration_assessment(project), current)
    current = _submit(
        runner,
        project,
        work_item_id,
        current["work_item_version"],
        assessment,
    )
    current = _confirm(
        runner,
        project,
        work_item_id,
        current["work_item_version"],
        "按只读方案调查",
    )
    current = _invoke(
        runner,
        project,
        "delivery",
        "--work-item-id",
        work_item_id,
        "--version",
        str(current["work_item_version"]),
        "--input",
        json.dumps(
            {
                "schema_version": "strixnova.actual-result.v1",
                "semantic_content_machine_proven": False,
                "effect_summary": f"{title}的只读调查完成。",
                "verification_review_results": [
                    {"target_ref": entry["target_ref"], "outcome": "supported", "rationale": "按计划对照实际来源审阅调查结论。", "evidence_refs": ["direction"]}
                    for entry in assessment["verification_reviews"]
                ],
                "delivered_outcomes": ["已说明观察事实。"],
                "deviations": [],
                "limitations": ["没有修改或验证项目行为。"],
                "verification_receipt_ids": [],
                "long_lived_refs": [],
                "method_application_results": [],
                "governance_rule_results": [],
            },
            ensure_ascii=False,
        ),
    )["next"]
    return _confirm(
        runner,
        project,
        work_item_id,
        current["work_item_version"],
        "接受调查结论",
    )


def test_cli_exposes_public_intents_and_progressively_discloses_context(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    runtime_commands = {
        "action",
        "intake",
        "next",
        "submit",
        "confirm",
        "delivery",
        "verify",
        "cancel",
            "activity",
            "alignment",
            "status",
        "authority",
        "history",
        "upgrade",
        "context",
    }
    assert set(main.commands) == runtime_commands | {"setup-agent"}

    empty = _invoke(runner, tmp_path, "next")
    assert empty == {"ok": True, "work_items": []}
    assert not (tmp_path / ".strixnova").exists()

    started = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps(
            {"title": "优化测试", "request": "测试等待过久。"},
            ensure_ascii=False,
        ),
    )["next"]
    work_item_id = started["work_item_id"]
    assert started["records"] == {}
    assert started["current_action"]["action_type"] == "submit_direction"
    assert started["current_action"]["record_refs"] == [
        "request",
        "project.direction_context",
        "project.follow_ups",
    ]
    contract_ref = started["current_action"]["input_contract_ref"]
    assert contract_ref == "input.contract:submit_direction"

    request = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        work_item_id,
        "--record",
        "request",
        "--record",
        "project.direction_context",
        "--record",
        contract_ref,
    )["next"]
    assert request["records"]["request"]["raw_request"] == "测试等待过久。"
    assert request["records"]["project.direction_context"]["context_ref"] is None
    assert contract_ref in request['record_pages']
    command_ref = contract_ref + '#/command'
    command_record = _invoke(runner, tmp_path, 'next', '--work-item-id', work_item_id,
                             '--record', command_ref)['next']['records']
    assert command_record[command_ref] == 'submit'

    awaiting_confirmation = _submit(
        runner,
        tmp_path,
        work_item_id,
        started["work_item_version"],
        _direction("减少测试等待"),
    )
    assert awaiting_confirmation["current_action"]["intent"] == "confirm"
    assessment = _confirm(
        runner,
        tmp_path,
        work_item_id,
        awaiting_confirmation["work_item_version"],
        "方向确认",
    )
    assert assessment["current_action"]["input_kind"] == (
        "engineering_assessment"
    )


def test_unadopted_git_project_rejects_formal_change_before_plan_confirmation(
    tmp_path: Path,
) -> None:
    """A first repository delivery must establish the full authority chain."""

    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    assessment = assessment_fixture(tmp_path)
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "initial")
    investigation_commit = _git(tmp_path, "rev-parse", "HEAD")

    runner = CliRunner()
    status = _invoke(runner, tmp_path, "status")["status"]
    assert status["baseline_id"] is None
    assert status["observed_commit"] is None
    assert status["next_required_actions"] == [
        "adopt_project_authorities_before_repository_delivery"
    ]

    started = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps(
            {"title": "修改现有能力", "request": "调整现有项目行为。"},
            ensure_ascii=False,
        ),
    )["next"]
    current = _submit(
        runner,
        tmp_path,
        started["work_item_id"],
        started["work_item_version"],
        _direction("调整现有项目行为"),
    )
    current = _confirm(
        runner,
        tmp_path,
        started["work_item_id"],
        current["work_item_version"],
        "方向确认",
    )
    action = current["current_action"]
    assert action["record_refs"] == [
        "direction",
        "direction_confirmation",
        "project.direction_context",
        "project.follow_ups",
    ]
    assert action["conditional_record_refs"] == []

    unavailable = runner.invoke(
        main,
        [
            "next",
            "--project-dir",
            str(tmp_path),
            "--work-item-id",
            started["work_item_id"],
            "--record",
            "project.engineering",
        ],
    )
    assert unavailable.exit_code == 1
    assert json.loads(unavailable.output)["error"]["code"] == (
        "record_not_available_for_action"
    )

    required = _invoke(
        runner,
        tmp_path,
        "next",
        # This test checks complete contract semantics; bounded traversal is
        # exercised independently with small and default response budgets.
        "--max-output-bytes",
        "1048576",
        "--work-item-id",
        started["work_item_id"],
        "--record",
        action["input_contract_ref"],
        "--record",
        "direction",
        "--record",
        "direction_confirmation",
    )["next"]["records"]
    assert set(required) == {
        action["input_contract_ref"],
        "direction",
        "direction_confirmation",
    }
    assert required[action["input_contract_ref"]]["contract_ref"] == (
        action["input_contract_ref"]
    )

    assessment["investigation_ref"] = investigation_commit
    assessment["source_references"][0]["observed_ref"] = investigation_commit
    _bind_assessment(assessment, current)
    rejected = runner.invoke(
        main,
        [
            "submit",
            "--project-dir",
            str(tmp_path),
            "--work-item-id",
            started["work_item_id"],
            "--version",
            str(current["work_item_version"]),
            "--input",
            json.dumps(assessment, ensure_ascii=False),
        ],
    )

    assert rejected.exit_code == 1
    error = json.loads(rejected.output)["error"]
    assert error["code"] == "unadopted_project_requires_create_project"
    assert error["details"] == {
        "current_change_kind": "modify_existing",
        "required_change_kind": "create_project",
    }
    unchanged = WorkflowAuthority(tmp_path).get(started["work_item_id"])
    assert unchanged["current_action"]["action_type"] == (
        "submit_engineering_assessment"
    )
    assert not (tmp_path / "strixnova-project.yaml").exists()
    assert not (tmp_path / "docs/engineering/baseline.yaml").exists()


def test_cli_reports_configured_integration_ref_that_is_missing_locally(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init", "-b", "work")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')

    runner = CliRunner()
    started = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps(
            {"title": "检查仓库结构", "request": "确认目录职责是否清晰。"},
            ensure_ascii=False,
        ),
    )["next"]
    result = runner.invoke(
        main,
        [
            "next",
            "--work-item-id",
            started["work_item_id"],
            "--record",
            "project.direction_context",
            "--project-dir",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output.strip())
    assert payload["error"]["code"] == "integration_ref_not_found"
    assert "main" in payload["error"]["message"]
    assert started["work_item_version"] == 1


@pytest.mark.parametrize("with_generated_artifacts", [False, True])
def test_cli_explicitly_checks_an_uncommitted_working_tree_candidate(
    tmp_path: Path,
    with_generated_artifacts: bool,
) -> None:
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "initial evidence")
    evidence_commit = _git(tmp_path, "rev-parse", "HEAD")

    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="cli-working-tree-candidate",
        artifacts=[],
    )
    identities = adopt_portable_ddd(tmp_path, baseline)
    baseline["code_version"]["repositories"][0]["base_commit"] = evidence_commit
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    alignment_path = tmp_path / identities["alignment_path"]
    alignment = yaml.safe_load(alignment_path.read_text(encoding="utf-8"))
    alignment["code_snapshot"]["repositories"][0]["base_commit"] = evidence_commit
    alignment_path.write_text(
        yaml.safe_dump(alignment, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')

    artifact = tmp_path / ".strixnova" / "artifacts" / "implementation-alignment" / "snapshot.json"
    if with_generated_artifacts:
        artifact.parent.mkdir(parents=True)
        artifact.write_bytes(b'{"generated":true}\n')

    runner = CliRunner()
    adopted = _invoke(runner, tmp_path, "status")["status"]
    candidate = _invoke(runner, tmp_path, "status", "--working-tree")[
        "status"
    ]

    assert adopted["authority_scope"] == "unadopted_project"
    assert adopted["baseline_id"] is None
    assert candidate["authority_scope"] == "working_tree_candidate"
    assert candidate["candidate_only"] is True
    assert candidate["observed_commit"] is None
    assert candidate["baseline_id"] == baseline["baseline_id"]
    assert candidate["cross_authority_consistency"][
        "structurally_consistent"
    ] is True
    assert not (tmp_path / ".strixnova" / "authority.sqlite3").exists()
    if with_generated_artifacts:
        assert artifact.read_bytes() == b'{"generated":true}\n'
        assert not (tmp_path / ".strixnova" / ".gitignore").exists()

    conflict = runner.invoke(
        main,
        [
            "status",
            "--working-tree",
            "--at-commit",
            evidence_commit,
            "--project-dir",
            str(tmp_path),
        ],
    )
    assert conflict.exit_code == 1
    assert json.loads(conflict.output)["error"]["code"] == (
        "project_status_scope_conflict"
    )


def test_cli_reads_domain_catalog_then_only_requested_fact_and_closure(
    tmp_path: Path,
) -> None:
    """Prove the public progressive-read seam without a new CLI intent."""

    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    (tmp_path / "src.py").write_text("VALUE = 1\n", encoding="utf-8")
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="on-demand-domain-project",
        artifacts=[
            {
                "artifact_id": "BASELINE-001",
                "artifact_type": "product_governance",
                "path": "docs/engineering/baseline.yaml",
                "status": "current",
                "relations": [],
            }
        ],
    )
    identities = adopt_portable_ddd(tmp_path, baseline)
    baseline_path = tmp_path / "docs/engineering/baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "adopt portable domain model")
    _git(tmp_path, "branch", "-M", "main")

    runner = CliRunner()
    started = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps(
            {
                "title": "调整事项术语",
                "request": "让事项术语更容易理解。",
            },
            ensure_ascii=False,
        ),
    )["next"]
    awaiting = _submit(
        runner,
        tmp_path,
        started["work_item_id"],
        started["work_item_version"],
        _direction(
            "让事项术语更容易理解",
            decision_context=_direction_context_binding(
                runner,
                tmp_path,
                started["work_item_id"],
            ),
        ),
    )
    assessing = _confirm(
        runner,
        tmp_path,
        started["work_item_id"],
        awaiting["work_item_version"],
        "方向确认",
    )
    assert "project.engineering" in assessing["current_action"][
        "conditional_record_refs"
    ]
    assert "project.domain.catalog" in assessing["current_action"][
        "conditional_record_refs"
    ]

    engineering_record = "project.engineering"
    catalog_record = "project.domain.catalog"
    initial_records = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        started["work_item_id"],
        "--record",
        engineering_record,
        "--record",
        catalog_record,
    )["next"]["records"]
    engineering = initial_records[engineering_record]
    ddd = next(
        item
        for item in engineering["engineering_methods"]
        if item["method_id"] == "ddd"
    )
    assert ddd["status"] == "adopted"
    assert ddd["policy_ref"] == "engineering-policy:method:ddd"
    assert ddd["adopted_technique_ids"]

    catalog = initial_records[catalog_record]
    assert engineering["observed_commit"] == catalog["observed_commit"]
    assert catalog["fact_bodies_included"] is False
    assert TEST_TERM_FACT_ID not in repr(catalog)
    assert "WorkItem 是一次需要闭环管理的建设事项" not in repr(catalog)

    collection_record = catalog["root_collections"][0]["record_ref"]
    collection = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        started["work_item_id"],
        "--record",
        collection_record,
    )["next"]["records"][collection_record]
    assert [item["title"] for item in collection["sources"]] == [
        "测试领域事实"
    ]
    assert TEST_TERM_FACT_ID not in repr(collection)

    source_record = collection["sources"][0]["record_ref"]
    source = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        started["work_item_id"],
        "--record",
        source_record,
    )["next"]["records"][source_record]
    assert TEST_TERM_FACT_ID in {
        item["fact_id"] for item in source["facts"]
    }
    assert "WorkItem 是一次需要闭环管理的建设事项" not in repr(source)

    fact_record = next(
        item["record_ref"]
        for item in source["facts"]
        if item["fact_id"] == TEST_TERM_FACT_ID
    )
    closure_record = f"project.domain.closure:{TEST_INVARIANT_FACT_ID}"
    selected_records = _invoke(
        runner,
        tmp_path,
        "next",
        "--max-output-bytes",
        "65536",
        "--work-item-id",
        started["work_item_id"],
        "--record",
        fact_record,
        "--record",
        closure_record,
    )["next"]["records"]
    fact = selected_records[fact_record]
    assert fact["content"] == {
        "term": "建设事项",
        "definition": "一次需要闭环管理的软件工程建设活动。",
    }
    assert fact["_observed_commit"] == _git(
        tmp_path, "rev-parse", "main"
    )

    closure = selected_records[closure_record]
    assert closure["bodies_loaded"] is True
    assert {TEST_INVARIANT_FACT_ID, identities["term_fact_id"]} <= set(
        closure["fact_ids"]
    )

    default_list = _invoke(runner, tmp_path, "next")
    assert "fact_bodies_included" not in repr(default_list)
    assert "WorkItem 是一次需要闭环管理的建设事项" not in repr(default_list)


def test_cli_rejects_non_text_semantics_before_creating_authority(
    tmp_path: Path,
) -> None:
    runner = CliRunner()

    result = runner.invoke(
        main,
        [
            "intake",
            "--project-dir",
            str(tmp_path),
            "--input",
            json.dumps({"title": True, "request": "不能伪装标题"}),
        ],
    )

    assert result.exit_code != 0
    assert "必须是字符串" in result.output
    assert not (tmp_path / ".strixnova").exists()


def test_intake_preserves_a_tracked_strixnova_ignore_and_clean_git(
    tmp_path: Path,
    monkeypatch,
) -> None:
    strixnova_root = tmp_path / ".strixnova"
    strixnova_root.mkdir()
    tracked_ignore = (
        "# Existing project-local rules.\n"
        "authority/\n"
        "runtime/\n"
        "cache/\n"
        "artifacts/\n"
    )
    (strixnova_root / ".gitignore").write_text(
        tracked_ignore,
        encoding="utf-8",
    )
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    _git(tmp_path, "add", ".strixnova/.gitignore")
    _git(tmp_path, "commit", "-m", "track project local-state policy")
    exclude_calls: list[tuple[str, ...]] = []
    original_ensure = GitWorkspace.ensure_local_excludes

    def counted_ensure(
        workspace: GitWorkspace,
        patterns: tuple[str, ...],
    ) -> None:
        exclude_calls.append(tuple(patterns))
        original_ensure(workspace, patterns)

    monkeypatch.setattr(
        GitWorkspace,
        "ensure_local_excludes",
        counted_ensure,
    )

    created = _invoke(
        CliRunner(),
        tmp_path,
        "intake",
        "--input",
        json.dumps({"title": "事项", "request": "建设能力"}),
    )
    _invoke(
        CliRunner(),
        tmp_path,
        "intake",
        "--input",
        json.dumps({"title": "第二事项", "request": "验证幂等初始化"}),
    )

    assert created["next"]["current_action"]["input_kind"] == "direction"
    assert (strixnova_root / ".gitignore").read_text(
        encoding="utf-8"
    ) == tracked_ignore
    assert _git(tmp_path, "status", "--porcelain") == ""
    assert len(exclude_calls) == 1
    exclude_path = Path(
        _git(tmp_path, "rev-parse", "--git-path", "info/exclude")
    )
    if not exclude_path.is_absolute():
        exclude_path = tmp_path / exclude_path
    exclude_lines = exclude_path.read_text(encoding="utf-8").splitlines()
    for expected in (
        "/.strixnova/.gitignore",
        "/.strixnova/authority.sqlite3*",
        "/.strixnova/artifacts/",
    ):
        assert exclude_lines.count(expected) == 1

    exclude_path.write_text(
        "# Simulate a user removing Strixnova's local excludes.\n",
        encoding="utf-8",
    )
    _invoke(
        CliRunner(),
        tmp_path,
        "intake",
        "--input",
        json.dumps({"title": "第三事项", "request": "修复本地排除"}),
    )
    assert len(exclude_calls) == 2
    repaired_lines = exclude_path.read_text(encoding="utf-8").splitlines()
    for expected in (
        "/.strixnova/.gitignore",
        "/.strixnova/authority.sqlite3*",
        "/.strixnova/artifacts/",
    ):
        assert repaired_lines.count(expected) == 1
    assert _git(tmp_path, "status", "--porcelain") == ""


def test_cli_projects_relations_only_for_each_focused_work_item(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    target = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps(
            {"title": "基础事项", "request": "建立基础能力"},
            ensure_ascii=False,
        ),
    )["next"]
    source = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps(
            {"title": "延续事项", "request": "继续已有工作"},
            ensure_ascii=False,
        ),
    )["next"]
    relation = {
        "target_work_item_id": target["work_item_id"],
        "relation_type": "follows_up",
        "reason": "延续事项承接基础事项。",
    }

    awaiting = _submit(
        runner,
        tmp_path,
        source["work_item_id"],
        source["work_item_version"],
        _direction("延续基础能力", [relation]),
    )
    before = _invoke(runner, tmp_path, "next")["work_items"]
    assert all("relations" not in item for item in before)
    source_before = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        source["work_item_id"],
    )["next"]
    target_before = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        target["work_item_id"],
    )["next"]
    assert source_before["relations"]["declared"] == []
    assert target_before["relations"]["referenced_by"] == []

    _confirm(
        runner,
        tmp_path,
        source["work_item_id"],
        awaiting["work_item_version"],
        "方向及关系确认",
    )
    after = _invoke(runner, tmp_path, "next")["work_items"]
    assert all("relations" not in item for item in after)
    source_after = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        source["work_item_id"],
    )["next"]
    target_after = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        target["work_item_id"],
    )["next"]

    assert source_after["relations"]["declared"][0][
        "target_work_item_id"
    ] == target["work_item_id"]
    assert target_after["relations"]["referenced_by"][0][
        "source_work_item_id"
    ] == source["work_item_id"]


def test_setup_agent_installs_only_the_packaged_skill(tmp_path: Path) -> None:
    runner = CliRunner()
    skills_dir = tmp_path / "agent-skills"

    result = runner.invoke(
        main,
        ["setup-agent", "--skills-dir", str(skills_dir)],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["install"]["status"] == "installed"
    assert payload["install"]["modifies_host_config"] is False
    assert payload["install"]["installs_hooks"] is False
    installed_root = skills_dir / "strixnova"
    installed_files = {
        path.relative_to(installed_root).as_posix()
        for path in installed_root.rglob("*")
        if path.is_file()
    }
    assert installed_files == {
        "SKILL.md",
        "agents/openai.yaml",
        "references/architecture-artifact-contracts.md",
        "references/artifact-documentation.md",
        "references/artifact-formation.md",
        "references/behavior-contracts.md",
        "references/behavior-examples.md",
        "references/code-review.md",
        "references/authority-authoring.md",
        "references/confirmation-and-cancel.md",
        "references/cross-artifact-review.md",
        "references/delivery.md",
        "references/direction.md",
        "references/domain-documentation.md",
        "references/domain-fact-contracts.md",
        "references/domain-modeling-and-alignment.md",
        "references/engineering-assessment.md",
        "references/engineering-methods.md",
        "references/engineering-policy-contracts.md",
        "references/history-and-upgrade.md",
        "references/follow-ups.md",
        "references/implementation-alignment-artifact-contracts.md",
        "references/implementation-alignment-workflow.md",
        "references/implementation-practices.md",
        "references/prd-authoring.md",
        "references/prepared-input.md",
        "references/product-discovery.md",
        "references/replanning.md",
        "references/spec-authoring.md",
        "references/ux-design.md",
        "references/verification.md",
    }


def test_cli_accepts_windows_utf8_bom_on_json_stdin(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        ["intake", "--project-dir", str(tmp_path), "--input", "@-"],
        input="\ufeff" + json.dumps({"title": "事项", "request": "建设能力"}),
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["next"]["current_action"]["action_type"] == (
        "submit_direction"
    )


def test_cli_returns_typed_json_error_without_traceback(tmp_path: Path) -> None:
    runner = CliRunner()
    started = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps({"title": "事项", "request": "建设能力"}),
    )["next"]

    result = runner.invoke(
        main,
        [
            "submit",
            "--project-dir",
            str(tmp_path),
            "--work-item-id",
            started["work_item_id"],
            "--version",
            "99",
            "--input",
            json.dumps(_direction("建设能力"), ensure_ascii=False),
        ],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output.strip())
    assert payload["error"]["code"] == "authority_conflict"
    assert "Traceback" not in result.output


def test_cli_help_does_not_expose_removed_commands_or_session_mechanisms() -> None:
    result = CliRunner().invoke(main, ["--help"])

    assert result.exit_code == 0
    for removed in (
        "turn",
        "implement",
        "result",
        "list",
        "dashboard",
        "sections",
        "ui",
        "resolve-cancel",
        "review",
        "session",
        "credential",
        "lease",
        "hook",
    ):
        assert removed not in main.commands


def test_delivery_pauses_when_target_advanced_after_assessment(
    tmp_path: Path,
) -> None:
    _git(tmp_path, "init")
    _git(tmp_path, "config", "user.name", "Strixnova Test")
    _git(tmp_path, "config", "user.email", "strixnova@example.invalid")
    assessment = assessment_fixture(tmp_path)
    # This scenario exercises target advancement before implementation, not
    # source-alignment planning. Use an ungoverned note operation; dedicated
    # planning tests cover the required alignment operation for source changes.
    assessment["operations"][0].update(action="create", path="notes.txt")
    _git(tmp_path, "add", "src.py")
    _git(tmp_path, "commit", "-m", "initial source")
    source_commit = _git(tmp_path, "rev-parse", "HEAD")
    baseline = portable_project_baseline(
        tmp_path,
        baseline_id="target-advance-project",
        artifacts=[],
    )
    adopt_portable_ddd(tmp_path, baseline)
    baseline["code_version"] = {'repositories': [{'repository_id': FRONTEND, 'base_commit': source_commit, 'worktree_state': 'clean'}]}
    baseline["review_state"] = {
        "required": True,
        "reasons": ["隔离测试实现对齐仍需复核。"],
        "affected_authority_kinds": ["implementation_alignment"],
    }
    baseline_path = tmp_path / "docs" / "engineering" / "baseline.yaml"
    baseline_path.write_text(
        yaml.safe_dump(baseline, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    configure_repository(tmp_path, baseline_path='docs/engineering/baseline.yaml', integration_ref='main')
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "adopt project authorities")
    _git(tmp_path, "branch", "-M", "main")
    assessment["investigation_ref"] = "main"
    assessment["source_references"][0]["observed_ref"] = "main"
    assessment["verification_commands"][0]["argv"][0] = sys.executable
    runner = CliRunner()

    started = _invoke(
        runner,
        tmp_path,
        "intake",
        "--input",
        json.dumps({"title": "目标前进", "request": "按当前事实实施"}),
    )["next"]
    work_item_id = started["work_item_id"]
    current = _submit(
        runner,
        tmp_path,
        work_item_id,
        started["work_item_version"],
        _direction(
            "按当前事实实施",
            decision_context=_direction_context_binding(
                runner,
                tmp_path,
                work_item_id,
            ),
        ),
    )
    current = _confirm(
        runner,
        tmp_path,
        work_item_id,
        current["work_item_version"],
        "方向准确",
    )
    _bind_assessment(assessment, current)
    current = _submit(
        runner,
        tmp_path,
        work_item_id,
        current["work_item_version"],
        assessment,
    )
    current = _confirm(
        runner,
        tmp_path,
        work_item_id,
        current["work_item_version"],
        "工程方案确认",
    )

    (tmp_path / "unrelated.txt").write_text("advanced\n", encoding="utf-8")
    _git(tmp_path, "add", "unrelated.txt")
    _git(tmp_path, "commit", "-m", "advance target")
    paused = _invoke(
        runner,
        tmp_path,
        "delivery",
        "--work-item-id",
        work_item_id,
        "--version",
        str(current["work_item_version"]),
        "--input",
        json.dumps({"target_ref": "main"}),
    )["next"]

    assert paused["current_action"]["action_type"] == "assess_target_advance"
    assert paused["current_action"]["intent"] == "submit"
    assert "changed_paths" not in WorkflowAuthority(tmp_path).get(work_item_id)[
        "data"
    ]["git"]["target_advance"]


@pytest.mark.parametrize(
    ("reply", "decision", "status"),
    [
        ("  可以，按刚才的方向继续。\n", "accept", "needs_engineering_assessment"),
        ("方向可以，\n但请先缩小范围。  ", "request_changes", "discussion"),
    ],
)
def test_cli_records_natural_reply_and_agent_decision_without_normalizing(
    tmp_path: Path, reply: str, decision: str, status: str,
) -> None:
    runner = CliRunner()
    created = _invoke(runner, tmp_path, "intake", "--input", json.dumps({
        "title": "Natural confirmation", "request": "Improve test feedback",
    }))["next"]
    identifier = created["work_item_id"]
    current = _submit(runner, tmp_path, identifier, created["work_item_version"], _direction("Improve test feedback"))
    challenge = WorkflowAuthority(tmp_path).get(identifier)["current_action"]["confirmation_challenge"]
    payload = {
        "candidate_fingerprint": challenge["candidate_fingerprint"],
        "user_confirmation": reply,
        "agent_decision": {"decision": decision, "reason": "The Agent applied this later owner reply to the displayed direction."},
    }
    _invoke(runner, tmp_path, "confirm", "--work-item-id", identifier,
            "--version", str(current["work_item_version"]),
            "--input", json.dumps(payload, ensure_ascii=False))
    item = WorkflowAuthority(tmp_path).get(identifier)
    assert item["status"] == status
    record = item["data"]["direction_confirmation"]
    assert record["user_confirmation"] == reply
    assert record["agent_decision"] == payload["agent_decision"]
    assert record["semantic_content_machine_proven"] is False


def test_cli_completes_a0_exploration_without_git_or_fake_receipt(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    current = _complete_a0(
        runner,
        tmp_path,
        title="只读调查",
        request="调查现象，不改项目",
        goal="只读调查当前现象",
    )

    assert current["work_item_status"] == "completed"
    assert current["current_action"] is None
    assert not (tmp_path / ".git").exists()


def test_cli_reads_part_of_relation_from_both_completed_work_items(
    tmp_path: Path,
) -> None:
    runner = CliRunner()
    target = _complete_a0(
        runner,
        tmp_path,
        title="质量管理大事项",
        request="说明质量管理建设方向",
        goal="明确质量管理建设方向",
    )
    relation = {
        "target_work_item_id": target["work_item_id"],
        "relation_type": "part_of",
        "reason": "测试证据整理是质量管理大事项的一部分。",
    }
    source = _complete_a0(
        runner,
        tmp_path,
        title="整理测试证据",
        request="把测试证据整理拆成独立事项",
        goal="说明测试证据整理范围",
        relations=[relation],
    )

    assert _invoke(runner, tmp_path, "next")["work_items"] == []
    source_focus = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        source["work_item_id"],
    )["next"]
    target_focus = _invoke(
        runner,
        tmp_path,
        "next",
        "--work-item-id",
        target["work_item_id"],
    )["next"]

    assert source_focus["work_item_status"] == "completed"
    assert source_focus["current_action"] is None
    assert source_focus["relations"]["declared"][0]["relation_type"] == (
        "part_of"
    )
    assert target_focus["work_item_status"] == "completed"
    assert target_focus["relations"]["referenced_by"][0][
        "source_work_item_id"
    ] == source["work_item_id"]
