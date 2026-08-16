"""A checker that did not decide must never be recorded as a rejection.

The project's core rule is that evidence is not proof. This is the same rule pointed
the other way: *failure to verify is not refutation*. A solver timeout, a prover
crash, an unreadable certificate, or an interval enclosure too coarse to settle the
question all say "the check did not conclude" — reporting any of them as REJECTED
tells the model its mathematics is wrong when nothing of the sort was established.

Every test here has a partner asserting that a *genuine* rejection still reads as a
rejection, so the distinction cannot be fixed by simply calling everything unsure.
"""

from __future__ import annotations

import pytest

from opentorus.research.verifiers.backends import CoqBackend, Lean4Backend
from opentorus.research.verifiers.base import ran_at_all
from opentorus.research.verifiers.interval import IntervalVerifier
from opentorus.research.verifiers.smt import SMTVerifier
from opentorus.tools.shell import ShellResult

mpmath = pytest.importorskip("mpmath")


def _shell(stdout: str = "", *, exit_code: int = 0, timed_out: bool = False) -> ShellResult:
    return ShellResult(
        command="fake", stdout=stdout, stderr="", exit_code=exit_code, timed_out=timed_out
    )


def _fake_run(result: ShellResult):
    def _run(command: str, *args: object, **kwargs: object) -> ShellResult:
        # The backends also shell out for --version; keep that path harmless.
        if "--version" in command:
            return _shell("fake 1.0")
        return result

    return _run


# --- exit-code classification -------------------------------------------------


def test_ran_at_all_classification() -> None:
    assert ran_at_all(0) is True
    assert ran_at_all(1) is True, "a prover that exits 1 with errors has rejected the proof"
    assert ran_at_all(-11) is False, "SIGSEGV — the prover crashed"
    assert ran_at_all(-9) is False, "SIGKILL — e.g. the OOM killer"
    assert ran_at_all(127) is False, "binary not found"
    assert ran_at_all(125) is False, "docker could not start the container"


# --- SMT ----------------------------------------------------------------------


@pytest.fixture
def smt(monkeypatch: pytest.MonkeyPatch) -> SMTVerifier:
    verifier = SMTVerifier(command="z3", timeout=120)
    monkeypatch.setattr(verifier, "is_available", lambda: True)
    return verifier


def test_smt_timeout_is_inconclusive(monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier) -> None:
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell", _fake_run(_shell("", timed_out=True))
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False
    assert result.inconclusive is True
    assert "not a rejection" in result.output
    assert result.status_line() == "smt: inconclusive"


def test_smt_unknown_is_inconclusive(monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier) -> None:
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell", _fake_run(_shell("unknown\n"))
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False
    assert result.inconclusive is True
    assert result.outcome == "unknown"


def test_smt_solver_error_without_verdict_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier
) -> None:
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell",
        _fake_run(_shell('(error "line 3: unknown sort")', exit_code=1)),
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False
    assert result.inconclusive is True
    # Reported through the error path, which also hands back the solver's own message.
    assert "unknown sort" in result.output


def test_silent_solver_without_verdict_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier
) -> None:
    """No verdict and no error either — still nothing to record as a result."""
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell", _fake_run(_shell("", exit_code=0))
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False
    assert result.inconclusive is True
    assert "no sat/unsat verdict" in result.output


def test_smt_crash_is_inconclusive(monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier) -> None:
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell", _fake_run(_shell("", exit_code=-9))
    )
    result = smt.verify("(check-sat)")
    assert result.inconclusive is True
    assert "did not run to completion" in result.output


def test_smt_unsat_still_proves(monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier) -> None:
    monkeypatch.setattr("opentorus.research.verifiers.smt.run_shell", _fake_run(_shell("unsat\n")))
    result = smt.verify("(check-sat)")
    assert result.accepted is True
    assert result.inconclusive is False


def test_smt_sat_is_a_real_refutation_not_inconclusive(
    monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier
) -> None:
    """``sat`` is a decisive counterexample — it must not be softened to 'unsure'."""
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell",
        _fake_run(_shell("sat\n(define-fun x () Int 3)")),
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False
    assert result.inconclusive is False
    assert result.outcome == "sat"
    assert result.model is not None


# --- Lean / Coq ---------------------------------------------------------------


@pytest.mark.parametrize("backend_cls", [Lean4Backend, CoqBackend])
def test_prover_crash_is_inconclusive(monkeypatch: pytest.MonkeyPatch, backend_cls: type) -> None:
    backend = backend_cls(command="fake-prover")
    monkeypatch.setattr(backend, "is_available", lambda: True)
    monkeypatch.setattr(
        "opentorus.research.verifiers.backends.run_shell", _fake_run(_shell("", exit_code=-11))
    )
    result = backend.verify("theorem foo : True := trivial")
    assert result.accepted is False
    assert result.inconclusive is True
    assert "did not run to completion" in result.output


@pytest.mark.parametrize("backend_cls", [Lean4Backend, CoqBackend])
def test_prover_error_exit_is_a_real_rejection(
    monkeypatch: pytest.MonkeyPatch, backend_cls: type
) -> None:
    """Exit 1 with error output is the prover judging the proof — a true rejection."""
    backend = backend_cls(command="fake-prover")
    monkeypatch.setattr(backend, "is_available", lambda: True)
    monkeypatch.setattr(
        "opentorus.research.verifiers.backends.run_shell",
        _fake_run(_shell("error: unsolved goals", exit_code=1)),
    )
    result = backend.verify("theorem foo : False := by trivial")
    assert result.accepted is False
    assert result.inconclusive is False
    assert result.status_line().endswith("rejected")


# --- interval arithmetic ------------------------------------------------------


def test_interval_straddling_enclosure_is_inconclusive() -> None:
    """Interval arithmetic is one-sided: too coarse a box does not disprove anything."""
    verifier = IntervalVerifier()
    # x on [0, 10] gives an enclosure straddling 5 — insufficient, but x < 5 is not
    # thereby refuted (it is simply not established over that box).
    cert = '{"relation": "<", "expression": "x", "variables": {"x": [0, 10]}, "bound": 5}'
    result = verifier.verify(cert)
    assert result.accepted is False
    assert result.inconclusive is True
    assert "refine the box" in result.output


def test_interval_proved_case_still_accepts() -> None:
    verifier = IntervalVerifier()
    cert = '{"relation": "<", "expression": "x", "variables": {"x": [0, 1]}, "bound": 5}'
    result = verifier.verify(cert)
    assert result.accepted is True
    assert result.inconclusive is False


def test_interval_invalid_certificate_is_inconclusive() -> None:
    verifier = IntervalVerifier()
    result = verifier.verify('{"relation": "~~", "expression": "x"}')
    assert result.accepted is False
    assert result.inconclusive is True, "a certificate we cannot read was never checked"


def test_interval_and_sympy_agree_on_malformed_input() -> None:
    """The two pure-Python backends must not disagree about what bad input means."""
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    interval = IntervalVerifier().verify("not json at all")
    sympy = SymPyVerifier().verify("not json at all")
    assert interval.inconclusive == sympy.inconclusive is True


# --- a verdict printed next to parse errors -----------------------------------

_UNDECLARED = """\
(declare-fun a () Int)
(assert (> a 0))
(assert (> c51 100))
(check-sat)
"""

_UNDECLARED_UNSAT = """\
(declare-fun a () Int)
(assert (> a 0))
(assert (< a 0))
(assert (> c73 100))
(check-sat)
"""


def test_sat_next_to_parse_errors_is_inconclusive(
    monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier
) -> None:
    """Observed live (barnette PROOF-0002): two unknown-constant errors, then `sat`."""
    output = (
        '(error "line 14 column 11: unknown constant c51")\n'
        '(error "line 18 column 11: unknown constant c73")\n'
        "sat\n"
    )
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell", _fake_run(_shell(output, exit_code=1))
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False
    assert result.inconclusive is True
    assert "different problem than the one submitted" in result.output
    # The model needs the error lines to fix its script.
    assert "unknown constant c51" in result.output
    assert "declare-fun" in result.output


def test_unsat_next_to_parse_errors_never_accepts(
    monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier
) -> None:
    """The dangerous direction: a typo must not yield an accepted formal proof.

    An accepted proof is the one artifact that can promote a claim to
    ``formally_verified``, so trusting a verdict printed beside dropped assertions is a
    route to a fabricated proof.
    """
    output = '(error "line 4 column 11: unknown constant c73")\nunsat\n'
    monkeypatch.setattr(
        "opentorus.research.verifiers.smt.run_shell", _fake_run(_shell(output, exit_code=1))
    )
    result = smt.verify("(check-sat)")
    assert result.accepted is False, "a verdict beside errors must never prove anything"
    assert result.inconclusive is True


def test_clean_output_is_unaffected(monkeypatch: pytest.MonkeyPatch, smt: SMTVerifier) -> None:
    monkeypatch.setattr("opentorus.research.verifiers.smt.run_shell", _fake_run(_shell("unsat\n")))
    assert smt.verify("(check-sat)").accepted is True


@pytest.mark.parametrize(("source", "token"), [(_UNDECLARED, "sat"), (_UNDECLARED_UNSAT, "unsat")])
def test_against_a_real_solver(source: str, token: str) -> None:
    """Pin the actual solver behaviour this defence is built on, not our model of it."""
    verifier = SMTVerifier(command="z3")
    if not verifier.is_available():
        pytest.skip("z3 not installed")

    raw = SMTVerifier(command="z3")
    result = raw.verify(source)
    # z3 really does print a verdict after dropping the unparseable assertion …
    assert token in result.output
    assert "(error" in result.output
    # … and we really do refuse to read it as a result.
    assert result.accepted is False
    assert result.inconclusive is True


def test_inconclusive_smt_cannot_back_a_verification_claim(tmp_path) -> None:
    """End to end: the bad verdict must not reach `formally_verified`."""
    from opentorus.config import default_config
    from opentorus.errors import OpenTorusError
    from opentorus.research.dossier import claims, store
    from opentorus.research.verifiers.proofs import submit_proof
    from opentorus.workspace import init_workspace, workspace_dir

    verifier = SMTVerifier(command="z3")
    if not verifier.is_available():
        pytest.skip("z3 not installed")

    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    pid = store.create_dossier(ot, "A conjecture about X.").id
    claim = claims.add_claim(ot, pid, claim_type="CLAIM", statement="X holds")

    attempt = submit_proof(
        ot, default_config(), "smt", _UNDECLARED_UNSAT, claim_id=claim.id, verifier=verifier
    )
    assert attempt.accepted is False and attempt.inconclusive is True
    with pytest.raises(OpenTorusError, match="inconclusive"):
        claims.add_evidence(
            ot,
            pid,
            claim.id,
            evidence_type="FORMAL_PROOF",
            summary="machine-checked",
            source_artifacts=[attempt.id],
        )
    assert store.get_claim(ot, pid, claim.id).status == "unverified"
