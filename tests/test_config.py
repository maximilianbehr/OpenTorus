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


def test_default_template_declares_campaign_and_models_paths() -> None:
    # The leaf-name guard above cannot tell `campaign.max_steps` from `agent.max_steps`;
    # pin the dotted paths of the new sections so a template drift is caught by name.
    raw = yaml.safe_load(default_config_yaml())

    def get(path: str) -> object:
        node = raw
        for part in path.split("."):
            assert isinstance(node, dict) and part in node, path
            node = node[part]
        return node

    assert get("models.default_profile") is None
    assert get("models.profiles") == {}
    assert get("governance.routing.task_routes") == {}
    assert get("governance.routing.task_models") == {}
    campaign = default_config().campaign.model_dump(mode="json")
    for key, value in campaign.items():
        if key == "scheduler_weights":
            continue
        assert get(f"campaign.{key}") == value, key
    for key, value in campaign["scheduler_weights"].items():
        assert get(f"campaign.scheduler_weights.{key}") == value, key
    assert get("campaign.default_mode") == "exploration"
    assert get("campaign.max_parallel_workers") == 1
    assert get("campaign.max_steps") == 50
    assert get("campaign.max_wall_seconds") == 0
    assert get("campaign.token_budget") == 0
    assert get("campaign.cost_budget") == 0.0
    text = default_config_yaml()
    assert "0 = not configured / unlimited" in text
    assert "<provider>" in text and "<model-id>" in text  # placeholder example, no real names
    assert "cannot write mappings" in text


def _strip_section(text: str, header: str, indent: int) -> str:
    """Drop a mapping (header line + everything indented deeper) from a config text."""
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        stripped = line.strip()
        own_indent = len(line) - len(line.lstrip())
        if own_indent == indent and stripped.startswith(header):
            skipping = True
            continue
        if skipping:
            if stripped and own_indent <= indent:
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out) + "\n"


def test_write_config_appends_missing_top_level_campaign_section(tmp_path: Path) -> None:
    from opentorus.config import CONFIG_FILENAME, set_dotted, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    old_text = _strip_section(path.read_text(encoding="utf-8"), "campaign:", 0)
    assert "campaign:" not in old_text
    assert "scheduler_weights" not in old_text
    path.write_text(old_text, encoding="utf-8")

    config = set_dotted(load_config(path), "campaign.max_steps", "99")
    config = set_dotted(config, "campaign.default_mode", "survey")
    write_config(path, config)

    text = path.read_text(encoding="utf-8")
    assert "\ncampaign:\n" in text
    assert "  max_steps: 99" in text
    assert "  scheduler_weights:\n    novelty: 1.0" in text  # nested mapping emitted too
    reloaded = load_config(path)
    assert reloaded.campaign.max_steps == 99
    assert reloaded.campaign.default_mode == "survey"
    assert reloaded.model_dump(mode="json") == config.model_dump(mode="json")
    assert "# Operating style:" in text  # comments elsewhere untouched


def test_write_config_appends_missing_nested_scheduler_weights(tmp_path: Path) -> None:
    from opentorus.config import CONFIG_FILENAME, set_dotted, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    old_text = _strip_section(path.read_text(encoding="utf-8"), "scheduler_weights:", 2)
    assert "scheduler_weights" not in old_text
    assert "\ncampaign:\n" in old_text
    path.write_text(old_text, encoding="utf-8")

    config = set_dotted(load_config(path), "campaign.scheduler_weights.novelty", "2.5")
    write_config(path, config)

    text = path.read_text(encoding="utf-8")
    assert text.count("\ncampaign:\n") == 1  # appended inside the existing section
    assert "  scheduler_weights:\n    novelty: 2.5\n    root_impact: 1.0" in text
    reloaded = load_config(path)
    assert reloaded.campaign.scheduler_weights.novelty == 2.5
    assert reloaded.model_dump(mode="json") == config.model_dump(mode="json")


def test_write_config_appends_missing_models_section_with_profiles(tmp_path: Path) -> None:
    from opentorus.config import CONFIG_FILENAME, ModelProfile, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    old_text = _strip_section(path.read_text(encoding="utf-8"), "models:", 0)
    assert "\nmodels:\n" not in old_text
    path.write_text(old_text, encoding="utf-8")

    config = load_config(path)
    config.models.default_profile = "strong"
    config.models.profiles = {
        "strong": ModelProfile(provider="ollama", name="big-model", capabilities=["tool_calling"])
    }
    write_config(path, config)

    text = path.read_text(encoding="utf-8")
    assert "\nmodels:\n" in text
    assert "  default_profile: strong" in text
    assert "  profiles:\n    strong:\n" in text  # container emitted under the missing section
    reloaded = load_config(path)
    assert reloaded.models.default_profile == "strong"
    assert reloaded.models.profiles["strong"].name == "big-model"
    assert reloaded.models.profiles["strong"].capabilities == ["tool_calling"]
    assert reloaded.model_dump(mode="json") == config.model_dump(mode="json")


def test_write_config_expands_an_empty_container_line_into_a_block(tmp_path: Path) -> None:
    # `profiles: {}` on disk with a non-empty in-memory value: the empty line has
    # nothing worth preserving, so it becomes a real mapping block (once — no duplicate
    # key) and the value round-trips instead of being silently dropped.
    from opentorus.config import CONFIG_FILENAME, ModelProfile, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    config = load_config(path)
    config.models.profiles = {"x": ModelProfile(provider="ollama", name="m")}
    config.governance.routing.task_routes = {"proof_development": ["x"]}
    write_config(path, config)
    text = path.read_text(encoding="utf-8")
    assert text.count("profiles:") == text.count("# profiles:") + 1
    assert "  profiles:\n    x:\n      provider: ollama\n" in text
    assert "    task_routes:\n      proof_development:\n      - x\n" in text
    assert "# profiles: a mapping of profile name" in text  # comments above it survive
    reloaded = load_config(path)
    assert reloaded.models.profiles["x"].name == "m"
    assert reloaded.governance.routing.task_routes == {"proof_development": ["x"]}
    assert reloaded.model_dump(mode="json") == config.model_dump(mode="json")


def test_write_config_expands_empty_campaign_block_and_round_trips(tmp_path: Path) -> None:
    # A one-line `campaign: {}` (an old or hand-minimised file) with scalar leaves set in
    # memory: the line becomes a block whose values load back.
    from opentorus.config import CONFIG_FILENAME, set_dotted, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    old_text = _strip_section(path.read_text(encoding="utf-8"), "campaign:", 0)
    old_text = old_text.rstrip("\n") + "\n\ncampaign: {}\n"
    path.write_text(old_text, encoding="utf-8")

    config = set_dotted(load_config(path), "campaign.token_budget", "4321")
    write_config(path, config)
    text = path.read_text(encoding="utf-8")
    assert text.count("\ncampaign:") == 1 and "campaign: {}" not in text
    assert "\ncampaign:\n" in text and "  token_budget: 4321" in text
    reloaded = load_config(path)
    assert reloaded.campaign.token_budget == 4321
    assert reloaded.model_dump(mode="json") == config.model_dump(mode="json")


def test_write_config_warns_about_leaves_under_a_non_empty_flow_container(
    tmp_path: Path, caplog
) -> None:
    # A hand-written non-empty flow mapping is left as written; the values that could
    # not be placed under it are named in a warning rather than lost silently.
    import logging

    from opentorus.config import CONFIG_FILENAME, dropped_leaves, set_dotted, write_config

    init_workspace(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    text = path.read_text(encoding="utf-8")
    text = _strip_section(text, "scheduler_weights:", 2)
    text = text.replace("\ncampaign:\n", "\ncampaign:\n  scheduler_weights: {novelty: 1.0}\n")
    path.write_text(text, encoding="utf-8")

    config = set_dotted(load_config(path), "campaign.scheduler_weights.novelty", "2.5")
    with caplog.at_level(logging.WARNING, logger="opentorus"):
        write_config(path, config)
    rendered = path.read_text(encoding="utf-8")
    assert "scheduler_weights: {novelty: 1.0}" in rendered  # hand-edit surface untouched
    assert dropped_leaves(rendered, config.model_dump(mode="json")) == [
        "campaign.scheduler_weights.novelty"
    ]
    assert any("campaign.scheduler_weights.novelty" in r.message for r in caplog.records)


def test_config_set_round_trips_campaign_key_on_old_file(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app
    from opentorus.config import CONFIG_FILENAME

    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    path = workspace_dir(tmp_path) / CONFIG_FILENAME
    path.write_text(
        _strip_section(path.read_text(encoding="utf-8"), "campaign:", 0), encoding="utf-8"
    )
    result = CliRunner().invoke(app, ["config", "set", "campaign.token_budget", "1234"])
    assert result.exit_code == 0, result.output
    assert load_config(path).campaign.token_budget == 1234
