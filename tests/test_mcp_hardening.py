"""MCP client hardening (item 4) and MCP intent records (item 6g)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from opentorus.config import McpServerConfig, default_config
from opentorus.execution.intents import IntentLog
from opentorus.tools.base import ToolCall
from opentorus.tools.mcp import (
    McpConfigError,
    McpServerHandle,
    close_all_mcp_servers,
    discover_mcp_tools,
)

_FAKE = str(Path(__file__).parent / "mcp_fake_server.py")
_SECRET = "sk-test-mcp-SECRET-0123456789abcdef"


def _config(tmp_path: Path, **server: object):
    config = default_config()
    fields: dict = {
        "name": "fake",
        "command": sys.executable,
        "args": [_FAKE],
        "enabled": True,
        "env": {"FAKE_MCP_PIDFILE": str(tmp_path / "pids.txt")},
    }
    fields.update(server)
    config.tools.mcp = [McpServerConfig(**fields)]
    return config


def _tools(tmp_path: Path, **server: object) -> dict:
    tools = discover_mcp_tools(_config(tmp_path, **server), tmp_path)
    return {t.remote_name: t for t in tools}


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    close_all_mcp_servers()


def _call(tool, **args):  # noqa: ANN001, ANN202
    return tool.run(ToolCall(name=tool.name, args=args))


def test_server_env_has_no_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _SECRET)
    monkeypatch.setenv("ANTHROPIC_API_KEY", _SECRET)
    monkeypatch.setenv("UNRELATED_VARIABLE", "parent-only")
    tools = _tools(tmp_path, env={"SERVER_SETTING": "explicit"})
    env = json.loads(_call(tools["env"]).content)
    assert "OPENAI_API_KEY" not in env and "ANTHROPIC_API_KEY" not in env
    assert _SECRET not in json.dumps(env)
    assert "UNRELATED_VARIABLE" not in env  # clean allowlist, not the parent env
    assert env["SERVER_SETTING"] == "explicit"  # explicit per-server env only
    assert "PATH" in env


def test_one_persistent_process_per_session(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    first = _call(tools["pid"]).content
    second = _call(tools["pid"]).content
    third = _call(tools["lookup"])
    assert first == second
    assert third.ok
    starts = (tmp_path / "pids.txt").read_text().split()
    assert starts == [first]  # discovery + three calls = one process


def test_server_is_killed_on_close(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    pid = int(_call(tools["pid"]).content)
    close_all_mcp_servers()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("MCP server survived close_all_mcp_servers()")


def test_timeout_is_outcome_unknown_and_recorded(tmp_path: Path) -> None:
    tools = _tools(tmp_path, timeout=0.5)
    started = time.monotonic()
    result = _call(tools["sleep"], seconds=30)
    assert time.monotonic() - started < 10  # a real timeout, not a hung readline
    assert not result.ok
    assert result.metadata["outcome"] == "unknown"
    assert "outcome unknown" in result.content.lower()
    assert "do not repeat" in result.content.lower()
    log = IntentLog(tmp_path / "intents.jsonl")
    op_id = result.metadata["op_id"]
    assert log.state(op_id) == "unknown"
    assert [r["op_id"] for r in log.unresolved()] == [op_id]
    # The session recovers: the next call gets a fresh server.
    assert _call(tools["pid"]).ok


def test_intent_is_durable_before_dispatch(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    result = _call(tools["lookup"], q="x")
    records = IntentLog(tmp_path / "intents.jsonl").records()
    assert [r["record"] for r in records] == ["intent", "outcome"]
    assert records[0]["op_id"] == records[1]["op_id"] == result.metadata["op_id"]
    assert records[0]["target"] == "fake/lookup"
    assert records[1]["outcome"] == "succeeded"


def test_oversized_message_is_refused(tmp_path: Path) -> None:
    tools = _tools(tmp_path, timeout=10)
    result = _call(tools["huge"])
    assert not result.ok
    assert "1 MiB" in result.content
    # The desynchronised stream is replaced, not reused.
    assert _call(tools["pid"]).ok


def test_tool_allowlist_exposes_only_named_tools(tmp_path: Path) -> None:
    tools = _tools(tmp_path, tools=["lookup", "pid"])
    assert sorted(tools) == ["lookup", "pid"]


def test_missing_allowlisted_tool_fails_startup(tmp_path: Path) -> None:
    with pytest.raises(McpConfigError, match="delete_everything"):
        _tools(tmp_path, tools=["lookup", "delete_everything"])


def test_read_only_hint_is_observation_otherwise_irreversible(tmp_path: Path) -> None:
    tools = _tools(tmp_path)
    assert tools["lookup"].effect == "observation"
    assert tools["pid"].effect == "irreversible"


def test_cancel_kills_the_server(tmp_path: Path) -> None:
    config = _config(tmp_path, timeout=30)
    handle = McpServerHandle(config.tools.mcp[0])
    client = handle.client()
    pid = int(client.call_tool("pid", {}))
    import threading

    transport = client._transport  # noqa: SLF001

    def _interrupt() -> None:
        time.sleep(0.3)
        transport._inbox.put(KeyboardInterrupt())  # noqa: SLF001 — simulate a cancel

    threading.Thread(target=_interrupt, daemon=True).start()
    with pytest.raises(KeyboardInterrupt):
        client.call_tool("sleep", {"seconds": 30})
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        time.sleep(0.05)
    pytest.fail("server survived the cancel")
