"""Tests for the sympy-backed algebra checker and its CLI.

The checker is the antidote to a common machine-written error: asserting a clean
interior optimum m* for an objective that is in fact monotone (so the optimum is
at a boundary), or asserting an m* that does not satisfy dW/dm = 0.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.research.algebra_check import check_optimizer

runner = CliRunner()


def test_false_interior_optimum_on_monotone_objective() -> None:
    # A strictly increasing objective has no interior optimum; any claimed one is false.
    r = check_optimizer("5*m + 3", variable="m", claimed_optimizer="7", domain=("1", "1000"))
    assert r.verdict == "rejected"
    assert r.is_monotone is True


def test_claimed_optimizer_not_stationary_is_rejected() -> None:
    # W = 100/m + 2m has its minimum at m = 5*sqrt(2) ~ 7.07; m* = 10 is not stationary.
    r = check_optimizer("100/m + 2*m", variable="m", claimed_optimizer="10", domain=("1", "1000"))
    assert r.verdict == "rejected"
    assert r.optimizer_is_critical is False


def test_correct_interior_optimizer_is_consistent() -> None:
    r = check_optimizer(
        "100/m + 2*m", variable="m", claimed_optimizer="5*sqrt(2)", domain=("1", "1000")
    )
    assert r.verdict == "consistent"
    assert r.optimizer_is_critical is True


def test_critical_points_reported() -> None:
    r = check_optimizer("100/m + 2*m", variable="m")
    assert any("sqrt" in c for c in r.critical_points)


def test_cli_rejects_false_optimum_with_exit_code() -> None:
    res = runner.invoke(
        app,
        ["check-algebra", "--expr", "5*m + 3", "--optimizer", "7", "--domain", "1,1000"],
    )
    assert res.exit_code == 2  # rejected → non-zero so CI can gate
    assert "REJECTED" in res.stdout


def test_cli_consistent_optimum_exit_zero() -> None:
    res = runner.invoke(
        app,
        ["check-algebra", "--expr", "100/m + 2*m", "--optimizer", "5*sqrt(2)"],
    )
    assert res.exit_code == 0
    assert "CONSISTENT" in res.stdout


def test_cli_json_spec_from_file(tmp_path: Path) -> None:
    spec = tmp_path / "claim.json"
    spec.write_text('{"expression": "5*m + 3", "claimed_optimizer": "7", "domain": [1, 1000]}')
    res = runner.invoke(app, ["check-algebra", str(spec), "--json"])
    assert res.exit_code == 2
    assert '"verdict": "rejected"' in res.stdout or '"verdict":"rejected"' in res.stdout
