"""Tool guards for the prove-loop literature phase (phase 1)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

LITERATURE_PHASE_FORBIDDEN = frozenset({"proof_write", "claim_new", "evidence_add"})

_PAPER_ID = re.compile(r"PAPER-\d{4}", re.I)


def literature_tool_gate(
    *,
    phase_complete: Callable[[], bool] | None = None,
) -> Callable[[str, dict], str | None]:
    """Return a gate that blocks deliverable tools during literature survey."""

    def gate(name: str, args: dict) -> str | None:
        if name in LITERATURE_PHASE_FORBIDDEN:
            return (
                f"Blocked: {name} is not allowed in literature phase (phase 1). "
                "Use paper_fetch, memory_add(kind=observations), "
                "dossier_known_result_add, and dossier_related_paper_add."
            )
        if phase_complete is not None and phase_complete():
            return None
        if name == "memory_add":
            kind = str(args.get("kind", "facts")).strip()
            if kind != "observations":
                return (
                    "Blocked during literature phase: memory_add must use kind=observations "
                    "with a PAPER-* citation."
                )
            text = str(args.get("text", "")).strip()
            if not _PAPER_ID.search(text):
                return (
                    "Blocked: each observation must cite a PAPER-* id "
                    "(e.g. 'PAPER-0001 Theorem 2.1, p.5: asymptotic error bound …')."
                )
        return None

    return gate


def observations_with_paper_refs(ot_dir: Path, *, obs_before: int) -> int:
    """Count new observation entries that cite a local PAPER-* id."""
    from opentorus.research.memory import list_memory

    added = list_memory(ot_dir, "observations")[obs_before:]
    return sum(1 for entry in added if _PAPER_ID.search(entry.text))
