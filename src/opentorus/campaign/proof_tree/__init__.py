"""The semantic proof tree: a derived, validated view over campaign + dossier state.

* :mod:`models` — ``ProofNode`` / ``ProofEdge`` / ``ProofGraph`` / ``ValidationIssue``;
* :mod:`settlement` — what a root relation can settle; the single source of truth
  for obligation closure (``can_close_obligation``); the derived root status;
* :mod:`builder` — ``build_proof_graph`` merges snapshot and ledgers, never raises;
* :mod:`validation` — the ten issue codes;
* :mod:`render` — plain / JSON / DOT plus the pure filter/search helpers.

The tree never sets a claim status and never infers the problem's status from
campaign progress; ``ProofGraph.root_status`` is read from ``status_gate`` / ``scope``.
Submodules are imported lazily by callers (the CLI, the dashboard) so
``import opentorus.campaign`` stays light.
"""

from __future__ import annotations

from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    ProofEdge,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
    RootStatusView,
    ValidationIssue,
)

__all__ = [
    "ROOT_ID",
    "ProofEdge",
    "ProofGraph",
    "ProofNode",
    "ProofNodeKind",
    "RootStatusView",
    "ValidationIssue",
]
