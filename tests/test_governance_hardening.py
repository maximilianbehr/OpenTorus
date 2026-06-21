"""Tests for governance/cost/provider hardening (batch 4 of scan fixes)."""

from __future__ import annotations

from pathlib import Path

from opentorus.usage import cost_known, format_usage_line, is_local_provider


def test_unknown_paid_model_is_not_rendered_free() -> None:
    # A paid cloud model with no price entry must not read as "$0 (local)".
    line = format_usage_line(
        provider="anthropic",
        model="claude-future-9",
        prompt_tokens=1000,
        completion_tokens=1000,
        tokens_estimated=False,
    )
    assert "price unknown" in line
    assert "(local)" not in line


def test_local_provider_is_free() -> None:
    assert is_local_provider("ollama")
    line = format_usage_line(
        provider="ollama", model="gpt-oss:120b", prompt_tokens=10, completion_tokens=10
    )
    assert "$0 (local)" in line


def test_known_model_priced() -> None:
    assert cost_known("openai", "gpt-4o")
    line = format_usage_line(
        provider="openai", model="gpt-4o", prompt_tokens=1_000_000, completion_tokens=0
    )
    assert "$2." in line  # 1M input tokens at $2.50/M


def test_egress_budget_reconciles_with_disk(tmp_path: Path) -> None:
    # Two guards sharing one ledger must not undercount: the second sees the first's
    # requests and the shared total is monotone.
    from opentorus.research.egress import EgressGuard

    ledger = tmp_path / "egress.json"

    def _mk() -> EgressGuard:
        return EgressGuard("trusted", daily_request_budget=3, ledger_path=ledger)

    g1 = _mk()
    g1._record("example.com", 0.0)
    g1._record("example.com", 0.0)  # disk count now 2
    g2 = _mk()  # constructed after; loads count=2
    g2._record("example.com", 0.0)  # -> 3
    # g2 is now at the cap; enforcing must raise rather than silently overrun.
    from opentorus.research.egress import EgressBlocked

    raised = False
    try:
        g2._enforce_budget()
    except EgressBlocked:
        raised = True
    assert raised


def test_provider_response_has_truncated_flag() -> None:
    from opentorus.providers.base import ProviderResponse

    r = ProviderResponse(kind="message", content="cut off", truncated=True)
    assert r.truncated is True
    assert ProviderResponse(kind="message").truncated is False
