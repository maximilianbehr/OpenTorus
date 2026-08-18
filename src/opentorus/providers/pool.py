"""Per-task provider routing with an auditable ledger.

Before this module, ``governance.route_model`` returned a *model name* that nothing
acted on: the provider was built once from ``model:`` and the usage ledger recorded
the configured name. :class:`ProviderPool` makes routing real and honest:

* profiles come from ``models.profiles`` (the ``model:`` block is the implicit
  profile ``default``); routes from ``governance.routing.task_routes`` (ordered
  profile names per task class) with the legacy ``task_models`` still honoured;
* :meth:`ProviderPool.acquire` picks the first *eligible* candidate — known
  profile, required capabilities present, local-only honoured, per-provider budget
  not breached — and builds the provider through the ordinary ``get_provider``
  on a profile-derived config, so a disabled router yields exactly the provider
  ``get_provider(config)`` would;
* **every** acquire appends a :class:`RoutingDecisionRecord` to
  ``.opentorus/usage/routing.jsonl`` (refusals included, as
  ``outcome="no_eligible_provider"``), so a fallback is never silent and a
  campaign can cite which decision produced which artifact.

Provider construction stays lazy and cached per profile; the pool never probes a
model online (capabilities come from the static table, the profile's declared
list, and the doctor's probe cache).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from opentorus.config import Config, ModelConfig, ModelProfile
from opentorus.errors import ProviderError
from opentorus.jsonl import append_jsonl, next_id
from opentorus.providers.base import BaseProvider
from opentorus.providers.capabilities import (
    CREDENTIAL_ENV_VARS,
    CapabilityCache,
    ProviderCapability,
    default_cache_path,
    effective_capabilities,
    parse_capabilities,
    profile_is_local,
)

logger = logging.getLogger("opentorus")

ROUTING_LEDGER_FILENAME = "routing.jsonl"
KNOWN_PROVIDERS: frozenset[str] = frozenset({"mock", "openai", "anthropic", "ollama"})
DEFAULT_PROFILE_NAME = "default"


class TaskClass(StrEnum):
    """What a model call is *for*; the routing key of ``task_routes``."""

    problem_normalization = "problem_normalization"
    campaign_strategy = "campaign_strategy"
    portfolio_deduplication = "portfolio_deduplication"
    scheduling = "scheduling"
    theorem_extraction = "theorem_extraction"
    literature_synthesis = "literature_synthesis"
    proof_development = "proof_development"
    counterexample_search = "counterexample_search"
    symbolic_experiment_design = "symbolic_experiment_design"
    numerical_experiment_design = "numerical_experiment_design"
    code_generation = "code_generation"
    formalization = "formalization"
    adversarial_critique = "adversarial_critique"
    verification_support = "verification_support"
    final_synthesis = "final_synthesis"
    narration = "narration"
    default = "default"


# The pre-campaign task classes (``governance.route_model``) map onto the new ones;
# ``narration`` and ``default`` keep their names.
LEGACY_TASK_ALIASES: dict[str, TaskClass] = {
    "proof": TaskClass.proof_development,
    "critique": TaskClass.adversarial_critique,
    "planning": TaskClass.campaign_strategy,
}


def task_class_lookup_names(task_class: str) -> list[str]:
    """Names to try, in order, when looking a task class up in a route table.

    A legacy name (``proof``) also tries its canonical class, and a canonical class
    also tries its legacy alias, so old ``task_models`` entries keep routing new
    callers and vice versa.
    """
    name = str(task_class)
    names = [name]
    alias = LEGACY_TASK_ALIASES.get(name)
    if alias is not None and alias.value not in names:
        names.append(alias.value)
    for legacy, canonical in LEGACY_TASK_ALIASES.items():
        if canonical.value == name and legacy not in names:
            names.append(legacy)
    return names


class CandidateVerdict(BaseModel):
    profile: str
    eligible: bool
    reason: str


class RoutingDecisionRecord(BaseModel):
    """One routing decision, as persisted in ``usage/routing.jsonl``."""

    decision_id: str
    task_class: str
    requested_profile: str | None = None
    selected_profile: str | None = None
    provider: str | None = None
    configured_model: str | None = None
    actual_model: str | None = None
    required_capabilities: list[str] = Field(default_factory=list)
    candidates_considered: list[CandidateVerdict] = Field(default_factory=list)
    fallback_reason: str | None = None
    routing_enabled: bool = False
    local_only_required: bool = False
    created_at: datetime
    campaign_id: str | None = None
    branch_id: str | None = None
    work_item_id: str | None = None
    session_id: str | None = None
    outcome: Literal["selected", "no_eligible_provider"] = "selected"


class RoutingObservation(BaseModel):
    """Append-only back-fill of the model the API actually reported for a decision."""

    decision_id: str
    actual_model: str
    observed_at: datetime


@dataclass
class ProviderLease:
    provider: BaseProvider
    decision: RoutingDecisionRecord
    profile_name: str
    profile: ModelProfile


@dataclass
class BudgetContext:
    """What the caller (a campaign worker, a CLI run) knows about its budget."""

    local_only_required: bool = False
    tokens_remaining: int | None = None
    cost_remaining_usd: float | None = None
    campaign_id: str | None = None
    branch_id: str | None = None
    work_item_id: str | None = None


@dataclass
class _Candidate:
    name: str
    source: str  # task_routes | task_routes.default | task_models | task_models.default | default


class ProfileReport(BaseModel):
    name: str
    provider: str
    model: str
    credential_env_var: str | None = None
    credential_present: bool = False
    capabilities: list[str] = Field(default_factory=list)
    source: str  # models.profiles | model | task_models
    is_default: bool = False
    routes_using: list[str] = Field(default_factory=list)
    problems: list[str] = Field(default_factory=list)


class RouteReport(BaseModel):
    task_class: str
    candidates: list[str] = Field(default_factory=list)
    first_eligible: str | None = None
    fallback_ok: bool = False
    note: str = ""


class NoEligibleProviderError(ProviderError):
    """No candidate profile could serve the task; the verdicts say why, per profile."""

    def __init__(self, message: str, decision: RoutingDecisionRecord) -> None:
        super().__init__(message)
        self.decision = decision

    @property
    def verdicts(self) -> list[CandidateVerdict]:
        return list(self.decision.candidates_considered)


def profile_config(config: Config, profile: ModelProfile) -> Config:
    """A copy of ``config`` whose ``model:`` block is this profile.

    Every provider is built through the ordinary factory on this derived config,
    so a profile behaves exactly like a ``model:`` block would (timeouts, sampling,
    Ollama options, tool-calling verification all included).
    """
    model = ModelConfig(**profile.model_dump(exclude={"capabilities", "local_only"}))
    return config.model_copy(update={"model": model}, deep=True)


def routing_ledger_path(ot_dir: Path) -> Path:
    from opentorus.usage import LEDGER_DIRNAME

    return ot_dir / LEDGER_DIRNAME / ROUTING_LEDGER_FILENAME


def read_routing_ledger(ot_dir: Path) -> list[RoutingDecisionRecord]:
    """All routing decisions, with later ``actual_model`` observations folded in.

    The ledger mixes two line shapes (decisions and observations) because it is
    append-only; corrupt lines are skipped with a warning like every other ledger.
    """
    path = routing_ledger_path(ot_dir)
    if not path.is_file():
        return []
    decisions: dict[str, RoutingDecisionRecord] = {}
    order: list[str] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "Skipping corrupt routing ledger line %d in %s: %s", lineno, path, exc
                )
                continue
            if not isinstance(payload, dict):
                continue
            try:
                if "observed_at" in payload:
                    observation = RoutingObservation.model_validate(payload)
                    known = decisions.get(observation.decision_id)
                    if known is not None:
                        known.actual_model = observation.actual_model
                    continue
                record = RoutingDecisionRecord.model_validate(payload)
            except ValidationError as exc:
                logger.warning(
                    "Skipping corrupt routing ledger line %d in %s: %s", lineno, path, exc
                )
                continue
            if record.decision_id not in decisions:
                order.append(record.decision_id)
            decisions[record.decision_id] = record
    return [decisions[key] for key in order]


ProviderFactory = Callable[[Config], BaseProvider]


def _default_factory(config: Config) -> BaseProvider:
    from opentorus.providers.registry import get_provider

    return get_provider(config)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProviderPool:
    """Resolve, build, cache, and record the provider for each task class."""

    def __init__(
        self,
        config: Config,
        *,
        ot_dir: Path | None = None,
        factory: ProviderFactory | None = None,
        capability_cache: CapabilityCache | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.ot_dir = ot_dir
        self._factory: ProviderFactory = factory or _default_factory
        self._cache = capability_cache
        self._clock = clock or _utcnow
        self._instances: dict[str, BaseProvider] = {}
        self._decisions: dict[str, RoutingDecisionRecord] = {}
        # Decision counter: seeded once from the on-disk ledger, then in-memory.
        self._counter: int | None = None

    # -- profiles -----------------------------------------------------------------

    def profiles(self) -> dict[str, ModelProfile]:
        """Every resolvable profile: declared ones, the implicit ``default`` (from
        ``model:``, unless a profile of that name is declared), and one synthesised
        ``default@<model>`` per legacy ``task_models`` entry."""
        profiles: dict[str, ModelProfile] = dict(self.config.models.profiles)
        if DEFAULT_PROFILE_NAME not in profiles:
            profiles[DEFAULT_PROFILE_NAME] = ModelProfile(**self.config.model.model_dump())
        base = profiles.get(self.default_profile_name(), profiles[DEFAULT_PROFILE_NAME])
        for model_name in self.config.governance.routing.task_models.values():
            if not model_name:
                continue
            synthesised = f"{DEFAULT_PROFILE_NAME}@{model_name}"
            if synthesised not in profiles:
                profiles[synthesised] = base.model_copy(update={"name": model_name})
        return profiles

    def profile_source(self, name: str) -> str:
        """Where a profile came from: ``models.profiles``, ``model`` or ``task_models``."""
        if name in self.config.models.profiles:
            return "models.profiles"
        if name == DEFAULT_PROFILE_NAME:
            return "model"
        return "task_models"

    def default_profile_name(self) -> str:
        return self.config.models.default_profile or DEFAULT_PROFILE_NAME

    # -- candidates ---------------------------------------------------------------

    def _candidate_entries(self, task_class: str) -> list[_Candidate]:
        routing = self.config.governance.routing
        default_name = self.default_profile_name()
        if not routing.enabled:
            return [_Candidate(default_name, "default")]
        entries: list[_Candidate] = []
        seen: set[str] = set()

        def add(name: str, source: str) -> None:
            if name and name not in seen:
                seen.add(name)
                entries.append(_Candidate(name, source))

        lookup = task_class_lookup_names(task_class)
        for key in lookup:
            for name in routing.task_routes.get(key, []):
                add(name, "task_routes")
        if TaskClass.default.value not in lookup:
            for name in routing.task_routes.get(TaskClass.default.value, []):
                add(name, "task_routes.default")
        for key in lookup:
            model = routing.task_models.get(key)
            if model:
                add(f"{DEFAULT_PROFILE_NAME}@{model}", "task_models")
        if TaskClass.default.value not in lookup:
            model = routing.task_models.get(TaskClass.default.value)
            if model:
                add(f"{DEFAULT_PROFILE_NAME}@{model}", "task_models.default")
        add(default_name, "default")
        return entries

    def candidates(self, task_class: str | TaskClass) -> list[str]:
        """Profile names to try for ``task_class``, in order.

        ``task_routes[tc]`` → ``task_routes["default"]`` → legacy ``task_models[tc]``
        (as ``default@<model>``) → legacy ``task_models["default"]`` → the default
        profile. With routing disabled: the default profile only.
        """
        return [entry.name for entry in self._candidate_entries(str(task_class))]

    def route_source(self, task_class: str | TaskClass) -> str:
        """Which table supplied the first candidate (``default`` when nothing routed)."""
        entries = self._candidate_entries(str(task_class))
        return entries[0].source if entries else "default"

    # -- acquisition --------------------------------------------------------------

    def _next_decision_id(self) -> str:
        if self._counter is None:
            if self.ot_dir is not None:
                existing = [d.decision_id for d in read_routing_ledger(self.ot_dir)]
                seed = next_id("RTD", existing)
                self._counter = int(seed.rsplit("-", 1)[-1]) - 1
            else:
                self._counter = 0
        self._counter += 1
        if self.ot_dir is None:
            return f"RTD-mem-{self._counter:04d}"
        return f"RTD-{self._counter:04d}"

    def _ineligibility_reason(
        self,
        profile: ModelProfile | None,
        required: frozenset[ProviderCapability],
        budget_context: BudgetContext | None,
    ) -> str | None:
        if profile is None:
            return "unknown profile (not in models.profiles)"
        if profile.provider.lower() not in KNOWN_PROVIDERS:
            return (
                f"unknown provider '{profile.provider}' (valid: "
                f"{', '.join(sorted(KNOWN_PROVIDERS))})"
            )
        caps = effective_capabilities(profile, self._cache)
        missing = sorted(c.value for c in required if c not in caps)
        if missing:
            return f"missing capabilities: {', '.join(missing)}"
        local = profile_is_local(profile)
        if budget_context is not None and budget_context.local_only_required and not local:
            return "local-only required but the provider is not local"
        if (
            budget_context is not None
            and budget_context.cost_remaining_usd is not None
            and budget_context.cost_remaining_usd <= 0
            and not local
        ):
            return "cost budget exhausted; only local providers remain eligible"
        if self.ot_dir is not None and self.config.governance.budgets.per_provider_usd:
            from opentorus.governance import budget_alerts

            for alert in budget_alerts(self.ot_dir, self.config):
                if alert.breached and alert.scope == profile.provider:
                    return f"per-provider budget breached ({alert.message})"
        return None

    def acquire(
        self,
        task_class: str | TaskClass,
        required_capabilities: frozenset[ProviderCapability] = frozenset(),
        budget_context: BudgetContext | None = None,
        *,
        tags: dict[str, str] | None = None,
    ) -> ProviderLease:
        """Pick the first eligible profile for ``task_class`` and lease its provider.

        The decision is recorded in the routing ledger whether or not a provider is
        found; when none is, :class:`NoEligibleProviderError` carries the per-candidate
        verdicts. ``tags`` may carry ``session_id``/``campaign_id``/``branch_id``/
        ``work_item_id`` for the record.
        """
        tc = str(task_class)
        tags = tags or {}
        required = frozenset(ProviderCapability(str(c)) for c in required_capabilities)
        profiles = self.profiles()
        entries = self._candidate_entries(tc)
        verdicts: list[CandidateVerdict] = []
        selected: _Candidate | None = None
        for entry in entries:
            reason = self._ineligibility_reason(profiles.get(entry.name), required, budget_context)
            if reason is None:
                verdicts.append(
                    CandidateVerdict(profile=entry.name, eligible=True, reason="selected")
                )
                selected = entry
                break
            verdicts.append(CandidateVerdict(profile=entry.name, eligible=False, reason=reason))

        skipped = [v for v in verdicts if not v.eligible]
        fallback_reason = None
        if selected is not None and skipped:
            fallback_reason = "; ".join(f"'{v.profile}' skipped: {v.reason}" for v in skipped)
        campaign_id = (budget_context.campaign_id if budget_context else None) or tags.get(
            "campaign_id"
        )
        branch_id = (budget_context.branch_id if budget_context else None) or tags.get("branch_id")
        work_item_id = (budget_context.work_item_id if budget_context else None) or tags.get(
            "work_item_id"
        )
        profile = profiles.get(selected.name) if selected is not None else None
        record = RoutingDecisionRecord(
            decision_id=self._next_decision_id(),
            task_class=tc,
            requested_profile=entries[0].name if entries else None,
            selected_profile=selected.name if selected is not None else None,
            provider=profile.provider if profile is not None else None,
            configured_model=profile.name if profile is not None else None,
            required_capabilities=sorted(c.value for c in required),
            candidates_considered=verdicts,
            fallback_reason=fallback_reason,
            routing_enabled=self.config.governance.routing.enabled,
            local_only_required=bool(budget_context and budget_context.local_only_required),
            created_at=self._clock(),
            campaign_id=campaign_id,
            branch_id=branch_id,
            work_item_id=work_item_id,
            session_id=tags.get("session_id"),
            outcome="selected" if selected is not None else "no_eligible_provider",
        )
        self._decisions[record.decision_id] = record
        if self.ot_dir is not None:
            append_jsonl(routing_ledger_path(self.ot_dir), record)
        if selected is None or profile is None:
            reasons = "; ".join(f"{v.profile}: {v.reason}" for v in verdicts) or "no candidates"
            raise NoEligibleProviderError(
                f"No eligible model profile for task class '{tc}' ({reasons}). "
                "Check models.profiles and governance.routing.task_routes in config.yaml.",
                record,
            )
        return ProviderLease(
            provider=self._instance(selected.name, profile),
            decision=record,
            profile_name=selected.name,
            profile=profile,
        )

    def _instance(self, name: str, profile: ModelProfile) -> BaseProvider:
        provider = self._instances.get(name)
        if provider is None:
            provider = self._factory(profile_config(self.config, profile))
            self._instances[name] = provider
        return provider

    def note_actual_model(self, decision_id: str, model: str | None) -> None:
        """Back-fill the model the API reported, as an appended observation line."""
        if not model:
            return
        decision = self._decisions.get(decision_id)
        if decision is not None:
            decision.actual_model = model
        if self.ot_dir is not None:
            append_jsonl(
                routing_ledger_path(self.ot_dir),
                RoutingObservation(
                    decision_id=decision_id, actual_model=model, observed_at=self._clock()
                ),
            )

    def decision(self, decision_id: str) -> RoutingDecisionRecord | None:
        return self._decisions.get(decision_id)

    # -- reporting (doctor) -------------------------------------------------------

    def _static_eligible(self, name: str, profiles: dict[str, ModelProfile]) -> bool:
        profile = profiles.get(name)
        return profile is not None and profile.provider.lower() in KNOWN_PROVIDERS

    def describe(self) -> tuple[list[ProfileReport], list[RouteReport]]:
        """Configuration-only view for ``doctor``: no provider is built, no probe run,
        and credentials are reported by environment-variable *name* only."""
        import os

        profiles = self.profiles()
        default_name = self.default_profile_name()
        routing = self.config.governance.routing
        route_keys: list[str] = [tc.value for tc in TaskClass]
        for key in list(routing.task_routes) + list(routing.task_models):
            if key not in route_keys:
                route_keys.append(key)
        routes_using: dict[str, list[str]] = {name: [] for name in profiles}
        route_reports: list[RouteReport] = []
        for key in route_keys:
            entries = self._candidate_entries(key)
            names = [e.name for e in entries]
            for name in names:
                routes_using.setdefault(name, []).append(key)
            eligible = [n for n in names if self._static_eligible(n, profiles)]
            unknown = [n for n in names if n not in profiles]
            notes: list[str] = []
            if key not in {tc.value for tc in TaskClass} and key not in LEGACY_TASK_ALIASES:
                notes.append("unknown task class")
            if unknown:
                notes.append(
                    f"unknown profile(s): {', '.join(unknown)} — edit config.yaml "
                    "(`config set` cannot write mappings)"
                )
            if not routing.enabled:
                notes.append("routing disabled")
            elif not routing.task_routes and not routing.task_models:
                notes.append(
                    "no task_routes configured; edit config.yaml (`config set` cannot write "
                    "mappings)"
                )
            fallback_ok = any(n != names[0] for n in eligible) if names else False
            route_reports.append(
                RouteReport(
                    task_class=key,
                    candidates=names,
                    first_eligible=eligible[0] if eligible else None,
                    fallback_ok=fallback_ok,
                    note="; ".join(notes),
                )
            )
        profile_reports: list[ProfileReport] = []
        for name, profile in profiles.items():
            env_var = CREDENTIAL_ENV_VARS.get(profile.provider.lower())
            problems: list[str] = []
            if profile.provider.lower() not in KNOWN_PROVIDERS:
                problems.append(
                    f"unknown provider '{profile.provider}' (valid: "
                    f"{', '.join(sorted(KNOWN_PROVIDERS))})"
                )
            _known, unknown_caps = parse_capabilities(profile.capabilities)
            if unknown_caps:
                problems.append(
                    f"unknown capabilities: {', '.join(unknown_caps)} (valid: "
                    f"{', '.join(c.value for c in ProviderCapability)})"
                )
            profile_reports.append(
                ProfileReport(
                    name=name,
                    provider=profile.provider,
                    model=profile.name,
                    credential_env_var=env_var,
                    credential_present=bool(env_var and os.environ.get(env_var)),
                    capabilities=sorted(
                        c.value for c in effective_capabilities(profile, self._cache)
                    ),
                    source=self.profile_source(name),
                    is_default=(name == default_name),
                    routes_using=sorted(set(routes_using.get(name, []))),
                    problems=problems,
                )
            )
        if default_name not in profiles:
            profile_reports.append(
                ProfileReport(
                    name=default_name,
                    provider="?",
                    model="?",
                    source="models.default_profile",
                    is_default=True,
                    problems=["models.default_profile names a profile that does not exist"],
                )
            )
        return profile_reports, route_reports


def build_pool(config: Config, ot_dir: Path | None) -> ProviderPool:
    """The pool a CLI command or worker should use: ledger + probe cache under ot_dir."""
    cache = CapabilityCache(default_cache_path(ot_dir)) if ot_dir is not None else None
    return ProviderPool(config, ot_dir=ot_dir, capability_cache=cache)


__all__ = [
    "BudgetContext",
    "CandidateVerdict",
    "DEFAULT_PROFILE_NAME",
    "LEGACY_TASK_ALIASES",
    "NoEligibleProviderError",
    "ProfileReport",
    "ProviderLease",
    "ProviderPool",
    "RouteReport",
    "RoutingDecisionRecord",
    "RoutingObservation",
    "TaskClass",
    "build_pool",
    "profile_config",
    "read_routing_ledger",
    "routing_ledger_path",
    "task_class_lookup_names",
]
