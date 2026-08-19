"""Tests for embedding backend selection (provider + local fallback)."""

from __future__ import annotations

import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from opentorus.config import default_config, set_dotted
from opentorus.research.embeddings import OllamaEmbedder, OpenAIEmbedder, load_embedder


def test_load_embedder_disabled() -> None:
    config = default_config()
    config.context.embeddings_enabled = False
    assert load_embedder(config) is None


def test_load_embedder_uses_openai_when_chat_provider_openai(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = set_dotted(default_config(), "model.provider", "openai")

    class _Stub:
        model_name = "text-embedding-3-small"

        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr("opentorus.research.embeddings._try_openai", lambda _cfg: _Stub())
    monkeypatch.setattr("opentorus.research.embeddings._try_ollama", lambda _cfg: None)
    monkeypatch.setattr("opentorus.research.embeddings._try_local", lambda _cfg: None)
    result = load_embedder(config)
    assert result is not None
    assert result.model_name == "text-embedding-3-small"


def test_openai_embedder_normalizes(monkeypatch: pytest.MonkeyPatch) -> None:
    config = set_dotted(default_config(), "model.provider", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    class _FakeEmbeddings:
        def create(self, *, model: str, input: list[str]):  # noqa: A002
            assert model == "text-embedding-3-small"
            row = MagicMock()
            row.embedding = [3.0, 4.0]
            out = MagicMock()
            out.data = [row]
            return out

    seen_kwargs: list[dict] = []

    def _client(**kwargs):  # noqa: ANN003
        seen_kwargs.append(kwargs)
        return SimpleNamespace(embeddings=_FakeEmbeddings())

    fake_openai = SimpleNamespace(OpenAI=_client)
    monkeypatch.setitem(sys.modules, "openai", fake_openai)

    embedder = OpenAIEmbedder(config, "text-embedding-3-small")
    vectors = embedder.encode(["hello"])
    assert len(vectors) == 1
    assert abs(vectors[0][0] - 0.6) < 1e-6
    assert abs(vectors[0][1] - 0.8) < 1e-6
    assert "base_url" not in seen_kwargs[-1]  # unset: the SDK's default endpoint
    # A configured endpoint (a local vLLM) is where the embeddings go too: the embedder
    # used to send workspace text to api.openai.com regardless of ``model.base_url``.
    config.model.base_url = "http://localhost:8000/v1"
    OpenAIEmbedder(config, "text-embedding-3-small").encode(["hello"])
    assert seen_kwargs[-1]["base_url"] == "http://localhost:8000/v1"


def test_ollama_embedder_parses_response(monkeypatch: pytest.MonkeyPatch) -> None:
    config = set_dotted(default_config(), "model.provider", "ollama")
    payload_holder: dict = {}

    class _FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return json.dumps({"embeddings": [[1.0, 0.0], [0.0, 1.0]]}).encode()

    def _fake_urlopen(request, timeout=120):  # noqa: ANN001, ARG001
        payload_holder["url"] = request.full_url
        return _FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", _fake_urlopen)
    embedder = OllamaEmbedder(config, "nomic-embed-text")
    vectors = embedder.encode(["a", "b"])
    assert payload_holder["url"].endswith("/api/embed")
    assert len(vectors) == 2
    assert vectors[0][0] == 1.0
    assert vectors[1][1] == 1.0


def test_local_openai_compatible_endpoint_embeds_locally_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A vLLM/llama.cpp endpoint configured as the ``openai`` provider is a chat server,
    not OpenAI: auto mode embeds on this machine first (sentence-transformers), then
    asks that endpoint, and the Ollama fallback targets the default local Ollama host —
    never the vLLM URL (no ``/api/embed`` there)."""
    from opentorus.research.embeddings import _attempt_order, _resolve_backend

    config = set_dotted(default_config(), "model.provider", "openai")
    config.model.base_url = "http://localhost:8000/v1"
    assert _resolve_backend(config) == "auto"
    assert _attempt_order(config, "auto") == ["local", "openai", "ollama"]
    assert OllamaEmbedder(config, "nomic-embed-text")._host == "http://localhost:11434"
    calls: list[str] = []

    class _Local:
        model_name = "all-MiniLM-L6-v2"

        def encode(self, texts: list[str]) -> list[list[float]]:
            return [[1.0] for _ in texts]

    monkeypatch.setattr(
        "opentorus.research.embeddings._try_local", lambda _cfg: calls.append("local") or _Local()
    )
    monkeypatch.setattr(
        "opentorus.research.embeddings._try_openai", lambda _cfg: calls.append("openai") or None
    )
    assert load_embedder(config).model_name == "all-MiniLM-L6-v2"  # type: ignore[union-attr]
    assert calls == ["local"]
    # a real OpenAI endpoint keeps the OpenAI embedder
    config.model.base_url = None
    assert _resolve_backend(config) == "openai"
    config.model.base_url = "https://api.openai.com/v1"
    assert _resolve_backend(config) == "openai"
