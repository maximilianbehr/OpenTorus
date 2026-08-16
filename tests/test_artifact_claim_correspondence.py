"""An accepted proof establishes *something* — not necessarily the claim citing it.

Requiring verification evidence to cite an accepted ``PROOF-*`` closes the hole where
the type field alone counted as verification. It does not close the next one: nobody
checks that the proof is *about* the claim. Observed in a real run (sidorenko), where
the workspace's only two accepted proofs were ``1/8 >= 1/16`` and ``1/32 >= 1/512`` —
true, and about nothing in particular.

Full correspondence checking is undecidable here, so the guard is deliberately narrow:
it fires only when the certificate provably has no free variables *and* the claim it
backs quantifies over a class. It raises the question; it never blocks.

The second file pinned here is the claim-id namespace: the workspace ladder and each
dossier share the ``CLAIM-NNNN`` space while ``proofs.jsonl`` is workspace-global, so
one workspace held a dossier CLAIM-0001 ("for every bipartite graph H …") and a
workspace CLAIM-0001 ("for the 4-vertex block graph …") at the same time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from opentorus.config import default_config
from opentorus.research.dossier import claims, store
from opentorus.research.dossier.referee import referee_review
from opentorus.research.verifiers.base import certificate_is_constant
from opentorus.research.verifiers.proofs import accepted_proof_for_claim, submit_proof
from opentorus.research.verifiers.sympy_backend import SymPyVerifier
from opentorus.workspace import init_workspace, workspace_dir

GENERAL = "For every bipartite graph H and every graph G, t_H(G) >= t_K2(G)^e(H)."
INSTANCE = "For the 4-vertex block graph G_block, t_{C_4}(G_block) >= (1/2)^4."

# Verbatim from the observed run: true, accepted, and vacuous.
_VACUOUS = json.dumps({"lhs": "1/8", "rhs": "1/16", "relation": "ge", "vars": []})
_WITH_VARS = json.dumps(
    {"lhs": "sin(x)**2 + cos(x)**2", "rhs": "1", "relation": "eq", "vars": {"x": "real"}}
)


def _problem(tmp_path: Path, statement: str = GENERAL) -> tuple[Path, str]:
    init_workspace(tmp_path)
    base = workspace_dir(tmp_path)
    return base, store.create_dossier(base, statement).id


def _submit(base: Path, source: str, **kw):
    return submit_proof(base, default_config(), "sympy", source, verifier=SymPyVerifier(), **kw)


# --- the detector -------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "constant"),
    [
        (_VACUOUS, True),
        (json.dumps({"lhs": "1/32", "rhs": "1/512", "relation": "ge", "vars": []}), True),
        (_WITH_VARS, False),
        (json.dumps({"lhs": "a+b", "rhs": "b+a", "relation": "eq", "vars": {"a": "real"}}), False),
        # An interval box pinned to a point is one numeric instance too.
        (json.dumps({"expression": "sqrt(x)", "variables": {"x": [2, 2]}, "bound": 2}), True),
        (json.dumps({"expression": "sqrt(x)", "variables": {"x": [1, 3.9]}, "bound": 2}), False),
    ],
)
def test_constant_certificate_detection(source: str, constant: bool) -> None:
    assert certificate_is_constant(source) is constant


@pytest.mark.parametrize("source", ["theorem foo : True := trivial", "(assert (> 1 2))", ""])
def test_non_json_source_is_never_called_constant(source: str) -> None:
    """Lean/Coq/SMT source is not a certificate; stay silent rather than guess."""
    assert certificate_is_constant(source) is False


# --- the referee finding ------------------------------------------------------


def test_vacuous_artifact_backing_a_general_claim_is_flagged(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement=GENERAL)
    attempt = _submit(base, _VACUOUS, claim_id=claim.id, problem_id=pid)
    claims.add_evidence(
        base,
        pid,
        claim.id,
        evidence_type="FORMAL_PROOF",
        summary="machine-checked",
        source_artifacts=[attempt.id],
    )

    report = referee_review(base, pid, persist=False)
    findings = [o for o in report.overclaims if o.kind == "instance_artifact_for_general_claim"]
    assert len(findings) == 1
    assert attempt.id in findings[0].phrase
    assert "quantifies over a whole class" in findings[0].suggestion
    assert "open gap" in findings[0].suggestion


def test_the_finding_asks_rather_than_blocks(tmp_path: Path) -> None:
    """A heuristic must not halt a run — it raises the question for a reader."""
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement=GENERAL)
    attempt = _submit(base, _VACUOUS, claim_id=claim.id, problem_id=pid)
    claims.add_evidence(
        base, pid, claim.id, evidence_type="FORMAL_PROOF", source_artifacts=[attempt.id]
    )
    assert referee_review(base, pid, persist=False).verdict == "revise"


def test_an_instance_claim_is_not_flagged(tmp_path: Path) -> None:
    """The same artifact is perfectly good evidence for the instance it checks."""
    base, pid = _problem(tmp_path, INSTANCE)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement=INSTANCE)
    attempt = _submit(base, _VACUOUS, claim_id=claim.id, problem_id=pid)
    claims.add_evidence(
        base, pid, claim.id, evidence_type="FORMAL_PROOF", source_artifacts=[attempt.id]
    )
    report = referee_review(base, pid, persist=False)
    assert not [o for o in report.overclaims if o.kind == "instance_artifact_for_general_claim"]


def test_a_certificate_with_free_variables_is_not_flagged(tmp_path: Path) -> None:
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement=GENERAL)
    attempt = _submit(base, _WITH_VARS, claim_id=claim.id, problem_id=pid)
    claims.add_evidence(
        base, pid, claim.id, evidence_type="FORMAL_PROOF", source_artifacts=[attempt.id]
    )
    report = referee_review(base, pid, persist=False)
    assert not [o for o in report.overclaims if o.kind == "instance_artifact_for_general_claim"]


# --- claim-id namespaces ------------------------------------------------------


def test_a_dossier_proof_does_not_answer_a_workspace_lookup(tmp_path: Path) -> None:
    """The observed collision: same id, opposite scope, one global proof ledger."""
    base, pid = _problem(tmp_path)
    dossier_claim = claims.add_claim(base, pid, claim_type="CLAIM", statement=GENERAL)
    attempt = _submit(base, _WITH_VARS, claim_id=dossier_claim.id, problem_id=pid)
    assert attempt.accepted is True

    # A workspace claim of the same id must not inherit the dossier claim's proof.
    assert accepted_proof_for_claim(base, dossier_claim.id) is None
    assert accepted_proof_for_claim(base, dossier_claim.id, problem_id=pid) is not None


def test_verification_evidence_rejects_another_dossiers_proof(tmp_path: Path) -> None:
    base, pid_a = _problem(tmp_path)
    pid_b = store.create_dossier(base, "A different conjecture entirely.").id
    claim_b = claims.add_claim(base, pid_b, claim_type="CLAIM", statement="Y holds")

    attempt = _submit(base, _WITH_VARS, claim_id="CLAIM-0001", problem_id=pid_a)
    with pytest.raises(Exception, match="not " + pid_b):
        claims.add_evidence(
            base,
            pid_b,
            claim_b.id,
            evidence_type="FORMAL_PROOF",
            summary="machine-checked",
            source_artifacts=[attempt.id],
        )


def test_an_unscoped_agent_submission_still_works(tmp_path: Path) -> None:
    """proof_submit targets workspace claims and records no dossier — keep that valid."""
    base, pid = _problem(tmp_path)
    claim = claims.add_claim(base, pid, claim_type="CLAIM", statement=GENERAL)
    attempt = _submit(base, _WITH_VARS, claim_id=claim.id)
    assert attempt.problem_id is None
    evidence, _ = claims.add_evidence(
        base, pid, claim.id, evidence_type="FORMAL_PROOF", source_artifacts=[attempt.id]
    )
    assert evidence.type == "FORMAL_PROOF"
