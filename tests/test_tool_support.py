"""Tool-calling capability detection: probe, Ollama /api/show, and refusal.

Design contract under test: the probe only ever CONFIRMS tool support (True) or is
INCONCLUSIVE (None) — it never returns a definitive False, because tool_choice is not
enforceable on every provider and refusing a tool-capable model is worse than
proceeding. A definitive negative comes only from Ollama /api/show.
"""

from __future__ import annotations

import json

import pytest

from opentorus.config import default_config
from opentorus.errors import OpenTorusError
from opentorus.providers.base import BaseProvider, ProviderResponse, ToolCallRequest
from opentorus.providers.tool_support import (
    _ollama_reports_tools,
    probe_tool_calling,
    provider_supports_tool_calling,
    require_tool_calling_provider,
)


class _Provider(BaseProvider):
    """A configurable fake provider for capability probing."""

    def __init__(self, name: str, behavior: str) -> None:
        self._name = name
        self._behavior = behavior  # "tool" | "tool_list" | "preamble" | "text" | "error"
        self.config = default_config()
        self.config.model.provider = name
        self.config.model.name = f"{name}-model"

    @property
    def name(self) -> str:
        return self._name

    def generate(self, messages, tools=None) -> ProviderResponse:
        if self._behavior == "error":
            raise RuntimeError("model does not accept a 'tools' parameter")
        if self._behavior == "tool":
            return ProviderResponse(kind="tool_call", tool_name="ot_capability_ping", tool_args={})
        ping = ToolCallRequest(tool_name="ot_capability_ping", tool_args={"ok": True})
        if self._behavior == "tool_list":
            # kind=message but a populated tool_calls list (the parse shape some providers emit).
            return ProviderResponse(kind="message", content="", tool_calls=[ping])
        if self._behavior == "preamble":
            # A tool call accompanied by a text preamble must still count as supported.
            return ProviderResponse(
                kind="tool_call",
                content="Sure, calling it:",
                tool_name="ot_capability_ping",
                tool_args={"ok": True},
                tool_calls=[ping],
            )
        return ProviderResponse(kind="message", content="Sure, I will call it.")

    def respond(self, messages, tools=None, **kwargs) -> ProviderResponse:
        return self.generate(messages, tools)


# --- probe_tool_calling -------------------------------------------------------


def test_probe_confirms_tool_call() -> None:
    assert probe_tool_calling(_Provider("openai", "tool")) == (True, "")


def test_probe_confirms_tool_call_via_list() -> None:
    # kind=message but a populated tool_calls list still counts as a tool call.
    assert probe_tool_calling(_Provider("openai", "tool_list")) == (True, "")


def test_probe_confirms_tool_call_with_text_preamble() -> None:
    assert probe_tool_calling(_Provider("openai", "preamble")) == (True, "")


def test_probe_text_reply_is_inconclusive_not_false() -> None:
    # A text reply must NOT be a definitive negative (tool_choice is not enforceable),
    # so a tool-capable model is never refused on one unforced sample.
    ok, detail = probe_tool_calling(_Provider("openai", "text"))
    assert ok is None
    assert "tool calling" in detail.lower()


def test_probe_inconclusive_on_error() -> None:
    ok, detail = probe_tool_calling(_Provider("openai", "error"))
    assert ok is None
    assert "probe" in detail.lower() or "failed" in detail.lower()


# --- _ollama_reports_tools (real /api/show parsing) ---------------------------


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, payload=None, exc: Exception | None = None):
    class _Resp:
        def __init__(self, body: bytes) -> None:
            self._body = body

        def read(self) -> bytes:
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *a: object) -> bool:
            return False

    def _open(req, timeout=None):
        if exc is not None:
            raise exc
        return _Resp(json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", _open)


def test_ollama_reports_tools_present(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, {"capabilities": ["completion", "tools"]})
    assert _ollama_reports_tools("http://h", "m") == (True, "")


def test_ollama_reports_no_tools_is_definitive_false(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_urlopen(monkeypatch, {"capabilities": ["completion", "insert"]})
    ok, detail = _ollama_reports_tools("http://h", "m")
    assert ok is False
    assert "m" in detail and "completion" in detail  # actionable: names model + caps


def test_ollama_no_capabilities_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    for payload in ({}, {"capabilities": []}, {"capabilities": "nope"}):
        _patch_urlopen(monkeypatch, payload)
        assert _ollama_reports_tools("http://h", "m") == (None, "")


def test_ollama_http_error_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    _patch_urlopen(monkeypatch, exc=urllib.error.URLError("refused"))
    assert _ollama_reports_tools("http://h", "m") == (None, "")


# --- provider_supports_tool_calling ------------------------------------------


def test_mock_provider_supported_without_probe() -> None:
    from opentorus.providers.mock_provider import MockProvider

    assert provider_supports_tool_calling(MockProvider()) == (True, "")


def test_none_provider_is_unsupported() -> None:
    ok, detail = provider_supports_tool_calling(None)
    assert ok is False
    assert "no model provider" in detail.lower()


def test_allow_probe_false_skips_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    p = _Provider("openai", "error")  # generate would raise if probed
    ok, detail = provider_supports_tool_calling(p, allow_probe=False)
    assert ok is None and detail == ""


def test_ollama_no_tools_skips_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentorus.providers.tool_support as ts

    monkeypatch.setattr(ts, "_ollama_reports_tools", lambda host, model: (False, "no tools X"))

    def _boom(_p, **k):
        raise AssertionError("probe must not run when /api/show is authoritative")

    monkeypatch.setattr(ts, "probe_tool_calling", _boom)
    ok, detail = provider_supports_tool_calling(_Provider("ollama", "tool"))
    assert ok is False and "X" in detail


def test_ollama_inconclusive_falls_back_to_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentorus.providers.tool_support as ts

    monkeypatch.setattr(ts, "_ollama_reports_tools", lambda host, model: (None, ""))
    assert provider_supports_tool_calling(_Provider("ollama", "tool")) == (True, "")


# --- require_tool_calling_provider -------------------------------------------


def test_require_passes_tool_capable() -> None:
    require_tool_calling_provider(_Provider("openai", "tool"))  # must not raise


def test_require_warns_but_proceeds_on_inconclusive_text() -> None:
    warnings: list[str] = []
    require_tool_calling_provider(_Provider("openai", "text"), warn=warnings.append)
    assert warnings and "tool calling" in warnings[0].lower()


def test_require_inconclusive_default_warn_none_does_not_crash() -> None:
    require_tool_calling_provider(_Provider("openai", "error"))  # warn defaults to None


def test_require_refuses_ollama_authoritative_no(monkeypatch: pytest.MonkeyPatch) -> None:
    import opentorus.providers.tool_support as ts

    monkeypatch.setattr(ts, "_ollama_reports_tools", lambda host, model: (False, "no tools cap"))
    with pytest.raises(OpenTorusError, match="does not support tool calling"):
        require_tool_calling_provider(_Provider("ollama", "text"))


def test_require_none_provider_raises_without_attribute_error() -> None:
    with pytest.raises(OpenTorusError, match="does not support tool calling"):
        require_tool_calling_provider(None)


def test_require_skipped_when_verify_disabled() -> None:
    import opentorus.providers.tool_support as ts

    p = _Provider("ollama", "text")
    p.config.model.verify_tool_calling = False
    # Even an authoritative no must be skipped when verification is disabled.
    ts._ollama_reports_tools = lambda host, model: (False, "x")  # type: ignore[assignment]
    require_tool_calling_provider(p, p.config)  # must not raise


# --- CLI-level wiring ---------------------------------------------------------


def test_cli_run_refuses_tool_incapable_model(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0

    # An Ollama model that authoritatively lacks tools must be refused before any loop work.
    import opentorus.providers.tool_support as ts

    monkeypatch.setattr(ts, "_ollama_reports_tools", lambda host, model: (False, "no tools cap"))
    monkeypatch.setattr(
        "opentorus.providers.registry.get_provider", lambda config: _Provider("ollama", "text")
    )
    result = runner.invoke(app, ["run", "do something"])
    assert result.exit_code != 0
    assert "tool calling" in result.output.lower()
