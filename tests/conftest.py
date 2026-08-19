"""Shared pytest fixtures.

Keep Rich output deterministic regardless of the host environment. Several tests
build ``Console(file=StringIO())`` and assert on plain text; a ``FORCE_COLOR`` /
``CLICOLOR_FORCE`` set in the environment (as some CI runners and terminals do)
would make Rich emit ANSI escapes into that buffer and break those assertions.
Neutralizing color here makes the suite robust to where it runs.
"""

from __future__ import annotations

import json
import os

import pytest

# Neutralize color at conftest import time — this runs before test modules are
# imported, so module-level consoles (e.g. opentorus.cli's ``console``) are built
# with color disabled. The autouse fixture below additionally protects against a
# test mutating the environment mid-session.
os.environ.pop("FORCE_COLOR", None)
os.environ.pop("CLICOLOR_FORCE", None)
os.environ.setdefault("NO_COLOR", "1")
# Typer switches its Rich help output into forced-terminal mode whenever GITHUB_ACTIONS,
# FORCE_COLOR or PY_COLORS is set (typer.rich_utils.FORCE_TERMINAL) — ANSI escapes plus
# 80-column wrapping that splits long option names such as ``--no-primary-claim`` across
# lines. Tests assert on plain ``--help`` text, so the help must render the same on a CI
# runner as on a laptop: Typer's own off-switch, and a wide fixed terminal width.
os.environ.setdefault("_TYPER_FORCE_DISABLE_TERMINAL", "1")
os.environ.setdefault("TERMINAL_WIDTH", "200")
os.environ.pop("PY_COLORS", None)


@pytest.fixture(autouse=True)
def _deterministic_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")


@pytest.fixture
def accepted_proof():
    """Record a genuinely accepted ``PROOF-*`` artifact and return its id.

    Verification-grade evidence (``FORMAL_PROOF`` / ``VALIDATED_NUMERICAL``) may only
    be recorded against a verifier run that actually happened and was accepted. Tests
    that need a verified claim must therefore produce a real one — this runs the sympy
    backend (a core dependency) on a true identity, so the artifact behind the
    promotion is as real in the tests as it must be in production.
    """
    from opentorus.config import default_config
    from opentorus.research.verifiers.proofs import submit_proof
    from opentorus.research.verifiers.sympy_backend import SymPyVerifier

    def _make(ot_dir, claim_id: str | None = None) -> str:
        certificate = json.dumps(
            {"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq", "vars": {"x": "real"}}
        )
        attempt = submit_proof(
            ot_dir,
            default_config(),
            "sympy",
            certificate,
            claim_id=claim_id,
            verifier=SymPyVerifier(),
        )
        assert attempt.accepted, f"fixture must produce a real accepted proof: {attempt.output}"
        return attempt.id

    return _make
