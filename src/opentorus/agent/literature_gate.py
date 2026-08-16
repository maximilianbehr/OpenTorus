"""Tool guards for the prove-loop literature phase (phase 1)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from opentorus.research.identifiers import PAPER_REF_RE

LITERATURE_PHASE_FORBIDDEN = frozenset({"proof_write", "proof_submit", "claim_new", "evidence_add"})

_PAPER_ID = PAPER_REF_RE


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
                # The example is written as a *shape*, not as a sentence that could be
                # sent back verbatim. It used to read "PAPER-0001 Theorem 2.1, p.5:
                # asymptotic error bound …", and one run recorded exactly that string
                # 364 times as a real observation — citing a theorem number that does
                # not exist in PAPER-0001. An illustration the model can paste is an
                # invitation to invent authority.
                return (
                    "Blocked: each observation must cite a PAPER-* id and state what "
                    "*that paper* says, in the form "
                    "'<PAPER-id> <result>, p.<page>: <what it states>' — filled in from "
                    "the paper you just read, never copied from this example."
                )
        return None

    return gate


def observations_with_paper_refs(ot_dir: Path, *, obs_before: int) -> int:
    """Count new observation entries that cite a local PAPER-* id."""
    from opentorus.research.memory import list_memory

    added = list_memory(ot_dir, "observations")[obs_before:]
    return sum(1 for entry in added if _PAPER_ID.search(entry.text))
