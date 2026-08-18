"""Graph validation: the ten issue codes, computed without ever raising.

The tree is assembled from several ledgers that can disagree (a claim cites evidence
that was never written, a campaign node names a branch the log lost, a synthetic
graph has a cycle). Validation makes every such disagreement a typed
:class:`ValidationIssue` attached to the graph, so a renderer or dashboard shows
the problem instead of crashing or, worse, hiding it. Each check is isolated: a
check that itself fails on strange input becomes a ``malformed_node`` issue naming
the check, and the remaining checks still run.

Codes (severity):

* ``missing_ref`` — an edge / parent / dependency names an unknown node (error); a
  supporting/contradicting/verification artifact list names one (warning: those may
  legitimately point outside the tree, e.g. a ``PAPER-``).
* ``duplicate_id`` — two node ids that differ only in case/whitespace (error).
* ``cycle`` — a cycle over ``parent`` / ``depends_on`` edges (iterative DFS; error).
* ``self_dependency`` — a node depending on / parented to itself (error).
* ``incompatible_assumptions`` — a child whose assumption context negates its parent's
  (``X`` vs ``not X`` / ``non-X``; error).
* ``invalid_relation`` — a root relation outside :class:`RootRelation`, an edge relation
  outside the vocabulary, or a relation the source/target kinds cannot carry (error).
* ``unsupported_transition`` — an obligation closed without a closing artifact, a
  status outside its ledger's vocabulary (error); a claim marked verified that no
  verification artifact reaches in the graph (warning).
* ``orphan_artifact`` — an artifact node with no edge at all (warning).
* ``special_case_root_closing`` — see ``settlement.special_case_marks_root``.
* ``malformed_node`` — a node the builder could not read, an id/key mismatch, a
  missing root, or a check that failed (error).
"""

from __future__ import annotations

import re
from collections.abc import Callable

from opentorus.campaign.models import BranchStatus, ObligationStatus, RootRelation
from opentorus.campaign.proof_tree.models import (
    ARTIFACT_KINDS,
    EDGE_RELATIONS,
    ProofGraph,
    ProofNode,
    ProofNodeKind,
    ValidationIssue,
)
from opentorus.research.dossier.models import CLAIM_STATUSES

# Which node kinds may be the *source* of a typed edge. ``parent`` and ``depends_on``
# are structural and open to every kind. A missing entry means "any kind".
EDGE_SOURCE_KINDS: dict[str, frozenset[ProofNodeKind]] = {
    "supports": frozenset(
        {
            ProofNodeKind.evidence,
            ProofNodeKind.experiment,
            ProofNodeKind.claim,
            ProofNodeKind.lemma,
            ProofNodeKind.counterexample,
            ProofNodeKind.theorem_reference,
            ProofNodeKind.proof_attempt,
            ProofNodeKind.verification,
            ProofNodeKind.obligation,
            ProofNodeKind.branch,
        }
    ),
    "contradicts": frozenset(
        {
            ProofNodeKind.evidence,
            ProofNodeKind.experiment,
            ProofNodeKind.claim,
            ProofNodeKind.lemma,
            ProofNodeKind.counterexample,
            ProofNodeKind.theorem_reference,
            ProofNodeKind.proof_attempt,
            ProofNodeKind.verification,
            ProofNodeKind.failed_attempt,
        }
    ),
    "verifies": frozenset(
        {ProofNodeKind.verification, ProofNodeKind.proof_attempt, ProofNodeKind.evidence}
    ),
    "reviews": frozenset({ProofNodeKind.review}),
    "specializes": frozenset(
        {
            ProofNodeKind.branch,
            ProofNodeKind.obligation,
            ProofNodeKind.claim,
            ProofNodeKind.lemma,
            ProofNodeKind.theorem_reference,
        }
    ),
    "relaxes": frozenset(
        {
            ProofNodeKind.branch,
            ProofNodeKind.obligation,
            ProofNodeKind.claim,
            ProofNodeKind.lemma,
            ProofNodeKind.theorem_reference,
        }
    ),
    "refutes": frozenset(
        {
            ProofNodeKind.counterexample,
            ProofNodeKind.claim,
            ProofNodeKind.evidence,
            ProofNodeKind.verification,
            ProofNodeKind.experiment,
        }
    ),
    "closes": frozenset(
        {
            ProofNodeKind.verification,
            ProofNodeKind.claim,
            ProofNodeKind.counterexample,
            ProofNodeKind.proof_attempt,
            ProofNodeKind.theorem_reference,
            ProofNodeKind.evidence,
        }
    ),
}
# Which node kinds may be the *target* of a typed edge (missing = any).
EDGE_TARGET_KINDS: dict[str, frozenset[ProofNodeKind]] = {
    "closes": frozenset({ProofNodeKind.obligation}),
    "verifies": frozenset(
        {
            ProofNodeKind.proof_attempt,
            ProofNodeKind.claim,
            ProofNodeKind.lemma,
            ProofNodeKind.counterexample,
            ProofNodeKind.obligation,
            ProofNodeKind.evidence,
            ProofNodeKind.root,
        }
    ),
}

# Id prefixes that denote nodes of the tree. Artifact lists may also cite things the
# tree does not model (``PAPER-``, ``APPR-``, ``COV-``, ``DATA-``); those are not
# missing references, so only ids with these prefixes are checked.
TREE_ID_PREFIXES: tuple[str, ...] = (
    "CLAIM-",
    "EVID-",
    "PROOF-",
    "EXP-",
    "THMREF-",
    "THM-",
    "REVIEW-",
    "REFEREE-",
    "OBL-",
    "BRANCH-",
    "FSIG-",
    "FAILED-",
    "NODE-",
)


def _tree_id_missing(ref: str, known: set[str]) -> bool:
    """``ref`` looks like a tree id and no node carries it (either ``PROOF-`` form)."""
    key = ref.strip().upper()
    if not key.startswith(TREE_ID_PREFIXES):
        return False
    if key in known:
        return False
    if key.startswith("PROOF-") and f"{key}@verifier" in known:
        return False
    return True


_VERIFICATION_STATUSES: frozenset[str] = frozenset({"accepted", "rejected", "inconclusive"})
_VERIFIED_CLAIM_STATUSES: frozenset[str] = frozenset({"verified", "formally_verified"})
_NEGATION = re.compile(r"^(?:not\s+|non-?\s*|no\s+)", re.I)


def _norm_assumption(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().rstrip(".").lower())


def _negated_pair(a: str, b: str) -> bool:
    """``a`` and ``b`` are the same assumption with and without a negation prefix."""
    na, nb = _norm_assumption(a), _norm_assumption(b)
    if not na or not nb or na == nb:
        return False
    return _NEGATION.sub("", na, count=1) == nb or _NEGATION.sub("", nb, count=1) == na


Check = Callable[[ProofGraph], list[ValidationIssue]]


def _check_structure(graph: ProofGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    if graph.root_id not in graph.nodes:
        issues.append(
            ValidationIssue(
                code="malformed_node",
                node_ids=[graph.root_id],
                message=f"graph has no root node '{graph.root_id}'",
            )
        )
    seen_fold: dict[str, str] = {}
    for key, node in graph.nodes.items():
        if not node.node_id.strip():
            issues.append(
                ValidationIssue(
                    code="malformed_node", node_ids=[key], message="node has an empty id"
                )
            )
        elif key != node.node_id:
            issues.append(
                ValidationIssue(
                    code="malformed_node",
                    node_ids=[key, node.node_id],
                    message=f"node stored under '{key}' says its id is '{node.node_id}'",
                )
            )
        fold = re.sub(r"\s+", "", node.node_id).upper()
        if fold in seen_fold and seen_fold[fold] != key:
            issues.append(
                ValidationIssue(
                    code="duplicate_id",
                    node_ids=[seen_fold[fold], key],
                    message=f"ids '{seen_fold[fold]}' and '{key}' collide (case/whitespace)",
                )
            )
        else:
            seen_fold.setdefault(fold, key)
    return issues


def _check_refs(graph: ProofGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    known = set(graph.nodes)
    for edge in graph.edges:
        for end, label in ((edge.source_id, "source"), (edge.target_id, "target")):
            if end not in known:
                issues.append(
                    ValidationIssue(
                        code="missing_ref",
                        node_ids=[edge.source_id, edge.target_id],
                        message=(
                            f"edge {edge.source_id} -{edge.relation}-> {edge.target_id}: "
                            f"unknown {label} node '{end}'"
                        ),
                    )
                )
    for node in graph.nodes.values():
        for field, ids in (("parent", node.parents), ("dependency", node.dependencies)):
            for ref in ids:
                if ref not in known:
                    issues.append(
                        ValidationIssue(
                            code="missing_ref",
                            node_ids=[node.node_id, ref],
                            message=f"{node.node_id} names unknown {field} '{ref}'",
                        )
                    )
        for field, ids in (
            ("supporting artifact", node.supporting_artifacts),
            ("contradicting artifact", node.contradicting_artifacts),
            ("verification ref", node.verification_refs),
        ):
            for ref in ids:
                if _tree_id_missing(ref, known):
                    issues.append(
                        ValidationIssue(
                            code="missing_ref",
                            node_ids=[node.node_id, ref],
                            message=f"{node.node_id} names {field} '{ref}' that is not in the tree",
                            severity="warning",
                        )
                    )
    return issues


def _check_self(graph: ProofGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    for node in graph.nodes.values():
        if node.node_id in node.parents or node.node_id in node.dependencies:
            issues.append(
                ValidationIssue(
                    code="self_dependency",
                    node_ids=[node.node_id],
                    message=f"{node.node_id} lists itself as parent/dependency",
                )
            )
    for edge in graph.edges:
        if edge.source_id == edge.target_id:
            issues.append(
                ValidationIssue(
                    code="self_dependency",
                    node_ids=[edge.source_id],
                    message=f"{edge.source_id} has a '{edge.relation}' edge to itself",
                )
            )
    return issues


def _adjacency(graph: ProofGraph) -> dict[str, list[str]]:
    """Directed ``node -> [nodes it points at]`` over parent/depends_on structure."""
    adj: dict[str, set[str]] = {nid: set() for nid in graph.nodes}
    for node in graph.nodes.values():
        for ref in [*node.parents, *node.dependencies]:
            if ref in adj:
                adj[node.node_id].add(ref)
    for edge in graph.edges:
        if edge.relation in ("parent", "depends_on") and edge.source_id in adj:
            if edge.target_id in adj:
                adj[edge.source_id].add(edge.target_id)
    return {k: sorted(v) for k, v in adj.items()}


def find_cycles(graph: ProofGraph) -> list[list[str]]:
    """Every distinct cycle over parent/depends_on edges, found by *iterative* DFS.

    Iterative so a 10k-node chain never hits the recursion limit; each cycle is
    reported once, as the ids along it starting from its smallest id.
    """
    adj = _adjacency(graph)
    white, grey, black = 0, 1, 2
    colour = dict.fromkeys(adj, white)
    cycles: list[list[str]] = []
    seen_keys: set[tuple[str, ...]] = set()
    for start in sorted(adj):
        if colour[start] != white:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = [start]
        colour[start] = grey
        while stack:
            node, idx = stack[-1]
            nexts = adj[node]
            if idx < len(nexts):
                stack[-1] = (node, idx + 1)
                nxt = nexts[idx]
                if colour[nxt] == white:
                    colour[nxt] = grey
                    stack.append((nxt, 0))
                    path.append(nxt)
                elif colour[nxt] == grey:
                    cyc = path[path.index(nxt) :]
                    pivot = cyc.index(min(cyc))
                    ordered = tuple(cyc[pivot:] + cyc[:pivot])
                    if ordered not in seen_keys:
                        seen_keys.add(ordered)
                        cycles.append(list(ordered))
            else:
                colour[node] = black
                stack.pop()
                path.pop()
    return cycles


def _check_cycles(graph: ProofGraph) -> list[ValidationIssue]:
    return [
        ValidationIssue(
            code="cycle",
            node_ids=list(cyc),
            message="cycle over parent/depends_on edges: " + " -> ".join([*cyc, cyc[0]]),
        )
        for cyc in find_cycles(graph)
        if len(cyc) > 1  # a self-loop is reported as self_dependency
    ]


def _check_assumptions(graph: ProofGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    pairs: set[tuple[str, str]] = set()
    for node in graph.nodes.values():
        for parent in node.parents:
            pairs.add((node.node_id, parent))
    for edge in graph.edges:
        if edge.relation == "parent":
            pairs.add((edge.source_id, edge.target_id))
    for child_id, parent_id in sorted(pairs):
        child = graph.nodes.get(child_id)
        parent_node = graph.nodes.get(parent_id)
        if child is None or parent_node is None:
            continue
        for a in child.assumption_context:
            for b in parent_node.assumption_context:
                if _negated_pair(a, b):
                    issues.append(
                        ValidationIssue(
                            code="incompatible_assumptions",
                            node_ids=[child_id, parent_id],
                            message=(
                                f"{child_id} assumes '{a}' under parent {parent_id} which "
                                f"assumes '{b}'"
                            ),
                        )
                    )
    return issues


def _check_relations(graph: ProofGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    valid_relations = {r.value for r in RootRelation}
    for node in graph.nodes.values():
        rel = getattr(node.root_relation, "value", node.root_relation)
        if str(rel) not in valid_relations:
            issues.append(
                ValidationIssue(
                    code="invalid_relation",
                    node_ids=[node.node_id],
                    message=f"{node.node_id} has root relation '{rel}' outside the vocabulary",
                )
            )
    for edge in graph.edges:
        if edge.relation not in EDGE_RELATIONS:
            issues.append(
                ValidationIssue(
                    code="invalid_relation",
                    node_ids=[edge.source_id, edge.target_id],
                    message=(
                        f"edge {edge.source_id} -> {edge.target_id} has relation "
                        f"'{edge.relation}' outside the vocabulary"
                    ),
                )
            )
            continue
        src = graph.nodes.get(edge.source_id)
        dst = graph.nodes.get(edge.target_id)
        allowed_src = EDGE_SOURCE_KINDS.get(edge.relation)
        if src is not None and allowed_src is not None and src.kind not in allowed_src:
            issues.append(
                ValidationIssue(
                    code="invalid_relation",
                    node_ids=[edge.source_id, edge.target_id],
                    message=(
                        f"a {src.kind.value} node cannot '{edge.relation}' "
                        f"({edge.source_id} -> {edge.target_id})"
                    ),
                )
            )
        allowed_dst = EDGE_TARGET_KINDS.get(edge.relation)
        if dst is not None and allowed_dst is not None and dst.kind not in allowed_dst:
            issues.append(
                ValidationIssue(
                    code="invalid_relation",
                    node_ids=[edge.source_id, edge.target_id],
                    message=(
                        f"'{edge.relation}' cannot target a {dst.kind.value} node "
                        f"({edge.source_id} -> {edge.target_id})"
                    ),
                )
            )
    return issues


def _verification_reaches(graph: ProofGraph, node_id: str) -> bool:
    for edge in graph.edges_to(node_id):
        if edge.relation == "verifies":
            return True
        if edge.relation == "supports":
            src = graph.nodes.get(edge.source_id)
            if src is not None and (
                src.kind is ProofNodeKind.verification
                or (
                    src.kind is ProofNodeKind.evidence
                    and str(src.extra.get("evidence_type", ""))
                    in ("FORMAL_PROOF", "VALIDATED_NUMERICAL")
                )
                or (src.kind is ProofNodeKind.proof_attempt and src.status == "verified")
            ):
                return True
    return False


def _check_transitions(graph: ProofGraph) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    obligation_statuses = {s.value for s in ObligationStatus}
    branch_statuses = {s.value for s in BranchStatus}
    for node in graph.nodes.values():
        if node.kind is ProofNodeKind.obligation:
            if node.status not in obligation_statuses:
                issues.append(
                    ValidationIssue(
                        code="unsupported_transition",
                        node_ids=[node.node_id],
                        message=f"{node.node_id}: obligation status '{node.status}' is unknown",
                    )
                )
            elif node.status == ObligationStatus.closed.value and not node.extra.get(
                "closed_by_artifact"
            ):
                issues.append(
                    ValidationIssue(
                        code="unsupported_transition",
                        node_ids=[node.node_id],
                        message=(
                            f"{node.node_id} is closed without a closing artifact — an "
                            "obligation closes only through obligation_closed citing one"
                        ),
                    )
                )
        elif node.kind in (ProofNodeKind.claim, ProofNodeKind.lemma, ProofNodeKind.counterexample):
            if node.status not in CLAIM_STATUSES:
                issues.append(
                    ValidationIssue(
                        code="unsupported_transition",
                        node_ids=[node.node_id],
                        message=(
                            f"{node.node_id}: claim status '{node.status}' is not a claim status"
                        ),
                    )
                )
            elif node.status in _VERIFIED_CLAIM_STATUSES and not (
                node.verification_refs or _verification_reaches(graph, node.node_id)
            ):
                issues.append(
                    ValidationIssue(
                        code="unsupported_transition",
                        node_ids=[node.node_id],
                        message=(
                            f"{node.node_id} is '{node.status}' but no verification artifact "
                            "reaches it in the tree"
                        ),
                        severity="warning",
                    )
                )
        elif node.kind is ProofNodeKind.branch and node.status not in branch_statuses:
            issues.append(
                ValidationIssue(
                    code="unsupported_transition",
                    node_ids=[node.node_id],
                    message=f"{node.node_id}: branch status '{node.status}' is unknown",
                )
            )
        elif node.kind is ProofNodeKind.verification and node.status not in _VERIFICATION_STATUSES:
            issues.append(
                ValidationIssue(
                    code="unsupported_transition",
                    node_ids=[node.node_id],
                    message=(
                        f"{node.node_id}: verification status '{node.status}' is not "
                        "accepted/rejected/inconclusive"
                    ),
                )
            )
    return issues


def _check_orphans(graph: ProofGraph) -> list[ValidationIssue]:
    touched: set[str] = set()
    for edge in graph.edges:
        touched.add(edge.source_id)
        touched.add(edge.target_id)
    for node in graph.nodes.values():
        if node.parents or node.dependencies:
            touched.add(node.node_id)
        touched.update(node.parents)
        touched.update(node.dependencies)
    return [
        ValidationIssue(
            code="orphan_artifact",
            node_ids=[node.node_id],
            message=f"{node.node_id} ({node.kind.value}) is connected to nothing",
            severity="warning",
        )
        for node in graph.nodes.values()
        if node.kind in ARTIFACT_KINDS and node.node_id not in touched
    ]


def _check_special_case(graph: ProofGraph) -> list[ValidationIssue]:
    from opentorus.campaign.proof_tree.settlement import special_case_marks_root

    return special_case_marks_root(graph)


CHECKS: tuple[tuple[str, Check], ...] = (
    ("structure", _check_structure),
    ("refs", _check_refs),
    ("self", _check_self),
    ("cycles", _check_cycles),
    ("assumptions", _check_assumptions),
    ("relations", _check_relations),
    ("transitions", _check_transitions),
    ("orphans", _check_orphans),
    ("special_case", _check_special_case),
)


def validate_graph(graph: ProofGraph) -> list[ValidationIssue]:
    """All issues of ``graph``; never raises (a failing check is itself an issue)."""
    issues: list[ValidationIssue] = []
    for name, check in CHECKS:
        try:
            issues.extend(check(graph))
        except Exception as exc:  # noqa: BLE001 - validation must report, not crash
            issues.append(
                ValidationIssue(
                    code="malformed_node",
                    node_ids=[],
                    message=f"validation check '{name}' failed: {type(exc).__name__}: {exc}",
                )
            )
    return issues


def issue_counts(issues: list[ValidationIssue]) -> dict[str, int]:
    """``code -> count`` in a stable order (for summaries and the dashboard)."""
    counts: dict[str, int] = {}
    for issue in issues:
        counts[issue.code] = counts.get(issue.code, 0) + 1
    return dict(sorted(counts.items()))


def is_artifact_node(node: ProofNode) -> bool:
    return node.kind in ARTIFACT_KINDS


__all__ = [
    "CHECKS",
    "EDGE_SOURCE_KINDS",
    "EDGE_TARGET_KINDS",
    "find_cycles",
    "is_artifact_node",
    "issue_counts",
    "validate_graph",
]
