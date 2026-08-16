"""The general-conjecture scope policy layer (``dossier.scope``).

Pins the honesty core of the campaign classifications: the two resolving labels
(GENERAL_CONJECTURE_PROVED / _REFUTED) are derivable only from verification-grade
artifacts on the designated primary claim of a *general* target — sketches,
experiments, and supported claims can never produce them. The layer is derived
and additive; it never changes claim statuses.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import claims, scope, store
from opentorus.workspace import init_workspace, workspace_dir

GENERAL_STATEMENT = (
    "Conjecture: there exists a universal constant K such that for every d and all "
    "vectors v_1..v_n with unit norm there are signs with small imbalance."
)
FIXED_STATEMENT = (
    "Construct or prove the nonexistence of a (7,5)-difference triangle set with scope at most 111."
)


def _dossier(tmp_path: Path, statement: str):
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    dossier = store.create_dossier(ot, statement, title="Target")
    return ot, dossier.id


def test_classify_target_general_fixed_unclear() -> None:
    assert scope.classify_target(GENERAL_STATEMENT) == "general"
    assert scope.classify_target(FIXED_STATEMENT) == "fixed_instance"
    assert scope.classify_target("Is this identity nice?") == "unclear"
    # A general quantifier wins over instance mentions (instances are tools).
    mixed = "For every graph G the bound holds; verified for n = 8 by computer."
    assert scope.classify_target(mixed) == "general"


def test_empty_dossier_is_status_uncertain(tmp_path: Path) -> None:
    ot, pid = _dossier(tmp_path, GENERAL_STATEMENT)
    label, _ = scope.classify_outcome(ot, pid)
    assert label == "STATUS_UNCERTAIN"


def test_sketches_and_experiments_never_resolve_the_campaign(tmp_path: Path) -> None:
    # The invariant pin: a dossier full of conjecture-grade material — a supported
    # claim, plain experiment evidence — classifies as evidence, never as
    # PROVED/REFUTED, even when designated primary.
    ot, pid = _dossier(tmp_path, GENERAL_STATEMENT)
    claim = claims.add_claim(
        ot, pid, claim_type="CONJECTURE", statement="The full conjecture holds."
    )
    dossier = store.require_dossier(ot, pid)
    dossier.primary_claim_id = claim.id
    store.save_dossier(ot, dossier)
    claims.add_evidence(
        ot, pid, claim.id, evidence_type="COMPUTATION", summary="random sweeps agree"
    )
    label, _ = scope.classify_outcome(ot, pid)
    assert label == "NUMERICAL_EVIDENCE"
    assert label not in ("GENERAL_CONJECTURE_PROVED", "GENERAL_CONJECTURE_REFUTED")


def test_validated_numerics_is_computational_evidence(tmp_path: Path, accepted_proof) -> None:
    ot, pid = _dossier(tmp_path, GENERAL_STATEMENT)
    claim = claims.add_claim(ot, pid, claim_type="CLAIM", statement="Bound holds for n<=10.")
    claims.add_evidence(
        ot,
        pid,
        claim.id,
        evidence_type="VALIDATED_NUMERICAL",
        summary="interval-certified",
        source_artifacts=[accepted_proof(ot, claim.id)],
    )
    label, _ = scope.classify_outcome(ot, pid)
    assert label == "COMPUTATIONAL_EVIDENCE"


def test_formally_verified_primary_resolves_general_target_only(
    tmp_path: Path, accepted_proof
) -> None:
    ot, pid = _dossier(tmp_path, GENERAL_STATEMENT)
    claim = claims.add_claim(ot, pid, claim_type="CLAIM", statement="The full conjecture.")
    # The legitimate promotion route: an accepted verifier run, cited as verification
    # evidence, then the gated status change. "accepted proof" now names a real one.
    claims.add_evidence(
        ot,
        pid,
        claim.id,
        evidence_type="FORMAL_PROOF",
        summary="accepted proof",
        source_artifacts=[accepted_proof(ot, claim.id)],
    )
    claims.set_claim_status(ot, pid, claim.id, "formally_verified")

    # Without primary designation: partial theorem, never the resolving label.
    label, _ = scope.classify_outcome(ot, pid)
    assert label == "VERIFIED_PARTIAL_THEOREM"

    dossier = store.require_dossier(ot, pid)
    dossier.primary_claim_id = claim.id
    store.save_dossier(ot, dossier)
    label, rationale = scope.classify_outcome(ot, pid)
    assert label == "GENERAL_CONJECTURE_PROVED"
    assert claim.id in rationale


def test_formally_verified_primary_on_fixed_target_stays_partial(
    tmp_path: Path, accepted_proof
) -> None:
    ot, pid = _dossier(tmp_path, FIXED_STATEMENT)
    claim = claims.add_claim(ot, pid, claim_type="CLAIM", statement="The instance works.")
    claims.add_evidence(
        ot,
        pid,
        claim.id,
        evidence_type="FORMAL_PROOF",
        summary="accepted certificate",
        source_artifacts=[accepted_proof(ot, claim.id)],
    )
    claims.set_claim_status(ot, pid, claim.id, "formally_verified")
    dossier = store.require_dossier(ot, pid)
    dossier.primary_claim_id = claim.id
    store.save_dossier(ot, dossier)
    label, _ = scope.classify_outcome(ot, pid)
    assert label == "VERIFIED_PARTIAL_THEOREM"  # a fixed instance cannot resolve a campaign


def test_failed_attempts_classify_as_failed_attempt(tmp_path: Path) -> None:
    ot, pid = _dossier(tmp_path, GENERAL_STATEMENT)
    store.add_failed_attempt(
        ot, pid, attempted_method="induction on n", reason_failed="base case does not extend"
    )
    label, _ = scope.classify_outcome(ot, pid)
    assert label == "FAILED_ATTEMPT"


def test_primary_claim_field_is_additive(tmp_path: Path) -> None:
    # Old dossiers (no primary_claim_id in problem.yaml) load unchanged.
    ot, pid = _dossier(tmp_path, GENERAL_STATEMENT)
    dossier = store.require_dossier(ot, pid)
    assert dossier.primary_claim_id is None
