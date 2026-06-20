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

from opentorus.research.verifiers.base import VerificationResult
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
        return _result_from_solver_output(self.name, self.version(), output)


def _result_from_solver_output(
    backend: str, version: str | None, output: str
) -> VerificationResult:
    """Map raw solver stdout onto a :class:`VerificationResult`.

    The first standalone ``sat``/``unsat``/``unknown`` token decides the outcome;
    for ``sat`` the remaining text is captured as the counterexample model.
    """
    outcome: str | None = None
    model_lines: list[str] = []
    for line in output.splitlines():
        token = line.strip()
        if outcome is None and token in ("sat", "unsat", "unknown"):
            outcome = token
            continue
        if outcome == "sat" and token:
            model_lines.append(token)
    accepted = outcome == "unsat"
    model = "\n".join(model_lines) if (outcome == "sat" and model_lines) else None
    return VerificationResult(
        backend=backend,
        backend_version=version,
        accepted=accepted,
        available=True,
        output=output,
        outcome=outcome,
        model=model,
    )
