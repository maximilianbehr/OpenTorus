"""Id minting for the campaign layer.

Two regimes, deliberately different:

* ``CAMPAIGN-NNNN`` is *workspace-unique*: it is derived with ``jsonl.next_id`` from
  every campaign directory under every problem, so two dossiers never share a
  campaign id and ``campaign status CAMPAIGN-0002`` needs no problem argument.
* Everything inside a campaign (``EVT-``, ``BRANCH-``, ``WI-``, ``OBL-``, ``FSIG-``,
  ``NODE-``) is *counter-derived*: ``EVT-`` from the event sequence number, the rest
  from counters that live in the snapshot and are advanced only by the reducer when
  it sees the ``*_proposed`` / ``*_created`` event carrying the id. The engine mints
  the next id by reading the current snapshot's counter (:func:`mint`), and replaying
  the log reproduces exactly the same ids — no clock, no uuid, no filesystem scan.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from opentorus.jsonl import next_id

CAMPAIGN_PREFIX = "CAMPAIGN"
BRANCH_PREFIX = "BRANCH"
WORK_ITEM_PREFIX = "WI"
OBLIGATION_PREFIX = "OBL"
FAILURE_SIGNATURE_PREFIX = "FSIG"
NODE_PREFIX = "NODE"

COUNTER_PREFIXES: tuple[str, ...] = (
    BRANCH_PREFIX,
    WORK_ITEM_PREFIX,
    OBLIGATION_PREFIX,
    FAILURE_SIGNATURE_PREFIX,
    NODE_PREFIX,
)

_CAMPAIGN_ID = re.compile(r"^CAMPAIGN-\d+$")
_SUFFIX = re.compile(r"-(\d+)$")


def is_campaign_id(text: str) -> bool:
    return bool(_CAMPAIGN_ID.match(text.strip().upper()))


def next_campaign_id(ot_dir: Path) -> str:
    """The next workspace-wide ``CAMPAIGN-NNNN`` (max existing suffix + 1)."""
    from opentorus.campaign.paths import list_campaigns

    return next_id(CAMPAIGN_PREFIX, (cid for _pid, cid in list_campaigns(ot_dir)))


def event_id(seq: int) -> str:
    """``EVT-000001`` for ``seq == 1``: the id *is* the sequence number."""
    if seq < 0:
        raise ValueError("event seq must be non-negative")
    return f"EVT-{seq:06d}"


def _format(prefix: str, n: int) -> str:
    if n < 1:
        raise ValueError(f"{prefix} ids start at 1")
    return f"{prefix}-{n:04d}"


def branch_id(n: int) -> str:
    return _format(BRANCH_PREFIX, n)


def work_item_id(n: int) -> str:
    return _format(WORK_ITEM_PREFIX, n)


def obligation_id(n: int) -> str:
    return _format(OBLIGATION_PREFIX, n)


def failure_signature_id(n: int) -> str:
    return _format(FAILURE_SIGNATURE_PREFIX, n)


def node_id(n: int) -> str:
    return _format(NODE_PREFIX, n)


def numeric_suffix(ident: str) -> int | None:
    """``7`` for ``BRANCH-0007``; ``None`` when the id carries no numeric suffix."""
    match = _SUFFIX.search(ident.strip())
    return int(match.group(1)) if match else None


def mint(counters: Mapping[str, int], prefix: str) -> str:
    """The next id for ``prefix`` given the snapshot's counters (does not advance them).

    The reducer advances the counter when it applies the event that carries the id,
    so minting twice without appending yields the same id — call it once per event.
    """
    return _format(prefix, int(counters.get(prefix, 0)) + 1)


__all__ = [
    "BRANCH_PREFIX",
    "CAMPAIGN_PREFIX",
    "COUNTER_PREFIXES",
    "FAILURE_SIGNATURE_PREFIX",
    "NODE_PREFIX",
    "OBLIGATION_PREFIX",
    "WORK_ITEM_PREFIX",
    "branch_id",
    "event_id",
    "failure_signature_id",
    "is_campaign_id",
    "mint",
    "next_campaign_id",
    "node_id",
    "numeric_suffix",
    "obligation_id",
    "work_item_id",
]
