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


def test_a_list_sent_as_prose_is_told_the_shape_to_send() -> None:
    """ "must be a array" is ungrammatical, silent about what arrived, and shows nothing.

    A Sendov run passed its whole gap list as one newline-separated bullet string. The
    rejection named the type and stopped there, so there was nothing to correct against.
    """
    from opentorus.tools.base import validate_tool_args

    schema = {"type": "object", "properties": {"gaps": {"type": "array"}}}
    err = validate_tool_args(schema, {"gaps": "- no explicit n_0 in Tao\n- degrees 9..n_0"})

    assert err is not None
    assert "must be an array" in err  # not "a array"
    assert "got str" in err
    assert '["no explicit n_0 in Tao", "…"]' in err
    assert "not one string with newlines or bullets" in err


def test_a_well_formed_list_still_passes() -> None:
    from opentorus.tools.base import validate_tool_args

    schema = {"type": "object", "properties": {"gaps": {"type": "array"}}}
    assert validate_tool_args(schema, {"gaps": ["a", "b"]}) is None


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


def test_leading_system_messages_are_merged_for_ollama() -> None:
    # Strict chat templates accept exactly ONE system message and reject the rest
    # with "system message must be at the beginning" — verified against Ollama:
    # one leading system works, two do not, regardless of position. OpenTorus
    # builds four leading system blocks, so whole model families failed on turn 1.
    from opentorus.agent.session import SessionMessage
    from opentorus.providers._convert import to_ollama_messages

    msgs = [
        SessionMessage(role="system", content="workspace"),
        SessionMessage(role="system", content="goal"),
        SessionMessage(role="system", content="retrieval"),
        SessionMessage(role="user", content="task"),
        SessionMessage(role="assistant", content="reply"),
    ]
    out = to_ollama_messages(msgs)
    assert [m["role"] for m in out] == ["system", "user", "assistant"]
    assert out[0]["content"] == "workspace\n\ngoal\n\nretrieval"  # content preserved verbatim

    # A single leading system message is passed through untouched.
    single = to_ollama_messages(
        [SessionMessage(role="system", content="only"), SessionMessage(role="user", content="hi")]
    )
    assert [m["role"] for m in single] == ["system", "user"]
    assert single[0]["content"] == "only"


# --- arguments a model encoded as strings ---------------------------------------

_COERCE_SCHEMA = {
    "type": "object",
    "properties": {
        "gaps": {"type": "array"},
        "limit": {"type": "integer"},
        "meta": {"type": "object"},
    },
}


def test_a_json_encoded_argument_is_read_back(tmp_path: Path) -> None:
    """Teaching the shape was not enough; the value was already right.

    llama3.1:70b sent ``gaps`` as a string sixteen times across two examples with the
    required JSON spelled out in every reply — and what it sent was the correct array,
    JSON-encoded once too often, plus ``limit='10'`` for an integer. Those are encodings
    of the intended value, not different values.
    """
    from opentorus.tools.base import coerce_tool_args, validate_tool_args

    args = coerce_tool_args(
        _COERCE_SCHEMA,
        {"gaps": '["[GAP-1] We need to show the bound"]', "limit": "10", "meta": '{"k": 1}'},
    )

    assert args == {"gaps": ["[GAP-1] We need to show the bound"], "limit": 10, "meta": {"k": 1}}
    assert validate_tool_args(_COERCE_SCHEMA, args) is None


def test_a_single_bare_item_is_wrapped_but_a_list_in_prose_is_not() -> None:
    """Wrapping one item invents no boundaries; splitting a bullet list would.

    A gap count is load-bearing — the referee counts them — so guessing how many items
    a multi-line string held is exactly the kind of silent reinterpretation to avoid.
    """
    from opentorus.tools.base import coerce_tool_args, validate_tool_args

    single = coerce_tool_args(_COERCE_SCHEMA, {"gaps": "[GAP-1]"})
    assert single == {"gaps": ["[GAP-1]"]}

    prose = {"gaps": "- no explicit n_0 in Tao\n- degrees 9..n_0 unresolved"}
    assert coerce_tool_args(_COERCE_SCHEMA, prose) == prose
    error = validate_tool_args(_COERCE_SCHEMA, prose)
    assert error is not None and "not one string with newlines or bullets" in error


def test_coercion_never_papers_over_a_real_mistake() -> None:
    from opentorus.tools.base import coerce_tool_args, validate_tool_args

    for bad in ({"limit": "zehn"}, {"limit": True}, {"meta": "{broken"}):
        assert coerce_tool_args(_COERCE_SCHEMA, bad) == bad
        assert validate_tool_args(_COERCE_SCHEMA, bad) is not None


def test_a_renamed_argument_is_named_in_the_rejection() -> None:
    """Across the recorded runs this failure is a renaming, not an omission.

    memory_add wanted 'text' and got 'note' or 'content'; claim_new wanted 'statement'
    and got 'claim'; dossier_known_result_add wanted 'source_artifacts' and got
    'paper_id'. "Missing required argument 'text'." says nothing about the value sitting
    right there under another name, so the model cannot see the mismatch — one run
    repeated the same call five times.
    """
    from opentorus.tools.base import validate_tool_args

    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "kind": {"type": "string"}},
        "required": ["text"],
    }
    err = validate_tool_args(schema, {"kind": "observations", "note": "PAPER-0003 states X"})

    assert err is not None
    assert "Missing required argument 'text'" in err
    assert "no argument 'note'" in err
    assert "send it under 'text'" in err


def test_a_genuinely_empty_call_lists_what_the_tool_takes() -> None:
    """With nothing to point at, the useful thing is the accepted argument names."""
    from opentorus.tools.base import validate_tool_args

    schema = {
        "type": "object",
        "properties": {"text": {"type": "string"}, "kind": {"type": "string"}},
        "required": ["text"],
    }
    err = validate_tool_args(schema, {"kind": "facts"})

    assert err is not None
    assert "Accepted arguments: 'kind', 'text'" in err
    assert "no argument" not in err


def test_a_paper_summary_is_pointed_at_paper_read_too() -> None:
    """A paper's bytes and its reading note are the same request.

    papers/PAPER-XXXX/ was recognised; summaries/PAPER-XXXX.md got the generic hint,
    which names no way to read a paper at all. Observed on a difference-triangle-set run.
    """
    from opentorus.tools.filesystem import _read_blocked_message

    for path in (
        ".opentorus/summaries/PAPER-0001.md",
        ".opentorus/papers/PAPER-0001/extracted.txt",
    ):
        message = _read_blocked_message(path, tuple(path.split("/")))
        assert message is not None
        assert 'paper_read("PAPER-0001")' in message


def test_a_recorded_proof_is_not_pointed_at_the_literature() -> None:
    from opentorus.tools.filesystem import _read_blocked_message

    path = ".opentorus/proof_attempts/PROOF-0001.md"
    message = _read_blocked_message(path, tuple(path.split("/")))
    assert message is not None
    assert "paper_fetch" not in message
    assert "proof_write" in message


def test_a_tool_name_with_a_stray_space_still_resolves(tmp_path: Path) -> None:
    """No registered tool has whitespace in its name, so "read_ file" is unambiguous.

    Observed 39 times across four runs — read_ file, paper_ fetch, list_ files,
    write_ file, glob_ files, exp_ new, exp_ run — with one run spending 25 of its 76
    actions on it while every reply listed the available tools. Explaining did not help;
    the model was not choosing the name, its output was corrupted.
    """
    registry = build_default_registry(tmp_path, tmp_path / ".opentorus")

    for written, meant in (
        ("read_ file", "read_file"),
        ("glob_ files", "glob_files"),
        (" status ", "status"),
    ):
        tool, resolved = registry.resolve(written)
        assert tool is not None, written
        assert resolved == meant


def test_a_genuinely_unknown_tool_still_misses(tmp_path: Path) -> None:
    """Recovering a corrupted name must not invent a tool that does not exist."""
    registry = build_default_registry(tmp_path, tmp_path / ".opentorus")

    tool, resolved = registry.resolve("find_file")
    assert tool is None
    assert resolved == "find_file"


def test_a_throttled_web_search_says_so_and_names_the_alternative() -> None:
    """A bare transport error reads as "the web is broken" or "my query was bad".

    The search backend throttles hard: 43 of 130 web_search calls across ten recorded
    runs came back "Connection reset by peer", and retrying the same query immediately
    just spends another turn.
    """
    from unittest.mock import patch

    from opentorus.research.sources.base import SourceError
    from opentorus.tools.base import ToolCall
    from opentorus.tools.builtin import WebSearchTool

    error = SourceError(
        "Could not reach https://html.duckduckgo.com/html/?q=x: "
        "[Errno 104] Connection reset by peer"
    )
    with patch("opentorus.tools.web.web_search", side_effect=error):
        result = WebSearchTool().run(ToolCall(id="c1", name="web_search", args={"query": "x"}))

    assert not result.ok
    assert "Connection reset by peer" in result.content  # the real error survives
    assert "throttling" in result.content
    assert "lit_search" in result.content


def test_a_genuine_http_error_gets_no_throttling_advice() -> None:
    from unittest.mock import patch

    from opentorus.research.sources.base import SourceError
    from opentorus.tools.base import ToolCall
    from opentorus.tools.builtin import WebSearchTool

    with patch("opentorus.tools.web.web_search", side_effect=SourceError("HTTP 404 from u: gone")):
        result = WebSearchTool().run(ToolCall(id="c1", name="web_search", args={"query": "x"}))

    assert not result.ok
    assert "throttling" not in result.content


def test_a_memory_kind_with_stray_whitespace_still_resolves() -> None:
    """The kind arrived as "  \\ndecisions  " and was answered "Unknown memory kind".

    `text` was already stripped in the same method; `kind` was not. Eight of these
    across three runs in one night, each about a kind that plainly exists.
    """
    import tempfile

    from opentorus.tools.base import ToolCall
    from opentorus.tools.research import MemoryAddTool
    from opentorus.workspace import init_workspace, workspace_dir

    root = Path(tempfile.mkdtemp())
    init_workspace(root)
    tool = MemoryAddTool(workspace_dir(root))

    result = tool.run(
        ToolCall(id="c", name="memory_add", args={"kind": "  \ndecisions  ", "text": "X"})
    )
    assert result.ok, result.content
    assert "(decisions)" in result.content

    bad = tool.run(ToolCall(id="c", name="memory_add", args={"kind": "nonsense", "text": "X"}))
    assert not bad.ok


def test_an_environment_name_split_by_a_space_still_resolves() -> None:
    """ "python- sci" can only mean "python-sci" — no environment name has whitespace.

    Ten such calls in one run, each answered with a list of known environments that
    contained the very name the model had meant. The tool registry already recovers a
    tool name the same way.
    """
    import tempfile

    import yaml

    from opentorus.errors import OpenTorusError
    from opentorus.execution.environments import resolve_environment
    from opentorus.workspace import init_workspace, workspace_dir

    root = Path(tempfile.mkdtemp())
    init_workspace(root)
    ot = workspace_dir(root)
    (ot / "environments.yaml").write_text(
        yaml.safe_dump({"environments": {"python-sci": {"image": "x:local"}}}), encoding="utf-8"
    )

    for written in ("python-sci", "python- sci", "python-\nsci"):
        assert resolve_environment(ot, written) is not None, written

    with pytest.raises(OpenTorusError):
        resolve_environment(ot, "nope")


def test_a_timed_out_command_says_the_limit_is_the_callers(tmp_path: Path) -> None:
    """ "Timed out after 120s" reads as a verdict on the command, not on its budget.

    Ten such runs across seven dossiers, spanning three days, and not one of them then
    raised the limit — 120s is the tool's default, which the message never said.
    """
    import sys

    from opentorus.tools.shell import run_shell

    # Portable across the CI matrix: `sleep` is not a Windows command and "/tmp" is not
    # a Windows directory, which is how this test first broke the Windows job.
    sleeper = f'"{sys.executable}" -c "import time; time.sleep(30)"'
    result = run_shell(sleeper, cwd=str(tmp_path), timeout=1)

    assert result.timed_out and result.exit_code == 124
    assert "caller-supplied limit" in result.stderr
    assert "not a property of the command" in result.stderr


def test_a_tool_name_with_the_wrong_case_resolves() -> None:
    """ "read_File" is the same failure as "read_ file": right tool, typed slightly wrong.

    Twelve occurrences in a single sampling sweep, from a model that had the full tool
    list in its context. Every registered name is lower case and no two differ only by
    case, so the recovery is unambiguous.
    """
    import tempfile

    from opentorus.config import default_config
    from opentorus.tools.builtin import build_default_registry
    from opentorus.workspace import init_workspace, workspace_dir

    root = Path(tempfile.mkdtemp())
    init_workspace(root)
    registry = build_default_registry(root, workspace_dir(root), default_config())

    for written in ("read_File", "Read_File", "read_ file", "Read_ File"):
        tool, _ = registry.resolve(written)
        assert tool is not None and tool.name == "read_file", written

    assert registry.resolve("PAPER_READ")[0].name == "paper_read"
    assert registry.resolve("exp_Run")[0].name == "exp_run"


def test_an_unknown_tool_is_still_unknown() -> None:
    import tempfile

    from opentorus.config import default_config
    from opentorus.tools.builtin import build_default_registry
    from opentorus.workspace import init_workspace, workspace_dir

    root = Path(tempfile.mkdtemp())
    init_workspace(root)
    registry = build_default_registry(root, workspace_dir(root), default_config())
    assert registry.resolve("no_such_tool")[0] is None


_KEY_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "run_from": {"type": "string"},
        "gaps_markdown": {"type": "string"},
    },
    "required": ["title"],
}


def test_an_argument_name_split_by_whitespace_is_repaired() -> None:
    """An unknown key passes validation and the argument simply never arrives.

    116 calls across six recorded workspaces did this, and the three most common are
    optional fields on proof_write — gaps_ markdown (34), evidence_ notes (23),
    connection_ to_ dossier (20). A proof_write whose gaps silently vanish is recorded
    as a proof *without* gaps: gap laundering by typo rather than by intent.
    """
    from opentorus.tools.base import normalize_arg_keys, validate_tool_args

    raw = {"title": "X", "run_ from": "workspace", "gaps_ markdown": "[GAP-1] still open"}
    # The old behaviour: silently valid, and both values lost.
    assert validate_tool_args(_KEY_SCHEMA, raw) is None

    fixed = normalize_arg_keys(_KEY_SCHEMA, raw)
    assert fixed["run_from"] == "workspace"
    assert fixed["gaps_markdown"] == "[GAP-1] still open"
    assert "run_ from" not in fixed and "gaps_ markdown" not in fixed


def test_normalisation_never_overwrites_or_invents() -> None:
    from opentorus.tools.base import normalize_arg_keys

    # A key that compacts onto one already supplied is left alone — no silent overwrite.
    both = {"title": "X", "run_from": "experiment", "run_ from": "workspace"}
    assert normalize_arg_keys(_KEY_SCHEMA, both)["run_from"] == "experiment"

    # A key that is not a declared property stays exactly as it came.
    unknown = {"title": "X", "made up": 1}
    assert normalize_arg_keys(_KEY_SCHEMA, unknown) == unknown


def test_a_repaired_argument_name_stays_visible_in_the_ledger(tmp_path: Path) -> None:
    """A fix that erases its own evidence makes the next defect harder to find.

    normalize_arg_keys runs before every log_action, so recording only the repaired form
    would make "the model did not slip" indistinguishable from "the repair worked" —
    and reading actions.jsonl is how this defect was found in the first place. The note
    goes to the log only; the tool receives clean arguments.
    """
    from opentorus.actions import list_actions
    from opentorus.agent.loop import AgentLoop
    from opentorus.config import default_config
    from opentorus.providers.base import BaseProvider, ProviderResponse
    from opentorus.tools.builtin import build_default_registry
    from opentorus.workspace import init_workspace, workspace_dir

    class SlipProvider(BaseProvider):
        def __init__(self) -> None:
            self.calls = 0

        def generate(self, messages, tools=None) -> ProviderResponse:
            self.calls += 1
            if self.calls == 1:
                return ProviderResponse(
                    kind="tool_call", tool_name="read_file", tool_args={"pa th": "notes.md"}
                )
            return ProviderResponse(kind="message", content="done")

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    (tmp_path / "notes.md").write_text("SENTINEL", encoding="utf-8")
    config = default_config()
    config.permissions.mode = "trusted"
    loop = AgentLoop(
        tmp_path,
        ot,
        SlipProvider(),
        build_default_registry(tmp_path, ot, config),
        config,
        max_steps=4,
    )
    loop.run("read notes")

    logged = [a for a in list_actions(ot) if a.tool_name == "read_file"]
    assert logged, "the call should have run rather than failed"
    assert any("_repaired_keys" in (a.args or {}) for a in logged)


def test_openai_provider_honours_base_url_timeout_and_sampling() -> None:
    """``model.base_url`` selects the endpoint (a vLLM server as much as OpenAI) — it
    used to be ignored, so a config pointing at vLLM silently talked to OpenAI. The
    sampling shape is forwarded only when set."""
    from opentorus.config import default_config
    from opentorus.providers.openai_provider import build_openai_request, openai_client_kwargs

    config = default_config()
    config.model.provider = "openai"
    config.model.name = "gemma-4-31b-it"
    assert openai_client_kwargs(config) == {"timeout": 300.0}
    config.model.base_url = "http://localhost:8000/v1"
    config.model.timeout_seconds = 900
    assert openai_client_kwargs(config) == {
        "base_url": "http://localhost:8000/v1",
        "timeout": 900.0,
    }
    messages = [SessionMessage(role="user", content="hi")]
    plain = build_openai_request(config, messages, None)
    assert plain["model"] == "gemma-4-31b-it" and "tools" not in plain
    assert not {"max_tokens", "top_p", "seed"} & plain.keys()
    config.model.max_tokens = 4096
    config.model.top_p = 0.9
    config.model.seed = 7
    shaped = build_openai_request(
        config, messages, [{"name": "status", "description": "d", "parameters": {"type": "object"}}]
    )
    assert (shaped["max_tokens"], shaped["top_p"], shaped["seed"]) == (4096, 0.9, 7)
    assert shaped["tools"][0]["function"]["name"] == "status"


def test_openai_parser_strips_gemma4_channel_markers() -> None:
    """A vLLM server without ``--reasoning-parser gemma4`` leaks Gemma 4's thinking
    channel into the content (observed live: ``<|channel>thought\\n<channel|>The …``).
    The thinking block is dropped; ordinary content is untouched."""
    from types import SimpleNamespace

    from opentorus.providers.openai_provider import parse_openai_message, strip_channel_markers

    leaked = SimpleNamespace(
        content="<|channel>thought\nLet me think about it.<channel|>The workspace is empty.",
        tool_calls=None,
    )
    assert parse_openai_message(leaked).content == "The workspace is empty."
    empty_thought = SimpleNamespace(content="<|channel>thought\n<channel|>Done.", tool_calls=None)
    assert parse_openai_message(empty_thought).content == "Done."
    assert strip_channel_markers('plain {"a": 1}') == 'plain {"a": 1}'
    assert strip_channel_markers("<channel|>tail only") == "tail only"


def _roles(messages: list[dict]) -> list[str]:
    return [m["role"] for m in messages]


def test_no_system_message_survives_past_the_leading_run() -> None:
    """qwen-family templates reject a `system` message that is not at the beginning.

    OpenTorus deliberately places volatile state late, as a `system` message, so the
    head stays a reusable prefix for a local server's KV cache. vLLM serving qwen
    answers `400 System message must be at the beginning`, and six campaign drivers
    died on their first call 38 seconds in — against a model that had answered a
    tool-calling probe moments before. The wire format is normalised here, so the
    internal message model and its transcripts are untouched.
    """
    from opentorus.providers._convert import to_openai_messages

    messages = [
        SessionMessage(role="system", content="head"),
        SessionMessage(role="user", content="the question"),
        SessionMessage(role="system", content="Workspace context: volatile"),
        SessionMessage(
            role="assistant",
            content="",
            metadata={"tool_calls": [{"id": "c1", "name": "status", "arguments": {}}]},
        ),
        SessionMessage(role="tool", content="ok", metadata={"tool_call_id": "c1"}),
    ]
    out = to_openai_messages(messages)
    roles = _roles(out)
    head = 0
    while head < len(roles) and roles[head] == "system":
        head += 1
    assert "system" not in roles[head:], roles
    # Folded into the user turn, not dropped.
    assert "volatile" in out[head]["content"]


def test_folding_never_produces_two_user_turns_in_a_row() -> None:
    """The other strict-template failure: consecutive same-role messages."""
    from opentorus.providers._convert import to_openai_messages

    messages = [
        SessionMessage(role="system", content="head"),
        SessionMessage(role="assistant", content="prior answer"),
        SessionMessage(role="system", content="volatile"),
        SessionMessage(role="user", content="the question"),
    ]
    out = to_openai_messages(messages)
    roles = _roles(out)
    assert not any(a == b == "user" for a, b in zip(roles, roles[1:], strict=False)), roles
    # The question still ends the turn it rides in — it is the answer target.
    assert out[-1]["role"] == "user"
    assert out[-1]["content"].endswith("the question")


def test_a_trailing_system_block_becomes_its_own_user_turn() -> None:
    """After tool results there is no user turn to fold into; a `user` message is legal."""
    from opentorus.providers._convert import to_openai_messages

    messages = [
        SessionMessage(role="system", content="head"),
        SessionMessage(
            role="assistant",
            content="",
            metadata={"tool_calls": [{"id": "c1", "name": "status", "arguments": {}}]},
        ),
        SessionMessage(role="tool", content="ok", metadata={"tool_call_id": "c1"}),
        SessionMessage(role="system", content="volatile"),
    ]
    out = to_openai_messages(messages)
    assert _roles(out) == ["system", "assistant", "tool", "user"]
    assert out[-1]["content"] == "volatile"


def test_leading_system_messages_are_merged_into_one() -> None:
    """qwen's template allows exactly one system message, at index 0.

    Its rejection reads "System message must be at the beginning", which is really
    "a system message turned up where none may be" — and index 1 is already such a
    place. A campaign strategist call carried four (system prompt, tool routing,
    current task, workspace context) and died on its first request, taking the
    campaign with it. Merging preserves the text and the order.
    """
    from opentorus.providers._convert import to_openai_messages

    messages = [
        SessionMessage(role="system", content="prompt"),
        SessionMessage(role="system", content="routing"),
        SessionMessage(role="system", content="current task"),
        SessionMessage(role="system", content="workspace context"),
        SessionMessage(role="user", content="the strategist prompt"),
    ]
    out = to_openai_messages(messages)
    assert _roles(out) == ["system", "user"]
    for part in ("prompt", "routing", "current task", "workspace context"):
        assert part in out[0]["content"]
    assert out[-1]["content"] == "the strategist prompt"


def test_a_single_system_message_is_left_alone() -> None:
    from opentorus.providers._convert import to_openai_messages

    messages = [
        SessionMessage(role="system", content="prompt"),
        SessionMessage(role="user", content="q"),
    ]
    out = to_openai_messages(messages)
    assert out[0] == {"role": "system", "content": "prompt"}
