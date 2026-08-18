"""Start-time validation, the primary-claim rule, and the small records the engine
threads through its phases.

Split out of :mod:`opentorus.campaign.engine` so the engine file holds the phase
handlers and the run loop only. Behaviour is unchanged: :func:`validate_start`
refuses the same requests with the same messages (exit 2 in the CLI),
:func:`create_primary_claim` implements rule D10 (the engine is the campaign driver,
so in prove-or-refute it creates the CONJECTURE claim from the statement and
designates it primary — status untouched, no ``status_changes`` entry), and
:class:`RunContext` is the per-campaign bundle every phase handler receives.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opentorus.campaign import ids
from opentorus.campaign.budget import has_positive_budget
from opentorus.campaign.clock import Clock
from opentorus.campaign.models import (
    CampaignConfigSnapshot,
    CampaignMode,
    CampaignPhase,
    CampaignRecord,
    CampaignSnapshot,
    NormalizedProblem,
)
from opentorus.campaign.phases import ModeProfile
from opentorus.campaign.store import CampaignStore
from opentorus.config import Config
from opentorus.errors import OpenTorusError

PRIMARY_CLAIM_REMEDIATION = (
    'opentorus problem claim {pid} --type CONJECTURE --statement "..." && '
    "opentorus problem verdict {pid} --set-primary CLAIM-XXXX"
)


class CampaignConfigError(OpenTorusError):
    """A ``campaign start`` request the engine refuses (exit 2 in the CLI)."""


@dataclass
class ResumeResult:
    record: CampaignRecord
    snapshot: CampaignSnapshot
    resumed: bool
    message: str


@dataclass
class PhaseOutcome:
    """What a phase handler decided: the next phase (``None`` when the handler itself
    moved the campaign — paused, completed, failed) and a short outcome note."""

    next_phase: CampaignPhase | None
    outcome: str = ""


@dataclass
class RunContext:
    """One open campaign: its store, its immutable record, its mode profile."""

    store: CampaignStore
    record: CampaignRecord
    profile: ModeProfile

    @property
    def cfg(self) -> CampaignConfigSnapshot:
        return self.record.config_snapshot

    @property
    def pid(self) -> str:
        return self.record.problem_id

    @property
    def cid(self) -> str:
        return self.record.id

    @property
    def snap(self) -> CampaignSnapshot:
        return self.store.snapshot


def resolve_mode(mode: CampaignMode | str | None, default: str) -> CampaignMode:
    """The requested mode (or the config default), or a ``CampaignConfigError``."""
    try:
        return CampaignMode(str(mode)) if mode is not None else CampaignMode(str(default))
    except ValueError as exc:
        raise CampaignConfigError(
            f"Unknown campaign mode '{mode}'. Valid modes: "
            + ", ".join(m.value for m in CampaignMode)
            + "."
        ) from exc


def validate_start(cfg: CampaignConfigSnapshot) -> None:
    """Refuse negative budgets, too few branches, and unbounded campaigns."""
    for name, value in (
        ("--max-steps", cfg.max_steps),
        ("--token-budget", cfg.token_budget),
        ("--max-wall-seconds", cfg.max_wall_seconds),
        ("--cost-budget", cfg.cost_budget),
    ):
        if value < 0:
            raise CampaignConfigError(f"{name} must be >= 0 (0 = unlimited), got {value}.")
    if cfg.initial_branches < 1:
        raise CampaignConfigError("--branches must be at least 1.")
    if cfg.mode is CampaignMode.prove_or_refute and cfg.initial_branches < 2:
        raise CampaignConfigError(
            "prove-or-refute needs at least 2 branches (a proof route and a "
            f"counterexample route); got --branches {cfg.initial_branches}."
        )
    if not has_positive_budget(cfg):
        raise CampaignConfigError(
            "No positive budget on any axis after merging config and flags: set "
            "--max-steps (or --token-budget / --max-wall-seconds / --cost-budget) to a "
            "positive value, or configure campaign.max_steps; 0 means unlimited and an "
            "unbounded campaign is refused."
        )


def create_primary_claim(ot_dir: Path, pid: str, *, notice: Callable[[str], None]) -> str:
    """Rule D10: create the CONJECTURE claim from the statement and designate it.

    The claim's status is whatever the dossier's own rules give a new CONJECTURE
    (``unverified``); nothing here changes it, and no ``status_changes`` entry is
    written. The engine is the campaign driver, so designating the target is its job.
    """
    from opentorus.research.dossier import store as dstore
    from opentorus.research.dossier.claims import add_claim

    raw = dstore.read_statement(ot_dir, pid)
    statement = (
        dstore.statement_body_for_display(raw).strip() or dstore.require_dossier(ot_dir, pid).title
    )
    claim = add_claim(
        ot_dir,
        pid,
        claim_type="CONJECTURE",
        statement=statement,
        notes=(
            "Created by `opentorus campaign start` (prove-or-refute) from the dossier "
            "statement and designated the primary claim; status untouched."
        ),
    )
    dossier = dstore.require_dossier(ot_dir, pid)
    dossier.primary_claim_id = claim.id
    dstore.save_dossier(ot_dir, dossier)
    notice(
        f"Created {claim.id} (CONJECTURE, status {claim.status}) from the statement of "
        f"{pid} and designated it the primary claim. The status is untouched; only "
        "verification artifacts can move it."
    )
    return claim.id


def normalize_problem(ot_dir: Path, pid: str) -> NormalizedProblem:
    """The NormalizedProblem every worker sees, from dossier facts only."""
    from opentorus.research.dossier import scope
    from opentorus.research.dossier import store as dstore

    dossier = dstore.require_dossier(ot_dir, pid)
    raw = dstore.read_statement(ot_dir, pid)
    statement = dstore.statement_body_for_display(raw).strip() or dossier.title
    return NormalizedProblem(
        problem_id=pid,
        statement=statement,
        title=dossier.title,
        target_scope=scope.classify_target(statement),
        assumptions=[a.statement for a in dstore.list_assumptions(ot_dir, pid)],
        definitions=[f"{d.term}: {d.definition}" for d in dstore.list_definitions(ot_dir, pid)],
        primary_claim_id=dossier.primary_claim_id,
    )


def create_campaign(
    ot_dir: Path,
    config: Config,
    clock: Clock,
    *,
    problem_id: str,
    mode: CampaignMode | str | None = None,
    branches: int | None = None,
    max_steps: int | None = None,
    token_budget: int | None = None,
    max_wall_seconds: int | None = None,
    cost_budget: float | None = None,
    designate_primary_claim: bool = True,
    notice: Callable[[str], None],
) -> RunContext:
    """Validate a start request, apply the primary-claim rule, allocate the id and
    create the store (``campaign_created`` + the primary-claim artifact reference and
    the parallelism diagnostic when applicable). Nothing runs yet."""
    from opentorus.campaign import events as ev
    from opentorus.campaign.budget import budget_from_config
    from opentorus.campaign.models import ArtifactRef, CampaignRecord
    from opentorus.campaign.phases import mode_profile
    from opentorus.research.dossier import store as dstore

    pid = dstore.canonical_problem_id(problem_id) or problem_id.strip().upper()
    dossier = dstore.require_dossier(ot_dir, pid)
    resolved_mode = resolve_mode(mode, str(config.campaign.default_mode))
    cfg = budget_from_config(
        config,
        mode=resolved_mode,
        branches=branches,
        max_steps=max_steps,
        token_budget=token_budget,
        max_wall_seconds=max_wall_seconds,
        cost_budget=cost_budget,
    )
    validate_start(cfg)
    primary_created: str | None = None
    if resolved_mode is CampaignMode.prove_or_refute and not dossier.primary_claim_id:
        if not designate_primary_claim:
            raise CampaignConfigError(
                f"prove-or-refute needs a designated primary claim on {pid} and "
                "--no-primary-claim refused to create one. Designate it yourself: "
                + PRIMARY_CLAIM_REMEDIATION.format(pid=pid)
            )
        primary_created = create_primary_claim(ot_dir, pid, notice=notice)
        dossier = dstore.require_dossier(ot_dir, pid)
    statement = dstore.read_statement(ot_dir, pid)
    cid = ids.next_campaign_id(ot_dir)
    record = CampaignRecord(
        id=cid,
        problem_id=pid,
        mode=resolved_mode,
        created_at=clock.now(),
        statement_sha256=hashlib.sha256(statement.encode("utf-8")).hexdigest(),
        config_snapshot=cfg,
        created_by="cli",
        primary_claim_id=dossier.primary_claim_id,
    )
    store = CampaignStore(
        ot_dir, pid, cid, clock=clock, fsync=True, persist_every_event=cfg.persist_every_event
    )
    store.create(record, actor="cli")
    if primary_created is not None:
        store.append(
            ev.EventType.artifact_created,
            ArtifactRef(artifact_id=primary_created, kind="claim"),
            actor="engine",
            refs=[primary_created],
        )
    if cfg.max_parallel_workers > 1:
        store.append(
            ev.EventType.parallelism_capped,
            ev.ParallelismCappedPayload(requested=cfg.max_parallel_workers, effective=1),
        )
    return RunContext(store=store, record=record, profile=mode_profile(resolved_mode))


__all__ = [
    "PRIMARY_CLAIM_REMEDIATION",
    "CampaignConfigError",
    "PhaseOutcome",
    "ResumeResult",
    "RunContext",
    "create_campaign",
    "create_primary_claim",
    "normalize_problem",
    "resolve_mode",
    "validate_start",
]
