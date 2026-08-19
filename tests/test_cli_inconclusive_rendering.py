"""``proof list`` / ``proof submit`` must render an inconclusive run as inconclusive.

The ledger records ``accepted: false, inconclusive: true`` when a checker gives up
(e.g. sympy "could not parse lhs/rhs" — a parse failure), but the CLI displayed
"rejected" — a tool that gave up shown as a mathematical rejection. Observed live in
five workspaces. These tests pin all three honest renderings: accepted / rejected /
inconclusive (plus the pre-existing "unavailable").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.jsonl import append_jsonl
from opentorus.research.verifiers.proofs import ProofAttempt, proofs_path
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


def _ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    init_workspace(tmp_path)
    monkeypatch.chdir(tmp_path)
    return workspace_dir(tmp_path)


def _attempt(pid: str, **overrides: Any) -> ProofAttempt:
    record: dict[str, Any] = {
        "id": pid,
        "backend": "sympy",
        "accepted": False,
        "available": True,
        "inconclusive": False,
        "source_path": f"proofs/{pid}.json",
    }
    record.update(overrides)
    return ProofAttempt(**record)


def test_proof_list_renders_all_three_states(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    base = _ws(tmp_path, monkeypatch)
    ledger = proofs_path(base)
    append_jsonl(ledger, _attempt("PROOF-0001", accepted=True))
    append_jsonl(ledger, _attempt("PROOF-0002"))  # a genuine rejection
    append_jsonl(
        ledger,
        _attempt("PROOF-0003", inconclusive=True, output="could not parse lhs/rhs"),
    )
    append_jsonl(ledger, _attempt("PROOF-0004", available=False))

    result = runner.invoke(app, ["proof", "list"])
    assert result.exit_code == 0
    rows = {
        pid: line
        for line in result.output.splitlines()
        for pid in ("PROOF-0001", "PROOF-0002", "PROOF-0003", "PROOF-0004")
        if pid in line
    }

    assert "accepted" in rows["PROOF-0001"]
    assert "rejected" in rows["PROOF-0002"], "a genuine rejection must still read as one"
    assert "inconclusive" in rows["PROOF-0003"]
    assert "rejected" not in rows["PROOF-0003"], "a checker that gave up did not reject"
    assert "unavailable" in rows["PROOF-0004"]


def _submit(monkeypatch: pytest.MonkeyPatch, attempt: ProofAttempt, tmp_path: Path) -> str:
    import opentorus.research.verifiers as verifiers

    source = tmp_path / "cert.json"
    source.write_text('{"lhs": "x", "rhs": "x"}', encoding="utf-8")
    monkeypatch.setattr(verifiers, "submit_proof", lambda *a, **k: attempt)
    result = runner.invoke(app, ["proof", "submit", "sympy", str(source)])
    assert result.exit_code == 0
    return result.output


def test_proof_submit_renders_inconclusive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ws(tmp_path, monkeypatch)
    out = _submit(
        monkeypatch,
        _attempt("PROOF-0001", inconclusive=True, output="could not parse lhs/rhs"),
        tmp_path,
    )
    assert "inconclusive" in out
    assert "rejected" not in out
    assert "not a rejection" in out


def test_proof_submit_renders_accepted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ws(tmp_path, monkeypatch)
    out = _submit(monkeypatch, _attempt("PROOF-0001", accepted=True), tmp_path)
    assert "accepted" in out
    assert "rejected" not in out
    assert "inconclusive" not in out


def test_proof_submit_renders_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _ws(tmp_path, monkeypatch)
    out = _submit(monkeypatch, _attempt("PROOF-0001"), tmp_path)
    assert "rejected" in out, "a genuine rejection must still read as one"
    assert "inconclusive" not in out
