"""Tests for validated (interval) numerics (Milestone 61).

A rigorous enclosure is parsed and recorded with bounds + rounding as strong
evidence; absence of the interval library degrades to sampled evidence honestly.
Offline; no mpmath required (the rigorous path is exercised via parsed output).
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.research.math_experiments import (
    SampledEstimate,
    VerifiedBounds,
    parse_numeric_result,
    record_bounds_evidence,
    rigorous_numerics_available,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _claim(ot: Path, statement: str):
    from opentorus.research.claims import new_claim

    return new_claim(ot, statement)


def test_parse_verified_bounds_keeps_rounding_and_bounds() -> None:
    stdout = (
        '{"kind": "verified_bounds", "rigorous": true, "library": "mpmath.iv", '
        '"quantity": "f", "domain": "[0, 1]", "rounding": "outward", '
        '"lower": 0.75, "upper": 1.0, "excludes_counterexample": true}'
    )
    result = parse_numeric_result(stdout)
    assert isinstance(result, VerifiedBounds)
    assert result.rounding == "outward"
    assert (result.lower, result.upper) == (0.75, 1.0)
    assert result.excludes_counterexample is True


def test_parse_sampling_fallback() -> None:
    stdout = (
        '{"kind": "numerical_sampling", "rigorous": false, "quantity": "f", '
        '"domain": "[0, 1]", "samples": 1001, "min_value": 0.75, "max_value": 1.0, '
        '"note": "mpmath not installed"}'
    )
    result = parse_numeric_result(stdout)
    assert isinstance(result, SampledEstimate)
    assert result.samples == 1001
    assert result.rigorous is False


def test_rigorous_bound_recorded_as_strong_evidence(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "f(x) > 0 on [0, 1].")
    bounds = VerifiedBounds(
        quantity="f",
        domain="[0, 1]",
        lower=0.75,
        upper=1.0,
        excludes_counterexample=True,
        library="mpmath.iv",
    )
    evidence, _advisory = record_bounds_evidence(ot, claim.id, bounds)
    assert evidence.direction == "supports"
    assert evidence.strength == "strong"
    assert evidence.limitations == []
    assert "rigorous" in evidence.summary.lower()


def test_sampling_recorded_as_weak_evidence(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "f(x) > 0 on [0, 1].")
    sample = SampledEstimate(
        quantity="f", domain="[0, 1]", samples=1001, min_value=0.75, max_value=1.0
    )
    evidence, _advisory = record_bounds_evidence(ot, claim.id, sample)
    assert evidence.strength == "weak"
    assert "not a rigorous bound" in " ".join(evidence.limitations)


def test_validated_numerics_template_runs_and_degrades_honestly(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "interval bound", template="validated_numerics")
    exp, code = run_experiment(ot, exp.id, timeout=60)
    assert code == 0
    stdout = (ot / exp.path / "results" / "stdout.txt").read_text(encoding="utf-8")
    result = parse_numeric_result(stdout)
    assert result is not None
    if rigorous_numerics_available():
        assert isinstance(result, VerifiedBounds)
        assert result.rigorous is True
    else:
        assert isinstance(result, SampledEstimate)
        assert "not a rigorous bound" in result.note
