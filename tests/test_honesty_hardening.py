"""Tests for honesty/DLP hardening: evasion resistance, heading lint, per-claim scope."""

from __future__ import annotations

from pathlib import Path

from opentorus.governance import scan_secrets
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.honesty import IssueKind, lint_report
from opentorus.research.dossier.report import _claim_honesty_context
from opentorus.research.honesty import lint_text
from opentorus.textnorm import normalize_for_scan
from opentorus.workspace import init_workspace, workspace_dir


def test_normalizer_folds_zero_width_and_homoglyphs() -> None:
    assert normalize_for_scan("pr​oven") == "proven"
    assert normalize_for_scan("prоven") == "proven"  # Cyrillic 'о'
    assert normalize_for_scan("we­prove") == "weprove"  # soft hyphen removed


def test_zero_width_evasion_flagged_global_linter() -> None:
    # "we pr<ZWSP>ove" must still be caught after normalization.
    issues = lint_text("We pr​ove the bound.")
    assert any("prove" in i.phrase.lower() for i in issues)


def test_homoglyph_evasion_flagged_global_linter() -> None:
    issues = lint_text("We prоve the bound.")  # Cyrillic 'о'
    assert any("prove" in i.phrase.lower() for i in issues)


def test_heading_overclaim_flagged_dossier_linter() -> None:
    # A heading is no longer a free pass for overclaiming language.
    issues = lint_report("# We prove the conjecture\n")
    assert any(i.kind == IssueKind.PROOF_CLAIM for i in issues)


def test_dossier_linter_folds_zero_width() -> None:
    issues = lint_report("We pr​ove that X holds.\n")
    assert any(i.kind == IssueKind.PROOF_CLAIM for i in issues)


def test_scan_secrets_resists_zero_width_split() -> None:
    key = "sk-" + "A" * 30
    split = "sk-" + "A" * 15 + "​" + "A" * 15  # zero-width in the middle
    assert scan_secrets(key)  # baseline
    assert scan_secrets(split), "zero-width-split key must still be detected"


def test_scan_secrets_resists_homoglyph() -> None:
    # 'Аpassword: hunter2longenough' with a Cyrillic 'А' prefix should still match.
    assert scan_secrets("аpi_key: s3cret_value_here")


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    return base, store.create_dossier(base, "A conjecture about X.").id


def test_per_claim_honesty_context_is_local(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    # Claim A: backed by a verification-grade FORMAL_PROOF evidence -> proved.
    a = claims.add_claim(base, pid, claim_type="CLAIM", statement="A is true")
    ev, _ = claims.add_evidence(
        base, pid, a.id, evidence_type="FORMAL_PROOF", summary="checked", direction="supports"
    )
    # Claim B: unproven.
    b = claims.add_claim(base, pid, claim_type="CONJECTURE", statement="B is open")

    a = store.get_claim(base, pid, a.id)
    b = store.get_claim(base, pid, b.id)
    a_proof, _, _ = _claim_honesty_context(a, [ev], [])
    b_proof, _, b_thm = _claim_honesty_context(b, [], [])
    assert a_proof is True  # A's own verification licenses A
    assert b_proof is False  # A's proof must NOT license B
    assert b_thm is False
