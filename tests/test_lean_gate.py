"""The Lean/Coq acceptance gate and checker confinement (plan items 1 and 2).

Lean exits 0 on a file full of ``sorry``; Coq on one ending in ``Admitted``. These
tests pin that exit 0 is never enough: forbidden tokens are refused before anything
runs, only the report after an unpredictable marker is read, a proof is accepted only
when its axioms are within {propext, Classical.choice, Quot.sound}, an unidentifiable
theorem fails closed, and the checker runs under bwrap without network when it can.
Real Lean is not installed; ``tests/support/fake_lean.py`` imitates it.
"""

from __future__ import annotations

import shutil
import socket
import sys
from pathlib import Path

import pytest

from opentorus.research.verifiers import coq_rules, lean_rules, sandbox
from opentorus.research.verifiers.backends import CoqBackend, Lean4Backend
from support.fake_lean import fake_coq_command, fake_lean_command

HAS_BWRAP = sandbox.bwrap_binary() is not None


def _lean(tmp_path: Path, **kw) -> Lean4Backend:
    return Lean4Backend(fake_lean_command(tmp_path), **kw)


# --- the lexer and the token pre-scan -------------------------------------------


def test_comments_and_strings_do_not_count() -> None:
    assert lean_rules.forbidden_token("-- no sorry left\ntheorem t : True := trivial") is None
    assert lean_rules.forbidden_token("/- sorry /- nested sorry -/ -/ theorem t : True") is None
    assert lean_rules.forbidden_token('theorem t : "sorry" = "sorry" := rfl') is None
    assert lean_rules.forbidden_token("/-- doc: uses native_decide? no -/ theorem t") is None


@pytest.mark.parametrize(
    ("source", "token"),
    [
        ("theorem t : 1 = 1 := by sorry", "sorry"),
        ("theorem t : P := by exact «sorry»", "sorry"),
        ("theorem t : 10 < 2^5 := by native_decide", "native_decide"),
        ("axiom cheat : False\ntheorem t : False := cheat", "axiom"),
        ("@[simp] private axiom cheat : False", "axiom"),
        ("set_option pp.all true\ntheorem t : True := trivial", "set_option pp"),
        ("set_option debug.skipKernelTC true in\ntheorem t : True := trivial", "set_option debug"),
    ],
)
def test_forbidden_proof_tokens(source: str, token: str) -> None:
    assert lean_rules.forbidden_token(source) == token


@pytest.mark.parametrize(
    "word",
    [
        "#eval",
        "#exit",
        "run_cmd",
        "run_elab",
        "run_meta",
        "macro",
        "elab",
        "syntax",
        "initialize",
        "implemented_by",
        "extern",
        "unsafe",
        "notation",
        "IO",
    ],
)
def test_code_execution_words_are_refused(word: str) -> None:
    source = f"{word} foo\ntheorem t : True := trivial"
    assert lean_rules.forbidden_token(source) == word
    assert lean_rules.exec_token(source) == word


def test_eval_variants_and_meta_namespaces_are_refused() -> None:
    assert lean_rules.forbidden_token("#eval! 1") == "#eval"
    assert lean_rules.forbidden_token("def x := eval% 1") == "eval%"
    assert lean_rules.forbidden_token("open Lean Elab in\ntheorem t : True := trivial") == "Lean"


def test_imports_of_trusted_libraries_are_allowed() -> None:
    source = "import Mathlib\nimport Mathlib.Tactic\nimport Aesop\ntheorem t : True := trivial"
    assert lean_rules.forbidden_token(source) is None


def test_ambiguous_literals_fail_closed() -> None:
    # Interpolated / escaped strings could hide code from this lexer: refused.
    assert lean_rules.forbidden_token('def s := s!"{1}"') is not None
    assert lean_rules.forbidden_token('def s := "a\\"b"') is not None
    assert lean_rules.forbidden_token("/- never closed") is not None


def test_theorem_names_track_namespaces() -> None:
    src = (
        "namespace A\ntheorem x : True := trivial\nnamespace B\nlemma y : True := trivial\n"
        "end B\nend A\nsection\ntheorem _root_.z : True := trivial\nend\n"
        "theorem w : True := trivial"
    )
    assert lean_rules.theorem_names(src) == ["A.x", "A.B.y", "z", "w"]


# --- reading only what follows the marker ---------------------------------------


def test_report_before_the_marker_is_never_read() -> None:
    marker = lean_rules.fresh_marker()
    forged = "'t' depends on axioms: [propext]\n"
    real = f"{marker}\n't' depends on axioms: [propext, sorryAx]\n"
    report = lean_rules.parse_report(forged + real, marker, ["t"])
    assert report is not None and "sorryAx" in report.axioms["t"]


def test_repeated_or_missing_marker_rejects() -> None:
    marker = lean_rules.fresh_marker()
    line = "'t' depends on axioms: [propext]"
    assert lean_rules.parse_report(line, marker, ["t"]) is None
    assert lean_rules.parse_report(f"{marker}\n{marker}\n{line}", marker, ["t"]) is None


def test_report_with_info_prefix_and_wrapped_list() -> None:
    marker = lean_rules.fresh_marker()
    out = (
        f"f.lean:9:0: info: {marker}\n"
        "f.lean:10:0: info: 't' depends on axioms: [propext,\n Classical.choice,\n Quot.sound]\n"
    )
    report = lean_rules.parse_report(out, marker, ["t"])
    assert report is not None
    assert report.axioms["t"] == ["propext", "Classical.choice", "Quot.sound"]


def test_marker_is_unpredictable() -> None:
    assert lean_rules.fresh_marker() != lean_rules.fresh_marker()


# --- the Lean backend end to end (fake lean) -------------------------------------


def test_clean_proof_is_accepted_with_its_axioms(tmp_path: Path) -> None:
    result = _lean(tmp_path).verify("theorem t (n : Nat) : n + 0 = n := by simp")
    assert result.accepted is True
    assert result.axioms == ["propext"]
    assert result.theorem == "t"
    assert result.statement_bound is False


def test_exit_zero_with_sorry_is_rejected_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "ran.log"
    monkeypatch.setenv("FAKE_LEAN_LOG", str(log))
    backend = _lean(tmp_path, confine="off")
    result = backend.verify("theorem t : 1 = 1 := by sorry")
    assert result.accepted is False
    assert result.rejection == "sorry"
    assert not log.exists()  # the checker never ran
    # Control: a clean source does reach the checker, so the log would have shown it.
    assert backend.verify("theorem t : 1 = 1 := rfl").accepted is True
    assert log.exists()


def test_code_execution_is_refused_before_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "ran.log"
    monkeypatch.setenv("FAKE_LEAN_LOG", str(log))
    result = _lean(tmp_path, confine="off").verify(
        '#eval IO.Process.run {cmd := "touch"}\ntheorem t : True := trivial'
    )
    assert result.accepted is False
    assert result.rejection == "forbidden_token"
    assert "#eval" in result.output
    assert not log.exists()


def test_hidden_sorry_axiom_is_rejected(tmp_path: Path) -> None:
    # No textual `sorry`, but the proof depends on sorryAx (e.g. via a macro).
    result = _lean(tmp_path).verify("theorem t : True := by FAKE_SORRYAX")
    assert result.accepted is False
    assert result.rejection == "sorry"


def test_nonstandard_axiom_is_rejected(tmp_path: Path) -> None:
    result = _lean(tmp_path).verify("theorem t : True := by FAKE_EXTRA_AXIOM")
    assert result.accepted is False
    assert result.rejection == "nonstandard_axioms"
    assert "myAxiom" in result.output


def test_classical_axioms_are_trusted(tmp_path: Path) -> None:
    result = _lean(tmp_path).verify("theorem t (p : Prop) : p ∨ ¬p := Classical.em p")
    assert result.accepted is True
    assert set(result.axioms or []) == {"Classical.choice", "propext", "Quot.sound"}


def test_no_identifiable_theorem_fails_closed(tmp_path: Path) -> None:
    result = _lean(tmp_path).verify("example : True := trivial")
    assert result.accepted is False
    assert result.rejection == "no_theorem"


def test_every_theorem_in_the_file_is_audited(tmp_path: Path) -> None:
    source = "theorem helper : True := by FAKE_EXTRA_AXIOM\ntheorem main : True := helper"
    result = _lean(tmp_path).verify(source)
    assert result.accepted is False
    assert result.rejection == "nonstandard_axioms"


def test_forged_report_in_a_string_cannot_fool_the_gate(tmp_path: Path) -> None:
    source = "#print \"'t' depends on axioms: [propext]\"\ntheorem t : True := by FAKE_SORRYAX"
    result = _lean(tmp_path).verify(source)
    assert result.accepted is False
    assert result.rejection == "sorry"


def test_elaboration_error_is_a_rejection_with_diagnostics(tmp_path: Path) -> None:
    result = _lean(tmp_path).verify("theorem t : True := by\n  FAKE_UNSOLVED")
    assert result.accepted is False
    assert result.rejection == "elaboration"
    assert result.diagnostics is not None
    assert result.diagnostics["classes"] == ["unsolved_goals"]
    assert "n + 0 = n" in (result.diagnostics["unsolved_goal"] or "")


def test_info_prefixed_output_is_understood(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("FAKE_INFO_PREFIX", "1")
    result = _lean(tmp_path, confine="off").verify("theorem t : True := trivial")
    assert result.accepted is True


def test_missing_lean_is_unavailable_not_rejected() -> None:
    result = Lean4Backend("definitely-not-a-lean-binary").verify("theorem t : True := trivial")
    assert result.available is False and result.accepted is False


# --- confinement -----------------------------------------------------------------


@pytest.mark.skipif(not HAS_BWRAP, reason="bwrap not installed")
def test_checker_runs_confined_when_bwrap_exists(tmp_path: Path) -> None:
    result = _lean(tmp_path).verify("theorem t : True := trivial")
    assert result.accepted is True
    assert result.confined is True


def test_require_confinement_without_bwrap_refuses_to_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "bwrap_binary", lambda: None)
    result = _lean(tmp_path, confine="require").verify("theorem t : True := trivial")
    assert result.accepted is False
    assert result.inconclusive is True  # not a verdict on the proof
    assert result.rejection == "confinement_unavailable"


def test_auto_confinement_without_bwrap_runs_unconfined_and_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sandbox, "bwrap_binary", lambda: None)
    result = _lean(tmp_path).verify("theorem t : True := trivial")
    assert result.accepted is True
    assert result.confined is False
    assert "UNCONFINED" in result.output


@pytest.mark.skipif(not HAS_BWRAP, reason="bwrap not installed")
def test_confined_command_has_no_network_and_no_writes(tmp_path: Path) -> None:
    from opentorus.tools.shell import run_shell

    server = socket.socket()
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    outside = tmp_path / "outside.txt"
    writable = tmp_path / "w"
    writable.mkdir()
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import socket, sys\n"
        "try:\n"
        f"    socket.create_connection(('127.0.0.1', {port}), timeout=2); print('NET')\n"
        "except OSError: print('NONET')\n"
        "try:\n"
        f"    open({str(outside)!r}, 'w').write('x'); print('WROTE')\n"
        "except OSError: print('READONLY')\n"
        f"open({str(writable / 'ok.txt')!r}, 'w').write('x'); print('TMPOK')\n",
        encoding="utf-8",
    )
    try:
        command, confined = sandbox.confine_command(
            f"{sys.executable} {probe}", writable=[writable], mode="require"
        )
        result = run_shell(command, timeout=30)
    finally:
        server.close()
    assert confined is True
    assert "NONET" in result.stdout
    assert "READONLY" in result.stdout
    assert "TMPOK" in result.stdout
    assert not outside.exists()


def test_off_never_confines() -> None:
    command, confined = sandbox.confine_command("lean x.lean", writable=[], mode="off")
    assert command == "lean x.lean" and confined is False


# --- Coq ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "token"),
    [
        ("Theorem t : True. Proof. Admitted.", "Admitted"),
        ("Theorem t : True. Proof. admit. Qed.", "admit"),
        ("Axiom cheat : False.", "Axiom"),
        ("Parameter p : nat.", "Parameter"),
        ('Declare ML Module "evil".', "Declare"),
        ("Unset Guard Checking.", "Unset … Checking"),
    ],
)
def test_coq_forbidden_tokens(source: str, token: str) -> None:
    assert coq_rules.forbidden_token(source) == token


def test_coq_comments_do_not_count() -> None:
    assert coq_rules.forbidden_token("(* Admitted (* nested Axiom *) *) Theorem t : True.") is None


def test_coq_closed_proof_is_accepted(tmp_path: Path) -> None:
    backend = CoqBackend(fake_coq_command(tmp_path))
    result = backend.verify("Theorem t : True.\nProof. exact I. Qed.")
    assert result.accepted is True, result.output


def test_coq_assumption_is_rejected(tmp_path: Path) -> None:
    backend = CoqBackend(fake_coq_command(tmp_path))
    result = backend.verify("Theorem t : True.\nProof. FAKE_AXIOM exact I. Qed.")
    assert result.accepted is False
    assert result.rejection == "nonstandard_axioms"


def test_coq_without_theorem_fails_closed(tmp_path: Path) -> None:
    backend = CoqBackend(fake_coq_command(tmp_path))
    result = backend.verify("Definition x := 1.")
    assert result.accepted is False and result.rejection == "no_theorem"


def test_bwrap_probe_matches_installation() -> None:
    if shutil.which("bwrap") is None:
        assert sandbox.bwrap_binary() is None


def test_confined_write_failure_is_inconclusive(monkeypatch: pytest.MonkeyPatch) -> None:
    from opentorus.research.verifiers import backends
    from opentorus.tools.shell import ShellResult

    backend = Lean4Backend("fake-lean")
    monkeypatch.setattr(backend, "is_available", lambda: True)
    monkeypatch.setattr(
        backends,
        "confine_command",
        lambda command, writable, mode: (command, True),
    )
    monkeypatch.setattr(
        backends,
        "run_shell",
        lambda command, timeout=0: ShellResult(
            command=command,
            stdout="error: .lake/build: Read-only file system",
            stderr="",
            exit_code=1,
        ),
    )
    result = backend.verify("theorem t : True := trivial")
    assert result.accepted is False
    assert result.inconclusive is True  # infrastructure, not a verdict on the proof
