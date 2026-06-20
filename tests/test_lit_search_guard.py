"""Literature and paper-list tools are never repeat-blocked in the agent loop."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class _ScriptedProvider(BaseProvider):
    name = "mock"
    supports_streaming = False

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)

    def generate(self, messages, tools=None):
        return self._responses.pop(0)

    def respond(self, messages, tools=None, **kwargs):
        return self.generate(messages, tools)


def test_lit_search_allows_repeat_queries(tmp_path: Path, monkeypatch) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"
    registry = build_default_registry(tmp_path, ot, config)
    provider = _ScriptedProvider(
        [
            ProviderResponse(
                kind="tool_call",
                tool_name="lit_search",
                tool_args={"query": "same topic", "limit": 5},
                tool_call_id="c1",
            ),
            ProviderResponse(
                kind="tool_call",
                tool_name="lit_search",
                tool_args={"query": "same topic", "limit": 5},
                tool_call_id="c2",
            ),
            ProviderResponse(kind="message", content="done"),
        ]
    )
    loop = AgentLoop(
        tmp_path,
        ot,
        provider,
        registry,
        config,
        max_steps=6,
        confirm=lambda _d, _desc, _scope=None: True,
    )

    monkeypatch.setattr(
        "opentorus.tools.builtin.LiteratureSearchTool.run",
        lambda self, call: self.ok(call, "hit"),
    )

    loop.run("search literature")
    assert loop.tools_used_this_run.count("lit_search") == 2
    blocked = [
        m.content
        for m in read_messages(ot)
        if m.role == "tool" and "Blocked" in m.content and "lit_search" in m.content
    ]
    assert not blocked


def test_paper_list_allows_repeat_calls(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"
    registry = build_default_registry(tmp_path, ot, config)
    provider = _ScriptedProvider(
        [
            ProviderResponse(
                kind="tool_call",
                tool_name="paper_list",
                tool_args={},
                tool_call_id="c1",
            ),
            ProviderResponse(
                kind="tool_call",
                tool_name="paper_list",
                tool_args={},
                tool_call_id="c2",
            ),
            ProviderResponse(kind="message", content="done"),
        ]
    )
    loop = AgentLoop(
        tmp_path,
        ot,
        provider,
        registry,
        config,
        max_steps=6,
        confirm=lambda _d, _desc, _scope=None: True,
    )

    loop.run("list papers")
    assert loop.tools_used_this_run.count("paper_list") == 2
    blocked = [
        m.content
        for m in read_messages(ot)
        if m.role == "tool" and "Blocked repeat paper_list" in m.content
    ]
    assert not blocked
