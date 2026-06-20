"""Concrete proof-assistant backends (Lean 4, Coq).

Each backend writes the formal source to a temporary file and invokes the
checker. Exit code 0 ⇒ accepted. If the tool is not installed, the backend
reports itself unavailable rather than faking rigor.
"""

from __future__ import annotations

import shlex
import shutil
import tempfile
from pathlib import Path

from opentorus.research.verifiers.base import VerificationResult
from opentorus.tools.shell import run_shell


class _CommandBackend:
    """A verifier that runs a command on a source file with a given suffix."""

    name: str = ""
    suffix: str = ".txt"

    def __init__(self, command: str, timeout: int = 120) -> None:
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
        if result.exit_code == 0:
            return result.stdout.strip().splitlines()[0] if result.stdout.strip() else None
        return None

    def verify(self, source: str) -> VerificationResult:
        if not self.is_available():
            return VerificationResult(
                backend=self.name,
                accepted=False,
                available=False,
                output=f"Backend '{self.name}' is not installed; formal verification unavailable.",
            )
        with tempfile.TemporaryDirectory(prefix="opentorus-proof-") as tmp:
            src = Path(tmp) / f"proof{self.suffix}"
            src.write_text(source, encoding="utf-8")
            result = run_shell(f"{self.command} {shlex.quote(str(src))}", timeout=self.timeout)
        output = (result.stdout + ("\n" + result.stderr if result.stderr else "")).strip()
        return VerificationResult(
            backend=self.name,
            backend_version=self.version(),
            accepted=result.exit_code == 0,
            output=output,
            available=True,
        )


class Lean4Backend(_CommandBackend):
    name = "lean4"
    suffix = ".lean"


class CoqBackend(_CommandBackend):
    name = "coq"
    suffix = ".v"
