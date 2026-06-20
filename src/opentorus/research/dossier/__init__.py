"""The credible math dossier subsystem (Milestone M1).

A ``PROBLEM-*`` dossier is the canonical research artifact for one open
mathematical problem: a local, auditable, file-based ledger of the statement,
definitions, assumptions, known results, related papers, claims, evidence,
failed attempts, experiments, and proof attempts — with the invariant that
*evidence is not truth* enforced in code.
"""

from __future__ import annotations

from opentorus.research.dossier import claims, store, validation
from opentorus.research.dossier.models import (
    ATTACK_STRATEGIES,
    CLAIM_STATUSES,
    CLAIM_TYPES,
    EVIDENCE_TYPES,
    FORMALIZATION_STATUSES,
    PROBLEM_STATUSES,
    Approach,
    Assumption,
    AttackStrategy,
    ClaimRecord,
    ClaimStatus,
    ClaimType,
    Definition,
    EvidenceRecord,
    EvidenceType,
    ExperimentRecord,
    FailedAttempt,
    KnownResult,
    ProblemDossier,
    ProblemStatus,
    ProofAttempt,
    RelatedPaper,
    TheoremRef,
)

__all__ = [
    "claims",
    "store",
    "validation",
    "ATTACK_STRATEGIES",
    "CLAIM_STATUSES",
    "CLAIM_TYPES",
    "EVIDENCE_TYPES",
    "FORMALIZATION_STATUSES",
    "PROBLEM_STATUSES",
    "Approach",
    "Assumption",
    "AttackStrategy",
    "ClaimRecord",
    "ClaimStatus",
    "ClaimType",
    "Definition",
    "EvidenceRecord",
    "EvidenceType",
    "ExperimentRecord",
    "FailedAttempt",
    "KnownResult",
    "ProblemDossier",
    "ProblemStatus",
    "ProofAttempt",
    "RelatedPaper",
    "TheoremRef",
]
