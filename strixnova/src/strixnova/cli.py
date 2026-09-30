"""Small intent-oriented command interface for Coding Agents."""

from __future__ import annotations

from functools import wraps
import json
from pathlib import Path
import sys
from typing import Any, Callable, ParamSpec, TypeVar

import click

from strixnova import __version__
from strixnova.confirmation_protocol import ConfirmationProtocolError, attach_confirmation_message
from strixnova.application_coordinator import (
    ApplicationCoordinator,
    ApplicationCoordinatorError,
)
from strixnova.host_adapter import (
    HostAdapterError,
    LocalHostAdapter,
)
from strixnova.runtime_upgrade import MaintenanceError, RuntimeUpgrade, runtime_identity, stop_evidence_contract
from strixnova.managed_installation import ManagedInstallation
from strixnova.review_context_projection import render_review_context
from strixnova.prepared_input import PreparedInputError
from strixnova.record_reading import DEFAULT_OUTPUT_BYTES


P = ParamSpec("P")
R = TypeVar("R")


def _configure_captured_output() -> None:
    """Use UTF-8 for redirected human-readable output on Windows hosts."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        isatty = getattr(stream, "isatty", None)
        if not callable(reconfigure) or not callable(isatty) or isatty():
            continue
        reconfigure(encoding="utf-8", errors="strict")


class _CapturedOutputGroup(click.Group):
    def main(self, *args: Any, **kwargs: Any) -> Any:
        _configure_captured_output()
        return super().main(*args, **kwargs)


def _contract_text(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise click.BadParameter(f"{field} 必须是字符串")
    if not value.strip():
        raise click.BadParameter(f"{field} 必须是非空字符串")
    return value.strip()


def _emit(value: Any) -> None:
    # The CLI is a structured Agent interface. ASCII JSON is lossless after
    # parsing and survives Windows console, pipe, and host-capture encodings
    # without requiring the caller to guess the active code page.
    click.echo(json.dumps(value, ensure_ascii=True, sort_keys=True))


def _project(value: Path) -> Path:
    project = value.expanduser().resolve()
    if not project.is_dir():
        raise click.BadParameter(f"项目目录不存在：{project}")
    return project


def _load_object(value: str) -> dict[str, Any]:
    raw = value.strip()
    if raw == "@-":
        binary_stdin = getattr(sys.stdin, "buffer", None)
        if binary_stdin is None:
            raw = sys.stdin.read()
        else:
            try:
                raw = binary_stdin.read().decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise click.BadParameter("stdin 必须是 UTF-8") from error
    elif raw.startswith("@"):
        path = Path(raw[1:]).expanduser().resolve()
        try:
            raw = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError as error:
            raise click.BadParameter(f"输入文件必须是 UTF-8：{path}") from error
        except OSError as error:
            raise click.BadParameter(f"无法读取输入文件：{path}") from error
    raw = raw.removeprefix("\ufeff")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as error:
        raise click.BadParameter(f"输入不是有效 JSON：{error.msg}") from error
    if not isinstance(parsed, dict):
        raise click.BadParameter("输入 JSON 必须是对象")
    return parsed


def _user_message(path: Path) -> str:
    # Decode bytes directly: universal-newline text reads would alter CRLF.
    try:
        return path.read_bytes().decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise click.BadParameter("User message source must be UTF-8") from error


def _command_errors(
    function: Callable[P, R],
) -> Callable[P, R | None]:
    @wraps(function)
    def wrapped(*args: P.args, **kwargs: P.kwargs) -> R | None:
        try:
            return function(*args, **kwargs)
        except (
            ApplicationCoordinatorError,
            HostAdapterError,
            MaintenanceError,
            ConfirmationProtocolError,
            PreparedInputError,
            OSError,
        ) as error:
            code = getattr(error, "code", "local_io_failed" if isinstance(error, OSError) else "application_use_case_rejected")
            details = getattr(error, "issues", None) or getattr(
                error,
                "details",
                None,
            )
            error_payload: dict[str, Any] = {
                "code": code,
                "message": str(error),
            }
            if details:
                error_payload["details"] = (
                    list(details)
                    if isinstance(details, (list, tuple))
                    else details
                )
            _emit(
                {
                    "ok": False,
                    "error": error_payload,
                }
            )
            raise click.exceptions.Exit(1) from None

    return wrapped

def _emit_next(
    project: Path,
    work_item_id: str,
    **facts: Any,
) -> None:
    _emit(
        {
            "ok": True,
            **facts,
            "next": _adapter(project).next_step(work_item_id),
        }
    )


PROJECT_OPTION = click.option(
    "--project-dir",
    type=click.Path(
        exists=True,
        file_okay=False,
        path_type=Path,
    ),
    default=".",
    show_default=True,
)


@click.group(cls=_CapturedOutputGroup)
@click.version_option(__version__, prog_name="strixnova")
@click.option("--project-bindings", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="明确本机绑定的 JSON 文件，格式见 context contract bindings。")
@click.pass_context
def main(context: click.Context, project_bindings: Path | None) -> None:
    """Strixnova：面向非专业项目负责人的本地软件工程治理。"""

    context.ensure_object(dict)
    context.obj["project_bindings"] = _load_object("@" + str(project_bindings)) if project_bindings else None


def _adapter(project: Path) -> LocalHostAdapter:
    context = click.get_current_context(silent=True)
    bindings = context.find_root().obj.get("project_bindings") if context and context.find_root().obj else None
    return LocalHostAdapter(project, project_bindings=bindings)


def _coordinator(project: Path) -> ApplicationCoordinator:
    return _adapter(project).coordinator


@main.group("context")
def context() -> None:
    """只读检查项目范围、读取内容或准备审阅资料；不采用配置或创建事项。"""


@context.command("contract")
@click.argument("action", type=click.Choice(["inspect", "read", "review", "configuration", "bindings"]))
@_command_errors
def context_contract(action: str) -> None:
    """读取上下文查询的完整输入合同。"""

    _emit({"ok": True, "contract": LocalHostAdapter.context_contract(action)})


@context.command("inspect")
@PROJECT_OPTION
@click.option("--input", "input_value", required=True, help="JSON、@文件或 @-；格式见 context contract inspect。")
@_command_errors
def context_inspect(project_dir: Path, input_value: str) -> None:
    """检查候选项目与仓库绑定；不读取或写入事项权威。"""

    _emit({
        "ok": True,
        "context": LocalHostAdapter.query_project_context(project_dir, "inspect", _load_object(input_value)),
    })


@context.command("read")
@PROJECT_OPTION
@click.option("--input", "input_value", required=True, help="JSON、@文件或 @-；格式见 context contract read。")
@_command_errors
def context_read(project_dir: Path, input_value: str) -> None:
    """从明确仓库读取有界内容窗口，返回原字节、摘要与实际版本。"""

    _emit({
        "ok": True,
        "content": LocalHostAdapter.query_project_context(project_dir, "read", _load_object(input_value)),
    })


@context.command("review")
@PROJECT_OPTION
@click.option("--input", "input_value", required=True, help="JSON、@文件或 @-；格式见 context contract review。")
@click.option("--format", "output_format", type=click.Choice(["json", "markdown"]), default="json", show_default=True)
@_command_errors
def context_review(project_dir: Path, input_value: str, output_format: str) -> None:
    """为本次改动或指定模块准备审阅资料，保留来源、版本和缺口。"""

    request = _load_object(input_value)
    root = click.get_current_context().find_root()
    bindings = (root.obj or {}).get("project_bindings")
    if bindings is not None:
        if "bindings" in request and request["bindings"] != bindings:
            raise click.BadParameter("请求绑定与 --project-bindings 不一致")
        request["bindings"] = bindings
    result = LocalHostAdapter.query_project_context(project_dir, "review", request)
    if output_format == "markdown":
        click.echo(render_review_context(result))
    else:
        _emit({"ok": True, "context": result})


@main.command("setup-agent")
@click.option(
    "--skills-dir",
    type=click.Path(file_okay=False, path_type=Path),
    help="Agent 的 skills 根目录；默认使用 CODEX_HOME/skills 或 ~/.codex/skills。",
)
@click.option(
    "--replace",
    is_flag=True,
    help="备份已有不同版本后替换；不会静默覆盖。",
)
@_command_errors
def setup_agent(skills_dir: Path | None, replace: bool) -> None:
    """安装轻量 Agent Skill；不修改配置、不安装 hook 或插件。"""

    _emit(
        {
            "ok": True,
            "install": ApplicationCoordinator.install_agent_guidance(
                skills_dir=skills_dir,
                replace=replace,
            ),
        }
    )


@main.group("alignment")
def alignment() -> None:
    """准备、检查实现观察，授权外部捕获并写入实现对齐草稿。"""


def _alignment_transport(project: Path, work_item_id: str, version: int, result: dict[str, Any]) -> dict[str, Any]:
    return {"schema_version": "strixnova.alignment-input-context.v1", "project": str(project),
            "work_item_id": work_item_id, "work_item_version": version, "preparation_ref": result["preparation_ref"]}


def _alignment_input(project: Path, prepared: Path | None, work_item_id: str | None,
                     version: int | None, payload: dict[str, Any]) -> tuple[str, int, dict[str, Any]]:
    if prepared is not None:
        context = _load_object("@" + str(prepared))
        expected = {"schema_version", "project", "work_item_id", "work_item_version", "preparation_ref"}
        if set(context) != expected or context["schema_version"] != "strixnova.alignment-input-context.v1" or context["project"] != str(project):
            raise click.BadParameter("Prepared alignment belongs to another project or has an invalid binding")
        if work_item_id is not None or version is not None or "preparation_ref" in payload:
            raise click.BadParameter("Use the prepared binding without duplicate identity fields")
        work_item_id, version = context["work_item_id"], context["work_item_version"]
        payload = {**payload, "preparation_ref": context["preparation_ref"]}
    if not isinstance(work_item_id, str) or not work_item_id or type(version) is not int or version < 1:
        raise click.BadParameter("Supply --prepared or explicit work-item-id and version")
    return work_item_id, version, payload


@alignment.command("prepare")
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option("--version", type=click.IntRange(min=1), required=True)
@click.option(
    "--input",
    "input_value",
    help="首次或新修订的最小观察范围 JSON、@UTF-8 文件或 @-。",
)
@click.option("--output", type=click.Path(path_type=Path), help="Save the exact binding for --prepared; no model copying of preparation_ref.")
@_command_errors
def alignment_prepare(
    project_dir: Path,
    work_item_id: str,
    version: int,
    input_value: str | None,
    output: Path | None,
) -> None:
    """生成内容寻址观察包；不改变 WorkItem 或长期权威。"""

    project = _project(project_dir)
    request = _load_object(input_value) if input_value is not None else None
    result = _coordinator(project).prepare_implementation_alignment(work_item_id, request, expected_version=version)
    if output is not None:
        _write_transport(output, _alignment_transport(project, work_item_id, version, result))
        _emit({"ok": True, "prepared": str(output.resolve())})
    else:
        _emit({"ok": True, "alignment": result})


@alignment.command("inspect")
@PROJECT_OPTION
@click.option("--work-item-id")
@click.option("--version", type=click.IntRange(min=1))
@click.option(
    "--input",
    "input_value",
    default="{}",
    help="只包含 prepare 返回的 preparation_ref；支持 @UTF-8 文件或 @-。",
)
@click.option(
    "--cursor",
    help="上一页返回的不透明 next_cursor；首页省略。",
)
@click.option(
    "--limit",
    type=click.IntRange(min=1, max=200),
    default=50,
    show_default=True,
    help="本页最多返回的逻辑记录数。",
)
@click.option("--prepared", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), help="Assemble all pages of this exact selected preparation into a local material file.")
@_command_errors
def alignment_inspect(
    project_dir: Path,
    work_item_id: str | None,
    version: int | None,
    input_value: str,
    prepared: Path | None,
    cursor: str | None,
    limit: int,
    output: Path | None,
) -> None:
    """分页读取判断所需逻辑事实；不暴露或修改缓存布局。"""

    project = _project(project_dir)
    work_item_id, version, payload = _alignment_input(project, prepared, work_item_id, version, _load_object(input_value))
    if set(payload) != {"preparation_ref"} or not isinstance(
        payload.get("preparation_ref"), dict
    ):
        raise click.BadParameter("inspect 输入必须只包含 preparation_ref")
    if output is not None and cursor is not None:
        raise click.BadParameter("Material assembly starts at the first page; omit --cursor")
    coordinator = _coordinator(project)
    result = coordinator.inspect_implementation_alignment(work_item_id, payload["preparation_ref"], cursor=cursor, limit=limit, expected_version=version)
    if output is None:
        _emit({"ok": True, "alignment": result})
        return
    total, items, seen = result["item_count"], list(result["items"]), set()
    while result.get("next_cursor") is not None:
        next_cursor = result["next_cursor"]
        if next_cursor in seen:
            raise HostAdapterError("alignment_material_cursor_repeated", "Inspection repeated a page; no material was written")
        seen.add(next_cursor)
        result = coordinator.inspect_implementation_alignment(work_item_id, payload["preparation_ref"], cursor=next_cursor, limit=limit, expected_version=version)
        if result["preparation_ref"] != payload["preparation_ref"] or result["item_count"] != total:
            raise HostAdapterError("alignment_material_source_changed", "Preparation changed during assembly")
        items.extend(result["items"])
    if len(items) != total:
        raise HostAdapterError("alignment_material_incomplete", "Inspection did not return every selected item")
    material = {"schema_version": "strixnova.selected-alignment-material.v1", "work_item_id": work_item_id,
                "work_item_version": version, "preparation_ref": payload["preparation_ref"], "items": items,
                "reading": {"complete": True, "scope": "selected_preparation", "item_count": total},
                "semantic_content_machine_proven": False}
    _write_transport(output, material)
    _emit({"ok": True, "material": str(output.resolve()), "item_count": total})


@alignment.command("gc")
@PROJECT_OPTION
@click.option(
    "--dry-run",
    is_flag=True,
    help="只报告无清单引用的孤立组件，不删除任何内容。",
)
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    help="只删除已由精确 dry-run 集合确认的孤立组件。",
)
@click.option(
    "--expected-orphan-set-sha256",
    help="--apply 必须提交最近一次 dry-run 返回的孤立集合 SHA-256。",
)
@_command_errors
def alignment_gc(
    project_dir: Path,
    dry_run: bool,
    apply_changes: bool,
    expected_orphan_set_sha256: str | None,
) -> None:
    """维护可重建缓存；不删除准备、捕获、事务或长期权威。"""

    if dry_run == apply_changes:
        raise click.BadParameter("gc 必须且只能选择 --dry-run 或 --apply")
    expected = (
        expected_orphan_set_sha256.strip().lower()
        if isinstance(expected_orphan_set_sha256, str)
        else None
    )
    if dry_run and expected is not None:
        raise click.BadParameter("--dry-run 不接受 --expected-orphan-set-sha256")
    if apply_changes and (
        expected is None
        or len(expected) != 64
        or any(character not in "0123456789abcdef" for character in expected)
    ):
        raise click.BadParameter(
            "--apply 必须提供有效 --expected-orphan-set-sha256"
        )
    project = _project(project_dir)
    _emit(
        {
            "ok": True,
            "alignment": _coordinator(
                project
            ).garbage_collect_implementation_alignment(
                apply=apply_changes,
                expected_orphan_set_sha256=expected,
            ),
        }
    )


@alignment.command("capture-external")
@PROJECT_OPTION
@click.option("--work-item-id")
@click.option("--version", type=click.IntRange(min=1))
@click.option(
    "--input",
    "input_value",
    default="{}",
    help="只包含 prepare 返回的 preparation_ref；支持 @UTF-8 文件或 @-。",
)
@click.option(
    "--authorize-external",
    is_flag=True,
    help="明确授权本次执行已确认工程方案中的精确外部 provider。",
)
@click.option("--prepared", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), help="Save the updated preparation binding after an explicitly authorized capture.")
@_command_errors
def alignment_capture_external(
    project_dir: Path,
    work_item_id: str | None,
    version: int | None,
    input_value: str,
    prepared: Path | None,
    authorize_external: bool,
    output: Path | None,
) -> None:
    """执行已计划 provider，并返回更新后的内容寻址准备引用。"""

    project = _project(project_dir)
    work_item_id, version, payload = _alignment_input(project, prepared, work_item_id, version, _load_object(input_value))
    if set(payload) != {"preparation_ref"} or not isinstance(
        payload.get("preparation_ref"), dict
    ):
        raise click.BadParameter("capture-external 输入必须只包含 preparation_ref")
    result = _coordinator(project).capture_external_implementation_alignment(work_item_id, payload["preparation_ref"],
        authorize_external=authorize_external, expected_version=version)
    if output is not None:
        _write_transport(output, _alignment_transport(project, work_item_id, version, result))
        _emit({"ok": True, "prepared": str(output.resolve())})
    else:
        _emit({"ok": True, "alignment": result})


@alignment.command("write-candidate")
@PROJECT_OPTION
@click.option("--work-item-id")
@click.option("--version", type=click.IntRange(min=1))
@click.option(
    "--input",
    "input_value",
    required=True,
    help="绑定 preparation_ref 的语义决定 JSON、@UTF-8 文件或 @-。",
)
@click.option("--prepared", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@_command_errors
def alignment_write_candidate(
    project_dir: Path,
    work_item_id: str | None,
    version: int | None,
    input_value: str,
    prepared: Path | None,
) -> None:
    """恢复性写入 draft；不确认、不采用、不推进 WorkItem。"""

    project = _project(project_dir)
    work_item_id, version, payload = _alignment_input(project, prepared, work_item_id, version, _load_object(input_value))
    _emit(
        {
            "ok": True,
            "alignment": _coordinator(
                project
            ).write_implementation_alignment_candidate(
                work_item_id,
                payload,
                expected_version=version,
            ),
        }
    )


@main.command("status")
@PROJECT_OPTION
@click.option("--follow-ups", is_flag=True, help="独立查询已接受结果中尚待处理的明确延期问题。")
@click.option("--include-closed", is_flag=True, help="跟进查询同时包含已解决或已接受的限制。")
@click.option("--limit", type=click.IntRange(1, 100), default=25, help="跟进查询每页条目数。")
@click.option("--cursor", help="跟进查询返回的精确续页引用。")
@click.option(
    "--at-commit",
    help="可选的不可变本地提交；缺省读取项目配置采用的本地集成版本。",
)
@click.option(
    "--working-tree",
    is_flag=True,
    help=(
        "显式校验当前工作树中的未提交长期权威候选；"
        "只证明结构和引用，不表示候选已经采用。"
    ),
)
@_command_errors
def project_status(
    project_dir: Path,
    at_commit: str | None,
    working_tree: bool,
    follow_ups: bool,
    include_closed: bool,
    limit: int,
    cursor: str | None,
) -> None:
    """分开读取目标、实现、验证、安装、交付、部署和运行状态。"""

    project = _project(project_dir)
    if follow_ups:
        if at_commit or working_tree:
            raise click.UsageError("--follow-ups 读取本地接受记录，不能与权威提交视图选项组合")
        _emit({"ok": True, "follow_ups": _adapter(project).follow_ups(limit=limit, cursor=cursor, include_closed=include_closed)})
        return
    if include_closed or cursor is not None or limit != 25:
        raise click.UsageError("跟进分页选项需要 --follow-ups")
    _emit(
        {
            "ok": True,
            "status": _adapter(project).project_status(
                at_commit=at_commit,
                working_tree=working_tree,
            ),
        }
    )


@main.command("authority")
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option(
    "--authority-kind",
    type=click.Choice(
        [
            "product_definition",
            "domain_model",
            "target_architecture",
            "engineering_policy",
        ],
        case_sensitive=True,
    ),
    required=False,
)
@click.option(
    "--input",
    "input_value",
    help="可选的负责人确认 JSON、@文件或 @-；缺省校验并记录精确候选展示。",
)
@click.option("--version", type=click.IntRange(min=1), required=True)
@click.option("--user-message-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Existing raw UTF-8 user-message source; never a model-authored transcript.")
@_command_errors
def project_authority(
    project_dir: Path,
    work_item_id: str,
    authority_kind: str | None,
    input_value: str | None,
    version: int,
    user_message_file: Path | None,
) -> None:
    """逐类展示候选，或一次提交完整负责人决定包。"""

    project = _project(project_dir)
    adapter = _adapter(project)
    if user_message_file is not None and input_value is None:
        raise click.BadParameter("--user-message-file requires explicit decision input")
    if input_value is None:
        if authority_kind is None:
            action = adapter.next_step(work_item_id).get('current_action') or {}
            if action.get('action_type') == 'author_project_authority_candidate':
                authority_kind = action.get('authority_kind')
                if not isinstance(authority_kind, str) or not authority_kind:
                    raise HostAdapterError('project_authority_kind_missing', '当前起草动作缺少明确权威种类')
        if authority_kind is None:
            _emit(
                {
                    "ok": True,
                    **adapter.project_authority_review_candidate(
                        work_item_id,
                        expected_version=version,
                    ),
                }
            )
            return
        _emit(
            {
                "ok": True,
                **adapter.project_authority_candidate(
                    work_item_id,
                    authority_kind,
                    expected_version=version,
                ),
            }
        )
        return
    payload = _load_object(input_value)
    if user_message_file is not None:
        payload = attach_confirmation_message(payload, _user_message(user_message_file))
    if authority_kind is not None:
        raise click.BadParameter(
            "提交候选复核或负责人决定包时不得提供 --authority-kind"
        )
    if payload.get("schema_version") == (
        "strixnova.project-authority-review-submission.v1"
    ):
        reviewed = adapter.review_project_authorities(
            work_item_id,
            payload,
            expected_version=version,
        )
        _emit_next(
            project,
            work_item_id,
            project_authority_review=reviewed["project_authority_review"],
        )
        return
    decisions_input = payload.get("decisions")
    if not isinstance(decisions_input, list) or not decisions_input:
        raise click.BadParameter(
            "确认时必须一次提交完整 decisions（决定）数组"
        )
    submitted_count = len(decisions_input)
    updated = adapter.confirm_project_authorities(
        work_item_id,
        payload,
        expected_version=version,
    )
    decisions = updated["data"].get("project_authority_decisions") or []
    _emit_next(
        project,
        work_item_id,
        project_authority_decisions=(
            decisions[-submitted_count:]
            if decisions and submitted_count > 0
            else []
        ),
    )


@main.command()
@PROJECT_OPTION
@click.option(
    "--input",
    "input_value",
    required=True,
    help="包含 title 和 request 的 JSON、@文件或 @-。",
)
@_command_errors
def intake(project_dir: Path, input_value: str) -> None:
    """创建一个 WorkItem；不会扫描源码或创建 Git 分支。"""

    project = _project(project_dir)
    request = _load_object(input_value)
    if set(request) != {"title", "request"}:
        raise click.BadParameter("intake 输入必须且只能包含 title 和 request")
    created = _coordinator(project).intake(
        title=_contract_text(request.get("title"), "title"),
        raw_request=_contract_text(request.get("request"), "request"),
    )
    _emit_next(project, created["work_item_id"])


@main.group("upgrade")
def upgrade() -> None:
    """显式预检、升级、查看或恢复 Strixnova 自身的本地运行数据。"""


@upgrade.command("runtime")
@_command_errors
def upgrade_runtime() -> None:
    """报告实际调用的程序、Skill 内容身份和支持格式。"""
    _emit({"ok": True, "runtime": runtime_identity()})


@upgrade.command("stop-evidence-contract")
@_command_errors
def upgrade_stop_evidence_contract() -> None:
    """读取外部执行停止证据的精确输入合同。"""
    _emit({"ok": True, "contract": stop_evidence_contract()})


@upgrade.command("operations")
@PROJECT_OPTION
@_command_errors
def upgrade_operations(project_dir: Path) -> None:
    """只读列出运行中或缺少结束记录的操作及证据绑定范围。"""
    _emit({"ok": True, **RuntimeUpgrade(_project(project_dir)).operations()})


@upgrade.command("recover-operation")
@PROJECT_OPTION
@click.option("--operation-id", required=True)
@click.option("--input", "input_value", required=True, help="绑定该操作的外部停止证据 JSON、@文件或 @-。")
@_command_errors
def upgrade_recover_operation(project_dir: Path, operation_id: str, input_value: str) -> None:
    """核对外部停止证据并收口旧执行，不重放命令或改写业务事实。"""
    _emit({"ok": True, "operation": RuntimeUpgrade(_project(project_dir)).resolve_operation(operation_id, _load_object(input_value))})


@upgrade.command("check")
@PROJECT_OPTION
@click.option("--target-wheel", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--installation-root", type=click.Path(file_okay=False, path_type=Path))
@click.option("--source-python", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--builder-python", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--wheelhouse", type=click.Path(exists=True, file_okay=False, path_type=Path))
@_command_errors
def upgrade_check(project_dir: Path, target_wheel: Path | None, installation_root: Path | None, source_python: Path | None, builder_python: Path | None, wheelhouse: Path | None) -> None:
    """只读预检并返回可直接提交的精确升级计划。"""
    operation = RuntimeUpgrade(_project(project_dir))
    installation = None
    if target_wheel is not None or installation_root is not None:
        if target_wheel is None or installation_root is None:
            raise click.BadParameter("完整安装升级必须同时指定 --target-wheel 和 --installation-root")
        installation = {"target_wheel": str(target_wheel), "installation_root": str(installation_root), "source_python": str(source_python) if source_python else None, "builder_python": str(builder_python) if builder_python else None, "wheelhouse": str(wheelhouse) if wheelhouse else None}
    elif source_python or builder_python or wheelhouse:
        raise click.BadParameter("安装选项需要明确目标 wheel 和安装根")
    _emit({"ok": True, "upgrade": operation.plan_view(operation.check(installation=installation))})


@upgrade.command("run", context_settings={"ignore_unknown_options": True})
@PROJECT_OPTION
@click.option("--installation-root", required=True, type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.argument("arguments", nargs=-1, type=click.UNPROCESSED)
@_command_errors
def upgrade_run(project_dir: Path, installation_root: Path, arguments: tuple[str, ...]) -> None:
    """通过稳定安装入口运行当前已选择的程序；参数放在 -- 之后。"""
    result = ManagedInstallation(installation_root, _project(project_dir)).run(list(arguments))
    if result.stdout:
        click.echo(result.stdout_text(), nl=False)
    if result.stderr:
        click.echo(result.stderr_text(), nl=False, err=True)
    raise click.exceptions.Exit(result.exit_code)


@upgrade.command("apply")
@PROJECT_OPTION
@click.option("--input", "input_value", required=True, help="check 返回的升级计划，支持 JSON、@文件或 @-。")
@_command_errors
def upgrade_apply(project_dir: Path, input_value: str) -> None:
    """按明确计划进入维护窗口，备份、转换、核验并切换。"""
    operation = RuntimeUpgrade(_project(project_dir))
    _emit({"ok": True, "upgrade": operation.status_view(operation.apply(_load_object(input_value)))})


@upgrade.command("status")
@PROJECT_OPTION
@click.option("--upgrade-id")
@_command_errors
def upgrade_status(project_dir: Path, upgrade_id: str | None) -> None:
    """查看进行中的升级或指定升级回执。"""
    operation = RuntimeUpgrade(_project(project_dir))
    _emit({"ok": True, "upgrade": operation.status_view(operation.status(upgrade_id))})


@upgrade.command("validate")
@PROJECT_OPTION
@click.option("--upgrade-id", required=True)
@_command_errors
def upgrade_validate(project_dir: Path, upgrade_id: str) -> None:
    """维护窗口内只读核验目标程序和已切换的项目历史。"""
    _emit({"ok": True, "validation": RuntimeUpgrade(_project(project_dir)).validate_target(upgrade_id)})


@upgrade.command("recover")
@PROJECT_OPTION
@click.option("--upgrade-id", required=True)
@click.option("--mode", type=click.Choice(["resume", "restore"]), default="resume", show_default=True)
@_command_errors
def upgrade_recover(project_dir: Path, upgrade_id: str, mode: str) -> None:
    """继续已核验切换或恢复原数据；不得覆盖新版产生的新事实。"""
    operation = RuntimeUpgrade(_project(project_dir))
    _emit({"ok": True, "upgrade": operation.status_view(operation.recover(upgrade_id, mode=mode))})


@main.command("history")
@PROJECT_OPTION
@click.option("--work-item-id")
@click.option("--record", "records", multiple=True)
@click.option("--query", default="", help="按事项标题中的文字筛选。")
@click.option("--state", "statuses", multiple=True)
@click.option("--since", help="更新时间下界（含），ISO 时间；无时区按 UTC。")
@click.option("--until", help="更新时间上界（不含），ISO 时间；无时区按 UTC。")
@click.option("--limit", type=int, default=25, show_default=True)
@click.option("--cursor", help="上一页返回的不透明续页引用。")
@click.option("--offset", type=int, default=0)
@click.option("--bytes", "byte_count", type=int, default=65536)
@_command_errors
def history(
    project_dir: Path, work_item_id: str | None, records: tuple[str, ...],
    query: str, statuses: tuple[str, ...], since: str | None, until: str | None,
    limit: int, cursor: str | None, offset: int, byte_count: int,
) -> None:
    """只读查询事项历史，不受当前动作限制。"""

    _emit({"ok": True, "history": _adapter(_project(project_dir)).history(
        work_item_id=work_item_id, records=records, query=query, statuses=statuses,
        since=since, until=until, limit=limit, cursor=cursor,
        offset=offset, byte_count=byte_count,
    )})


@main.command("next")
@PROJECT_OPTION
@click.option("--work-item-id")
@click.option("--max-output-bytes", type=int, default=DEFAULT_OUTPUT_BYTES, show_default=True,
              help="聚焦读取的完整 JSON 响应预算，包含外壳与换行。")
@click.option("--cursor", help="原样复制 record_pages 的 next_cursor；每次续读一个记录。")
@click.option("--expected-version", type=int, help="读取目录时的事项版本。")
@click.option("--expected-sha256", help="读取目录返回的 source_sha256。")
@click.option(
    "--record",
    "record_refs",
    multiple=True,
    help=(
        "读取 CurrentAction 的 input_contract_ref、record_refs 或适用的 "
        "conditional_record_refs；"
        "聚焦事项还可按需读取 "
        "engineering.trace.current 或 engineering.trace.audit。可重复；"
        "同一判断步骤已明确需要且彼此不依赖当前响应的多个引用，"
        "应在一次调用中批量读取。"
    ),
)
@_command_errors
def next_step(
    project_dir: Path,
    work_item_id: str | None,
    record_refs: tuple[str, ...],
    max_output_bytes: int,
    cursor: str | None,
    expected_version: int | None,
    expected_sha256: str | None,
) -> None:
    """读取最小下一步；不指定事项时只列出未完成事项。"""

    project = _project(project_dir)
    if work_item_id:
        _emit(
            {
                "ok": True,
                "next": _adapter(project).next_step(
                    work_item_id,
                    record_refs=record_refs,
                    max_output_bytes=max_output_bytes,
                    cursor=cursor, expected_version=expected_version,
                    expected_sha256=expected_sha256,
                ),
            }
        )
        return
    if record_refs or cursor is not None or expected_version is not None or expected_sha256 is not None:
        raise click.BadParameter("读取记录时必须给出 --work-item-id")
    adapter = _adapter(project)
    with adapter.coordinator.read_operation():
        items = adapter.read_model.work_items()["work_items"]
    _emit(
        {
            "ok": True,
            "work_items": [
                item for item in items if not item["is_terminal"]
            ],
        }
    )


@main.group("action")
def action_commands() -> None:
    """Prepare bound inputs, inspect selected material and submit explicit judgments."""


def _write_transport(path: Path, value: Any) -> None:
    # Caller chooses the output; never overwrite an existing candidate or source.
    if path.is_symlink() or path.is_junction() or any(p.is_symlink() or p.is_junction() for p in path.parents):
        raise click.BadParameter("Transport output must use ordinary paths")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


@action_commands.command("prepare")
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@click.option("--receipt-id", help="Select one pending receipt; its command and version are carried automatically.")
@_command_errors
def action_prepare(project_dir: Path, work_item_id: str, output: Path, receipt_id: str | None) -> None:
    context = _adapter(_project(project_dir)).prepare_input(work_item_id, receipt_id=receipt_id)
    _write_transport(output, context)
    _emit({"ok": True, "context": str(output.resolve()), "action": context["binding"]["action"]["action_type"],
           "checklist_items": len(context["checklist"]), "version": context["binding"]["work_item_version"],
           "semantic_content_machine_proven": False})


@action_commands.command("preview")
@PROJECT_OPTION
@click.option("--context", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--input", "input_value", required=True)
@click.option("--user-message-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--output", type=click.Path(path_type=Path), required=True)
@_command_errors
def action_preview(project_dir: Path, context: Path, input_value: str, user_message_file: Path | None, output: Path) -> None:
    report = _adapter(_project(project_dir)).preview_input(_load_object("@" + str(context)), _load_object(input_value),
        user_message=_user_message(user_message_file) if user_message_file else None)
    _write_transport(output, report)
    _emit({"ok": report["ok"], "report": str(output.resolve()), "issue_count": len(report["issues"]),
           "semantic_content_machine_proven": False})
    if not report["ok"]:
        raise click.exceptions.Exit(1)


@action_commands.command("apply")
@PROJECT_OPTION
@click.option("--context", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--input", "input_value", required=True)
@click.option("--user-message-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@_command_errors
def action_apply(project_dir: Path, context: Path, input_value: str, user_message_file: Path | None) -> None:
    _emit(_adapter(_project(project_dir)).apply_input(_load_object("@" + str(context)), _load_object(input_value),
        user_message=_user_message(user_message_file) if user_message_file else None))


@action_commands.command("authorities")
@PROJECT_OPTION
@click.option("--context", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--kind", "authority_kinds", multiple=True, required=True)
@_command_errors
def action_authorities(project_dir: Path, context: Path, authority_kinds: tuple[str, ...]) -> None:
    report = _adapter(_project(project_dir)).present_authorities(_load_object("@" + str(context)), list(authority_kinds))
    _emit(report)
    if not report["ok"]:
        raise click.exceptions.Exit(1)


@action_commands.command("cases")
@PROJECT_OPTION
@click.option("--context", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--command-id", required=True)
@click.option("--report", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@_command_errors
def action_cases(project_dir: Path, context: Path, command_id: str, report: Path, output: Path) -> None:
    result = _adapter(_project(project_dir)).preflight_cases(_load_object("@" + str(context)), command_id, _load_object("@" + str(report)))
    _write_transport(output, result)
    _emit({"ok": result["ok"], "report": str(output.resolve()), "issue_count": len(result["issues"]), "execution_performed": False})
    if not result["ok"]:
        raise click.exceptions.Exit(1)


@action_commands.command("records")
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option("--record", "record_refs", multiple=True, required=True)
@click.option("--output", type=click.Path(path_type=Path), required=True)
@_command_errors
def action_records(project_dir: Path, work_item_id: str, record_refs: tuple[str, ...], output: Path) -> None:
    material = _adapter(_project(project_dir)).read_materials(work_item_id, record_refs=record_refs)
    _write_transport(output, material)
    _emit({"ok": True, "material": str(output.resolve()), "version": material["work_item_version"],
           "records": list(material["records"]), "reading": material["reading"]})


@action_commands.command("inspect")
@click.option("--source", type=click.Path(exists=True, dir_okay=False, path_type=Path), required=True)
@click.option("--pointer", default="", help="Select an exact JSON pointer within the saved material.")
@click.option("--max-output-bytes", type=click.IntRange(512, 1048576), default=16384)
@click.option("--readable", is_flag=True, help="UTF-8 presentation; canonical transport hashes are unchanged.")
@_command_errors
def action_inspect(source: Path, pointer: str, max_output_bytes: int, readable: bool) -> None:
    from strixnova.prepared_input import inspect_material
    result = inspect_material(_load_object("@" + str(source)), pointer, max_output_bytes)
    if readable:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        _emit(result)


@main.command("submit")
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option(
    "--input",
    "input_value",
    required=True,
    help="内联 JSON、@文件或 @- 标准输入。",
)
@click.option("--version", type=click.IntRange(min=1), required=True)
@_command_errors
def submit(
    project_dir: Path,
    work_item_id: str,
    input_value: str,
    version: int,
) -> None:
    """提交 CurrentAction 要求的候选内容或明确判断。"""

    project = _project(project_dir)
    payload = _load_object(input_value)
    _adapter(project).submit_current_action_input(
        work_item_id,
        payload,
        expected_version=version,
    )
    _emit_next(project, work_item_id)


@main.command()
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option(
    "--input",
    "input_value",
    required=True,
    help="包含程序内部候选绑定和用户确认原文的 JSON、@文件或 @-；不得要求用户复制候选指纹。",
)
@click.option("--version", type=click.IntRange(min=1), required=True)
@click.option("--user-message-file", type=click.Path(exists=True, dir_okay=False, path_type=Path), help="Existing raw UTF-8 user-message source; never a model-authored transcript.")
@_command_errors
def confirm(
    project_dir: Path,
    work_item_id: str,
    input_value: str,
    version: int,
    user_message_file: Path | None,
) -> None:
    """记录三个用户确认点之一。"""

    project = _project(project_dir)
    action = _adapter(project).current_action(work_item_id) or {}
    confirmation_kinds = {
        "confirm_direction": "direction",
        "confirm_engineering_plan": "engineering_plan",
        "confirm_actual_result": "actual_result",
    }
    kind = confirmation_kinds.get(action.get("action_type"))
    if kind is None:
        raise HostAdapterError(
            "confirmation_not_expected",
            "当前下一步不是用户确认",
        )
    payload = _load_object(input_value)
    if user_message_file is not None:
        payload = attach_confirmation_message(payload, _user_message(user_message_file))
    if set(payload) != {"candidate_fingerprint", "user_confirmation", "agent_decision"}:
        raise click.BadParameter(
            "confirm 输入必须包含 candidate_fingerprint、user_confirmation 和 agent_decision"
        )
    _adapter(project).confirm(
        work_item_id,
        kind,
        candidate_fingerprint=_contract_text(
            payload.get("candidate_fingerprint"),
            "candidate_fingerprint",
        ),
        user_confirmation=payload.get("user_confirmation"),
        agent_decision=payload.get("agent_decision"),
        expected_version=version,
    )
    _emit_next(project, work_item_id)


@main.command("delivery")
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option(
    "--input",
    "input_value",
    default="{}",
    show_default=True,
    help="当前交付动作所需 JSON、@文件或 @-。",
)
@click.option("--version", type=click.IntRange(min=1), required=True)
@_command_errors
def delivery(
    project_dir: Path,
    work_item_id: str,
    input_value: str,
    version: int,
) -> None:
    """推进工作区、实际结果、提交、本地集成或安全清理。"""

    project = _project(project_dir)
    result = _coordinator(project).delivery(
        work_item_id,
        _load_object(input_value),
        expected_version=version,
    )
    facts = {
        key: result[key]
        for key in ("steps", "coverage")
        if key in result
    }
    _emit_next(project, work_item_id, **facts)


@main.command()
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option(
    "--input",
    "input_value",
    required=True,
    help=(
        "验证 JSON；mode 为 run、not_run 或事后 assess。"
    ),
)
@click.option("--version", type=click.IntRange(min=1), required=True)
@_command_errors
def verify(
    project_dir: Path,
    work_item_id: str,
    input_value: str,
    version: int,
) -> None:
    """运行工程方案中已选择的一项本地验证。"""

    project = _project(project_dir)
    result = _coordinator(project).verify(
        work_item_id,
        _load_object(input_value),
        expected_version=version,
    )
    _emit_next(
        project,
        work_item_id,
        verification=result["verification"],
        coverage=result["coverage"],
    )


@main.command("activity")
@PROJECT_OPTION
@click.option(
    "--input",
    "input_value",
    required=True,
    help="交付、发布、部署、观测或运维活动请求 JSON、@文件或 @-。",
)
@_command_errors
def activity(project_dir: Path, input_value: str) -> None:
    """治理外部活动计划和回执；本命令不执行外部活动。"""

    project = _project(project_dir)
    request = _load_object(input_value)
    action = _contract_text(request.get("action"), "action")
    allowed_fields = {
        "plan": {"action", "work_item_id", "work_item_version", "plan"},
        "authorize": {
            "action",
            "activity_id",
            "activity_version",
            "work_item_version",
        },
        "record": {"action", "activity_id", "activity_version", "receipt"},
        "cancel": {
            "action",
            "activity_id",
            "activity_version",
            "canceled_by",
            "reason",
        },
        "get": {"action", "activity_id"},
        "list": {"action", "work_item_id"},
    }
    if action not in allowed_fields:
        raise click.BadParameter("action 必须是 plan、authorize、record、cancel、get 或 list")
    extra = sorted(set(request) - allowed_fields[action])
    if extra:
        raise click.BadParameter("活动请求包含未知字段：" + ", ".join(extra))

    adapter = _adapter(project)
    if action == "list":
        value = request.get("work_item_id")
        _emit(
            {
                "ok": True,
                **adapter.delivery_activities(
                    work_item_id=(
                        None
                        if value is None
                        else _contract_text(value, "work_item_id")
                    )
                ),
            }
        )
        return
    activity_id = (
        None
        if action == "plan"
        else _contract_text(request.get("activity_id"), "activity_id")
    )
    if action == "get":
        assert activity_id is not None
        _emit({"ok": True, **adapter.delivery_activity(activity_id)})
        return

    def positive_integer(field: str) -> int:
        value = request.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise click.BadParameter(f"{field} 必须是正整数")
        return value

    if action == "plan":
        plan = request.get("plan")
        if not isinstance(plan, dict):
            raise click.BadParameter("plan 必须是对象")
        result = adapter.plan_delivery_activity(
            _contract_text(request.get("work_item_id"), "work_item_id"),
            plan,
            expected_version=positive_integer("work_item_version"),
        )
    elif action == "authorize":
        assert activity_id is not None
        result = adapter.authorize_delivery_activity(
            activity_id,
            expected_activity_version=positive_integer("activity_version"),
            expected_work_item_version=positive_integer("work_item_version"),
        )
    elif action == "record":
        assert activity_id is not None
        receipt = request.get("receipt")
        if not isinstance(receipt, dict):
            raise click.BadParameter("receipt 必须是对象")
        result = adapter.record_delivery_activity_receipt(
            activity_id,
            receipt,
            expected_activity_version=positive_integer("activity_version"),
        )
    else:
        assert activity_id is not None
        result = adapter.cancel_planned_delivery_activity(
            activity_id,
            expected_activity_version=positive_integer("activity_version"),
            canceled_by=_contract_text(request.get("canceled_by"), "canceled_by"),
            reason=_contract_text(request.get("reason"), "reason"),
        )
    _emit(
        {
            "ok": True,
            "activity": result,
            "capability_notice": (
                "Strixnova 只治理计划和真实外部回执，不执行发布、部署或运维活动。"
            ),
        }
    )


@main.command()
@PROJECT_OPTION
@click.option("--work-item-id", required=True)
@click.option(
    "--input",
    "input_value",
    required=True,
    help="取消原因或待处理工作决策的 JSON、@文件或 @-。",
)
@click.option("--version", type=click.IntRange(min=1), required=True)
@_command_errors
def cancel(
    project_dir: Path,
    work_item_id: str,
    input_value: str,
    version: int,
) -> None:
    """取消事项，或处理取消后留下的本地工作。"""

    project = _project(project_dir)
    _coordinator(project).cancel(
        work_item_id,
        _load_object(input_value),
        expected_version=version,
    )
    _emit_next(project, work_item_id)


if __name__ == "__main__":
    main()
