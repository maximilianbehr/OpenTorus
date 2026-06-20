"""Opt-in integration test for the Ollama provider.

These tests talk to a *live* Ollama server, so they are marked ``integration``
and deselected by the default ``pytest`` run (see ``addopts`` in pyproject). Run
them explicitly with ``pytest -m integration``. Even then they skip gracefully
when no server is reachable, or when the only available model cannot satisfy the
test (insufficient memory, or no tool-calling support) — those are environment
limitations, not provider defects.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import NoReturn

import pytest

from opentorus.agent.session import SessionMessage
from opentorus.config import default_config, set_dotted
from opentorus.errors import ProviderError
from opentorus.providers.ollama_provider import OllamaProvider

_CANDIDATE_HOSTS = ("http://localhost:11434", "http://localhost:11435")


def _discover() -> tuple[str, str] | None:
    """Return (host, model) for a reachable Ollama server, or None."""
    for host in _CANDIDATE_HOSTS:
        try:
            with urllib.request.urlopen(f"{host}/api/tags", timeout=2) as response:
                data = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            continue
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        if models:
            return host, models[0]
    return None


_STATUS_TOOL = {
    "name": "status",
    "description": "Show workspace, git, and project status.",
    "parameters": {"type": "object", "properties": {}},
}

# Server-side conditions that mean "this model cannot satisfy the test here", as
# opposed to a provider bug. We skip rather than fail on these.
_ENV_LIMIT_MARKERS = ("more system memory", "does not support tools", "requires more system")


def _config(host: str, model: str):
    config = set_dotted(default_config(), "model.provider", "ollama")
    config = set_dotted(config, "model.name", model)
    return set_dotted(config, "model.base_url", host)


@pytest.fixture
def ollama_target() -> tuple[str, str]:
    """Discover a reachable Ollama server lazily, or skip.

    Done in a fixture (not at import time) so collection never touches the
    network when these tests are deselected by the default ``-m 'not integration'``.
    """
    target = _discover()
    if target is None:
        pytest.skip("No local Ollama server reachable.")
    return target


def _skip_on_env_limit(exc: ProviderError) -> NoReturn:
    """Skip when the reachable model can't run here (memory / no tool support)."""
    if any(marker in str(exc).lower() for marker in _ENV_LIMIT_MARKERS):
        pytest.skip(f"Reachable Ollama model cannot satisfy this test: {exc}")
    raise exc


@pytest.mark.integration
def test_ollama_round_trip(ollama_target: tuple[str, str]) -> None:
    host, model = ollama_target
    provider = OllamaProvider(_config(host, model))
    try:
        response = provider.generate(
            [
                SessionMessage(role="system", content="You are concise."),
                SessionMessage(role="user", content="Reply with exactly the word: pong"),
            ]
        )
    except ProviderError as exc:
        _skip_on_env_limit(exc)
    assert response.kind == "message"
    assert response.content.strip() != ""


@pytest.mark.integration
def test_ollama_tool_calling(ollama_target: tuple[str, str]) -> None:
    host, model = ollama_target
    provider = OllamaProvider(_config(host, model))
    try:
        response = provider.generate(
            [
                SessionMessage(
                    role="system",
                    content="Use the provided tools when the user asks about workspace status.",
                ),
                SessionMessage(role="user", content="What is the current workspace status?"),
            ],
            tools=[_STATUS_TOOL],
        )
    except ProviderError as exc:
        _skip_on_env_limit(exc)
    # Tool support depends on the model; accept either a tool call (preferred) or
    # a plain message, but a tool call must be well-formed when present.
    if response.kind == "tool_call":
        assert response.tool_name == "status"
        assert response.tool_call_id
    else:
        assert response.content.strip() != ""


def test_ollama_timeout_raises_provider_error(monkeypatch: pytest.MonkeyPatch) -> None:
    config = set_dotted(default_config(), "model.provider", "ollama")
    config = set_dotted(config, "model.name", "test")
    config = set_dotted(config, "model.base_url", "http://localhost:11434")
    config.model.timeout_seconds = 5
    provider = OllamaProvider(config)

    def _timeout(*args: object, **kwargs: object) -> None:
        raise TimeoutError("timed out")

    monkeypatch.setattr(urllib.request, "urlopen", _timeout)
    with pytest.raises(ProviderError, match="timed out after 5s"):
        provider.generate([SessionMessage(role="user", content="hi")])
