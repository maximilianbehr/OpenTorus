"""Provenance drill-down and a read-only dashboard (Milestone 74).

``explain(id)`` traces any artifact back to its evidence: the experiments,
papers, and proofs behind it, contradicting findings from adversarial review
(Phase 19), and its current rigor level — rendered as a focused subgraph. The
dashboard is a static, deterministic export of the graph, journal, and claim
statuses. Everything here is **read-only**: it only reads ledgers, so opening it
can never mutate state.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.research.claims import (
    Claim,
    get_claim,
    list_claims,
    rigor_phrase,
)
from opentorus.research.evidence import Evidence, list_evidence
from opentorus.research.graph import GraphEdge, list_edges, to_mermaid

# Artifact-id prefix -> human label, for rendering and kind detection.
_KIND_LABELS: dict[str, str] = {
    "CLAIM": "claim",
    "PAPER": "paper",
    "EXP": "experiment",
    "EVIDENCE": "evidence",
    "REPORT": "report",
    "PROOF": "proof",
    "REVIEW": "review",
    "DATASET": "dataset",
    "REPO": "repo",
    "FIGURE": "figure",
    "EDGE": "edge",
    "JOURNAL": "journal entry",
}


def artifact_kind(artifact_id: str) -> str:
    prefix = artifact_id.split("-", 1)[0].upper()
    return _KIND_LABELS.get(prefix, "artifact")


class EvidenceView(BaseModel):
    id: str
    source_type: str
    source_id: str | None = None
    direction: str
    strength: str
    summary: str = ""


def _view(evidence: Evidence) -> EvidenceView:
    return EvidenceView(
        id=evidence.id,
        source_type=evidence.source_type,
        source_id=evidence.source_id,
        direction=evidence.direction,
        strength=evidence.strength,
        summary=evidence.summary,
    )


class ExplainResult(BaseModel):
    artifact_id: str
    kind: str
    title: str = ""
    status: str | None = None
    rigor: str = ""
    supporting: list[EvidenceView] = Field(default_factory=list)
    contradicting: list[EvidenceView] = Field(default_factory=list)
    neighbors: list[str] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    open_findings: list[str] = Field(default_factory=list)

    def subgraph_mermaid(self) -> str:
        return to_mermaid(self.edges)


def _subgraph(ot_dir: Path, artifact_id: str) -> tuple[list[GraphEdge], list[str]]:
    """All edges touching ``artifact_id`` (deterministically ordered) + neighbors."""
    touching = [e for e in list_edges(ot_dir) if artifact_id in (e.source_id, e.target_id)]
    touching.sort(key=lambda e: e.id)
    neighbors: list[str] = []
    for edge in touching:
        other = edge.target_id if edge.source_id == artifact_id else edge.source_id
        if other != artifact_id and other not in neighbors:
            neighbors.append(other)
    return touching, sorted(neighbors)


def _claim_title(ot_dir: Path, artifact_id: str, claim: Claim | None) -> str:
    if claim is not None:
        return claim.statement
    return artifact_id


def explain(ot_dir: Path, artifact_id: str) -> ExplainResult:
    """Trace ``artifact_id`` to its evidence, provenance subgraph, and rigor level.

    Read-only and deterministic. For a claim, ``status``/``rigor`` reflect the
    claim's status; supporting and contradicting evidence are separated; open
    blocking review findings (Phase 19) are listed so weaknesses are visible.
    """
    from opentorus.agent.review import open_blocking_findings

    kind = artifact_kind(artifact_id)
    edges, neighbors = _subgraph(ot_dir, artifact_id)

    claim = get_claim(ot_dir, artifact_id) if kind == "claim" else None

    # Evidence *about* this artifact (if it is a claim) plus evidence *produced by*
    # this artifact (it appears as the evidence source elsewhere).
    about = list_evidence(ot_dir, artifact_id) if kind == "claim" else []
    produced = [e for e in list_evidence(ot_dir) if e.source_id == artifact_id]
    seen: set[str] = set()
    relevant: list[Evidence] = []
    for ev in [*about, *produced]:
        if ev.id not in seen:
            seen.add(ev.id)
            relevant.append(ev)

    supporting = [_view(e) for e in relevant if e.direction == "supports"]
    contradicting = [_view(e) for e in relevant if e.direction in ("contradicts", "mixed")]

    status = claim.status if claim else None
    rigor = rigor_phrase(claim.status) if claim else ""

    findings = open_blocking_findings(ot_dir, artifact_id)
    open_findings = [f"[{f.category}] {f.rationale}" for f in findings]

    return ExplainResult(
        artifact_id=artifact_id,
        kind=kind,
        title=_claim_title(ot_dir, artifact_id, claim),
        status=status,
        rigor=rigor,
        supporting=supporting,
        contradicting=contradicting,
        neighbors=neighbors,
        edges=edges,
        open_findings=open_findings,
    )


def render_explain_text(result: ExplainResult) -> str:
    """Render an :class:`ExplainResult` as a readable, deterministic report."""
    lines = [
        f"# {result.artifact_id} ({result.kind})",
        "",
        f"- Title: {result.title}",
    ]
    if result.status:
        lines.append(f"- Status: {result.status} — {result.rigor}")
    lines.append("")
    lines.append("## Supporting evidence")
    if result.supporting:
        for ev in result.supporting:
            src = ev.source_id or ev.source_type
            lines.append(f"- {ev.id} ({src}, {ev.strength}): {ev.summary}")
    else:
        lines.append("- _None._")
    lines.append("")
    lines.append("## Contradicting evidence")
    if result.contradicting:
        for ev in result.contradicting:
            src = ev.source_id or ev.source_type
            lines.append(f"- {ev.id} ({src}, {ev.strength}): {ev.summary}")
    else:
        lines.append("- _None._")
    lines.append("")
    lines.append("## Open blocking review findings")
    if result.open_findings:
        lines.extend(f"- {f}" for f in result.open_findings)
    else:
        lines.append("- _None._")
    lines.append("")
    lines.append("## Provenance subgraph")
    if result.edges:
        for edge in result.edges:
            lines.append(f"- {edge.source_id} --{edge.relation}--> {edge.target_id}")
    else:
        lines.append("- _No graph edges touch this artifact._")
    return "\n".join(lines)


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def build_dashboard_html(ot_dir: Path) -> str:
    """Build a static, deterministic, read-only dashboard page.

    Shows claim statuses (rigor-encoded), the artifact graph as Mermaid, and the
    research journal. Deterministic: no timestamps are embedded and all sections
    are sorted, so the same workspace always renders byte-identically.
    """
    from opentorus.research.journal import list_entries

    claims = sorted(list_claims(ot_dir), key=lambda c: c.id)
    edges = sorted(list_edges(ot_dir), key=lambda e: e.id)
    entries = sorted(list_entries(ot_dir), key=lambda e: e.id)

    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>OpenTorus dashboard (read-only)</title>",
        '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>',
        "<script>mermaid.initialize({startOnLoad:true});</script>",
        "</head><body>",
        "<h1>OpenTorus dashboard</h1>",
        "<p><em>Read-only view. Opening this page never mutates workspace state.</em></p>",
        "<h2>Claims</h2><table>",
        "<tr><th>ID</th><th>Status</th><th>Rigor</th><th>Statement</th></tr>",
    ]
    for claim in claims:
        parts.append(
            "<tr>"
            f"<td>{_html_escape(claim.id)}</td>"
            f"<td>{_html_escape(claim.status)}</td>"
            f"<td>{_html_escape(rigor_phrase(claim.status))}</td>"
            f"<td>{_html_escape(claim.statement)}</td>"
            "</tr>"
        )
    parts.append("</table>")

    parts.append("<h2>Artifact graph</h2>")
    parts.append(f'<pre class="mermaid">\n{_html_escape(to_mermaid(edges))}\n</pre>')

    parts.append("<h2>Research journal</h2><ol>")
    for entry in entries:
        claim_note = f" — {entry.claim_id} [{entry.claim_status}]" if entry.claim_id else ""
        parts.append(
            f"<li><strong>{_html_escape(entry.investigation)} "
            f"#{entry.iteration}</strong>{_html_escape(claim_note)}: "
            f"{_html_escape(entry.goal)} → {_html_escape(entry.next_step)}</li>"
        )
    parts.append("</ol>")
    parts.append("</body></html>")
    return "\n".join(parts)


def export_dashboard(ot_dir: Path, out_path: Path | None = None) -> Path:
    """Write the read-only dashboard to ``.opentorus/dashboard.html`` and return it."""
    out = out_path or ot_dir / "dashboard.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_dashboard_html(ot_dir), encoding="utf-8")
    return out
