"""Provider robustness: failure-class retries, streaming, context-length handling."""

from __future__ import annotations

import io
import json
import sys
import types
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import opentorus.providers.retry as retry
from opentorus.agent.session import SessionMessage, append_message, read_messages
from opentorus.config import default_config
from opentorus.errors import ProviderError
from opentorus.providers.base import ProviderResponse
from opentorus.providers.retry import (
    ContextLengthExceededError,
    FailureClass,
    backoff_seconds,
    classify_status,
)

_MSGS = [SessionMessage(role="user", content="hi")]


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []
    monkeypatch.setattr(retry, "_sleep", recorded.append)
    return recorded


# --- classification ---------------------------------------------------------------------


@pytest.mark.parametrize("status", [408, 425, 429, 500, 502, 503])
def test_answered_transient_statuses(status: int) -> None:
    assert classify_status(status) is FailureClass.ANSWERED_TRANSIENT


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_auth_and_validation_are_permanent(status: int) -> None:
    assert classify_status(status) is FailureClass.PERMANENT


def test_context_length_and_unreachable_classes() -> None:
    body = "This model's maximum context length is 262144 tokens. However, you requested 300000"
    assert classify_status(400, body) is FailureClass.CONTEXT_LENGTH
    assert classify_status(None) is FailureClass.UNREACHABLE


def test_answered_backs_off_longer_than_unreachable() -> None:
    answered = [backoff_seconds(FailureClass.ANSWERED_TRANSIENT, i) for i in range(4)]
    unreachable = [backoff_seconds(FailureClass.UNREACHABLE, i) for i in range(4)]
    assert answered == [2.0, 4.0, 8.0, 16.0]
    assert unreachable == [0.5, 1.0, 2.0, 4.0]
    assert backoff_seconds(FailureClass.ANSWERED_TRANSIENT, 0, retry_after=7) == 7.0
    assert backoff_seconds(FailureClass.ANSWERED_TRANSIENT, 30) == retry.ANSWERED_MAX_SECONDS


# --- Ollama -------------------------------------------------------------------------------


class _Resp:
    def __init__(self, body: dict) -> None:
        self._body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self) -> bytes:
        return self._body


def _http_error(code: int, body: str = "", headers: dict | None = None) -> urllib.error.HTTPError:
    import email.message

    msg = email.message.Message()
    for k, v in (headers or {}).items():
        msg[k] = v
    return urllib.error.HTTPError("http://h/api/chat", code, "err", msg, io.BytesIO(body.encode()))


def _ollama(monkeypatch, script):  # noqa: ANN001, ANN202
    """Serve ``script`` (exceptions are raised, dicts answered) and record bodies."""
    from opentorus.providers.ollama_provider import OllamaProvider

    bodies: list[dict] = []
    queue = list(script)

    def _open(request, timeout=None):  # noqa: ANN001
        bodies.append(json.loads(request.data))
        item = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(item, BaseException):
            raise item
        return _Resp(item)

    monkeypatch.setattr(urllib.request, "urlopen", _open)
    config = default_config()
    config.model.provider = "ollama"
    config.model.name = "m"
    config.model.max_retries = 3
    return OllamaProvider(config), bodies


_OK = {"model": "m", "message": {"role": "assistant", "content": "fine"}, "done": True}


def test_ollama_retries_a_busy_server_with_long_backoff(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(monkeypatch, [_http_error(503), _http_error(429), _OK])
    assert provider.generate(_MSGS).content == "fine"
    assert len(bodies) == 3 and sleeps == [2.0, 4.0]


def test_ollama_honours_retry_after(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, _ = _ollama(monkeypatch, [_http_error(429, headers={"Retry-After": "7"}), _OK])
    provider.generate(_MSGS)
    assert sleeps == [7.0]


def test_ollama_retries_unreachable_with_short_backoff(monkeypatch, sleeps) -> None:  # noqa: ANN001
    refused = urllib.error.URLError(ConnectionRefusedError(111, "refused"))
    provider, bodies = _ollama(monkeypatch, [refused, refused, _OK])
    assert provider.generate(_MSGS).content == "fine"
    assert sleeps == [0.5, 1.0]


def test_ollama_never_retries_validation_errors(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(monkeypatch, [_http_error(400, "model 'm' not found")])
    with pytest.raises(ProviderError, match="HTTP 400"):
        provider.generate(_MSGS)
    assert len(bodies) == 1 and sleeps == []


def test_ollama_retries_are_bounded(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(monkeypatch, [_http_error(503)])
    with pytest.raises(ProviderError, match="HTTP 503"):
        provider.generate(_MSGS)
    assert len(bodies) == 4  # 1 + max_retries(3)


def test_ollama_timeout_is_not_retried(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(monkeypatch, [TimeoutError("read timed out")])
    with pytest.raises(ProviderError, match="timed out"):
        provider.generate(_MSGS)
    assert len(bodies) == 1


def test_ollama_tool_parse_500_is_left_to_the_loop(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(monkeypatch, [_http_error(500, "error parsing tool call: x")])
    with pytest.raises(ProviderError, match="tool-call JSON"):
        provider.generate(_MSGS)
    assert len(bodies) == 1


def test_ollama_context_length_raises_the_dedicated_error(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(monkeypatch, [_http_error(400, "context length exceeded")])
    with pytest.raises(ContextLengthExceededError):
        provider.generate(_MSGS)
    assert len(bodies) == 1


def test_ollama_drops_think_for_a_model_without_thinking(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, bodies = _ollama(
        monkeypatch, [_http_error(400, '{"error":"\\"m\\" does not support thinking"}'), _OK]
    )
    provider.config.model.reasoning_effort = "high"
    assert provider.generate(_MSGS).content == "fine"
    assert bodies[0]["think"] is True and "think" not in bodies[1]
    assert sleeps == []  # an adaptation, not a retry


# --- OpenAI-compatible --------------------------------------------------------------------


class _StatusError(Exception):
    def __init__(self, status: int, text: str = "", headers: dict | None = None) -> None:
        super().__init__(f"Error code: {status} - {text}")
        self.status_code = status
        self.response = types.SimpleNamespace(status_code=status, headers=headers or {})


class APIConnectionError(Exception):
    pass


def _completion(content: str = "ok", finish: str = "stop"):  # noqa: ANN202
    return types.SimpleNamespace(
        model="served-model",
        usage=None,
        choices=[
            types.SimpleNamespace(
                finish_reason=finish,
                message=types.SimpleNamespace(content=content, tool_calls=None),
            )
        ],
    )


def _chunk(content=None, *, tool=None, finish=None, reasoning=None, usage=None):  # noqa: ANN001, ANN202
    delta = types.SimpleNamespace(content=content, tool_calls=tool, reasoning_content=reasoning)
    return types.SimpleNamespace(
        model="served-model",
        usage=usage,
        choices=[types.SimpleNamespace(delta=delta, finish_reason=finish)],
    )


def _tool_delta(index, *, id=None, name=None, args=None):  # noqa: ANN001, ANN202, A002
    return [
        types.SimpleNamespace(
            index=index, id=id, function=types.SimpleNamespace(name=name, arguments=args)
        )
    ]


def _openai(monkeypatch, script, *, stream=False):  # noqa: ANN001, ANN202
    """Fake SDK serving ``script`` items: exceptions raised, lists streamed, else returned."""
    requests: list[dict] = []
    clients: list[dict] = []
    queue = list(script)

    class Completions:
        def create(self, **kwargs):  # noqa: ANN003, ANN201
            requests.append(dict(kwargs))
            item = queue.pop(0) if len(queue) > 1 else queue[0]
            if isinstance(item, BaseException):
                raise item
            if callable(item):
                return item()
            return item

    class Client:
        def __init__(self, **kwargs):  # noqa: ANN003
            clients.append(kwargs)
            self.chat = types.SimpleNamespace(completions=Completions())

        def with_options(self, **kwargs):  # noqa: ANN003, ANN201
            clients.append({"with_options": kwargs})
            return self

    stub = types.ModuleType("openai")
    stub.OpenAI = Client  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", stub)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key-not-a-real-secret")
    from opentorus.providers.openai_provider import _EFFORT_REMAP, OpenAIProvider

    _EFFORT_REMAP.clear()
    config = default_config()
    config.model.provider = "openai"
    config.model.name = "m"
    config.model.base_url = "http://localhost:9/v1"
    config.model.max_retries = 3
    config.model.stream = stream
    return OpenAIProvider(config), requests, clients


def test_openai_own_retry_replaces_the_sdk_retry(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, requests, clients = _openai(
        monkeypatch, [_StatusError(503), APIConnectionError("down"), _completion()]
    )
    assert provider.generate(_MSGS).content == "ok"
    assert len(requests) == 3 and sleeps == [2.0, 1.0]
    assert {"with_options": {"max_retries": 0}} in clients


def test_openai_auth_failure_is_not_retried(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, requests, _ = _openai(monkeypatch, [_StatusError(401, "bad key")])
    with pytest.raises(ProviderError, match="401"):
        provider.generate(_MSGS)
    assert len(requests) == 1


def test_openai_context_length_is_its_own_error(monkeypatch, sleeps) -> None:  # noqa: ANN001
    text = "This model's maximum context length is 262144 tokens. However, you requested 9e5"
    provider, requests, _ = _openai(monkeypatch, [_StatusError(400, text)])
    with pytest.raises(ContextLengthExceededError):
        provider.generate(_MSGS)
    assert len(requests) == 1


def test_openai_effort_is_remapped_to_what_the_endpoint_supports(monkeypatch, sleeps) -> None:  # noqa: ANN001
    rejection = _StatusError(
        400,
        "{'error': {'message': 'Unexpected reasoning effort high. Supported types are "
        "xhigh (default), medium, and low.'}}",
    )
    provider, requests, _ = _openai(monkeypatch, [rejection, _completion(), _completion()])
    provider.config.model.reasoning_effort = "high"
    provider.generate(_MSGS)
    assert [r["reasoning_effort"] for r in requests] == ["high", "xhigh"]
    provider.generate(_MSGS)  # remembered for the endpoint: no second rejection
    assert requests[-1]["reasoning_effort"] == "xhigh" and len(requests) == 3


def test_openai_stream_assembles_text_tool_calls_and_usage(monkeypatch, sleeps) -> None:  # noqa: ANN001
    usage = types.SimpleNamespace(
        prompt_tokens=10, completion_tokens=5, completion_tokens_details=None
    )
    chunks = [
        _chunk(reasoning="think "),
        _chunk("Hel"),
        _chunk("lo", tool=_tool_delta(0, id="c1", name="read_file", args='{"pa')),
        _chunk(tool=_tool_delta(0, args='th": "x.md"}')),
        _chunk(finish="tool_calls"),
        types.SimpleNamespace(model="served-model", usage=usage, choices=[]),
    ]
    provider, requests, _ = _openai(monkeypatch, [lambda: iter(chunks)], stream=True)
    shown: list[str] = []
    thought: list[str] = []
    response = provider.respond(_MSGS, on_text=shown.append, on_thinking=thought.append)
    assert requests[0]["stream"] is True
    assert requests[0]["stream_options"] == {"include_usage": True}
    assert shown == ["Hel", "lo"] and thought == ["think "]
    assert response.kind == "tool_call"
    assert response.tool_calls[0].tool_args == {"path": "x.md"}
    assert response.usage is not None and response.usage.prompt_tokens == 10
    assert response.model == "served-model" and not response.truncated


def test_openai_stream_length_finish_marks_truncated(monkeypatch, sleeps) -> None:  # noqa: ANN001
    chunks = [_chunk("partial"), _chunk(finish="length")]
    provider, _, _ = _openai(monkeypatch, [lambda: iter(chunks)], stream=True)
    assert provider.generate(_MSGS).truncated is True


def test_reply_at_the_token_cap_counts_as_truncated_whatever_finish_reason_says(
    monkeypatch, sleeps
) -> None:  # noqa: ANN001
    """vLLM reports finish_reason "tool_calls" for a tool call cut off at max_tokens."""
    cut = types.SimpleNamespace(
        id="c1", function=types.SimpleNamespace(name="write_file", arguments='{"path": "p.md"')
    )
    completion = types.SimpleNamespace(
        model="m",
        usage=types.SimpleNamespace(
            prompt_tokens=50, completion_tokens=120, completion_tokens_details=None
        ),
        choices=[
            types.SimpleNamespace(
                finish_reason="tool_calls",
                message=types.SimpleNamespace(content=None, tool_calls=[cut]),
            )
        ],
    )
    provider, _, _ = _openai(monkeypatch, [completion])
    provider.config.model.max_tokens = 120
    response = provider.generate(_MSGS)
    assert response.truncated is True and response.kind == "tool_call"
    provider.config.model.max_tokens = 4000  # well under the cap: an ordinary parse error
    with pytest.raises(ProviderError, match="Failed to parse JSON"):
        provider.generate(_MSGS)


def test_openai_stream_without_finish_reason_is_an_error(monkeypatch, sleeps) -> None:  # noqa: ANN001
    provider, requests, _ = _openai(monkeypatch, [lambda: iter([_chunk("half")])], stream=True)
    with pytest.raises(ProviderError, match="without a finish_reason"):
        provider.generate(_MSGS)
    assert len(requests) == 1  # bytes had arrived: not retried


def test_openai_stream_retries_only_before_the_first_byte(monkeypatch, sleeps) -> None:  # noqa: ANN001
    def broken_after_first():  # noqa: ANN202
        yield _chunk("Hel")
        raise ConnectionError("reset")

    provider, requests, _ = _openai(monkeypatch, [broken_after_first], stream=True)
    with pytest.raises(ProviderError, match="after the response had started"):
        provider.generate(_MSGS)
    assert len(requests) == 1

    def broken_before_first():  # noqa: ANN202
        raise APIConnectionError("reset")
        yield  # pragma: no cover

    ok = [_chunk("done"), _chunk(finish="stop")]
    provider, requests, _ = _openai(
        monkeypatch, [broken_before_first, lambda: iter(ok)], stream=True
    )
    assert provider.generate(_MSGS).content == "done"
    assert len(requests) == 2


# --- the agent loop on a context overflow ------------------------------------------------


class _Overflowing:
    name = "overflowing"
    supports_streaming = False

    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def respond(self, messages, tools=None, on_text=None, **_kw):  # noqa: ANN001, ANN003, ANN201
        self.calls += 1
        if self.calls <= self.failures:
            raise ContextLengthExceededError("context length exceeded")
        return ProviderResponse(kind="message", content="answer")


def _loop_ws(tmp_path: Path):  # noqa: ANN202
    from opentorus.workspace import init_workspace, workspace_dir

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    for i in range(12):
        append_message(ot, SessionMessage(role="user", content=f"old task {i} " * 30))
        append_message(ot, SessionMessage(role="assistant", content=f"old answer {i} " * 30))
    config = default_config()
    config.context.compaction_llm = False
    return ot, config


def test_loop_compacts_once_on_context_overflow_then_succeeds(tmp_path: Path) -> None:
    from opentorus.agent.loop import AgentLoop
    from opentorus.tools.registry import ToolRegistry

    ot, config = _loop_ws(tmp_path)
    provider = _Overflowing(failures=1)
    loop = AgentLoop(tmp_path, ot, provider, ToolRegistry(), config)  # type: ignore[arg-type]
    assert loop.run("new task") == "answer"
    markers = [m for m in read_messages(ot) if m.metadata.get("compaction_marker")]
    assert len(markers) == 1 and markers[0].metadata["trigger"] == "forced"


def test_loop_raises_a_second_context_overflow(tmp_path: Path) -> None:
    from opentorus.agent.loop import AgentLoop
    from opentorus.tools.registry import ToolRegistry

    ot, config = _loop_ws(tmp_path)
    loop = AgentLoop(tmp_path, ot, _Overflowing(failures=5), ToolRegistry(), config)  # type: ignore[arg-type]
    with pytest.raises(ContextLengthExceededError):
        loop.run("new task")
