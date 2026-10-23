"""Every tool result fed to the model is bounded; the persisted session keeps it whole."""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.agent.context import build_messages
from opentorus.agent.session import SessionMessage, append_message, read_messages
from opentorus.agent.tool_result_bound import bound_tool_result
from opentorus.config import default_config
from opentorus.workspace import init_workspace, workspace_dir


def test_short_result_is_unchanged() -> None:
    assert bound_tool_result("exit_code=0\nstdout:\nhi", 100) == "exit_code=0\nstdout:\nhi"


def test_shell_result_cuts_longest_section_and_keeps_exit_code() -> None:
    text = "exit_code=124\ntimed_out=true\nstdout:\n" + "x" * 5000 + "\nstderr:\nboom at end"
    out = bound_tool_result(text, 1000)
    assert len(out) <= 1000
    assert out.startswith("exit_code=124\ntimed_out=true\nstdout:\n")
    assert out.endswith("stderr:\nboom at end")  # the short section is untouched
    assert "[cut: " in out and " chars omitted]" in out


def test_json_result_cuts_longest_string_field() -> None:
    payload = {"exit_code": 1, "timed_out": False, "stdout": "y" * 10_000, "note": "keep"}
    out = bound_tool_result(json.dumps(payload), 2000)
    assert len(out) <= 2000
    data = json.loads(out)
    assert data["exit_code"] == 1 and data["timed_out"] is False and data["note"] == "keep"
    assert "[cut: " in data["stdout"]


def test_plain_text_keeps_head_and_tail_with_marker() -> None:
    text = "HEAD" + "z" * 10_000 + "TAIL"
    out = bound_tool_result(text, 1000)
    assert len(out) <= 1000
    assert out.startswith("HEAD") and out.endswith("TAIL")
    omitted = int(out.split("[cut: ")[1].split(" ")[0])
    head, _, rest = out.partition("\n[cut: ")
    tail = rest.split(" chars omitted]\n", 1)[1]
    assert omitted == len(text) - len(head) - len(tail)


def test_zero_limit_disables() -> None:
    text = "a" * 100_000
    assert bound_tool_result(text, 0) == text


def test_request_is_bounded_but_session_keeps_full_output(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.agent.max_tool_result_chars = 2000
    config.context.compaction_enabled = False
    config.context.retrieval_enabled = False
    big = "exit_code=0\nstdout:\n" + "q" * 50_000
    append_message(ot, SessionMessage(role="user", content="go"))
    append_message(
        ot,
        SessionMessage(
            role="assistant",
            content="",
            metadata={"tool_calls": [{"id": "c1", "name": "run_shell", "args": {}}]},
        ),
    )
    append_message(
        ot, SessionMessage(role="tool", content=big, metadata={"tool_call_id": "c1", "ok": True})
    )
    messages = build_messages(tmp_path, ot, config, ["run_shell"])
    tool_msgs = [m for m in messages if m.role == "tool"]
    assert tool_msgs and len(tool_msgs[0].content) <= 2000
    assert tool_msgs[0].content.startswith("exit_code=0\n")
    # On disk the full output is still there.
    stored = [m for m in read_messages(ot) if m.role == "tool"]
    assert stored[0].content == big
