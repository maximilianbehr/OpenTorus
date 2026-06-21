"""A checker timeout must read as inconclusive, not as a rejection."""

from __future__ import annotations

from opentorus.research.verifiers import backends
from opentorus.tools.shell import ShellResult


def test_command_backend_timeout_is_inconclusive(monkeypatch) -> None:  # noqa: ANN001
    def fake_run_shell(command, cwd=None, timeout=120):  # noqa: ANN001, ANN202
        return ShellResult(
            command=command, stdout="", stderr="Timed out", exit_code=124, timed_out=True
        )

    monkeypatch.setattr(backends, "run_shell", fake_run_shell)
    # 'true' exists, so the backend reports itself available; the (faked) run times out.
    result = backends.Lean4Backend("true").verify("theorem foo : 1 = 1 := rfl")
    assert result.available is True
    assert result.accepted is False
    assert result.inconclusive is True  # "the checker gave up" != "the proof is wrong"
    assert "inconclusive" in result.status_line()
