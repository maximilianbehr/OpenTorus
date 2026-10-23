"""Concrete proof-assistant backends (Lean 4, Coq).

Each backend writes the formal source to a temporary file and invokes the checker.
Exit code 0 is *necessary*, never sufficient: Lean exits 0 on a file full of
``sorry`` and Coq on one that ends in ``Admitted``. Acceptance therefore goes through
a gate (``lean_rules`` / ``coq_rules``):

1. a textual pre-scan *before anything runs* refuses ``sorry``/``Admitted``, user
   axioms, ``native_decide``, ``set_option pp.*``/``debug.*`` and every
   code-execution word (``#eval``, ``run_cmd``, ``macro``, ``IO`` …);
2. the checker runs confined (``sandbox.py``: bwrap, no network) when available;
3. ``#print axioms <thm>`` (Coq: ``Print Assumptions``) is appended behind a random
   marker, only output after the marker is read, and a theorem is accepted only when
   its axioms are within {propext, Classical.choice, Quot.sound} (Coq: closed under
   the global context);
4. against a frozen formal statement, the statement must appear verbatim and the
   theorem's elaborated type (``pp.all``) must equal the frozen statement's.

If the tool is not installed, the backend reports itself unavailable rather than
faking rigor. If no theorem can be identified, the result is a rejection (fail
closed).
"""

from __future__ import annotations

import re
import shlex
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from opentorus.research.verifiers import coq_rules, lean_rules
from opentorus.research.verifiers.base import VerificationResult, ran_at_all
from opentorus.research.verifiers.sandbox import ConfinementUnavailable, confine_command
from opentorus.tools.shell import ShellResult, run_shell


@dataclass(frozen=True)
class FrozenSpec:
    """What a backend needs to bind a candidate to a frozen formal statement."""

    source: str  # the full frozen file (preamble + statement + placeholder proof)
    theorem: str  # the statement's theorem name
    pristine_type: str  # the frozen statement's elaborated type


class _CommandBackend:
    """A verifier that runs a command on a source file with a given suffix."""

    name: str = ""
    suffix: str = ".txt"

    def __init__(self, command: str, timeout: int = 120, *, confine: str = "auto") -> None:
        self.command = command
        self.timeout = timeout
        self.confine = confine

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
        if result.exit_code == 0:
            return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
        return None

    def _unavailable(self) -> VerificationResult:
        return VerificationResult(
            backend=self.name,
            accepted=False,
            available=False,
            output=f"Backend '{self.name}' is not installed; formal verification unavailable.",
        )

    def _run(self, source: str) -> tuple[ShellResult, bool]:
        """Run the checker on ``source``; ``(result, confined)``.

        Raises :class:`ConfinementUnavailable` when confinement is required but
        impossible — the checker is then never started.
        """
        with tempfile.TemporaryDirectory(prefix="opentorus-proof-") as tmp:
            src = Path(tmp) / f"proof{self.suffix}"
            src.write_text(source, encoding="utf-8")
            # Deliberately world-readable: containerized checkers (the Docker Coq
            # fallback) run as a different uid and cannot traverse the default 0700
            # tempdir — every submission failed with "Can't find file". Proof sources
            # are not sensitive: they are persisted verbatim in the PROOF-* artifact.
            Path(tmp).chmod(0o755)
            src.chmod(0o644)
            command = f"{self.command} {shlex.quote(str(src))}"
            command, confined = confine_command(
                command,
                writable=[Path(tmp)],
                mode=self.confine,  # type: ignore[arg-type]
            )
            result = run_shell(command, timeout=self.timeout)
        return result, confined

    def _not_concluded(
        self, result: ShellResult, output: str, confined: bool
    ) -> VerificationResult | None:
        # A timeout is "the checker gave up", not "the proof is wrong": report it as
        # inconclusive (not accepted, but not a clean rejection either) so a slow
        # proof is never recorded as refuted.
        if result.timed_out:
            return VerificationResult(
                backend=self.name,
                backend_version=self.version(),
                accepted=False,
                inconclusive=True,
                output=output
                or f"Timed out after {self.timeout}s (inconclusive, not a rejection).",
                available=True,
                confined=confined,
                diagnostics=_diagnostics(self.name, output, timed_out=True),
            )
        # A confined checker that tried to write outside its temp dir (e.g. lake
        # deciding to rebuild the project) failed for an infrastructure reason, not
        # because of the proof: inconclusive, with the fix spelled out.
        if confined and result.exit_code != 0 and "Read-only file system" in output:
            return VerificationResult(
                backend=self.name,
                accepted=False,
                inconclusive=True,
                output=(
                    "[opentorus gate] the confined checker tried to write outside its "
                    "temp dir (read-only sandbox) — inconclusive, not a verdict on the "
                    "proof. Build the Lean project first (`lake build`) or set "
                    f"tools.verifiers.confine to 'off'.\n{output}"
                ),
                available=True,
                confined=True,
            )
        # Likewise a crash: a prover killed by a signal (SIGSEGV, or SIGKILL from the
        # OOM killer on a large Mathlib elaboration) or a launcher that could not start
        # it at all judged nothing. Only a prover that ran and exited nonzero has
        # actually rejected the proof.
        if not ran_at_all(result.exit_code):
            return VerificationResult(
                backend=self.name,
                backend_version=self.version(),
                accepted=False,
                inconclusive=True,
                output=(
                    f"'{self.name}' did not run to completion (exit {result.exit_code}); "
                    f"this is inconclusive, not a rejection.\n{output}"
                ).strip(),
                available=True,
                confined=confined,
            )
        return None

    def _reject(
        self,
        reason: str,
        message: str,
        *,
        output: str = "",
        confined: bool | None = None,
        version: str | None = None,
        theorem: str | None = None,
        axioms: list[str] | None = None,
    ) -> VerificationResult:
        text = f"[opentorus gate] REJECTED ({reason}): {message}"
        if output:
            text += "\n\n" + output
        return VerificationResult(
            backend=self.name,
            backend_version=version,
            accepted=False,
            output=text,
            available=self.is_available(),
            rejection=reason,
            confined=confined,
            theorem=theorem,
            axioms=axioms,
            diagnostics=_diagnostics(self.name, output) if output else None,
        )

    def _execute(self, source: str) -> tuple[ShellResult | None, bool, VerificationResult | None]:
        try:
            result, confined = self._run(source)
        except ConfinementUnavailable as exc:
            return (
                None,
                False,
                VerificationResult(
                    backend=self.name,
                    accepted=False,
                    available=True,
                    inconclusive=True,
                    rejection="confinement_unavailable",
                    output=f"[opentorus gate] {exc}",
                    confined=False,
                ),
            )
        return result, confined, None


def _combined(result: ShellResult) -> str:
    return (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()


def _diagnostics(backend: str, output: str, *, timed_out: bool = False) -> dict | None:
    from opentorus.research.verifiers.diagnostics import summarize

    return summarize(backend, output, timed_out=timed_out)


class Lean4Backend(_CommandBackend):
    name = "lean4"
    suffix = ".lean"

    def verify(self, source: str) -> VerificationResult:
        """Gate-check ``source`` with no frozen statement (never statement-bound)."""
        return self._verify(source, None)

    def verify_against(self, source: str, spec: FrozenSpec) -> VerificationResult:
        """Gate-check ``source`` against a frozen statement (statement fidelity)."""
        return self._verify(source, spec)

    def _verify(self, source: str, spec: FrozenSpec | None) -> VerificationResult:
        # 1. Textual pre-scan, before anything runs.
        bad = lean_rules.forbidden_token(source)
        if bad:
            return self._reject(
                "sorry" if bad == "sorry" else "forbidden_token",
                f"forbidden token {bad!r} outside comments/strings. "
                + _FORBIDDEN_HINT.get(bad, _FORBIDDEN_DEFAULT_HINT),
            )
        checked = source
        if spec is not None:
            statement = lean_rules.extract_statement(spec.source)
            if statement is None:
                return self._reject(
                    "frozen_statement_invalid", "the frozen file has no extractable statement"
                )
            if not lean_rules.contains_statement(source, statement):
                return self._reject(
                    "statement_mismatch",
                    "the frozen theorem statement does not appear verbatim (whitespace-"
                    "normalized, outside comments) in the submission. Copy it exactly:\n"
                    + statement.strip(),
                )
            try:
                checked, rest = lean_rules.checked_source(spec.source, source)
            except lean_rules.LeanSourceError as exc:
                return self._reject(
                    "preamble_mismatch",
                    f"{exc}. The submission must start with the frozen file's preamble "
                    "(imports, opens, definitions) unchanged.",
                )
            if not lean_rules.contains_statement(rest, statement):
                return self._reject(
                    "statement_mismatch", "the frozen statement is not after the preamble"
                )
            bad = lean_rules.forbidden_token(checked)
            if bad:
                return self._reject("forbidden_token", f"forbidden token {bad!r}")
        thms = lean_rules.theorem_names(checked)
        if spec is not None:
            thms = [spec.theorem, *(t for t in thms if t != spec.theorem)]
        if not thms:
            return self._reject(
                "no_theorem",
                "no `theorem`/`lemma` declaration found, so its axioms cannot be audited "
                "(an `example` cannot be named in `#print axioms`). State the result as "
                "`theorem name : … := …`.",
            )
        if not self.is_available():
            return self._unavailable()
        marker = lean_rules.fresh_marker()
        probe = checked + lean_rules.report_commands(
            marker, thms, type_of=spec.theorem if spec else None
        )
        result, confined, refused = self._execute(probe)
        if refused is not None or result is None:
            return refused or self._unavailable()
        output = _combined(result)
        early = self._not_concluded(result, output, confined)
        if early is not None:
            return early
        version = self.version()
        if result.exit_code != 0 or re.search(r"(?m)\berror\b:", output):
            return self._reject(
                "elaboration",
                "Lean reported errors.",
                output=output,
                confined=confined,
                version=version,
            )
        if "declaration uses 'sorry'" in output:
            return self._reject(
                "sorry",
                "a declaration uses `sorry`.",
                output=output,
                confined=confined,
                version=version,
            )
        report = lean_rules.parse_report(
            output, marker, thms, type_of=spec.theorem if spec else None
        )
        if report is None:
            return self._reject(
                "no_report",
                f"Lean printed no well-formed `#print axioms` report for {', '.join(thms)} "
                "after the file (a theorem name may not resolve at the end of the file, "
                "e.g. inside an unclosed namespace).",
                output=output,
                confined=confined,
                version=version,
            )
        all_axioms = sorted({a for axs in report.axioms.values() for a in axs})
        if "sorryAx" in all_axioms:
            return self._reject(
                "sorry",
                "the proof depends on `sorryAx` (an unfinished proof).",
                output=output,
                confined=confined,
                version=version,
                theorem=thms[0],
                axioms=all_axioms,
            )
        extra = lean_rules.untrusted_axioms(all_axioms)
        if extra:
            return self._reject(
                "nonstandard_axioms",
                f"depends on axioms outside {{propext, Classical.choice, Quot.sound}}: "
                f"{', '.join(extra)}",
                output=output,
                confined=confined,
                version=version,
                theorem=thms[0],
                axioms=all_axioms,
            )
        if spec is not None and lean_rules.normalize_type(
            report.type_text or ""
        ) != lean_rules.normalize_type(spec.pristine_type):
            return self._reject(
                "type_mismatch",
                f"`{spec.theorem}` elaborates to a different type than the frozen "
                "statement (the surface text is kept but means something else — e.g. a "
                "redefined name or changed notation).",
                output=output,
                confined=confined,
                version=version,
                theorem=spec.theorem,
                axioms=all_axioms,
            )
        note = (
            f"[opentorus gate] accepted: {', '.join(thms)} depend only on "
            f"[{', '.join(all_axioms) or 'no axioms'}]"
            + ("; statement-bound (type matches the frozen statement)" if spec else "")
            + ("" if confined else "; checker ran UNCONFINED (no bwrap)")
        )
        return VerificationResult(
            backend=self.name,
            backend_version=version,
            accepted=True,
            output=note + ("\n\n" + output if output else ""),
            available=True,
            axioms=all_axioms,
            theorem=thms[0],
            statement_bound=spec is not None,
            confined=confined,
        )

    def pristine_type(self, frozen: str) -> tuple[str | None, str]:
        """``(elaborated type, output)`` of a frozen statement checked with ``sorry``.

        Computed exactly as a candidate is checked (separator after the preamble,
        marker, ``#print axioms``, ``pp.all`` probe), so the frozen file's own commands
        cannot stand in for the report. ``None`` with the reason on any failure.
        """
        objection = lean_rules.frozen_objection(frozen)
        if objection:
            return None, f"frozen statement refused: {objection}"
        names = lean_rules.theorem_names(frozen)
        if not self.is_available():
            return None, f"Backend '{self.name}' is not installed."
        checked, _ = lean_rules.checked_source(frozen, frozen)
        marker = lean_rules.fresh_marker()
        probe = checked + lean_rules.report_commands(marker, names, type_of=names[0])
        try:
            result, _confined = self._run(probe)
        except ConfinementUnavailable as exc:
            return None, str(exc)
        output = _combined(result)
        if result.exit_code != 0 or re.search(r"(?m)\berror\b:", output):
            return None, f"the frozen statement does not elaborate:\n{output}"
        report = lean_rules.parse_report(output, marker, names, type_of=names[0])
        if report is None or report.type_text is None:
            return None, f"Lean printed no `#check @{names[0]}` report:\n{output}"
        return report.type_text, output

    def check_partial(self, source: str) -> PartialCheck:
        """Elaborate a *partial* proof (``sorry`` allowed) and report its errors.

        Never a verdict and never recorded: used by the tactic-suite pass to find out
        whether a candidate's only gaps are its ``sorry``s and which splice closes one.
        Every other forbidden token is still refused before anything runs.
        """
        bad = lean_rules.forbidden_token(source, allow_sorry=True)
        if bad:
            return PartialCheck(ran=False, errors=0, output="", refused=bad)
        if not self.is_available():
            return PartialCheck(ran=False, errors=0, output="", refused="unavailable")
        try:
            result, _confined = self._run(source)
        except ConfinementUnavailable as exc:
            return PartialCheck(ran=False, errors=0, output=str(exc), refused="confinement")
        output = _combined(result)
        if result.timed_out or not ran_at_all(result.exit_code):
            return PartialCheck(ran=False, errors=0, output=output, refused="timeout")
        diag = _diagnostics(self.name, output) or {}
        errors = int(diag.get("error_count") or 0)
        if errors == 0 and result.exit_code != 0:
            errors = 1
        return PartialCheck(
            ran=True,
            errors=errors,
            output=output,
            classes=list(diag.get("classes") or []),
        )


@dataclass
class PartialCheck:
    """Outcome of :meth:`Lean4Backend.check_partial` (never a proof verdict)."""

    ran: bool
    errors: int
    output: str
    refused: str | None = None
    classes: list[str] | None = None


_FORBIDDEN_DEFAULT_HINT = (
    "Proof sources may not run code, extend the syntax, or reach the meta/IO libraries "
    "while they elaborate; remove it."
)
_FORBIDDEN_HINT = {
    "sorry": "An unfinished proof is not a proof: close every goal.",
    "native_decide": "native_decide trusts the compiler (Lean.ofReduceBool); use decide.",
    "axiom": "A user axiom proves anything; derive the fact instead.",
    "set_option pp": "pp.* options are reserved for the statement-fidelity probe.",
    "set_option debug": "debug.* options can skip kernel checks.",
}


class CoqBackend(_CommandBackend):
    name = "coq"
    suffix = ".v"

    def verify(self, source: str) -> VerificationResult:
        return self._verify(source, None)

    def verify_against(self, source: str, spec: FrozenSpec) -> VerificationResult:
        return self._verify(source, spec)

    def _verify(self, source: str, spec: FrozenSpec | None) -> VerificationResult:
        bad = coq_rules.forbidden_token(source)
        if bad:
            return self._reject(
                "sorry" if bad in ("Admitted", "admit", "give_up") else "forbidden_token",
                f"forbidden token {bad!r} outside comments/strings (unfinished proofs, "
                "assumptions, plugin/file commands and disabled kernel checks are refused).",
            )
        checked = source
        if spec is not None:
            statement = coq_rules.extract_statement(spec.source)
            if statement is None or not coq_rules.contains_statement(source, statement):
                return self._reject(
                    "statement_mismatch",
                    "the frozen statement does not appear verbatim in the submission"
                    + (f":\n{statement.strip()}" if statement else ""),
                )
            rebuilt = _coq_checked_source(spec.source, source)
            if rebuilt is None:
                return self._reject(
                    "preamble_mismatch",
                    "the submission does not begin with the frozen file's preamble",
                )
            checked = rebuilt
        thms = coq_rules.theorem_names(checked)
        if spec is not None:
            thms = [spec.theorem, *(t for t in thms if t != spec.theorem)]
        if not thms:
            return self._reject(
                "no_theorem",
                "no Theorem/Lemma declaration found, so its assumptions cannot be audited.",
            )
        if not self.is_available():
            return self._unavailable()
        marker = coq_rules.fresh_marker()
        probe = checked + coq_rules.report_commands(
            marker, thms, type_of=spec.theorem if spec else None
        )
        result, confined, refused = self._execute(probe)
        if refused is not None or result is None:
            return refused or self._unavailable()
        output = _combined(result)
        early = self._not_concluded(result, output, confined)
        if early is not None:
            return early
        version = self.version()
        if result.exit_code != 0 or re.search(r"(?m)^Error:", output):
            return self._reject(
                "elaboration", "coqc reported errors.", output=output, confined=confined
            )
        report = coq_rules.parse_report(
            output, marker, thms, type_of=spec.theorem if spec else None
        )
        if report is None:
            return self._reject(
                "no_report",
                f"coqc printed no well-formed `Print Assumptions` report for {', '.join(thms)}.",
                output=output,
                confined=confined,
                version=version,
            )
        assumed = sorted({a for items in report.assumptions.values() for a in items})
        if assumed:
            return self._reject(
                "nonstandard_axioms",
                f"not closed under the global context; assumes: {', '.join(assumed)}",
                output=output,
                confined=confined,
                version=version,
                theorem=thms[0],
                axioms=assumed,
            )
        if spec is not None and lean_rules.normalize_type(
            report.type_text or ""
        ) != lean_rules.normalize_type(spec.pristine_type):
            return self._reject(
                "type_mismatch",
                f"`{spec.theorem}` has a different type than the frozen statement.",
                output=output,
                confined=confined,
                version=version,
                theorem=spec.theorem,
            )
        note = (
            f"[opentorus gate] accepted: {', '.join(thms)} closed under the global context"
            + ("; statement-bound" if spec else "")
            + ("" if confined else "; checker ran UNCONFINED (no bwrap)")
        )
        return VerificationResult(
            backend=self.name,
            backend_version=version,
            accepted=True,
            output=note + ("\n\n" + output if output else ""),
            available=True,
            axioms=[],
            theorem=thms[0],
            statement_bound=spec is not None,
            confined=confined,
        )

    def pristine_type(self, frozen: str) -> tuple[str | None, str]:
        objection = coq_rules.frozen_objection(frozen)
        if objection:
            return None, f"frozen statement refused: {objection}"
        if not self.is_available():
            return None, f"Backend '{self.name}' is not installed."
        names = coq_rules.theorem_names(frozen)
        marker = coq_rules.fresh_marker()
        # Only the Check probe: the frozen proof is Admitted, so its assumptions are
        # known not to be closed.
        probe = frozen + f"\nLocate {marker}.\nSet Printing All.\nCheck {names[0]}.\n"
        try:
            result, _confined = self._run(probe)
        except ConfinementUnavailable as exc:
            return None, str(exc)
        output = _combined(result)
        if result.exit_code != 0 or re.search(r"(?m)^Error:", output):
            return None, f"the frozen statement does not check:\n{output}"
        report = coq_rules.parse_report(output, marker, [], type_of=names[0])
        if report is None or report.type_text is None:
            return None, f"coqc printed no `Check {names[0]}` report:\n{output}"
        return report.type_text, output


def _coq_checked_source(frozen: str, candidate: str) -> str | None:
    """Frozen preamble + the candidate after its (whitespace-insensitive) copy of it."""
    statement = coq_rules.extract_statement(frozen)
    if statement is None:
        return None
    pre = frozen[: frozen.find(statement)].rstrip()
    if not pre.strip():
        return candidate
    try:
        pre_code = coq_rules.coq_code(pre)
        cand_code = coq_rules.coq_code(candidate)
    except coq_rules.CoqSourceError:
        return None
    want = [ch for ch in pre_code if not ch.isspace()]
    j = 0
    end = 0
    for i, ch in enumerate(cand_code):
        if j == len(want):
            break
        if ch.isspace():
            continue
        if ch != want[j]:
            return None
        j += 1
        end = i + 1
    if j < len(want):
        return None
    return pre + candidate[end:]
