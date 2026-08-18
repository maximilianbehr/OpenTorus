"""Tests for the provider pool: real per-task routing with an auditable ledger.

Two distinguishable fake providers are registered through the pool's ``factory``
hook (keyed on the profile-derived config), so every assertion is about *which
provider actually answered*, not about a model name in metadata.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from opentorus.agent.session import SessionMessage
from opentorus.config import Config, ModelProfile, default_config
from opentorus.governance import route_model
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.providers.capabilities import ProviderCapability
from opentorus.providers.mock_provider import MockProvider
from opentorus.providers.pool import (
    LEGACY_TASK_ALIASES,
    BudgetContext,
    NoEligibleProviderError,
    ProviderPool,
    RoutingDecisionRecord,
    TaskClass,
    build_pool,
    profile_config,
    read_routing_ledger,
    routing_ledger_path,
)
from opentorus.providers.registry import get_provider, get_provider_for_profile
from opentorus.workspace import init_workspace, workspace_dir


class _Fake(BaseProvider):
    """A canned provider that reports who it is in every answer."""

    def __init__(self, name: str, model_name: str, config: Config) -> None:
        self.name = name  # type: ignore[misc]
        self.model_name = model_name
        self.config = config
        self.calls = 0

    def generate(
        self, messages: list[SessionMessage], tools: list[dict] | None = None
    ) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            kind="message", content=f"answer from {self.name}", model=f"{self.model_name}-v2"
        )


def _factory(cfg: Config) -> BaseProvider:
    # Keyed on the profile-derived config: the pool must build providers through
    # exactly this path so ``get_provider`` semantics (and its lazy imports) hold.
    if cfg.model.name == "model-a":
        return _Fake("fake-a", "model-a", cfg)
    if cfg.model.name == "model-b":
        return _Fake("fake-b", "model-b", cfg)
    return get_provider(cfg)


def _routed_config() -> Config:
    config = default_config()
    config.models.profiles = {
        "a": ModelProfile(
            provider="ollama", name="model-a", capabilities=["tool_calling", "vision"]
        ),
        "b": ModelProfile(provider="ollama", name="model-b", capabilities=["tool_calling"]),
    }
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"proof_development": ["b", "a"]}
    return config


def _fixed_clock() -> datetime:
    return datetime(2026, 1, 1, tzinfo=UTC)


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_routed_task_uses_the_routed_provider_and_records_it(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pool = ProviderPool(_routed_config(), ot_dir=ot, factory=_factory, clock=_fixed_clock)
    lease = pool.acquire(TaskClass.proof_development)
    assert lease.profile_name == "b"
    assert lease.provider.name == "fake-b"
    response = lease.provider.respond([SessionMessage(role="user", content="prove it")])
    assert response.content == "answer from fake-b"
    assert response.model == "model-b-v2"

    ledger = read_routing_ledger(ot)
    assert len(ledger) == 1
    record = ledger[0]
    assert record.decision_id == "RTD-0001"
    assert record.task_class == "proof_development"
    assert record.selected_profile == "b"
    assert record.requested_profile == "b"
    assert record.provider == "ollama"
    assert record.configured_model == "model-b"
    assert record.routing_enabled is True
    assert record.outcome == "selected"
    assert record.fallback_reason is None
    assert lease.decision.decision_id == "RTD-0001"

    # The API's reported model is back-filled as an append-only observation.
    pool.note_actual_model(record.decision_id, response.model)
    assert read_routing_ledger(ot)[0].actual_model == "model-b-v2"
    lines = routing_ledger_path(ot).read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2  # decision + observation, no rewrite


def test_capability_requirement_falls_back_with_reason(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pool = ProviderPool(_routed_config(), ot_dir=ot, factory=_factory)
    lease = pool.acquire(
        TaskClass.proof_development, required_capabilities=frozenset({ProviderCapability.vision})
    )
    assert lease.profile_name == "a"
    assert lease.provider.name == "fake-a"
    decision = lease.decision
    assert decision.requested_profile == "b"
    assert decision.selected_profile == "a"
    assert decision.fallback_reason is not None and "'b' skipped" in decision.fallback_reason
    assert "vision" in decision.fallback_reason
    considered = [(v.profile, v.eligible) for v in decision.candidates_considered]
    assert considered == [("b", False), ("a", True)]
    assert decision.required_capabilities == ["vision"]
    # Persisted identically.
    assert read_routing_ledger(ot)[0].fallback_reason == decision.fallback_reason


def test_no_eligible_provider_raises_and_records_refusal(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pool = ProviderPool(_routed_config(), ot_dir=ot, factory=_factory)
    with pytest.raises(NoEligibleProviderError) as excinfo:
        pool.acquire(
            TaskClass.proof_development,
            required_capabilities=frozenset({ProviderCapability.formalization_support}),
        )
    message = str(excinfo.value)
    assert "b:" in message and "a:" in message and "default:" in message
    assert "formalization_support" in message
    verdicts = excinfo.value.verdicts
    assert [v.profile for v in verdicts] == ["b", "a", "default"]
    assert not any(v.eligible for v in verdicts)
    ledger = read_routing_ledger(ot)
    assert len(ledger) == 1
    assert ledger[0].outcome == "no_eligible_provider"
    assert ledger[0].selected_profile is None
    assert ledger[0].provider is None


def test_legacy_model_only_config_yields_default_profile(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    config = default_config()  # only ``model:``; routing disabled
    pool = ProviderPool(config, ot_dir=ot)
    assert list(pool.profiles()) == ["default"]
    assert pool.default_profile_name() == "default"
    assert pool.candidates(TaskClass.proof_development) == ["default"]
    lease = pool.acquire(TaskClass.narration)
    baseline = get_provider(config)
    assert type(lease.provider) is type(baseline) is MockProvider
    assert lease.provider.model_name == "mock-default"
    assert lease.decision.routing_enabled is False
    assert lease.decision.selected_profile == "default"
    # Disabled routing still leaves an auditable record.
    assert read_routing_ledger(ot)[0].decision_id == "RTD-0001"


def test_disabled_routing_ignores_routes(tmp_path: Path) -> None:
    config = _routed_config()
    config.governance.routing.enabled = False
    pool = ProviderPool(config, factory=_factory)
    assert pool.candidates(TaskClass.proof_development) == ["default"]
    lease = pool.acquire(TaskClass.proof_development)
    assert lease.profile_name == "default"
    assert lease.decision.decision_id.startswith("RTD-mem-")


def test_legacy_task_models_are_honoured_including_default() -> None:
    config = default_config()
    config.model.provider = "ollama"
    config.model.name = "base-model"
    config.governance.routing.enabled = True
    config.governance.routing.task_models = {
        "proof": "strong-model",
        "narration": "cheap-model",
        "default": "mid-model",
    }
    pool = ProviderPool(config)
    # Legacy alias and canonical class both resolve to the same synthesised profile.
    assert pool.candidates("proof") == ["default@strong-model", "default@mid-model", "default"]
    assert pool.candidates(TaskClass.proof_development) == [
        "default@strong-model",
        "default@mid-model",
        "default",
    ]
    assert pool.candidates(TaskClass.narration) == [
        "default@cheap-model",
        "default@mid-model",
        "default",
    ]
    # Unmapped class → the legacy "default" entry, then the default profile.
    assert pool.candidates(TaskClass.scheduling) == ["default@mid-model", "default"]
    synthesised = pool.profiles()["default@strong-model"]
    assert synthesised.provider == "ollama"
    assert synthesised.name == "strong-model"
    assert synthesised.timeout_seconds == config.model.timeout_seconds
    assert pool.profile_source("default@strong-model") == "task_models"

    seen: list[str] = []

    def factory(cfg: Config) -> BaseProvider:
        seen.append(cfg.model.name)
        return _Fake("fake", cfg.model.name, cfg)

    lease = ProviderPool(config, factory=factory).acquire(TaskClass.proof_development)
    assert seen == ["strong-model"]
    assert lease.provider.model_name == "strong-model"


def test_candidate_order_task_routes_before_legacy_before_default() -> None:
    config = _routed_config()
    config.governance.routing.task_routes["default"] = ["a"]
    config.governance.routing.task_models = {"proof_development": "legacy-x", "default": "legacy-y"}
    pool = ProviderPool(config)
    assert pool.candidates(TaskClass.proof_development) == [
        "b",
        "a",
        "default@legacy-x",
        "default@legacy-y",
        "default",
    ]
    # A class with no explicit route: task_routes["default"] first, then legacy default.
    assert pool.candidates(TaskClass.narration) == ["a", "default@legacy-y", "default"]
    assert pool.route_source(TaskClass.narration) == "task_routes.default"


def test_provider_instances_are_cached_per_profile() -> None:
    pool = ProviderPool(_routed_config(), factory=_factory)
    first = pool.acquire(TaskClass.proof_development)
    second = pool.acquire(TaskClass.proof_development)
    assert first.provider is second.provider
    other = pool.acquire(
        TaskClass.proof_development, required_capabilities=frozenset({ProviderCapability.vision})
    )
    assert other.provider is not first.provider
    # Distinct decisions even for the same cached instance.
    assert first.decision.decision_id != second.decision.decision_id


def test_local_only_requirement_excludes_cloud_profiles() -> None:
    config = default_config()
    config.models.profiles = {
        "cloud": ModelProfile(provider="openai", name="model-a"),
        "local": ModelProfile(provider="ollama", name="model-b"),
    }
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["cloud", "local"]}
    pool = ProviderPool(config, factory=_factory)
    lease = pool.acquire(
        TaskClass.narration, budget_context=BudgetContext(local_only_required=True)
    )
    assert lease.profile_name == "local"
    assert lease.decision.local_only_required is True
    assert lease.decision.candidates_considered[0].eligible is False
    assert "local-only" in lease.decision.candidates_considered[0].reason
    # An explicit ``local_only: true`` override makes a cloud-looking profile eligible.
    config.models.profiles["cloud"].local_only = True
    lease2 = ProviderPool(config, factory=_factory).acquire(
        TaskClass.narration, budget_context=BudgetContext(local_only_required=True)
    )
    assert lease2.profile_name == "cloud"


def test_unknown_profile_in_route_is_skipped_with_reason() -> None:
    config = _routed_config()
    config.governance.routing.task_routes = {"narration": ["missing", "a"]}
    pool = ProviderPool(config, factory=_factory)
    lease = pool.acquire(TaskClass.narration)
    assert lease.profile_name == "a"
    assert lease.decision.candidates_considered[0].reason.startswith("unknown profile")


def test_per_provider_budget_breach_skips_provider(tmp_path: Path) -> None:
    from opentorus.usage import UsageRecord, record_usage

    ot = _ot(tmp_path)
    config = default_config()
    config.models.profiles = {
        "paid": ModelProfile(provider="openai", name="model-a"),
        "free": ModelProfile(provider="ollama", name="model-b"),
    }
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["paid", "free"]}
    config.governance.budgets.per_provider_usd = {"openai": 0.5}
    record_usage(ot, UsageRecord(provider="openai", model="model-a", cost_usd=0.6))
    lease = ProviderPool(config, ot_dir=ot, factory=_factory).acquire(TaskClass.narration)
    assert lease.profile_name == "free"
    assert "budget" in lease.decision.candidates_considered[0].reason


def test_decision_ids_continue_from_the_ledger(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    config = default_config()
    ProviderPool(config, ot_dir=ot).acquire(TaskClass.narration)
    ProviderPool(config, ot_dir=ot).acquire(TaskClass.narration)
    pool = ProviderPool(config, ot_dir=ot)
    pool.acquire(TaskClass.narration)
    pool.acquire(TaskClass.narration)
    ids = [d.decision_id for d in read_routing_ledger(ot)]
    assert ids == ["RTD-0001", "RTD-0002", "RTD-0003", "RTD-0004"]


def test_tags_and_budget_context_are_recorded(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pool = ProviderPool(default_config(), ot_dir=ot)
    lease = pool.acquire(
        TaskClass.final_synthesis,
        budget_context=BudgetContext(campaign_id="CAMPAIGN-0001", branch_id="BRANCH-0002"),
        tags={"session_id": "s-1", "work_item_id": "WI-0003"},
    )
    record = lease.decision
    assert record.campaign_id == "CAMPAIGN-0001"
    assert record.branch_id == "BRANCH-0002"
    assert record.work_item_id == "WI-0003"
    assert record.session_id == "s-1"


def test_profile_config_derives_model_block_only() -> None:
    config = default_config()
    config.agent.max_steps = 7
    profile = ModelProfile(provider="ollama", name="x", capabilities=["vision"], local_only=True)
    derived = profile_config(config, profile)
    assert derived.model.provider == "ollama"
    assert derived.model.name == "x"
    assert derived.agent.max_steps == 7
    assert "capabilities" not in derived.model.model_dump()
    assert config.model.name == "mock-default"  # original untouched


def test_get_provider_for_profile_wrapper() -> None:
    config = default_config()
    provider = get_provider_for_profile(config, "default")
    assert isinstance(provider, MockProvider)
    from opentorus.errors import ProviderError

    with pytest.raises(ProviderError):
        get_provider_for_profile(config, "nope")


def test_build_pool_reads_capability_cache(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pool = build_pool(default_config(), ot)
    assert pool.ot_dir == ot
    assert pool.acquire(TaskClass.narration).profile_name == "default"


def test_describe_reports_names_only(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-never-appear-0123456789")
    config = default_config()
    config.models.profiles = {"cloud": ModelProfile(provider="openai", name="gpt-x")}
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"proof_development": ["cloud", "ghost"]}
    profiles, routes = ProviderPool(config).describe()
    by_name = {p.name: p for p in profiles}
    assert by_name["cloud"].credential_env_var == "OPENAI_API_KEY"
    assert by_name["cloud"].credential_present is True
    assert by_name["default"].is_default is True
    assert "proof_development" in by_name["cloud"].routes_using
    dumped = str([p.model_dump() for p in profiles]) + str([r.model_dump() for r in routes])
    assert "sk-should-never-appear" not in dumped
    proof = next(r for r in routes if r.task_class == "proof_development")
    assert proof.candidates == ["cloud", "ghost", "default"]
    assert proof.first_eligible == "cloud"
    assert proof.fallback_ok is True
    assert "ghost" in proof.note
    assert {r.task_class for r in routes} >= {tc.value for tc in TaskClass}


def test_route_model_compat_strings() -> None:
    config = default_config()
    config.model.name = "base-model"
    assert route_model(config, "proof").rationale == "routing disabled; using model.name"
    config.governance.routing.enabled = True
    config.governance.routing.task_models = {"proof": "strong-model", "default": "mid-model"}
    decision = route_model(config, "proof")
    assert decision.model == "strong-model"
    assert decision.rationale == "routed 'proof' to configured model"
    assert route_model(config, "planning").model == "mid-model"
    config.governance.routing.task_models = {}
    decision = route_model(config, "critique")
    assert decision.model == "base-model"
    assert decision.rationale == "no route for 'critique'; using model.name"
    # New-style routes are reported too.
    config.models.profiles = {"strong": ModelProfile(provider="ollama", name="big")}
    config.governance.routing.task_routes = {"adversarial_critique": ["strong"]}
    assert route_model(config, "critique").model == "big"


def test_task_class_enum_and_aliases() -> None:
    assert len(TaskClass) == 17
    assert TaskClass.default.value == "default"
    assert LEGACY_TASK_ALIASES == {
        "proof": TaskClass.proof_development,
        "critique": TaskClass.adversarial_critique,
        "planning": TaskClass.campaign_strategy,
    }
    from opentorus.governance import VALID_TASK_CLASSES

    assert set(VALID_TASK_CLASSES) >= {tc.value for tc in TaskClass} | set(LEGACY_TASK_ALIASES)
    record = RoutingDecisionRecord(
        decision_id="RTD-0001", task_class="x", created_at=_fixed_clock()
    )
    assert record.outcome == "selected"


def test_budget_alerts_are_read_once_per_acquire(tmp_path: Path, monkeypatch) -> None:
    """Three paid candidates over budget: the usage ledger is parsed once, not per candidate."""
    from opentorus import governance
    from opentorus.usage import UsageRecord, record_usage

    ot = _ot(tmp_path)
    config = default_config()
    config.models.profiles = {
        "p1": ModelProfile(provider="openai", name="model-a"),
        "p2": ModelProfile(provider="openai", name="model-a"),
        "p3": ModelProfile(provider="anthropic", name="model-a"),
        "free": ModelProfile(provider="ollama", name="model-b"),
    }
    config.governance.routing.enabled = True
    config.governance.routing.task_routes = {"narration": ["p1", "p2", "p3", "free"]}
    config.governance.budgets.per_provider_usd = {"openai": 0.5, "anthropic": 0.5}
    record_usage(ot, UsageRecord(provider="openai", model="model-a", cost_usd=0.6))
    record_usage(ot, UsageRecord(provider="anthropic", model="model-a", cost_usd=0.6))
    calls = {"n": 0}
    original = governance.budget_alerts

    def _counting(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        calls["n"] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(governance, "budget_alerts", _counting)
    lease = ProviderPool(config, ot_dir=ot, factory=_factory).acquire(TaskClass.narration)
    assert lease.profile_name == "free"
    assert calls["n"] == 1
    reasons = [v.reason for v in lease.decision.candidates_considered[:3]]
    assert all("per-provider budget breached" in r for r in reasons)


def test_unknown_default_profile_falls_back_to_the_implicit_default(tmp_path: Path) -> None:
    """A typo in ``models.default_profile`` must not break every command: acquire falls
    back to the ``model:`` block and says so in the recorded fallback reason."""
    ot = _ot(tmp_path)
    config = default_config()
    config.models.default_profile = "typo"
    pool = ProviderPool(config, ot_dir=ot)
    assert pool.default_profile_defined() is False
    assert pool.candidates(TaskClass.narration) == ["typo", "default"]
    lease = pool.acquire(TaskClass.narration)
    assert lease.profile_name == "default"
    assert isinstance(lease.provider, MockProvider)
    assert lease.decision.fallback_reason is not None
    assert lease.decision.fallback_reason.startswith(
        "models.default_profile 'typo' is not defined; using the implicit default profile"
    )
    assert lease.decision.candidates_considered[0].profile == "typo"
    assert lease.decision.candidates_considered[0].eligible is False
    # Routing enabled: the same fallback closes the candidate list.
    config.governance.routing.enabled = True
    config.models.profiles = {"a": ModelProfile(provider="ollama", name="model-a")}
    config.governance.routing.task_routes = {"proof_development": ["a"]}
    routed = ProviderPool(config, ot_dir=ot)
    assert routed.candidates(TaskClass.narration) == ["typo", "default"]
    assert routed.candidates(TaskClass.proof_development) == ["a", "typo", "default"]
    # Doctor still flags the undefined name (a fallback is not a fix).
    profiles, routes = routed.describe()
    assert any("does not exist" in p for r in profiles for p in r.problems)
