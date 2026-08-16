"""A read timeout must never escape as a raw traceback.

``urllib.request.urlopen`` raises a bare :class:`TimeoutError` when the *read* times
out. ``TimeoutError`` is an ``OSError`` but **not** a ``urllib.error.URLError``, so
every handler that caught only ``URLError`` let it through. That killed four real
benchmark runs (``examples/*/run.log``, 2026-08-16 06:19) inside the tool-calling
probe, before the run had done any work.

These tests pin the whole class of sites: each one must turn a read timeout into a
clean, typed, resumable failure.
"""

from __future__ import annotations

import urllib.request

import pytest

from opentorus.research.sources.base import SourceError, http_get_bytes, http_get_text


def _raise_timeout(*args: object, **kwargs: object) -> None:
    raise TimeoutError("timed out")


def test_timeout_is_not_a_urlerror() -> None:
    """The premise of the bug: catching URLError alone cannot catch a read timeout."""
    import urllib.error

    assert issubclass(TimeoutError, OSError)
    assert not issubclass(TimeoutError, urllib.error.URLError)


# --- literature sources: every lit_search / paper_fetch goes through here ------


def test_http_get_text_timeout_becomes_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    with pytest.raises(SourceError) as exc:
        http_get_text("https://example.invalid/api", timeout=7)
    message = str(exc.value)
    assert "Timed out after 7s" in message
    assert "transient" in message
    # Names the recovery, because the run's artifacts survive the failure.
    assert "re-running resumes" in message
    assert exc.value.status is None


def test_http_get_bytes_timeout_becomes_source_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    with pytest.raises(SourceError):
        http_get_bytes("https://example.invalid/paper.pdf", timeout=5)


# --- the tool-calling probe: the site that actually killed the four runs -------


def test_ollama_capability_timeout_is_transient_not_fatal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from opentorus.providers import tool_support

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    verdict, detail = tool_support._ollama_reports_tools("http://localhost:11434", "some-model")
    # Inconclusive — never a definitive "cannot call tools".
    assert verdict is None
    # Non-empty reason marks it transient, so the caller skips the probe.
    assert "could not reach" in detail.lower()


def test_unreachable_server_does_not_burn_probe_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead endpoint must not be probed further — the probe costs model calls."""
    from opentorus.config import default_config
    from opentorus.providers import tool_support

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    calls: list[object] = []
    monkeypatch.setattr(
        tool_support,
        "probe_tool_calling",
        lambda provider, **kw: calls.append(provider) or (None, "probed"),
    )

    config = default_config()
    config.model.provider = "ollama"
    config.model.name = "some-model"

    class _Provider:
        name = "ollama"

    ok, detail = tool_support.provider_supports_tool_calling(_Provider(), config)
    assert ok is None
    assert calls == [], "an unreachable server must not be probed with model calls"
    assert "could not reach" in detail.lower()


def test_probe_timeout_warns_and_proceeds(monkeypatch: pytest.MonkeyPatch) -> None:
    """The documented contract: a transient probe failure never blocks a run."""
    from opentorus.config import default_config
    from opentorus.providers import tool_support

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    config = default_config()
    config.model.provider = "ollama"
    config.model.name = "some-model"

    class _Provider:
        name = "ollama"

    warnings: list[str] = []
    # Must not raise — this is the exact call that ended four runs with a traceback.
    tool_support.require_tool_calling_provider(_Provider(), config, warn=warnings.append)
    assert len(warnings) == 1
    assert "some-model" in warnings[0]


# --- embeddings and vision ----------------------------------------------------


def test_ollama_embedder_timeout_is_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentorus.config import default_config
    from opentorus.research.embeddings import OllamaEmbedder

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    config = default_config()
    config.model.base_url = "http://localhost:11434"
    embedder = OllamaEmbedder(config, "nomic-embed-text")
    with pytest.raises(RuntimeError, match="Timed out"):
        embedder.encode(["hello"])


def test_vision_capability_timeout_returns_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentorus.providers.vision import _ollama_reports_vision

    monkeypatch.setattr(urllib.request, "urlopen", _raise_timeout)
    ok, reason = _ollama_reports_vision("http://localhost:11434", "llava")
    assert ok is False
    assert "Timed out" in reason
