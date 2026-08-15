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


def test_negated_experiment_claim_is_honest_hedging() -> None:
    # The exact phrasing from the first Crouzeix calibration run: this is the
    # wording the linter itself asks for, and it must not be flagged.
    assert lint_report("experiments on KMS matrices support <=2 but do not prove it.\n") == []
    assert lint_report("the simulations cannot prove the bound.\n") == []
    assert lint_report("numerics fail to prove the conjecture.\n") == []
    assert lint_report("this is not numerically proven.\n") == []


def test_affirmative_experiment_claim_still_flagged() -> None:
    issues = lint_report("The experiments prove the conjecture.\n")
    assert [i.kind for i in issues] == [IssueKind.EXPERIMENT_PROOF]
    issues = lint_report("numerically proven for all n.\n")
    assert [i.kind for i in issues] == [IssueKind.EXPERIMENT_PROOF]


def test_trivial_as_classifier_noun_phrase_is_not_weasel() -> None:
    # "the trivial family (X-a)^d" names an object; it does not wave away a step.
    assert lint_report("the variety is contained in the trivial family.\n") == []
    assert lint_report("only the trivial solution remains.\n") == []


def test_dismissive_trivial_still_flagged() -> None:
    assert [i.kind for i in lint_report("the proof is trivial.\n")] == [IssueKind.WEASEL]
    assert [i.kind for i in lint_report("trivially, the bound holds.\n")] == [IssueKind.WEASEL]


def test_result_claim_with_local_citation_is_attributed() -> None:
    # Reporting a literature result with its local source on the same line is
    # honest; the citation-grounding check validates the theorem number.
    line = "the conjecture is proved for d = p^k; PAPER-0004 Theorem 3.\n"
    assert lint_report(line) == []


def test_result_claim_without_citation_still_flagged() -> None:
    issues = lint_report("the conjecture is proved for d = p^k.\n")
    assert [i.kind for i in issues] == [IssueKind.RESULT_CLAIM]


def test_first_person_result_claim_not_laundered_by_citation() -> None:
    issues = lint_report("we proved the conjecture, see PAPER-0004.\n")
    assert IssueKind.RESULT_CLAIM in [i.kind for i in issues]


def test_referee_finding_quotes_are_not_relinted() -> None:
    echo = (
        "- [REFEREE] Unsupported result_claim at PROOF-0001 body: 'is proved'. "
        "No supported THEOREM backs this result-assertion.\n"
    )
    assert lint_report(echo) == []


def test_overclaim_outside_referee_quotes_still_flagged() -> None:
    line = "- [REFEREE] finding resolved: 'old text' — hence the conjecture is proved.\n"
    issues = lint_report(line)
    assert IssueKind.RESULT_CLAIM in [i.kind for i in issues]


def test_fenced_code_blocks_are_not_linted() -> None:
    # A Coq template echoed into the report ends in "Qed." — verbatim material,
    # not an assertion (found by the strassen-formal calibration run).
    text = (
        "Formalization template:\n"
        "```coq\n"
        "Lemma strassen_correct : forall a b, mul a b = strassen a b.\n"
        "Proof. ring. Qed.\n"
        "we prove the conjecture (template comment)\n"
        "```\n"
        "The template above is unverified.\n"
    )
    assert lint_report(text) == []


def test_overclaim_after_fence_close_still_flagged() -> None:
    text = "```\nQed.\n```\nWe prove the conjecture.\n"
    issues = lint_report(text)
    assert [i.kind for i in issues] == [IssueKind.PROOF_CLAIM]


def test_inline_code_does_not_hide_overclaims() -> None:
    issues = lint_report("as `we prove the conjecture` shows.\n")
    assert IssueKind.PROOF_CLAIM in [i.kind for i in issues]


def test_attributed_proof_claims_are_literature_reporting() -> None:
    # Class 6 (lonely-runner smoke run): "X proves the conjecture for k=7; PAPER-NNNN"
    # is cited literature reporting, not a self-claim.
    line = "Rosenfeld proves the conjecture for k=7 by computer verification. PAPER-0002 p.1.\n"
    assert lint_report(line) == []
    line = "Barajas-Serra prove the conjecture for k=6 via p-adic valuations; PAPER-0001.\n"
    assert lint_report(line) == []


def test_self_proof_claims_not_laundered_by_citation() -> None:
    issues = lint_report("we prove the conjecture, following PAPER-0002.\n")
    assert IssueKind.PROOF_CLAIM in [i.kind for i in issues]
    issues = lint_report("proves the conjecture\n")  # no citation on the line
    assert [i.kind for i in issues] == [IssueKind.PROOF_CLAIM]


def test_sketch_open_conjecture_warning_is_attribution_aware() -> None:
    from opentorus.research.dossier.nl_proof import lint_proof_sketch

    cited = "The conjecture holds for k=8 i.e. nine runners; PAPER-0004 Key results p.1."
    assert lint_proof_sketch(cited, open_problem=True) == []
    bare = "Therefore the conjecture holds in general."
    warnings = lint_proof_sketch(bare, open_problem=True)
    assert any("appears to resolve" in w for w in warnings)
