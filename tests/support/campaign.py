"""Shared helpers for the campaign-engine tests: a workspace with one dossier and an
engine on a deterministic clock (no model calls; the mock path is offline)."""

from __future__ import annotations

from pathlib import Path

from opentorus.campaign.clock import StepClock
from opentorus.campaign.engine import CampaignEngine
from opentorus.config import Config, default_config
from opentorus.research.dossier.store import create_dossier
from opentorus.workspace import init_workspace, workspace_dir

GENERAL_STATEMENT = "For every n >= 1, the property P(n) holds."


def make_workspace(tmp_path: Path, *, statement: str = GENERAL_STATEMENT) -> tuple[Path, Path, str]:
    """``(root, ot_dir, problem_id)`` for a fresh initialized workspace with one dossier."""
    root = tmp_path
    init_workspace(root)
    ot_dir = workspace_dir(root)
    dossier = create_dossier(ot_dir, statement)
    return root, ot_dir, dossier.id


def make_engine(
    root: Path,
    ot_dir: Path,
    *,
    config: Config | None = None,
    clock: StepClock | None = None,
    **kwargs: object,
) -> CampaignEngine:
    return CampaignEngine(
        root,
        ot_dir,
        config or default_config(),
        clock=clock or StepClock(),
        **kwargs,  # type: ignore[arg-type]
    )
