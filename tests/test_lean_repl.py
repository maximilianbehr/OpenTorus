"""The resident Lean REPL backend (plan item 12), against a fake REPL.

One process, the header elaborated once, a per-request deadline that kills a hung
process, a single respawn on death — and the very same gate as the file backend.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.config import default_config
from opentorus.research.verifiers import lean_repl, sandbox
from opentorus.research.verifiers.lean_repl import LeanReplBackend
from opentorus.research.verifiers.registry import get_verifier
from support.fake_lean import fake_repl_command


@pytest.fixture(autouse=True)
def _fresh_pool():
    lean_repl.shutdown_all()
    yield
    lean_repl.shutdown_all()


def _repl(tmp_path: Path, **kw) -> LeanReplBackend:
    kw.setdefault("confine", "off")
    return LeanReplBackend(fake_repl_command(tmp_path), **kw)


def _log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    log = tmp_path / "repl.log"
    monkeypatch.setenv("FAKE_REPL_LOG", str(log))
    return log


def test_header_loaded_once_and_reused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    log = _log(tmp_path, monkeypatch)
    repl = _repl(tmp_path)
    first = repl.verify("import Mathlib\ntheorem t (n : Nat) : n + 0 = n := by simp")
    second = repl.verify("import Mathlib\ntheorem u : True := trivial")
    assert first.accepted is True, first.output
    assert second.accepted is True, second.output
    entries = log.read_text(encoding="utf-8").splitlines()
    assert entries.count("start") == 1
    assert entries.count("cmd env=None") == 1  # only the header ran without an env
    assert entries.count("cmd env=0") == 2  # both submissions reused the header env


def test_gate_applies_unchanged(tmp_path: Path) -> None:
    repl = _repl(tmp_path)
    assert repl.verify("theorem t : True := by sorry").rejection == "sorry"
    assert repl.verify("#eval 1\ntheorem t : True := trivial").rejection == "forbidden_token"
    hidden = repl.verify("import Mathlib\ntheorem t : True := by FAKE_SORRYAX")
    assert hidden.accepted is False and hidden.rejection == "sorry"
    errs = repl.verify("import Mathlib\ntheorem t : True := by\n  FAKE_UNSOLVED")
    assert errs.rejection == "elaboration"
    assert errs.diagnostics and errs.diagnostics["classes"] == ["unsolved_goals"]


def test_uncovered_imports_run_without_the_header_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _log(tmp_path, monkeypatch)
    repl = _repl(tmp_path)
    result = repl.verify("import Other.Library\ntheorem t : True := trivial")
    assert result.accepted is True, result.output
    assert log.read_text(encoding="utf-8").splitlines().count("cmd env=None") == 2


def test_timeout_kills_and_next_request_respawns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _log(tmp_path, monkeypatch)
    repl = _repl(tmp_path, timeout=2)
    hung = repl.verify("import Mathlib\ntheorem t : True := by FAKE_HANG")
    assert hung.accepted is False
    assert hung.inconclusive is True  # a deadline is not a verdict
    ok = repl.verify("import Mathlib\ntheorem t : True := trivial")
    assert ok.accepted is True, ok.output
    assert log.read_text(encoding="utf-8").splitlines().count("start") == 2


def test_crash_respawns_once_then_is_inconclusive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = _log(tmp_path, monkeypatch)
    repl = _repl(tmp_path)
    crashed = repl.verify("import Mathlib\ntheorem t : True := by FAKE_CRASH")
    assert crashed.accepted is False
    assert crashed.inconclusive is True
    assert "died twice" in crashed.output
    assert log.read_text(encoding="utf-8").splitlines().count("start") == 2


@pytest.mark.skipif(sandbox.bwrap_binary() is None, reason="bwrap not installed")
def test_repl_runs_confined(tmp_path: Path) -> None:
    repl = _repl(tmp_path, confine="auto")
    result = repl.verify("import Mathlib\ntheorem t : True := trivial")
    assert result.accepted is True, result.output
    assert result.confined is True


def test_registry_selects_repl_only_when_enabled(tmp_path: Path) -> None:
    config = default_config()
    config.tools.verifiers.lean = True
    assert not isinstance(get_verifier(config, "lean4"), LeanReplBackend)
    config.tools.verifiers.lean_repl = True
    assert isinstance(get_verifier(config, "lean4"), LeanReplBackend)
