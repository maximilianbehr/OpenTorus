"""Proof attempts as provenance-rich artifacts.

Each submission of a formal goal/term to a backend produces a ``PROOF-*``
artifact: the exact source, the backend + version, and the verbatim
accept/reject output. Accepted proofs that target a claim add a ``validates``
edge to the artifact graph (rendered in the M35 graph view).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl

if TYPE_CHECKING:
    from opentorus.config import Config
    from opentorus.research.verifiers.base import Verifier

_SUFFIX = {"lean4": ".lean", "lean": ".lean", "coq": ".v", "smt": ".smt2", "z3": ".smt2"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ProofAttempt(BaseModel):
    """A recorded formal-verification attempt."""

    id: str
    backend: str
    backend_version: str | None = None
    accepted: bool
    available: bool = True
    claim_id: str | None = None
    source_path: str
    output: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


def proofs_dir(ot_dir: Path) -> Path:
    return ot_dir / "proofs"


def proofs_path(ot_dir: Path) -> Path:
    return ot_dir / "proofs.jsonl"


def list_proofs(ot_dir: Path) -> list[ProofAttempt]:
    return read_jsonl(proofs_path(ot_dir), ProofAttempt)


def get_proof(ot_dir: Path, proof_id: str) -> ProofAttempt | None:
    for proof in list_proofs(ot_dir):
        if proof.id == proof_id:
            return proof
    return None


def accepted_proof_for_claim(ot_dir: Path, claim_id: str) -> ProofAttempt | None:
    """Return the most recent accepted proof attempt for a claim, if any."""
    matches = [p for p in list_proofs(ot_dir) if p.claim_id == claim_id and p.accepted]
    return matches[-1] if matches else None


def submit_proof(
    ot_dir: Path,
    config: Config,
    backend: str,
    source: str,
    *,
    claim_id: str | None = None,
    verifier: Verifier | None = None,
) -> ProofAttempt:
    """Submit ``source`` to a formal backend and persist the attempt.

    If ``verifier`` is given it is used directly (for tests/injection); otherwise
    the backend is resolved from ``config``. An unconfigured backend raises rather
    than faking rigor. Accepted attempts targeting a claim add a ``validates``
    edge to the graph.
    """
    if verifier is None:
        from opentorus.research.verifiers.registry import get_verifier

        verifier = get_verifier(config, backend)
    if verifier is None:
        raise OpenTorusError(
            f"Verifier '{backend}' is not enabled. Enable it via "
            "config.tools.verifiers; with no backend, formal verification is unavailable."
        )

    result = verifier.verify(source)

    existing = list_proofs(ot_dir)
    proof_id = next_sequential_id("PROOF", len(existing))
    pdir = proofs_dir(ot_dir)
    pdir.mkdir(parents=True, exist_ok=True)
    suffix = _SUFFIX.get(result.backend, _SUFFIX.get(backend, ".txt"))
    source_file = pdir / f"{proof_id}{suffix}"
    source_file.write_text(source, encoding="utf-8")
    rel_source = f"proofs/{source_file.name}"

    attempt = ProofAttempt(
        id=proof_id,
        backend=result.backend,
        backend_version=result.backend_version,
        accepted=result.accepted,
        available=result.available,
        claim_id=claim_id,
        source_path=rel_source,
        output=result.output,
    )
    append_jsonl(proofs_path(ot_dir), attempt)

    if attempt.accepted and claim_id:
        from opentorus.research.graph import add_edge

        add_edge(
            ot_dir,
            proof_id,
            claim_id,
            "validates",
            rationale=f"Formally accepted by {result.backend}"
            + (f" {result.backend_version}" if result.backend_version else ""),
        )

    # An SMT ``sat`` verdict is a concrete refutation: record the model as
    # contradicting evidence (M50/M59) and link it as such. ``unknown`` is
    # inconclusive and records nothing.
    if not attempt.accepted and result.outcome == "sat" and result.model and claim_id:
        from opentorus.research.dossier.store import get_active_problem
        from opentorus.research.evidence import add_evidence
        from opentorus.research.graph import add_edge

        add_evidence(
            ot_dir,
            claim_id,
            source_type="external",
            source_id=proof_id,
            summary=f"{result.backend} found a counterexample model:\n{result.model}",
            direction="contradicts",
            strength="strong",
            problem_id=get_active_problem(ot_dir),
        )
        add_edge(
            ot_dir,
            proof_id,
            claim_id,
            "contradicts",
            rationale=f"{result.backend} returned sat (counterexample model).",
        )

    return attempt
