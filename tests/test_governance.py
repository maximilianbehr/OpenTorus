"""Tests for governance: DLP, budgets, and model routing (Milestone 75).

Fully offline. DLP fails closed, budget breaches stop cleanly, and routing is
policy-driven and recorded.
"""

from __future__ import annotations

import pytest

from opentorus.config import default_config
from opentorus.governance import (
    BudgetExceeded,
    DlpBlocked,
    assert_egress_safe,
    assert_within_budget,
    breached_budgets,
    budget_alerts,
    dlp_check,
    route_model,
    scan_secrets,
)
from opentorus.usage import UsageRecord, record_usage


def _ot(tmp_path):  # noqa: ANN001
    ot = tmp_path / ".opentorus"
    ot.mkdir()
    return ot


# --- DLP --------------------------------------------------------------------


def test_scan_secrets_detects_common_tokens() -> None:
    text = "here is my key sk-ABCDEFGHIJKLMNOPQRSTUVWX and an aws AKIA1234567890ABCD56"
    findings = scan_secrets(text)
    kinds = {f.kind for f in findings}
    assert "openai_key" in kinds
    assert "aws_access_key" in kinds
    # Excerpts are redacted, never the raw secret.
    assert all("redacted" in f.excerpt for f in findings)


def test_dlp_blocks_payload_with_secret() -> None:
    result = dlp_check("token=supersecretvalue123")
    assert result.allowed is False
    assert "Blocked pre-egress" in result.reason
    with pytest.raises(DlpBlocked):
        assert_egress_safe("password = hunter2trustno1")


def test_dlp_allows_clean_payload() -> None:
    clean = "Summarize the convergence proof for the spectral gap bound."
    assert dlp_check(clean, scan_pii=False).allowed is True
    assert_egress_safe(clean, scan_pii=False)  # does not raise


def test_dlp_respects_disabled_config() -> None:
    config = default_config()
    config.governance.dlp = False
    # With DLP disabled the guard is a no-op even on a secret.
    assert_egress_safe("token=supersecretvalue123", config)


def test_egress_guard_screens_payload(tmp_path) -> None:  # noqa: ANN001
    from opentorus.research.egress import EgressGuard

    guard = EgressGuard("ask")
    with pytest.raises(DlpBlocked):
        guard.screen_payload("api_key=abcdef123456")
    guard_off = EgressGuard("ask", dlp=False)
    guard_off.screen_payload("api_key=abcdef123456")  # no-op


# --- Budgets ----------------------------------------------------------------


def _spend(ot, provider, model, cost, tokens):  # noqa: ANN001
    record_usage(
        ot,
        UsageRecord(
            provider=provider,
            model=model,
            prompt_tokens=tokens,
            completion_tokens=0,
            cost_usd=cost,
        ),
    )


def test_budget_breach_alerts_and_stops(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    config.governance.budgets.cost_budget_usd = 1.0
    config.governance.budgets.token_budget = 1000

    _spend(ot, "openai", "gpt-4o", 0.4, 300)
    assert breached_budgets(ot, config) == []  # under budget
    assert_within_budget(ot, config)  # does not raise

    _spend(ot, "openai", "gpt-4o", 0.8, 800)  # now total 1.2 USD, 1100 tokens
    breached = breached_budgets(ot, config)
    metrics = {a.metric for a in breached}
    assert metrics == {"cost_usd", "tokens"}
    with pytest.raises(BudgetExceeded):
        assert_within_budget(ot, config)


def test_per_provider_budget(tmp_path) -> None:  # noqa: ANN001
    ot = _ot(tmp_path)
    config = default_config()
    config.governance.budgets.per_provider_usd = {"openai": 0.5}
    _spend(ot, "openai", "gpt-4o", 0.6, 100)
    _spend(ot, "anthropic", "claude-3-opus", 5.0, 100)
    breached = breached_budgets(ot, config)
    assert [a.scope for a in breached] == ["openai"]  # only the capped provider
    alerts = budget_alerts(ot, config)
    assert any("openai" in a.message for a in alerts)


# --- Routing ----------------------------------------------------------------


def test_routing_disabled_uses_default_model() -> None:
    config = default_config()
    config.model.name = "base-model"
    decision = route_model(config, "proof")
    assert decision.model == "base-model"
    assert "disabled" in decision.rationale


def test_routing_selects_model_per_task_class() -> None:
    config = default_config()
    config.model.name = "base-model"
    config.governance.routing.enabled = True
    config.governance.routing.task_models = {
        "narration": "cheap-model",
        "proof": "strong-model",
        "default": "mid-model",
    }
    assert route_model(config, "narration").model == "cheap-model"
    assert route_model(config, "proof").model == "strong-model"
    assert route_model(config, "planning").model == "mid-model"  # falls back to default
    assert route_model(config, "narration").task_class == "narration"


# --- Campaign-scoped budgets ---------------------------------------------------


def test_campaign_scoped_budget_breach(tmp_path) -> None:  # noqa: ANN001
    # A campaign's workers run under many session ids; the campaign id is the axis
    # that makes a campaign budget non-vacuous. Spend outside the campaign must not
    # count against it, and the campaign's own spend must.
    ot = _ot(tmp_path)
    config = default_config()
    config.governance.budgets.cost_budget_usd = 1.0
    record_usage(
        ot,
        UsageRecord(session_id="s1", provider="openai", model="gpt-4o", cost_usd=0.9),
    )  # unattributed
    record_usage(
        ot,
        UsageRecord(
            session_id="s2",
            provider="openai",
            model="gpt-4o",
            cost_usd=0.4,
            campaign_id="CAMPAIGN-0001",
        ),
    )
    record_usage(
        ot,
        UsageRecord(
            session_id="s3",
            provider="openai",
            model="gpt-4o",
            cost_usd=0.4,
            campaign_id="CAMPAIGN-0001",
        ),
    )
    # Workspace-wide: 1.7 >= 1.0 → breached.
    assert breached_budgets(ot, config)
    # Campaign-scoped: 0.8 < 1.0 → within budget, across two session ids.
    assert breached_budgets(ot, config, campaign_id="CAMPAIGN-0001") == []
    assert_within_budget(ot, config, campaign_id="CAMPAIGN-0001")  # does not raise
    alerts = budget_alerts(ot, config, campaign_id="CAMPAIGN-0001")
    assert [a.spent for a in alerts] == [0.8]
    record_usage(
        ot,
        UsageRecord(
            session_id="s4",
            provider="openai",
            model="gpt-4o",
            cost_usd=0.3,
            campaign_id="CAMPAIGN-0001",
        ),
    )
    with pytest.raises(BudgetExceeded):
        assert_within_budget(ot, config, campaign_id="CAMPAIGN-0001")
    # Another campaign is unaffected.
    assert breached_budgets(ot, config, campaign_id="CAMPAIGN-0002") == []


def test_valid_task_classes_cover_new_and_legacy_names() -> None:
    from opentorus.governance import VALID_TASK_CLASSES

    for name in ("planning", "narration", "proof", "critique", "default"):
        assert name in VALID_TASK_CLASSES
    for name in ("proof_development", "campaign_strategy", "final_synthesis"):
        assert name in VALID_TASK_CLASSES


# --- an unpriced model must not read as $0 spent ---------------------------------------------


def test_glm_on_mistral_is_priced() -> None:
    """The model this surfaced on: it must cost something, not silently nothing."""
    from opentorus.usage import cost_known, estimate_cost

    assert cost_known("mistral", "zai-glm-5-2") is True
    cost = estimate_cost("mistral", "zai-glm-5-2", 1_000_000, 100_000)
    assert cost == pytest.approx(1.40 + 0.44)


def _ledger(tmp_path, *records):  # noqa: ANN001
    """A workspace directory whose usage ledger holds exactly these records."""
    ot = _ot(tmp_path)
    for record in records:
        record_usage(ot, record)
    return ot


def test_cost_budget_says_so_when_it_cannot_bind(tmp_path) -> None:  # noqa: ANN001
    """A cap the ledger cannot measure must announce itself, not report a calm $0.

    An unpriced call contributes 0.0 to cost_usd, so `cost_budget_usd` would sit at
    "$0 / $50" forever while real money is spent.
    """
    from opentorus.governance import budget_alerts
    from opentorus.usage import UsageRecord

    config = default_config()
    config.governance.budgets.cost_budget_usd = 50.0
    ot = _ledger(
        tmp_path,
        UsageRecord(
            provider="openai",
            model="some-unlisted-cloud-model",
            prompt_tokens=2_000_000,
            completion_tokens=50_000,
            cost_usd=0.0,
            cost_known=False,
        ),
    )
    notes = [a.note for a in budget_alerts(ot, config) if a.note]
    assert notes, "an unmeasurable cap must be reported"
    assert "cannot bind" in notes[0]
    assert "some-unlisted-cloud-model" in notes[0]
    assert "token_budget" in notes[0], "it must point at the cap that does hold"


def test_a_priced_run_gets_no_such_warning(tmp_path) -> None:  # noqa: ANN001
    from opentorus.governance import budget_alerts
    from opentorus.usage import UsageRecord

    config = default_config()
    config.governance.budgets.cost_budget_usd = 50.0
    ot = _ledger(
        tmp_path,
        UsageRecord(
            provider="openai",
            model="gpt-4o",
            prompt_tokens=1000,
            completion_tokens=100,
            cost_usd=0.0035,
            cost_known=True,
        ),
    )
    assert [a.note for a in budget_alerts(ot, config) if a.note] == []
