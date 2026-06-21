"""Verifier protocol and result model."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel


class VerificationResult(BaseModel):
    """Outcome of a single formal-verification attempt.

    ``outcome`` and ``model`` are populated by decision-procedure backends (SMT,
    M62): ``unsat`` means the goal is proved (``accepted``), ``sat`` attaches a
    counterexample ``model`` (a refutation), and ``unknown`` is inconclusive —
    never a proof. Proof-assistant backends (Lean/Coq) leave them ``None``.
    """

    backend: str
    backend_version: str | None = None
    accepted: bool
    output: str = ""
    available: bool = True
    # True when the checker neither accepted nor cleanly rejected: a timeout, a
    # crash, or a source that failed to parse. Distinguishing this from a genuine
    # rejection keeps "the tool gave up" from being read as "the proof is wrong".
    inconclusive: bool = False
    outcome: str | None = None  # SMT: "unsat" | "sat" | "unknown"
    model: str | None = None  # SMT "sat": the counterexample model

    def status_line(self) -> str:
        if not self.available:
            return f"{self.backend}: unavailable"
        if self.inconclusive:
            return f"{self.backend}: inconclusive"
        if self.outcome is not None:
            return f"{self.backend}: {self.outcome}"
        return f"{self.backend}: {'accepted' if self.accepted else 'rejected'}"


@runtime_checkable
class Verifier(Protocol):
    """A formal-verification backend (e.g. Lean 4, Coq)."""

    name: str

    def is_available(self) -> bool:
        """Whether the backend tool is installed and runnable."""
        ...

    def version(self) -> str | None:
        """Backend version string, or ``None`` if unavailable."""
        ...

    def verify(self, source: str) -> VerificationResult:
        """Submit ``source`` and report whether the checker accepts it."""
        ...
