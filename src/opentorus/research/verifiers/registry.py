"""Select enabled verifier backends from config."""

from __future__ import annotations

from opentorus.config import Config
from opentorus.research.verifiers.backends import CoqBackend, Lean4Backend
from opentorus.research.verifiers.base import Verifier
from opentorus.research.verifiers.interval import IntervalVerifier
from opentorus.research.verifiers.smt import SMTVerifier


def available_verifiers(config: Config) -> dict[str, Verifier]:
    """Return the enabled-and-installed verifiers, keyed by name."""
    cfg = config.tools.verifiers
    verifiers: dict[str, Verifier] = {}
    if cfg.lean:
        lean: Verifier = Lean4Backend(cfg.lean_command)
        if lean.is_available():
            verifiers[lean.name] = lean
    if cfg.coq:
        coq: Verifier = CoqBackend(cfg.coq_command)
        if coq.is_available():
            verifiers[coq.name] = coq
    if cfg.smt:
        smt: Verifier = SMTVerifier(cfg.smt_command)
        if smt.is_available():
            verifiers[smt.name] = smt
    if getattr(cfg, "interval", False):
        interval: Verifier = IntervalVerifier()
        if interval.is_available():
            verifiers[interval.name] = interval
    return verifiers


def get_verifier(config: Config, name: str) -> Verifier | None:
    """Return the named verifier if enabled in config (installed or not)."""
    cfg = config.tools.verifiers
    if name in {"lean4", "lean"} and cfg.lean:
        return Lean4Backend(cfg.lean_command)
    if name == "coq" and cfg.coq:
        return CoqBackend(cfg.coq_command)
    if name in {"smt", "z3", "cvc5"} and cfg.smt:
        return SMTVerifier(cfg.smt_command)
    if name in {"interval", "validated_numerical"} and getattr(cfg, "interval", False):
        return IntervalVerifier()
    return None
