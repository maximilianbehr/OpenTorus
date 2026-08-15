"""Tests for the hostile referee (post-proof integrity stage)."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.referee import latest_referee, referee_review
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    dossier = store.create_dossier(base, "A conjecture about objects X.", domain="test")
    return base, dossier.id


def test_referee_recommends_downgrade_for_unsupported_theorem_like(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    # A CLAIM (theorem-like) with no evidence and no source is unsupported.
    c = claims.add_claim(base, pid, claim_type="CLAIM", statement="Y is true for all inputs")
    rep = referee_review(base, pid)
    assessment = next(a for a in rep.assessments if a.claim_id == c.id)
    assert assessment.classification == "unsupported"
    assert assessment.recommended_type == "CONJECTURE"
    assert rep.downgrades_recommended
    assert rep.verdict in ("revise", "block")


def test_referee_classifies_cited_theorem(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    thm = claims.add_claim(
        base, pid, claim_type="THEOREM", statement="A cited bound", source_artifacts=["PAPER-0001"]
    )
    rep = referee_review(base, pid)
    assessment = next(a for a in rep.assessments if a.claim_id == thm.id)
    assert assessment.classification == "cited"
    assert assessment.recommended_type is None


def test_referee_flags_overclaim_and_blocks(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_proof_attempt(
        base, pid, title="bad sketch", body="We prove that X holds for every n. QED.", kind="sketch"
    )
    rep = referee_review(base, pid)
    assert rep.overclaims
    assert any(o.kind in ("proof_claim", "result_claim") for o in rep.overclaims)
    assert rep.verdict == "block"


def test_referee_detects_contradiction(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    claims.add_evidence(
        base,
        pid,
        c.id,
        evidence_type="EXPERIMENT",
        summary="a counterexample",
        direction="contradicts",
    )
    rep = referee_review(base, pid)
    assert rep.contradictions
    assert rep.verdict == "block"


def test_referee_apply_downgrades_mutates_ledger(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CLAIM", statement="Y is true")
    referee_review(base, pid, apply_downgrades=True)
    updated = store.get_claim(base, pid, c.id)
    assert updated is not None
    assert updated.type == "CONJECTURE"
    assert updated.status == "needs_review"
    # The downgrade is logged, not silent.
    changes = store.list_status_changes(base, pid)
    assert any(ch.claim_id == c.id for ch in changes)


def test_referee_persisted_and_latest(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds")
    rep = referee_review(base, pid)
    rdir = store.dossier_dir(base, pid) / "referee"
    assert (rdir / f"{rep.id}.json").is_file()
    assert (rdir / f"{rep.id}.md").is_file()
    latest = latest_referee(base, pid)
    assert latest is not None and latest.id == rep.id


def test_referee_passes_clean_cited_dossier(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    thm = claims.add_claim(
        base,
        pid,
        claim_type="THEOREM",
        statement="A cited bound from the literature",
        source_artifacts=["PAPER-0001"],
    )
    claims.add_evidence(
        base, pid, thm.id, evidence_type="PAPER", summary="matches the paper", direction="supports"
    )
    rep = referee_review(base, pid)
    assert not rep.contradictions
    assert not rep.overclaims
    assert rep.verdict == "pass"


def _write_statement(base: Path, pid: str, text: str) -> None:
    (store.dossier_dir(base, pid) / "statement.md").write_text(text, encoding="utf-8")


def test_formalization_demand_without_submission_blocks(tmp_path: Path) -> None:
    # Stage 2 of the proof_submit anchoring: a statement that explicitly demands
    # machine-checking via proof_submit blocks until a submission is ACCEPTED.
    base, pid = _problem(tmp_path)
    _write_statement(
        base, pid, "# Task\nSubmit every finite check via proof_submit (sympy backend).\n"
    )
    rep = referee_review(base, pid)
    finding = [o for o in rep.overclaims if o.kind == "formalization_required"]
    assert finding and rep.verdict == "block"
    assert "proof_submit" in finding[0].suggestion

    # The finding reopens as a [REFEREE] gap so it lives in the proof artifact.
    from opentorus.agent.prove_loop import referee_block_gaps

    gaps = referee_block_gaps(rep)
    assert any("formalization_required" in g for g in gaps)


def test_formalization_demand_cleared_by_accepted_submission(tmp_path: Path) -> None:
    from opentorus.config import default_config
    from opentorus.research.verifiers import submit_proof
    from opentorus.research.verifiers.base import VerificationResult

    base, pid = _problem(tmp_path)
    _write_statement(base, pid, "Machine-check the core via proof_submit.\n")

    class _Accepting:
        name = "stub"

        def is_available(self) -> bool:
            return True

        def version(self) -> str | None:
            return "stub-1.0"

        def verify(self, source: str) -> VerificationResult:
            return VerificationResult(backend=self.name, accepted=True, output="QED")

    submit_proof(base, default_config(), "sympy", "certificate", verifier=_Accepting())
    rep = referee_review(base, pid)
    assert not [o for o in rep.overclaims if o.kind == "formalization_required"]


def test_no_formalization_demand_no_finding(tmp_path: Path) -> None:
    # Ordinary dossiers (statement never names proof_submit) are unaffected.
    base, pid = _problem(tmp_path)
    _write_statement(base, pid, "# Task\nSurvey the status of the conjecture.\n")
    rep = referee_review(base, pid)
    assert not [o for o in rep.overclaims if o.kind == "formalization_required"]
    assert rep.verdict == "pass"
