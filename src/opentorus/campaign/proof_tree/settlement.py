"""Settlement rules: what a root relation *could* settle, and the single source of
truth for whether an obligation may close.

Two questions are answered here and nowhere else in the campaign layer:

1. **Relation settlement** — given how a branch/obligation relates to the root
   (:class:`~opentorus.campaign.models.RootRelation`), can settling it ever settle
   the root? Only ``equivalent``, ``sufficient``, ``necessary`` and
   ``counterexample-route`` can, and each only under a named further condition
   (:data:`RELATION_CAN_SETTLE`). ``special-case``, ``relaxation``, ``supporting``,
   ``unrelated`` and ``unknown`` never can — a proof of a special case, however
   solid, leaves the general statement open.

2. **Obligation closure** — :func:`can_close_obligation` decides whether an artifact
   may close an obligation, per closure mode. Everything that closes an obligation
   is an *accepted* artifact checked here with the same rules the dossier uses:

   * certificate modes (``formal_proof``, ``smt_certificate``,
     ``exact_symbolic_certificate``, ``validated_numerical_certificate``): a
     ``PROOF-*`` in the workspace verifier ledger passing the four checks of
     ``dossier.claims._require_verification_artifact`` — exists, not inconclusive,
     accepted, recorded under this problem or unscoped — with a backend matching
     the mode;
   * ``accepted_counterexample_certificate``: a cited dossier claim of type
     ``COUNTEREXAMPLE_VERIFIED`` (only creatable with an explicit verification
     record) whose record names every assumption the dossier records
     (:func:`witness_satisfies_root_assumptions`, conservative: a missing
     assumption refuses);
   * ``nl_proof_referee_accepted``: a gap-free *primary* dossier proof attempt whose
     ``claim_links`` name the claim the obligation is about, that documents the
     closure of the gap the obligation came from, and on which the hostile referee
     (``referee_review(persist=False)``) passes;
   * ``accepted_literature_theorem``: a human-accepted ``THMREF-*`` with an accepted
     applicability check for this problem targeting the obligation or its claim.

   Anything else stays open, with the reason.

The verifier-coordinator (``workers/verifier.py``) turns an allowed verdict into a
*proposal*; the engine records ``obligation_closed``. No code path here touches a
claim status, and closing an obligation never changes the problem's derived status
(:func:`root_status`), which is read from ``status_gate`` / ``scope`` on demand.

Gap markers: deleting ``[GAP-n]`` from a proof body does not close the obligation
that gap produced. The obligation's status lives in the campaign event log; and the
referee route requires the marker to be *accounted for* in the body (a ``[GAP-n]
closed: ...`` note or a "gaps closed" section, the closed contexts ``nl_proof``
already recognises), so silent erasure is refused with a reason that says what to
write instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from opentorus.campaign.models import (
    ClosureMode,
    Obligation,
    ObligationStatus,
    RootRelation,
)
from opentorus.campaign.proof_tree.models import (
    ProofGraph,
    ProofNodeKind,
    RootStatusView,
    ValidationIssue,
)

if TYPE_CHECKING:
    from opentorus.research.dossier.models import ClaimRecord, ProofAttempt

# --------------------------------------------------------------------------------------
# Relation settlement
# --------------------------------------------------------------------------------------

# Relation -> the further condition under which settling the branch settles the root;
# ``None`` = never (settling the branch says nothing about the root's truth value).
RELATION_CAN_SETTLE: dict[RootRelation, str | None] = {
    RootRelation.equivalent: "needs_justified_equivalence",
    RootRelation.sufficient: "needs_verified_reduction_and_obligations",
    RootRelation.necessary: "needs_converse",
    RootRelation.counterexample_route: "needs_accepted_witness",
    RootRelation.special_case: None,
    RootRelation.relaxation: None,
    RootRelation.supporting: None,
    RootRelation.unrelated: None,
    RootRelation.unknown: None,
}

_SETTLEMENT_REASONS: dict[RootRelation, str] = {
    RootRelation.equivalent: (
        "an equivalent statement settles the root once the equivalence itself is "
        "justified (a verified reduction in both directions or an accepted reference)"
    ),
    RootRelation.sufficient: (
        "a sufficient condition settles the root only in the proving direction, and only "
        "when the reduction is verified and every obligation it opens is closed"
    ),
    RootRelation.necessary: (
        "a necessary condition can refute the root (if it fails) but proving it settles "
        "nothing without the converse"
    ),
    RootRelation.counterexample_route: (
        "a counterexample route settles the root negatively once an accepted witness "
        "passes every root assumption and violates the conclusion"
    ),
    RootRelation.special_case: (
        "a special case cannot settle the root: proving the statement for a subclass "
        "leaves the general statement open (a special-case refutation refutes the root, "
        "but then the branch is a counterexample route)"
    ),
    RootRelation.relaxation: (
        "a relaxation cannot settle the root: a weaker statement neither proves nor "
        "refutes the stronger one"
    ),
    RootRelation.supporting: "supporting work informs the attack; it settles nothing itself",
    RootRelation.unrelated: "an unrelated branch settles nothing about the root",
    RootRelation.unknown: (
        "the relation to the root is not yet classified; nothing can be settled until it is"
    ),
}


class SettlementVerdict(BaseModel):
    can_settle: bool
    relation: RootRelation
    condition: str | None = None
    reason: str = ""


def relation_settlement(relation: RootRelation | str) -> SettlementVerdict:
    """Can settling something in this relation to the root settle the root — and how?"""
    rel = RootRelation(relation)
    condition = RELATION_CAN_SETTLE[rel]
    return SettlementVerdict(
        can_settle=condition is not None,
        relation=rel,
        condition=condition,
        reason=_SETTLEMENT_REASONS[rel],
    )


# --------------------------------------------------------------------------------------
# Obligation closure
# --------------------------------------------------------------------------------------

# Verifier backend -> the certificate mode it can satisfy. ``formal_proof`` (a proof
# assistant) is also what the codebase calls "verification-grade" in general, so any
# accepted backend satisfies ``formal_proof`` when the obligation lists it; the
# certificate modes additionally require the matching backend.
BACKEND_CLOSURE_MODES: dict[str, ClosureMode] = {
    "lean4": ClosureMode.formal_proof,
    "lean": ClosureMode.formal_proof,
    "coq": ClosureMode.formal_proof,
    "smt": ClosureMode.smt_certificate,
    "z3": ClosureMode.smt_certificate,
    "cvc5": ClosureMode.smt_certificate,
    "sympy": ClosureMode.exact_symbolic_certificate,
    "symbolic": ClosureMode.exact_symbolic_certificate,
    "interval": ClosureMode.validated_numerical_certificate,
    "validated_numerical": ClosureMode.validated_numerical_certificate,
}
CERTIFICATE_MODES: frozenset[ClosureMode] = frozenset(
    {
        ClosureMode.formal_proof,
        ClosureMode.smt_certificate,
        ClosureMode.exact_symbolic_certificate,
        ClosureMode.validated_numerical_certificate,
    }
)

_PROOF_ID = re.compile(r"^PROOF-\d+$")
_CLAIM_ID = re.compile(r"^CLAIM-\d+$")
_THMREF_ID = re.compile(r"^THMREF-\d+$")
_GAP_BRACKET = re.compile(r"\[GAP[^\]]*\]", re.I)


class ClosureVerdict(BaseModel):
    """The answer to "may this obligation close?" with every reason that was checked."""

    allowed: bool
    obligation_id: str = ""
    mode: ClosureMode | None = None
    artifact_id: str | None = None
    reason: str = ""
    check_id: str | None = None
    # Every per-artifact / per-mode finding, in evaluation order (the verifier's notes).
    details: list[str] = Field(default_factory=list)


def _norm_id(text: str) -> str:
    return text.strip().upper()


def _cited_ids(ob: Obligation) -> list[str]:
    """Explicitly cited artifacts (supporting + source proof), normalised, in order."""
    seen: list[str] = []
    for aid in [*ob.supporting_artifacts, *([ob.source_proof_id] if ob.source_proof_id else [])]:
        key = _norm_id(aid)
        if key and key not in seen:
            seen.append(key)
    return seen


def _ledger_candidates(ob: Obligation, explicit: str | None) -> list[str]:
    """``PROOF-*`` ids to check against the workspace verifier ledger.

    ``source_proof_id`` is deliberately excluded: it names a *dossier* proof attempt
    (``proof_attempts/index.jsonl``), and the dossier and workspace ``PROOF-`` id
    spaces collide (the collision ``verifiers/proofs.py`` documents). Looking a
    sketch's id up in the ledger could hit an unrelated accepted certificate.
    """
    if explicit is not None:
        return [_norm_id(explicit)] if _PROOF_ID.match(_norm_id(explicit)) else []
    out: list[str] = []
    for aid in ob.supporting_artifacts:
        key = _norm_id(aid)
        if _PROOF_ID.match(key) and key not in out:
            out.append(key)
    return out


def _named_claim_ids(ot_dir: Path, problem_id: str, ob: Obligation) -> list[str]:
    """The claim(s) an obligation is about: cited/depended-on CLAIM ids, else the
    dossier's designated primary claim (the obligation of a prove-or-refute campaign
    is about its primary claim unless it says otherwise)."""
    ids: list[str] = []
    for aid in [*ob.dependencies, *ob.supporting_artifacts]:
        key = _norm_id(aid)
        if _CLAIM_ID.match(key) and key not in ids:
            ids.append(key)
    if ids:
        return ids
    from opentorus.research.dossier import store

    dossier = store.get_dossier(ot_dir, problem_id)
    if dossier is not None and dossier.primary_claim_id:
        return [_norm_id(dossier.primary_claim_id)]
    return []


def ledger_proof_verdict(ot_dir: Path, problem_id: str, proof_id: str) -> tuple[bool, str, str]:
    """``(accepted, backend, reason)`` — the four checks of the dossier claim gate.

    Mirrors ``dossier.claims._require_verification_artifact`` exactly: the attempt
    must exist, must not be inconclusive (timeout/crash verifies nothing), must be
    accepted, and must be recorded under this problem or unscoped.
    """
    from opentorus.research.verifiers.proofs import get_proof

    proof = get_proof(ot_dir, proof_id)
    if proof is None:
        return False, "", f"{proof_id}: no such attempt in the proof ledger"
    if proof.inconclusive:
        return False, proof.backend, f"{proof_id}: {proof.backend} was inconclusive"
    if not proof.accepted:
        return False, proof.backend, f"{proof_id}: {proof.backend} REJECTED this attempt"
    if proof.problem_id is not None and proof.problem_id != problem_id:
        return False, proof.backend, f"{proof_id}: recorded under {proof.problem_id}"
    return True, proof.backend, f"{proof_id}: {proof.backend} accepted"


def _certificate_route(
    ot_dir: Path, problem_id: str, ob: Obligation, explicit: str | None, details: list[str]
) -> ClosureVerdict | None:
    wanted = [m for m in ob.closure_modes if m in CERTIFICATE_MODES]
    if not wanted:
        return None
    for aid in _ledger_candidates(ob, explicit):
        ok, backend, reason = ledger_proof_verdict(ot_dir, problem_id, aid)
        details.append(reason)
        if not ok:
            continue
        backend_mode = BACKEND_CLOSURE_MODES.get(backend.lower())
        if backend_mode is not None and backend_mode in wanted:
            mode = backend_mode
        elif ClosureMode.formal_proof in wanted:
            mode = ClosureMode.formal_proof
        else:
            details.append(f"{aid}: backend {backend} does not match {[m.value for m in wanted]}")
            continue
        return ClosureVerdict(
            allowed=True,
            obligation_id=ob.obligation_id,
            mode=mode,
            artifact_id=aid,
            reason=reason,
            check_id=aid,
        )
    return None


def _assumption_haystack(ot_dir: Path, problem_id: str, claim: ClaimRecord) -> str:
    """Everything a counterexample's verification record says, lower-cased.

    The claim's own text and notes; every cited artifact — dossier evidence
    (summary + limitations, and the verifier runs it cites), dossier proof attempts
    (title, gaps, body), workspace verifier runs (output + submitted source); and the
    reasons recorded in the claim's status changelog.
    """
    from opentorus.research.dossier import store
    from opentorus.research.verifiers.proofs import get_proof

    parts: list[str] = [claim.statement or "", claim.notes or ""]
    evidence = {e.id: e for e in store.list_evidence(ot_dir, problem_id)}
    attempts = {p.id: p for p in store.list_proof_attempts(ot_dir, problem_id)}
    ddir = store.dossier_dir(ot_dir, problem_id)

    def _ledger_text(pid: str) -> None:
        proof = get_proof(ot_dir, pid)
        if proof is None:
            return
        parts.append(proof.output or "")
        src = ot_dir / proof.source_path
        if src.is_file():
            try:
                parts.append(src.read_text(encoding="utf-8"))
            except OSError:
                pass

    for aid in [*claim.source_artifacts, *claim.evidence_links]:
        key = _norm_id(aid)
        ev = evidence.get(key)
        if ev is not None:
            parts.append(ev.summary or "")
            parts.extend(ev.limitations)
            for cited in ev.source_artifacts:
                if _PROOF_ID.match(_norm_id(cited)):
                    _ledger_text(_norm_id(cited))
        att = attempts.get(key)
        if att is not None:
            parts.append(att.title or "")
            parts.extend(att.gaps)
            if att.body_path and (ddir / att.body_path).is_file():
                try:
                    parts.append((ddir / att.body_path).read_text(encoding="utf-8"))
                except OSError:
                    pass
        elif _PROOF_ID.match(key):
            _ledger_text(key)
    for change in store.list_status_changes(ot_dir, problem_id):
        if change.claim_id == claim.id:
            parts.append(change.reason or "")
    return _squash("\n".join(parts))


def _squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def witness_satisfies_root_assumptions(
    ot_dir: Path, problem_id: str, claim: ClaimRecord
) -> tuple[bool, list[str]]:
    """Does a verified counterexample's record account for every dossier assumption?

    Conservative by design: each recorded assumption must be *named* — its text (or
    its ``ASM-`` id) must occur in the claim's notes/statement, its cited artifacts, or
    the status-change reasons — otherwise it is reported as missing and the witness
    is not accepted for closure. A dossier with no recorded assumptions has nothing
    to check and passes vacuously (the empty list says so).
    """
    from opentorus.research.dossier import store

    pid = _norm_id(problem_id)
    assumptions = store.list_assumptions(ot_dir, pid)
    if not assumptions:
        return True, []
    haystack = _assumption_haystack(ot_dir, pid, claim)
    missing: list[str] = []
    for asm in assumptions:
        text = _squash(asm.statement).rstrip(".")
        if not text:
            continue
        if text in haystack or asm.id.lower() in haystack:
            continue
        missing.append(asm.statement)
    return not missing, missing


def _counterexample_route(
    ot_dir: Path, problem_id: str, ob: Obligation, explicit: str | None, details: list[str]
) -> ClosureVerdict | None:
    if ClosureMode.accepted_counterexample_certificate not in ob.closure_modes:
        return None
    from opentorus.research.dossier import store

    candidates = [_norm_id(explicit)] if explicit is not None else _cited_ids(ob)
    claims = {c.id.upper(): c for c in store.list_claims(ot_dir, problem_id)}
    for aid in candidates:
        claim = claims.get(aid)
        if claim is None:
            continue
        if claim.type != "COUNTEREXAMPLE_VERIFIED":
            details.append(f"{aid}: {claim.type} is not a verified counterexample")
            continue
        ok, missing = witness_satisfies_root_assumptions(ot_dir, problem_id, claim)
        if not ok:
            details.append(
                f"{aid}: verification record does not name the root assumption(s) "
                + "; ".join(repr(m) for m in missing)
                + " — record them in the claim notes or the witness check"
            )
            continue
        return ClosureVerdict(
            allowed=True,
            obligation_id=ob.obligation_id,
            mode=ClosureMode.accepted_counterexample_certificate,
            artifact_id=aid,
            reason=f"{aid} is COUNTEREXAMPLE_VERIFIED and its record names every root assumption",
            check_id=aid,
        )
    return None


def _proof_body(ot_dir: Path, problem_id: str, proof: ProofAttempt) -> str:
    from opentorus.research.dossier import store

    if not proof.body_path:
        return ""
    path = store.dossier_dir(ot_dir, problem_id) / proof.body_path
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def documented_gap_closure(body: str, gap_marker: str | None) -> bool | None:
    """Is the gap ``gap_marker`` (e.g. ``GAP-1``) accounted for as *closed* in ``body``?

    ``True``: the marker occurs only in closed contexts (a "gaps closed" section or
    ``[GAP-n] closed/handled/... ``); ``False``: the marker is gone or still open;
    ``None``: the marker cannot be tracked (no ``GAP-n`` key). Uses the same closed-
    context rules as ``nl_proof.explicit_gaps`` so the two never disagree.
    """
    from opentorus.research.dossier.nl_proof import explicit_gaps, gap_marker_key

    key = gap_marker_key(gap_marker or "")
    if key is None:
        return None
    all_keys = {gap_marker_key(m.group(0)) for m in _GAP_BRACKET.finditer(body)}
    open_keys = {gap_marker_key(g) for g in explicit_gaps(gaps=[], body=body)}
    return key in all_keys and key not in open_keys


def _referee_route(
    ot_dir: Path, problem_id: str, ob: Obligation, explicit: str | None, details: list[str]
) -> ClosureVerdict | None:
    if ClosureMode.nl_proof_referee_accepted not in ob.closure_modes:
        return None
    from opentorus.research.dossier import store
    from opentorus.research.dossier.nl_proof import explicit_gaps

    candidates = [_norm_id(explicit)] if explicit is not None else _cited_ids(ob)
    attempts = {p.id.upper(): p for p in store.list_proof_attempts(ot_dir, problem_id)}
    claim_ids = _named_claim_ids(ot_dir, problem_id, ob)
    for aid in candidates:
        proof = attempts.get(aid)
        if proof is None:
            continue
        if proof.scope != "primary":
            details.append(f"{proof.id}: exploration-scope attempt is not the dossier answer")
            continue
        linked = {_norm_id(c) for c in proof.claim_links}
        if not claim_ids:
            details.append(
                f"{proof.id}: the obligation names no claim (no CLAIM- dependency and no "
                "primary claim), so no proof can be tied to it"
            )
            continue
        if not linked & set(claim_ids):
            details.append(
                f"{proof.id}: claim_links {sorted(linked) or '[]'} do not name the "
                f"obligation's claim ({', '.join(claim_ids)})"
            )
            continue
        body = _proof_body(ot_dir, problem_id, proof)
        gaps = explicit_gaps(gaps=list(proof.gaps), body=body)
        if gaps:
            details.append(f"{proof.id}: open gaps remain ({len(gaps)})")
            continue
        if ob.gap_marker and ob.source_proof_id and _norm_id(ob.source_proof_id) == aid:
            documented = documented_gap_closure(body, ob.gap_marker)
            if documented is False:
                details.append(
                    f"{proof.id}: gap {ob.gap_marker} is no longer marked but its closure is "
                    "not documented — deleting a [GAP-n] marker does not close the "
                    "obligation; write '[GAP-n] closed: ...' or a 'Gaps closed' section"
                )
                continue
        try:
            from opentorus.research.dossier.referee import referee_review

            report = referee_review(ot_dir, problem_id, persist=False)
        except Exception as exc:  # noqa: BLE001 - the referee must never break a run
            details.append(f"{proof.id}: referee unavailable ({exc})")
            continue
        if report.verdict != "pass":
            details.append(f"{proof.id}: referee verdict {report.verdict}")
            continue
        refuted = [
            a.claim_id
            for a in report.assessments
            if a.claim_id.upper() in claim_ids and a.classification == "refuted"
        ]
        if refuted:
            details.append(f"{proof.id}: referee classifies {', '.join(refuted)} as refuted")
            continue
        return ClosureVerdict(
            allowed=True,
            obligation_id=ob.obligation_id,
            mode=ClosureMode.nl_proof_referee_accepted,
            artifact_id=proof.id,
            reason="referee pass on a gap-free primary proof attempt (not machine-checked)",
            check_id=report.id or "referee",
        )
    return None


def _literature_route(
    ot_dir: Path, problem_id: str, ob: Obligation, explicit: str | None, details: list[str]
) -> ClosureVerdict | None:
    if ClosureMode.accepted_literature_theorem not in ob.closure_modes:
        return None
    from opentorus.research.theorems import store as thm_store

    candidates = [_norm_id(explicit)] if explicit is not None else _cited_ids(ob)
    targets = {ob.obligation_id.upper(), *_named_claim_ids(ot_dir, problem_id, ob)}
    for aid in candidates:
        if not _THMREF_ID.match(aid):
            continue
        ref = thm_store.get_reference(ot_dir, aid)
        if ref is None:
            details.append(f"{aid}: no such theorem reference")
            continue
        if ref.review_status != "accepted":
            details.append(f"{aid}: review status {ref.review_status} (needs accepted)")
            continue
        checks = [
            c
            for c in thm_store.list_applicability_checks(ot_dir, ref_id=aid)
            if c.problem_id.upper() == problem_id and str(c.result) == "accepted"
        ]
        if not checks:
            details.append(f"{aid}: no accepted applicability check for {problem_id}")
            continue
        targeted = [c for c in checks if c.target_id and _norm_id(c.target_id) in targets]
        if not targeted:
            details.append(
                f"{aid}: accepted applicability check(s) target "
                f"{sorted({str(c.target_id) for c in checks})}, not the obligation or its "
                f"claim ({', '.join(sorted(targets))})"
            )
            continue
        return ClosureVerdict(
            allowed=True,
            obligation_id=ob.obligation_id,
            mode=ClosureMode.accepted_literature_theorem,
            artifact_id=aid,
            reason="accepted reference with an accepted applicability check for this target",
            check_id=targeted[-1].id or None,
        )
    return None


def can_close_obligation(
    ot_dir: Path,
    problem_id: str,
    obligation: Obligation,
    *,
    artifact_id: str | None = None,
) -> ClosureVerdict:
    """May ``obligation`` close — and with which artifact and mode?

    Routes are tried in a fixed order (certificate, counterexample, referee,
    literature); the first that finds an accepted artifact wins. With
    ``artifact_id`` only that artifact is considered (a "can *this* close it?"
    question); otherwise the obligation's own citations are. The verdict carries every
    reason that was checked so a refusal is explainable.
    """
    pid = _norm_id(problem_id)
    details: list[str] = []
    if obligation.status not in (ObligationStatus.open, ObligationStatus.in_progress):
        return ClosureVerdict(
            allowed=False,
            obligation_id=obligation.obligation_id,
            reason=f"{obligation.obligation_id} is {obligation.status.value}; nothing to close",
        )
    if not obligation.closure_modes:
        return ClosureVerdict(
            allowed=False,
            obligation_id=obligation.obligation_id,
            reason=f"{obligation.obligation_id} lists no closure modes",
        )
    explicit = artifact_id.strip() if artifact_id else None
    for route in (_certificate_route, _counterexample_route, _referee_route, _literature_route):
        verdict = route(ot_dir, pid, obligation, explicit, details)
        if verdict is not None:
            verdict.details = list(details)
            return verdict
    return ClosureVerdict(
        allowed=False,
        obligation_id=obligation.obligation_id,
        reason=(
            f"{obligation.obligation_id}: stays open (no accepted artifact backs a closure)"
            + (" — " + "; ".join(details) if details else "")
        ),
        details=details,
    )


# --------------------------------------------------------------------------------------
# Root status and structural settlement checks
# --------------------------------------------------------------------------------------


def root_status(ot_dir: Path, problem_id: str) -> RootStatusView:
    """The problem's status as the tree shows it — from dossier artifacts only.

    Delegates to ``campaign.facts.root_math_status`` (``scope.classify_outcome`` +
    ``status_gate.derive_status``); a completed campaign, a closed obligation or a
    finished branch never enter this. Never raises: an unreadable dossier yields
    ``STATUS_UNCERTAIN`` with the error as rationale.
    """
    from opentorus.campaign.facts import root_math_status

    facts = root_math_status(ot_dir, problem_id)
    derived_from = [
        "research.dossier.scope.classify_outcome",
        "research.dossier.status_gate.derive_status",
    ]
    if facts.primary_claim_id:
        derived_from.append(f"primary claim {facts.primary_claim_id}")
    return RootStatusView(
        label=facts.label,
        rationale=facts.rationale or facts.report_rationale,
        report_status=facts.report_status,
        derived_from=derived_from,
    )


_NON_SETTLING: frozenset[RootRelation] = frozenset(
    {RootRelation.special_case, RootRelation.relaxation}
)
_ROOT_CLOSING_EDGES: frozenset[str] = frozenset({"closes", "verifies", "refutes"})
# Status strings that would claim the *root* is settled; matched case-insensitively.
_SETTLING_STATUSES: frozenset[str] = frozenset(
    {
        "settles-root",
        "root-settled",
        "closes-root",
        "root-closed",
        "proves-root",
        "refutes-root",
        "general_conjecture_proved",
        "general_conjecture_refuted",
    }
)


def special_case_marks_root(graph: ProofGraph) -> list[ValidationIssue]:
    """Issues for special-case/relaxation nodes presented as settling the root.

    Error: an edge ``closes`` / ``verifies`` / ``refutes`` into the root from such a
    node, a node status that claims the root is settled, or ``extra.settles_root``.
    Warning: a *closed* special-case/relaxation obligation attached directly to the
    root (its closure is real, but the reader must not take it for the root's).
    """
    issues: list[ValidationIssue] = []
    root = graph.root_id
    for edge in graph.edges:
        if edge.target_id != root or edge.relation not in _ROOT_CLOSING_EDGES:
            continue
        src = graph.nodes.get(edge.source_id)
        if src is not None and src.root_relation in _NON_SETTLING:
            issues.append(
                ValidationIssue(
                    code="special_case_root_closing",
                    node_ids=[src.node_id, root],
                    message=(
                        f"{src.node_id} ({src.root_relation.value}) has a '{edge.relation}' "
                        f"edge into the root: a {src.root_relation.value} cannot settle the root"
                    ),
                    severity="error",
                )
            )
    for node in graph.nodes.values():
        if node.root_relation not in _NON_SETTLING or node.node_id == root:
            continue
        if node.status.lower() in _SETTLING_STATUSES or bool(node.extra.get("settles_root")):
            issues.append(
                ValidationIssue(
                    code="special_case_root_closing",
                    node_ids=[node.node_id],
                    message=(
                        f"{node.node_id} ({node.root_relation.value}) claims to settle the root "
                        f"(status '{node.status}'): a {node.root_relation.value} never can"
                    ),
                    severity="error",
                )
            )
        elif (
            node.kind is ProofNodeKind.obligation
            and node.status == ObligationStatus.closed.value
            and root in node.parents
        ):
            issues.append(
                ValidationIssue(
                    code="special_case_root_closing",
                    node_ids=[node.node_id],
                    message=(
                        f"{node.node_id} is a closed {node.root_relation.value} obligation "
                        "attached directly to the root; its closure is not the root's"
                    ),
                    severity="warning",
                )
            )
    return issues


__all__ = [
    "BACKEND_CLOSURE_MODES",
    "CERTIFICATE_MODES",
    "RELATION_CAN_SETTLE",
    "ClosureVerdict",
    "SettlementVerdict",
    "can_close_obligation",
    "documented_gap_closure",
    "ledger_proof_verdict",
    "relation_settlement",
    "root_status",
    "special_case_marks_root",
    "witness_satisfies_root_assumptions",
]
