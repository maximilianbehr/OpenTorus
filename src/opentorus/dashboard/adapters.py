"""Pure view-models for the dashboard: no ``textual``, no terminal, no writes.

Everything the terminal app shows is computed here from three read-only inputs —
the campaign snapshot (``store.open_campaign(...).load()``), the status summary
(``campaign.status.summarize_snapshot``) and the proof graph
(``proof_tree.builder.build_proof_graph``) — so the whole dashboard is testable
without a screen, and so the app can stay presentation only: it forwards key presses
to the state transitions defined at the bottom of this module and re-renders.

Three view-models:

* :class:`OverviewModel` — the header: campaign id / mode / phase / status, the
  budgets, branch and obligation counts, the current worker and last route, recent
  events, load diagnostics and graph issue counts. Its ``problem_*`` fields are the
  problem's status *derived from dossier artifacts* (``status_gate`` + ``scope`` via
  ``proof_tree.settlement.root_status``); ``problem_status_source`` says so in words
  and the app prints that label next to the value, because a campaign that
  ``completed`` next to a problem that is ``UNSOLVED`` is the normal case.
* :class:`TreeRowModel` — one visible line of the proof tree with its symbol
  (``render.symbol_for``), depth, status, root relation and expand state.
* :class:`NodeDetailModel` — the right pane: statement/objective, assumptions,
  quantifiers, root relation and what settling it could mean
  (``settlement.relation_settlement``), status, dependencies, parents, cited
  artifacts, verification refs, review findings, routing provenance and cost, the
  timestamps and every validation issue naming the node.

Read-only by construction: this module imports no store writer and no usage recorder
(a test greps the package for ``CampaignStore.append`` / ``write_snapshot`` /
``record_usage``); malformed or cyclic graphs arrive as issues on the graph and are
shown, never raised on. Node statuses are copies of their ledgers; nothing here can
upgrade a status.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.campaign.clock import Clock
from opentorus.campaign.models import CampaignSnapshot, Diagnostic, RootRelation
from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
    ValidationIssue,
)
from opentorus.campaign.proof_tree.render import (
    STATUS_NOTE,
    filter_graph,
    search_nodes,
    symbol_for,
    tree_rows,
)
from opentorus.campaign.proof_tree.settlement import relation_settlement
from opentorus.campaign.status import CampaignStatusSummary
from opentorus.errors import OpenTorusError

PROBLEM_STATUS_SOURCE = (
    "derived from dossier artifacts (status_gate + scope); never from campaign state, "
    "node statuses or closed obligations"
)
# Obligation statuses ``o`` (next open obligation) jumps to.
OPEN_OBLIGATION_STATUSES: frozenset[str] = frozenset({"open", "in_progress"})
# Status filter values offered first when present in the graph; the rest follow sorted.
PREFERRED_STATUS_ORDER: tuple[str, ...] = (
    "open",
    "in_progress",
    "closed",
    "verified",
    "formally_verified",
    "contradicted",
    "suspended",
    "active",
    "completed",
    "exhausted",
    "rejected",
    "unverified",
    "supported",
    "accepted",
    "sketch",
    "failed",
)
_LABEL_WIDTH = 72
# The header keeps the last few events; the full tail is in ``campaign status``.
RECENT_EVENTS_SHOWN = 3


# --------------------------------------------------------------------------------------
# Overview
# --------------------------------------------------------------------------------------


class BudgetAxisView(BaseModel):
    """One budget axis; ``limit <= 0`` means unlimited (the ledger's convention)."""

    name: str
    used: float
    limit: float
    unit: str = ""

    def text(self) -> str:
        lim = "unlimited" if self.limit <= 0 else f"{self.limit:g}{self.unit}"
        return f"{self.name} {self.used:g}{self.unit} / {lim}"


class RouteView(BaseModel):
    """A routing decision as the dashboard shows it (provenance, never a choice)."""

    decision_id: str
    task_class: str = ""
    selected_profile: str | None = None
    provider: str | None = None
    actual_model: str | None = None
    fallback_reason: str | None = None

    def text(self) -> str:
        parts = [self.decision_id]
        if self.task_class:
            parts.append(self.task_class)
        parts.append(f"-> {self.selected_profile or '?'}")
        if self.provider:
            parts.append(f"[{self.provider}]")
        if self.actual_model:
            parts.append(f"({self.actual_model})")
        if self.fallback_reason:
            parts.append(f"fallback: {self.fallback_reason}")
        return " ".join(parts)


class WorkerView(BaseModel):
    work_item_id: str
    branch_id: str
    role: str


class EventView(BaseModel):
    event_id: str
    type: str
    summary: str = ""


class OverviewModel(BaseModel):
    """The header of the dashboard: orchestration state next to the derived problem status.

    ``problem_status_label`` / ``problem_report_status`` / ``problem_status_rationale``
    come from the proof graph's ``root_status`` (``settlement.root_status``); they are
    **derived from dossier artifacts** and are labelled as such by
    ``problem_status_source`` so no reader mistakes them for a campaign outcome.
    """

    campaign_id: str
    problem_id: str
    mode: str
    phase: str
    status: str
    resume_phase: str | None = None
    pause_reason: str | None = None
    stop_reason: str | None = None
    failure_reason: str | None = None
    completion_reason: str | None = None
    problem_status_label: str = "STATUS_UNCERTAIN"
    problem_report_status: str = "UNSOLVED"
    problem_status_rationale: str = ""
    problem_status_source: str = PROBLEM_STATUS_SOURCE
    budgets: list[BudgetAxisView] = Field(default_factory=list)
    budget_exhausted: list[str] = Field(default_factory=list)
    branch_counts: dict[str, int] = Field(default_factory=dict)
    obligations_open: int = 0
    obligations_closed: int = 0
    current_worker: WorkerView | None = None
    last_route: RouteView | None = None
    recent_events: list[EventView] = Field(default_factory=list)
    diagnostics_count: int = 0
    graph_issue_counts: dict[str, int] = Field(default_factory=dict)
    graph_errors: int = 0
    graph_warnings: int = 0
    node_count: int = 0
    edge_count: int = 0
    rounds: int = 0
    steps_executed: int = 0
    artifact_count: int = 0
    updated_at: datetime | None = None


def _route_view(route: object | None) -> RouteView | None:
    """A ``RouteSummary`` / ``RoutingDecisionRecord`` (duck-typed) as a :class:`RouteView`."""
    if route is None:
        return None
    return RouteView(
        decision_id=str(getattr(route, "decision_id", "") or ""),
        task_class=str(getattr(route, "task_class", "") or ""),
        selected_profile=getattr(route, "selected_profile", None),
        provider=getattr(route, "provider", None),
        actual_model=getattr(route, "actual_model", None),
        fallback_reason=getattr(route, "fallback_reason", None),
    )


def overview_from(summary: CampaignStatusSummary, graph: ProofGraph) -> OverviewModel:
    """The overview from an already-built summary and graph (pure; used by the loader)."""
    from opentorus.campaign.proof_tree.validation import issue_counts

    b = summary.budget
    worker = summary.current_worker
    errors = sum(1 for i in graph.issues if i.severity == "error")
    return OverviewModel(
        campaign_id=summary.campaign_id,
        problem_id=summary.problem_id,
        mode=summary.mode.value,
        phase=summary.phase.value,
        status=summary.status.value,
        resume_phase=summary.resume_phase.value if summary.resume_phase else None,
        pause_reason=summary.pause_reason,
        stop_reason=summary.stop_reason,
        failure_reason=summary.failure_reason,
        completion_reason=summary.completion_reason,
        problem_status_label=graph.root_status.label,
        problem_report_status=graph.root_status.report_status,
        problem_status_rationale=graph.root_status.rationale,
        budgets=[
            BudgetAxisView(name="steps", used=b.steps_used, limit=b.steps_limit),
            BudgetAxisView(name="tokens", used=b.tokens_used, limit=b.token_limit),
            BudgetAxisView(name="cost", used=b.cost_used_usd, limit=b.cost_limit_usd, unit=" USD"),
            BudgetAxisView(name="wall", used=b.wall_seconds_used, limit=b.wall_limit, unit="s"),
        ],
        budget_exhausted=list(b.exhausted),
        branch_counts=dict(summary.branch_counts),
        obligations_open=summary.obligations_open,
        obligations_closed=summary.obligations_closed,
        current_worker=(
            WorkerView(
                work_item_id=worker.work_item_id,
                branch_id=worker.branch_id,
                role=worker.role.value,
            )
            if worker
            else None
        ),
        last_route=_route_view(summary.last_route),
        recent_events=[
            EventView(event_id=e.event_id, type=e.type, summary=e.summary)
            for e in summary.latest_events
        ],
        diagnostics_count=summary.diagnostics_count,
        graph_issue_counts=issue_counts(graph.issues),
        graph_errors=errors,
        graph_warnings=len(graph.issues) - errors,
        node_count=len(graph.nodes),
        edge_count=len(graph.edges),
        rounds=summary.rounds,
        steps_executed=summary.steps_executed,
        artifact_count=summary.artifact_count,
        updated_at=summary.updated_at,
    )


def build_overview(
    ot_dir: Path,
    campaign_id: str,
    *,
    snapshot: CampaignSnapshot | None = None,
    summary: CampaignStatusSummary | None = None,
    graph: ProofGraph | None = None,
) -> OverviewModel:
    """The overview of ``campaign_id``; whatever is not passed in is read from disk.

    Read-only: ``build_status_summary`` and ``build_proof_graph`` only read the campaign
    files, the dossier and the workspace ledgers. A missing campaign raises the
    store's :class:`OpenTorusError` (it names the campaigns that do exist).
    """
    if summary is None:
        from opentorus.campaign.status import build_status_summary

        summary = build_status_summary(ot_dir, campaign_id)
    if graph is None:
        from opentorus.campaign.proof_tree.builder import build_proof_graph
        from opentorus.campaign.store import open_campaign

        if snapshot is None:
            snapshot = open_campaign(ot_dir, campaign_id).load().snapshot
        graph = build_proof_graph(ot_dir, summary.problem_id, snapshot)
    return overview_from(summary, graph)


def overview_lines(overview: OverviewModel) -> list[str]:
    """Plain-text lines of the header (no markup; the app wraps them in a widget)."""
    o = overview
    lines = [
        f"Campaign {o.campaign_id} on {o.problem_id}  mode={o.mode}  "
        f"campaign status={o.status}  phase={o.phase}"
        + (f"  resume-phase={o.resume_phase}" if o.resume_phase else ""),
    ]
    for label, reason in (
        ("paused", o.pause_reason),
        ("stopped", o.stop_reason),
        ("failed", o.failure_reason),
        ("completed", o.completion_reason),
    ):
        if reason:
            lines.append(f"  {label}: {reason}")
    lines.append(
        f"Problem status (derived from dossier artifacts): {o.problem_report_status} / "
        f"{o.problem_status_label}"
        + (f" -- {o.problem_status_rationale}" if o.problem_status_rationale else "")
    )
    lines.append("  " + STATUS_NOTE)
    lines.append(
        "budget: "
        + ", ".join(axis.text() for axis in o.budgets)
        + (f"  exhausted: {', '.join(o.budget_exhausted)}" if o.budget_exhausted else "")
    )
    branches = ", ".join(f"{k}={v}" for k, v in sorted(o.branch_counts.items())) or "none"
    lines.append(
        f"branches: {branches}  obligations: open={o.obligations_open} "
        f"closed={o.obligations_closed}  rounds={o.rounds}  artifacts={o.artifact_count}  "
        f"nodes={o.node_count} edges={o.edge_count}"
    )
    if o.current_worker:
        w = o.current_worker
        lines.append(f"running: {w.work_item_id} ({w.role} on {w.branch_id})")
    if o.last_route:
        lines.append("last route: " + o.last_route.text())
    if o.diagnostics_count or o.graph_issue_counts:
        issues = ", ".join(f"{k}={v}" for k, v in o.graph_issue_counts.items()) or "none"
        lines.append(
            f"diagnostics: {o.diagnostics_count} (campaign log)  graph issues: {issues} "
            f"({o.graph_errors} error(s), {o.graph_warnings} warning(s))"
        )
    for event in o.recent_events[-RECENT_EVENTS_SHOWN:]:
        lines.append(f"recent: {event.event_id} {event.type} {event.summary}".rstrip())
    return lines


# --------------------------------------------------------------------------------------
# Tree rows
# --------------------------------------------------------------------------------------


class TreeRowModel(BaseModel):
    """One visible line of the tree; ``expanded`` is only meaningful when ``has_children``."""

    node_id: str
    kind: str
    depth: int
    symbol: str
    label: str
    status: str
    root_relation: str
    expanded: bool = True
    has_children: bool = False
    repeated: bool = False

    def text(self) -> str:
        indent = "  " * self.depth
        if self.repeated:
            return f"{indent}-> {self.node_id} (shown above)"
        marker = ("- " if self.expanded else "+ ") if self.has_children else "  "
        return (
            f"{indent}{marker}{self.symbol} {self.node_id} [{self.root_relation}] "
            f"{self.kind}: {self.label}  status={self.status}"
        )


def _short(text: str, width: int = _LABEL_WIDTH) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= width else flat[: width - 3] + "..."


def _parents_index(graph: ProofGraph) -> dict[str, list[str]]:
    index: dict[str, set[str]] = {}
    for edge in graph.edges:
        if edge.relation == "parent":
            index.setdefault(edge.source_id, set()).add(edge.target_id)
    for node in graph.nodes.values():
        for p in node.parents:
            index.setdefault(node.node_id, set()).add(p)
    return {k: sorted(v) for k, v in index.items()}


def _restrict(graph: ProofGraph, keep_ids: Iterable[str]) -> ProofGraph:
    """The subgraph of ``keep_ids`` plus the root and every ancestor (a search view)."""
    keep: set[str] = {graph.root_id} if graph.root_id in graph.nodes else set()
    wanted = [nid for nid in keep_ids if nid in graph.nodes]
    keep.update(wanted)
    parents = _parents_index(graph)
    stack = list(wanted)
    while stack:
        nid = stack.pop()
        for p in parents.get(nid, []):
            if p in graph.nodes and p not in keep:
                keep.add(p)
                stack.append(p)
    nodes = {nid: node for nid, node in graph.nodes.items() if nid in keep}
    edges = [e for e in graph.edges if e.source_id in keep and e.target_id in keep]
    return graph.model_copy(update={"nodes": nodes, "edges": edges})


def visible_graph(
    graph: ProofGraph,
    *,
    kinds: set[str] | None = None,
    statuses: set[str] | None = None,
    search: str | None = None,
) -> ProofGraph:
    """Kind/status filter (``render.filter_graph``, ancestors kept) then the search
    restriction (``render.search_nodes`` hits plus their ancestors)."""
    view = filter_graph(graph, kinds, statuses) if (kinds or statuses) else graph
    needle = (search or "").strip()
    if needle:
        hits = [n.node_id for n in search_nodes(view, needle)]
        view = _restrict(view, hits)
    return view


def build_rows(
    graph: ProofGraph,
    *,
    expanded: set[str],
    kinds: set[str] | None = None,
    statuses: set[str] | None = None,
    search: str | None = None,
) -> list[TreeRowModel]:
    """The visible rows: filtered, searched, then collapsed below every node not in
    ``expanded`` (``render.tree_rows`` supplies the cycle-safe depth-first order).

    A node with children that is *not* in ``expanded`` hides its whole subtree; the
    marker on its line says so. While a search is active every node counts as
    expanded — a hit hidden under a collapsed ancestor would defeat the search — and
    the caller's collapse state is left untouched for when the search is cleared.
    Repeated-node markers (diamonds and cycles) are kept as one-line rows so a cyclic
    graph still renders completely.
    """
    view = visible_graph(graph, kinds=kinds, statuses=statuses, search=search)
    if (search or "").strip():
        expanded = set(view.nodes)
    children: dict[str, set[str]] = {}
    for edge in view.edges:
        if edge.relation == "parent" and edge.target_id in view.nodes:
            children.setdefault(edge.target_id, set()).add(edge.source_id)
    rows: list[TreeRowModel] = []
    hide_below: int | None = None
    for row in tree_rows(view):
        if hide_below is not None and row.depth > hide_below:
            continue
        hide_below = None
        node = view.nodes[row.node_id]
        has_children = bool(children.get(row.node_id))
        is_expanded = row.node_id in expanded
        if row.repeated:
            rows.append(
                TreeRowModel(
                    node_id=row.node_id,
                    kind=node.kind.value,
                    depth=row.depth,
                    symbol=symbol_for(node),
                    label=_short(node.title or node.statement or ""),
                    status=node.status,
                    root_relation=node.root_relation.value,
                    expanded=is_expanded,
                    has_children=has_children,
                    repeated=True,
                )
            )
            continue
        rows.append(
            TreeRowModel(
                node_id=row.node_id,
                kind=node.kind.value,
                depth=row.depth,
                symbol=symbol_for(node),
                label=_short(node.title or node.statement or ""),
                status=node.status,
                root_relation=node.root_relation.value,
                expanded=is_expanded,
                has_children=has_children,
            )
        )
        if has_children and not is_expanded:
            hide_below = row.depth
    return rows


def next_open_obligation(rows: list[TreeRowModel], current: str | None) -> str | None:
    """The id of the first open/in-progress obligation *after* ``current`` in row order,
    wrapping around; ``None`` when the visible rows hold no open obligation.

    ``current`` may be an obligation itself (then the *next* one is returned, so
    repeated presses cycle) or any other node id / ``None`` (then the first open
    obligation after that position, or from the top).
    """
    ids = [r.node_id for r in rows if not r.repeated]
    candidates = [
        r.node_id
        for r in rows
        if not r.repeated
        and r.kind == ProofNodeKind.obligation.value
        and r.status.strip().lower() in OPEN_OBLIGATION_STATUSES
    ]
    if not candidates:
        return None
    start = ids.index(current) if current in ids else -1
    later = [nid for nid in candidates if ids.index(nid) > start]
    return later[0] if later else candidates[0]


# --------------------------------------------------------------------------------------
# Node detail
# --------------------------------------------------------------------------------------


class WorkItemView(BaseModel):
    work_item_id: str
    role: str = ""
    status: str = ""
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    routing_decision_id: str | None = None
    session_id: str = ""
    failure_reason: str | None = None


class CostView(BaseModel):
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    wall_seconds: float = 0.0
    work_items: int = 0

    def text(self) -> str:
        return (
            f"steps={self.steps} tokens={self.tokens} cost={self.cost_usd:g} USD "
            f"wall={self.wall_seconds:g}s work_items={self.work_items}"
        )


class EdgeView(BaseModel):
    relation: str
    other_id: str
    rationale: str = ""


class IssueView(BaseModel):
    code: str
    severity: str
    message: str


class NodeDetailModel(BaseModel):
    """Everything the detail pane shows for one node (a *view* of ledger data).

    ``settlement_*`` restate ``proof_tree.settlement.relation_settlement`` for the
    node's root relation: whether settling this node could ever settle the root and
    under what further condition — so a closed special-case obligation reads as
    "cannot settle the root" right next to its check mark. Routing provenance comes
    from the branch's work items (``extra["work_items"]``), an artifact's campaign
    provenance (``extra["campaign"]``) and, when the loader could read it, the
    workspace routing ledger; ``cost`` is the branch's ``actual_cost``.
    """

    node_id: str
    kind: str
    title: str = ""
    statement: str = ""
    objective: str = ""
    symbol: str = ""
    status: str = "unknown"
    source: str = "dossier"
    root_relation: str = RootRelation.unknown.value
    can_settle_root: bool = False
    settlement_condition: str | None = None
    settlement_note: str = ""
    assumptions: list[str] = Field(default_factory=list)
    quantifiers: list[str] = Field(default_factory=list)
    parents: list[str] = Field(default_factory=list)
    children: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    supporting_artifacts: list[str] = Field(default_factory=list)
    contradicting_artifacts: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    review_findings: list[str] = Field(default_factory=list)
    edges_out: list[EdgeView] = Field(default_factory=list)
    edges_in: list[EdgeView] = Field(default_factory=list)
    provenance: dict[str, str] = Field(default_factory=dict)
    work_items: list[WorkItemView] = Field(default_factory=list)
    routing: list[RouteView] = Field(default_factory=list)
    cost: CostView | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    issues: list[IssueView] = Field(default_factory=list)
    details: dict[str, str] = Field(default_factory=dict)


def _str_list(value: object) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if v is not None and str(v) != ""]
    return []


def _detail_pairs(node: ProofNode) -> dict[str, str]:
    """Kind-specific ``extra`` entries worth a line, as ``label -> text``."""
    x = node.extra
    keys: tuple[str, ...]
    if node.kind is ProofNodeKind.obligation:
        keys = (
            "closure_modes",
            "closed_by_artifact",
            "closed_by_mode",
            "closed_by_check",
            "gap_marker",
            "source_proof_id",
            "failed_approaches",
            "branch_id",
            "created_seq",
            "updated_seq",
        )
    elif node.kind is ProofNodeKind.branch:
        keys = (
            "kind",
            "priority",
            "estimated_cost",
            "assigned_worker_role",
            "approach_id",
            "target_claim_id",
            "strategy_key",
            "rejection_reason",
            "duplicate_of",
            "suspension_reason",
            "consecutive_failures",
            "failure_signatures",
            "artifact_references",
        )
    elif node.kind is ProofNodeKind.proof_attempt:
        keys = (
            "scope",
            "attempt_kind",
            "gap_count",
            "gaps",
            "claim_links",
            "verifier",
            "verification_artifact",
            "machine_checked",
        )
    elif node.kind is ProofNodeKind.verification:
        keys = (
            "artifact_id",
            "backend",
            "backend_version",
            "accepted",
            "inconclusive",
            "outcome",
            "claim_id",
            "problem_id",
            "submitted_under",
            "cached",
        )
    elif node.kind is ProofNodeKind.evidence:
        keys = ("evidence_type", "direction", "claim_id", "limitations", "path")
    elif node.kind in (ProofNodeKind.claim, ProofNodeKind.lemma, ProofNodeKind.counterexample):
        keys = ("claim_type", "primary", "confidence", "notes", "evidence_links")
    elif node.kind is ProofNodeKind.experiment:
        keys = ("command", "claim_links", "random_seed", "git_commit", "output_artifacts")
    elif node.kind is ProofNodeKind.theorem_reference:
        keys = (
            "paper_id",
            "paper_artifact",
            "theorem_label",
            "theorem_number",
            "categories",
            "extraction_method",
            "review_note",
            "applicability",
            "note",
        )
    elif node.kind is ProofNodeKind.failed_attempt:
        keys = (
            # dossier failed attempts
            "reason_failed",
            "artifacts",
            "reusable_obstruction",
            "tags",
            # campaign failure signatures
            "key",
            "occurrences",
            "tool_or_solver",
            "target_obligation",
            "retry_notes",
            "artifact_ids",
        )
    elif node.kind is ProofNodeKind.review:
        keys = (
            "target_id",
            "target_kind",
            "critic",
            "open_findings",
            "report_status",
            "assessments",
        )
    elif node.kind is ProofNodeKind.root:
        keys = ("problem_id", "primary_claim_id", "target_scope", "problem_status")
    else:
        keys = ()
    out: dict[str, str] = {}
    for key in keys:
        value = x.get(key)
        if value is None or value == "" or value == [] or value == {}:
            continue
        if isinstance(value, (list, tuple)):
            out[key] = ", ".join(str(v) for v in value)
        elif isinstance(value, dict):
            out[key] = ", ".join(f"{k}={v}" for k, v in value.items())
        else:
            out[key] = str(value)
    return out


def build_detail(
    graph: ProofGraph,
    node_id: str,
    snapshot: CampaignSnapshot | None,
    *,
    routing_records: Mapping[str, RouteView] | None = None,
) -> NodeDetailModel:
    """The detail view of ``node_id``; an unknown id yields a stub that says so.

    ``snapshot`` supplies work-item cost/routing for branches and the obligation's
    typed fields (quantifiers) when the builder's ``extra`` lacks them;
    ``routing_records`` (decision id -> view) resolves routing decision ids to the
    profile / provider / actual model the ledger recorded.
    """
    node = graph.nodes.get(node_id)
    if node is None:
        return NodeDetailModel(
            node_id=node_id,
            kind="missing",
            title=node_id,
            statement=f"{node_id} is not in the tree (a dangling reference).",
            status="missing",
        )
    verdict = relation_settlement(node.root_relation)
    x = node.extra
    quantifiers = _str_list(x.get("quantifiers"))
    if not quantifiers and snapshot is not None:
        ob = snapshot.obligations.get(node_id)
        if ob is not None:
            quantifiers = list(ob.quantifiers)
    provenance: dict[str, str] = {}
    prov = x.get("campaign")
    if isinstance(prov, dict):
        provenance = {str(k): str(v) for k, v in prov.items() if v is not None}
    for key in ("campaign_node_id", "work_item_id", "branch_id"):
        value = x.get(key)
        if value and key not in provenance:
            provenance[key] = str(value)
    work_items: list[WorkItemView] = []
    raw_items = x.get("work_items")
    if isinstance(raw_items, list):
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            work_items.append(
                WorkItemView(
                    work_item_id=str(item.get("work_item_id", "")),
                    role=str(item.get("role", "") or ""),
                    status=str(item.get("status", "") or ""),
                    steps=int(item.get("steps") or 0),
                    tokens=int(item.get("tokens") or 0),
                    cost_usd=float(item.get("cost_usd") or 0.0),
                    routing_decision_id=(
                        str(item["routing_decision_id"])
                        if item.get("routing_decision_id")
                        else None
                    ),
                    session_id=str(item.get("session_id", "") or ""),
                    failure_reason=(
                        str(item["failure_reason"]) if item.get("failure_reason") else None
                    ),
                )
            )
    elif snapshot is not None and node.kind is ProofNodeKind.branch:
        branch = snapshot.branches.get(node_id)
        if branch is not None:
            for wid in branch.work_item_ids:
                w = snapshot.work_items.get(wid)
                if w is None:
                    continue
                work_items.append(
                    WorkItemView(
                        work_item_id=w.work_item_id,
                        role=w.role.value,
                        status=w.status.value,
                        steps=w.usage.steps,
                        tokens=w.usage.tokens,
                        cost_usd=w.usage.cost_usd,
                        routing_decision_id=w.routing_decision_id,
                        session_id=w.session_id,
                        failure_reason=w.failure_reason,
                    )
                )
    decision_ids: list[str] = []
    for did in _str_list(x.get("routing_decision_ids")):
        if did not in decision_ids:
            decision_ids.append(did)
    for item in work_items:
        if item.routing_decision_id and item.routing_decision_id not in decision_ids:
            decision_ids.append(item.routing_decision_id)
    if provenance.get("work_item_id") and snapshot is not None:
        w = snapshot.work_items.get(provenance["work_item_id"])
        if w is not None and w.routing_decision_id and w.routing_decision_id not in decision_ids:
            decision_ids.append(w.routing_decision_id)
    routing = [
        (routing_records or {}).get(did) or RouteView(decision_id=did) for did in decision_ids
    ]
    cost: CostView | None = None
    raw_cost = x.get("actual_cost")
    if isinstance(raw_cost, dict):
        cost = CostView(
            steps=int(raw_cost.get("steps") or 0),
            tokens=int(raw_cost.get("tokens") or 0),
            cost_usd=float(raw_cost.get("cost_usd") or 0.0),
            wall_seconds=float(raw_cost.get("wall_seconds") or 0.0),
            work_items=int(raw_cost.get("work_items") or 0),
        )
    elif provenance.get("work_item_id") and snapshot is not None:
        w = snapshot.work_items.get(provenance["work_item_id"])
        if w is not None:
            cost = CostView(
                steps=w.usage.steps,
                tokens=w.usage.tokens,
                cost_usd=w.usage.cost_usd,
                wall_seconds=w.usage.wall_seconds,
                work_items=w.usage.work_items,
            )
    issues = [
        IssueView(code=i.code, severity=i.severity, message=i.message)
        for i in graph.issues
        if node_id in i.node_ids
    ]
    return NodeDetailModel(
        node_id=node.node_id,
        kind=node.kind.value,
        title=node.title,
        statement=node.statement,
        objective=node.statement if node.kind is ProofNodeKind.branch else "",
        symbol=symbol_for(node),
        status=node.status,
        source=node.source,
        root_relation=node.root_relation.value,
        can_settle_root=verdict.can_settle,
        settlement_condition=verdict.condition,
        settlement_note=verdict.reason,
        assumptions=list(node.assumption_context),
        quantifiers=quantifiers,
        parents=list(node.parents),
        children=graph.children_of(node_id),
        dependencies=list(node.dependencies),
        supporting_artifacts=list(node.supporting_artifacts),
        contradicting_artifacts=list(node.contradicting_artifacts),
        verification_refs=list(node.verification_refs),
        review_findings=list(node.review_findings),
        edges_out=[
            EdgeView(relation=e.relation, other_id=e.target_id, rationale=e.rationale)
            for e in graph.edges_from(node_id)
        ],
        edges_in=[
            EdgeView(relation=e.relation, other_id=e.source_id, rationale=e.rationale)
            for e in graph.edges_to(node_id)
        ],
        provenance=provenance,
        work_items=work_items,
        routing=routing,
        cost=cost,
        created_at=node.created_at,
        updated_at=node.updated_at,
        issues=issues,
        details=_detail_pairs(node),
    )


def _stamp(value: datetime | None) -> str:
    return value.isoformat() if value is not None else "-"


def detail_lines(detail: NodeDetailModel) -> list[str]:
    """Plain-text lines of the detail pane (no markup)."""
    d = detail
    lines = [f"{d.symbol} {d.node_id}  {d.kind}  status={d.status}  source={d.source}"]
    if d.title and d.title != d.node_id:
        lines.append(f"title: {d.title}")
    if d.kind == ProofNodeKind.branch.value and d.objective:
        lines.append(f"objective: {d.objective}")
    elif d.statement:
        lines.append(f"statement: {d.statement}")
    settle = "can settle the root" if d.can_settle_root else "cannot settle the root"
    lines.append(f"root relation: {d.root_relation} -- {settle}")
    if d.settlement_condition:
        lines.append(f"  condition: {d.settlement_condition}")
    if d.settlement_note:
        lines.append(f"  note: {d.settlement_note}")
    if d.assumptions:
        lines.append("assumptions: " + "; ".join(d.assumptions))
    if d.quantifiers:
        lines.append("quantifiers: " + "; ".join(d.quantifiers))
    lines.append(f"parents: {', '.join(d.parents) or '-'}")
    if d.children:
        lines.append(f"children: {', '.join(d.children)}")
    if d.dependencies:
        lines.append(f"depends on: {', '.join(d.dependencies)}")
    if d.supporting_artifacts:
        lines.append(f"supporting: {', '.join(d.supporting_artifacts)}")
    if d.contradicting_artifacts:
        lines.append(f"contradicting: {', '.join(d.contradicting_artifacts)}")
    if d.verification_refs:
        lines.append(f"verification refs: {', '.join(d.verification_refs)}")
    if d.review_findings:
        lines.append("review findings: " + "; ".join(d.review_findings))
    for key, value in d.details.items():
        lines.append(f"{key}: {value}")
    if d.edges_out:
        lines.append(
            "edges out: " + ", ".join(f"{e.relation} -> {e.other_id}" for e in d.edges_out)
        )
    if d.edges_in:
        lines.append("edges in: " + ", ".join(f"{e.other_id} {e.relation} ->" for e in d.edges_in))
    if d.provenance:
        lines.append(
            "campaign provenance: " + ", ".join(f"{k}={v}" for k, v in d.provenance.items())
        )
    if d.cost:
        lines.append("cost: " + d.cost.text())
    for w in d.work_items:
        lines.append(
            f"work item {w.work_item_id}: {w.role} {w.status} steps={w.steps} "
            f"tokens={w.tokens} cost={w.cost_usd:g}"
            + (f" route={w.routing_decision_id}" if w.routing_decision_id else "")
            + (f" failure={w.failure_reason}" if w.failure_reason else "")
        )
    for r in d.routing:
        lines.append("routing: " + r.text())
    lines.append(f"created: {_stamp(d.created_at)}  updated: {_stamp(d.updated_at)}")
    for issue in d.issues:
        lines.append(f"issue [{issue.severity}] {issue.code}: {issue.message}")
    return lines


# --------------------------------------------------------------------------------------
# Loading (read-only) and the view state the app drives
# --------------------------------------------------------------------------------------


@dataclass
class DashboardData:
    """Everything one load produced: the inputs plus the derived overview and rows."""

    campaign_id: str
    problem_id: str
    snapshot: CampaignSnapshot
    summary: CampaignStatusSummary
    graph: ProofGraph
    overview: OverviewModel
    routing_records: dict[str, RouteView] = field(default_factory=dict)
    load_diagnostics: list[Diagnostic] = field(default_factory=list)


def _routing_index(ot_dir: Path, snapshot: CampaignSnapshot) -> dict[str, RouteView]:
    """Routing decisions of this campaign from the workspace ledger (read-only, tolerant)."""
    wanted = set(snapshot.routing_decision_ids)
    for w in snapshot.work_items.values():
        if w.routing_decision_id:
            wanted.add(w.routing_decision_id)
    if not wanted:
        return {}
    try:
        from opentorus.providers.pool import read_routing_ledger

        records = read_routing_ledger(ot_dir)
    except (OSError, ValueError, OpenTorusError):
        return {}
    out: dict[str, RouteView] = {}
    for record in records:
        if record.decision_id in wanted or record.campaign_id == snapshot.campaign_id:
            view = _route_view(record)
            if view is not None:
                out[record.decision_id] = view
    return out


def load_dashboard_data(
    ot_dir: Path, campaign_id: str, *, clock: Clock | None = None
) -> DashboardData:
    """Read the campaign, summarize it and build its proof graph — nothing is written.

    Uses the same read paths as ``campaign status`` and ``campaign tree``
    (``open_campaign(...).load()``, ``summarize_snapshot``, ``build_proof_graph``).
    Malformed ledgers, cyclic or dangling references become issues on the graph and
    diagnostics on the summary; only a missing campaign raises (the store's error
    names the campaigns that exist).
    """
    from opentorus.campaign.proof_tree.builder import build_proof_graph
    from opentorus.campaign.status import summarize_snapshot
    from opentorus.campaign.store import open_campaign

    store = open_campaign(ot_dir, campaign_id, clock=clock)
    loaded = store.load()
    events, _read_diags = store.read_events()
    summary = summarize_snapshot(
        ot_dir, loaded.snapshot, events=events, load_diagnostics=loaded.diagnostics
    )
    graph = build_proof_graph(ot_dir, store.problem_id, loaded.snapshot, clock=clock)
    return DashboardData(
        campaign_id=loaded.snapshot.campaign_id,
        problem_id=store.problem_id,
        snapshot=loaded.snapshot,
        summary=summary,
        graph=graph,
        overview=overview_from(summary, graph),
        routing_records=_routing_index(ot_dir, loaded.snapshot),
        load_diagnostics=list(loaded.diagnostics),
    )


DataLoader = Callable[[], DashboardData]


def kind_cycle(graph: ProofGraph) -> list[str | None]:
    """``None`` (all) followed by the node kinds present in the graph, in enum order.

    Only kinds that occur are offered: cycling through a dozen empty views is noise,
    and the root is always shown anyway.
    """
    present = {n.kind for n in graph.nodes.values()}
    return [None, *[k.value for k in ProofNodeKind if k in present and k is not ProofNodeKind.root]]


def status_cycle(graph: ProofGraph) -> list[str | None]:
    """``None`` (all) followed by the statuses present (preferred order first, rest sorted)."""
    # The root's status is the derived report status (``UNSOLVED`` ...), not a node
    # status one filters by; the root is shown in every view anyway.
    present = {
        n.status.strip().lower()
        for n in graph.nodes.values()
        if n.status.strip() and n.kind is not ProofNodeKind.root
    }
    ordered = [s for s in PREFERRED_STATUS_ORDER if s in present]
    ordered += sorted(present - set(ordered))
    return [None, *ordered]


def _next_in_cycle(current: str | None, cycle: list[str | None]) -> str | None:
    if current not in cycle:
        return cycle[0] if cycle else None
    idx = cycle.index(current)
    return cycle[(idx + 1) % len(cycle)]


@dataclass
class ViewState:
    """The dashboard's UI state — the app owns one and only calls the transitions below.

    ``collapsed`` (rather than an expanded set) is stored so a reload that brings new
    nodes shows them expanded like everything else; :meth:`expanded_ids` derives the
    set :func:`build_rows` wants.
    """

    collapsed: set[str] = field(default_factory=set)
    kind_filter: str | None = None
    status_filter: str | None = None
    search: str | None = None
    cursor: int = 0
    live: bool = False

    def expanded_ids(self, graph: ProofGraph) -> set[str]:
        return set(graph.nodes) - self.collapsed

    def rows(self, graph: ProofGraph) -> list[TreeRowModel]:
        return build_rows(
            graph,
            expanded=self.expanded_ids(graph),
            kinds={self.kind_filter} if self.kind_filter else None,
            statuses={self.status_filter} if self.status_filter else None,
            search=self.search,
        )

    def clamp(self, rows: list[TreeRowModel]) -> None:
        self.cursor = 0 if not rows else max(0, min(self.cursor, len(rows) - 1))

    def current_id(self, rows: list[TreeRowModel]) -> str | None:
        return rows[self.cursor].node_id if rows and 0 <= self.cursor < len(rows) else None

    def move(self, delta: int, rows: list[TreeRowModel]) -> None:
        self.cursor += delta
        self.clamp(rows)

    def select(self, node_id: str, rows: list[TreeRowModel]) -> bool:
        for i, row in enumerate(rows):
            if row.node_id == node_id and not row.repeated:
                self.cursor = i
                return True
        return False

    def toggle(self, node_id: str) -> None:
        if node_id in self.collapsed:
            self.collapsed.discard(node_id)
        else:
            self.collapsed.add(node_id)

    def cycle_kind(self, graph: ProofGraph) -> str | None:
        self.kind_filter = _next_in_cycle(self.kind_filter, kind_cycle(graph))
        return self.kind_filter

    def cycle_status(self, graph: ProofGraph) -> str | None:
        self.status_filter = _next_in_cycle(self.status_filter, status_cycle(graph))
        return self.status_filter

    def set_search(self, text: str | None) -> None:
        cleaned = (text or "").strip()
        self.search = cleaned or None

    def filter_text(self) -> str:
        parts = [
            f"kind={self.kind_filter or 'all'}",
            f"status={self.status_filter or 'all'}",
        ]
        if self.search:
            parts.append(f"search={self.search!r}")
        parts.append("live=on" if self.live else "live=off")
        return "  ".join(parts)


def issue_lines(issues: list[ValidationIssue], *, limit: int = 12) -> list[str]:
    """The diagnostics panel: one line per graph issue (errors first), capped."""
    ordered = sorted(issues, key=lambda i: (i.severity != "error", i.code, i.message))
    lines = [
        f"[{i.severity}] {i.code}: {i.message}"
        + (f"  <{', '.join(i.node_ids)}>" if i.node_ids else "")
        for i in ordered[:limit]
    ]
    if len(ordered) > limit:
        lines.append(f"... {len(ordered) - limit} more issue(s); see `campaign tree`")
    return lines


__all__ = [
    "OPEN_OBLIGATION_STATUSES",
    "PREFERRED_STATUS_ORDER",
    "PROBLEM_STATUS_SOURCE",
    "RECENT_EVENTS_SHOWN",
    "ROOT_ID",
    "BudgetAxisView",
    "CostView",
    "DashboardData",
    "DataLoader",
    "EdgeView",
    "EventView",
    "IssueView",
    "NodeDetailModel",
    "OverviewModel",
    "RouteView",
    "TreeRowModel",
    "ViewState",
    "WorkItemView",
    "WorkerView",
    "build_detail",
    "build_overview",
    "build_rows",
    "detail_lines",
    "issue_lines",
    "kind_cycle",
    "load_dashboard_data",
    "next_open_obligation",
    "overview_from",
    "overview_lines",
    "status_cycle",
    "visible_graph",
]
