"""Tests for --verbose LLM tracing and Ollama streaming."""

from __future__ import annotations

import pytest

from opentorus.agent.session import SessionMessage
from opentorus.config import default_config, set_dotted
from opentorus.providers.ollama_provider import OllamaProvider, build_ollama_chat_body
from opentorus.ux import make_llm_trace


def test_build_ollama_chat_body_stream_flag() -> None:
    body = build_ollama_chat_body(
        default_config(),
        [SessionMessage(role="user", content="hi")],
        None,
        stream=True,
    )
    assert body["stream"] is True


def test_ollama_stream_respond(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        b'{"message":{"role":"assistant","content":"Hel"},"done":false}\n',
        b'{"message":{"role":"assistant","content":"lo"},"done":false}\n',
        b'{"message":{"role":"assistant","content":"!"},"done":true}\n',
    ]

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def __iter__(self):
            return iter(lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _FakeResponse())

    config = set_dotted(default_config(), "model.provider", "ollama")
    provider = OllamaProvider(config)
    chunks: list[str] = []
    response = provider.respond(
        [SessionMessage(role="user", content="hi")],
        on_text=chunks.append,
        stream=True,
    )
    assert response.kind == "message"
    assert response.content == "Hello!"
    assert "".join(chunks) == "Hello!"


def test_ollama_stream_surfaces_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    lines = [
        b'{"message":{"role":"assistant","thinking":"Let me ","content":""},"done":false}\n',
        b'{"message":{"role":"assistant","thinking":"reason.","content":""},"done":false}\n',
        b'{"message":{"role":"assistant","content":"Answer."},"done":true}\n',
    ]

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def __iter__(self):
            return iter(lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _FakeResponse())

    config = set_dotted(default_config(), "model.provider", "ollama")
    provider = OllamaProvider(config)
    thinking: list[str] = []
    content: list[str] = []
    response = provider.respond(
        [SessionMessage(role="user", content="hi")],
        on_text=content.append,
        on_thinking=thinking.append,
        stream=True,
    )
    assert "".join(thinking) == "Let me reason."
    assert "".join(content) == "Answer."
    assert response.content == "Answer."


def test_ollama_stream_preserves_tool_calls_through_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The tool call arrives in one delta; the final ``done`` chunk has an empty
    # message. Streamed tool calls must NOT be dropped by the done chunk.
    lines = [
        b'{"message":{"role":"assistant","content":""},"done":false}\n',
        b'{"message":{"role":"assistant","content":"",'
        b'"tool_calls":[{"function":{"name":"write_file",'
        b'"arguments":{"path":"out.md","content":"hi"}}}]},"done":false}\n',
        b'{"message":{"role":"assistant","content":""},"done":true}\n',
    ]

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def __iter__(self):
            return iter(lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: _FakeResponse())

    config = set_dotted(default_config(), "model.provider", "ollama")
    provider = OllamaProvider(config)
    response = provider.respond(
        [SessionMessage(role="user", content="write the file")],
        tools=[{"name": "write_file", "description": "", "parameters": {}}],
        stream=True,
    )
    assert response.kind == "tool_call"
    assert response.tool_name == "write_file"
    assert response.tool_args == {"path": "out.md", "content": "hi"}


def test_make_llm_trace_disabled_by_default() -> None:
    on_request, on_response, on_text, stream, on_thinking, trace = make_llm_trace(
        None, verbose=False
    )
    assert on_request is None
    assert on_response is None
    assert stream is False
    assert on_thinking is None
    assert trace is None


def test_make_llm_trace_enabled() -> None:
    from io import StringIO

    from rich.console import Console

    from opentorus.providers.base import ProviderResponse

    console = Console(file=StringIO(), width=120)
    captured: list[str] = []

    on_request, on_response, on_text, stream, on_thinking, trace = make_llm_trace(
        console,
        verbose=True,
        user_on_text=captured.append,
    )
    assert on_request is not None
    assert on_response is not None
    assert on_text is not None
    assert stream is True
    assert on_thinking is not None
    assert trace is not None

    on_request(
        [
            SessionMessage(role="system", content="sys"),
            SessionMessage(role="user", content="hello"),
        ],
        [{"name": "read_file", "description": "d", "parameters": {}}],
    )
    on_text("Hel")
    on_text("lo")
    assert captured == ["Hel", "lo"]
    on_thinking("reasoning…")
    output = console.file.getvalue()
    assert "Step 1" in output
    assert "hello" in output
    assert "reasoning…" in output
    assert "sys" not in output or "system" in output
    on_response(ProviderResponse(kind="tool_call", tool_name="read_file", tool_args={"path": "x"}))
    assert "→ call" in console.file.getvalue()


def test_make_llm_trace_incremental_context() -> None:
    from io import StringIO

    from rich.console import Console

    console = Console(file=StringIO(), width=120)
    on_request, _, _, _, _, _ = make_llm_trace(console, verbose=True)
    assert on_request is not None
    on_request(
        [
            SessionMessage(role="system", content="system prompt"),
            SessionMessage(role="user", content="goal"),
        ],
        None,
    )
    on_request(
        [
            SessionMessage(role="system", content="system prompt"),
            SessionMessage(role="user", content="goal"),
            SessionMessage(role="assistant", content="calling tool"),
            SessionMessage(
                role="tool",
                content="created PROOF-0001 [sketch]",
                metadata={"name": "proof_write"},
            ),
        ],
        None,
    )
    output = console.file.getvalue()
    assert output.count("goal") == 1
    assert "calling tool" in output
    assert "PROOF-0001" in output
    assert "Step 2" in output


def test_make_llm_trace_truncates_bulky_tool_messages() -> None:
    from io import StringIO

    from rich.console import Console

    console = Console(file=StringIO(), width=120)
    on_request, _, _, _, _, _ = make_llm_trace(console, verbose=True)
    assert on_request is not None
    on_request(
        [
            SessionMessage(
                role="tool",
                content="created PROOF-0001 [sketch] at path\nGaps recorded: 2\n\n" + ("x" * 500),
                metadata={"name": "proof_write"},
            ),
        ],
        None,
    )
    output = console.file.getvalue()
    assert "PROOF-0001" in output
    assert "Gaps recorded: 2" in output
    assert "x" * 100 not in output


def test_llm_trace_session_phase_banner() -> None:
    from io import StringIO

    from rich.console import Console

    from opentorus.ux import LlmTraceSession

    console = Console(file=StringIO(), width=120)
    trace = LlmTraceSession(console, debug=False)
    trace.set_banner("Proof draft")
    trace.on_request([SessionMessage(role="user", content="go")], None)
    output = console.file.getvalue()
    assert "Proof draft" in output
    assert "Step 1 · Proof draft" in output


def test_configure_llm_cli_hooks_default_is_spinner_only() -> None:
    from io import StringIO

    from rich.console import Console

    from opentorus.ux import configure_llm_cli_hooks

    console = Console(file=StringIO(), width=120)
    hooks = configure_llm_cli_hooks(console, verbose=False, debug=False)
    assert hooks.on_llm_text is None
    assert hooks.on_thinking is None
    assert hooks.on_llm_request is None
    assert hooks.stream_llm is False


def test_configure_llm_cli_hooks_verbose_enables_trace() -> None:
    from io import StringIO

    from rich.console import Console

    from opentorus.ux import configure_llm_cli_hooks

    console = Console(file=StringIO(), width=120)
    hooks = configure_llm_cli_hooks(console, verbose=True, debug=False)
    assert hooks.on_llm_text is not None
    assert hooks.on_thinking is not None
    assert hooks.on_llm_request is not None
    assert hooks.stream_llm is True


def test_make_llm_stream_callbacks() -> None:
    from io import StringIO

    from rich.console import Console

    from opentorus.ux import ActivityIndicator, make_llm_stream_callbacks

    console = Console(file=StringIO(), width=120)
    indicator = ActivityIndicator(console, enabled=False)
    on_text, on_thinking = make_llm_stream_callbacks(console, indicator=indicator)
    on_thinking("reasoning chunk")
    on_text("answer chunk")
    output = console.file.getvalue()
    assert "reasoning chunk" in output
    assert "answer chunk" in output
