"""Tests for the C/D/UI increment:

- C-step-2: `init --problem` creates a single, active dossier.
- UI#4: the dashboard's Problems panel.
- UI#6: structured provider-error formatting.
- D-step-1: characterization of the global claim/evidence stack's epistemic guards
  (pins behavior that any future unification with the dossier stack must preserve).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentorus.cli import app
from opentorus.errors import OpenTorusError
from opentorus.workspace import init_workspace, workspace_dir

runner = CliRunner()


# --- C-step-2 ----------------------------------------------------------------


def test_init_problem_creates_active_dossier(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    res = runner.invoke(app, ["init", "--problem", "Prove or refute: every widget folds."])
    assert res.exit_code == 0, res.stdout
    assert "PROBLEM-0001" in res.stdout
    from opentorus.research.dossier import store

    base = workspace_dir(tmp_path)
    assert store.get_active_problem(base) == "PROBLEM-0001"
    # Subsequent commands work with no id (operate on the active problem).
    assert runner.invoke(app, ["problem", "show"]).exit_code == 0


# --- UI#4 dashboard ----------------------------------------------------------


def test_dashboard_problems_panel(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    from opentorus.research.dossier import claims, store
    from opentorus.tui.panels import build_dashboard

    d = store.create_dossier(base, "Conjecture X.")
    claims.add_claim(base, d.id, claim_type="CONJECTURE", statement="X holds.")
    out = build_dashboard(tmp_path)
    assert "Problems" in out
    assert "PROBLEM-0001" in out
    assert "unverified" in out  # claims-by-status tally


# --- UI#6 provider error UX --------------------------------------------------


def test_provider_error_api_key() -> None:
    from opentorus.ux import format_provider_error

    msg = format_provider_error("OPENAI_API_KEY is not set")
    assert "Likely cause" in msg and "Next action" in msg
    assert "key" in msg.lower()


def test_provider_error_unreachable() -> None:
    from opentorus.ux import provider_error_cause

    cause, action = provider_error_cause("Could not reach Ollama at http://localhost:11434")
    assert "unreachable" in cause.lower()
    assert "ollama serve" in action.lower() or "base_url" in action.lower()


def test_provider_error_no_tools() -> None:
    from opentorus.ux import provider_error_cause

    cause, _ = provider_error_cause("model 'x' does not support tools")
    assert "tool" in cause.lower()


# --- D-step-1 characterization (global stack epistemic guards) ----------------


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_global_evidence_never_changes_claim_status(tmp_path: Path) -> None:
    from opentorus.research.claims import get_claim, new_claim
    from opentorus.research.evidence import add_evidence

    ot = _ws(tmp_path)
    c = new_claim(ot, "X holds for all n.")
    add_evidence(ot, c.id, source_type="experiment", direction="supports", strength="strong")
    after = get_claim(ot, c.id)
    assert after is not None
    assert after.status not in {"verified", "formally_verified"}


def test_global_formally_verified_requires_proof(tmp_path: Path) -> None:
    from opentorus.research.claims import new_claim, update_claim

    ot = _ws(tmp_path)
    c = new_claim(ot, "X.")
    with pytest.raises(OpenTorusError):
        update_claim(ot, c.id, status="formally_verified")


def test_global_verified_requires_confirmation(tmp_path: Path) -> None:
    from opentorus.research.claims import new_claim, update_claim

    ot = _ws(tmp_path)
    c = new_claim(ot, "X.")
    with pytest.raises(OpenTorusError):
        update_claim(ot, c.id, status="verified")  # no confirm callback
