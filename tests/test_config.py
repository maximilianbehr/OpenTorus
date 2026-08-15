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


def test_prove_gap_fill_max_steps_accepts_unlimited() -> None:
    # Mirrors agent.max_steps: inf / unlimited / -1 mean "no separate gap-fill cap",
    # so a user who sets max_steps inf can also uncap gap-filling.
    import math

    from opentorus.config import default_config, set_dotted

    for token in ("inf", "unlimited", "-1"):
        cfg = set_dotted(default_config(), "agent.prove_gap_fill_max_steps", token)
        assert math.isinf(cfg.agent.prove_gap_fill_max_steps), token
    assert (
        set_dotted(
            default_config(), "agent.prove_gap_fill_max_steps", "500"
        ).agent.prove_gap_fill_max_steps
        == 500
    )
    # Finite values below 1 are still rejected.
    import pytest

    from opentorus.errors import ConfigError

    with pytest.raises(ConfigError):
        set_dotted(default_config(), "agent.prove_gap_fill_max_steps", "0")


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


def _scalar_leaf_paths(data: dict, prefix: tuple[str, ...] = ()) -> list[tuple[str, ...]]:
    out: list[tuple[str, ...]] = []
    for key, value in data.items():
        if isinstance(value, dict):
            out.extend(_scalar_leaf_paths(value, prefix + (key,)))
        elif not isinstance(value, list):
            out.append(prefix + (key,))
    return out


def test_default_template_covers_every_scalar_config_field() -> None:
    # Class-closing guard for the silent config-set no-op: a model field without a
    # template line could not be persisted by `opentorus config set` (a real run
    # executed with a campaign gate its driver believed it had enabled). Every new
    # Config field MUST ship a default_config.yaml line — this test fails otherwise.
    import re

    template = default_config_yaml()
    data = default_config().model_dump(mode="json")
    missing = [
        ".".join(path)
        for path in _scalar_leaf_paths(data)
        if not re.search(rf"^\s*{re.escape(path[-1])}:", template, re.M)
    ]
    assert missing == []


def test_write_config_appends_fields_missing_from_old_files(tmp_path: Path) -> None:
    # Old workspace configs predate newer fields. write_config must append such
    # fields into their existing section instead of silently dropping the values.
    from opentorus.config import CONFIG_FILENAME, set_dotted, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    # Simulate an old file: strip the newer field lines from the on-disk config.
    newer = [
        "prove_require_instance_work",
        "prove_referee_reopens_gaps",
        "max_tokens",
        "interval",
        "sympy",
    ]
    old_text = "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not any(line.strip().startswith(f"{k}:") for k in newer)
    )
    path.write_text(old_text + "\n", encoding="utf-8")

    config = load_config(path)
    config = set_dotted(config, "agent.prove_require_instance_work", "true")
    config = set_dotted(config, "agent.prove_referee_reopens_gaps", "false")
    config = set_dotted(config, "model.max_tokens", "123")
    config = set_dotted(config, "tools.verifiers.interval", "false")
    config = set_dotted(config, "tools.verifiers.sympy", "false")
    write_config(path, config)

    reloaded = load_config(path)
    assert reloaded.model_dump(mode="json") == config.model_dump(mode="json")
    # Comments and untouched values survive the surgical rewrite.
    text = path.read_text(encoding="utf-8")
    assert "# Operating style:" in text
    assert "prove_require_instance_work: true" in text


def test_config_set_cli_fails_loudly_when_not_persisted(tmp_path: Path, monkeypatch) -> None:
    # The CLI must never print green "Set" on the strength of the in-memory update:
    # it re-reads the file and errors if the value did not round-trip.
    from typer.testing import CliRunner

    from opentorus.cli import app
    from opentorus.config import CONFIG_FILENAME

    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["config", "set", "agent.prove_require_instance_work", "true"])
    assert result.exit_code == 0
    assert "prove_require_instance_work: true" in (
        (workspace_dir(tmp_path) / CONFIG_FILENAME).read_text(encoding="utf-8")
    )
