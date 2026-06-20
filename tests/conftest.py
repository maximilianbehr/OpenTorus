"""Shared pytest fixtures.

Keep Rich output deterministic regardless of the host environment. Several tests
build ``Console(file=StringIO())`` and assert on plain text; a ``FORCE_COLOR`` /
``CLICOLOR_FORCE`` set in the environment (as some CI runners and terminals do)
would make Rich emit ANSI escapes into that buffer and break those assertions.
Neutralizing color here makes the suite robust to where it runs.
"""

from __future__ import annotations

import os

import pytest

# Neutralize color at conftest import time — this runs before test modules are
# imported, so module-level consoles (e.g. opentorus.cli's ``console``) are built
# with color disabled. The autouse fixture below additionally protects against a
# test mutating the environment mid-session.
os.environ.pop("FORCE_COLOR", None)
os.environ.pop("CLICOLOR_FORCE", None)
os.environ.setdefault("NO_COLOR", "1")


@pytest.fixture(autouse=True)
def _deterministic_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
