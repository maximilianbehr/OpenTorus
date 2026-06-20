"""Tests for the SMT decision-procedure backend (Milestone 62).

A valid linear-arithmetic lemma is accepted (unsat); a false one yields a
counterexample model (sat); unknown/absent solver is reported honestly. A stub
solver is used so no real Z3/cvc5 is required.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.research.evidence import list_evidence
from opentorus.research.graph import related
from opentorus.research.verifiers import submit_proof
from opentorus.research.verifiers.base import VerificationResult
from opentorus.research.verifiers.smt import _result_from_solver_output
from opentorus.workspace import init_workspace, workspace_dir


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _claim(ot: Path, statement: str):
    from opentorus.research.claims import new_claim

    return new_claim(ot, statement)


class StubSMT:
    """A fake SMT solver: 'unsat' if source contains UNSAT, 'sat' if SAT, else unknown."""

    name = "smt"

    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def version(self) -> str | None:
        return "stub-z3" if self._available else None

    def verify(self, source: str) -> VerificationResult:
        if not self._available:
            return VerificationResult(
                backend=self.name, accepted=False, available=False, output="no solver"
            )
        if "UNSAT" in source:
            return _result_from_solver_output(self.name, "stub-z3", "unsat")
        if "SAT" in source:
            return _result_from_solver_output(self.name, "stub-z3", "sat\n((x 1) (y 0))")
        return _result_from_solver_output(self.name, "stub-z3", "unknown")


def test_unsat_goal_is_accepted_and_linked(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "x + 0 = x for all integers.")
    proof = submit_proof(
        ot,
        default_config(),
        "smt",
        "(assert UNSAT-goal)\n(check-sat)",
        claim_id=claim.id,
        verifier=StubSMT(),
    )
    assert proof.accepted is True
    edges = related(ot, proof.id)
    assert any(e.relation == "validates" and e.target_id == claim.id for e in edges)


def test_sat_goal_yields_counterexample_evidence(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "x > y for all integers (false).")
    proof = submit_proof(
        ot,
        default_config(),
        "smt",
        "(assert SAT-goal)\n(check-sat)\n(get-model)",
        claim_id=claim.id,
        verifier=StubSMT(),
    )
    assert proof.accepted is False
    evidence = list_evidence(ot, claim.id)
    assert any(e.direction == "contradicts" and "x 1" in e.summary for e in evidence)
    edges = related(ot, proof.id)
    assert any(e.relation == "contradicts" and e.target_id == claim.id for e in edges)


def test_unknown_is_inconclusive_not_a_proof(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = _claim(ot, "Some nonlinear goal.")
    proof = submit_proof(
        ot,
        default_config(),
        "smt",
        "(assert hard)\n(check-sat)",
        claim_id=claim.id,
        verifier=StubSMT(),
    )
    assert proof.accepted is False
    assert proof.available is True
    assert list_evidence(ot, claim.id) == []
    assert not any(e.relation == "validates" for e in related(ot, proof.id))


def test_absent_solver_reported_honestly(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    proof = submit_proof(
        ot, default_config(), "smt", "(check-sat)", verifier=StubSMT(available=False)
    )
    assert proof.available is False
    assert proof.accepted is False


def test_outcome_parsing_maps_verdicts() -> None:
    assert _result_from_solver_output("smt", None, "unsat").accepted is True
    sat = _result_from_solver_output("smt", None, "sat\n((x 3))")
    assert sat.accepted is False
    assert sat.outcome == "sat"
    assert sat.model == "((x 3))"
    unknown = _result_from_solver_output("smt", None, "unknown")
    assert unknown.outcome == "unknown"
    assert unknown.accepted is False
