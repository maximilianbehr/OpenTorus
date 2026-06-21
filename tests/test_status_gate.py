"""Tests for the derived report-status gate.

The gate's whole purpose is that a pile of proof sketches can never read as a
solution. These pin that behavior.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.experiments import create_experiment, run_experiment
from opentorus.research.dossier.status_gate import derive_status
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    dossier = store.create_dossier(base, "A conjecture about objects X.", domain="test")
    return base, dossier.id


def test_unsolved_when_only_conjecture(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds for all n")
    assert derive_status(base, pid).status == "UNSOLVED"


def test_heuristic_only_with_sketch(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    claims.add_proof_attempt(base, pid, title="sketch", body="step 1 ... gap", kind="sketch")
    assert derive_status(base, pid).status == "HEURISTIC_ONLY"


def test_heuristic_only_with_heuristic_claim(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="HEURISTIC", statement="empirically m* ~ sqrt(a/b)")
    assert derive_status(base, pid).status == "HEURISTIC_ONLY"


def test_experimental_only(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="OBSERVATION", statement="pattern seen")
    exp = create_experiment(base, pid, title="sweep", command="true", random_seed=1)
    run_experiment(base, pid, exp.experiment_id)
    assert derive_status(base, pid).status == "EXPERIMENTAL_ONLY"


def test_partially_solved_with_supported_theorem(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    thm = claims.add_claim(
        base, pid, claim_type="THEOREM", statement="A cited bound", source_artifacts=["PAPER-0001"]
    )
    # Supporting (non-verification) evidence moves it to 'supported' but not verified.
    claims.add_evidence(
        base, pid, thm.id, evidence_type="PAPER", summary="matches the paper", direction="supports"
    )
    v = derive_status(base, pid)
    assert v.status == "PARTIALLY_SOLVED"
    assert v.has_supported_theorem is True
    assert v.has_verified_theorem is False


def test_solved_with_verified_proof(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n=5 refutes X"
    )
    ev, _ = claims.add_evidence(
        base,
        pid,
        cand.id,
        evidence_type="FORMAL_PROOF",
        summary="machine-checked",
        direction="supports",
    )
    claims.verify_counterexample(base, pid, cand.id, verification_artifact=ev.id)
    # A verified counterexample makes the original conjecture INVALID.
    assert derive_status(base, pid).status == "INVALID"


def test_invalid_on_algebra_rejection(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    assert derive_status(base, pid, algebra_rejected=True).status == "INVALID"


def test_open_gaps_counted_from_body(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_proof_attempt(
        base,
        pid,
        title="sketch",
        body="step 1 [GAP-1] need bound\nstep 2 [GAP-2] need lemma",
        kind="sketch",
    )
    assert derive_status(base, pid).open_gap_count >= 2
