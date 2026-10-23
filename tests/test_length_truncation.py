"""Length-truncated replies: text kept, tool calls dropped unexecuted, bounded continuation."""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.agent.prompts import LENGTH_CONTINUATION
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.providers.base import ProviderResponse, ToolCallRequest
from opentorus.providers.ollama_provider import OllamaProvider
from opentorus.tools.base import Tool, ToolCall, ToolResult
from opentorus.tools.registry import ToolRegistry
from opentorus.workspace import init_workspace, workspace_dir
from support.providers import ScriptedProvider, message


class _CountingTool(Tool):
    name = "touch_thing"
    description = "records each call"
    input_schema: dict = {"type": "object", "properties": {"x": {"type": "string"}}}
    permission = "read"

    def __init__(self) -> None:
        self.runs: list[dict] = []

    def run(self, call: ToolCall) -> ToolResult:
        self.runs.append(call.args)
        return self.ok(call, "done")


def _truncated_with_calls(text: str = "partial") -> ProviderResponse:
    calls = [
        ToolCallRequest(tool_name="touch_thing", tool_args={"x": "a"}, tool_call_id="c1"),
        ToolCallRequest(tool_name="touch_thing", tool_args={"x": "b"}, tool_call_id="c2"),
    ]
    return ProviderResponse(
        kind="tool_call",
        content=text,
        tool_name="touch_thing",
        tool_args={"x": "a"},
        tool_call_id="c1",
        tool_calls=calls,
        truncated=True,
    )


def _setup(tmp_path: Path):
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"
    tool = _CountingTool()
    registry = ToolRegistry()
    registry.register(tool)
    return ot, config, tool, registry


def test_truncated_tool_calls_are_never_executed_and_continuation_is_asked(
    tmp_path: Path,
) -> None:
    ot, config, tool, registry = _setup(tmp_path)
    provider = ScriptedProvider([_truncated_with_calls("first half"), message("complete answer")])
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=5)
    result = loop.run("do it")
    assert tool.runs == []  # neither cut-off call ran
    assert result == "complete answer"
    msgs = read_messages(ot)
    partial = [m for m in msgs if m.metadata.get("truncated")]
    assert len(partial) == 1
    assert partial[0].content == "first half"
    assert partial[0].metadata["dropped_tool_calls"] == ["touch_thing", "touch_thing"]
    assert "tool_calls" not in partial[0].metadata  # no result will ever pair with them
    assert not [m for m in msgs if m.role == "tool"]
    cont = [m for m in msgs if m.metadata.get("synthetic") == "length_continuation"]
    assert len(cont) == 1 and cont[0].content == LENGTH_CONTINUATION
    # The second request carried the continuation as its last turn.
    second_request = provider.calls[1][0]
    assert second_request[-1].content == LENGTH_CONTINUATION
    assert loop.model_tool_calls == 0


def test_truncated_final_message_is_not_accepted_and_continuations_are_bounded(
    tmp_path: Path,
) -> None:
    ot, config, tool, registry = _setup(tmp_path)
    config.agent.max_length_continuations = 2
    cut = ProviderResponse(kind="message", content="The answer is", truncated=True)
    provider = ScriptedProvider([cut])
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=10)
    result = loop.run("answer")
    assert result.startswith("[stopped]")
    assert "output-token limit" in result
    assert len(provider.calls) == 3  # first try + 2 continuations, then stop
    assert not loop.hit_max_steps


def test_continuation_counter_resets_after_a_complete_reply(tmp_path: Path) -> None:
    ot, config, tool, registry = _setup(tmp_path)
    config.agent.max_length_continuations = 1
    cut = ProviderResponse(kind="message", content="part", truncated=True)
    provider = ScriptedProvider(
        [cut, ProviderResponse(kind="tool_call", tool_name="touch_thing"), cut, message("fin")]
    )
    result = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=10).run("go")
    assert result == "fin"
    assert len(tool.runs) == 1  # only the complete call ran


def test_empty_truncated_reply_keeps_role_alternation(tmp_path: Path) -> None:
    ot, config, tool, registry = _setup(tmp_path)
    cut = ProviderResponse(kind="message", content="", truncated=True)
    provider = ScriptedProvider([cut, message("ok")])
    AgentLoop(tmp_path, ot, provider, registry, config, max_steps=4).run("go")
    partial = [m for m in read_messages(ot) if m.metadata.get("truncated")]
    assert partial and partial[0].content.strip()


def test_ollama_done_reason_length_marks_truncated(monkeypatch) -> None:
    config = default_config()
    config.model.provider = "ollama"
    config.model.name = "m"
    body = {
        "model": "m",
        "message": {"role": "assistant", "content": "cut"},
        "done": True,
        "done_reason": "length",
    }

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(body).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _Resp())
    assert OllamaProvider(config).generate([]).truncated is True
