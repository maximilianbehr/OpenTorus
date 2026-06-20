"""Tests for the dossier's validated-numerics verification path.

Pins the honest behavior of the VALIDATED_NUMERICAL verification-grade evidence and
confirms it does not weaken the support-only treatment of ordinary numerics (EVAL-001).
This is the dossier-side counterpart to the general research-stack numerics in
``test_validated_numerics.py``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.validated_numerics import (
    record_validated_numerical,
    verify_certificate,
)
from opentorus.research.dossier.validation import evidence_can_verify
from opentorus.research.verifiers.interval import IntervalVerifier
from opentorus.workspace import init_workspace, workspace_dir

_needs_mpmath = pytest.mark.skipif(
    not IntervalVerifier().is_available(), reason="mpmath not installed"
)


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: f(x) >= 0 on the box.", domain="demo")
    return base, d.id


def test_validated_numerical_is_verification_grade() -> None:
    assert evidence_can_verify("VALIDATED_NUMERICAL") is True
    # EVAL-001 invariant preserved: ordinary numerics stay support-only.
    assert evidence_can_verify("EXPERIMENT") is False
    assert evidence_can_verify("COMPUTATION") is False


@_needs_mpmath
def test_verifier_accepts_true_inequality() -> None:
    r = verify_certificate(
        {"variables": {"x": [1, 3.9]}, "expression": "sqrt(x)", "relation": "<", "bound": 2}
    )
    assert r.accepted is True


@_needs_mpmath
def test_verifier_rejects_false_inequality() -> None:
    # x*x < 0 is false on [1, 2]; a sound verifier must NOT accept it.
    r = verify_certificate(
        {"variables": {"x": [1, 2]}, "expression": "x*x", "relation": "<", "bound": 0}
    )
    assert r.accepted is False


@_needs_mpmath
def test_verifier_inconclusive_when_enclosure_straddles() -> None:
    r = verify_certificate(
        {"variables": {"x": [0, 2]}, "expression": "x-1", "relation": ">", "bound": 0}
    )
    assert r.accepted is False
    assert "straddle" in r.output.lower()


@_needs_mpmath
def test_verifier_rejects_unsafe_expression() -> None:
    r = verify_certificate(
        {"variables": {}, "expression": "__import__('os')", "relation": "<", "bound": 0}
    )
    assert r.accepted is False
    assert "invalid certificate" in r.output


def test_verifier_unavailable_without_mpmath(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(IntervalVerifier, "is_available", lambda self: False)
    r = IntervalVerifier().verify(json.dumps({"variables": {}, "expression": "1"}))
    assert r.available is False
    assert r.accepted is False


@_needs_mpmath
def test_accepted_certificate_creates_evidence_and_promotes(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="x*x exceeds 1 on [2,3]."
    )
    ev, result = record_validated_numerical(
        base,
        pid,
        cand.id,
        certificate={"variables": {"x": [2, 3]}, "expression": "x*x", "relation": ">", "bound": 1},
        summary="x*x > 1 on [2,3] (interval enclosure)",
    )
    assert result.accepted is True
    assert ev is not None and ev.type == "VALIDATED_NUMERICAL"
    verified = claims.verify_counterexample(base, pid, cand.id, verification_artifact=ev.id)
    assert verified.type == "COUNTEREXAMPLE_VERIFIED"
    assert verified.status == "verified"


@_needs_mpmath
def test_inconclusive_certificate_records_nothing(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="x-1 > 0 on [0,2]."
    )
    ev, result = record_validated_numerical(
        base,
        pid,
        cand.id,
        certificate={"variables": {"x": [0, 2]}, "expression": "x-1", "relation": ">", "bound": 0},
    )
    assert result.accepted is False
    assert ev is None
    from opentorus.errors import OpenTorusError

    with pytest.raises(OpenTorusError):
        claims.verify_counterexample(base, pid, cand.id, verification_artifact="EVID-0000")
