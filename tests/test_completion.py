"""Tests for CLI shell-completion helpers."""

from __future__ import annotations

from opentorus.completion import (
    complete_config_key,
    complete_config_value,
    complete_shell_name,
    completion_script,
    dotted_config_keys,
)
from opentorus.config import Config


class _FakeCtx:
    params: dict


def test_dotted_config_keys_includes_agent_style() -> None:
    keys = dotted_config_keys(Config)
    assert "agent.style" in keys
    assert "model.provider" in keys


def test_complete_config_key_prefix() -> None:
    ctx = _FakeCtx()
    ctx.params = {}
    matches = complete_config_key(ctx, "agent.")
    assert "agent.style" in matches
    assert all(m.startswith("agent.") for m in matches)


def test_complete_config_value_for_style() -> None:
    ctx = _FakeCtx()
    ctx.params = {"key": "agent.style"}
    matches = complete_config_value(ctx, "aut")
    assert matches == ["autonomous"]


def test_complete_shell_name() -> None:
    ctx = _FakeCtx()
    ctx.params = {}
    assert "zsh" in complete_shell_name(ctx, "")


def test_completion_script_zsh() -> None:
    script = completion_script("zsh")
    assert "#compdef opentorus" in script
    assert "_OPENTORUS_COMPLETE" in script


def test_dotted_config_keys_excludes_list_model_subkeys() -> None:
    # tools.mcp is list[McpServerConfig]; its element fields are not settable via
    # `config set`, so they must not be advertised by tab-completion.
    from opentorus.completion import dotted_config_keys
    from opentorus.config import Config

    keys = dotted_config_keys(Config)
    assert "model.name" in keys
    assert "tools.verifiers.lean" in keys
    assert not any(k.startswith("tools.mcp.") for k in keys)
