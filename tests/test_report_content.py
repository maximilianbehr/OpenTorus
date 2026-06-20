"""Tests for the enriched dossier report (summary, badges, inline honesty, map)."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.report import build_report, lint_dossier_report
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: every widget folds.", domain="demo")
    return base, d.id


def test_report_has_executive_summary(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="All widgets fold.")
    claims.add_evidence(base, pid, c.id, evidence_type="EXPERIMENT", summary="held to 1e4")
    report = build_report(base, pid, harvest_session=False)
    assert "## Summary" in report
    assert "**Claims:**" in report
    assert "Verified results:** none" in report
    assert "does not verify them" in report  # honest disclaimer


def test_explicit_gaps_captures_inline_described_markers() -> None:
    # A gap written as "[GAP-n: description]" (colon + text inside the brackets)
    # must be extracted, not just the bare "[GAP-n]" form.
    from opentorus.research.dossier.nl_proof import explicit_gaps

    body = (
        "The bound is plausible [GAP-1: Quantitative bound on $\\kappa(V)$ vs $n$].\n"
        "The Hermitian case [GAP-2: Formal proof for specific decay rates]."
    )
    gaps = explicit_gaps(gaps=[], body=body)
    assert len(gaps) == 2
    assert any("GAP-1: Quantitative bound" in g for g in gaps)
    # Ordinary bracketed prose mentioning the spectral "gap" must NOT be captured.
    assert explicit_gaps(gaps=[], body="the [gap between eigenvalues] is small") == []


def test_report_reports_gap_markers_present_in_proof_body(tmp_path: Path) -> None:
    # Regression: a proof body containing [GAP-n: ...] markers but an empty stored
    # gaps list must still be reported — the report reconciles gaps from the prose
    # so a gap-laden body can never render with "no gaps reported".
    base, pid = _problem(tmp_path)
    claims.add_proof_attempt(
        base,
        pid,
        title="Conditioning sketch",
        body=(
            "For random matrices the basis becomes compressed. "
            "[GAP-1: Quantitative bound on $\\kappa(V)$ vs $n$ for random matrices].\n\n"
            "For Hermitian matrices the basis is better conditioned. "
            "[GAP-2: Formal proof that $\\kappa(V) \\approx 1$ for specific decay rates]."
        ),
        gaps=[],  # write-time extractor missed the described markers
    )
    report = build_report(base, pid, harvest_session=False)
    assert "**Gaps recorded:** 2" in report
    assert "GAP-1: Quantitative bound" in report


def test_report_claim_badge_and_settle_hint(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="All widgets fold.")
    claims.add_evidence(
        base, pid, c.id, evidence_type="EXPERIMENT", summary="a", direction="supports"
    )
    claims.add_evidence(
        base, pid, c.id, evidence_type="COMPUTATION", summary="b", direction="contradicts"
    )
    report = build_report(base, pid, harvest_session=False)
    assert "**Evidence strength:** 1 supporting, 1 contradicting" in report
    assert "**To settle:**" in report
    assert "support only — never a proof" in report


def test_report_epistemic_map_is_present(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X.")
    ev, _ = claims.add_evidence(base, pid, c.id, evidence_type="EXPERIMENT", summary="s")
    report = build_report(base, pid, harvest_session=False)
    assert "## Epistemic Map" in report
    assert "```mermaid" in report
    assert f"{ev.id} -->|supports| {c.id}" in report


def test_report_inline_honesty_flags_overclaiming_statement(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    # An overclaiming statement should be flagged inline in its own claim block.
    claims.add_claim(base, pid, claim_type="OBSERVATION", statement="This is obviously true.")
    report = build_report(base, pid, harvest_session=False)
    assert "⚠ **Honesty:**" in report


def test_enriched_report_is_still_honest(tmp_path: Path) -> None:
    # The new sections must not introduce overclaiming language of their own.
    base, pid = _problem(tmp_path)
    claims.add_claim(base, pid, claim_type="CONJECTURE", statement="A neutral statement.")
    build_report(base, pid, harvest_session=False)
    assert not lint_dossier_report(base, pid)
