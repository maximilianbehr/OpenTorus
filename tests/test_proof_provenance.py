"""Which campaign produced a submission, kept apart from which claim it names.

``ProofAttempt`` carries two dossier references and they answer different questions:

* ``problem_id`` — which claim *store* ``claim_id`` belongs to (identity). The two
  stores share the ``CLAIM-NNNN`` space, so an unqualified id is ambiguous.
* ``submitted_under`` — which campaign the submission was made under (provenance).
  This is what the referee's formalization demand needs.

Collapsing them into one field is what made the id collision possible, and an attempt
to reuse ``problem_id`` for the second question blocked the campaign gate outright:
the agent's proof_submit targets workspace claims, so every real submission carries no
``problem_id`` at all.

Scope note: the leak this closes is reachable in principle but occurs in no recorded
run — it needs a workspace with several dossiers, one of them demanding formalization,
plus an accepted proof under another. No example workspace has that combination, so
the multi-dossier cases below are constructed rather than reproduced. The
single-dossier legacy case is real (observed in the sidorenko workspace: two accepted
proofs carrying no provenance).
"""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.research.dossier import store
from opentorus.research.dossier.referee import referee_review
from opentorus.research.verifiers.base import VerificationResult
from opentorus.research.verifiers.proofs import list_proofs, submit_proof
from opentorus.workspace import init_workspace, workspace_dir

DEMANDS_FORMALIZATION = "Machine-check the finite core via proof_submit.\n"


class _Accepting:
    name = "stub"

    def is_available(self) -> bool:
        return True

    def version(self) -> str | None:
        return "stub-1.0"

    def verify(self, source: str) -> VerificationResult:
        return VerificationResult(backend=self.name, accepted=True, output="QED")


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _dossier(base: Path, statement: str, demand: bool = False) -> str:
    pid = store.create_dossier(base, statement).id
    if demand:
        (store.dossier_dir(base, pid) / "statement.md").write_text(
            DEMANDS_FORMALIZATION, encoding="utf-8"
        )
    return pid


def _submit(base: Path, **kw):
    return submit_proof(base, default_config(), "sympy", "certificate", verifier=_Accepting(), **kw)


def _demand_open(base: Path, pid: str) -> bool:
    report = referee_review(base, pid, persist=False)
    return bool([o for o in report.overclaims if o.kind == "formalization_required"])


# --- the two fields are not the same thing ------------------------------------


def test_provenance_is_recorded_separately_from_identity(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    pid = _dossier(base, "A conjecture about X.")
    attempt = _submit(base, claim_id="CLAIM-0001", submitted_under=pid)

    # claim_id names a workspace claim; the submission belongs to the campaign.
    assert attempt.problem_id is None
    assert attempt.submitted_under == pid


# --- the gate --------------------------------------------------------------


def test_provenance_clears_the_demand(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    pid = _dossier(base, "A conjecture about X.", demand=True)
    _dossier(base, "An unrelated second conjecture.")

    assert _demand_open(base, pid)
    _submit(base, submitted_under=pid)
    assert not _demand_open(base, pid)


def test_another_dossiers_proof_does_not_clear_the_demand(tmp_path: Path) -> None:
    """The leak itself: constructed, because no recorded run reaches this state."""
    base = _ws(tmp_path)
    pid = _dossier(base, "A conjecture about X.", demand=True)
    other = _dossier(base, "An unrelated second conjecture.")

    _submit(base, submitted_under=other)
    assert _demand_open(base, pid), "work on another problem cannot satisfy this one"


def test_legacy_records_still_count_in_a_single_dossier_workspace(tmp_path: Path) -> None:
    """Real case: the sidorenko workspace holds accepted proofs with no provenance."""
    base = _ws(tmp_path)
    pid = _dossier(base, "A conjecture about X.", demand=True)

    _submit(base)  # no provenance, as every pre-existing record has
    assert list_proofs(base)[0].submitted_under is None
    assert not _demand_open(base, pid), "one dossier — nothing to confuse it with"


def test_legacy_records_do_not_count_once_a_second_dossier_exists(tmp_path: Path) -> None:
    base = _ws(tmp_path)
    pid = _dossier(base, "A conjecture about X.", demand=True)
    _submit(base)
    assert not _demand_open(base, pid)

    _dossier(base, "A second conjecture.")
    assert _demand_open(base, pid), "with two dossiers an unscoped record is ambiguous"


# --- the wiring that makes it reach production --------------------------------


def test_the_prove_registry_hands_the_dossier_to_proof_submit(tmp_path: Path) -> None:
    """Without this the field would exist and never be populated."""
    from opentorus.tools.builtin import build_default_registry

    base = _ws(tmp_path)
    pid = _dossier(base, "A conjecture about X.")
    config = default_config()

    registry = build_default_registry(tmp_path, base, config, problem_id=pid)
    tool = registry.get("proof_submit")
    assert tool is not None, "verifier backends are on by default (interval + sympy)"
    assert tool._problem_id == pid

    # Every other entry point records no campaign, which is the honest default.
    assert build_default_registry(tmp_path, base, config).get("proof_submit")._problem_id is None


def test_cli_submit_records_the_dossier(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    base = workspace_dir(tmp_path)
    pid = _dossier(base, "A conjecture about X.")

    source = tmp_path / "cert.json"
    source.write_text('{"lhs": "1", "rhs": "1", "relation": "eq"}', encoding="utf-8")
    result = runner.invoke(app, ["proof", "submit", "sympy", str(source), "--problem", pid])
    assert result.exit_code == 0, result.stdout
    assert list_proofs(base)[-1].submitted_under == pid
