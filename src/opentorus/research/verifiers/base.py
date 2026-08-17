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
    # Whether the checked statement quantified over anything, i.e. whether accepting it
    # says something general. ``False`` marks a closed arithmetic fact — "1+2 = 3",
    # "2**(4-2) + 1 = 5", "1/3 >= (5 - sqrt(5))/10" — all of which real runs submitted
    # against universally quantified claims and had recorded as *validating* them. Seven
    # of eleven accepted proofs in one sweep were of that kind. ``None`` means the
    # backend cannot tell, and nothing downstream may assume either way.
    general: bool | None = None

    def status_line(self) -> str:
        if not self.available:
            return f"{self.backend}: unavailable"
        if self.inconclusive:
            return f"{self.backend}: inconclusive"
        if self.outcome is not None:
            return f"{self.backend}: {self.outcome}"
        return f"{self.backend}: {'accepted' if self.accepted else 'rejected'}"


# Exit codes that mean the checker never got to judge the mathematics. A negative
# code is a signal (subprocess reports ``-N``): SIGSEGV on a prover crash, SIGKILL
# when the OOM killer steps in. 125/126/127 are "could not execute": no such binary,
# not executable, or — for the containerized Coq fallback — a docker/image failure.
# None of these is a statement about the proof, so none may be recorded as one.
_CRASH_EXIT_CODES = frozenset({125, 126, 127})


def ran_at_all(exit_code: int) -> bool:
    """Whether a nonzero exit is a *verdict* rather than a failure to run.

    A prover that exits 1 with error messages has judged the proof and rejected it.
    A prover killed by a signal, or a launcher that could not start it, has judged
    nothing — reporting that as a rejection tells the model its mathematics is wrong
    when the truth is that the check never ran.
    """
    return exit_code >= 0 and exit_code not in _CRASH_EXIT_CODES


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


def certificate_is_constant(source: str) -> bool:
    """Whether a JSON certificate only compares constants — no free variables.

    ``1/8 >= 1/16`` is a true statement and a backend will accept it, but accepting it
    establishes nothing about a claim that quantifies over anything. Both observed in a
    real run (sidorenko) as the workspace's only two accepted proofs.

    Returns ``False`` for anything it cannot confidently read, including Lean/Coq/SMT
    source, so the caller only ever acts on a certificate positively identified as
    vacuous. This is a heuristic used to *raise a question*, never to reject.
    """
    import json

    try:
        cert = json.loads(source)
    except (json.JSONDecodeError, ValueError):
        return False  # not a JSON certificate (Lean/Coq/SMT source) — say nothing
    if not isinstance(cert, dict):
        return False

    # sympy: an identity/inequality between two expressions, with declared variables.
    if "lhs" in cert and "rhs" in cert:
        declared = cert.get("vars") or cert.get("variables") or {}
        if declared:
            return False
        return not _mentions_a_symbol(f"{cert.get('lhs', '')} {cert.get('rhs', '')}")

    # interval: an expression bounded over a box. A box of point intervals [a, a] pins
    # every variable to a single value, which is again one numeric instance.
    if "expression" in cert:
        boxes = _boxes(cert)
        if boxes is None:
            return not _mentions_a_symbol(str(cert.get("expression", "")))
        return all(_is_point(box) for box in boxes)

    return False


def _mentions_a_symbol(text: str) -> bool:
    """True if the text contains an identifier that is not a known function name."""
    import re

    known = {"sqrt", "exp", "log", "ln", "sin", "cos", "tan", "abs", "pi", "e", "max", "min"}
    return any(word not in known for word in re.findall(r"[A-Za-z_]\w*", text))


def _boxes(cert: dict) -> list[object] | None:
    for key in ("variables", "domain", "box", "bounds"):
        value = cert.get(key)
        if isinstance(value, dict) and value:
            return list(value.values())
    return None


def _is_point(box: object) -> bool:
    if not isinstance(box, list | tuple) or len(box) != 2:
        return False
    try:
        return float(box[0]) == float(box[1])
    except (TypeError, ValueError):
        return False
