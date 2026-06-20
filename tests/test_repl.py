"""Tests for the interactive shell dispatch (Milestone 2)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.session import SessionMessage, append_message, read_messages
from opentorus.config import CONFIG_FILENAME, load_config
from opentorus.repl import _maybe_cli_hint, build_banner, complete_repl, dispatch
from opentorus.workspace import init_workspace, workspace_dir


def test_help_returns_text() -> None:
    result = dispatch("/help")
    assert not result.should_exit
    assert any("slash commands" in m.lower() for m in result.messages)


def test_exit_signals_exit() -> None:
    result = dispatch("/exit")
    assert result.should_exit is True


def test_clear_signals_clear() -> None:
    result = dispatch("/clear")
    assert result.should_clear is True


def test_unknown_command_is_reported() -> None:
    result = dispatch("/frobnicate")
    assert not result.should_exit
    assert any("unknown command" in m.lower() for m in result.messages)


def test_status_command(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    result = dispatch("/status", start=tmp_path)
    assert any("Workspace:" in m for m in result.messages)


def test_empty_line_is_noop() -> None:
    result = dispatch("   ")
    assert result.messages == []
    assert not result.should_exit


def test_natural_language_dispatch_is_empty() -> None:
    # Natural-language input is routed to the agent loop in run_repl, not dispatch.
    result = dispatch("inspect this repo")
    assert result.messages == []
    assert not result.should_exit


def test_natural_language_is_not_a_cli_hint() -> None:
    assert _maybe_cli_hint("prove the little theorem", None) is None
    assert _maybe_cli_hint("how is the project doing?", None) is None


def test_bare_opentorus_command_gives_hint() -> None:
    hint = _maybe_cli_hint("opentorus status", None)
    assert hint is not None
    assert "slash commands" in hint
    assert "not sent to the model" in hint


def test_python_module_invocation_is_caught() -> None:
    hint = _maybe_cli_hint("python -m opentorus claims", None)
    assert hint is not None
    assert "/help" in hint


def test_config_set_via_cli_prefix_is_applied(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    hint = _maybe_cli_hint("opentorus config set model.provider ollama", start=tmp_path)
    assert hint is not None
    assert "Set model.provider = ollama" in hint
    config = load_config(workspace_dir(tmp_path) / CONFIG_FILENAME)
    assert config.model.provider == "ollama"


def test_complete_command_prefix() -> None:
    matches = complete_repl("/st", "/st")
    assert "/status" in matches
    assert "/style" in matches
    assert all(m.startswith("/st") for m in matches)


def test_complete_empty_slash_lists_all() -> None:
    matches = complete_repl("/", "/")
    assert "/help" in matches and "/exit" in matches


def test_complete_natural_language_is_empty() -> None:
    assert complete_repl("prove the theorem", "prove") == []


def test_complete_style_values() -> None:
    assert set(complete_repl("/style ", "")) == {"cautious", "normal", "fast", "autonomous"}
    assert complete_repl("/style fa", "fa") == ["fast"]


def test_complete_model_subcommands() -> None:
    assert complete_repl("/model ", "") == ["set"]
    assert "provider" in complete_repl("/model set ", "")
    assert "ollama" in complete_repl("/model set provider ", "")


def test_complete_checkpoint_subcommands() -> None:
    assert set(complete_repl("/checkpoint ", "")) == {"create", "list"}


def test_complete_artifact_ids(tmp_path: Path) -> None:
    from opentorus.research.claims import new_claim

    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    new_claim(base, "Caching reduces p95 latency")
    matches = complete_repl("/evidence ", "", start=tmp_path)
    assert matches == ["CLAIM-0001"]
    matches = complete_repl("/related CLAIM", "CLAIM", start=tmp_path)
    assert "CLAIM-0001" in matches


def test_complete_ids_without_workspace_is_empty(tmp_path: Path) -> None:
    # tmp_path has no .opentorus ancestor, so id completion finds nothing.
    assert complete_repl("/evidence ", "", start=tmp_path) == []


def test_banner_contains_workspace(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    banner = build_banner(tmp_path)
    assert "OpenTorus" in banner
    assert "Project mode:" in banner


def test_session_message_roundtrip(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    append_message(base, SessionMessage(role="user", content="hello"))
    append_message(base, SessionMessage(role="assistant", content="hi"))
    messages = read_messages(base)
    assert [(m.role, m.content) for m in messages] == [
        ("user", "hello"),
        ("assistant", "hi"),
    ]
