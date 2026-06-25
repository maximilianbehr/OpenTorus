"""Honest report generation for a problem dossier (Milestone M1, Phase 9).

The report is assembled only from local artifacts and uses status-accurate
language: a conjecture is a conjecture, a sketch is a sketch, numerical evidence
is evidence. It never silently upgrades evidence into proof. After building, the
report is linted by the artifact-aware honesty linter and any remaining warnings
are surfaced in a dedicated section.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.dossier import store
from opentorus.research.dossier.honesty import ReportIssue, lint_report
from opentorus.research.dossier.models import ClaimRecord, ProblemDossier
from opentorus.research.dossier.validation import evidence_can_verify

_STATUS_LABEL = {
    "open": "open",
    "refuted": "refuted (a counterexample is verified)",
    "solved_externally": "solved externally (cite the source)",
    "partially_resolved": "partially resolved",
    "unknown": "unknown",
}

_CLAIM_TYPE_LABEL = {
    "OBSERVATION": "observation",
    "CLAIM": "claim",
    "CONJECTURE": "conjecture (open, unproven)",
    "LEMMA_ATTEMPT": "lemma attempt",
    "THEOREM": "theorem (referenced/verified)",
    "COUNTEREXAMPLE_CANDIDATE": "counterexample candidate (UNVERIFIED)",
    "COUNTEREXAMPLE_VERIFIED": "counterexample (verified)",
    "REFERENCE_FACT": "reference fact",
    "FORMAL_PROOF_VERIFIED": "formally verified",
    "FORMAL_PROOF_FAILED": "formal proof attempt (failed)",
    "HEURISTIC": "heuristic (plausible, NOT proven)",
    "EXPERIMENTAL_OBSERVATION": "experimental observation (evidence, not proof)",
    "OPEN_GAP": "open gap (unresolved sub-question)",
}


def honesty_context(ot_dir: Path, problem_id: str) -> tuple[bool, bool, bool]:
    """Return (has_verified_proof, has_reference, has_supported_theorem) for the dossier.

    These three booleans license, respectively: strong proof-claim language, "it is
    known that …" knowledge claims, and result-assertion language ("we proved",
    "provably", "the problem is solved").
    """
    claims = store.list_claims(ot_dir, problem_id)
    proofs = store.list_proof_attempts(ot_dir, problem_id)
    has_verified_proof = any(p.status == "verified" for p in proofs) or any(
        c.status == "formally_verified" or c.type == "FORMAL_PROOF_VERIFIED" for c in claims
    )
    has_reference = (
        bool(store.list_known_results(ot_dir, problem_id))
        or bool(store.list_theorem_refs(ot_dir, problem_id))
        or any(p.paper_artifact for p in store.list_related_papers(ot_dir, problem_id))
        or any(c.type == "REFERENCE_FACT" for c in claims)
    )
    has_supported_theorem = any(
        c.type in ("THEOREM", "LEMMA_ATTEMPT")
        and c.status in ("supported", "verified", "formally_verified")
        for c in claims
    )
    return has_verified_proof, has_reference, has_supported_theorem


def _claim_honesty_context(
    claim: ClaimRecord,
    ev_list: list,
    proofs: list,  # noqa: ANN001
) -> tuple[bool, bool, bool]:
    """Per-claim honesty license (has_verified_proof, has_reference, has_supported_theorem).

    Scoped to a single claim so that a verified proof of one claim cannot license
    overclaiming language about a *different*, unproven claim — the licensing must
    be local to the claim whose wording is being checked.
    """
    has_proof = (
        claim.status == "formally_verified"
        or claim.type == "FORMAL_PROOF_VERIFIED"
        or any(e.direction == "supports" and evidence_can_verify(e.type) for e in ev_list)
        or any(p.status == "verified" and claim.id in (p.claim_links or []) for p in proofs)
    )
    has_ref = bool(claim.source_artifacts) or claim.type == "REFERENCE_FACT"
    has_thm = claim.type in ("THEOREM", "LEMMA_ATTEMPT") and claim.status in (
        "supported",
        "verified",
        "formally_verified",
    )
    return has_proof, has_ref, has_thm


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {x}" for x in items) if items else "- (none)"


def _settle_hint(claim: ClaimRecord) -> str | None:
    """A short, honest pointer to what would actually settle an open claim."""
    if claim.status in ("verified", "formally_verified"):
        return None
    if claim.type == "COUNTEREXAMPLE_CANDIDATE":
        return (
            "Link a verification artifact (a verified proof attempt or verification-grade "
            "evidence such as FORMAL_PROOF), then promote it — until then it stays a candidate."
        )
    if claim.type in ("CONJECTURE", "LEMMA_ATTEMPT", "CLAIM", "OBSERVATION"):
        return (
            "Open: experiments and sketches can support but never verify it; only an "
            "accepted proof artifact settles it."
        )
    if claim.type in ("HEURISTIC", "EXPERIMENTAL_OBSERVATION"):
        return (
            "Heuristic/empirical: it motivates a precise CONJECTURE or LEMMA_ATTEMPT but "
            "does not settle anything; a proof artifact would be needed to verify."
        )
    if claim.type == "OPEN_GAP":
        return "Unresolved sub-question: close it with a lemma, an experiment, or a citation."
    return None


def _evidence_badge(ev_list: list) -> str:  # noqa: ANN001
    """A compact strength summary: supporting vs contradicting, verification-grade flag."""
    supporting = [e for e in ev_list if e.direction == "supports"]
    contradicting = [e for e in ev_list if e.direction == "contradicts"]
    verification = [e for e in supporting if evidence_can_verify(e.type)]
    parts = [f"{len(supporting)} supporting", f"{len(contradicting)} contradicting"]
    if verification:
        parts.append(f"{len(verification)} verification-grade")
    return ", ".join(parts)


def _claim_block(  # noqa: ANN001
    ot_dir: str,
    problem_id: str,
    claim: ClaimRecord,
    evidence_by_claim,
    *,
    has_proof: bool = False,
    has_ref: bool = False,
    has_thm: bool = False,
) -> str:
    type_label = _CLAIM_TYPE_LABEL.get(claim.type, claim.type)
    ev_list = evidence_by_claim.get(claim.id, [])
    lines = [
        f"### {claim.id} — {type_label}",
        "",
        f"- **Statement:** {claim.statement}",
        f"- **Type:** {claim.type}",
        f"- **Status:** {claim.status}",
        f"- **Evidence strength:** {_evidence_badge(ev_list)}",
    ]
    if ev_list:
        lines.append("- **Evidence:**")
        for ev in ev_list:
            grade = "" if evidence_can_verify(ev.type) else " (support only — never a proof)"
            lines.append(f"  - {ev.id} [{ev.type}, {ev.direction}]{grade}: {ev.summary}")
    else:
        lines.append("- **Evidence:** (none linked)")
    limitations: list[str] = []
    for ev in ev_list:
        limitations.extend(ev.limitations)
    if limitations:
        lines.append("- **Limitations:**")
        lines.extend(f"  - {x}" for x in limitations)
    hint = _settle_hint(claim)
    if hint:
        lines.append(f"- **To settle:** {hint}")
    # Inline honesty check on the claim's own wording (statement + notes).
    claim_text = f"{claim.statement}\n{claim.notes or ''}"
    claim_issues = lint_report(
        claim_text,
        has_verified_proof=has_proof,
        has_reference=has_ref,
        has_supported_theorem=has_thm,
    )
    if claim_issues:
        flagged = "; ".join(f"'{i.phrase}' — {i.suggestion}" for i in claim_issues)
        lines.append(f"- ⚠ **Honesty:** {flagged}")
    lines.append("")
    return "\n".join(lines)


def _executive_summary(  # noqa: ANN001
    dossier: ProblemDossier,
    claims: list[ClaimRecord],
    evidence_by_claim,
    proofs,
    experiments,
    failed,
) -> str:
    """An honest, scannable TL;DR built only from artifact counts and statuses.

    Worded to pass the honesty linter: evidence supports, it never proves.
    """
    by_type: dict[str, int] = {}
    for c in claims:
        by_type[c.type] = by_type.get(c.type, 0) + 1
    verified = [c for c in claims if c.status in ("verified", "formally_verified")]
    contradicted = [c for c in claims if c.status == "contradicted"]
    verified_proofs = [p for p in proofs if p.status == "verified"]
    sketches = [p for p in proofs if p.status != "verified"]

    # Strongest support: the claim with the most supporting evidence links.
    strongest = None
    best = 0
    for c in claims:
        support = sum(1 for e in evidence_by_claim.get(c.id, []) if e.direction == "supports")
        if support > best:
            best, strongest = support, c

    lines = ["## Summary\n"]
    lines.append(
        f"**Status:** {dossier.status} — {_STATUS_LABEL.get(dossier.status, dossier.status)}.\n"
    )
    type_breakdown = (
        ", ".join(f"{n} {t}" for t, n in sorted(by_type.items())) if by_type else "none yet"
    )
    bullets = [
        f"**Claims:** {len(claims)} ({type_breakdown}).",
        (
            f"**Verified results:** {len(verified)}."
            if verified
            else "**Verified results:** none — nothing has reached a verified status."
        ),
        f"**Experiments:** {len(experiments)} reproducible run(s).",
        f"**Proof attempts:** {len(verified_proofs)} verified, {len(sketches)} sketch(es).",
        f"**Failed attempts:** {len(failed)} recorded.",
    ]
    if contradicted:
        ids = ", ".join(c.id for c in contradicted)
        bullets.append(
            f"**Contradictions:** {len(contradicted)} claim(s) have contradicting "
            f"evidence ({ids}); review."
        )
    if strongest is not None:
        bullets.append(
            f"**Strongest support:** {strongest.id} has the most supporting evidence "
            f"({best} item(s))."
        )
    lines.append(_bullets(bullets))
    lines.append(
        "\n_Evidence here supports claims but does not verify them; only a verified proof "
        "or verification artifact settles a claim._\n"
    )
    return "\n".join(lines)


def _epistemic_map(claims: list[ClaimRecord], evidence_by_claim, proofs) -> str:  # noqa: ANN001
    """A Mermaid graph of claims, their evidence, and proof links.

    Node labels use controlled vocabulary (id / type / status) only — never free
    statement text — so the map cannot smuggle overclaiming language past the linter.
    """
    if not claims:
        return ""
    out = ["## Epistemic Map\n", "```mermaid", "graph LR"]
    claim_ids = {c.id for c in claims}
    for c in claims:
        out.append(f'  {c.id}["{c.id}<br/>{c.type}<br/>{c.status}"]')
    for c in claims:
        for ev in evidence_by_claim.get(c.id, []):
            out.append(f"  {ev.id} -->|{ev.direction}| {c.id}")
    for p in proofs:
        rel = "verifies" if p.status == "verified" else "sketch"
        arrow = "-->" if p.status == "verified" else "-.->"
        for cid in getattr(p, "claim_links", []) or []:
            if cid in claim_ids:
                out.append(f"  {p.id} {arrow}|{rel}| {cid}")
    out.append("```\n")
    return "\n".join(out)


def _proof_sketch_block(ot_dir: Path, problem_id: str, proof) -> str:  # noqa: ANN001
    """Render a full NL proof sketch for report readers (not just metadata)."""
    from opentorus.research.dossier.nl_proof import explicit_gaps

    scope = getattr(proof, "scope", "primary") or "primary"
    # Read the body first so the reported gaps reflect markers actually present in
    # the prose. A [GAP-n] / [GAP-n: …] marker in the text must be reported even
    # if it was never captured into ``proof.gaps`` at write time (e.g. older
    # records, or markers the write-time extractor missed). Reconciling here keeps
    # the report honest: a body full of gaps can never render with "no gaps".
    body_text = ""
    body_note = ""
    if proof.body_path:
        body_file = store.dossier_dir(ot_dir, problem_id) / proof.body_path
        if body_file.is_file():
            body_text = body_file.read_text(encoding="utf-8").strip()
        else:
            body_note = f"_Body file missing: {proof.body_path}_"
    else:
        body_note = "_No body file recorded._"

    gaps = explicit_gaps(gaps=list(proof.gaps or []), body=body_text)
    lines = [
        f"#### {proof.id} — {proof.title or 'Proof sketch'}",
        "",
        f"- **Status:** {proof.status} (NOT machine-checked)",
        f"- **Scope:** {scope}"
        + (" — _speculative connection, NOT the dossier answer_" if scope == "exploration" else ""),
    ]
    if gaps:
        lines.append(f"- **Gaps recorded:** {len(gaps)}")
        for gap in gaps:
            lines.append(f"  - {gap}")
    lines.append("")
    lines.append(body_text or body_note)
    lines.append("")
    return "\n".join(lines)


def _status_changelog(ot_dir: Path, problem_id: str) -> str:
    """Render the epistemic status-change log (how beliefs evolved over time)."""
    changes = store.list_status_changes(ot_dir, problem_id)
    lines = ["## Status Changelog\n"]
    if not changes:
        lines.append("- (no status changes recorded yet)")
        return "\n".join(lines) + "\n"
    rows = []
    for ch in changes:
        when = ch.created_at.date().isoformat()
        via = f" via {ch.artifact}" if ch.artifact else ""
        reason = f" — {ch.reason}" if ch.reason else ""
        rows.append(f"{when} · {ch.claim_id}: {ch.from_status} → {ch.to_status}{via}{reason}")
    lines.append(_bullets(rows))
    return "\n".join(lines) + "\n"


def _next_actions(
    ot_dir: Path, problem_id: str, dossier: ProblemDossier, claims: list[ClaimRecord]
) -> list[str]:
    actions: list[str] = []
    approaches = store.list_approaches(ot_dir, problem_id)
    if not approaches:
        actions.append(
            f"Start an attack: `opentorus problem attack {problem_id} --strategy literature_map`."
        )
    has_conjecture = any(c.type == "CONJECTURE" for c in claims)
    has_evidence = any(c.evidence_links for c in claims)
    if has_conjecture and not has_evidence:
        actions.append(
            "Gather evidence: run a numerical_experiment or counterexample_search and "
            "link the result to the conjecture."
        )
    candidates = [c for c in claims if c.type == "COUNTEREXAMPLE_CANDIDATE"]
    if candidates:
        actions.append(
            f"Verify or refute the {len(candidates)} counterexample candidate(s) with an "
            "explicit verification artifact before calling them counterexamples."
        )
    sketches = [p for p in store.list_proof_attempts(ot_dir, problem_id) if p.status != "verified"]
    if sketches:
        actions.append(
            "Close the gaps in proof sketches or pursue a formalization_attempt toward a "
            "machine-checked proof."
        )
    if dossier.formalization_status == "informal":
        actions.append(
            "Consider a formalization_attempt to make definitions proof-assistant ready."
        )
    if not actions:
        actions.append("Review claims and decide whether the status can be honestly updated.")
    return actions


def _latest_referee_verdict(ot_dir: Path, problem_id: str) -> str:
    """Return a short referee-verdict line for the header, or a 'not run' note."""
    try:
        from opentorus.research.dossier.referee import latest_referee
    except Exception:  # noqa: BLE001 - referee is optional; never break the report
        return "not run"
    rep = latest_referee(ot_dir, problem_id)
    if rep is None:
        return "not run"
    return f"{rep.verdict} ({rep.id})"


def _status_header(
    ot_dir: Path,
    problem_id: str,
    dossier: ProblemDossier,
    claims: list[ClaimRecord],
    proofs: list,  # noqa: ANN001
    experiments: list,  # noqa: ANN001
) -> str:
    """A scannable, machine-derived header: status + what actually backs it.

    Built only from artifact counts/statuses and a deterministic status gate, so it
    cannot overstate the work. It is the first thing a reader sees.
    """
    from opentorus.research.dossier.status_gate import derive_status

    verdict = derive_status(ot_dir, problem_id)
    verified_theorems = [
        c for c in claims if c.type == "THEOREM" and c.status in ("verified", "formally_verified")
    ]
    heuristics = [c for c in claims if c.type in ("HEURISTIC", "EXPERIMENTAL_OBSERVATION")]
    sketches = [p for p in proofs if p.status != "verified"]
    ran = [e for e in experiments if e.status in ("succeeded", "failed", "inconclusive")]
    planned = [e for e in experiments if e.status == "planned"]
    open_gaps = [c for c in claims if c.type == "OPEN_GAP"]
    gap_total = verdict.open_gap_count

    if verified_theorems:
        thm_line = ", ".join(c.id for c in verified_theorems)
    else:
        thm_line = "none — no theorem has reached a verified status"

    heur_line = (
        f"{len(sketches)} proof sketch(es), {len(heuristics)} heuristic/empirical claim(s)"
        if (sketches or heuristics)
        else "none recorded"
    )
    exp_line = f"{len(ran)} executed, {len(planned)} planned"
    if gap_total:
        gap_line = f"{gap_total} recorded ({len(open_gaps)} OPEN_GAP claim(s) + sketch gaps)"
    else:
        gap_line = "none explicitly recorded"

    next_actions = _next_actions(ot_dir, problem_id, dossier, claims)
    next_step = next_actions[0] if next_actions else "Review claims and update status."

    lines = [
        "## Status Summary\n",
        f"- **Status:** {verdict.status} — {verdict.rationale}",
        f"- **Verified theorems:** {thm_line}",
        f"- **Heuristics / sketches:** {heur_line}",
        f"- **Experiments run:** {exp_line}",
        f"- **Main gaps:** {gap_line}",
        f"- **Referee verdict:** {_latest_referee_verdict(ot_dir, problem_id)}",
        f"- **Recommended next step:** {next_step}",
        "",
    ]
    return "\n".join(lines)


def build_report(ot_dir: Path, problem_id: str, *, harvest_session: bool = True) -> str:
    """Assemble report.md from local artifacts and persist it."""
    if harvest_session:
        from opentorus.agent.prove_harvest import harvest_prove_session

        harvest_prove_session(ot_dir, problem_id, create_proof=True)
    dossier = store.require_dossier(ot_dir, problem_id)
    statement = store.read_statement(ot_dir, problem_id).strip()
    definitions = store.list_definitions(ot_dir, problem_id)
    assumptions = store.list_assumptions(ot_dir, problem_id)
    known = store.list_known_results(ot_dir, problem_id)
    related = store.list_related_papers(ot_dir, problem_id)
    claims = store.list_claims(ot_dir, problem_id)
    experiments = _safe_experiments(ot_dir, problem_id)
    proofs = store.list_proof_attempts(ot_dir, problem_id)
    failed = store.list_failed_attempts(ot_dir, problem_id)

    evidence_by_claim: dict[str, list] = {}
    for ev in store.list_evidence(ot_dir, problem_id):
        evidence_by_claim.setdefault(ev.claim_id, []).append(ev)

    # Honesty context is needed early so per-claim inline checks can use it.
    has_proof, has_ref, has_thm = honesty_context(ot_dir, problem_id)

    parts: list[str] = []
    parts.append(f"# {dossier.id} — {dossier.title}\n")
    parts.append("> Auto-generated from local artifacts. Evidence is not proof.\n")

    parts.append(_status_header(ot_dir, problem_id, dossier, claims, proofs, experiments))

    parts.append(
        _executive_summary(dossier, claims, evidence_by_claim, proofs, experiments, failed)
    )

    parts.append("## Problem\n")
    body = statement
    if body.startswith("#"):
        body = "\n".join(line for line in body.splitlines() if not line.startswith("#")).strip()
    parts.append(body or "_No statement recorded._")
    parts.append("")
    parts.append(f"- **id:** {dossier.id}")
    parts.append(f"- **domain:** {dossier.domain or '(unspecified)'}")
    parts.append(f"- **formalization:** {dossier.formalization_status}")
    if dossier.tags:
        parts.append(f"- **tags:** {', '.join(dossier.tags)}")
    if dossier.known_equivalent_forms:
        parts.append(f"- **equivalent forms:** {', '.join(dossier.known_equivalent_forms)}")
    if dossier.known_obstructions:
        parts.append(f"- **known obstructions:** {', '.join(dossier.known_obstructions)}")
    parts.append("")

    parts.append("## Current Status\n")
    parts.append(f"**{dossier.status}** — {_STATUS_LABEL.get(dossier.status, dossier.status)}.")
    if dossier.status == "open":
        parts.append(
            "\nThis problem is open. Nothing below should be read as a solution; claims "
            "carry their own epistemic status."
        )
    parts.append("")

    parts.append("## Definitions and Assumptions\n")
    parts.append("### Definitions\n")
    parts.append(_bullets([f"{d.id}: **{d.term}** — {d.definition}" for d in definitions]))
    parts.append("\n### Assumptions\n")
    parts.append(
        _bullets(
            [
                f"{a.id}: {a.statement}" + (f" ({a.rationale})" if a.rationale else "")
                for a in assumptions
            ]
        )
    )
    parts.append("")

    parts.append("## Known Results\n")
    parts.append("_Only results backed by a local source artifact._\n")
    parts.append(
        _bullets(
            [f"{k.id}: {k.statement} [sources: {', '.join(k.source_artifacts)}]" for k in known]
        )
    )
    if related:
        parts.append("\n### Related papers\n")
        parts.append(
            _bullets(
                [
                    f"{r.id}: {r.title or '(untitled)'}"
                    + (
                        f" → {r.paper_artifact}"
                        if r.paper_artifact
                        else " (no local PAPER-* artifact)"
                    )
                    for r in related
                ]
            )
        )
    parts.append("")

    parts.append("## Claims and Evidence\n")
    if claims:
        for claim in claims:
            # Per-claim licensing: a verified proof of another claim must not license
            # overclaiming language in this claim's block.
            c_proof, c_ref, c_thm = _claim_honesty_context(
                claim, evidence_by_claim.get(claim.id, []), proofs
            )
            parts.append(
                _claim_block(
                    str(ot_dir),
                    problem_id,
                    claim,
                    evidence_by_claim,
                    has_proof=c_proof,
                    has_ref=c_ref,
                    has_thm=c_thm,
                )
            )
    else:
        parts.append("_No claims recorded yet._\n")

    epistemic_map = _epistemic_map(claims, evidence_by_claim, proofs)
    if epistemic_map:
        parts.append(epistemic_map)

    parts.append("## Experiments\n")
    parts.append("_Reproducible runs. Each is evidence, not proof — cite the EXP-* id._\n")
    if experiments:
        parts.append(
            _bullets(
                [
                    f"{e.experiment_id} [{e.status}]: {e.title} — `{e.command}` "
                    f"(seed={e.random_seed}); {e.result_summary or 'not run yet'}"
                    for e in experiments
                ]
            )
        )
    else:
        parts.append("- (none)")
    parts.append("")

    parts.append("## Proof Attempts\n")
    verified = [p for p in proofs if p.status == "verified"]
    sketches = [p for p in proofs if p.status != "verified"]
    parts.append("### Verified proofs\n")
    parts.append(
        _bullets(
            [
                f"{p.id}: {p.title} — verified by "
                f"{p.verifier or 'verifier'} ({p.verification_artifact})"
                for p in verified
            ]
        )
    )
    parts.append("\n### Proof sketches (NOT machine-checked)\n")
    primary_sketches = [p for p in sketches if getattr(p, "scope", "primary") != "exploration"]
    exploration_sketches = [p for p in sketches if getattr(p, "scope", "primary") == "exploration"]
    if primary_sketches:
        parts.append(
            "#### Primary answer (dossier problem)\n\n"
            "_Full natural-language argument below — cite the PROOF-* id; "
            "gaps mean the sketch is incomplete._\n"
        )
        for proof in primary_sketches:
            parts.append(_proof_sketch_block(ot_dir, problem_id, proof))
    else:
        parts.append("#### Primary answer (dossier problem)\n\n- (none)\n")
    if exploration_sketches:
        parts.append(
            "\n#### Exploratory connections (hypothesis — NOT the dossier answer)\n\n"
            "_Side threads the agent explored; verify the bridge before treating as relevant._\n"
        )
        for proof in exploration_sketches:
            parts.append(_proof_sketch_block(ot_dir, problem_id, proof))
    elif not primary_sketches:
        parts.append("")

    parts.append("## Failed Attempts\n")
    parts.append("_First-class artifacts. Do not retry these without a new assumption._\n")
    if failed:
        parts.append(
            _bullets(
                [
                    f"{f.id}: {f.attempted_method} — {f.reason_failed}"
                    + (" [reusable obstruction]" if f.reusable_obstruction else "")
                    for f in failed
                ]
            )
        )
    else:
        parts.append("- (none)")
    parts.append("")

    parts.append("## Counterexample Search\n")
    candidates = [c for c in claims if c.type == "COUNTEREXAMPLE_CANDIDATE"]
    verified_cx = [c for c in claims if c.type == "COUNTEREXAMPLE_VERIFIED"]
    parts.append(
        _bullets(
            [f"{c.id} [candidate, UNVERIFIED]: {c.statement}" for c in candidates]
            + [f"{c.id} [VERIFIED]: {c.statement}" for c in verified_cx]
        )
    )
    parts.append("")

    parts.append(_status_changelog(ot_dir, problem_id))

    parts.append("## Next Actions\n")
    parts.append(_bullets(_next_actions(ot_dir, problem_id, dossier, claims)))
    parts.append("")

    report_text = "\n".join(parts)

    # Lint the report we just generated and append any remaining warnings.
    issues = lint_report(
        report_text,
        has_verified_proof=has_proof,
        has_reference=has_ref,
        has_supported_theorem=has_thm,
    )
    parts.append("## Honesty Warnings\n")
    if issues:
        parts.append(
            _bullets(
                [f"line {i.line} [{i.kind.value}] '{i.phrase}': {i.suggestion}" for i in issues]
            )
        )
    else:
        parts.append("- None. Report language matches the dossier's artifacts.")
    parts.append("")

    final = "\n".join(parts)
    (store.dossier_dir(ot_dir, problem_id) / "report.md").write_text(final, encoding="utf-8")
    return final


def _safe_experiments(ot_dir: Path, problem_id: str):  # noqa: ANN201
    from opentorus.research.dossier.experiments import list_experiments

    return list_experiments(ot_dir, problem_id)


def lint_dossier_report(ot_dir: Path, problem_id: str) -> list[ReportIssue]:
    """Lint the persisted report.md against the dossier's artifacts."""
    store.require_dossier(ot_dir, problem_id)
    report_path = store.dossier_dir(ot_dir, problem_id) / "report.md"
    text = report_path.read_text("utf-8") if report_path.is_file() else ""
    # Don't re-lint the report's own "Honesty Warnings" section: it quotes the very
    # phrases the linter flags (e.g. 'is proved'), which would re-trigger and report
    # phantom warnings on the warning text itself. That section is the linter's output,
    # not dossier prose.
    marker = text.rfind("## Honesty Warnings")
    if marker != -1:
        text = text[:marker]
    has_proof, has_ref, has_thm = honesty_context(ot_dir, problem_id)
    return lint_report(
        text,
        has_verified_proof=has_proof,
        has_reference=has_ref,
        has_supported_theorem=has_thm,
    )
