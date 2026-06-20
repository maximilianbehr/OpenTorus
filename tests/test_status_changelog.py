"""Tests for the epistemic status-change changelog."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.report import build_report
from opentorus.workspace import init_workspace, workspace_dir


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    d = store.create_dossier(base, "Conjecture: X.", domain="demo")
    return base, d.id


def test_evidence_logs_status_transition(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds.")
    assert store.list_status_changes(base, pid) == []
    ev, _ = claims.add_evidence(base, pid, c.id, evidence_type="EXPERIMENT", summary="s")
    changes = store.list_status_changes(base, pid)
    assert len(changes) == 1
    assert changes[0].from_status == "unverified"
    assert changes[0].to_status == "supported"
    assert changes[0].artifact == ev.id


def test_contradiction_logs_transition(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X holds.")
    claims.add_evidence(
        base, pid, c.id, evidence_type="EXPERIMENT", summary="c", direction="contradicts"
    )
    changes = store.list_status_changes(base, pid)
    assert changes[-1].to_status == "contradicted"


def test_counterexample_verification_logs_transition(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n=5 refutes X."
    )
    ev, _ = claims.add_evidence(
        base, pid, cand.id, evidence_type="FORMAL_PROOF", summary="machine-checked"
    )
    claims.verify_counterexample(base, pid, cand.id, verification_artifact=ev.id)
    changes = store.list_status_changes(base, pid)
    assert any(
        ch.to_status == "verified" and ch.reason == "counterexample verified" for ch in changes
    )


def test_report_includes_changelog_section(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    c = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="X.")
    claims.add_evidence(base, pid, c.id, evidence_type="EXPERIMENT", summary="s")
    report = build_report(base, pid, harvest_session=False)
    assert "## Status Changelog" in report
    assert "unverified → supported" in report
