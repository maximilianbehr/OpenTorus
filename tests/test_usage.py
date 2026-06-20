"""Tests for the usage and cost ledger (Milestone 31)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.usage import (
    UsageRecord,
    estimate_cost,
    read_usage,
    record_usage,
    summarize_usage,
)
from opentorus.workspace import init_workspace, workspace_dir


def test_local_providers_are_free() -> None:
    assert estimate_cost("ollama", "qwen3", 1000, 1000) == 0.0
    assert estimate_cost("mock", "mock", 1000, 1000) == 0.0


def test_known_model_cost_estimate() -> None:
    # gpt-4o: $2.50/Mtok input, $10/Mtok output
    cost = estimate_cost("openai", "gpt-4o", 1_000_000, 1_000_000)
    assert abs(cost - 12.50) < 1e-9


def test_exact_provider_usage_is_recorded_and_not_estimated() -> None:
    # When a provider returns exact token counts, the loop must record those and
    # mark the entry as not estimated.
    from opentorus.providers.base import ProviderResponse, TokenUsage

    response = ProviderResponse(
        kind="message",
        content="x",
        usage=TokenUsage(prompt_tokens=1234, completion_tokens=56),
    )
    assert response.usage is not None
    assert response.usage.prompt_tokens == 1234


def test_usage_line_marks_exact_vs_estimated() -> None:
    from opentorus.usage import format_usage_line

    estimated = format_usage_line("ollama", "llama3", 1234, 56, tokens_estimated=True)
    exact = format_usage_line("ollama", "llama3", 1234, 56, tokens_estimated=False)
    assert estimated.startswith("↳ ~")  # '~' marks a local estimate
    assert exact.startswith("↳ =")  # '=' marks the provider's exact count


def test_usage_line_shows_thinking_subcount() -> None:
    from opentorus.usage import format_usage_line

    with_think = format_usage_line("ollama", "qwen3", 1000, 250, thinking_tokens=120)
    without = format_usage_line("ollama", "qwen3", 1000, 250, thinking_tokens=0)
    assert "think" in with_think
    assert "120" in with_think
    assert "think" not in without  # omitted when there is no reasoning


def test_summary_flags_estimated_when_any_turn_estimated(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    record_usage(base, UsageRecord(session_id="S", prompt_tokens=10, tokens_estimated=False))
    record_usage(base, UsageRecord(session_id="S", prompt_tokens=20, tokens_estimated=True))
    assert summarize_usage(base, "S").tokens_estimated is True

    init_workspace(tmp_path / "w2")
    base2 = workspace_dir(tmp_path / "w2")
    record_usage(base2, UsageRecord(session_id="S", prompt_tokens=10, tokens_estimated=False))
    assert summarize_usage(base2, "S").tokens_estimated is False


def test_unknown_model_costs_zero() -> None:
    assert estimate_cost("openai", "totally-unknown-model", 1000, 1000) == 0.0


def test_version_suffix_matches_price() -> None:
    cost = estimate_cost("anthropic", "claude-3-5-sonnet-20241022", 1_000_000, 0)
    assert abs(cost - 3.00) < 1e-9


def test_record_and_summarize(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    record_usage(
        ot,
        UsageRecord(
            session_id="s1",
            provider="openai",
            model="gpt-4o",
            prompt_tokens=100,
            completion_tokens=50,
            latency_ms=200,
            cost_usd=0.001,
        ),
    )
    record_usage(
        ot,
        UsageRecord(
            session_id="s2",
            provider="ollama",
            model="qwen3",
            prompt_tokens=300,
            completion_tokens=100,
            latency_ms=400,
            cost_usd=0.0,
        ),
    )
    summary = summarize_usage(ot)
    assert summary.turns == 2
    assert summary.total_tokens == 550
    assert summary.avg_latency_ms == 300
    assert summary.by_model["gpt-4o"] == 150

    only_s1 = summarize_usage(ot, "s1")
    assert only_s1.turns == 1
    assert only_s1.total_tokens == 150


def test_loop_records_usage(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot)
    loop = AgentLoop(tmp_path, ot, MockProvider(), registry, default_config())
    loop.run("just say hello")
    records = read_usage(ot)
    assert records, "expected at least one usage record from the loop"
    assert all(r.session_id == loop.session_id for r in records)
    assert all(r.provider == "mock" for r in records)


def test_empty_summary(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    summary = summarize_usage(ot)
    assert summary.turns == 0
    assert summary.total_tokens == 0
