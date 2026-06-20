"""Tests for persistent REPL line-editing history."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus import replhistory
from opentorus.repl import dispatch

readline = pytest.importorskip("readline")


@pytest.fixture(autouse=True)
def _isolated_history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("OPENTORUS_NO_HISTORY", raising=False)
    monkeypatch.setenv("OPENTORUS_HISTORY_FILE", str(tmp_path / "hist"))
    readline.clear_history()
    yield
    readline.clear_history()


def test_history_path_respects_env(tmp_path: Path) -> None:
    assert replhistory.history_path() == tmp_path / "hist"


def test_no_history_env_disables_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENTORUS_NO_HISTORY", "1")
    assert replhistory.history_path() is None
    assert replhistory.setup_history() is None


def test_history_roundtrips_to_disk(tmp_path: Path) -> None:
    path = replhistory.setup_history()
    assert path == tmp_path / "hist"
    readline.add_history("opentorus status")
    readline.add_history("/claims")
    replhistory.save_history()
    assert path is not None and path.is_file()

    readline.clear_history()
    replhistory.setup_history()
    assert replhistory.recent_history(10) == ["opentorus status", "/claims"]


def test_recent_history_respects_limit() -> None:
    replhistory.setup_history()
    for i in range(5):
        readline.add_history(f"cmd {i}")
    assert replhistory.recent_history(2) == ["cmd 3", "cmd 4"]


def test_history_slash_command_lists_entries() -> None:
    replhistory.setup_history()
    readline.add_history("first")
    readline.add_history("second")
    result = dispatch("/history")
    assert len(result.messages) == 1
    assert "first" in result.messages[0]
    assert "second" in result.messages[0]


def test_history_slash_command_rejects_bad_count() -> None:
    replhistory.setup_history()
    result = dispatch("/history notanumber")
    assert "Usage:" in result.messages[0]
