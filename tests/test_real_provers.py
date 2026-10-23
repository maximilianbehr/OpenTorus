"""The proof gate against the real checkers (opt-in: ``pytest -m integration``).

The default suite pins the gate with fake ``lean``/``coqc`` scripts; these tests run
the same cases through an installed Rocq/Coq and a Lean + Mathlib project, so the
parts a fake cannot prove — the real ``#print axioms`` / ``Print Assumptions`` output
format, the confined checker, the elaborated-type comparison — are checked too.

Lean needs a built Mathlib project: set ``OPENTORUS_LEAN_PROJECT`` to its directory
(``lake new <dir> math && lake exe cache get``); each cold check takes minutes on a
small machine. Coq needs ``coqc`` on PATH.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from opentorus.research.verifiers.backends import CoqBackend, Lean4Backend

pytestmark = pytest.mark.integration

COQ_CASES = {
    "good": (
        "Theorem t : forall n : nat, n + 0 = n.\nProof. intros n. induction n; simpl; auto. Qed.\n",
        True,
    ),
    "admitted": ("Theorem t : forall n : nat, n * 0 = 1.\nProof. Admitted.\n", False),
    "axiom": ("Axiom bad : False.\nTheorem t : 1 = 2.\nProof. destruct bad. Qed.\n", False),
    "parameter": ("Parameter p : nat.\nTheorem t : p = p.\nProof. reflexivity. Qed.\n", False),
    "wrong": ("Theorem t : 1 = 2.\nProof. reflexivity. Qed.\n", False),
    "section": (
        "Section S.\nVariable n : nat.\nTheorem t : n = n.\nProof. reflexivity. Qed.\nEnd S.\n",
        True,
    ),
}


@pytest.mark.skipif(shutil.which("coqc") is None, reason="coqc not installed")
@pytest.mark.parametrize("name", sorted(COQ_CASES))
def test_real_coq_gate(name: str) -> None:
    source, accepted = COQ_CASES[name]
    result = CoqBackend("coqc", timeout=120).verify(source)
    assert result.accepted is accepted, result.output
    if accepted:
        assert result.axioms == []


def _lean() -> Lean4Backend | None:
    project = os.environ.get("OPENTORUS_LEAN_PROJECT")
    if (
        not project
        or not (Path(project) / "lakefile.lean").exists()
        and not (Path(project) / "lakefile.toml").exists()
    ):
        return None
    if shutil.which("lake") is None:
        return None
    return Lean4Backend(f"env -C {project} lake env lean", timeout=1200)


H = "import Mathlib\n"
LEAN_CASES = {
    "good": (H + "theorem t (n : ℕ) : n + 0 = n := by simp\n", True),
    "classical": (H + "theorem t (p : Prop) : p ∨ ¬p := Classical.em p\n", True),
    "wrong": (H + "theorem t : (1:ℕ) = 2 := by norm_num\n", False),
}


@pytest.mark.parametrize("name", sorted(LEAN_CASES))
def test_real_lean_gate(name: str) -> None:
    backend = _lean()
    if backend is None:
        pytest.skip("set OPENTORUS_LEAN_PROJECT to a built Mathlib project")
    source, accepted = LEAN_CASES[name]
    result = backend.verify(source)
    assert result.accepted is accepted, result.output
    if accepted:
        assert set(result.axioms or []) <= {"propext", "Classical.choice", "Quot.sound"}
