"""Epistemic behavior tests for the credible math dossier (Milestone M1).

These map to EVAL-001..008 in the milestone spec: the rules that keep OpenTorus
honest are more important than any single feature.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.errors import OpenTorusError
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.experiments import create_experiment, run_experiment
from opentorus.research.dossier.report import build_report, lint_dossier_report
from opentorus.research.dossier.strategies import STRATEGY_TEMPLATES, create_approach
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _problem(tmp_path: Path) -> tuple[Path, str]:
    base = _ws(tmp_path)
    dossier = store.create_dossier(base, "A conjecture about objects X.", domain="test")
    return base, dossier.id


def test_canonical_problem_id() -> None:
    assert store.canonical_problem_id("PROBLEM-1") == "PROBLEM-0001"
    assert store.canonical_problem_id("problem 3") == "PROBLEM-0003"
    assert store.canonical_problem_id("PROBLEM-0042") == "PROBLEM-0042"
    assert store.canonical_problem_id("no digits") is None


def test_resolve_dossier_id(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    store.create_dossier(base, "First problem.")
    assert store.resolve_dossier_id(base, "PROBLEM-0001") == "PROBLEM-0001"
    assert store.resolve_dossier_id(base, "PROBLEM-1") == "PROBLEM-0001"
    assert store.resolve_dossier_id(base, "problem 1") == "PROBLEM-0001"
    assert store.resolve_dossier_id(base, "PROBLEM-0002") is None


def test_create_dossier_scaffold(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    d = store.dossier_dir(base, pid)
    assert (d / "problem.yaml").is_file()
    assert (d / "statement.md").is_file()
    for sub in ("experiments", "proof_attempts", "counterexample_search", "evidence"):
        assert (d / sub).is_dir()
    assert store.get_dossier(base, pid) is not None
    assert pid == "PROBLEM-0001"


# --- EVAL-001: numerical evidence must not prove a conjecture -----------------


def test_eval001_numerical_evidence_does_not_verify(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds for all n")
    assert claim.status == "unverified"

    exp = create_experiment(base, pid, title="sweep", command="true", random_seed=1)
    claims.add_evidence(
        base,
        pid,
        claim.id,
        evidence_type="EXPERIMENT",
        summary="held for n<=10^6",
        direction="supports",
        source_artifacts=[exp.experiment_id],
    )
    updated = store.get_claim(base, pid, claim.id)
    assert updated is not None
    # Evidence may support, but never verify.
    assert updated.status == "supported"
    assert updated.status not in ("verified", "formally_verified")

    with pytest.raises(OpenTorusError):
        claims.set_claim_status(base, pid, claim.id, "formally_verified")
    with pytest.raises(OpenTorusError):
        claims.set_claim_status(base, pid, claim.id, "verified")


# --- EVAL-002: "we prove" needs a verified proof artifact ---------------------


def test_eval002_honesty_linter_flags_unbacked_proof(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    from opentorus.research.dossier.honesty import IssueKind, lint_report

    text = "We prove that X holds for every n.\n"
    issues = lint_report(text, has_verified_proof=False)
    assert any(i.kind == IssueKind.PROOF_CLAIM for i in issues)

    # With a verified proof artifact, the same sentence is acceptable.
    assert not lint_report(text, has_verified_proof=True)


def test_eval002_knowledge_claim_disclaimer_not_flagged() -> None:
    # An explicit absence-of-knowledge statement is honest hedging, not an
    # overclaim — the linter must not flag "it is not known that ...".
    from opentorus.research.dossier.honesty import IssueKind, lint_report

    honest = "It is not known that X holds for every n.\n"
    issues = lint_report(honest, has_reference=False)
    assert not any(i.kind == IssueKind.KNOWLEDGE_CLAIM for i in issues)

    # The affirmative form is still flagged without a cited reference.
    overclaim = "It is known that X holds for every n.\n"
    flagged = lint_report(overclaim, has_reference=False)
    assert any(i.kind == IssueKind.KNOWLEDGE_CLAIM for i in flagged)


def test_eval002_experiment_proves_always_rejected(tmp_path: Path) -> None:
    from opentorus.research.dossier.honesty import IssueKind, lint_report

    text = "The experiment proves the conjecture.\n"
    # Even with a verified proof artifact, "experiment proves" is always wrong.
    issues = lint_report(text, has_verified_proof=True)
    assert any(i.kind == IssueKind.EXPERIMENT_PROOF for i in issues)


# --- EVAL-003: distinguish theorem / conjecture / observation / sketch --------


def test_eval003_claim_types_are_distinct(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    obs = claims.add_claim(base, pid, claim_type="OBSERVATION", statement="pattern seen")
    conj = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    claims.add_proof_attempt(
        base, pid, title="sketch of X", body="step 1 ... gap here", kind="sketch"
    )

    assert obs.type == "OBSERVATION"
    assert conj.type == "CONJECTURE"
    proofs = store.list_proof_attempts(base, pid)
    assert proofs and proofs[0].status == "sketch"

    report = build_report(base, pid)
    assert "conjecture" in report.lower()
    assert "observation" in report.lower()
    assert "proof sketch" in report.lower() or "sketch" in report.lower()
    assert "step 1" in report
    # A sketch must never appear as a verified proof.
    assert "Verified proofs" in report


def test_eval003_theorem_requires_source(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    with pytest.raises(OpenTorusError):
        claims.add_claim(base, pid, claim_type="THEOREM", statement="A deep theorem")
    # With a source artifact it is allowed.
    thm = claims.add_claim(
        base,
        pid,
        claim_type="THEOREM",
        statement="Brooks' theorem",
        source_artifacts=["PAPER-0001"],
    )
    assert thm.type == "THEOREM"


# --- EVAL-004: failed attempts are kept ---------------------------------------


def test_eval004_failed_attempts_persisted(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    store.add_failed_attempt(
        base,
        pid,
        attempted_method="maximum principle",
        reason_failed="boundary condition not preserved",
        reusable_obstruction=True,
    )
    failed = store.list_failed_attempts(base, pid)
    assert len(failed) == 1
    assert failed[0].reusable_obstruction is True
    report = build_report(base, pid)
    assert "Failed Attempts" in report
    assert "maximum principle" in report


# --- EVAL-005: reproducible experiment manifest -------------------------------


def test_eval005_experiment_manifest_is_reproducible(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    exp = create_experiment(
        base, pid, title="random sweep", command="python3 -c 'print(42)'", random_seed=123
    )
    assert exp.random_seed == 123
    assert exp.python_version
    assert exp.command
    edir = store.dossier_dir(base, pid) / "experiments" / exp.experiment_id
    assert (edir / "manifest.yaml").is_file()
    assert (edir / "run.sh").is_file()

    ran = run_experiment(base, pid, exp.experiment_id)
    assert ran.status == "succeeded"
    assert (edir / "stdout.log").is_file()
    assert "42" in (edir / "stdout.log").read_text()


def test_eval005_randomized_experiment_requires_seed_recorded(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    exp = create_experiment(base, pid, title="seeded", command="true", random_seed=7)
    # run.sh must export the seed so the run is reproducible.
    run_sh = (
        store.dossier_dir(base, pid) / "experiments" / exp.experiment_id / "run.sh"
    ).read_text()
    assert "PYTHONHASHSEED=7" in run_sh


# --- EVAL-006: do not cite nonexistent papers / theorem numbers ---------------


def test_eval006_known_result_requires_source(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    with pytest.raises(OpenTorusError):
        store.add_known_result(base, pid, "It is known that X.")
    kr = store.add_known_result(
        base, pid, "Brooks' theorem bounds chi by Delta.", source_artifacts=["PAPER-0001"]
    )
    assert kr.source_artifacts == ["PAPER-0001"]


def test_eval006_theorem_ref_marks_missing_metadata(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    ref = store.add_theorem_ref(
        base, pid, paper_artifact="PAPER-0001", statement_summary="bound on chromatic number"
    )
    # Missing theorem number / page are explicitly None, never invented.
    assert ref.theorem_number is None
    assert ref.page is None


def test_eval006_reference_fact_requires_source(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    with pytest.raises(OpenTorusError):
        claims.add_claim(base, pid, claim_type="REFERENCE_FACT", statement="It is known that X.")


# --- EVAL-007: counterexample candidate is not verified without artifact ------


def test_eval007_counterexample_candidate_not_auto_verified(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n=5 object refutes X"
    )
    assert cand.type == "COUNTEREXAMPLE_CANDIDATE"
    assert cand.status == "unverified"

    # Cannot create a verified counterexample out of thin air.
    with pytest.raises(OpenTorusError):
        claims.add_claim(base, pid, claim_type="COUNTEREXAMPLE_VERIFIED", statement="n=5 refutes X")
    # Cannot verify the candidate without a real verification artifact.
    with pytest.raises(OpenTorusError):
        claims.verify_counterexample(base, pid, cand.id, verification_artifact="EVID-9999")


def test_eval007_counterexample_verified_with_artifact(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n=5 object refutes X"
    )
    ev, _ = claims.add_evidence(
        base,
        pid,
        cand.id,
        evidence_type="FORMAL_PROOF",
        summary="machine-checked refutation",
        direction="supports",
    )
    verified = claims.verify_counterexample(
        base, pid, cand.id, verification_artifact=ev.id, summary="confirmed"
    )
    assert verified.type == "COUNTEREXAMPLE_VERIFIED"
    assert verified.status == "verified"


def test_eval007_contradicting_formal_evidence_cannot_verify(tmp_path: Path) -> None:
    # A verification-grade artifact that *contradicts* the candidate must not be
    # usable to verify it: only supporting evidence promotes a claim (invariant 2).
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n=5 object refutes X"
    )
    ev, _ = claims.add_evidence(
        base,
        pid,
        cand.id,
        evidence_type="FORMAL_PROOF",
        summary="machine-checked proof that the candidate is NOT a counterexample",
        direction="contradicts",
    )
    with pytest.raises(OpenTorusError):
        claims.verify_counterexample(base, pid, cand.id, verification_artifact=ev.id)


# --- EVAL-008: useful report even when the problem is open --------------------


def test_eval008_report_useful_when_open(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    report = build_report(base, pid)
    assert "## Problem" in report
    assert "## Current Status" in report
    assert "open" in report.lower()
    assert "## Next Actions" in report
    assert "## Honesty Warnings" in report
    # The generated report itself is honest.
    assert not lint_dossier_report(base, pid)


# --- Strategy templates -------------------------------------------------------


def test_all_strategies_have_templates() -> None:
    from opentorus.research.dossier.models import ATTACK_STRATEGIES

    assert set(STRATEGY_TEMPLATES) == set(ATTACK_STRATEGIES)
    for template in STRATEGY_TEMPLATES.values():
        assert template.objective
        assert template.failure_modes


def test_attack_creates_approach_card(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    approach = create_approach(base, pid, "counterexample_search")
    assert approach.strategy == "counterexample_search"
    card = store.dossier_dir(base, pid) / "approaches" / f"{approach.id}.md"
    assert card.is_file()
    assert "Failure modes" in card.read_text()
