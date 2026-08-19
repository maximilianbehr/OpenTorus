"""Typed relations between theorem references (and from references to claims).

Relations are recorded with provenance and their own review status so a
model-proposed ``implies`` edge is distinguishable from a human-asserted one; the
applicability checker treats ``contradicts`` edges to *accepted* references as
disqualifying and uses ``implies``/``requires-definition`` edges to recognise
covered hypotheses.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.errors import OpenTorusError
from opentorus.research.theorems import store
from opentorus.research.theorems.models import (
    REVIEW_STATUSES,
    Provenance,
    ReviewStatus,
    TheoremRelation,
    TheoremRelationKind,
)

# Non-THMREF targets an ``applies-to`` edge may point at (dossier claims and
# campaign obligations); anything else must be a reference in the ledger.
_APPLIES_TO_TARGET_PREFIXES = ("CLAIM-", "OBL-")


def add_relation(
    ot_dir: Path,
    source_ref: str,
    target_ref: str,
    relation: str,
    *,
    provenance: Provenance,
    rationale: str = "",
    review_status: ReviewStatus = "candidate",
) -> TheoremRelation:
    """Record ``source_ref --relation--> target_ref`` after validating both ends."""
    try:
        kind = TheoremRelationKind(relation)
    except ValueError as exc:
        raise OpenTorusError(
            f"Unknown relation '{relation}'; expected one of "
            f"{', '.join(k.value for k in TheoremRelationKind)}."
        ) from exc
    if review_status not in REVIEW_STATUSES:
        raise OpenTorusError(
            f"Unknown review status '{review_status}'; expected one of "
            f"{', '.join(REVIEW_STATUSES)}."
        )
    src = store.require_reference(ot_dir, source_ref).id
    tgt = target_ref.strip().upper()
    if kind is TheoremRelationKind.applies_to and tgt.startswith(_APPLIES_TO_TARGET_PREFIXES):
        pass
    else:
        tgt = store.require_reference(ot_dir, tgt).id
    if src == tgt:
        raise OpenTorusError("A relation needs two distinct endpoints.")
    return store.add_relation(
        ot_dir,
        TheoremRelation(
            source_ref=src,
            target_ref=tgt,
            relation=kind,
            provenance=provenance,
            rationale=rationale,
            review_status=review_status,
        ),
    )


def relation_graph(ot_dir: Path) -> dict[str, list[TheoremRelation]]:
    """Outgoing adjacency: ``source_ref -> [relations]`` (rejected edges excluded)."""
    graph: dict[str, list[TheoremRelation]] = {}
    for rel in store.list_relations(ot_dir):
        if rel.review_status == "rejected":
            continue
        graph.setdefault(rel.source_ref, []).append(rel)
    return graph


def contradicting_refs(ot_dir: Path, ref_id: str) -> list[str]:
    """Ids linked to ``ref_id`` by a non-rejected ``contradicts`` edge (either direction)."""
    wanted = ref_id.strip().upper()
    found: list[str] = []
    for rel in store.list_relations(ot_dir, ref_id=wanted):
        if rel.relation is not TheoremRelationKind.contradicts or rel.review_status == "rejected":
            continue
        other = rel.target_ref if rel.source_ref.upper() == wanted else rel.source_ref
        if other not in found:
            found.append(other)
    return found
