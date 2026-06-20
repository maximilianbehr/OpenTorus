"""A minimal artifact graph (no graph database).

Edges between artifacts (claims, experiments, papers, reports, patches, ...) are
stored as JSON lines in ``.opentorus/graph.jsonl``. Relations are validated
against a fixed vocabulary so the graph stays meaningful and queryable.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from opentorus.errors import OpenTorusError
from opentorus.jsonl import append_jsonl, next_id, read_jsonl

Relation = Literal[
    "supports",
    "contradicts",
    "tests",
    "cites",
    "depends_on",
    "generated_by",
    "modifies",
    "supersedes",
    "blocks",
    "resolves",
    "explains",
    "derived_from",
    "validates",
    "weakens",
]

VALID_RELATIONS: tuple[str, ...] = (
    "supports",
    "contradicts",
    "tests",
    "cites",
    "depends_on",
    "generated_by",
    "modifies",
    "supersedes",
    "blocks",
    "resolves",
    "explains",
    "derived_from",
    "validates",
    "weakens",
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GraphEdge(BaseModel):
    id: str
    source_id: str
    target_id: str
    relation: Relation
    rationale: str = ""
    created_at: datetime = Field(default_factory=_utcnow)


def graph_path(ot_dir: Path) -> Path:
    return ot_dir / "graph.jsonl"


def list_edges(ot_dir: Path) -> list[GraphEdge]:
    return read_jsonl(graph_path(ot_dir), GraphEdge)


def add_edge(
    ot_dir: Path,
    source_id: str,
    target_id: str,
    relation: str,
    rationale: str = "",
) -> GraphEdge:
    """Add a validated relation edge between two artifacts."""
    if relation not in VALID_RELATIONS:
        raise OpenTorusError(
            f"Invalid relation '{relation}'. Valid relations: {', '.join(VALID_RELATIONS)}"
        )
    existing = list_edges(ot_dir)
    edge = GraphEdge(
        id=next_id("EDGE", (e.id for e in existing)),
        source_id=source_id,
        target_id=target_id,
        relation=relation,  # type: ignore[arg-type]
        rationale=rationale,
    )
    append_jsonl(graph_path(ot_dir), edge)
    return edge


def related(ot_dir: Path, artifact_id: str) -> list[GraphEdge]:
    """Return all edges touching ``artifact_id`` (as source or target)."""
    return [edge for edge in list_edges(ot_dir) if artifact_id in (edge.source_id, edge.target_id)]


# Mermaid line styles per relation, grouped by meaning so diagrams read well:
# supportive (solid), opposing (thick), and structural (dotted) relations.
_MERMAID_LINK = {
    "supports": "-->",
    "validates": "-->",
    "tests": "-->",
    "explains": "-->",
    "resolves": "-->",
    "cites": "-.->",
    "depends_on": "-.->",
    "generated_by": "-.->",
    "derived_from": "-.->",
    "modifies": "-.->",
    "supersedes": "-.->",
    "blocks": "==>",
    "contradicts": "==>",
    "weakens": "==>",
}


def _node_id(artifact_id: str) -> str:
    """Sanitize an artifact id into a Mermaid-safe node identifier."""
    return "".join(ch if ch.isalnum() else "_" for ch in artifact_id)


def to_mermaid(edges: list[GraphEdge]) -> str:
    """Render edges as a Mermaid ``graph LR`` diagram, styled by relation."""
    lines = ["graph LR"]
    seen: set[str] = set()
    for edge in edges:
        for artifact in (edge.source_id, edge.target_id):
            node = _node_id(artifact)
            if node not in seen:
                seen.add(node)
                lines.append(f'    {node}["{artifact}"]')
    for edge in edges:
        link = _MERMAID_LINK.get(edge.relation, "-->")
        src = _node_id(edge.source_id)
        dst = _node_id(edge.target_id)
        lines.append(f"    {src} {link}|{edge.relation}| {dst}")
    return "\n".join(lines)


def to_ascii(edges: list[GraphEdge]) -> str:
    """Render edges as a simple, readable ASCII adjacency listing."""
    if not edges:
        return "(empty graph)"
    width = max(len(e.source_id) for e in edges)
    return "\n".join(
        f"{edge.source_id.rjust(width)} --{edge.relation}--> {edge.target_id}" for edge in edges
    )


def to_mermaid_html(edges: list[GraphEdge]) -> str:
    """Wrap a Mermaid diagram in a standalone, offline-friendly HTML page."""
    diagram = to_mermaid(edges)
    return (
        "<!doctype html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        "<title>OpenTorus artifact graph</title>\n"
        '<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>\n'
        "<script>mermaid.initialize({startOnLoad:true});</script>\n"
        "</head>\n<body>\n<h1>OpenTorus artifact graph</h1>\n"
        f'<pre class="mermaid">\n{diagram}\n</pre>\n'
        "</body>\n</html>\n"
    )


def export_graph(
    ot_dir: Path, fmt: str = "mermaid", open_file: bool = False, scope: str = "all"
) -> str:
    """Export the graph as ``mermaid`` or ``ascii``; optionally write an HTML file.

    Returns the rendered text. When ``open_file`` is set (mermaid only), a
    standalone HTML page is written under ``.opentorus/graph.html`` and its path
    is appended to the returned text. ``scope="literature"`` restricts the diagram
    to edges touching a ``PAPER-*`` artifact.
    """
    edges = list_edges(ot_dir)
    if scope == "literature":
        edges = [
            e for e in edges if e.source_id.startswith("PAPER") or e.target_id.startswith("PAPER")
        ]
    elif scope != "all":
        raise OpenTorusError(f"Unknown graph scope '{scope}'. Valid scopes: all, literature.")
    if fmt == "ascii":
        return to_ascii(edges)
    if fmt == "mermaid":
        rendered = to_mermaid(edges)
        if open_file:
            out = ot_dir / "graph.html"
            out.write_text(to_mermaid_html(edges), encoding="utf-8")
            rendered += f"\n\nWrote {out}"
        return rendered
    raise OpenTorusError(f"Unknown graph format '{fmt}'. Valid formats: mermaid, ascii.")
