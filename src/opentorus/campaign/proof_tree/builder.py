"""Build the proof tree from a campaign snapshot and the dossier/workspace ledgers.

:func:`build_proof_graph` is a *read-only merge*. It creates:

* the ``ROOT`` node from the dossier statement (status = the derived report status);
* one ``branch`` node per snapshot branch (parent: its parent branch or ``ROOT``;
  ``specializes`` / ``relaxes`` edges for special-case / relaxation relations);
* one ``obligation`` node per snapshot obligation (parent: its branch; ``supports`` /
  ``contradicts`` edges from cited artifacts; a ``closes`` edge from
  ``closed_by_artifact`` — the *only* way an obligation shows as closed);
* dossier claims (``claim`` / ``lemma`` for ``LEMMA_ATTEMPT`` / ``counterexample`` for
  ``COUNTEREXAMPLE_*``), evidence (``supports`` / ``contradicts`` by direction), proof
  attempts (gap count reconciled with the body), the workspace verifier ledger
  (``verification`` nodes, ``verifies`` edges), merged experiments, failed attempts
  and campaign failure signatures, reviews and the latest referee report, theorem
  references (``THMREF-`` and legacy ``THM-``);
* campaign nodes from the snapshot, merged onto the artifact they point at (provenance
  in ``extra["campaign"]``) or created as free nodes.

Node ids reuse artifact ids. The one exception is documented and deliberate: the
dossier's proof attempts (``proof_attempts/index.jsonl``) and the workspace verifier
ledger (``proofs.jsonl``) share the ``PROOF-NNNN`` id space, so verifier-ledger nodes
are ``PROOF-NNNN@verifier`` (``extra["artifact_id"]`` keeps the bare id for search).

Edges are requested while nodes are created and resolved once every ledger has been
read (:class:`_PendingEdge`), so an artifact cited before its own record was read still
links up. A reference that resolves to nothing becomes a ``missing_ref`` issue when
the caller asked for one; otherwise the id simply stays in the node's artifact lists,
where validation reports it.

Malformed input never raises: an unreadable ledger, a corrupt line, a campaign node
of unknown kind, a reference to something that no longer exists — each becomes a
:class:`ValidationIssue` (``malformed_node`` / ``missing_ref``) on the graph, and the
rest of the tree is still built. ``snapshot=None`` builds the dossier-only tree.
Nothing here writes, and no status is decided here: every ``status`` is copied from
its ledger and the root status comes from ``settlement.root_status``.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from opentorus.campaign.clock import Clock
from opentorus.campaign.models import (
    ArtifactRef,
    CampaignNodeState,
    CampaignSnapshot,
    RootRelation,
)
from opentorus.campaign.proof_tree.models import (
    ROOT_ID,
    EdgeRelation,
    IssueCode,
    IssueSeverity,
    ProofEdge,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
    RootStatusView,
    ValidationIssue,
)
from opentorus.campaign.proof_tree.settlement import CERTIFICATE_MODES, root_status

T = TypeVar("T")

VERIFIER_SUFFIX = "@verifier"
_PROOF_ID = re.compile(r"^PROOF-\d+$")
_CLAIM_ID = re.compile(r"^CLAIM-\d+$")
_EXP_ID = re.compile(r"^EXP-\d+$")

# ``CampaignNodeState.kind`` / ``ArtifactRef.kind`` -> tree kind. Kinds absent here
# are recorded on their branch (``extra["other_artifacts"]``) rather than as nodes.
_CAMPAIGN_KIND_MAP: dict[str, ProofNodeKind] = {
    "root": ProofNodeKind.root,
    "branch": ProofNodeKind.branch,
    "obligation": ProofNodeKind.obligation,
    "claim": ProofNodeKind.claim,
    "lemma": ProofNodeKind.lemma,
    "theorem-reference": ProofNodeKind.theorem_reference,
    "theorem_reference": ProofNodeKind.theorem_reference,
    "theorem_ref": ProofNodeKind.theorem_reference,
    "evidence": ProofNodeKind.evidence,
    "proof-attempt": ProofNodeKind.proof_attempt,
    "proof_attempt": ProofNodeKind.proof_attempt,
    "counterexample": ProofNodeKind.counterexample,
    "experiment": ProofNodeKind.experiment,
    "failed-attempt": ProofNodeKind.failed_attempt,
    "failed_attempt": ProofNodeKind.failed_attempt,
    "review": ProofNodeKind.review,
    "verification": ProofNodeKind.verification,
    "proof": ProofNodeKind.verification,
    "work-item": ProofNodeKind.work_item,
    "work_item": ProofNodeKind.work_item,
}
# Evidence types whose ``PROOF-`` sources are verifier-ledger runs (``epistemics``).
_VERIFICATION_EVIDENCE: frozenset[str] = frozenset({"FORMAL_PROOF", "VALIDATED_NUMERICAL"})
_NON_NODE_KINDS: frozenset[str] = frozenset(
    {"approach", "coverage", "known_result", "related_paper", "definition", "assumption"}
)
# The engine records the normalized statement as an artifact of the problem itself.
_ROOT_KINDS: frozenset[str] = frozenset({"problem_statement", "statement", "problem"})


def verifier_node_id(proof_id: str) -> str:
    """The tree id of a workspace verifier-ledger entry (see module docstring)."""
    return f"{proof_id.strip().upper()}{VERIFIER_SUFFIX}"


def _up(text: str | None) -> str:
    return (text or "").strip().upper()


def _norm_ref(text: str | None) -> str:
    """Normalise a node reference: ids upper-cased, the verifier suffix kept as is."""
    raw = (text or "").strip()
    if raw.lower().endswith(VERIFIER_SUFFIX):
        return verifier_node_id(raw[: -len(VERIFIER_SUFFIX)])
    return raw.upper()


@dataclass(frozen=True)
class _PendingEdge:
    """An edge requested before both ends are guaranteed to exist."""

    source: str
    target: str
    relation: EdgeRelation
    rationale: str = ""
    # ``PROOF-`` ids are ambiguous; say which store each end means.
    source_verifier: bool = False
    target_verifier: bool = False
    # When set, an unresolved end is reported as ``missing_ref`` with this message.
    missing: str | None = None


class _Builder:
    """Mutable assembly state for one build; :meth:`graph` returns the result."""

    def __init__(self, ot_dir: Path, problem_id: str, snapshot: CampaignSnapshot | None) -> None:
        self.ot_dir = ot_dir
        self.pid = problem_id.strip().upper()
        self.snapshot = snapshot
        self.nodes: dict[str, ProofNode] = {}
        self.edges: list[ProofEdge] = []
        self.issues: list[ValidationIssue] = []
        self._edge_keys: set[tuple[str, str, str]] = set()
        # artifact id -> where the campaign says it came from
        self.attribution: dict[str, ArtifactRef] = {}
        self.pending: list[_PendingEdge] = []
        self.primary_claim_id: str | None = None
        self.root_status_view = RootStatusView()

    # -- primitives -------------------------------------------------------------------

    def issue(
        self,
        code: IssueCode,
        message: str,
        *,
        node_ids: list[str] | None = None,
        severity: IssueSeverity = "error",
    ) -> None:
        self.issues.append(
            ValidationIssue(code=code, node_ids=node_ids or [], message=message, severity=severity)
        )

    def _guard(self, label: str, fn: Callable[[], T], default: T) -> T:
        """Run a ledger reader; a failure becomes a ``malformed_node`` issue, not a crash."""
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - every ledger is untrusted input here
            self.issue("malformed_node", f"could not read {label}: {type(exc).__name__}: {exc}")
            return default

    def read_list(self, label: str, fn: Callable[[], list[T]]) -> list[T]:
        return self._guard(label, fn, [])

    def read_opt(self, label: str, fn: Callable[[], T | None]) -> T | None:
        return self._guard(label, fn, None)

    def read_str(self, label: str, fn: Callable[[], str]) -> str:
        return self._guard(label, fn, "")

    def scan_corrupt_lines(self, path: Path, model: type[BaseModel], label: str) -> None:
        """Report ledger lines the tolerant reader will skip, so a lost record is visible."""
        if not path.is_file():
            return
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            self.issue("malformed_node", f"could not read {label}: {exc}")
            return
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                model.model_validate_json(line)
            except ValidationError as exc:
                errors = exc.errors()
                where = "record"
                why = "invalid"
                if errors:
                    where = ".".join(str(part) for part in errors[0].get("loc", ())) or where
                    why = str(errors[0].get("msg", why))
                self.issue(
                    "malformed_node",
                    f"{label} line {lineno} is malformed ({where}: {why}); the record is skipped",
                )

    def add_node(self, node: ProofNode) -> ProofNode | None:
        if node.node_id in self.nodes:
            self.issue(
                "duplicate_id",
                f"two records claim the id {node.node_id} ({self.nodes[node.node_id].kind.value} "
                f"and {node.kind.value}); the second is skipped",
                node_ids=[node.node_id],
            )
            return None
        self.nodes[node.node_id] = node
        return node

    def want(
        self,
        source: str,
        target: str,
        relation: EdgeRelation,
        rationale: str = "",
        *,
        source_verifier: bool = False,
        target_verifier: bool = False,
        missing: str | None = None,
    ) -> None:
        """Request an edge; resolved in :meth:`link` once every ledger has been read."""
        self.pending.append(
            _PendingEdge(
                _norm_ref(source),
                _norm_ref(target),
                relation,
                rationale,
                source_verifier=source_verifier,
                target_verifier=target_verifier,
                missing=missing,
            )
        )

    def _add_edge(self, source: str, target: str, relation: EdgeRelation, rationale: str) -> None:
        key = (source, target, relation)
        if key in self._edge_keys:
            return
        self._edge_keys.add(key)
        self.edges.append(
            ProofEdge(source_id=source, target_id=target, relation=relation, rationale=rationale)
        )

    def has(self, node_id: str | None) -> bool:
        return bool(node_id) and node_id in self.nodes

    def resolve(self, artifact_id: str, *, prefer_verifier: bool = False) -> str | None:
        """The node id an artifact id denotes, or ``None`` when it is not in the tree.

        ``PROOF-`` ids are ambiguous (dossier attempt vs verifier ledger); the caller
        says which store it means with ``prefer_verifier``.
        """
        aid = _norm_ref(artifact_id)
        if not aid:
            return None
        if _PROOF_ID.match(aid):
            ledger = verifier_node_id(aid)
            order = (ledger, aid) if prefer_verifier else (aid, ledger)
            for candidate in order:
                if candidate in self.nodes:
                    return candidate
            return None
        return aid if aid in self.nodes else None

    def link(self) -> None:
        """Resolve every pending edge; report the ones the caller wanted reported."""
        for p in self.pending:
            src = self.resolve(p.source, prefer_verifier=p.source_verifier)
            dst = self.resolve(p.target, prefer_verifier=p.target_verifier)
            if src is not None and dst is not None:
                self._add_edge(src, dst, p.relation, p.rationale)
            elif p.missing:
                self.issue(
                    "missing_ref", p.missing, node_ids=[p.source, p.target], severity="warning"
                )

    def branch_of(self, artifact_id: str) -> str | None:
        ref = self.attribution.get(_up(artifact_id))
        if ref is not None and ref.branch_id and ref.branch_id in self.nodes:
            return ref.branch_id
        return None

    def provenance(self, artifact_id: str) -> dict[str, object]:
        ref = self.attribution.get(_up(artifact_id))
        if ref is None:
            return {}
        return {
            "branch_id": ref.branch_id,
            "work_item_id": ref.work_item_id,
            "role": ref.role.value if ref.role else None,
            "seq": ref.seq,
        }

    # -- steps ------------------------------------------------------------------------

    def build_root(self) -> None:
        from opentorus.research.dossier import scope, store

        dossier = self.read_opt("problem.yaml", lambda: store.get_dossier(self.ot_dir, self.pid))
        raw = self.read_str("statement.md", lambda: store.read_statement(self.ot_dir, self.pid))
        statement = store.statement_body_for_display(raw) if raw else ""
        assumptions = self.read_list(
            "assumptions.yaml", lambda: store.list_assumptions(self.ot_dir, self.pid)
        )
        definitions = self.read_list(
            "definitions.yaml", lambda: store.list_definitions(self.ot_dir, self.pid)
        )
        status = root_status(self.ot_dir, self.pid)
        if dossier is None:
            self.issue(
                "malformed_node",
                f"dossier {self.pid} is missing or unreadable; the root carries no statement",
                node_ids=[ROOT_ID],
            )
        else:
            self.primary_claim_id = dossier.primary_claim_id
        extra: dict[str, object] = {
            "problem_id": self.pid,
            "primary_claim_id": self.primary_claim_id,
            "target_scope": scope.classify_target(statement) if statement else "unclear",
            "root_label": status.label,
            "root_rationale": status.rationale,
            "definitions": [d.term for d in definitions],
            "formalization_status": dossier.formalization_status if dossier else None,
            "problem_status": dossier.status if dossier else None,
        }
        if self.snapshot is not None:
            extra["campaign"] = {
                "campaign_id": self.snapshot.campaign_id,
                "mode": self.snapshot.mode.value,
                "phase": self.snapshot.phase.value,
                "status": self.snapshot.status.value,
                "note": "campaign status is orchestration; it never sets the problem status",
            }
        self.add_node(
            ProofNode(
                node_id=ROOT_ID,
                kind=ProofNodeKind.root,
                title=(dossier.title if dossier and dossier.title else self.pid),
                statement=statement or (dossier.title if dossier else ""),
                root_relation=RootRelation.equivalent,
                assumption_context=[a.statement for a in assumptions],
                status=status.report_status,
                created_at=dossier.created_at if dossier else None,
                updated_at=dossier.updated_at if dossier else None,
                source="dossier",
                extra=extra,
            )
        )
        self.root_status_view = status

    def build_attribution(self) -> None:
        snap = self.snapshot
        if snap is None:
            return
        for ref in sorted(snap.artifact_refs, key=lambda r: (r.seq or 0, r.artifact_id)):
            key = _up(ref.artifact_id)
            if ref.kind == "proof":
                key = verifier_node_id(key)
            self.attribution.setdefault(key, ref)
        for node in snap.campaign_nodes.values():
            if node.artifact_id and node.branch_id:
                key = _up(node.artifact_id)
                if node.kind == "proof":
                    key = verifier_node_id(key)
                self.attribution.setdefault(
                    key,
                    ArtifactRef(
                        artifact_id=node.artifact_id,
                        kind=node.kind,
                        branch_id=node.branch_id,
                        work_item_id=node.work_item_id,
                        seq=node.created_seq,
                    ),
                )

    def build_branches(self) -> None:
        snap = self.snapshot
        if snap is None:
            return
        for bid in sorted(snap.branches):
            b = snap.branches[bid]
            parent = b.parent_branch_id or ROOT_ID
            items = [snap.work_items[w] for w in b.work_item_ids if w in snap.work_items]
            routing = sorted({w.routing_decision_id for w in items if w.routing_decision_id})
            extra: dict[str, object] = {
                "kind": b.kind.value,
                "priority": b.priority,
                "estimated_cost": b.estimated_cost,
                "actual_cost": b.actual_cost.model_dump(mode="json"),
                "assigned_worker_role": b.assigned_worker_role.value,
                "approach_id": b.approach_id,
                "rejection_reason": b.rejection_reason,
                "duplicate_of": b.duplicate_of,
                "distinctness_note": b.distinctness_note,
                "suspension_reason": b.suspension_reason,
                "reactivation_conditions": [
                    c.model_dump(mode="json") for c in b.reactivation_conditions
                ],
                "consecutive_failures": b.consecutive_failures,
                "target_claim_id": b.target_claim_id,
                "strategy_key": b.strategy_key,
                "artifact_references": list(b.artifact_references),
                "failure_signatures": list(b.failure_signatures),
                "routing_decision_ids": routing,
                "work_items": [
                    {
                        "work_item_id": w.work_item_id,
                        "role": w.role.value,
                        "status": w.status.value,
                        "steps": w.usage.steps,
                        "tokens": w.usage.tokens,
                        "cost_usd": w.usage.cost_usd,
                        "routing_decision_id": w.routing_decision_id,
                        "session_id": w.session_id,
                        "failure_reason": w.failure_reason,
                    }
                    for w in items
                ],
                "other_artifacts": [],
            }
            if (
                self.add_node(
                    ProofNode(
                        node_id=bid,
                        kind=ProofNodeKind.branch,
                        title=b.title,
                        statement=b.objective,
                        root_relation=b.root_relation,
                        assumption_context=list(b.assumption_context),
                        status=b.status.value,
                        parents=[parent],
                        dependencies=list(b.dependencies),
                        created_at=b.created_at,
                        updated_at=b.updated_at,
                        source="campaign",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            self.want(bid, parent, "parent")
            if b.root_relation is RootRelation.special_case:
                self.want(bid, parent, "specializes", "special-case branch")
            elif b.root_relation is RootRelation.relaxation:
                self.want(bid, parent, "relaxes", "relaxation branch")
            for dep in b.dependencies:
                self.want(bid, dep, "depends_on")

    def build_obligations(self) -> None:
        snap = self.snapshot
        if snap is None:
            return
        # A closure is a recorded event; the rules that admitted it may since have been
        # tightened (a live run closed thirteen gaps through a PROOF- id collision). Re-check
        # every closed obligation so the tree shows what the *current* rules would accept.
        from opentorus.campaign.proof_tree.settlement import audit_closures

        try:
            audits = {
                a.obligation_id: a
                for a in audit_closures(self.ot_dir, self.pid, snap.obligations.values())
            }
        except Exception as exc:  # noqa: BLE001 - the audit must never break the tree
            audits = {}
            self.issue("malformed_node", f"closure audit failed: {exc}", severity="warning")
        for oid in sorted(snap.obligations):
            ob = snap.obligations[oid]
            audit = audits.get(oid)
            if audit is not None and not audit.justified:
                self.issue(
                    "unsupported_transition",
                    f"{oid} is recorded as closed by {ob.closed_by_artifact or '?'} "
                    f"({ob.closed_by_mode.value if ob.closed_by_mode else '?'}), but the current "
                    f"settlement rules do not accept that closure: {audit.reason}",
                    node_ids=[oid],
                    severity="error",
                )
            parent = ob.branch_id if ob.branch_id and ob.branch_id in snap.branches else ROOT_ID
            if ob.branch_id and ob.branch_id not in snap.branches:
                self.issue(
                    "missing_ref",
                    f"{oid} names branch {ob.branch_id}, which the snapshot does not hold",
                    node_ids=[oid, ob.branch_id],
                    severity="warning",
                )
            extra: dict[str, object] = {
                "closure_modes": [m.value for m in ob.closure_modes],
                "closed_by_artifact": ob.closed_by_artifact,
                "closed_by_mode": ob.closed_by_mode.value if ob.closed_by_mode else None,
                "closed_by_check": ob.closed_by_check,
                "gap_marker": ob.gap_marker,
                "source_proof_id": ob.source_proof_id,
                "quantifiers": list(ob.quantifiers),
                "failed_approaches": list(ob.failed_approaches),
                "created_seq": ob.created_seq,
                "updated_seq": ob.updated_seq,
                "branch_id": ob.branch_id,
                "closure_audit": (
                    None if audit is None else ("justified" if audit.justified else "unjustified")
                ),
            }
            if (
                self.add_node(
                    ProofNode(
                        node_id=oid,
                        kind=ProofNodeKind.obligation,
                        title=ob.statement[:80],
                        statement=ob.statement,
                        root_relation=ob.root_relation,
                        assumption_context=list(ob.assumptions),
                        status=ob.status.value,
                        parents=[parent],
                        dependencies=list(ob.dependencies),
                        supporting_artifacts=list(ob.supporting_artifacts),
                        contradicting_artifacts=list(ob.contradicting_artifacts),
                        review_findings=list(ob.review_findings),
                        source="campaign",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            self.want(oid, parent, "parent")
            for dep in ob.dependencies:
                self.want(oid, dep, "depends_on")
            for aid in ob.supporting_artifacts:
                self.want(aid, oid, "supports", "cited by the obligation", source_verifier=True)
            for aid in ob.contradicting_artifacts:
                self.want(aid, oid, "contradicts", "cited by the obligation", source_verifier=True)
            if ob.source_proof_id:
                self.want(oid, ob.source_proof_id, "depends_on", "gap extracted from this proof")
            if ob.closed_by_artifact:
                certificate = ob.closed_by_mode in CERTIFICATE_MODES if ob.closed_by_mode else False
                closer = _up(ob.closed_by_artifact)
                if certificate and _PROOF_ID.match(closer):
                    closer = verifier_node_id(closer)  # a certificate is a ledger entry
                mode = ob.closed_by_mode.value if ob.closed_by_mode else "closure"
                self.want(
                    closer,
                    oid,
                    "closes",
                    mode + (f" via {ob.closed_by_check}" if ob.closed_by_check else ""),
                    missing=(
                        f"{oid} was closed by {ob.closed_by_artifact}, which is not in the tree"
                    ),
                )

    def build_claims(self) -> None:
        from opentorus.research.dossier import store
        from opentorus.research.dossier.models import ClaimRecord

        ddir = store.dossier_dir(self.ot_dir, self.pid)
        self.scan_corrupt_lines(ddir / "claims.jsonl", ClaimRecord, "claims.jsonl")
        claims = self.read_list("claims.jsonl", lambda: store.list_claims(self.ot_dir, self.pid))
        primary = _up(self.primary_claim_id)
        for c in claims:
            cid = _up(c.id)
            if c.type == "LEMMA_ATTEMPT":
                kind = ProofNodeKind.lemma
            elif c.type.startswith("COUNTEREXAMPLE_"):
                kind = ProofNodeKind.counterexample
            else:
                kind = ProofNodeKind.claim
            is_primary = bool(primary) and cid == primary
            deps = [_up(d) for d in c.depends_on]
            if is_primary:
                relation = RootRelation.equivalent
            elif kind is ProofNodeKind.counterexample and primary and primary in deps:
                relation = RootRelation.counterexample_route
            else:
                relation = RootRelation.unknown
            branch = self.branch_of(cid)
            parents = [ROOT_ID] if is_primary else ([branch] if branch else [])
            extra: dict[str, object] = {
                "claim_type": c.type,
                "primary": is_primary,
                "confidence": c.confidence,
                "notes": c.notes,
                "source_artifacts": list(c.source_artifacts),
                "evidence_links": list(c.evidence_links),
            }
            prov = self.provenance(cid)
            if prov:
                extra["campaign"] = prov
            if (
                self.add_node(
                    ProofNode(
                        node_id=cid,
                        kind=kind,
                        title=f"{c.type} {cid}",
                        statement=c.statement,
                        root_relation=relation,
                        status=c.status,
                        parents=parents,
                        dependencies=deps,
                        supporting_artifacts=list(c.source_artifacts),
                        verification_refs=[
                            _up(a) for a in c.source_artifacts if _PROOF_ID.match(_up(a))
                        ],
                        created_at=c.created_at,
                        updated_at=c.updated_at,
                        source="dossier",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            for p in parents:
                self.want(cid, p, "parent")
            for dep in deps:
                self.want(cid, dep, "depends_on")
                if c.type == "COUNTEREXAMPLE_VERIFIED":
                    self.want(cid, dep, "refutes", "verified counterexample")
                    if dep == primary:
                        self.want(cid, ROOT_ID, "refutes", "refutes the primary claim")

    def build_evidence(self) -> None:
        from opentorus.research.dossier import store
        from opentorus.research.dossier.models import EvidenceRecord

        ddir = store.dossier_dir(self.ot_dir, self.pid)
        self.scan_corrupt_lines(
            ddir / "evidence" / "index.jsonl", EvidenceRecord, "evidence/index.jsonl"
        )
        records = self.read_list(
            "evidence/index.jsonl", lambda: store.list_evidence(self.ot_dir, self.pid)
        )
        for e in records:
            eid = _up(e.id)
            claim = _up(e.claim_id)
            branch = self.branch_of(eid)
            extra: dict[str, object] = {
                "evidence_type": e.type,
                "direction": e.direction,
                "claim_id": claim,
                "path": e.path,
                "limitations": list(e.limitations),
                "source_artifacts": list(e.source_artifacts),
            }
            prov = self.provenance(eid)
            if prov:
                extra["campaign"] = prov
            # Claims are built before evidence, so "does the claim exist" is known here.
            parents = [claim] if claim else ([branch] if branch else [])
            if (
                self.add_node(
                    ProofNode(
                        node_id=eid,
                        kind=ProofNodeKind.evidence,
                        title=f"{e.type} evidence",
                        statement=e.summary,
                        status=e.direction,
                        parents=parents,
                        supporting_artifacts=list(e.source_artifacts),
                        verification_refs=[
                            _up(a) for a in e.source_artifacts if _PROOF_ID.match(_up(a))
                        ],
                        created_at=e.created_at,
                        source="dossier",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            if self.has(claim):
                self.want(eid, claim, "parent")
                if e.direction == "supports":
                    self.want(eid, claim, "supports")
                elif e.direction == "contradicts":
                    self.want(eid, claim, "contradicts")
            elif branch:
                self.want(eid, branch, "parent")
            for aid in e.source_artifacts:
                key = _up(aid)
                if _EXP_ID.match(key):
                    self.want(eid, key, "depends_on", "evidence from this experiment")
                elif _PROOF_ID.match(key) and e.type in _VERIFICATION_EVIDENCE:
                    # Verification-grade evidence cites a verifier run (the ledger id),
                    # never a dossier sketch: resolve the ledger node only.
                    self.want(
                        verifier_node_id(key),
                        eid,
                        "verifies",
                        "verifier run cited by the evidence",
                        missing=f"{eid} cites verifier run {key}, which is not in the tree",
                    )
                elif _PROOF_ID.match(key):
                    self.want(eid, key, "depends_on", "evidence drawn from this proof attempt")

    def build_workspace_evidence(self) -> None:
        """Workspace-ledger evidence (``EVIDENCE-*`` in ``evidence.jsonl``).

        The falsifier and numerical workers record their bounded searches through the
        workspace stack (``record_search_evidence``), exactly like the research loop
        does, so their evidence never reaches the dossier's ``evidence/index.jsonl``.
        A tree that read only the dossier ledger reported those campaign artifacts as
        ``missing_ref`` — the first real routed run had two. Anything attributed to
        this problem, or referenced by the campaign, is a node here.
        """
        from opentorus.research.evidence import list_evidence

        entries = self.read_list("evidence.jsonl", lambda: list_evidence(self.ot_dir))
        for e in entries:
            eid = _up(e.id)
            if eid in self.nodes:
                continue
            attributed = e.problem_id == self.pid or eid in self.attribution
            if not attributed:
                continue
            claim = _up(e.claim_id)
            branch = self.branch_of(eid)
            extra: dict[str, object] = {
                "evidence_type": e.source_type,
                "direction": e.direction,
                "strength": e.strength,
                "claim_id": claim,
                "source_id": e.source_id,
                "limitations": list(e.limitations),
                "ledger": "workspace",
            }
            prov = self.provenance(eid)
            if prov:
                extra["campaign"] = prov
            parents = [claim] if self.has(claim) else ([branch] if branch else [])
            supporting = [_up(e.source_id)] if e.source_id else []
            if (
                self.add_node(
                    ProofNode(
                        node_id=eid,
                        kind=ProofNodeKind.evidence,
                        title=f"{e.source_type} evidence ({e.strength})",
                        statement=e.summary,
                        status=e.direction,
                        parents=parents,
                        supporting_artifacts=supporting,
                        created_at=e.created_at,
                        source="workspace",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            if self.has(claim):
                self.want(eid, claim, "parent")
                if e.direction == "supports":
                    self.want(eid, claim, "supports")
                elif e.direction == "contradicts":
                    self.want(eid, claim, "contradicts")
            elif branch:
                self.want(eid, branch, "parent")
            if e.source_id and _EXP_ID.match(_up(e.source_id)):
                self.want(eid, _up(e.source_id), "depends_on", "evidence from this experiment")

    def build_proof_attempts(self) -> None:
        from opentorus.research.dossier import store
        from opentorus.research.dossier.models import ProofAttempt
        from opentorus.research.dossier.nl_proof import explicit_gaps

        ddir = store.dossier_dir(self.ot_dir, self.pid)
        self.scan_corrupt_lines(
            ddir / "proof_attempts" / "index.jsonl", ProofAttempt, "proof_attempts/index.jsonl"
        )
        attempts = self.read_list(
            "proof_attempts/index.jsonl", lambda: store.list_proof_attempts(self.ot_dir, self.pid)
        )
        for p in attempts:
            pid = _up(p.id)
            body = ""
            if p.body_path and (ddir / p.body_path).is_file():
                try:
                    body = (ddir / p.body_path).read_text(encoding="utf-8")
                except OSError as exc:
                    self.issue("malformed_node", f"could not read {p.id} body: {exc}")
            gaps = explicit_gaps(gaps=list(p.gaps), body=body)
            links = [_up(c) for c in p.claim_links]
            branch = self.branch_of(pid)
            first_claim = next((c for c in links if _CLAIM_ID.match(c) and self.has(c)), None)
            if first_claim:
                parents = [first_claim]
            elif branch:
                parents = [branch]
            elif p.scope == "primary":
                parents = [ROOT_ID]
            else:
                parents = []
            extra: dict[str, object] = {
                "scope": p.scope,
                "attempt_kind": p.kind,
                "gaps": gaps,
                "gap_count": len(gaps),
                "recorded_gaps": list(p.gaps),
                "claim_links": links,
                "verifier": p.verifier,
                "verification_artifact": p.verification_artifact,
                "body_path": p.body_path,
                "evidence_snapshot": p.evidence_snapshot,
                "machine_checked": p.status == "verified",
            }
            prov = self.provenance(pid)
            if prov:
                extra["campaign"] = prov
            relation = RootRelation.equivalent if p.scope == "primary" else RootRelation.unknown
            if (
                self.add_node(
                    ProofNode(
                        node_id=pid,
                        kind=ProofNodeKind.proof_attempt,
                        title=p.title or f"proof attempt {pid}",
                        statement=p.title,
                        root_relation=relation,
                        status=p.status,
                        parents=parents,
                        supporting_artifacts=links,
                        verification_refs=(
                            [_up(p.verification_artifact)] if p.verification_artifact else []
                        ),
                        created_at=p.created_at,
                        updated_at=p.updated_at,
                        source="dossier",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            for par in parents:
                self.want(pid, par, "parent")
            for c in links:
                self.want(pid, c, "verifies" if p.status == "verified" else "supports")
            if p.verification_artifact:
                self.want(
                    verifier_node_id(p.verification_artifact),
                    pid,
                    "verifies",
                    "verification artifact of the attempt",
                    missing=(
                        f"{pid} cites verification artifact {p.verification_artifact}, "
                        "which is not in the tree"
                    ),
                )

    def build_verifier_ledger(self) -> None:
        from opentorus.research.verifiers.proofs import list_proofs

        entries = self.read_list("proofs.jsonl", lambda: list_proofs(self.ot_dir))
        for p in entries:
            if p.problem_id is not None and _up(p.problem_id) != self.pid:
                continue
            nid = verifier_node_id(p.id)
            if p.inconclusive:
                status = "inconclusive"
            elif p.accepted:
                status = "accepted"
            else:
                status = "rejected"
            output = (p.output or "").strip()
            extra: dict[str, object] = {
                "artifact_id": _up(p.id),
                "backend": p.backend,
                "backend_version": p.backend_version,
                "accepted": p.accepted,
                "inconclusive": p.inconclusive,
                "available": p.available,
                "outcome": p.outcome,
                "claim_id": p.claim_id,
                "problem_id": p.problem_id,
                "submitted_under": p.submitted_under,
                "source_path": p.source_path,
                "cached": p.cached,
                "output": output[:400],
            }
            prov = self.provenance(nid)
            if prov:
                extra["campaign"] = prov
            branch = self.branch_of(nid)
            claim = _up(p.claim_id) if p.claim_id else ""
            # An unscoped ledger entry's claim_id may name a *workspace* claim; only a
            # problem-scoped one is known to mean this dossier's claim.
            scoped = bool(claim) and p.problem_id is not None and self.has(claim)
            parents = [claim] if scoped else ([branch] if branch else [])
            if (
                self.add_node(
                    ProofNode(
                        node_id=nid,
                        kind=ProofNodeKind.verification,
                        title=f"{p.backend} {p.outcome or status}",
                        statement=output.splitlines()[0][:200] if output else "",
                        status=status,
                        parents=parents,
                        created_at=p.created_at,
                        source="workspace",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            for par in parents:
                self.want(nid, par, "parent")
            if scoped and status == "accepted":
                self.want(nid, claim, "verifies", "accepted verifier run for this claim")

    def build_experiments(self) -> None:
        from opentorus.research.dossier.experiments import list_problem_experiments

        records = self.read_list(
            "experiments", lambda: list_problem_experiments(self.ot_dir, self.pid)
        )
        for x in records:
            xid = _up(x.experiment_id)
            links = [_up(c) for c in x.claim_links]
            branch = self.branch_of(xid)
            first_claim = next((c for c in links if _CLAIM_ID.match(c) and self.has(c)), None)
            parents = [first_claim] if first_claim else ([branch] if branch else [])
            extra: dict[str, object] = {
                "command": x.command,
                "claim_links": links,
                "random_seed": x.random_seed,
                "git_commit": x.git_commit,
                "input_artifacts": list(x.input_artifacts),
                "output_artifacts": list(x.output_artifacts),
                "python_version": x.python_version,
            }
            prov = self.provenance(xid)
            if prov:
                extra["campaign"] = prov
            if (
                self.add_node(
                    ProofNode(
                        node_id=xid,
                        kind=ProofNodeKind.experiment,
                        title=x.title or xid,
                        statement=x.result_summary,
                        status=x.status,
                        parents=parents,
                        supporting_artifacts=links,
                        created_at=x.created_at,
                        source="dossier",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            for par in parents:
                self.want(xid, par, "parent")

    def build_failed_attempts(self) -> None:
        from opentorus.research.dossier import store
        from opentorus.research.dossier.models import FailedAttempt

        ddir = store.dossier_dir(self.ot_dir, self.pid)
        self.scan_corrupt_lines(
            ddir / "failed_attempts.jsonl", FailedAttempt, "failed_attempts.jsonl"
        )
        failed = self.read_list(
            "failed_attempts.jsonl", lambda: store.list_failed_attempts(self.ot_dir, self.pid)
        )
        for f in failed:
            fid = _up(f.id)
            parent = self.branch_of(fid) or ROOT_ID
            extra: dict[str, object] = {
                "reason_failed": f.reason_failed,
                "artifacts": list(f.artifacts),
                "reusable_obstruction": f.reusable_obstruction,
                "tags": list(f.tags),
            }
            prov = self.provenance(fid)
            if prov:
                extra["campaign"] = prov
            summary = f.summary + (f" — {f.reason_failed}" if f.reason_failed else "")
            if (
                self.add_node(
                    ProofNode(
                        node_id=fid,
                        kind=ProofNodeKind.failed_attempt,
                        title=f.attempted_method,
                        statement=summary.strip(),
                        status="failed",
                        parents=[parent],
                        created_at=f.created_at,
                        source="dossier",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            self.want(fid, parent, "parent")
        snap = self.snapshot
        if snap is None:
            return
        for sid in sorted(snap.failure_signatures):
            sig = snap.failure_signatures[sid]
            if sig.target_obligation and sig.target_obligation in self.nodes:
                parent = sig.target_obligation
            elif sig.branch_id and sig.branch_id in self.nodes:
                parent = sig.branch_id
            else:
                parent = ROOT_ID
            if (
                self.add_node(
                    ProofNode(
                        node_id=sid,
                        kind=ProofNodeKind.failed_attempt,
                        title=f"{sig.strategy_class}: {sig.error_category}",
                        statement=sig.counterargument,
                        assumption_context=list(sig.assumption_context),
                        status=sig.error_category,
                        parents=[parent],
                        source="campaign",
                        extra={
                            "key": sig.key,
                            "artifact_ids": list(sig.artifact_ids),
                            "tool_or_solver": sig.tool_or_solver,
                            "occurrences": sig.occurrences,
                            "retry_notes": list(sig.retry_notes),
                            "branch_id": sig.branch_id,
                            "work_item_id": sig.work_item_id,
                            "first_seq": sig.first_seq,
                            "last_seq": sig.last_seq,
                            "target_obligation": sig.target_obligation,
                        },
                    )
                )
                is None
            ):
                continue
            self.want(sid, parent, "parent")

    def build_reviews(self) -> None:
        from opentorus.agent.review import list_reviews
        from opentorus.research.dossier.referee import latest_referee

        reviews = self.read_list("reviews/index.jsonl", lambda: list_reviews(self.ot_dir))
        for r in reviews:
            target = _up(r.target_id)
            if target not in self.nodes:
                continue  # a review of an artifact outside this problem's tree
            rid = _up(r.id)
            findings = [
                f"{f.finding_id} {f.category}/{f.severity}: {f.rationale}"
                + (f" [{f.resolution}]" if f.resolution != "open" else "")
                for f in r.findings
            ]
            if (
                self.add_node(
                    ProofNode(
                        node_id=rid,
                        kind=ProofNodeKind.review,
                        title=f"review of {target}",
                        statement=f"{r.critic} critic: {r.verdict}",
                        status=r.verdict,
                        parents=[target],
                        review_findings=findings,
                        created_at=r.created_at,
                        source="workspace",
                        extra={
                            "target_id": target,
                            "target_kind": r.target_kind,
                            "critic": r.critic,
                            "open_findings": sum(1 for f in r.findings if f.resolution == "open"),
                        },
                    )
                )
                is None
            ):
                continue
            self.want(rid, target, "parent")
            self.want(rid, target, "reviews")
        report = self.read_opt("referee/index.jsonl", lambda: latest_referee(self.ot_dir, self.pid))
        if report is None:
            return
        rid = _up(report.id)
        findings = list(report.contradictions)
        findings += [f"{o.location}: '{o.phrase}' ({o.kind})" for o in report.overclaims]
        findings += [f"downgrade recommended: {d}" for d in report.downgrades_recommended]
        if (
            self.add_node(
                ProofNode(
                    node_id=rid,
                    kind=ProofNodeKind.review,
                    title="referee report",
                    statement=report.summary,
                    status=report.verdict,
                    parents=[ROOT_ID],
                    review_findings=findings,
                    source="dossier",
                    extra={
                        "report_status": report.report_status,
                        "assessments": {a.claim_id: a.classification for a in report.assessments},
                        "created_at": report.created_at,
                    },
                )
            )
            is None
        ):
            return
        self.want(rid, ROOT_ID, "parent")
        self.want(rid, ROOT_ID, "reviews", "hostile referee over the dossier")

    def build_theorem_references(self) -> None:
        from opentorus.research.dossier import store
        from opentorus.research.theorems import store as thm_store

        refs = self.read_list(
            "theorems/references.jsonl",
            lambda: thm_store.list_references(self.ot_dir, problem_id=self.pid),
        )
        checks = self.read_list(
            "theorems/applicability_checks.jsonl",
            lambda: thm_store.list_applicability_checks(self.ot_dir),
        )
        for ref in refs:
            rid = _up(ref.id)
            branch = self.branch_of(rid)
            mine = [
                c
                for c in checks
                if _up(c.theorem_reference_id) == rid and _up(c.problem_id) == self.pid
            ]
            relation = RootRelation.unknown
            if ref.root_relation:
                try:
                    relation = RootRelation(ref.root_relation)
                except ValueError:
                    self.issue(
                        "invalid_relation",
                        f"{rid} carries root relation '{ref.root_relation}' outside the vocabulary",
                        node_ids=[rid],
                    )
            extra: dict[str, object] = {
                "paper_id": ref.paper_id,
                "locator": ref.locator.model_dump(mode="json"),
                "theorem_label": ref.theorem_label,
                "categories": [c.value for c in ref.categories],
                "extraction_method": ref.extraction_method,
                "review_note": ref.review_note,
                "applicability": [
                    {"id": c.id, "target_id": c.target_id, "result": str(c.result)} for c in mine
                ],
            }
            prov = self.provenance(rid)
            if prov:
                extra["campaign"] = prov
            parent = branch or ROOT_ID
            if (
                self.add_node(
                    ProofNode(
                        node_id=rid,
                        kind=ProofNodeKind.theorem_reference,
                        title=ref.title or ref.theorem_label or rid,
                        statement=ref.normalized_statement or ref.excerpt,
                        root_relation=relation,
                        assumption_context=list(ref.assumptions),
                        status=ref.review_status,
                        parents=[parent],
                        dependencies=[_up(d) for d in ref.dependencies],
                        created_at=ref.created_at,
                        updated_at=ref.updated_at,
                        source="workspace",
                        extra=extra,
                    )
                )
                is None
            ):
                continue
            self.want(rid, parent, "parent")
            for d in ref.dependencies:
                self.want(rid, d, "depends_on")
            if ref.review_status == "accepted":
                for c in mine:
                    if str(c.result) == "accepted" and c.target_id:
                        self.want(rid, c.target_id, "supports", f"applicability {c.id} accepted")
        legacy = self.read_list(
            "theorem_refs.jsonl", lambda: store.list_theorem_refs(self.ot_dir, self.pid)
        )
        for t in legacy:
            tid = _up(t.id)
            links = [_up(c) for c in t.claim_links]
            first_claim = next((c for c in links if _CLAIM_ID.match(c) and self.has(c)), None)
            parent = first_claim or ROOT_ID
            if (
                self.add_node(
                    ProofNode(
                        node_id=tid,
                        kind=ProofNodeKind.theorem_reference,
                        title=f"{t.paper_artifact} theorem {t.theorem_number or '?'}",
                        statement=t.statement_summary,
                        status="legacy",
                        parents=[parent],
                        supporting_artifacts=[t.paper_artifact],
                        created_at=t.created_at,
                        source="dossier",
                        extra={
                            "paper_artifact": t.paper_artifact,
                            "theorem_number": t.theorem_number,
                            "page": t.page,
                            "section": t.section,
                            "exact_quote": t.exact_quote,
                            "claim_links": links,
                            "note": "legacy THM- reference (unvalidated pointer)",
                        },
                    )
                )
                is None
            ):
                continue
            self.want(tid, parent, "parent")

    def build_campaign_nodes(self) -> None:
        snap = self.snapshot
        if snap is None:
            return
        for nid in sorted(snap.campaign_nodes):
            cn = snap.campaign_nodes[nid]
            if cn.obligation_id:
                target = _up(cn.obligation_id)
                if target in self.nodes:
                    self.nodes[target].extra["campaign_node_id"] = nid
                else:
                    self.issue(
                        "missing_ref",
                        f"campaign node {nid} mirrors obligation {target}, "
                        "which the snapshot lacks",
                        node_ids=[nid, target],
                        severity="warning",
                    )
                continue
            if cn.artifact_id:
                self._merge_artifact_node(cn)
                continue
            self._free_campaign_node(cn)
        # artifact refs the campaign recorded that no ledger can produce any more
        for ref in snap.artifact_refs:
            key = _up(ref.artifact_id)
            if ref.kind == "proof":
                key = verifier_node_id(key)
            elif ref.kind in _ROOT_KINDS or key == self.pid:
                key = ROOT_ID
            if key in self.nodes:
                continue
            if ref.kind in _NON_NODE_KINDS:
                self._note_other_artifact(ref.branch_id, key)
                continue
            if ref.kind not in _CAMPAIGN_KIND_MAP:
                continue
            self.issue(
                "missing_ref",
                f"the campaign recorded {ref.kind} {ref.artifact_id} (branch {ref.branch_id}), "
                "but no ledger holds it now",
                node_ids=[ref.artifact_id],
                severity="warning",
            )

    def _note_other_artifact(self, branch_id: str | None, key: str) -> None:
        if branch_id and branch_id in self.nodes:
            others = self.nodes[branch_id].extra.setdefault("other_artifacts", [])
            if isinstance(others, list) and key not in others:
                others.append(key)

    def _merge_artifact_node(self, cn: CampaignNodeState) -> None:
        key = _up(cn.artifact_id)
        if cn.kind == "proof":
            key = verifier_node_id(key)
        elif cn.kind in _ROOT_KINDS or key == self.pid:
            key = ROOT_ID
        node = self.nodes.get(key)
        if node is None and cn.kind in _NON_NODE_KINDS:
            self._note_other_artifact(cn.branch_id, key)
            return
        if node is None:
            self.issue(
                "missing_ref",
                f"campaign node {cn.node_id} points at {cn.kind} {cn.artifact_id}, "
                "which no ledger holds now",
                node_ids=[cn.node_id, key],
                severity="warning",
            )
            return
        campaign = node.extra.get("campaign")
        merged: dict[str, object] = dict(campaign) if isinstance(campaign, dict) else {}
        merged.update(
            {
                "campaign_node_id": cn.node_id,
                "branch_id": merged.get("branch_id") or cn.branch_id,
                "work_item_id": merged.get("work_item_id") or cn.work_item_id,
                "node_status": cn.status,
                "changes": list(cn.changes),
            }
        )
        node.extra["campaign"] = merged
        if (
            node.root_relation is RootRelation.unknown
            and cn.root_relation is not RootRelation.unknown
        ):
            node.root_relation = cn.root_relation
        branch = cn.branch_id
        if branch and branch in self.nodes and not node.parents:
            node.parents.append(branch)
            self.want(key, branch, "parent", "produced by this branch")

    def _free_campaign_node(self, cn: CampaignNodeState) -> None:
        kind = _CAMPAIGN_KIND_MAP.get(cn.kind)
        if kind is None or kind is ProofNodeKind.root:
            self.issue(
                "malformed_node",
                f"campaign node {cn.node_id} has kind '{cn.kind}', which the tree cannot place",
                node_ids=[cn.node_id],
                severity="warning",
            )
            return
        parents = [_up(p) for p in cn.parents] or ([cn.branch_id] if cn.branch_id else [ROOT_ID])
        deps = [_up(d) for d in cn.dependencies]
        if (
            self.add_node(
                ProofNode(
                    node_id=cn.node_id,
                    kind=kind,
                    title=cn.title or cn.node_id,
                    statement=cn.statement,
                    root_relation=cn.root_relation,
                    status=cn.status,
                    parents=parents,
                    dependencies=deps,
                    source="campaign",
                    extra={
                        "branch_id": cn.branch_id,
                        "work_item_id": cn.work_item_id,
                        "created_seq": cn.created_seq,
                        "updated_seq": cn.updated_seq,
                        "changes": list(cn.changes),
                    },
                )
            )
            is None
        ):
            return
        for p in parents:
            self.want(cn.node_id, p, "parent")
        for d in deps:
            self.want(cn.node_id, d, "depends_on")

    # -- assembly ---------------------------------------------------------------------

    def run(self) -> None:
        for step in (
            self.build_root,
            self.build_attribution,
            self.build_branches,
            self.build_obligations,
            self.build_claims,
            self.build_evidence,
            self.build_workspace_evidence,
            self.build_proof_attempts,
            self.build_verifier_ledger,
            self.build_experiments,
            self.build_failed_attempts,
            self.build_reviews,
            self.build_theorem_references,
            self.build_campaign_nodes,
        ):
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - one broken source must not lose the tree
                self.issue(
                    "malformed_node",
                    f"{step.__name__} failed: {type(exc).__name__}: {exc}",
                )
        self.link()

    def graph(self, campaign_id: str | None, generated_at: datetime | None) -> ProofGraph:
        edges = sorted(self.edges, key=lambda e: (e.source_id, e.target_id, e.relation))
        return ProofGraph(
            campaign_id=campaign_id,
            problem_id=self.pid,
            root_id=ROOT_ID,
            nodes=self.nodes,
            edges=edges,
            issues=list(self.issues),
            root_status=self.root_status_view,
            generated_at=generated_at,
        )


def build_proof_graph(
    ot_dir: Path,
    problem_id: str,
    snapshot: CampaignSnapshot | None = None,
    *,
    clock: Clock | None = None,
    validate: bool = True,
) -> ProofGraph:
    """The proof tree of ``problem_id`` merged with ``snapshot`` (``None`` = dossier only).

    ``generated_at`` is stamped only when a clock is given (the campaign layer reads
    no clock of its own); ``validate=False`` skips :func:`validation.validate_graph`
    for callers that validate later. Never raises on bad input.
    """
    builder = _Builder(ot_dir, problem_id, snapshot)
    builder.run()
    graph = builder.graph(
        snapshot.campaign_id if snapshot is not None else None,
        clock.now() if clock is not None else None,
    )
    if validate:
        from opentorus.campaign.proof_tree.validation import validate_graph

        graph.issues.extend(validate_graph(graph))
    return graph


__all__ = ["VERIFIER_SUFFIX", "build_proof_graph", "verifier_node_id"]
