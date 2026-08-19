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
    # Routing / backend / state checks are unconditional (informational when absent).
    for name in (
        "profiles",
        "routes",
        "credentials",
        "formal-systems",
        "dashboard",
        "paper-parsing",
        "dossier-state",
        "version",
    ):
        assert name in names, name
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


def test_doctor_routes_flag_unknown_profile_only(tmp_path: Path) -> None:
    # A route naming an unknown profile is a misconfiguration → ok=False with the
    # `config set` note; a valid route table stays green.
    from opentorus.config import ModelProfile

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.models.profiles = {"local": ModelProfile(provider="ollama", name="qwen")}
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["local", "ghost"]}
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert not checks["routes"].ok
    assert "ghost" in checks["routes"].detail
    assert "config set" in checks["routes"].detail
    assert checks["profiles"].ok
    routes = checks["routes"].data["routes"]
    assert isinstance(routes, list)
    narration = next(r for r in routes if r["task_class"] == "narration")
    assert narration["candidates"] == ["local", "ghost", "default"]
    assert narration["first_eligible"] == "local"

    config.governance.routing.task_routes = {"narration": ["local"]}
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert checks["routes"].ok
    assert checks["profiles"].ok


def test_doctor_capabilities_adds_tables_and_fallback(tmp_path: Path) -> None:
    from opentorus.config import ModelProfile

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.models.profiles = {"local": ModelProfile(provider="ollama", name="qwen")}
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["local"]}
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config, capabilities=True)}
    assert "capabilities:" in checks["profiles"].detail
    assert "fallback available" in checks["routes"].detail
    routes = checks["routes"].data["routes"]
    assert isinstance(routes, list)
    narration = next(r for r in routes if r["task_class"] == "narration")
    assert narration["fallback_ok"] is True  # 'default' backs 'local'
    profiles = checks["profiles"].data["profiles"]
    assert isinstance(profiles, list)
    local = next(p for p in profiles if p["name"] == "local")
    assert "local_only" in local["capabilities"]
    assert "streaming" in local["capabilities"]
    assert "tool_calling" not in local["capabilities"]  # undeclared on Ollama


def test_doctor_never_prints_secret_values(tmp_path: Path, monkeypatch) -> None:
    from opentorus.config import ModelProfile

    secret = "sk-doctor-must-not-print-this-0123456789"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.models.profiles = {"cloud": ModelProfile(provider="openai", name="gpt-x")}
    checks = run_doctor(tmp_path, ot, config, capabilities=True)
    blob = repr([(c.name, c.detail, c.data) for c in checks])
    assert secret not in blob
    by_name = {c.name: c for c in checks}
    assert "OPENAI_API_KEY set" in by_name["profiles"].detail
    assert by_name["credentials"].ok
    assert "OPENAI_API_KEY" in by_name["credentials"].detail


def test_doctor_credentials_missing_for_routed_cloud_profile(tmp_path: Path, monkeypatch) -> None:
    from opentorus.config import ModelProfile

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.models.profiles = {"cloud": ModelProfile(provider="anthropic", name="claude-x")}
    # Declared but unrouted: informational only.
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert checks["credentials"].ok
    assert "ANTHROPIC_API_KEY" in checks["credentials"].detail
    # Routed: a missing variable is a real misconfiguration (name only, never a value).
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["cloud"]}
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert not checks["credentials"].ok
    assert "missing: ANTHROPIC_API_KEY" in checks["credentials"].detail


def test_doctor_informational_checks_are_ok_when_backends_absent(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    checks = {c.name: c for c in run_doctor(tmp_path, ot, default_config())}
    assert checks["formal-systems"].ok
    assert checks["dashboard"].ok
    assert checks["paper-parsing"].ok
    assert checks["dossier-state"].ok
    assert checks["dossier-state"].data["problems"] == 0
    assert checks["version"].ok
    from opentorus import __version__

    assert __version__ in checks["version"].detail
    assert checks["profiles"].ok
    assert "default (default)=mock/mock-default" in checks["profiles"].detail
    assert checks["routes"].ok
    assert "routing disabled" in checks["routes"].detail


def test_doctor_json_cli(tmp_path: Path, monkeypatch) -> None:
    import json

    from typer.testing import CliRunner

    from opentorus.cli import app

    monkeypatch.setenv("OPENAI_API_KEY", "sk-not-for-output-abcdefghijklmnop")
    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["doctor", "--json"])
    assert result.exit_code in (0, 1), result.output  # 1 only when e.g. pytest is off PATH
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    names = {entry["name"] for entry in payload}
    assert {"profiles", "routes", "credentials", "version", "dossier-state"} <= names
    for entry in payload:
        assert set(entry) >= {"name", "ok", "detail", "data"}
    assert "sk-not-for-output" not in result.stdout
    failing = [e["name"] for e in payload if not e["ok"]]
    assert failing in ([], ["quality"])

    result = runner.invoke(app, ["doctor", "--capabilities", "--json"])
    payload = json.loads(result.stdout)
    routes = next(e for e in payload if e["name"] == "routes")
    assert all("fallback_ok" in r for r in routes["data"]["routes"])


def test_doctor_probe_implies_capabilities(tmp_path: Path, monkeypatch) -> None:
    """``doctor --probe`` without ``--capabilities`` used to do nothing at all; a probe
    now always shows the capability tables it fills in (mock profiles are not probed)."""
    from opentorus import doctor as doctor_module

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    probed: list[dict] = []

    def _fake_probe(_ot, _config, profiles):  # noqa: ANN001, ANN202
        probed.append(dict(profiles))
        return {name: "probe skipped (test)" for name in profiles}

    monkeypatch.setattr(doctor_module, "_probe_profiles", _fake_probe)
    checks = {c.name: c for c in run_doctor(tmp_path, ot, default_config(), probe=True)}
    assert probed and "default" in probed[0]
    assert "capabilities:" in checks["profiles"].detail
    assert checks["profiles"].data["probe_notes"] == {"default": "probe skipped (test)"}


def test_doctor_flags_an_undefined_default_profile_in_profiles_and_routes(tmp_path: Path) -> None:
    """A typo in ``models.default_profile``: acquire falls back to ``model:`` at run
    time (see the pool tests), but doctor must still say the name does not exist."""
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.models.default_profile = "typo"
    checks = {c.name: c for c in run_doctor(tmp_path, ot, config)}
    assert not checks["profiles"].ok
    assert "does not exist" in checks["profiles"].detail
    assert not checks["routes"].ok
    assert "typo" in checks["routes"].detail
    narration = next(r for r in checks["routes"].data["routes"] if r["task_class"] == "narration")
    assert narration["candidates"] == ["typo", "default"]
    assert narration["first_eligible"] == "default"
