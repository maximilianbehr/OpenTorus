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
        return _result_from_solver_output(self.name, self.version(), output)


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
