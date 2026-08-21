"""Select enabled verifier backends from config."""

from __future__ import annotations

from opentorus.config import Config
from opentorus.research.verifiers.backends import CoqBackend, Lean4Backend
from opentorus.research.verifiers.base import Verifier
from opentorus.research.verifiers.interval import IntervalVerifier
from opentorus.research.verifiers.smt import SMTVerifier
from opentorus.research.verifiers.sympy_backend import SymPyVerifier


def resolve_timeout(config: Config, requested: int | None = None) -> tuple[int, str | None]:
    """``(timeout, note)``: the seconds a checker may run, and why if it was changed.

    ``requested`` is what the model asked for via ``proof_submit``. It is clamped to
    ``verifiers.max_timeout_seconds`` and the clamp is reported rather than applied
    silently — the same contract ``campaign.max_experiment_seconds`` uses for
    ``exp_run``, and for the same reason: a checker that quietly gets less time than
    asked for looks like a proof that failed.
    """
    cfg = config.tools.verifiers
    default = max(1, int(cfg.timeout_seconds))
    if requested is None:
        return default, None
    ceiling = int(cfg.max_timeout_seconds)
    asked = max(1, int(requested))
    if ceiling <= 0:
        return default, (
            f"Requested timeout {asked}s ignored: verifiers.max_timeout_seconds is 0, "
            f"so every check runs at verifiers.timeout_seconds ({default}s)."
        )
    if asked > ceiling:
        return ceiling, (
            f"Requested timeout {asked}s exceeds verifiers.max_timeout_seconds; "
            f"clamped to {ceiling}s."
        )
    return asked, None


def available_verifiers(config: Config, timeout: int | None = None) -> dict[str, Verifier]:
    """Return the enabled-and-installed verifiers, keyed by name."""
    cfg = config.tools.verifiers
    seconds = timeout if timeout is not None else resolve_timeout(config)[0]
    verifiers: dict[str, Verifier] = {}
    if cfg.lean:
        lean: Verifier = Lean4Backend(cfg.lean_command, timeout=seconds)
        if lean.is_available():
            verifiers[lean.name] = lean
    if cfg.coq:
        coq: Verifier = CoqBackend(cfg.coq_command, timeout=seconds)
        if coq.is_available():
            verifiers[coq.name] = coq
    if cfg.smt:
        smt: Verifier = SMTVerifier(cfg.smt_command, timeout=seconds)
        if smt.is_available():
            verifiers[smt.name] = smt
    if getattr(cfg, "interval", False):
        interval: Verifier = IntervalVerifier()
        if interval.is_available():
            verifiers[interval.name] = interval
    if getattr(cfg, "sympy", False):
        sympy_v: Verifier = SymPyVerifier()
        if sympy_v.is_available():
            verifiers[sympy_v.name] = sympy_v
    return verifiers


def get_verifier(config: Config, name: str, timeout: int | None = None) -> Verifier | None:
    """Return the named verifier if enabled in config (installed or not)."""
    cfg = config.tools.verifiers
    seconds = timeout if timeout is not None else resolve_timeout(config)[0]
    if name in {"lean4", "lean"} and cfg.lean:
        return Lean4Backend(cfg.lean_command, timeout=seconds)
    if name == "coq" and cfg.coq:
        return CoqBackend(cfg.coq_command, timeout=seconds)
    if name in {"smt", "z3", "cvc5"} and cfg.smt:
        return SMTVerifier(cfg.smt_command, timeout=seconds)
    if name in {"interval", "validated_numerical"} and getattr(cfg, "interval", False):
        return IntervalVerifier()
    if name in {"sympy", "symbolic"} and getattr(cfg, "sympy", False):
        return SymPyVerifier()
    return None
