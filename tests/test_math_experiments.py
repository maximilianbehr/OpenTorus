"""Tests for math-aware experiments (Milestone 50).

A deterministic symbolic check runs via a template; a planted counterexample is
found and recorded; and a clean bounded search is stored as bounded numerical
evidence (never as "true"). No network is used.
"""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.research.evidence import list_evidence
from opentorus.research.experiments import new_experiment, run_experiment
from opentorus.research.math_experiments import (
    MATH_TEMPLATES,
    counterexample_search,
    record_search_evidence,
)
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_counterexample_search_finds_planted() -> None:
    # Conjecture: n != 7 holds for all n. Planted counterexample at n=7.
    result = counterexample_search(lambda n: n != 7, 1, 100, description="n != 7")
    assert result.found is True
    assert result.counterexample == 7
    assert "refutes" in result.evidence_summary()


def test_counterexample_search_bounded_no_counterexample() -> None:
    # Conjecture: n*n >= n holds for positive n (true on the range).
    result = counterexample_search(lambda n: n * n >= n, 1, 50, description="n^2 >= n")
    assert result.found is False
    assert result.counterexample is None
    assert result.checked == 50
    summary = result.evidence_summary()
    assert "not a proof" in summary
    assert "[1, 50]" in summary


def test_counterexample_search_rejects_bad_step() -> None:
    try:
        counterexample_search(lambda n: True, 1, 10, step=0)
        raise AssertionError("expected ValueError for non-positive step")
    except ValueError:
        pass


def test_record_search_evidence_contradicts_on_counterexample(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "P(n) holds for all n.")
    result = counterexample_search(lambda n: n != 5, 1, 10)
    evidence, advisory = record_search_evidence(ot, claim.id, result)
    assert evidence.direction == "contradicts"
    assert evidence.strength == "strong"
    assert advisory and "contradicts" in advisory


def test_record_search_evidence_weak_support_when_clean(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    from opentorus.research.claims import new_claim

    claim = new_claim(ot, "P(n) holds for all n.")
    result = counterexample_search(lambda n: True, 1, 100)
    evidence, advisory = record_search_evidence(ot, claim.id, result)
    assert evidence.direction == "supports"
    assert evidence.strength == "weak"
    assert "not a proof" in evidence.summary
    assert advisory is None
    assert list_evidence(ot, claim.id)


def test_symbolic_template_runs_deterministically(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "Symbolic identity", template="symbolic")
    exp, code = run_experiment(ot, exp.id)
    assert code == 0
    stdout = (ot / exp.path / "results" / "stdout.txt").read_text()
    data = json.loads(stdout.strip().splitlines()[-1])
    assert data["kind"] == "symbolic_check"
    assert data["all_hold"] is True


def test_counterexample_template_records_bounded_range(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    exp = new_experiment(ot, "Search", template="counterexample_search")
    exp, code = run_experiment(ot, exp.id)
    assert code == 0
    stdout = (ot / exp.path / "results" / "stdout.txt").read_text()
    data = json.loads(stdout.strip().splitlines()[-1])
    assert data["kind"] == "counterexample_search"
    assert data["counterexample"] is None
    assert "bounded evidence" in data["result"]


def test_unknown_template_rejected(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    try:
        new_experiment(ot, "x", template="bogus")
        raise AssertionError("expected error for unknown template")
    except Exception as exc:  # noqa: BLE001
        assert "Unknown experiment template" in str(exc)


def test_math_templates_present() -> None:
    assert set(MATH_TEMPLATES) == {
        "symbolic",
        "numerical",
        "counterexample_search",
        "validated_numerics",
    }
