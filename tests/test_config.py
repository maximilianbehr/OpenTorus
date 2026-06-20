"""Tests for workspace configuration loading and the default template."""

from __future__ import annotations

from pathlib import Path

import yaml

from opentorus.config import default_config, default_config_yaml, load_config
from opentorus.workspace import init_workspace, workspace_dir


def test_default_config_prove_min_papers_is_zero() -> None:
    assert default_config().agent.prove_min_papers == 0


def test_default_config_yaml_contains_comments_and_sections() -> None:
    text = default_config_yaml()
    assert text.lstrip().startswith("#")
    for section in ("model:", "agent:", "tools:", "governance:"):
        assert section in text
    assert "mock | openai | anthropic | ollama" in text


def test_default_config_yaml_matches_schema() -> None:
    raw = yaml.safe_load(default_config_yaml())
    loaded = default_config().model_validate(raw)
    assert loaded == default_config()


def test_init_writes_commented_config(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    config_path = workspace_dir(tmp_path) / "config.yaml"
    text = config_path.read_text(encoding="utf-8")
    assert "# OpenTorus workspace configuration" in text
    assert load_config(config_path) == default_config()


def test_config_set_negative_value(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()

    result = runner.invoke(app, ["config", "set", "model.num_predict=-1"])
    assert result.exit_code == 0, result.output
    assert load_config(workspace_dir(tmp_path) / "config.yaml").model.num_predict == -1

    result = runner.invoke(app, ["config", "set", "model.num_ctx", "--value", "-1"])
    assert result.exit_code == 0, result.output
    assert load_config(workspace_dir(tmp_path) / "config.yaml").model.num_ctx == -1


def test_config_set_preserves_inline_documentation(tmp_path: Path) -> None:
    # `opentorus config set` must not strip the per-field documentation, so the
    # user can keep editing config.yaml by hand after changing a value.
    from opentorus.config import CONFIG_FILENAME, set_dotted, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    comments_before = sum(
        1 for ln in path.read_text("utf-8").splitlines() if ln.strip().startswith("#")
    )

    for key, val in [("model.provider", "ollama"), ("agent.max_steps", "inf")]:
        write_config(path, set_dotted(load_config(path), key, val))

    text = path.read_text("utf-8")
    comments_after = sum(1 for ln in text.splitlines() if ln.strip().startswith("#"))
    assert comments_after == comments_before  # no documentation lost
    assert "# Provider: mock | openai | anthropic | ollama" in text  # field doc intact
    assert "  provider: ollama" in text  # value updated in place
    assert "- docker" in text  # list containers preserved
    cfg = load_config(path)
    assert cfg.model.provider == "ollama"
    import math

    assert math.isinf(cfg.agent.max_steps)
