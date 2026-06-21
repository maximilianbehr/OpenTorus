"""Connect the literature into the artifact graph (Milestone 47).

Citation edges (``cites`` / ``derived_from``) link ``PAPER-*`` artifacts; papers
are linked to claims as **evidence** (M17) with a direction and strength. Two
disciplines hold: contradictory evidence is *preserved*, never silently
resolved; and nothing here promotes a claim to a verified status. A gap query
surfaces claims that are weakly supported or contradicted so they can be
revisited.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.research.claims import list_claims
from opentorus.research.evidence import Evidence, add_evidence, list_evidence
from opentorus.research.graph import GraphEdge, add_edge, list_edges
from opentorus.research.papers import Paper, list_papers

_CITATION_RELATIONS = {"cites", "derived_from"}


def find_paper(ot_dir: Path, identifier: str) -> Paper | None:
    """Find a local paper by id, DOI, or arXiv id (case-insensitive)."""
    ident = identifier.strip().lower()
    for paper in list_papers(ot_dir):
        if paper.id.lower() == ident:
            return paper
        if paper.doi and paper.doi.lower() == ident:
            return paper
        if paper.arxiv_id and paper.arxiv_id.lower() == ident:
            return paper
    return None


def link_citation(
    ot_dir: Path,
    citing_paper_id: str,
    cited_identifier: str,
    *,
    relation: str = "cites",
    rationale: str = "",
) -> GraphEdge | None:
    """Add a citation edge between two *locally known* papers.

    ``cited_identifier`` may be a paper id, DOI, or arXiv id. Returns the edge, or
    ``None`` if the cited work is not in the local corpus (citations are only
    drawn between artifacts that actually exist — no invented references).
    """
    if relation not in _CITATION_RELATIONS:
        valid = ", ".join(sorted(_CITATION_RELATIONS))
        raise OpenTorusError(f"Invalid citation relation '{relation}'. Valid: {valid}")
    if find_paper(ot_dir, citing_paper_id) is None:
        raise OpenTorusError(f"No local paper with id '{citing_paper_id}'.")
    cited = find_paper(ot_dir, cited_identifier)
    if cited is None:
        return None
    if cited.id == citing_paper_id:
        return None
    for edge in list_edges(ot_dir):
        if (
            edge.source_id == citing_paper_id
            and edge.target_id == cited.id
            and edge.relation == relation
        ):
            return edge
    return add_edge(ot_dir, citing_paper_id, cited.id, relation, rationale=rationale)


def ingest_citations(
    ot_dir: Path, citing_paper_id: str, cited_identifiers: list[str]
) -> list[GraphEdge]:
    """Add ``cites`` edges for every cited identifier that resolves locally."""
    edges: list[GraphEdge] = []
    for cited in cited_identifiers:
        edge = link_citation(ot_dir, citing_paper_id, cited)
        if edge is not None:
            edges.append(edge)
    return edges


def link_paper_to_claim(
    ot_dir: Path,
    paper_id: str,
    claim_id: str,
    *,
    direction: str = "supports",
    strength: str = "moderate",
    summary: str = "",
) -> tuple[Evidence, GraphEdge, str | None]:
    """Record a paper as evidence for a claim and add a matching graph edge.

    Never changes the claim's status. Returns the evidence, the graph edge, and an
    optional advisory note (raised when the evidence contradicts the claim).
    """
    if find_paper(ot_dir, paper_id) is None:
        raise OpenTorusError(f"No local paper with id '{paper_id}'.")

    from opentorus.research.dossier.store import get_active_problem

    evidence, advisory = add_evidence(
        ot_dir,
        claim_id,
        source_type="paper",
        source_id=paper_id,
        summary=summary,
        direction=direction,
        strength=strength,
        problem_id=get_active_problem(ot_dir),
    )
    relation = "contradicts" if direction == "contradicts" else "supports"
    edge = add_edge(ot_dir, paper_id, claim_id, relation, rationale=summary)
    return evidence, edge, advisory


class ClaimGap(BaseModel):
    """A claim that is weakly supported or has contradictory evidence."""

    claim_id: str
    statement: str
    status: str
    reasons: list[str] = Field(default_factory=list)
    support_count: int = 0
    contradiction_count: int = 0


_STRENGTH_WEIGHT = {"weak": 1, "moderate": 2, "strong": 3}
# Statuses considered settled enough that they are not flagged as gaps.
_SETTLED = {"human_reviewed", "verified", "refuted"}


def find_gaps(ot_dir: Path) -> list[ClaimGap]:
    """Surface claims that are contradicted or insufficiently supported.

    A claim is a gap when it has contradictory evidence, or when (below a settled
    status) it lacks at least one strong (or two moderate) supporting items.
    """
    gaps: list[ClaimGap] = []
    all_evidence = list_evidence(ot_dir)
    by_claim: dict[str, list[Evidence]] = {}
    for ev in all_evidence:
        by_claim.setdefault(ev.claim_id, []).append(ev)

    for claim in list_claims(ot_dir):
        evidence = by_claim.get(claim.id, [])
        supporting = [e for e in evidence if e.direction == "supports"]
        contradicting = [e for e in evidence if e.direction in ("contradicts", "mixed")]
        support_score = sum(_STRENGTH_WEIGHT.get(e.strength, 0) for e in supporting)

        reasons: list[str] = []
        if contradicting:
            reasons.append(f"{len(contradicting)} contradicting evidence item(s)")
        if claim.status not in _SETTLED and support_score < 3:
            reasons.append("weak support" if supporting else "no supporting evidence")

        if reasons:
            gaps.append(
                ClaimGap(
                    claim_id=claim.id,
                    statement=claim.statement,
                    status=claim.status,
                    reasons=reasons,
                    support_count=len(supporting),
                    contradiction_count=len(contradicting),
                )
            )
    return gaps


def _verification_path(gap: ClaimGap) -> str:
    """Propose a concrete, honest way to test a gap (never a guarantee)."""
    if gap.contradiction_count > 0:
        return (
            "Replicate the contradicting result in a numerical experiment and compare "
            "directly against the supporting evidence; reconcile or downgrade the claim."
        )
    if gap.support_count == 0:
        return (
            "Search the literature for primary sources, then design a numerical experiment "
            "or proof sketch to test the claim before treating it as evidence."
        )
    return (
        "Strengthen with an additional independent source or a confirming numerical "
        "experiment; current support is weak."
    )


def propose_hypotheses(ot_dir: Path):
    """For each research gap, record a testable ``hypotheses`` memory entry.

    Each hypothesis links its source claim and the evidence behind the gap, and
    states a proposed verification path. Hypotheses are evidence, never promoted
    to claims. Returns the created memory entries.
    """
    from opentorus.research.memory import add_memory

    created = []
    for gap in find_gaps(ot_dir):
        evidence_ids = [e.id for e in list_evidence(ot_dir, gap.claim_id)]
        evidence_str = ", ".join(evidence_ids) if evidence_ids else "none yet"
        text = (
            f"Hypothesis (for {gap.claim_id}): {gap.statement} "
            f"| gap: {'; '.join(gap.reasons)} "
            f"| evidence: {evidence_str} "
            f"| verification: {_verification_path(gap)} "
            f"| status: hypothesis (not verified)."
        )
        created.append(add_memory(ot_dir, "hypotheses", text))
    return created


def literature_subgraph(edges: list[GraphEdge]) -> list[GraphEdge]:
    """Filter edges to the literature subgraph (anything touching a PAPER node)."""
    return [
        edge
        for edge in edges
        if edge.source_id.startswith("PAPER") or edge.target_id.startswith("PAPER")
    ]
