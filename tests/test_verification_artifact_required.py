"""EVAL-002, enforced against the artifact rather than against a string.

The dossier's central promise is that only a verification artifact promotes a claim.
That was enforced by checking the *type field* of an evidence record: anything typed
``FORMAL_PROOF`` counted as verification-grade, and nothing checked that a verifier
had ever run. ``EXPERIMENT`` — the one type that can never verify — was the only type
whose artifact was validated, so the check was exactly inverted.

These tests pin both directions: a promotion must be traceable to an accepted verifier
run recorded in this workspace, and the legitimate route must still work end to end.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentorus.config import default_config
from opentorus.errors import OpenTorusError
from opentorus.research.dossier import claims, store
from opentorus.research.verifiers.proofs import submit_proof
from opentorus.research.verifiers.sympy_backend import SymPyVerifier
from opentorus.workspace import init_workspace, workspace_dir

VERIFICATION_TYPES = ["FORMAL_PROOF", "VALIDATED_NUMERICAL"]


def _problem(tmp_path: Path) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    return base, store.create_dossier(base, "A conjecture about X.").id


def _submit(base: Path, source: str, claim_id: str | None = None):
    return submit_proof(
        base, default_config(), "sympy", source, claim_id=claim_id, verifier=SymPyVerifier()
    )


_TRUE_IDENTITY = json.dumps(
    {"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq", "vars": {"x": "real"}}
)
_FALSE_IDENTITY = json.dumps({"lhs": "x + 1", "rhs": "x + 2", "relation": "eq"})


# --- the hole itself ----------------------------------------------------------


@pytest.mark.parametrize("evidence_type", VERIFICATION_TYPES)
def test_bare_verification_evidence_is_refused(tmp_path: Path, evidence_type: str) -> None:
    """The exact call that used to mint verification out of nothing."""
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")
    with pytest.raises(OpenTorusError, match="verification-grade"):
        claims.add_evidence(
            base, pid, claim.id, evidence_type=evidence_type, summary="machine-checked"
        )


def test_refusal_names_the_honest_alternative(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")
    with pytest.raises(OpenTorusError) as exc:
        claims.add_evidence(base, pid, claim.id, evidence_type="FORMAL_PROOF", summary="")
    message = str(exc.value)
    assert "proof_submit" in message
    assert "EXPERIMENT" in message and "supported" in message


def test_hallucinated_proof_id_is_refused(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")
    with pytest.raises(OpenTorusError, match="no such attempt"):
        claims.add_evidence(
            base,
            pid,
            claim.id,
            evidence_type="FORMAL_PROOF",
            summary="checked",
            source_artifacts=["PROOF-9999"],
        )


def test_rejected_attempt_cannot_back_verification(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="x + 1 = x + 2")
    attempt = _submit(base, _FALSE_IDENTITY, claim.id)
    assert attempt.accepted is False
    with pytest.raises(OpenTorusError, match="no cited attempt was accepted"):
        claims.add_evidence(
            base,
            pid,
            claim.id,
            evidence_type="FORMAL_PROOF",
            summary="checked",
            source_artifacts=[attempt.id],
        )


def test_inconclusive_attempt_cannot_back_verification(tmp_path: Path) -> None:
    """A checker that gave up must not be laundered into a verification."""
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")
    attempt = _submit(base, "this is not a certificate at all", claim.id)
    assert attempt.inconclusive is True
    with pytest.raises(OpenTorusError, match="inconclusive"):
        claims.add_evidence(
            base,
            pid,
            claim.id,
            evidence_type="FORMAL_PROOF",
            summary="checked",
            source_artifacts=[attempt.id],
        )


def test_nothing_is_written_when_the_check_refuses(tmp_path: Path) -> None:
    """The guard runs before any persistence, so a refused call leaves no trace."""
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")
    with pytest.raises(OpenTorusError):
        claims.add_evidence(base, pid, claim.id, evidence_type="FORMAL_PROOF", summary="x")
    assert store.list_evidence(base, pid) == []
    assert store.get_claim(base, pid, claim.id).status == "unverified"


# --- the legitimate route still works -----------------------------------------


def test_accepted_attempt_backs_verification_and_promotes(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    cand = claims.add_claim(
        base, pid, claim_type="COUNTEREXAMPLE_CANDIDATE", statement="n=5 refutes X"
    )
    attempt = _submit(base, _TRUE_IDENTITY, cand.id)
    assert attempt.accepted is True

    evidence, _ = claims.add_evidence(
        base,
        pid,
        cand.id,
        evidence_type="FORMAL_PROOF",
        summary="machine-checked refutation",
        source_artifacts=[attempt.id],
    )
    verified = claims.verify_counterexample(
        base, pid, cand.id, verification_artifact=evidence.id, summary="confirmed"
    )
    assert verified.status == "verified"
    # The promotion is traceable all the way back to the verifier run.
    assert attempt.id in evidence.source_artifacts


def test_support_only_evidence_is_unaffected(tmp_path: Path) -> None:
    """The guard must not make ordinary, honest evidence harder to record."""
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")
    for etype in ("COMPUTATION", "PROOF_SKETCH", "PAPER"):
        evidence, _ = claims.add_evidence(
            base, pid, claim.id, evidence_type=etype, summary="supporting work"
        )
        assert evidence.type == etype
    assert store.get_claim(base, pid, claim.id).status == "supported"


def test_validated_numerics_path_records_its_own_proof_artifact(tmp_path: Path) -> None:
    """The interval route is a verifier run, so it must leave a PROOF-* behind."""
    pytest.importorskip("mpmath")
    from opentorus.research.dossier.validated_numerics import record_validated_numerical
    from opentorus.research.verifiers.proofs import get_proof

    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="sqrt(x) < 2 on [1, 3.9]")
    evidence, result = record_validated_numerical(
        base,
        pid,
        claim.id,
        certificate={
            "variables": {"x": [1, 3.9]},
            "expression": "sqrt(x)",
            "relation": "<",
            "bound": 2,
        },
    )
    assert result.accepted is True
    assert evidence is not None
    assert evidence.source_artifacts, "must cite the verifier run it is based on"
    proof = get_proof(base, evidence.source_artifacts[0])
    assert proof is not None and proof.accepted is True


# --- the CLI route ------------------------------------------------------------


def test_cli_evidence_requires_an_artifact_for_formal_proof(tmp_path: Path, monkeypatch) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    assert runner.invoke(app, ["init"]).exit_code == 0
    base = workspace_dir(tmp_path)
    pid = store.create_dossier(base, "A conjecture about X.").id
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement="X holds")

    bare = runner.invoke(
        app,
        ["problem", "evidence", pid, "--claim", claim.id, "--type", "FORMAL_PROOF"],
    )
    assert bare.exit_code == 1
    assert "verification-grade" in bare.stdout

    attempt = _submit(base, _TRUE_IDENTITY, claim.id)
    backed = runner.invoke(
        app,
        [
            "problem",
            "evidence",
            pid,
            "--claim",
            claim.id,
            "--type",
            "FORMAL_PROOF",
            "--artifact",
            attempt.id,
        ],
    )
    assert backed.exit_code == 0, backed.stdout
