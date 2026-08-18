"""Typed proof-tree records: nodes, edges, the graph, and its validation issues.

The proof tree is a *derived view*: it merges the campaign's orchestration nodes
(branches, obligations, failure signatures, campaign-proposed nodes) with the
dossier's artifacts (claims, evidence, proof attempts, experiments, failed
attempts, reviews, theorem references) and the workspace verifier ledger. Nothing
in this module is persisted and nothing here can change a claim status: a
``ProofNode.status`` is a *copy* of what the owning ledger says, and the graph's
``root_status`` is derived from dossier artifacts by ``settlement.root_status``
(``status_gate`` + ``scope``), never from campaign completion.

Every model is plain pydantic so ``render_json`` round-trips through
``ProofGraph.model_validate`` and the (M7) dashboard can consume it unchanged.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from opentorus.campaign.models import RootRelation


class ProofNodeKind(StrEnum):
    """What a node *is*; it decides the DOT shape and which edge relations are legal."""

    root = "root"
    branch = "branch"
    obligation = "obligation"
    claim = "claim"
    lemma = "lemma"
    theorem_reference = "theorem-reference"
    evidence = "evidence"
    proof_attempt = "proof-attempt"
    counterexample = "counterexample"
    experiment = "experiment"
    failed_attempt = "failed-attempt"
    review = "review"
    # A workspace verifier-ledger entry (``proofs.jsonl``): the artifact that can
    # actually back a ``verifies`` / ``closes`` edge.
    verification = "verification"
    # Reserved for views that want scheduling detail; the builder folds work items
    # into their branch's ``extra`` instead of emitting one node each.
    work_item = "work-item"


# Node kinds that describe *artifacts* (as opposed to the root and the campaign's
# structural nodes). ``orphan_artifact`` applies to these only.
ARTIFACT_KINDS: frozenset[ProofNodeKind] = frozenset(
    {
        ProofNodeKind.claim,
        ProofNodeKind.lemma,
        ProofNodeKind.theorem_reference,
        ProofNodeKind.evidence,
        ProofNodeKind.proof_attempt,
        ProofNodeKind.counterexample,
        ProofNodeKind.experiment,
        ProofNodeKind.failed_attempt,
        ProofNodeKind.review,
        ProofNodeKind.verification,
    }
)

EdgeRelation = Literal[
    "parent",
    "depends_on",
    "supports",
    "contradicts",
    "verifies",
    "reviews",
    "specializes",
    "relaxes",
    "refutes",
    "closes",
]
EDGE_RELATIONS: tuple[str, ...] = (
    "parent",
    "depends_on",
    "supports",
    "contradicts",
    "verifies",
    "reviews",
    "specializes",
    "relaxes",
    "refutes",
    "closes",
)

NodeSource = Literal["campaign", "dossier", "workspace"]

IssueCode = Literal[
    "missing_ref",
    "duplicate_id",
    "cycle",
    "self_dependency",
    "incompatible_assumptions",
    "invalid_relation",
    "unsupported_transition",
    "orphan_artifact",
    "special_case_root_closing",
    "malformed_node",
]
ISSUE_CODES: tuple[str, ...] = (
    "missing_ref",
    "duplicate_id",
    "cycle",
    "self_dependency",
    "incompatible_assumptions",
    "invalid_relation",
    "unsupported_transition",
    "orphan_artifact",
    "special_case_root_closing",
    "malformed_node",
)
IssueSeverity = Literal["warning", "error"]

ROOT_ID = "ROOT"


class ValidationIssue(BaseModel):
    """One finding of :func:`validation.validate_graph` (or the builder)."""

    code: IssueCode
    node_ids: list[str] = Field(default_factory=list)
    message: str
    severity: IssueSeverity = "error"


class ProofNode(BaseModel):
    """One node of the tree; ``status`` is copied from the owning ledger, never decided here.

    ``extra`` carries kind-specific detail a renderer may show (routing provenance and
    cost for branches, gap counts for proof attempts, closure info for obligations,
    the campaign node id and work item that produced an artifact).
    """

    model_config = ConfigDict(extra="forbid")

    node_id: str
    kind: ProofNodeKind
    title: str = ""
    statement: str = ""
    root_relation: RootRelation = RootRelation.unknown
    assumption_context: list[str] = Field(default_factory=list)
    status: str = "unknown"
    parents: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    supporting_artifacts: list[str] = Field(default_factory=list)
    contradicting_artifacts: list[str] = Field(default_factory=list)
    verification_refs: list[str] = Field(default_factory=list)
    review_findings: list[str] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    source: NodeSource = "dossier"
    extra: dict[str, object] = Field(default_factory=dict)


class ProofEdge(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str
    target_id: str
    relation: EdgeRelation
    rationale: str = ""


class RootStatusView(BaseModel):
    """The problem's derived status as the tree shows it (a *view*, not a decision).

    ``label`` is ``scope.classify_outcome``'s campaign-level classification,
    ``report_status`` is ``status_gate.derive_status``'s report rung; ``derived_from``
    names the functions and artifacts the derivation rests on, so a reader can see
    that no campaign state entered it.
    """

    label: str = "STATUS_UNCERTAIN"
    rationale: str = ""
    report_status: str = "UNSOLVED"
    derived_from: list[str] = Field(default_factory=list)


class ProofGraph(BaseModel):
    """The whole tree: nodes by id, typed edges, validation issues, derived root status."""

    model_config = ConfigDict(extra="forbid")

    campaign_id: str | None = None
    problem_id: str
    root_id: str = ROOT_ID
    nodes: dict[str, ProofNode] = Field(default_factory=dict)
    edges: list[ProofEdge] = Field(default_factory=list)
    issues: list[ValidationIssue] = Field(default_factory=list)
    root_status: RootStatusView = Field(default_factory=RootStatusView)
    generated_at: datetime | None = None

    # -- small read helpers renderers and validators share -------------------------

    def children_of(self, node_id: str) -> list[str]:
        """Ids whose ``parent`` edge points at ``node_id`` (sorted, deterministic)."""
        out = {e.source_id for e in self.edges if e.relation == "parent" and e.target_id == node_id}
        return sorted(out)

    def edges_from(self, node_id: str) -> list[ProofEdge]:
        return [e for e in self.edges if e.source_id == node_id]

    def edges_to(self, node_id: str) -> list[ProofEdge]:
        return [e for e in self.edges if e.target_id == node_id]

    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


__all__ = [
    "ARTIFACT_KINDS",
    "EDGE_RELATIONS",
    "ISSUE_CODES",
    "ROOT_ID",
    "EdgeRelation",
    "IssueCode",
    "IssueSeverity",
    "NodeSource",
    "ProofEdge",
    "ProofGraph",
    "ProofNode",
    "ProofNodeKind",
    "RootStatusView",
    "ValidationIssue",
]
