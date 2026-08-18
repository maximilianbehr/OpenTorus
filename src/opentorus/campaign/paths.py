"""Where a campaign lives on disk.

Layout (all under the dossier, so a dossier export/pack carries its campaigns)::

    .opentorus/problems/PROBLEM-0001/campaigns/CAMPAIGN-0001/
        campaign.yaml     the immutable CampaignRecord (id, mode, config snapshot)
        events.jsonl      append-only typed event log — the source of truth
        snapshot.json     reducer output, atomically rewritten, never ahead of the log
        progress.md       human-readable progress (orchestration state only)
        branches/         one card per branch for humans; nothing reads them back

Campaign ids are workspace-unique, so :func:`find_campaign` can locate one without
being told the problem.
"""

from __future__ import annotations

import re
from pathlib import Path

from opentorus.errors import OpenTorusError

CAMPAIGNS_DIRNAME = "campaigns"
EVENTS_FILENAME = "events.jsonl"
SNAPSHOT_FILENAME = "snapshot.json"
RECORD_FILENAME = "campaign.yaml"
PROGRESS_FILENAME = "progress.md"
BRANCHES_DIRNAME = "branches"

_PROBLEM_DIR = re.compile(r"^PROBLEM-\d+$")
_CAMPAIGN_DIR = re.compile(r"^CAMPAIGN-\d+$")


def campaigns_dir(ot_dir: Path, problem_id: str) -> Path:
    from opentorus.research.dossier.store import dossier_dir

    return dossier_dir(ot_dir, problem_id) / CAMPAIGNS_DIRNAME


def campaign_dir(ot_dir: Path, problem_id: str, campaign_id: str) -> Path:
    return campaigns_dir(ot_dir, problem_id) / campaign_id


def events_path(ot_dir: Path, problem_id: str, campaign_id: str) -> Path:
    return campaign_dir(ot_dir, problem_id, campaign_id) / EVENTS_FILENAME


def snapshot_path(ot_dir: Path, problem_id: str, campaign_id: str) -> Path:
    return campaign_dir(ot_dir, problem_id, campaign_id) / SNAPSHOT_FILENAME


def campaign_yaml_path(ot_dir: Path, problem_id: str, campaign_id: str) -> Path:
    return campaign_dir(ot_dir, problem_id, campaign_id) / RECORD_FILENAME


def progress_path(ot_dir: Path, problem_id: str, campaign_id: str) -> Path:
    return campaign_dir(ot_dir, problem_id, campaign_id) / PROGRESS_FILENAME


def branches_dir(ot_dir: Path, problem_id: str, campaign_id: str) -> Path:
    return campaign_dir(ot_dir, problem_id, campaign_id) / BRANCHES_DIRNAME


def list_campaigns(ot_dir: Path, *, problem_id: str | None = None) -> list[tuple[str, str]]:
    """``(problem_id, campaign_id)`` for every campaign directory, sorted.

    A directory counts as a campaign once it holds ``campaign.yaml`` or
    ``events.jsonl``; an empty ``CAMPAIGN-*`` directory is an aborted create and is
    ignored, so the next campaign id can reuse it (``CampaignStore.create`` accepts an
    empty directory).
    """
    from opentorus.research.dossier.store import problems_root

    root = problems_root(ot_dir)
    if not root.is_dir():
        return []
    found: list[tuple[str, str]] = []
    wanted = problem_id.strip().upper() if problem_id else None
    for problem_dir in sorted(root.iterdir()):
        if not problem_dir.is_dir() or not _PROBLEM_DIR.match(problem_dir.name):
            continue
        if wanted is not None and problem_dir.name != wanted:
            continue
        cdir = problem_dir / CAMPAIGNS_DIRNAME
        if not cdir.is_dir():
            continue
        for candidate in sorted(cdir.iterdir()):
            if not candidate.is_dir() or not _CAMPAIGN_DIR.match(candidate.name):
                continue
            if not (
                (candidate / RECORD_FILENAME).is_file() or (candidate / EVENTS_FILENAME).is_file()
            ):
                continue
            found.append((problem_dir.name, candidate.name))
    return found


def find_campaign(ot_dir: Path, campaign_id: str) -> tuple[str, Path]:
    """Locate ``campaign_id`` across all problems: ``(problem_id, campaign_dir)``.

    Raises :class:`OpenTorusError` naming the campaigns that do exist when the id is
    unknown — the usual cause is a typo or a different workspace.
    """
    wanted = campaign_id.strip().upper()
    if not _CAMPAIGN_DIR.match(wanted):
        raise OpenTorusError(
            f"'{campaign_id}' is not a campaign id (expected CAMPAIGN-NNNN, e.g. CAMPAIGN-0001)."
        )
    for pid, cid in list_campaigns(ot_dir):
        if cid == wanted:
            return pid, campaign_dir(ot_dir, pid, cid)
    known = ", ".join(cid for _pid, cid in list_campaigns(ot_dir))
    raise OpenTorusError(
        f"No campaign '{wanted}' in this workspace. "
        + (f"Known campaigns: {known}." if known else "Start one with `opentorus campaign start`.")
    )


__all__ = [
    "BRANCHES_DIRNAME",
    "CAMPAIGNS_DIRNAME",
    "EVENTS_FILENAME",
    "PROGRESS_FILENAME",
    "RECORD_FILENAME",
    "SNAPSHOT_FILENAME",
    "branches_dir",
    "campaign_dir",
    "campaign_yaml_path",
    "campaigns_dir",
    "events_path",
    "find_campaign",
    "list_campaigns",
    "progress_path",
    "snapshot_path",
]
