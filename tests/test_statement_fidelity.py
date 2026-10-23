"""Statement fidelity: a formal proof verifies a claim only if it proves *that* claim.

Before frozen statements, any accepted Lean file could be cited for any claim — the
checker says some theorem is proved, nothing said it was the claim. These tests pin:

* a frozen statement (FSTMT-*) binds nothing until a human accepts it, and its digest
  is re-checked at acceptance;
* without an accepted frozen statement, an accepted Lean proof is *support* (a
  ``supports`` edge) and can never promote a claim to ``formally_verified``;
* against a frozen statement, a proof of the wrong theorem, a changed preamble, or a
  different elaborated type is rejected; the matching proof is statement-bound and
  promotes (workspace ladder and dossier FORMAL_PROOF evidence alike).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.config import default_config
from opentorus.errors import OpenTorusError
from opentorus.research.claims import new_claim, update_claim
from opentorus.research.dossier import claims as dclaims
from opentorus.research.dossier import store
from opentorus.research.graph import related
from opentorus.research.verifiers.backends import Lean4Backend
from opentorus.research.verifiers.proofs import accepted_proof_for_claim, submit_proof
from opentorus.research.verifiers.statements import (
    accept_statement,
    get_statement,
    propose_statement,
    record_pristine_type,
    statement_source,
)
from opentorus.tools.base import ToolCall
from opentorus.tools.research import ProofSubmitTool
from opentorus.workspace import init_workspace, workspace_dir
from support.fake_lean import fake_lean_command

FROZEN = """import Mathlib

def double (n : Nat) : Nat := 2 * n

theorem double_even (n : Nat) : double n % 2 = 0 := by
  sorry
"""

GOOD = """import Mathlib

def double (n : Nat) : Nat := 2 * n

theorem double_even (n : Nat) : double n % 2 = 0 := by
  unfold double
  omega
"""

WRONG_THEOREM = """import Mathlib

def double (n : Nat) : Nat := 2 * n

theorem double_even (n : Nat) : double 0 % 2 = 0 := by
  rfl
"""

CHANGED_PREAMBLE = """import Mathlib

def double (n : Nat) : Nat := 0

theorem double_even (n : Nat) : double n % 2 = 0 := by
  rfl
"""


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _lean(tmp_path: Path) -> Lean4Backend:
    return Lean4Backend(fake_lean_command(tmp_path))


def _freeze(ot: Path, claim_id: str, problem_id: str | None = None) -> str:
    rec = propose_statement(ot, "lean4", FROZEN, claim_id=claim_id, problem_id=problem_id)
    accept_statement(ot, rec.id, confirm=lambda _r: True, accepted_by="tester")
    return rec.id


def _submit(ot: Path, tmp_path: Path, source: str, claim_id: str, **kw):  # noqa: ANN202
    return submit_proof(
        ot, default_config(), "lean4", source, claim_id=claim_id, verifier=_lean(tmp_path), **kw
    )


# --- the artifact --------------------------------------------------------------


def test_frozen_statement_must_be_a_sorry_placeholder(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    with pytest.raises(OpenTorusError, match="sorry"):
        propose_statement(ot, "lean4", GOOD, claim_id=claim.id)
    with pytest.raises(OpenTorusError, match="exactly one theorem"):
        propose_statement(
            ot,
            "lean4",
            "theorem a : True := trivial\ntheorem b : True := sorry",
            claim_id=claim.id,
        )
    with pytest.raises(OpenTorusError, match="forbidden"):
        propose_statement(ot, "lean4", "#eval 1\ntheorem a : True := sorry", claim_id=claim.id)


def test_proposed_statement_binds_nothing_until_human_acceptance(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    rec = propose_statement(ot, "lean4", FROZEN, claim_id=claim.id, proposed_by="agent")
    assert rec.status == "proposed" and len(rec.sha256) == 64
    attempt = _submit(ot, tmp_path, GOOD, claim.id)
    assert attempt.accepted and not attempt.statement_bound
    with pytest.raises(OpenTorusError, match="human confirmation"):
        accept_statement(ot, rec.id, confirm=None)
    with pytest.raises(OpenTorusError, match="human confirmation"):
        accept_statement(ot, rec.id, confirm=lambda _r: False)
    assert get_statement(ot, rec.id).status == "proposed"  # type: ignore[union-attr]


def test_edited_statement_source_cannot_be_accepted(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    rec = propose_statement(ot, "lean4", FROZEN, claim_id=claim.id)
    (ot / rec.source_path).write_text(FROZEN.replace("2 * n", "0"), encoding="utf-8")
    with pytest.raises(OpenTorusError, match="sha256"):
        accept_statement(ot, rec.id, confirm=lambda _r: True)


# --- without a frozen statement: support only ----------------------------------


def test_unbound_lean_proof_is_support_and_cannot_promote(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    attempt = _submit(ot, tmp_path, GOOD, claim.id)
    assert attempt.accepted is True
    assert attempt.statement_bound is False
    edges = related(ot, attempt.id)
    assert any(e.relation == "supports" for e in edges)
    assert not any(e.relation == "validates" for e in edges)
    assert accepted_proof_for_claim(ot, claim.id) is None
    with pytest.raises(OpenTorusError, match="frozen formal statement"):
        update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)


# --- against a frozen statement ------------------------------------------------


def test_wrong_theorem_proof_cannot_verify_the_claim(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    _freeze(ot, claim.id)
    attempt = _submit(ot, tmp_path, WRONG_THEOREM, claim.id)
    assert attempt.accepted is False
    assert attempt.rejection == "statement_mismatch"
    with pytest.raises(OpenTorusError):
        update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)


def test_statement_only_in_a_comment_does_not_count(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    _freeze(ot, claim.id)
    commented = WRONG_THEOREM + ("\n/- theorem double_even (n : Nat) : double n % 2 = 0 := -/\n")
    attempt = _submit(ot, tmp_path, commented, claim.id)
    assert attempt.accepted is False and attempt.rejection == "statement_mismatch"


def test_redefined_preamble_is_rejected(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    _freeze(ot, claim.id)
    attempt = _submit(ot, tmp_path, CHANGED_PREAMBLE, claim.id)
    assert attempt.accepted is False
    assert attempt.rejection == "preamble_mismatch"


def test_different_elaborated_type_is_rejected(tmp_path: Path) -> None:
    # Same surface text, different meaning (e.g. a notation or coercion resolved
    # differently): simulated by a pristine type the candidate does not reproduce.
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    sid = _freeze(ot, claim.id)
    version = _lean(tmp_path).version()
    record_pristine_type(ot, sid, "double_even : ∀ (n : ℕ), double n % 2 = 1", version)
    attempt = _submit(ot, tmp_path, GOOD, claim.id)
    assert attempt.accepted is False
    assert attempt.rejection == "type_mismatch"


def test_matching_proof_is_statement_bound_and_promotes(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    sid = _freeze(ot, claim.id)
    attempt = _submit(ot, tmp_path, GOOD, claim.id)
    assert attempt.accepted is True, attempt.output
    assert attempt.statement_bound is True
    assert attempt.statement_id == sid
    # The pristine type was computed once and cached on the statement.
    assert get_statement(ot, sid).pristine_type  # type: ignore[union-attr]
    assert any(e.relation == "validates" for e in related(ot, attempt.id))
    promoted = update_claim(ot, claim.id, status="formally_verified", confirm=lambda a, b: True)
    assert promoted.status == "formally_verified"


def test_sorry_against_frozen_statement_is_still_rejected(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    sid = _freeze(ot, claim.id)
    frozen = statement_source(ot, get_statement(ot, sid))  # type: ignore[arg-type]
    attempt = _submit(ot, tmp_path, frozen, claim.id)
    assert attempt.accepted is False and attempt.rejection == "sorry"


def test_statement_for_another_claim_does_not_bind(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    other = new_claim(ot, "something else")
    _freeze(ot, other.id)
    attempt = _submit(ot, tmp_path, GOOD, claim.id)
    assert attempt.accepted and not attempt.statement_bound
    assert accepted_proof_for_claim(ot, claim.id) is None


# --- dossier claims --------------------------------------------------------------


def test_dossier_formal_proof_evidence_requires_a_bound_proof(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    pid = store.create_dossier(ot, "double n is even").id
    claim = dclaims.add_claim(ot, pid, claim_type="CONJECTURE", statement="double n is even")
    unbound = _submit(ot, tmp_path, GOOD, claim.id, submitted_under=pid)
    with pytest.raises(OpenTorusError, match="frozen formal statement"):
        dclaims.add_evidence(
            ot,
            pid,
            claim.id,
            evidence_type="FORMAL_PROOF",
            summary="lean",
            source_artifacts=[unbound.id],
        )
    _freeze(ot, claim.id, problem_id=pid)
    bound = _submit(ot, tmp_path, GOOD + "\n-- v2\n", claim.id, submitted_under=pid)
    assert bound.statement_bound is True, bound.output
    ev, _ = dclaims.add_evidence(
        ot,
        pid,
        claim.id,
        evidence_type="FORMAL_PROOF",
        summary="lean, statement-bound",
        source_artifacts=[bound.id],
    )
    assert ev.id


# --- the agent tool ------------------------------------------------------------------


def test_proof_submit_tool_reports_binding(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    tool = ProofSubmitTool(ot, default_config(), resolver=lambda _n: _lean(tmp_path))
    call = ToolCall(
        name="proof_submit", args={"backend": "lean4", "source": GOOD, "claim_id": claim.id}
    )
    unbound = tool.run(call)
    assert unbound.ok is True
    assert "SUPPORT" in unbound.content
    _freeze(ot, claim.id)
    call2 = ToolCall(
        name="proof_submit",
        args={"backend": "lean4", "source": GOOD + "\n", "claim_id": claim.id},
    )
    bound = tool.run(call2)
    assert bound.ok is True
    assert "Statement-bound" in bound.content
    wrong = tool.run(
        ToolCall(
            name="proof_submit",
            args={"backend": "lean4", "source": WRONG_THEOREM, "claim_id": claim.id},
        )
    )
    assert wrong.ok is False
    assert "statement_mismatch" in wrong.content


# --- the CLI -----------------------------------------------------------------------


def test_cli_statement_add_accept_list(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    ot = _ot(tmp_path)
    claim = new_claim(ot, "double n is even")
    frozen = tmp_path / "frozen.lean"
    frozen.write_text(FROZEN, encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    res = runner.invoke(app, ["proof", "statement", "add", str(frozen), "--claim", claim.id])
    assert res.exit_code == 0, res.output
    assert "FSTMT-0001 proposed" in res.output
    # Declining the interactive prompt leaves it proposed.
    res = runner.invoke(app, ["proof", "statement", "accept", "FSTMT-0001"], input="n\n")
    assert res.exit_code == 1
    assert get_statement(ot, "FSTMT-0001").status == "proposed"  # type: ignore[union-attr]
    res = runner.invoke(app, ["proof", "statement", "accept", "FSTMT-0001"], input="y\n")
    assert res.exit_code == 0, res.output
    assert get_statement(ot, "FSTMT-0001").status == "accepted"  # type: ignore[union-attr]
    res = runner.invoke(app, ["proof", "statement", "list"])
    assert "double_even" in res.output


def test_coq_statement_binding(tmp_path: Path) -> None:
    from opentorus.research.verifiers.backends import CoqBackend
    from support.fake_lean import fake_coq_command

    ot = _ot(tmp_path)
    claim = new_claim(ot, "n + 0 = n")
    frozen = "Theorem add_zero : forall n : nat, n + 0 = n.\nProof. Admitted.\n"
    rec = propose_statement(ot, "coq", frozen, claim_id=claim.id)
    accept_statement(ot, rec.id, confirm=lambda _r: True)
    coq = CoqBackend(fake_coq_command(tmp_path))

    def submit(src: str):  # noqa: ANN202
        return submit_proof(ot, default_config(), "coq", src, claim_id=claim.id, verifier=coq)

    wrong = submit("Theorem add_zero : 0 + 0 = 0.\nProof. reflexivity. Qed.\n")
    assert wrong.accepted is False and wrong.rejection == "statement_mismatch"
    good = submit(
        "Theorem add_zero : forall n : nat, n + 0 = n.\nProof. intros n. induction n; auto. Qed.\n"
    )
    assert good.accepted is True, good.output
    assert good.statement_bound is True
    assert accepted_proof_for_claim(ot, claim.id) is not None
