"""Renderers and pure view helpers for the proof tree — no UI dependency.

Three exports (``render_plain``, ``render_json``, ``render_dot``) and the pure
helpers the ``campaign tree`` command and the (M7) dashboard share:
:func:`filter_graph`, :func:`search_nodes`, :func:`tree_rows`, :func:`symbol_for`.

Everything here is a projection of a :class:`ProofGraph`; nothing reads a ledger and
nothing decides a status. The plain view prints the derived problem status *once*,
at the top, labelled as derived from dossier artifacts, and every node line shows
its relation to the root, so a closed special-case obligation can never be read as
the root being settled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from opentorus.campaign.models import RootRelation
from opentorus.campaign.proof_tree.models import ProofGraph, ProofNode, ProofNodeKind

SYMBOL_OK = "✓"
SYMBOL_OPEN = "○"
SYMBOL_BAD = "✗"
SYMBOL_UNKNOWN = "?"
SYMBOL_SPECIAL = "⊂"
SYMBOL_FLAG = "⚑"

LEGEND = (
    f"Legend: {SYMBOL_OK} closed/verified/accepted  {SYMBOL_OPEN} open/in progress  "
    f"{SYMBOL_BAD} contradicted/refuted/rejected/failed  {SYMBOL_UNKNOWN} unknown  "
    f"{SYMBOL_SPECIAL} special-case/relaxation (cannot settle the root)  "
    f"{SYMBOL_FLAG} suspended/exhausted/blocked  [relation] = relation to the root"
)
STATUS_NOTE = (
    "Problem status is derived from dossier artifacts (status_gate + scope); "
    "no node status and no campaign state ever upgrades it."
)

_OK_STATUSES: frozenset[str] = frozenset(
    {"closed", "verified", "formally_verified", "accepted", "pass", "succeeded", "solved"}
)
_BAD_STATUSES: frozenset[str] = frozenset(
    {
        "contradicted",
        "refuted",
        "rejected",
        "failed",
        "block",
        "abandoned",
        "invalid",
        "contradicts",
    }
)
_FLAG_STATUSES: frozenset[str] = frozenset({"suspended", "exhausted", "blocked", "paused"})
_OPEN_STATUSES: frozenset[str] = frozenset(
    {
        "open",
        "in_progress",
        "unverified",
        "supported",
        "sketch",
        "proposed",
        "active",
        "completed",
        "running",
        "planned",
        "needs_review",
        "candidate",
        "revise",
        "inconclusive",
        "recorded",
        "legacy",
        "neutral",
        "supports",
        "created",
        "scheduled",
        "unsolved",
        "partially_solved",
        "heuristic_only",
        "experimental_only",
        "status_uncertain",
    }
)
_NON_SETTLING: frozenset[RootRelation] = frozenset(
    {RootRelation.special_case, RootRelation.relaxation}
)

# DOT shapes by kind: structural nodes are boxes/octagons, artifacts get distinct
# shapes so a reader can tell evidence from a verifier run at a glance.
DOT_SHAPES: dict[ProofNodeKind, str] = {
    ProofNodeKind.root: "doubleoctagon",
    ProofNodeKind.branch: "box",
    ProofNodeKind.obligation: "hexagon",
    ProofNodeKind.claim: "ellipse",
    ProofNodeKind.lemma: "ellipse",
    ProofNodeKind.counterexample: "octagon",
    ProofNodeKind.theorem_reference: "folder",
    ProofNodeKind.evidence: "note",
    ProofNodeKind.proof_attempt: "component",
    ProofNodeKind.verification: "diamond",
    ProofNodeKind.experiment: "cylinder",
    ProofNodeKind.failed_attempt: "box",
    ProofNodeKind.review: "parallelogram",
    ProofNodeKind.work_item: "plaintext",
}


def symbol_for(node: ProofNode) -> str:
    """The status symbol(s) of a node: status glyph, plus ``⊂`` for non-settling relations."""
    status = node.status.strip().lower()
    if node.kind is ProofNodeKind.failed_attempt:
        # A failed attempt / failure signature is a failure whatever its category says.
        glyph = SYMBOL_BAD
    elif status in _OK_STATUSES:
        glyph = SYMBOL_OK
    elif status in _BAD_STATUSES:
        glyph = SYMBOL_BAD
    elif status in _FLAG_STATUSES:
        glyph = SYMBOL_FLAG
    elif status in _OPEN_STATUSES:
        glyph = SYMBOL_OPEN
    else:
        glyph = SYMBOL_UNKNOWN
    if node.root_relation in _NON_SETTLING:
        glyph += SYMBOL_SPECIAL
    return glyph


# --------------------------------------------------------------------------------------
# Pure view helpers
# --------------------------------------------------------------------------------------


def _norm_set(values: set[str] | None) -> set[str] | None:
    if values is None:
        return None
    return {v.strip().lower() for v in values if v.strip()} or None


def _matches(node: ProofNode, kinds: set[str] | None, statuses: set[str] | None) -> bool:
    if kinds is not None and node.kind.value not in kinds:
        return False
    return statuses is None or node.status.strip().lower() in statuses


def _parents_index(graph: ProofGraph) -> dict[str, list[str]]:
    index: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.relation == "parent":
            index.setdefault(edge.source_id, set()).add(edge.target_id)
    for node in graph.nodes.values():
        for p in node.parents:
            index.setdefault(node.node_id, set()).add(p)
    return {k: sorted(v) for k, v in index.items()}


def filter_graph(
    graph: ProofGraph,
    kinds: set[str] | None = None,
    statuses: set[str] | None = None,
    *,
    keep_ancestors: bool = True,
) -> ProofGraph:
    """A copy of ``graph`` restricted to nodes matching ``kinds`` / ``statuses``.

    The root is always kept and, with ``keep_ancestors`` (default), so is every parent
    chain of a matching node, so the tree stays readable (``--kind obligation`` shows
    obligations *under their branches*). Edges are restricted to kept nodes; the
    issues are those of the full graph (they describe the data, not the view).
    """
    kind_set = _norm_set(kinds)
    status_set = _norm_set(statuses)
    if kind_set is None and status_set is None:
        return graph.model_copy(deep=True)
    keep: set[str] = {graph.root_id} if graph.root_id in graph.nodes else set()
    matched = [n.node_id for n in graph.nodes.values() if _matches(n, kind_set, status_set)]
    keep.update(matched)
    if keep_ancestors:
        parents = _parents_index(graph)
        stack = list(matched)
        while stack:
            nid = stack.pop()
            for p in parents.get(nid, []):
                if p in graph.nodes and p not in keep:
                    keep.add(p)
                    stack.append(p)
    nodes = {nid: node.model_copy(deep=True) for nid, node in graph.nodes.items() if nid in keep}
    edges = [e for e in graph.edges if e.source_id in keep and e.target_id in keep]
    return graph.model_copy(update={"nodes": nodes, "edges": edges}, deep=True)


def search_nodes(graph: ProofGraph, text: str) -> list[ProofNode]:
    """Nodes whose id, title, statement or bare artifact id contains ``text`` (case-insensitive)."""
    needle = text.strip().lower()
    if not needle:
        return []
    hits: list[ProofNode] = []
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        haystack = " ".join(
            [
                node.node_id,
                node.title,
                node.statement,
                str(node.extra.get("artifact_id", "")),
            ]
        ).lower()
        if needle in haystack:
            hits.append(node)
    return hits


@dataclass(frozen=True)
class TreeRow:
    """One line of the indented tree: the node, its depth, and whether it repeats."""

    node_id: str
    depth: int
    repeated: bool = False
    truncated_children: int = 0

    @property
    def is_marker(self) -> bool:
        return self.repeated or self.truncated_children > 0


def tree_rows(graph: ProofGraph, *, max_depth: int | None = None) -> list[TreeRow]:
    """Depth-first rows from the root, then any node not reachable via ``parent`` edges.

    Cycle- and diamond-safe: a node already shown is emitted once more as a
    ``repeated`` marker row instead of a second subtree; nothing recurses (an explicit
    stack), so a 10k-node chain renders. ``max_depth`` cuts subtrees with a marker row
    that says how many direct children were hidden.
    """
    children: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.relation == "parent" and edge.target_id in graph.nodes:
            children.setdefault(edge.target_id, []).append(edge.source_id)
    for nid in children:
        children[nid] = sorted(set(children[nid]))
    rows: list[TreeRow] = []
    seen: set[str] = set()

    def walk(start: str) -> None:
        stack: list[tuple[str, int]] = [(start, 0)]
        while stack:
            nid, depth = stack.pop()
            if nid not in graph.nodes:
                continue
            if nid in seen:
                rows.append(TreeRow(nid, depth, repeated=True))
                continue
            seen.add(nid)
            kids = children.get(nid, [])
            if max_depth is not None and depth >= max_depth and kids:
                rows.append(TreeRow(nid, depth, truncated_children=len(kids)))
                # The hidden subtree counts as shown: it must not resurface as
                # "unattached" below.
                hidden = list(kids)
                while hidden:
                    h = hidden.pop()
                    if h in seen:
                        continue
                    seen.add(h)
                    hidden.extend(children.get(h, []))
                continue
            rows.append(TreeRow(nid, depth))
            for kid in reversed(kids):
                stack.append((kid, depth + 1))

    if graph.root_id in graph.nodes:
        walk(graph.root_id)
    # Unattached: nodes with no in-graph parent first (their own subtrees), then leftovers.
    has_parent = {e.source_id for e in graph.edges if e.relation == "parent"}
    for nid in sorted(graph.nodes):
        if nid not in seen and nid not in has_parent:
            walk(nid)
    for nid in sorted(graph.nodes):
        if nid not in seen:
            walk(nid)
    return rows


# --------------------------------------------------------------------------------------
# Plain text
# --------------------------------------------------------------------------------------


def _detail(node: ProofNode) -> str:
    """The short kind-specific tail of a plain line (closure, gaps, backend, ...)."""
    x = node.extra
    if node.kind is ProofNodeKind.obligation:
        if node.status == "closed" and x.get("closed_by_artifact"):
            return f"closed by {x.get('closed_by_artifact')} ({x.get('closed_by_mode')})"
        modes = x.get("closure_modes")
        if isinstance(modes, list) and modes:
            return "closable by " + ", ".join(str(m) for m in modes)
        return ""
    if node.kind is ProofNodeKind.proof_attempt:
        return f"gaps={x.get('gap_count', 0)} scope={x.get('scope', '?')}"
    if node.kind is ProofNodeKind.verification:
        return f"backend={x.get('backend', '?')} artifact={x.get('artifact_id', '?')}"
    if node.kind is ProofNodeKind.evidence:
        return f"type={x.get('evidence_type', '?')}"
    if node.kind is ProofNodeKind.branch:
        cost = x.get("actual_cost")
        steps = cost.get("steps") if isinstance(cost, dict) else None
        parts = [f"kind={x.get('kind', '?')}"]
        if steps is not None:
            parts.append(f"steps={steps}")
        if x.get("rejection_reason"):
            parts.append(f"rejected={x.get('rejection_reason')}")
        if x.get("suspension_reason"):
            parts.append(f"suspended={x.get('suspension_reason')}")
        return " ".join(parts)
    if node.kind is ProofNodeKind.theorem_reference:
        return f"paper={x.get('paper_id') or x.get('paper_artifact') or '?'}"
    if node.kind is ProofNodeKind.review:
        n = len(node.review_findings)
        return f"findings={n}"
    if node.kind is ProofNodeKind.failed_attempt:
        occ = x.get("occurrences")
        return f"occurrences={occ}" if occ is not None else ""
    return ""


def _line(node: ProofNode, *, show_symbols: bool) -> str:
    title = (node.title or node.statement or "").replace("\n", " ").strip()
    if len(title) > 90:
        title = title[:87] + "..."
    head = f"{symbol_for(node)} " if show_symbols else ""
    detail = _detail(node)
    tail = f"  ({detail})" if detail else ""
    return (
        f"{head}{node.node_id} [{node.root_relation.value}] {node.kind.value}: "
        f"{title}  status={node.status}{tail}"
    )


def render_plain(
    graph: ProofGraph,
    *,
    kinds: set[str] | None = None,
    statuses: set[str] | None = None,
    show_symbols: bool = True,
    max_depth: int | None = None,
) -> str:
    """The indented tree with the derived problem status, a legend and the issues."""
    view = filter_graph(graph, kinds, statuses) if (kinds or statuses) else graph
    lines: list[str] = []
    head = f"Proof tree: {graph.problem_id}"
    if graph.campaign_id:
        head += f" (campaign {graph.campaign_id})"
    lines.append(head)
    rs = graph.root_status
    lines.append(
        f"Problem status (derived from dossier artifacts): {rs.report_status} / {rs.label}"
        + (f" — {rs.rationale}" if rs.rationale else "")
    )
    lines.append(STATUS_NOTE)
    if kinds or statuses:
        shown = []
        if kinds:
            shown.append("kinds=" + ",".join(sorted(kinds)))
        if statuses:
            shown.append("statuses=" + ",".join(sorted(statuses)))
        lines.append("Filter: " + " ".join(shown) + " (ancestors kept)")
    lines.append("")
    rows = tree_rows(view, max_depth=max_depth)
    unattached_started = False
    for row in rows:
        node = view.nodes[row.node_id]
        indent = "  " * row.depth
        if row.depth == 0 and row.node_id != view.root_id and not unattached_started:
            unattached_started = True
            lines.append("")
            lines.append("Unattached (no parent path to the root):")
        if row.repeated:
            lines.append(f"{indent}↳ {row.node_id} (shown above)")
            continue
        lines.append(indent + _line(node, show_symbols=show_symbols))
        if row.truncated_children:
            lines.append(
                f"{indent}  … {row.truncated_children} child node(s) hidden below depth {max_depth}"
            )
    if not rows:
        lines.append("(no nodes)")
    lines.append("")
    if show_symbols:
        lines.append(LEGEND)
    errors = sum(1 for i in graph.issues if i.severity == "error")
    warnings = len(graph.issues) - errors
    if graph.issues:
        lines.append(f"Issues ({errors} error(s), {warnings} warning(s)):")
        for issue in graph.issues:
            ids = ", ".join(issue.node_ids)
            lines.append(
                f"  [{issue.severity}] {issue.code}: {issue.message}"
                + (f"  <{ids}>" if ids else "")
            )
    else:
        lines.append("Issues: none")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------------------
# JSON and DOT
# --------------------------------------------------------------------------------------


def render_json(graph: ProofGraph) -> str:
    """The graph as JSON with sorted keys (round-trips via ``ProofGraph.model_validate``)."""
    return (
        json.dumps(graph.model_dump(mode="json"), indent=2, sort_keys=True, ensure_ascii=False)
        + "\n"
    )


def _dot_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "")


def _dot_label(node: ProofNode) -> str:
    title = (node.title or node.statement or "").replace("\n", " ").strip()
    if len(title) > 60:
        title = title[:57] + "..."
    parts = [node.node_id, f"{node.kind.value} [{node.root_relation.value}]"]
    if title and title != node.node_id:
        parts.append(title)
    parts.append(f"status: {node.status}")
    return _dot_escape("\n".join(parts))


_DOT_EDGE_STYLE: dict[str, str] = {
    "parent": 'style=dashed color="gray50"',
    "depends_on": 'color="gray30"',
    "supports": 'color="darkgreen"',
    "contradicts": 'color="red3"',
    "verifies": 'color="blue3" penwidth=2',
    "reviews": 'color="purple" style=dotted',
    "specializes": 'color="orange3"',
    "relaxes": 'color="orange3" style=dashed',
    "refutes": 'color="red3" penwidth=2',
    "closes": 'color="blue3" penwidth=2',
}


def render_dot(graph: ProofGraph) -> str:
    """A Graphviz digraph: shapes by kind, edge labels by relation, valid escaping."""
    lines = ["digraph proof_tree {", "  rankdir=TB;", '  node [fontname="Helvetica"];']
    caption = (
        f"{graph.problem_id}: problem status {graph.root_status.report_status} "
        "(derived from dossier artifacts)"
    )
    lines.append(f'  label="{_dot_escape(caption)}";')
    lines.append("  labelloc=t;")
    for nid in sorted(graph.nodes):
        node = graph.nodes[nid]
        shape = DOT_SHAPES.get(node.kind, "box")
        style = ' style="dashed"' if node.kind is ProofNodeKind.failed_attempt else ""
        peripheries = " peripheries=2" if node.root_relation in _NON_SETTLING else ""
        attrs = f'label="{_dot_label(node)}" shape={shape}{style}{peripheries}'
        lines.append(f'  "{_dot_escape(nid)}" [{attrs}];')
    for edge in graph.edges:
        style = _DOT_EDGE_STYLE.get(edge.relation, "")
        lines.append(
            f'  "{_dot_escape(edge.source_id)}" -> "{_dot_escape(edge.target_id)}" '
            f'[label="{_dot_escape(edge.relation)}"{" " + style if style else ""}];'
        )
    lines.append("}")
    return "\n".join(lines) + "\n"


__all__ = [
    "DOT_SHAPES",
    "LEGEND",
    "STATUS_NOTE",
    "SYMBOL_BAD",
    "SYMBOL_FLAG",
    "SYMBOL_OK",
    "SYMBOL_OPEN",
    "SYMBOL_SPECIAL",
    "SYMBOL_UNKNOWN",
    "TreeRow",
    "filter_graph",
    "render_dot",
    "render_json",
    "render_plain",
    "search_nodes",
    "symbol_for",
    "tree_rows",
]
