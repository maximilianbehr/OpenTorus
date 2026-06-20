"""Tests for the centralized, color-deterministic Console factory."""

from __future__ import annotations

from io import StringIO

import pytest

from opentorus.ux import make_console


def test_make_console_honors_no_color(monkeypatch: pytest.MonkeyPatch) -> None:
    # NO_COLOR must disable color even when a terminal is forced (no-color.org).
    monkeypatch.setenv("FORCE_COLOR", "3")
    monkeypatch.setenv("NO_COLOR", "1")
    console = make_console(file=StringIO(), force_terminal=True)
    assert console.no_color is True


def test_make_console_no_color_strips_color_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    buf = StringIO()
    console = make_console(file=buf, width=80, force_terminal=True)
    console.print("[red]hello[/red]")
    out = buf.getvalue()
    assert "hello" in out
    # The red color SGR codes must be absent under NO_COLOR.
    assert "31m" not in out and "38;2" not in out


def test_make_console_passes_kwargs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("NO_COLOR", "1")
    console = make_console(width=42, record=True)
    assert console.width == 42
