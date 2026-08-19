"""The campaign engine: persistent, resumable orchestration of one problem attack.

Layer boundary — read this before adding anything here
-------------------------------------------------------

A campaign is *orchestration state*: which branches exist, which work item is
running, what the budget ledger says, which phase the engine is in. All of it lives
under ``.opentorus/problems/<PROBLEM-ID>/campaigns/<CAMPAIGN-ID>/`` as an
append-only typed event log (``events.jsonl``) plus a derived ``snapshot.json``
that a pure reducer can always rebuild from the log.

The *mathematical* truth about the problem — claim statuses, verified proofs,
counterexamples, evidence — lives in the dossier and the workspace ledgers, and is
governed by the epistemic invariants in ``research.dossier.validation``. The
campaign layer only ever *references* those artifacts by id (``ArtifactRef``);
it never sets or changes a claim status, never marks a problem solved, and never
copies a status into its own state. ``campaign status`` therefore shows two
separate things: the orchestration state (phase, budget, branches) and the root
mathematical status, which is derived on demand from dossier artifacts by
``research.dossier.status_gate`` / ``research.dossier.scope``. A *completed*
campaign means the engine ran out of work or budget under its mode's criterion —
not that the problem is solved.

Determinism: ids are minted from reducer-owned counters (``BRANCH-``, ``WI-``,
``OBL-``, ``FSIG-``, ``NODE-``) and the event sequence number (``EVT-``);
``CAMPAIGN-`` ids come from a workspace-wide ``next_id`` scan; every timestamp
comes from an injectable :class:`~opentorus.campaign.clock.Clock`; the reducer
reads no clock, mints no uuid, and performs no I/O.
"""

from __future__ import annotations

__all__: list[str] = []
