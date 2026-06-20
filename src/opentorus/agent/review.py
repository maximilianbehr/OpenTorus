"""Multi-agent adversarial review (Phase 19).

An independent *critic* reviews a target artifact (a claim, an experiment, or a
report) and emits structured, evidence-linked findings — then a verdict. The
critic never promotes a claim's truth status; it only *challenges*, *records*
(as ``REVIEW-*`` artifacts and graph edges), and *gates* presentation.

The critic is deterministic and sees only persisted artifacts, so a review is
reproducible from the workspace alone. A ``provider`` may be supplied for future
narration but is never required.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_sequential_id, read_jsonl, rewrite_jsonl

Severity = Literal["info", "warning", "blocking"]
FindingCategory = Literal["citation", "honesty", "rigor", "support", "assumption"]
ResolutionState = Literal["open", "accepted", "disputed", "deferred"]
Verdict = Literal["pass", "revise", "block"]

# A raw finding before it is assigned a finding id: (category, severity, rationale, action).
RawFinding = tuple[FindingCategory, Severity, str, str]

_ID_RE = re.compile(r"\b(?:PAPER|CLAIM|EXP|EVIDENCE|REPORT)-\d+\b")
_SETTLED = {"human_reviewed", "verified", "formally_verified", "refuted"}


def _utcnow() -> datetime:
    return datetime.now(UTC)


class ReviewFinding(BaseModel):
    finding_id: str
    target_id: str
    category: FindingCategory
    severity: Severity
    rationale: str
    suggested_action: str = ""
    resolution: ResolutionState = "open"
    resolution_note: str = ""


class Review(BaseModel):
    id: str
    target_id: str
    target_kind: str
    critic: str = "deterministic"
    verdict: Verdict
    findings: list[ReviewFinding] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)


def reviews_dir(ot_dir: Path) -> Path:
    return ot_dir / "reviews"


def _index_path(ot_dir: Path) -> Path:
    return reviews_dir(ot_dir) / "index.jsonl"


def list_reviews(ot_dir: Path, target_id: str | None = None) -> list[Review]:
    reviews = read_jsonl(_index_path(ot_dir), Review)
    if target_id is not None:
        return [r for r in reviews if r.target_id == target_id]
    return reviews


def get_review(ot_dir: Path, review_id: str) -> Review | None:
    for review in list_reviews(ot_dir):
        if review.id == review_id:
            return review
    return None


def _verdict_for(findings: list[ReviewFinding]) -> Verdict:
    if any(f.severity == "blocking" for f in findings):
        return "block"
    if any(f.severity == "warning" for f in findings):
        return "revise"
    return "pass"


# ---------------------------------------------------------------------------
# Artifact existence (citation attacks, M59)
# ---------------------------------------------------------------------------


def _artifact_exists(ot_dir: Path, artifact_id: str) -> bool:
    prefix = artifact_id.split("-", 1)[0]
    if prefix == "CLAIM":
        from opentorus.research.claims import get_claim

        return get_claim(ot_dir, artifact_id) is not None
    if prefix == "PAPER":
        from opentorus.research.knowledge import find_paper

        return find_paper(ot_dir, artifact_id) is not None
    if prefix == "EXP":
        from opentorus.research.experiments import get_experiment

        return get_experiment(ot_dir, artifact_id) is not None
    if prefix == "EVIDENCE":
        from opentorus.research.evidence import get_evidence

        return get_evidence(ot_dir, artifact_id) is not None
    return False


def _honesty_findings(
    ot_dir: Path, target_id: str, text: str, *, has_proof: bool, has_bound: bool = False
) -> list[str]:
    from opentorus.research.honesty import lint_text

    issues = lint_text(text, has_formal_proof=has_proof, has_rigorous_bound=has_bound)
    return [f"Overclaim '{i.phrase}': {i.suggestion}" for i in issues]


# ---------------------------------------------------------------------------
# Target reviewers
# ---------------------------------------------------------------------------


def _new_finding_id(review_id: str, n: int) -> str:
    return f"{review_id}-F{n}"


def _review_claim(ot_dir: Path, claim) -> list[RawFinding]:
    from opentorus.research.evidence import list_evidence
    from opentorus.research.verifiers.proofs import accepted_proof_for_claim

    raw: list[RawFinding] = []
    evidence = list_evidence(ot_dir, claim.id)
    supporting = [e for e in evidence if e.direction == "supports"]
    contradicting = [e for e in evidence if e.direction in ("contradicts", "mixed")]
    has_proof = accepted_proof_for_claim(ot_dir, claim.id) is not None
    has_rigorous_bound = any("rigorous enclosure" in e.summary.lower() for e in supporting)

    if contradicting:
        ids = ", ".join(e.id for e in contradicting)
        raw.append(
            (
                "support",
                "blocking",
                f"Contradicting evidence exists ({ids}).",
                "Reconcile or downgrade the claim; do not present it as settled.",
            )
        )
    if claim.status not in _SETTLED and not supporting:
        raw.append(
            (
                "support",
                "warning",
                "No supporting evidence recorded.",
                "Add evidence (experiment, paper, or proof) before relying on this claim.",
            )
        )
    # Rigor attack: a verified-class status requires an accepted proof artifact.
    if claim.status == "formally_verified" and not has_proof:
        raw.append(
            (
                "rigor",
                "blocking",
                "Claimed formally_verified without an accepted proof artifact.",
                "Submit a proof to a verifier backend (M51/M62) or downgrade the status.",
            )
        )
    # Prefer a decision procedure when the goal may be decidable: sampling and
    # conjecture statuses are not rigorous, so record why and point to M61/M62.
    samples_only = not has_proof and not has_rigorous_bound
    if claim.status in ("conjecture", "numerical_evidence") and samples_only:
        raw.append(
            (
                "rigor",
                "info",
                "Relying on sampling/conjecture; this is evidence, not rigour.",
                "Prefer an SMT decision procedure (M62) if decidable, or validated "
                "numerics (M61) for a rigorous bound.",
            )
        )
    issues = _honesty_findings(
        ot_dir, claim.id, claim.statement, has_proof=has_proof, has_bound=has_rigorous_bound
    )
    for issue in issues:
        raw.append(("honesty", "blocking", issue, "State the rigor level precisely."))
    return raw


def _resolve_target(ot_dir: Path, target_id: str):
    prefix = target_id.split("-", 1)[0]
    if prefix == "CLAIM":
        from opentorus.research.claims import get_claim

        claim = get_claim(ot_dir, target_id)
        if claim is None:
            raise OpenTorusError(f"No claim with id '{target_id}'.")
        return "claim", _review_claim(ot_dir, claim)
    if prefix == "EXP":
        from opentorus.research.experiments import get_experiment

        if get_experiment(ot_dir, target_id) is None:
            raise OpenTorusError(f"No experiment with id '{target_id}'.")
        # Experiments are observations; the critic checks they are not overstated
        # elsewhere, so a bare experiment review has no findings by itself.
        return "experiment", []
    raise OpenTorusError(f"Cannot review '{target_id}': unsupported artifact kind.")


def review_target(ot_dir: Path, target_id: str, *, provider=None) -> Review:
    """Review an artifact into structured, persisted findings and a verdict."""
    target_kind, raw = _resolve_target(ot_dir, target_id)

    existing = list_reviews(ot_dir)
    review_id = next_sequential_id("REVIEW", len(existing))
    findings = [
        ReviewFinding(
            finding_id=_new_finding_id(review_id, n + 1),
            target_id=target_id,
            category=cat,
            severity=sev,
            rationale=rationale,
            suggested_action=action,
        )
        for n, (cat, sev, rationale, action) in enumerate(raw)
    ]
    review = Review(
        id=review_id,
        target_id=target_id,
        target_kind=target_kind,
        critic=getattr(provider, "name", "deterministic"),
        verdict=_verdict_for(findings),
        findings=findings,
    )
    _persist(ot_dir, review)

    # The challenge is itself inspectable evidence: link the review to its target.
    if review.verdict != "pass":
        from opentorus.research.graph import add_edge

        relation = (
            "contradicts"
            if any(f.category == "support" and f.severity == "blocking" for f in findings)
            else "weakens"
        )
        add_edge(
            ot_dir,
            review_id,
            target_id,
            relation,
            rationale=f"Adversarial review: {review.verdict}",
        )
    return review


def _persist(ot_dir: Path, review: Review) -> None:
    reviews_dir(ot_dir).mkdir(parents=True, exist_ok=True)
    append_jsonl(_index_path(ot_dir), review)
    (reviews_dir(ot_dir) / f"{review.id}.md").write_text(render_review(review), encoding="utf-8")


def render_review(review: Review) -> str:
    lines = [
        f"# {review.id} — review of {review.target_id} ({review.target_kind})",
        "",
        f"- Critic: {review.critic}",
        f"- Verdict: **{review.verdict}**",
        "",
        "## Findings",
        "",
    ]
    if not review.findings:
        lines.append("_No findings; the target survives review._")
    for f in review.findings:
        lines.append(
            f"- [{f.severity}] ({f.category}) {f.finding_id} [{f.resolution}]: {f.rationale}"
        )
        if f.suggested_action:
            lines.append(f"  - Suggested: {f.suggested_action}")
    lines.append("")
    lines.append("> Review is evidence and gates presentation; it never upgrades truth status.")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Rigor attack: run a bounded counterexample search against a math claim (M59)
# ---------------------------------------------------------------------------


def challenge_claim_numerically(
    ot_dir: Path,
    claim_id: str,
    predicate,
    start: int,
    stop: int,
    step: int = 1,
    *,
    description: str = "",
) -> tuple[Review, object]:
    """Attack a claim with a bounded counterexample search and record the result.

    A found counterexample becomes contradicting evidence (M50) and a blocking
    finding; a clean bounded search is recorded as weak evidence with no blocking
    finding. Returns the persisted review and the search result.
    """
    from opentorus.research.claims import get_claim
    from opentorus.research.math_experiments import counterexample_search, record_search_evidence

    if get_claim(ot_dir, claim_id) is None:
        raise OpenTorusError(f"No claim with id '{claim_id}'.")

    result = counterexample_search(predicate, start, stop, step, description=description)
    record_search_evidence(ot_dir, claim_id, result)

    existing = list_reviews(ot_dir)
    review_id = next_sequential_id("REVIEW", len(existing))
    findings: list[ReviewFinding] = []
    if result.found:
        findings.append(
            ReviewFinding(
                finding_id=_new_finding_id(review_id, 1),
                target_id=claim_id,
                category="rigor",
                severity="blocking",
                rationale=result.evidence_summary(),
                suggested_action="Refute or restrict the claim; a counterexample was found.",
            )
        )
    review = Review(
        id=review_id,
        target_id=claim_id,
        target_kind="claim",
        critic="counterexample_search",
        verdict=_verdict_for(findings),
        findings=findings,
    )
    _persist(ot_dir, review)
    if result.found:
        from opentorus.research.graph import add_edge

        add_edge(ot_dir, review_id, claim_id, "contradicts", rationale="Counterexample found.")
    return review, result


# ---------------------------------------------------------------------------
# Resolution & gating (M60)
# ---------------------------------------------------------------------------


def resolve_finding(
    ot_dir: Path,
    review_id: str,
    finding_id: str,
    resolution: ResolutionState,
    note: str = "",
) -> Review:
    """Record a resolution (accepted/disputed/deferred) for a finding."""
    if resolution not in ("open", "accepted", "disputed", "deferred"):
        raise OpenTorusError(f"Invalid resolution '{resolution}'.")
    reviews = list_reviews(ot_dir)
    target = next((r for r in reviews if r.id == review_id), None)
    if target is None:
        raise OpenTorusError(f"No review with id '{review_id}'.")
    found = False
    for f in target.findings:
        if f.finding_id == finding_id:
            f.resolution = resolution
            f.resolution_note = note
            found = True
    if not found:
        raise OpenTorusError(f"No finding '{finding_id}' in review '{review_id}'.")
    rewrite_jsonl(_index_path(ot_dir), reviews)
    (reviews_dir(ot_dir) / f"{target.id}.md").write_text(render_review(target), encoding="utf-8")
    return target


def open_blocking_findings(ot_dir: Path, target_id: str) -> list[ReviewFinding]:
    """All unresolved blocking findings across reviews of ``target_id``."""
    blocking: list[ReviewFinding] = []
    for review in list_reviews(ot_dir, target_id):
        blocking.extend(
            f for f in review.findings if f.severity == "blocking" and f.resolution == "open"
        )
    return blocking


class GateDecision(BaseModel):
    allowed: bool
    enforced: bool
    reason: str
    blocking: list[ReviewFinding] = Field(default_factory=list)


def gate_publication(ot_dir: Path, target_id: str, *, review_mode: bool) -> GateDecision:
    """Decide whether a target may be presented/published.

    Open blocking findings forbid publication in ``review`` mode (enforced) and
    are advisory otherwise. Resolving or disputing the findings clears the gate.
    """
    blocking = open_blocking_findings(ot_dir, target_id)
    if not blocking:
        return GateDecision(allowed=True, enforced=review_mode, reason="No open blocking findings.")
    reason = f"{len(blocking)} open blocking finding(s) for {target_id}."
    if review_mode:
        return GateDecision(allowed=False, enforced=True, reason=reason, blocking=blocking)
    return GateDecision(
        allowed=True,
        enforced=False,
        reason=f"{reason} Advisory only in normal mode.",
        blocking=blocking,
    )
