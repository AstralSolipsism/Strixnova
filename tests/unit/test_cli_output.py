from __future__ import annotations

import codecs
from io import BytesIO, TextIOWrapper
import json
import os
from pathlib import Path
import subprocess
import sys

from strixnova.cli import _emit


def test_emit_preserves_json_when_stdout_cannot_encode_unicode(
    monkeypatch,
) -> None:
    raw = BytesIO()
    stdout = TextIOWrapper(raw, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    payload = {
        "chinese": "中文",
        "emoji": "\U0001f600",
        "replacement_character": "\ufffd",
    }

    _emit(payload)
    stdout.flush()

    encoded = raw.getvalue()
    assert encoded.isascii()
    assert json.loads(encoded.decode("ascii")) == payload


def test_emit_uses_ascii_transport_even_when_stdout_can_encode_unicode(
    monkeypatch,
) -> None:
    raw = BytesIO()
    stdout = TextIOWrapper(raw, encoding="gbk", errors="strict")
    monkeypatch.setattr(sys, "stdout", stdout)
    payload = {"message": "这次运行没有标签"}

    _emit(payload)
    stdout.flush()

    rendered = raw.getvalue().decode("ascii")
    assert "这次运行没有标签" not in rendered
    assert json.loads(rendered) == payload


def test_stdin_reads_utf8_bytes_independent_of_windows_console_code_page(
    tmp_path: Path,
) -> None:
    payload = {"title": "无标签运行", "request": "聚焦详情说明"}
    input_bytes = codecs.BOM_UTF8 + json.dumps(
        payload,
        ensure_ascii=False,
    ).encode("utf-8")
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "gbk:strict"
    script = (
        "import json; "
        "from strixnova.cli import _load_object; "
        "print(json.dumps(_load_object('@-'), ensure_ascii=True))"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("gbk", errors="replace")
    assert json.loads(result.stdout.decode("ascii")) == payload


def test_help_uses_utf8_when_windows_redirected_output_defaults_to_gbk(
    tmp_path: Path,
) -> None:
    environment = dict(os.environ)
    environment["PYTHONIOENCODING"] = "gbk:strict"
    script = (
        "from strixnova.cli import main; "
        "main.main(args=['--help'], prog_name='strixnova', "
        "standalone_mode=False)"
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    help_text = result.stdout.decode("utf-8")
    assert "面向非专业项目负责人的本地软件工程治理" in help_text
    assert "创建一个 WorkItem" in help_text


def test_raw_user_message_preserves_line_endings_and_unicode(tmp_path):
    from strixnova.cli import _user_message
    message = "  同意，但有条件。\r\n保留空白与标点。\n\r\n "
    path = tmp_path / "raw-message.txt"
    path.write_bytes(codecs.BOM_UTF8 + message.encode("utf-8"))
    assert _user_message(path) == message
