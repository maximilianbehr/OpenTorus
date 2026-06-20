"""Record validated-numerical (interval-arithmetic) certificates as evidence.

This is the integrity boundary for the ``VALIDATED_NUMERICAL`` evidence type: it is
created **only** from a certificate that the interval verifier actually accepted —
exactly as ``FORMAL_PROOF`` evidence is created only from an accepted proof. A
certificate the verifier cannot confirm produces *no* verification evidence (the
caller may still record support-only EXPERIMENT/COMPUTATION evidence separately).

A confirmed certificate is verification-grade, so the resulting evidence can promote
a ``COUNTEREXAMPLE_CANDIDATE`` via :func:`claims.verify_counterexample`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from opentorus.research.dossier import claims, store
from opentorus.research.dossier.models import EvidenceDirection, EvidenceRecord
from opentorus.research.verifiers.base import VerificationResult
from opentorus.research.verifiers.interval import IntervalVerifier


def verify_certificate(certificate: dict[str, Any] | str) -> VerificationResult:
    """Run the interval verifier on a certificate (dict or JSON string)."""
    source = certificate if isinstance(certificate, str) else json.dumps(certificate)
    return IntervalVerifier().verify(source)


def record_validated_numerical(
    ot_dir: Path,
    problem_id: str,
    claim_id: str,
    *,
    certificate: dict[str, Any] | str,
    summary: str = "",
    direction: EvidenceDirection = "supports",
) -> tuple[EvidenceRecord | None, VerificationResult]:
    """Verify a certificate and, only if accepted, attach VALIDATED_NUMERICAL evidence.

    Returns ``(evidence, result)``. ``evidence`` is ``None`` when the certificate is
    not accepted (inconclusive, invalid, or the verifier is unavailable) — nothing
    verification-grade is ever recorded from an unconfirmed certificate.
    """
    store.require_dossier(ot_dir, problem_id)
    if store.get_claim(ot_dir, problem_id, claim_id) is None:
        from opentorus.errors import OpenTorusError

        raise OpenTorusError(f"No claim '{claim_id}' in dossier '{problem_id}'.")

    result = verify_certificate(certificate)
    if not result.accepted:
        return None, result

    # Persist the certificate + verifier output for provenance.
    cert_obj = certificate if not isinstance(certificate, str) else json.loads(certificate)
    ev_dir = store.dossier_dir(ot_dir, problem_id) / "evidence"
    ev_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{claim_id}-validated-{len(store.list_evidence(ot_dir, problem_id))}"
    cert_path = ev_dir / f"{stem}.json"
    cert_path.write_text(
        json.dumps(
            {"certificate": cert_obj, "verifier": result.backend, "output": result.output},
            indent=2,
        ),
        encoding="utf-8",
    )
    rel_path = (
        str(cert_path.relative_to(ot_dir.parent))
        if ot_dir.parent in cert_path.parents
        else str(cert_path)
    )

    evidence, _ = claims.add_evidence(
        ot_dir,
        problem_id,
        claim_id,
        evidence_type="VALIDATED_NUMERICAL",
        summary=summary or result.output,
        direction=direction,
        path=rel_path,
        source_artifacts=[],
    )
    return evidence, result
