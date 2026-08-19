"""SMT decision-procedure backend (Milestone 62).

An ``SMTVerifier`` discharges decidable goals automatically as a sibling of the
Lean/Coq backends. It accepts an SMT-LIB script (which should ``(check-sat)``)
and maps the solver verdict onto :class:`VerificationResult`:

- ``unsat`` ⇒ the negated goal is unsatisfiable ⇒ the goal is **proved**
  (``accepted``).
- ``sat`` ⇒ a model exists ⇒ a concrete **counterexample** (``accepted`` is
  False; the model is attached as contradicting evidence by the proof layer).
- ``unknown`` ⇒ inconclusive; reported honestly, never as a proof.

If the solver binary is not installed the backend reports itself unavailable
rather than faking rigor.
"""

from __future__ import annotations

import shlex
import shutil
import tempfile
from pathlib import Path

from opentorus.research.verifiers.base import VerificationResult, ran_at_all
from opentorus.tools.shell import run_shell


class SMTVerifier:
    """A Z3/cvc5-style SMT solver exposed through the verifier protocol."""

    name = "smt"
    suffix = ".smt2"

    def __init__(self, command: str = "z3", timeout: int = 120) -> None:
        self.command = command
        self.timeout = timeout

    def _binary(self) -> str:
        parts = shlex.split(self.command)
        return parts[0] if parts else ""

    def is_available(self) -> bool:
        binary = self._binary()
        return bool(binary) and shutil.which(binary) is not None

    def version(self) -> str | None:
        if not self.is_available():
            return None
        result = run_shell(f"{self._binary()} --version", timeout=self.timeout)
        if result.exit_code == 0 and result.stdout.strip():
            return result.stdout.strip().splitlines()[0]
        return None

    def verify(self, source: str) -> VerificationResult:
        if not self.is_available():
            return VerificationResult(
                backend=self.name,
                accepted=False,
                available=False,
                output=f"SMT solver '{self._binary()}' is not installed; verification unavailable.",
            )
        with tempfile.TemporaryDirectory(prefix="opentorus-smt-") as tmp:
            src = Path(tmp) / f"goal{self.suffix}"
            src.write_text(source, encoding="utf-8")
            result = run_shell(f"{self.command} {shlex.quote(str(src))}", timeout=self.timeout)
        output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
        # A solver that ran out of time or died never decided anything. Reporting that
        # as a rejection tells the model its goal is false when the truth is that the
        # check did not finish — the exact evidence/proof confusion this project exists
        # to prevent, pointed the other way.
        if result.timed_out:
            return VerificationResult(
                backend=self.name,
                backend_version=self.version(),
                accepted=False,
                inconclusive=True,
                available=True,
                output=output
                or f"Timed out after {self.timeout}s (inconclusive, not a rejection).",
            )
        if not ran_at_all(result.exit_code):
            return VerificationResult(
                backend=self.name,
                backend_version=self.version(),
                accepted=False,
                inconclusive=True,
                available=True,
                output=(
                    f"The solver did not run to completion (exit {result.exit_code}); "
                    f"this is inconclusive, not a rejection.\n{output}"
                ).strip(),
            )
        verdict = _result_from_solver_output(self.name, self.version(), output)
        if verdict.accepted:
            vacuous = self._vacuity_check(source)
            if vacuous is not None:
                return vacuous
        return verdict

    def _vacuity_check(self, source: str) -> VerificationResult | None:
        """Refuse an ``unsat`` whose hypotheses are already unsatisfiable on their own.

        ``unsat`` proves the goal only when the assertions *before* the negated goal
        are consistent; inconsistent hypotheses make every goal "provable". Observed
        live (caccetta-haggkvist, PROOF-0009): ``(assert (forall ((i Int)) (and (>= i 0)
        (< i 9))))`` — "every integer lies in [0, 9)" — followed by the real encoding,
        and z3 said ``unsat`` about nothing. So when the script carries two or more
        assertions, the script minus its *last* assertion (by convention the negated
        goal) is run again: if that residue is ``unsat`` too, the proof is vacuous and is
        REJECTED with the reason (not inconclusive — the solver did decide, about the
        wrong thing). Returns ``None`` when the hypotheses are consistent (or the check
        itself could not conclude, which is reported as inconclusive).
        """
        forms = _top_level_forms(source)
        assert_idx = [i for i, f in enumerate(forms) if f.lstrip("( \t\r\n").startswith("assert")]
        if len(assert_idx) < 2:
            return None
        residue_forms = [f for i, f in enumerate(forms) if i != assert_idx[-1]]
        if not any(f.lstrip("( \t\r\n").startswith("check-sat") for f in residue_forms):
            residue_forms.append("(check-sat)")
        residue = "\n".join(residue_forms)
        with tempfile.TemporaryDirectory(prefix="opentorus-smt-") as tmp:
            src = Path(tmp) / f"hypotheses{self.suffix}"
            src.write_text(residue, encoding="utf-8")
            result = run_shell(f"{self.command} {shlex.quote(str(src))}", timeout=self.timeout)
        output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
        if result.timed_out or not ran_at_all(result.exit_code):
            return VerificationResult(
                backend=self.name,
                backend_version=self.version(),
                accepted=False,
                inconclusive=True,
                available=True,
                output=(
                    "The goal came back unsat, but the vacuity check (the script without its "
                    "last assertion) did not conclude, so it is unknown whether the hypotheses "
                    "are consistent; recorded as inconclusive, not as a proof.\n" + output
                ).strip(),
            )
        residue_verdict = _result_from_solver_output(self.name, self.version(), output)
        if residue_verdict.outcome == "unsat":
            return VerificationResult(
                backend=self.name,
                backend_version=self.version(),
                accepted=False,
                inconclusive=False,
                available=True,
                outcome="unsat",
                output=(
                    "REJECTED as vacuous: the assertions *before* the last one are already "
                    "unsatisfiable on their own, so 'unsat' proves nothing about the goal "
                    "(inconsistent hypotheses make every statement 'provable'). Check the "
                    "hypotheses for a contradiction — e.g. a quantifier over all integers "
                    "that pins them into a finite range — and put the negated goal last.\n" + output
                ).strip(),
            )
        return None


def _top_level_forms(source: str) -> list[str]:
    """Split an SMT-LIB script into its top-level s-expressions (comments and string
    literals respected). Text outside parentheses is dropped."""
    forms: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    in_comment = False
    i = 0
    while i < len(source):
        ch = source[i]
        if in_comment:
            if ch == "\n":
                in_comment = False
        elif in_string:
            if ch == '"':
                if i + 1 < len(source) and source[i + 1] == '"':
                    i += 1  # escaped quote
                else:
                    in_string = False
        elif ch == ";":
            in_comment = True
        elif ch == '"':
            in_string = True
        elif ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    forms.append(source[start : i + 1])
                    start = None
        i += 1
    return forms


def _errors_invalidate_the_verdict(
    backend: str,
    version: str | None,
    outcome: str | None,
    errors: list[str],
    output: str,
) -> VerificationResult:
    """A verdict printed next to parse errors says nothing about the submitted goal.

    z3 and cvc5 do not abort on a malformed assertion: they emit ``(error …)``, drop
    that assertion, and solve what is left. Observed live (barnette, PROOF-0002): two
    ``unknown constant`` errors followed by ``sat``, recorded as a REJECTED — telling
    the model its mathematics was wrong when the truth was a missing ``declare-fun``.

    The ``unsat`` case is the dangerous one and is reachable the same way: dropping an
    assertion can leave a residue that *is* unsatisfiable, so a typo could yield an
    ACCEPTED formal proof of a goal the solver never saw. Verified against z3 5.0.0 —
    before this, such a submission returned ``accepted=True``. Since an accepted proof
    is the one artifact that can promote a claim to ``formally_verified``, treating a
    verdict-with-errors as a real result is a route to a fabricated proof, and neither
    direction may be trusted.
    """
    listed = "\n".join(errors)
    seen = f"a '{outcome}' verdict" if outcome else "no verdict"
    return VerificationResult(
        backend=backend,
        backend_version=version,
        accepted=False,
        inconclusive=True,
        available=True,
        outcome=outcome,
        output=(
            f"The solver reported {len(errors)} error(s) and then printed {seen}. It "
            "discards an assertion it cannot parse and solves what remains, so that "
            "verdict is about a different problem than the one submitted — it is "
            "inconclusive, neither a proof nor a refutation.\n\n"
            f"{listed}\n\nFix the script (an 'unknown constant' means a missing "
            "declare-fun / declare-const for that symbol) and resubmit.\n\n"
            f"{output}"
        ),
    )


def _result_from_solver_output(
    backend: str, version: str | None, output: str
) -> VerificationResult:
    """Map raw solver stdout onto a :class:`VerificationResult`.

    The first standalone ``sat``/``unsat``/``unknown`` token decides the outcome;
    for ``sat`` the remaining text is captured as the counterexample model.
    """
    outcome: str | None = None
    model_lines: list[str] = []
    errors: list[str] = []
    for line in output.splitlines():
        token = line.strip()
        # SMT-LIB error responses. A solver that cannot parse an assertion *discards it*
        # and carries on with the rest, so any verdict that follows is about a different
        # problem than the one submitted.
        if token.startswith("(error"):
            errors.append(token)
            continue
        if outcome is None and token in ("sat", "unsat", "unknown"):
            outcome = token
            continue
        if outcome == "sat" and token:
            model_lines.append(token)

    if errors:
        return _errors_invalidate_the_verdict(backend, version, outcome, errors, output)
    accepted = outcome == "unsat"
    model = "\n".join(model_lines) if (outcome == "sat" and model_lines) else None
    # ``unsat`` proves and ``sat`` refutes. Everything else — an explicit ``unknown``,
    # or no verdict token at all because the solver errored on the script — decided
    # nothing and must not read as a refutation.
    inconclusive = outcome not in ("unsat", "sat")
    if outcome is None:
        output = (
            "The solver produced no sat/unsat verdict; this is inconclusive, not a "
            f"rejection. Check the script parses and ends with (check-sat).\n{output}"
        ).strip()
    return VerificationResult(
        backend=backend,
        backend_version=version,
        accepted=accepted,
        inconclusive=inconclusive,
        available=True,
        output=output,
        outcome=outcome,
        model=model,
    )
