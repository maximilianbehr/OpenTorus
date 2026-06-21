"""Hostile referee for a problem dossier (post-proof integrity stage).

After the prove loop has run, the referee plays the role a journal referee plays:
it reads only the persisted artifacts and tries to find every way the dossier
overstates what it has. It is deterministic (no model required) so the verdict is
reproducible from the workspace alone; a ``provider`` may be supplied for an
optional narrated summary using :data:`prompts/referee.md`, but is never required.

For each claim it produces a classification — ``proved`` / ``cited`` /
``heuristic`` / ``unsupported`` / ``refuted`` — then:

* recommends downgrading any theorem-like claim that is *not* proved or cited
  (``THEOREM`` → ``CONJECTURE``), surfacing it as a finding rather than silently
  rewriting truth status (the dossier's CRUD applies a downgrade only on request);
* flags contradictions across the claim set;
* runs the artifact-aware honesty linter over every claim and proof body to catch
  overclaiming;
* derives the report status gate.

The result is persisted as a machine-readable JSON record plus a human ``.md``
summary under ``<dossier>/referee/``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, Field

from opentorus.jsonl import next_sequential_id
from opentorus.research.dossier import store
from opentorus.research.dossier.honesty import lint_report
from opentorus.research.dossier.models import ClaimRecord, ClaimType, EvidenceRecord, utcnow
from opentorus.research.dossier.validation import evidence_can_verify

ClaimClassification = Literal["proved", "cited", "heuristic", "unsupported", "refuted"]
RefereeVerdict = Literal["pass", "revise", "block"]

# Claim types that assert a mathematical result and so must be backed to stand.
_THEOREM_LIKE: frozenset[str] = frozenset({"THEOREM", "LEMMA_ATTEMPT", "CLAIM"})


class ClaimAssessment(BaseModel):
    claim_id: str
    claim_type: str
    statement: str
    status: str
    classification: ClaimClassification
    rationale: str
    recommended_type: str | None = None


class Overclaim(BaseModel):
    location: str
    phrase: str
    kind: str
    suggestion: str


class RefereeReport(BaseModel):
    id: str
    problem_id: str
    verdict: RefereeVerdict
    report_status: str
    assessments: list[ClaimAssessment] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    overclaims: list[Overclaim] = Field(default_factory=list)
    downgrades_recommended: list[str] = Field(default_factory=list)
    summary: str = ""
    created_at: str = ""


def referee_dir(ot_dir: Path, problem_id: str) -> Path:
    return store.dossier_dir(ot_dir, problem_id) / "referee"


def referee_prompt() -> str:
    """Return the reusable referee prompt (``prompts/referee.md``).

    Searches upward from this module for a ``prompts/referee.md`` (found in both an
    editable install and a checkout). Raises if absent — the deterministic referee
    does not need it; it is for an optional narrated summary.
    """
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "prompts" / "referee.md"
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8")
    raise FileNotFoundError("prompts/referee.md not found upward from the package.")


def _has_verification(claim: ClaimRecord, evidence: list[EvidenceRecord], proofs: list) -> bool:  # noqa: ANN001
    """Mirror of claims._has_verification_artifact, kept local to stay self-contained."""
    by_id = {e.id: e for e in evidence}
    for ev_id in claim.evidence_links:
        ev = by_id.get(ev_id)
        if ev is not None and ev.direction == "supports" and evidence_can_verify(ev.type):
            return True
    return any(p.status == "verified" and claim.id in (p.claim_links or []) for p in proofs)


def _classify(
    claim: ClaimRecord,
    evidence: list[EvidenceRecord],
    proofs: list,  # noqa: ANN001
) -> tuple[ClaimClassification, str]:
    claim_evidence = [e for e in evidence if e.claim_id == claim.id]
    supporting = [e for e in claim_evidence if e.direction == "supports"]
    contradicting = [e for e in claim_evidence if e.direction == "contradicts"]

    if claim.status in ("verified", "formally_verified") or _has_verification(
        claim, evidence, proofs
    ):
        return "proved", "Backed by a verification artifact (verified proof / formal evidence)."
    if claim.status in ("refuted", "contradicted") or contradicting:
        return "refuted", "Contradicted or refuted by recorded evidence."
    if claim.type in ("THEOREM", "REFERENCE_FACT") and claim.source_artifacts:
        return (
            "cited",
            "Asserted on the authority of a cited source; not verified locally.",
        )
    if claim.type in ("HEURISTIC", "EXPERIMENTAL_OBSERVATION"):
        return "heuristic", "Declared heuristic/empirical; supports a conjecture, proves nothing."
    if supporting:
        return (
            "heuristic",
            "Supported only by experiments/sketches/notes — evidence, not verification.",
        )
    return "unsupported", "No verification artifact, no cited source, and no supporting evidence."


def _recommended_downgrade(claim: ClaimRecord, classification: ClaimClassification) -> str | None:
    """A theorem-like claim that is not proved or cited should not be called a theorem."""
    if classification in ("unsupported", "heuristic") and claim.type in _THEOREM_LIKE:
        return "CONJECTURE"
    return None


def _find_contradictions(claims: list[ClaimRecord], evidence: list[EvidenceRecord]) -> list[str]:
    out: list[str] = []
    for c in claims:
        ev = [e for e in evidence if e.claim_id == c.id]
        has_support = any(e.direction == "supports" for e in ev)
        has_contra = any(e.direction == "contradicts" for e in ev)
        if has_support and has_contra:
            out.append(
                f"{c.id} has both supporting and contradicting evidence; reconcile before "
                "presenting it as settled."
            )
        if c.status in ("contradicted", "refuted"):
            out.append(f"{c.id} is {c.status}; it must not be relied upon as a result.")
    # A verified counterexample alongside a non-refuted positive claim is a conflict.
    verified_cx = [c for c in claims if c.type == "COUNTEREXAMPLE_VERIFIED"]
    positive = [
        c
        for c in claims
        if c.type in ("THEOREM", "LEMMA_ATTEMPT", "CONJECTURE", "CLAIM")
        and c.status in ("supported", "verified", "formally_verified")
    ]
    if verified_cx and positive:
        out.append(
            f"A verified counterexample ({', '.join(c.id for c in verified_cx)}) coexists with "
            f"supported positive claim(s) ({', '.join(c.id for c in positive)}); these cannot "
            "both stand."
        )
    return out


def _collect_overclaims(
    ot_dir: Path,
    problem_id: str,
    claims: list[ClaimRecord],
    proofs: list,  # noqa: ANN001
    *,
    has_verified_proof: bool,
    has_reference: bool,
    has_supported_theorem: bool,
) -> list[Overclaim]:
    out: list[Overclaim] = []

    def _lint(text: str, location: str) -> None:
        for issue in lint_report(
            text,
            has_verified_proof=has_verified_proof,
            has_reference=has_reference,
            has_supported_theorem=has_supported_theorem,
        ):
            out.append(
                Overclaim(
                    location=location,
                    phrase=issue.phrase,
                    kind=issue.kind.value,
                    suggestion=issue.suggestion,
                )
            )

    for c in claims:
        _lint(f"{c.statement}\n{c.notes or ''}", f"{c.id} statement/notes")
    for p in proofs:
        body_path = getattr(p, "body_path", None)
        if not body_path:
            continue
        f = store.dossier_dir(ot_dir, problem_id) / body_path
        if f.is_file():
            _lint(f.read_text(encoding="utf-8"), f"{p.id} body")
    return out


def referee_review(
    ot_dir: Path,
    problem_id: str,
    *,
    provider=None,  # noqa: ANN001 - reserved for optional narrated summary
    apply_downgrades: bool = False,
) -> RefereeReport:
    """Run the hostile referee over a dossier and persist a JSON + markdown report."""
    from opentorus.research.dossier.report import honesty_context
    from opentorus.research.dossier.status_gate import derive_status

    store.require_dossier(ot_dir, problem_id)
    claims = store.list_claims(ot_dir, problem_id)
    evidence = store.list_evidence(ot_dir, problem_id)
    proofs = store.list_proof_attempts(ot_dir, problem_id)
    has_proof, has_ref, has_thm = honesty_context(ot_dir, problem_id)

    assessments: list[ClaimAssessment] = []
    downgrades: list[str] = []
    for c in claims:
        classification, why = _classify(c, evidence, proofs)
        rec = _recommended_downgrade(c, classification)
        assessments.append(
            ClaimAssessment(
                claim_id=c.id,
                claim_type=c.type,
                statement=c.statement,
                status=c.status,
                classification=classification,
                rationale=why,
                recommended_type=rec,
            )
        )
        if rec is not None:
            downgrades.append(f"{c.id}: {c.type} → {rec} ({classification})")

    contradictions = _find_contradictions(claims, evidence)
    overclaims = _collect_overclaims(
        ot_dir,
        problem_id,
        claims,
        proofs,
        has_verified_proof=has_proof,
        has_reference=has_ref,
        has_supported_theorem=has_thm,
    )

    # Optionally apply the recommended downgrades through the dossier's CRUD so the
    # change is logged in the status changelog (never a silent rewrite).
    if apply_downgrades and downgrades:
        from opentorus.research.dossier.claims import downgrade_claim_type

        for a in assessments:
            if a.recommended_type:
                downgrade_claim_type(
                    ot_dir,
                    problem_id,
                    a.claim_id,
                    cast(ClaimType, a.recommended_type),
                    reason=f"referee: {a.classification} {a.claim_type} cannot stand as written",
                )

    hard_overclaim = any(
        o.kind in ("experiment_proof", "proof_claim", "result_claim") for o in overclaims
    )
    if contradictions or hard_overclaim:
        verdict: RefereeVerdict = "block"
    elif downgrades or overclaims or any(a.classification == "heuristic" for a in assessments):
        verdict = "revise"
    else:
        verdict = "pass"

    status_verdict = derive_status(ot_dir, problem_id, referee_blocked=bool(contradictions))

    summary = _summary(verdict, status_verdict.status, assessments, contradictions, overclaims)

    existing = _list_records(ot_dir, problem_id)
    report = RefereeReport(
        id=next_sequential_id("REFEREE", len(existing)),
        problem_id=problem_id,
        verdict=verdict,
        report_status=status_verdict.status,
        assessments=assessments,
        contradictions=contradictions,
        overclaims=overclaims,
        downgrades_recommended=downgrades,
        summary=summary,
        created_at=utcnow().isoformat(),
    )
    _persist(ot_dir, problem_id, report)
    return report


def _summary(
    verdict: RefereeVerdict,
    report_status: str,
    assessments: list[ClaimAssessment],
    contradictions: list[str],
    overclaims: list[Overclaim],
) -> str:
    by_class: dict[str, int] = {}
    for a in assessments:
        by_class[a.classification] = by_class.get(a.classification, 0) + 1
    breakdown = ", ".join(f"{n} {k}" for k, n in sorted(by_class.items())) or "no claims"
    return (
        f"Referee verdict: {verdict}. Derived report status: {report_status}. "
        f"Claims by classification: {breakdown}. "
        f"{len(contradictions)} contradiction(s), {len(overclaims)} overclaim(s)."
    )


def render_referee(report: RefereeReport) -> str:
    lines = [
        f"# {report.id} — referee of {report.problem_id}",
        "",
        f"- Verdict: **{report.verdict}**",
        f"- Derived report status: **{report.report_status}**",
        "",
        report.summary,
        "",
        "## Claim classification",
        "",
    ]
    if report.assessments:
        for a in report.assessments:
            rec = f" → recommend **{a.recommended_type}**" if a.recommended_type else ""
            lines.append(
                f"- {a.claim_id} [{a.claim_type} / {a.status}] — **{a.classification}**{rec}: "
                f"{a.rationale}"
            )
    else:
        lines.append("_No claims recorded._")
    lines.append("")
    lines.append("## Contradictions")
    lines.append("")
    lines.extend([f"- {c}" for c in report.contradictions] or ["- none found"])
    lines.append("")
    lines.append("## Overclaiming language")
    lines.append("")
    if report.overclaims:
        for o in report.overclaims:
            lines.append(f"- {o.location} [{o.kind}] '{o.phrase}': {o.suggestion}")
    else:
        lines.append("- none — report language matches the artifacts")
    lines.append("")
    lines.append("## Recommended downgrades")
    lines.append("")
    lines.extend([f"- {d}" for d in report.downgrades_recommended] or ["- none"])
    lines.append("")
    lines.append(
        "> The referee challenges and records; it never upgrades truth status. Downgrades are "
        "recommendations applied only via the dossier's CRUD."
    )
    return "\n".join(lines) + "\n"


def _records_index(ot_dir: Path, problem_id: str) -> Path:
    return referee_dir(ot_dir, problem_id) / "index.jsonl"


def _list_records(ot_dir: Path, problem_id: str) -> list[RefereeReport]:
    path = _records_index(ot_dir, problem_id)
    if not path.is_file():
        return []
    out: list[RefereeReport] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(RefereeReport.model_validate_json(line))
    return out


def latest_referee(ot_dir: Path, problem_id: str) -> RefereeReport | None:
    records = _list_records(ot_dir, problem_id)
    return records[-1] if records else None


def _persist(ot_dir: Path, problem_id: str, report: RefereeReport) -> None:
    rdir = referee_dir(ot_dir, problem_id)
    rdir.mkdir(parents=True, exist_ok=True)
    with (_records_index(ot_dir, problem_id)).open("a", encoding="utf-8") as fh:
        fh.write(report.model_dump_json() + "\n")
    (rdir / f"{report.id}.json").write_text(
        json.dumps(report.model_dump(), indent=2), encoding="utf-8"
    )
    (rdir / f"{report.id}.md").write_text(render_referee(report), encoding="utf-8")
