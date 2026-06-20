"""Optional formal verification backends (Phase 16, Milestone 51).

Proof assistants (Lean 4 / mathlib, Coq) can *prove* some results rather than
merely support them. Backends are opt-in via ``config.tools.verifiers`` and gated
like external tools. Every attempt is recorded as a provenance-rich
``PROOF-*`` artifact (formal source, backend + version, exact accept/reject
output). With no backend installed, verification is honestly unavailable.
"""

from opentorus.research.verifiers.base import (
    VerificationResult,
    Verifier,
)
from opentorus.research.verifiers.proofs import (
    ProofAttempt,
    get_proof,
    list_proofs,
    submit_proof,
)
from opentorus.research.verifiers.registry import available_verifiers, get_verifier
from opentorus.research.verifiers.smt import SMTVerifier

__all__ = [
    "Verifier",
    "VerificationResult",
    "ProofAttempt",
    "submit_proof",
    "list_proofs",
    "get_proof",
    "available_verifiers",
    "get_verifier",
    "SMTVerifier",
]
