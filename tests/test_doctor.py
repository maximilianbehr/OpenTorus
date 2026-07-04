"""Tests for ``opentorus doctor`` health checks."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.doctor import run_doctor
from opentorus.workspace import init_workspace, workspace_dir


def test_doctor_ok_on_fresh_workspace(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.model.provider = "mock"
    checks = run_doctor(tmp_path, ot, config)
    names = {c.name for c in checks}
    assert "workspace" in names
    assert "config" in names
    assert "tools" in names
    assert all(c.ok for c in checks if c.name != "quality")


def test_doctor_probe_times_out_instead_of_hanging(tmp_path: Path, monkeypatch) -> None:
    # Provider SDKs default to multi-minute read timeouts; an accept-then-stall
    # endpoint must not hang the diagnostics command, and the timeout must not
    # swallow the remaining checks.
    import time

    import opentorus.doctor as doctor_mod
    import opentorus.providers.tool_support as tool_support

    monkeypatch.setattr(doctor_mod, "_PROBE_TIMEOUT_SECONDS", 0.05)
    monkeypatch.setattr(
        tool_support, "provider_supports_tool_calling", lambda *a, **k: time.sleep(5)
    )
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.model.provider = "openai"
    config.model.name = "gpt-4o-mini"
    start = time.monotonic()
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert time.monotonic() - start < 3
    assert not checks["model"].ok
    assert "timed out" in checks["model"].detail
    assert "tools" in checks  # later checks still ran


def test_doctor_flags_provider_that_cannot_run(tmp_path: Path, monkeypatch) -> None:
    # A green "model" check for a provider with no API key sends the user's first
    # real run into a failure doctor said could not happen; doctor must run the
    # same probe `prove` uses and surface the actionable cause.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.model.provider = "openai"
    config.model.name = "gpt-4o-mini"
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert not checks["model"].ok
    assert "Next action:" in checks["model"].detail
