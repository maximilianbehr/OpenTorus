"""Tests for provider resolution and config mutation (Milestone 11)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.config import CONFIG_FILENAME, default_config, load_config, set_dotted
from opentorus.errors import ConfigError, ProviderError
from opentorus.providers.mock_provider import MockProvider
from opentorus.providers.registry import get_provider
from opentorus.repl import _handle_model, dispatch
from opentorus.workspace import init_workspace, workspace_dir


def test_get_provider_mock_by_default() -> None:
    assert isinstance(get_provider(default_config()), MockProvider)


def test_get_provider_unknown_raises() -> None:
    config = set_dotted(default_config(), "model.provider", "does-not-exist")
    with pytest.raises(ProviderError):
        get_provider(config)


def test_get_provider_real_lazy_without_key_raises() -> None:
    config = set_dotted(default_config(), "model.provider", "openai")
    provider = get_provider(config)  # construction must not require a key
    with pytest.raises(ProviderError):
        provider.generate([])


def test_set_dotted_coerces_types() -> None:
    config = set_dotted(default_config(), "model.temperature", "0.7")
    assert config.model.temperature == pytest.approx(0.7)
    config = set_dotted(config, "privacy.sensitive_file_guard", "false")
    assert config.privacy.sensitive_file_guard is False


def test_set_dotted_unknown_key_raises() -> None:
    with pytest.raises(ConfigError):
        set_dotted(default_config(), "model.nope", "x")


def test_set_dotted_max_steps_allows_inf() -> None:
    import math

    for token in ("inf", "infinity", "unlimited", "-1"):
        config = set_dotted(default_config(), "agent.max_steps", token)
        assert math.isinf(config.agent.max_steps)
    config = set_dotted(default_config(), "agent.max_steps", "1000")
    assert config.agent.max_steps == 1000


def test_repl_model_set_persists(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    out = _handle_model("set provider anthropic", tmp_path)
    assert "anthropic" in out
    config = load_config(workspace_dir(tmp_path) / CONFIG_FILENAME)
    assert config.model.provider == "anthropic"


def test_repl_context_and_model_show(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ctx = dispatch("/context", tmp_path)
    assert any("available tools" in m for m in ctx.messages)
    model = dispatch("/model", tmp_path)
    assert any("provider" in m for m in model.messages)
