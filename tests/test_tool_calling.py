"""Tests for provider tool-calling plumbing (message/spec conversion, parsing).

These tests never hit the network: real-provider parsers are exercised with
small stand-in objects, and the agent loop is driven by a scripted fake provider.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import SessionMessage, read_messages
from opentorus.config import default_config
from opentorus.providers._convert import (
    to_function_tools,
    to_ollama_messages,
    to_openai_messages,
)
from opentorus.providers.anthropic_provider import parse_anthropic_message, to_anthropic_messages
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.ollama_provider import parse_ollama_message
from opentorus.providers.openai_provider import parse_openai_message
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def _tool_turn_messages() -> list[SessionMessage]:
    return [
        SessionMessage(role="system", content="sys"),
        SessionMessage(role="user", content="show status"),
        SessionMessage(
            role="assistant",
            content="",
            metadata={"tool_calls": [{"id": "call_1", "name": "status", "args": {}}]},
        ),
        SessionMessage(
            role="tool",
            content="workspace_root=/x",
            metadata={"tool_call_id": "call_1", "name": "status"},
        ),
    ]


def test_registry_specs_are_json_schema() -> None:
    registry = build_default_registry(Path("/tmp"), Path("/tmp/.opentorus"))
    specs = {s["name"]: s for s in registry.specs()}
    assert "status" in specs
    assert specs["read_file"]["parameters"]["required"] == ["path"]
    assert specs["status"]["parameters"]["type"] == "object"


def test_to_openai_messages_roundtrips_tool_calls() -> None:
    out = to_openai_messages(_tool_turn_messages())
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "call_1"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {}
    tool = next(m for m in out if m["role"] == "tool")
    assert tool["tool_call_id"] == "call_1"


def test_to_ollama_messages_keeps_args_as_object() -> None:
    out = to_ollama_messages(_tool_turn_messages())
    assistant = next(m for m in out if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["function"]["arguments"] == {}
    tool = next(m for m in out if m["role"] == "tool")
    assert tool["tool_name"] == "status"


def test_to_anthropic_messages_uses_blocks() -> None:
    system, convo = to_anthropic_messages(_tool_turn_messages())
    assert system == "sys"
    assistant = next(m for m in convo if m["role"] == "assistant")
    assert assistant["content"][0]["type"] == "tool_use"
    # The tool result is sent back as a user turn with a tool_result block.
    tool_result = convo[-1]
    assert tool_result["content"][0]["tool_use_id"] == "call_1"


def test_to_anthropic_messages_coalesces_parallel_tool_results() -> None:
    # A turn with several parallel tool calls yields consecutive tool messages;
    # Anthropic requires their tool_result blocks in ONE user message, not one
    # user turn each (which the API rejects).
    messages = [
        SessionMessage(role="user", content="do both"),
        SessionMessage(
            role="assistant",
            content="",
            metadata={
                "tool_calls": [
                    {"id": "call_1", "name": "status", "args": {}},
                    {"id": "call_2", "name": "read_file", "args": {"path": "x"}},
                ]
            },
        ),
        SessionMessage(role="tool", content="r1", metadata={"tool_call_id": "call_1"}),
        SessionMessage(role="tool", content="r2", metadata={"tool_call_id": "call_2"}),
    ]
    _system, convo = to_anthropic_messages(messages)
    # Exactly one user message carries both tool_result blocks.
    tool_result_msgs = [
        m
        for m in convo
        if m["role"] == "user"
        and isinstance(m["content"], list)
        and m["content"]
        and m["content"][0].get("type") == "tool_result"
    ]
    assert len(tool_result_msgs) == 1
    ids = [b["tool_use_id"] for b in tool_result_msgs[0]["content"]]
    assert ids == ["call_1", "call_2"]


def test_to_function_tools_shape() -> None:
    spec = {"name": "x", "description": "d", "parameters": {"type": "object"}}
    wrapped = to_function_tools([spec])
    assert wrapped[0]["type"] == "function"
    assert wrapped[0]["function"]["name"] == "x"


def test_parse_openai_tool_call() -> None:
    fn = SimpleNamespace(name="git_diff", arguments='{"path": "src"}')
    call = SimpleNamespace(id="call_9", function=fn)
    message = SimpleNamespace(tool_calls=[call], content=None)
    resp = parse_openai_message(message)
    assert resp.kind == "tool_call"
    assert resp.tool_name == "git_diff"
    assert resp.tool_args == {"path": "src"}
    assert resp.tool_call_id == "call_9"


def test_parse_openai_plain_message() -> None:
    message = SimpleNamespace(tool_calls=None, content="hello")
    resp = parse_openai_message(message)
    assert resp.kind == "message"
    assert resp.content == "hello"


def test_providers_surface_exact_token_usage() -> None:
    # Each provider must expose the API's exact token counts on the response so
    # the ledger records them instead of a character-count estimate.
    from opentorus.providers.anthropic_provider import _anthropic_usage, parse_anthropic_message
    from opentorus.providers.ollama_provider import _ollama_usage
    from opentorus.providers.openai_provider import _openai_usage

    # Ollama: counts live on the top-level response (prompt_eval_count/eval_count).
    u = _ollama_usage({"prompt_eval_count": 1234, "eval_count": 56})
    assert (u.prompt_tokens, u.completion_tokens) == (1234, 56)
    assert _ollama_usage({"message": {"content": "x"}}) is None  # no counts → estimate

    # OpenAI: completion.usage.
    comp = SimpleNamespace(usage=SimpleNamespace(prompt_tokens=2000, completion_tokens=300))
    assert _openai_usage(comp).prompt_tokens == 2000
    assert _openai_usage(SimpleNamespace(usage=None)) is None

    # Anthropic: message.usage flows through the parser onto the response.
    msg = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="hi")],
        usage=SimpleNamespace(input_tokens=999, output_tokens=42),
    )
    resp = parse_anthropic_message(msg)
    assert resp.usage is not None
    assert (resp.usage.prompt_tokens, resp.usage.completion_tokens) == (999, 42)
    assert _anthropic_usage(SimpleNamespace()) is None


def test_apportion_thinking_splits_exact_total_by_char_share() -> None:
    # The thinking subcount must be a share of the EXACT total (never independent
    # of it), so it stays consistent with — and bounded by — the reported output.
    from opentorus.providers.base import apportion_thinking

    # 16002 total, thinking dominates (45156 vs 1451 chars) → ~96.9% of the total.
    assert apportion_thinking(16002, "y" * 45156, "x" * 1451) == 15504
    assert apportion_thinking(100, "", "abc") == 0  # no thinking
    assert apportion_thinking(0, "yyyy", "x") == 0  # no output
    assert apportion_thinking(50, "y" * 100, "") == 50  # all thinking, capped at total


def test_providers_surface_thinking_tokens() -> None:
    # Reasoning tokens are a subset of the output count: exact for OpenAI
    # (reasoning_tokens); for Ollama/Anthropic the exact output total is
    # apportioned by character share between thinking and the rest.
    from opentorus.providers.anthropic_provider import parse_anthropic_message
    from opentorus.providers.openai_provider import _openai_usage

    # OpenAI: exact reasoning_tokens inside completion_tokens_details.
    comp = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=2000,
            completion_tokens=900,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=700),
        )
    )
    assert _openai_usage(comp).thinking_tokens == 700

    # Anthropic: thinking blocks apportioned out of the exact output_tokens.
    msg = SimpleNamespace(
        content=[
            SimpleNamespace(type="thinking", thinking="y" * 800),
            SimpleNamespace(type="text", text="final"),
        ],
        usage=SimpleNamespace(input_tokens=500, output_tokens=300),
    )
    resp = parse_anthropic_message(msg)
    assert resp.usage is not None
    assert resp.usage.thinking_tokens == 298  # 300 * 800/805
    assert resp.usage.thinking_tokens <= resp.usage.completion_tokens


def test_parse_ollama_tool_call_and_message() -> None:
    tool_msg = {
        "tool_calls": [{"function": {"name": "memory_list", "arguments": {"kind": "facts"}}}]
    }
    resp = parse_ollama_message(tool_msg)
    assert resp.kind == "tool_call"
    assert resp.tool_name == "memory_list"
    assert resp.tool_args == {"kind": "facts"}
    assert resp.tool_call_id  # synthesized when missing

    plain = parse_ollama_message({"content": "hi"})
    assert plain.kind == "message"
    assert plain.content == "hi"


def test_parse_anthropic_tool_call() -> None:
    block = SimpleNamespace(type="tool_use", id="tu_1", name="status", input={})
    message = SimpleNamespace(content=[block])
    resp = parse_anthropic_message(message)
    assert resp.kind == "tool_call"
    assert resp.tool_name == "status"
    assert resp.tool_call_id == "tu_1"


def test_parse_openai_malformed_args_raises_recoverable() -> None:
    # Malformed tool-arg JSON must become a recoverable parse error (so the loop
    # retries with a hint), not a silent empty-args call.
    from opentorus.errors import ProviderError, is_recoverable_tool_parse_error

    fn = SimpleNamespace(name="read_file", arguments='{"path": ')  # truncated JSON
    call = SimpleNamespace(id="c1", function=fn)
    message = SimpleNamespace(tool_calls=[call], content=None)
    with pytest.raises(ProviderError) as exc:
        parse_openai_message(message)
    assert is_recoverable_tool_parse_error(exc.value)


def test_parse_ollama_malformed_args_raises_recoverable() -> None:
    from opentorus.errors import ProviderError, is_recoverable_tool_parse_error

    msg = {"tool_calls": [{"function": {"name": "read_file", "arguments": "{not json"}}]}
    with pytest.raises(ProviderError) as exc:
        parse_ollama_message(msg)
    assert is_recoverable_tool_parse_error(exc.value)


def test_parse_openai_parses_all_parallel_tool_calls() -> None:
    # All tool calls in a turn are captured; the scalar fields mirror the first.
    fn1 = SimpleNamespace(name="status", arguments="{}")
    fn2 = SimpleNamespace(name="git_diff", arguments="{}")
    calls = [SimpleNamespace(id="a", function=fn1), SimpleNamespace(id="b", function=fn2)]
    resp = parse_openai_message(SimpleNamespace(tool_calls=calls, content=None))
    assert resp.tool_name == "status"  # back-compat scalar = first
    assert [c.tool_name for c in resp.tool_calls] == ["status", "git_diff"]
    assert [c.tool_call_id for c in resp.tool_calls] == ["a", "b"]


_READ_FILE_SCHEMA = {
    "type": "object",
    "properties": {
        "path": {"type": "string"},
        "start": {"type": "integer"},
    },
    "required": ["path"],
}
_ENUM_SCHEMA = {
    "type": "object",
    "properties": {"scope": {"type": "string", "enum": ["primary", "exploration"]}},
}


def test_validate_tool_args_accepts_well_formed() -> None:
    from opentorus.tools.base import validate_tool_args

    assert validate_tool_args(_READ_FILE_SCHEMA, {"path": "a.txt", "start": 3}) is None


def test_validate_tool_args_flags_missing_required() -> None:
    from opentorus.tools.base import validate_tool_args

    err = validate_tool_args(_READ_FILE_SCHEMA, {"start": 1})
    assert err is not None and "path" in err


def test_validate_tool_args_flags_wrong_type() -> None:
    from opentorus.tools.base import validate_tool_args

    err = validate_tool_args(_READ_FILE_SCHEMA, {"path": "a", "start": "oops"})
    assert err is not None and "start" in err


def test_validate_tool_args_flags_bad_enum() -> None:
    from opentorus.tools.base import validate_tool_args

    err = validate_tool_args(_ENUM_SCHEMA, {"scope": "bogus"})
    assert err is not None and "one of" in err


def test_validate_tool_args_fails_open_on_unknown_schema() -> None:
    # Anything the validator does not understand leaves the tool's own checks
    # in charge — it must never block a call it cannot reason about.
    from opentorus.tools.base import validate_tool_args

    assert validate_tool_args({"not": "a real schema"}, {"x": 1}) is None
    assert validate_tool_args(_READ_FILE_SCHEMA, {"path": "a", "extra": 7}) is None


class _ScriptedProvider(BaseProvider):
    """Returns queued responses in order; used to drive the loop deterministically."""

    name = "scripted"

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = responses
        self.calls: list[list[dict]] = []

    def generate(self, messages, tools=None):  # type: ignore[override]
        self.calls.append(tools or [])
        return self._responses.pop(0)


def test_loop_persists_tool_call_and_result_turns(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    provider = _ScriptedProvider(
        [
            ProviderResponse(kind="tool_call", tool_name="status", tool_args={}, tool_call_id="c1"),
            ProviderResponse(kind="message", content="done"),
        ]
    )
    loop = AgentLoop(tmp_path, ot_dir, provider, registry, default_config())
    answer = loop.run("status please")
    assert answer == "done"

    msgs = read_messages(ot_dir)
    assistant_tool = next(m for m in msgs if m.role == "assistant" and m.metadata.get("tool_calls"))
    assert assistant_tool.metadata["tool_calls"][0]["id"] == "c1"
    tool_msg = next(m for m in msgs if m.role == "tool")
    assert tool_msg.metadata["tool_call_id"] == "c1"
    # The provider received JSON-schema tool specs.
    assert any(spec["name"] == "status" for spec in provider.calls[0])


def test_loop_executes_all_tool_calls_in_one_turn(tmp_path: Path) -> None:
    # A turn with several tool calls runs every one (each gated and logged), not
    # just the first.
    from opentorus.actions import list_actions
    from opentorus.providers.base import ToolCallRequest

    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    multi = ProviderResponse(
        kind="tool_call",
        tool_name="status",
        tool_args={},
        tool_call_id="c1",
        tool_calls=[
            ToolCallRequest(tool_name="status", tool_args={}, tool_call_id="c1"),
            ToolCallRequest(tool_name="memory_list", tool_args={}, tool_call_id="c2"),
        ],
    )
    provider = _ScriptedProvider([multi, ProviderResponse(kind="message", content="done")])
    loop = AgentLoop(tmp_path, ot_dir, provider, registry, default_config())
    assert loop.run("status and memory") == "done"

    tools_run = [a.tool_name for a in list_actions(ot_dir)]
    assert "status" in tools_run and "memory_list" in tools_run
    msgs = read_messages(ot_dir)
    tool_ids = {m.metadata.get("tool_call_id") for m in msgs if m.role == "tool"}
    assert {"c1", "c2"} <= tool_ids
    # One assistant turn lists both calls.
    at = next(m for m in msgs if m.role == "assistant" and m.metadata.get("tool_calls"))
    assert len(at.metadata["tool_calls"]) == 2
