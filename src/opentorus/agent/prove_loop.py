"""Focused agent loop for natural-language proof work on a problem dossier."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from opentorus.config import Config
from opentorus.providers.base import BaseProvider


def bootstrap_literature_tool(root: Path, problem_id: str) -> tuple[str, dict]:
    """First tool when the literature phase model returns chat-only."""
    pid = problem_id.strip().upper()
    statement = f".opentorus/problems/{pid}/statement.md"
    if (root / statement).is_file():
        return "read_file", {"path": statement}
    return "paper_list", {}


@dataclass
class ProveOutcome:
    problem_id: str
    answer: str
    proof_ids: list[str]
    gap_count: int
    lint_issues: int
    tool_calls: int
    papers_added: int = 0
    papers_read: int = 0
    unread_papers: list[str] | None = None
    literature_tools_used: bool = False
    literature_complete: bool = True
    literature_detail: str = ""
    proof_warnings: list[str] | None = None
    harvested_experiments: list[str] | None = None
    harvested_claims: list[str] | None = None
    gaps_remaining: int = 0
    gap_fill_exhausted: bool = False
    referee_verdict: str | None = None


def latest_proof_gap_count(ot_dir: Path, problem_id: str) -> int:
    """Return the number of recorded gaps on the latest proof attempt."""
    from opentorus.research.dossier import store

    proofs = store.list_proof_attempts(ot_dir, problem_id.strip().upper())
    if not proofs:
        return 0
    return len(proofs[-1].gaps)


def has_primary_proof(ot_dir: Path, problem_id: str) -> bool:
    """True if a primary (non-exploration) proof attempt exists for this problem.

    Distinguishes "no proof written for the target dossier yet" (NOT done) from
    "a proof with zero gaps" (done) — both of which give ``latest_proof_gap_count
    == 0`` and would otherwise be conflated.
    """
    from opentorus.research.dossier import store

    proofs = store.list_proof_attempts(ot_dir, problem_id.strip().upper())
    return any(getattr(p, "scope", "primary") != "exploration" for p in proofs)


def build_proof_gap_recovery_hint(ot_dir: Path, problem_id: str) -> str:
    """Recovery text when a primary proof exists but gaps remain."""
    from opentorus.research.dossier import store

    pid = problem_id.strip().upper()
    proofs = store.list_proof_attempts(ot_dir, pid)
    if not proofs:
        return "Continue with proof_write(scope=primary) for the dossier."
    latest = proofs[-1]
    gap_n = len(latest.gaps)
    if gap_n == 0:
        return "All recorded gaps are closed. Summarize briefly and stop."
    preview = "; ".join(latest.gaps[:3])
    if gap_n > 3:
        preview = f"{preview}; … (+{gap_n - 3} more)"
    hint = (
        f"{latest.id} still has {gap_n} recorded gap(s): {preview}. "
        "Read that proof and relevant PAPER-* notes; use paper_read, lit_search, "
        "paper_fetch, or exp_run as needed; then proof_write(scope=primary) to fill "
        "[GAP-n] or shrink the gap list. Do not stop with a chat-only summary."
    )
    if any(g.startswith(_REFEREE_GAP_PREFIX) for g in latest.gaps):
        hint += (
            f" The {_REFEREE_GAP_PREFIX} gap(s) were reopened by the hostile referee and "
            "reappear until resolved — deleting them does not close them. Fix the flagged "
            "language (e.g. replace 'we prove'/'provably' with 'we conjecture'/'a sketch "
            "argues') or record a supporting THEOREM/verification artifact, then rewrite the "
            "proof. Relabelling an unresolved step as an 'Open Problem' in prose does not "
            "close its gap."
        )
    return _append_known_bad_citations(ot_dir, pid, hint)


# Referee-reopened gaps carry this marker so the loop can tell them from the model's own
# gaps (replace-on-recheck, keep model gaps) and the recovery hint can explain them.
_REFEREE_GAP_PREFIX = "[REFEREE]"


def referee_block_gaps(report) -> list[str]:  # noqa: ANN001 - RefereeReport (lazy import)
    """Turn a *blocking* referee verdict into actionable, deduped proof gaps.

    Only the hard, blocking findings become gaps: contradictions and overclaims that
    assert an unsupported result (``experiment_proof`` / ``proof_claim`` / ``result_claim``).
    Soft ``revise`` findings (e.g. a claim merely classified heuristic) are not reopened —
    presenting those honestly as conjecture is legitimate.
    """
    gaps: list[str] = []
    for c in report.contradictions:
        gaps.append(
            f"{_REFEREE_GAP_PREFIX} Contradiction flagged by the referee: {c} "
            "Reconcile this before the result can stand."
        )
    for o in report.overclaims:
        if o.kind not in ("experiment_proof", "proof_claim", "result_claim"):
            continue
        gaps.append(
            f"{_REFEREE_GAP_PREFIX} Unsupported {o.kind} at {o.location}: '{o.phrase}'. "
            f"{o.suggestion}"
        )
    seen: set[str] = set()
    out: list[str] = []
    for g in gaps:
        if g not in seen:
            seen.add(g)
            out.append(g)
    return out


def reopen_referee_gaps(ot_dir: Path, problem_id: str) -> list[str]:
    """Run the hostile referee on a gap-free proof; if it blocks, write its findings as gaps.

    Returns the referee-derived gaps now on the latest attempt — empty when the referee
    does not block, i.e. the gap-free proof is *honestly* complete. Idempotent: any prior
    referee-injected gaps are replaced with the current verdict's findings while the model's
    own gaps are preserved, so re-running on an unchanged proof reproduces the same list.
    """
    from opentorus.research.dossier import store
    from opentorus.research.dossier.models import utcnow
    from opentorus.research.dossier.referee import referee_review

    pid = problem_id.strip().upper()
    try:
        report = referee_review(ot_dir, pid, persist=False)
    except Exception:  # noqa: BLE001 - the referee must never break the prove run
        return []
    gaps = referee_block_gaps(report) if report.verdict == "block" else []
    proofs = store.list_proof_attempts(ot_dir, pid)
    if not proofs:
        return gaps
    latest = proofs[-1]
    # Keep the model's own gaps; replace any prior referee-injected ones. When the referee
    # no longer blocks (gaps == []) this strips stale [REFEREE] gaps so the proof can settle.
    kept = [g for g in latest.gaps if not g.startswith(_REFEREE_GAP_PREFIX)]
    new_gaps = kept + gaps
    if new_gaps != latest.gaps:
        latest.gaps = new_gaps
        latest.updated_at = utcnow()
        store.rewrite_proof_attempts(ot_dir, pid, proofs)
    return gaps


def _append_known_bad_citations(ot_dir: Path, problem_id: str, text: str) -> str:
    """Re-inject the dossier's known-nonexistent citations so they survive compaction."""
    from opentorus.research.paper_citations import known_bad_citations

    bad = known_bad_citations(ot_dir, problem_id)
    if not bad:
        return text
    return (
        text
        + "\n\nDo NOT cite these (already shown nonexistent in the parsed sources):\n- "
        + "\n- ".join(bad[:12])
    )


def literature_requirements_met(
    ot_dir: Path,
    *,
    min_papers: int,
    obs_before: int,
    tools_used: set[str] | frozenset[str],
) -> tuple[bool, str]:
    """Return whether a prove run did enough literature work (not just paper count)."""
    from opentorus.research.memory import list_memory
    from opentorus.research.papers import is_paper_parsed, list_papers

    if min_papers <= 0:
        return True, "No minimum literature configured."

    parsed = sum(1 for p in list_papers(ot_dir) if is_paper_parsed(ot_dir, p))
    obs_added = len(list_memory(ot_dir, "observations")) - obs_before
    min_obs = min(min_papers, 3)
    lit_tools = {"lit_search", "paper_fetch"} & tools_used
    from opentorus.agent.literature_gate import observations_with_paper_refs

    paper_obs = observations_with_paper_refs(ot_dir, obs_before=obs_before)

    if parsed < min_papers:
        return False, f"Need ≥{min_papers} [parsed] papers in paper_list (have {parsed})."
    if obs_added < min_obs:
        return (
            False,
            f"Need ≥{min_obs} memory_add(kind=observations) with per-paper theorems "
            f"(added {obs_added}).",
        )
    if paper_obs < min_obs:
        return (
            False,
            f"Need ≥{min_obs} observations citing PAPER-* ids (have {paper_obs}).",
        )
    if not lit_tools:
        return False, "Need lit_search or paper_fetch in this session."
    return (
        True,
        f"{parsed} parsed paper(s); {obs_added} observation(s) added this session.",
    )


def statement_suggests_open_problem(ot_dir: Path, problem_id: str) -> bool:
    """Heuristic: dossier statement says the problem is still open."""
    from opentorus.research.dossier import store

    path = store.dossier_dir(ot_dir, problem_id.strip().upper()) / "statement.md"
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace").lower()
    markers = (
        "remains open",
        "is open",
        "open conjecture",
        "unsolved",
        "unresolved",
        "still open",
        "not known whether",
        "unknown whether",
    )
    return any(m in text for m in markers)


def dossier_statement_focus(ot_dir: Path, problem_id: str, *, limit: int = 1200) -> str:
    """First chunk of the dossier statement for literature prompts."""
    from opentorus.research.dossier import store

    path = store.dossier_dir(ot_dir, problem_id.strip().upper()) / "statement.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def build_literature_recovery_hint(
    ot_dir: Path,
    *,
    min_papers: int,
    obs_before: int,
    tools_used: set[str] | frozenset[str],
) -> str:
    """Tell the model what to do next — avoid endless tangential lit_search."""
    ok, detail = literature_requirements_met(
        ot_dir,
        min_papers=min_papers,
        obs_before=obs_before,
        tools_used=tools_used,
    )
    if ok:
        return (
            "Literature phase complete. Stop calling tools and reply briefly that phase 1 is done."
        )

    detail_lower = detail.lower()
    if "observation" in detail_lower or "memory_add" in detail_lower:
        return (
            f"Literature phase incomplete: {detail} "
            "Call memory_add(kind=observations) for each [parsed] PAPER-* with theorem/page refs. "
            "Use paper_read / paper_fetch / lit_search freely if you still need sources. "
            "Also dossier_known_result_add / dossier_related_paper_add."
        )
    if "parsed" in detail_lower:
        return (
            f"Literature phase incomplete: {detail} "
            "Run lit_search from the problem statement (or a documented hypothesis), "
            "then paper_fetch each hit worth reading."
        )
    if "lit_search" in detail_lower or "paper_fetch" in detail_lower:
        return (
            f"Literature phase incomplete: {detail} "
            "Read the problem statement, lit_search, then paper_fetch."
        )
    return (
        f"Literature phase incomplete: {detail} "
        "Continue literature work or record hypotheses via memory_add."
    )


def build_literature_prompt(
    problem_id: str,
    *,
    min_papers: int = 0,
    extra: str = "",
    focus: str = "",
) -> str:
    """Dedicated literature phase: fetch and parse papers before proof work."""
    pid = problem_id.strip().upper()
    extra_block = f"\n{extra.strip()}\n" if extra.strip() else ""
    goal = (
        f"Goal: fetch and **read** at least {min_papers} relevant preprints before any proof.\n\n"
        if min_papers > 0
        else "Goal: fetch and parse relevant preprints as needed (no fixed minimum).\n\n"
    )
    focus_block = ""
    has_focus = bool(focus.strip())
    if has_focus:
        focus_block = (
            f"\n=== Dossier {pid} (use this EXACT problem_id everywhere) ===\n{focus.strip()}\n"
        )
    step1 = (
        f"1. The statement for {pid} is already included above — do NOT read_file it or "
        f"guess the id; use '{pid}' exactly.\n"
        if has_focus
        else f"1. read_file .opentorus/problems/{pid}/statement.md\n"
    )
    relevance = (
        "Relevance rules:\n"
        "- Start with lit_search using the problem statement; follow promising leads.\n"
        "- Exploratory searches are welcome — use memory_add(kind=hypotheses) to record "
        "why a thread might connect to the dossier.\n"
        "- paper_fetch hits that support or constrain the dossier; also fetch papers that "
        "might enable a novel connection if you state the hypothesis.\n"
        "- Do NOT call evidence_add or claim_new in this phase.\n\n"
    )
    return (
        f"Literature survey for dossier {pid} (phase 1 — no proof_write yet).\n\n"
        f"{goal}"
        f"{focus_block}"
        f"{relevance}"
        "Workflow:\n"
        f"{step1}"
        "2. paper_list — note [UNREAD] vs [parsed] (.opentorus/papers/, not workspace papers/)\n"
        "3. One focused lit_search from the problem statement\n"
        "4. paper_fetch(identifier=…) for each directly relevant hit — downloads and "
        "parses the PDF\n"
        "5. paper_read(paper_id=…) for notes; re-fetch any PAPER-* still [UNREAD]\n"
        "6. memory_add(kind=observations) per parsed paper: PAPER-* id + theorem/page refs\n"
        "7. dossier_related_paper_add + dossier_known_result_add for each parsed paper "
        "that bears on the problem\n\n"
        "Do NOT call proof_write, claim_new, or evidence_add in this phase.\n"
        "Fetching alone is insufficient — every cited paper must be [parsed].\n"
        f"{extra_block}"
    )


def build_prove_prompt(
    problem_id: str,
    *,
    disprove: bool = False,
    literature_first: bool = True,
    min_papers: int = 0,
    open_problem: bool = False,
    statement_focus: str = "",
    extra: str = "",
) -> str:
    """Build the user goal for a single proof-focused agent run."""
    pid = problem_id.strip().upper()
    optional_lit = (
        "3. paper_list + paper_read — notes for [parsed] PAPER-* in .opentorus/papers/; "
        "paper_fetch if [UNREAD]. lit_search only if a definition/theorem is missing "
        "(statement terms only).\n"
    )
    if disprove:
        goal = (
            "Find a **refutation**: counterexample, obstruction, or rigorous "
            "natural-language disproof of the main conjecture."
        )
        step4 = (
            "4. counterexample_search: scripts + exp_new/exp_run; record "
            "COUNTEREXAMPLE_CANDIDATE if found; verify finitely when possible."
        )
        lit_block = (
            "3. lit_search + paper_fetch: find 1–2 papers on known counterexamples or "
            "impossibility results; paper_fetch each new PAPER-*.\n"
            if min_papers > 0
            else optional_lit
        )
    else:
        if open_problem:
            goal = (
                "Produce an honest **status sketch** for an **open** problem: summarize "
                "known bounds, counterexamples, and obstructions from parsed PAPER-* "
                "artifacts. Do NOT claim the conjecture is proved or disproved unless you "
                "have a complete argument without [GAP-n]."
            )
        else:
            goal = (
                "Produce the strongest **natural-language proof or proof sketch** "
                "you can, with explicit gaps where the argument is incomplete."
            )
        if literature_first and min_papers > 0:
            lit_block = (
                f"3. **Literature (required before proof_write):** at least {min_papers} "
                "papers must show [parsed] in paper_list (not [UNREAD]):\n"
                "   • lit_search(query=…) then paper_fetch for each relevant arXiv/DOI\n"
                "   • paper_read(paper_id=…) for reading notes — not read_file on "
                ".opentorus/summaries/\n"
                "   • Do NOT use run_shell opentorus … or workspace papers/ (use "
                ".opentorus/papers/)\n"
                "   • memory_add(kind=observations) with contribution + theorem citations\n"
                "   • Do NOT cite a paper you have not parsed.\n"
            )
        else:
            lit_block = optional_lit

    extra_block = f"\nAdditional instructions:\n{extra.strip()}\n" if extra.strip() else ""
    focus_block = ""
    has_focus = bool(statement_focus.strip())
    if has_focus:
        focus_block = (
            f"\n\n=== Dossier {pid} (use this EXACT problem_id everywhere) ===\n"
            f"{statement_focus.strip()}\n\n"
            f"This session works on {pid} ONLY — it is a single problem, NOT a research "
            "queue. Do not read, plan, or write for any other PROBLEM-* dossier; finish "
            f"the proof for {pid} and stop.\n"
            "Two-lane discipline (creativity allowed, confusion prevented):\n"
            "• scope=primary — direct answer to the dossier (required deliverable).\n"
            "• scope=exploration — speculative side threads (e.g. a Fredholm reformulation); "
            "requires connection_to_dossier explaining the hypothesized link; mark gaps "
            "[GAP-n]; does NOT replace the primary sketch.\n"
        )

    if has_focus:
        step1 = (
            f"1. The statement for {pid} is already included verbatim below — "
            f"use problem_id exactly '{pid}'. Do NOT read_file the statement or guess the id.\n"
        )
    else:
        step1 = f"1. read_file .opentorus/problems/{pid}/statement.md\n"

    if disprove:
        workflow = (
            f"{step1}"
            "2. status + paper_list — note existing PAPER-*, EXP-*, CLAIM-*\n"
            f"{lit_block}"
            f"{step4}\n"
            "5. proof_write(problem_id, title, theorem, definitions, lemmas, main_proof, "
            "gaps_markdown, evidence_notes, gaps=[…]) — **mandatory** NL refutation sketch\n"
            "   • Cite PAPER-* ids where literature applies\n"
            "   • Cite a theorem NUMBER only if you saw it in that paper's reading note; "
            "otherwise cite by content/section or mark [GAP-n] — a wrong number rejects "
            "the whole proof_write.\n"
            "   • Mark every unjustified step [GAP-1], [GAP-2], …\n"
            "6. memory_add(kind=decisions): refuted / open + gap count + papers read\n"
        )
    else:
        numerics = (
            "5. Optional numerics/special cases only under proof_write evidence_notes "
            "(corroboration, not proof).\n"
        )
        workflow = (
            f"{step1}"
            "2. status + paper_list — note existing PAPER-*, EXP-*, CLAIM-*\n"
            f"{lit_block}"
            "4. Synthesize: which cited results support, constrain, or obstruct a proof?\n"
            f"{numerics}"
            "6. proof_write(problem_id, title, theorem, definitions, lemmas, main_proof, "
            "gaps_markdown, evidence_notes, gaps=[…]) — **mandatory** NL proof artifact\n"
            "   • scope=primary (default): `theorem` restates the dossier problem below\n"
            "   • scope=exploration: side thread + connection_to_dossier (≥60 chars); "
            "does not finish the run alone\n"
            "   • Cite PAPER-* ids in evidence_notes and lemmas where literature applies\n"
            "   • Cite a theorem NUMBER only if you saw it in that paper's reading note; "
            "otherwise cite by content/section or mark the step [GAP-n]. A wrong number "
            "rejects the whole proof_write — never guess.\n"
            "   • Mark every unjustified step [GAP-1], [GAP-2], …\n"
            "   • Do NOT write 'we prove', 'QED', or 'theorem' as settled while [GAP-n] remain\n"
            "   • A bound with log(n), log(d), or n^log d is quasi-polynomial — NOT polynomial\n"
            "7. After the first PROOF-*, keep working while gaps remain: read the sketch, "
            "fetch evidence, run numerics, and call proof_write again to close [GAP-n].\n"
            "8. memory_add(kind=decisions): proved / refuted / open + gap count + papers read\n"
        )

    return (
        f"Natural-language proof work for dossier {pid}.\n\n"
        f"Primary goal: {goal}\n\n"
        "Workflow (tools required — a chat-only reply is not acceptable):\n"
        f"{workflow}\n"
        "claim_new and evidence_add alone are NOT sufficient deliverables for this run.\n"
        f"Required deliverable: proof_write for {pid} → PROOF-* under proof_attempts/.\n"
        f"{focus_block}"
        f"{extra_block}"
    )


def run_prove(
    root: Path,
    ot_dir: Path,
    provider: BaseProvider,
    config: Config,
    problem_id: str,
    *,
    disprove: bool = False,
    literature_first: bool = True,
    min_papers: int = 0,
    extra: str = "",
    confirm=None,
    on_text=None,
    on_llm_request=None,
    on_llm_response=None,
    stream_llm: bool = False,
    on_thinking=None,
    on_status=None,
    session_id: str | None = None,
) -> ProveOutcome:
    """Run one bounded agent session aimed at an NL proof artifact."""
    from opentorus.agent.context import reset_retrieval_breaker
    from opentorus.agent.loop import AgentLoop
    from opentorus.research.dossier import store
    from opentorus.research.dossier.report import lint_dossier_report
    from opentorus.research.papers import is_paper_parsed, list_papers
    from opentorus.tools.builtin import build_default_registry

    # Start each prove run with retrieval re-enabled: a breaker tripped in an earlier
    # phase/run must not silently disable retrieval here.
    reset_retrieval_breaker()
    pid = problem_id.strip().upper()
    store.require_dossier(ot_dir, pid)

    def _unread_ids() -> list[str]:
        return [
            p.id
            for p in list_papers(ot_dir)
            if p.full_text_accessible and not is_paper_parsed(ot_dir, p)
        ]

    papers_before = len(list_papers(ot_dir))
    parsed_before = sum(1 for p in list_papers(ot_dir) if is_paper_parsed(ot_dir, p))
    from opentorus.research.memory import list_memory

    obs_before = len(list_memory(ot_dir, "observations"))
    open_problem = statement_suggests_open_problem(ot_dir, pid)
    before_proofs = {p.id for p in store.list_proof_attempts(ot_dir, pid)}
    registry = build_default_registry(root, ot_dir, config)
    floor = 40 if disprove else 12
    steps = config.agent.max_steps
    if not math.isinf(steps):
        steps = max(int(steps), floor)
    if literature_first and min_papers > 0 and not math.isinf(steps):
        steps = max(int(steps), 20)

    # ``steps`` is the GLOBAL model-iteration budget for the whole prove run, shared
    # across the literature, literature-continuation, and proof phases. Without this
    # each phase would spend its own full cap, so max_steps=100 could run ~200+
    # iterations (and spin forever when literature can never reach [parsed]).
    total_budget = steps
    steps_used = 0

    def _remaining() -> float:
        if math.isinf(total_budget):
            return math.inf
        return max(total_budget - steps_used, 0)

    def _make_loop(
        step_cap: float,
        *,
        bootstrap: tuple[str, dict] | None = None,
        session_gate: Callable[[], bool] | None = None,
        session_recovery_hint: Callable[[], str] | None = None,
        pre_deliverable_gate: Callable[[], bool] | None = None,
        pre_deliverable_gate_detail: Callable[[], str] | None = None,
        deliverable_complete: Callable[[], bool] | None = None,
        tool_gate: Callable[[str, dict], str | None] | None = None,
    ) -> AgentLoop:
        return AgentLoop(
            root,
            ot_dir,
            provider,
            registry,
            config,
            max_steps=step_cap,
            session_id=session_id,
            confirm=confirm,
            on_text=on_text,
            on_llm_request=on_llm_request,
            on_llm_response=on_llm_response,
            stream_llm=stream_llm,
            on_thinking=on_thinking,
            on_status=on_status,
            deliverable_bootstrap=bootstrap,
            session_gate=session_gate,
            session_recovery_hint=session_recovery_hint,
            pre_deliverable_gate=pre_deliverable_gate,
            pre_deliverable_gate_detail=pre_deliverable_gate_detail,
            deliverable_complete=deliverable_complete,
            tool_gate=tool_gate,
        )

    statement_focus = dossier_statement_focus(ot_dir, pid)
    _active_lit: dict[str, AgentLoop | None] = {"loop": None}

    def _literature_tools_used() -> frozenset[str]:
        loop = _active_lit["loop"]
        extra = loop.tools_used_this_run if loop is not None else []
        return frozenset(all_tools_used + extra)

    def _literature_gate() -> bool:
        ok, _ = literature_requirements_met(
            ot_dir,
            min_papers=min_papers,
            obs_before=obs_before,
            tools_used=_literature_tools_used(),
        )
        return ok

    def _literature_recovery() -> str:
        return build_literature_recovery_hint(
            ot_dir,
            min_papers=min_papers,
            obs_before=obs_before,
            tools_used=_literature_tools_used(),
        )

    from opentorus.research.dossier.nl_proof import bootstrap_proof_write_args

    total_tool_calls = 0
    all_tools_used: list[str] = []
    answer = ""
    goal_summary = "disproof sketch" if disprove else "proof sketch"
    proof_bootstrap = (
        "proof_write",
        bootstrap_proof_write_args(
            pid,
            f"Natural-language {goal_summary} for {pid}",
            statement=statement_focus,
        ),
    )

    if literature_first and min_papers > 0:
        if on_status is not None:
            on_status(
                "phase",
                "Literature survey" if not disprove else "Literature (refutation context)",
            )
        lit_steps = max(min_papers * 6, 20, steps // 2 if not math.isinf(steps) else min_papers * 6)
        # Literature (first attempt + continuation) may use at most half the global
        # budget; the proof phase always keeps the remainder. This prevents an
        # unsatisfiable literature gate (e.g. only paywalled papers) from consuming
        # the whole run.
        if math.isinf(total_budget):
            lit_phase_cap: float = float(lit_steps)
        else:
            lit_phase_cap = min(lit_steps, max(total_budget // 2, 1))
        lit_phase_used = 0

        from opentorus.agent.literature_gate import literature_tool_gate

        lit_loop = _make_loop(
            min(lit_phase_cap, _remaining()),
            bootstrap=bootstrap_literature_tool(root, pid),
            session_gate=_literature_gate,
            session_recovery_hint=_literature_recovery,
            tool_gate=literature_tool_gate(phase_complete=_literature_gate),
        )
        _active_lit["loop"] = lit_loop
        answer = lit_loop.run(
            build_literature_prompt(
                pid,
                min_papers=min_papers,
                extra=extra,
                focus=statement_focus,
            )
        )
        steps_used += lit_loop.steps_run
        lit_phase_used += lit_loop.steps_run
        total_tool_calls += lit_loop.tool_calls_this_run
        all_tools_used.extend(lit_loop.tools_used_this_run)

        lit_ok, lit_detail = literature_requirements_met(
            ot_dir,
            min_papers=min_papers,
            obs_before=obs_before,
            tools_used=frozenset(all_tools_used),
        )
        cont_cap = min(lit_phase_cap - lit_phase_used, _remaining())
        if not lit_ok and cont_cap >= 1:
            if on_status is not None:
                on_status("phase", "Literature (continued)")
            cont_loop = _make_loop(
                cont_cap,
                bootstrap=bootstrap_literature_tool(root, pid),
                session_gate=_literature_gate,
                session_recovery_hint=_literature_recovery,
                tool_gate=literature_tool_gate(phase_complete=_literature_gate),
            )
            _active_lit["loop"] = cont_loop
            _recovery_hint = build_literature_recovery_hint(
                ot_dir,
                min_papers=min_papers,
                obs_before=obs_before,
                tools_used=frozenset(all_tools_used),
            )
            cont_prompt = (
                f"Literature phase INCOMPLETE for {pid}: {lit_detail}\n\n"
                f"{_recovery_hint}\n"
                "Still no proof_write.\n"
                f"{extra.strip()}"
            ).strip()
            cont_answer = cont_loop.run(cont_prompt)
            answer = f"{answer}\n\n---\n\n{cont_answer}" if answer else cont_answer
            steps_used += cont_loop.steps_run
            total_tool_calls += cont_loop.tool_calls_this_run
            all_tools_used.extend(cont_loop.tools_used_this_run)

    def _literature_ready() -> tuple[bool, str]:
        return literature_requirements_met(
            ot_dir,
            min_papers=min_papers,
            obs_before=obs_before,
            tools_used=frozenset(all_tools_used),
        )

    if on_status is not None:
        on_status("phase", "Disproof draft" if disprove else "Proof draft")
    proof_kw: dict = {}
    if min_papers > 0:
        proof_kw["pre_deliverable_gate"] = lambda: _literature_ready()[0]
        proof_kw["pre_deliverable_gate_detail"] = lambda: _literature_ready()[1]

    proof_loop_holder: list = []
    _gap_fill: dict[str, int | None] = {
        "anchor": None,
        "best": None,
        "best_step": None,
        "evidence": None,
    }
    # Memoize the referee gate per model step so a single text-only turn (which probes
    # _proof_deliverable_complete several times) runs the deterministic referee at most once.
    _referee_gate: dict[str, int] = {"step": -1}

    def _evidence_count() -> int:
        # Genuine progress signals beyond the gap count: a parsed paper or a recorded
        # experiment is new evidence the model can fold into the proof. Counting these
        # lets the no-progress window credit active evidence-gathering (a model that runs
        # experiments toward closing a gap is NOT stuck) without letting bare re-reads or
        # re-writes of the same sketch reset it.
        from opentorus.research.dossier.experiments import list_experiments
        from opentorus.research.papers import is_paper_parsed, list_papers

        parsed = sum(1 for p in list_papers(ot_dir) if is_paper_parsed(ot_dir, p))
        return parsed + len(list_experiments(ot_dir, pid))

    def _proof_deliverable_complete() -> bool:
        # A proof must actually exist for THIS dossier; otherwise the model may have
        # written to the wrong problem and nothing was delivered for `pid`.
        if not has_primary_proof(ot_dir, pid):
            return False
        if not config.agent.prove_until_gaps_closed:
            return True
        # Let the hostile referee weigh in on every completion check (memoized per model
        # step, since the referee is deterministic and local). When it blocks (unsupported
        # result-claims, contradictions) it reopens `[REFEREE]` gaps; when it passes it
        # strips them. The gap count is re-read afterwards, so the run can only settle once
        # the proof is genuinely gap-free AND the referee no longer blocks — a real overclaim
        # surfaces even if the model's own gap count is a miscount. This also closes the
        # escape where a model empties `gaps` by relabelling unresolved steps as prose
        # "Open Problems" (the trace's "proof stopped very early" bug).
        if config.agent.prove_referee_reopens_gaps:
            step = proof_loop_holder[0].steps_run if proof_loop_holder else -1
            if _referee_gate["step"] != step:
                _referee_gate["step"] = step
                reopen_referee_gaps(ot_dir, pid)
        gaps = latest_proof_gap_count(ot_dir, pid)
        if gaps == 0:
            return True
        if not proof_loop_holder:
            return False
        loop = proof_loop_holder[0]
        evidence = _evidence_count()
        if _gap_fill["anchor"] is None:
            _gap_fill["anchor"] = loop.steps_run
            _gap_fill["best"] = gaps
            _gap_fill["best_step"] = loop.steps_run
            _gap_fill["evidence"] = evidence
            # The draft now exists with open gaps: reflect the gap-fill phase in the
            # trace banner instead of leaving it on "Proof draft".
            if on_status is not None:
                on_status("phase", "Proof gap-fill")
            return False
        # Progress = the gap count dropped OR new evidence (experiment/paper) was gathered.
        # Either resets the no-progress window so productive work is never cut off.
        gaps_improved = _gap_fill["best"] is None or gaps < int(_gap_fill["best"])
        new_evidence = _gap_fill["evidence"] is None or evidence > int(_gap_fill["evidence"])
        if gaps_improved:
            _gap_fill["best"] = gaps
        if new_evidence:
            _gap_fill["evidence"] = evidence
        if gaps_improved or new_evidence:
            _gap_fill["best_step"] = loop.steps_run
        spent = loop.steps_run - int(_gap_fill["anchor"])
        if spent >= config.agent.prove_gap_fill_max_steps:
            return True
        # No-progress backstop: stop if neither gaps nor evidence advanced for a whole
        # window, even when the caps are inf — otherwise a model that cannot close gaps
        # grinds forever (re-reading the same sketch, re-declaring "done").
        no_progress = loop.steps_run - int(_gap_fill["best_step"] or _gap_fill["anchor"])
        return no_progress >= config.agent.prove_gap_fill_no_progress_steps

    def _proof_gap_recovery() -> str:
        return build_proof_gap_recovery_hint(ot_dir, pid)

    from opentorus.agent.prove_gate import prove_tool_gate

    proof_loop = _make_loop(
        _remaining(),
        bootstrap=proof_bootstrap,
        deliverable_complete=_proof_deliverable_complete,
        session_recovery_hint=_proof_gap_recovery,
        tool_gate=prove_tool_gate(
            pid,
            deliverable_done=lambda: bool(
                proof_loop_holder and proof_loop_holder[0]._deliverable_satisfied
            ),
        ),
        **proof_kw,
    )
    proof_loop_holder.append(proof_loop)
    proof_extra = extra
    unread = _unread_ids()
    if literature_first and unread:
        proof_extra = (
            f"{extra}\n\nUnread papers (re-fetch before citing): {', '.join(unread)}"
        ).strip()
    proof_prompt = build_prove_prompt(
        pid,
        disprove=disprove,
        literature_first=literature_first,
        min_papers=min_papers,
        open_problem=open_problem,
        statement_focus=statement_focus,
        extra=proof_extra,
    )
    # On a resumed run, re-feed citations a prior run already proved nonexistent.
    proof_prompt = _append_known_bad_citations(ot_dir, pid, proof_prompt)
    proof_answer = proof_loop.run(proof_prompt)
    answer = proof_answer if not answer else f"{answer}\n\n---\n\n{proof_answer}"
    total_tool_calls += proof_loop.tool_calls_this_run
    all_tools_used.extend(proof_loop.tools_used_this_run)
    loop = proof_loop
    loop.tool_calls_this_run = total_tool_calls
    loop.tools_used_this_run = all_tools_used

    harvest_outcome = None
    if disprove:
        from opentorus.agent.prove_harvest import harvest_prove_session

        harvest_outcome = harvest_prove_session(
            ot_dir, pid, session_id=session_id, create_proof=True
        )

    after = store.list_proof_attempts(ot_dir, pid)
    new_proofs = [p for p in after if p.id not in before_proofs]
    if not new_proofs and harvest_outcome and harvest_outcome.proof_ids:
        new_proofs = [p for p in after if p.id in harvest_outcome.proof_ids]
    if not new_proofs and "proof_write" in loop.tools_used_this_run:
        new_proofs = after[-1:]

    gap_count = sum(len(p.gaps) for p in new_proofs)

    # Hostile referee: classify claims, lint proof bodies, gate. Persisted as a
    # REFEREE-* artifact so `problem report` surfaces the verdict. Never fatal.
    referee_verdict: str | None = None
    try:
        from opentorus.research.dossier.referee import referee_review

        referee_verdict = referee_review(ot_dir, pid).verdict
    except Exception:  # noqa: BLE001 - the referee must never break the prove run
        referee_verdict = None

    lint_issues = 0
    report_path = store.dossier_dir(ot_dir, pid) / "report.md"
    if report_path.is_file():
        lint_issues = len(lint_dossier_report(ot_dir, pid))

    lit_tools = {"lit_search", "paper_fetch", "web_search"}
    literature_tools_used = bool(lit_tools & set(all_tools_used))
    parsed_after = sum(1 for p in list_papers(ot_dir) if is_paper_parsed(ot_dir, p))
    lit_complete, lit_detail = literature_requirements_met(
        ot_dir,
        min_papers=min_papers,
        obs_before=obs_before,
        tools_used=frozenset(all_tools_used),
    )

    proof_warnings: list[str] = []
    if new_proofs:
        from opentorus.research.dossier.nl_proof import lint_proof_sketch

        for proof in new_proofs:
            body_path = (
                store.dossier_dir(ot_dir, pid) / proof.body_path if proof.body_path else None
            )
            if body_path and body_path.is_file():
                proof_warnings.extend(
                    lint_proof_sketch(
                        body_path.read_text(encoding="utf-8", errors="replace"),
                        open_problem=open_problem,
                        statement=statement_focus,
                    )
                )

    gaps_remaining = latest_proof_gap_count(ot_dir, pid)
    _anchor = _gap_fill["anchor"]
    _best_step = _gap_fill["best_step"]
    gap_fill_exhausted = bool(
        config.agent.prove_until_gaps_closed
        and gaps_remaining > 0
        and _anchor is not None
        and (
            proof_loop.steps_run - int(_anchor) >= config.agent.prove_gap_fill_max_steps
            or proof_loop.steps_run - int(_best_step if _best_step is not None else _anchor)
            >= config.agent.prove_gap_fill_no_progress_steps
        )
    )

    return ProveOutcome(
        problem_id=pid,
        answer=answer,
        proof_ids=[p.id for p in new_proofs],
        gap_count=gap_count,
        lint_issues=lint_issues,
        tool_calls=total_tool_calls,
        papers_added=len(list_papers(ot_dir)) - papers_before,
        papers_read=parsed_after - parsed_before,
        unread_papers=_unread_ids() or None,
        literature_tools_used=literature_tools_used,
        literature_complete=lit_complete,
        literature_detail=lit_detail,
        proof_warnings=proof_warnings or None,
        harvested_experiments=harvest_outcome.experiment_ids if harvest_outcome else None,
        harvested_claims=harvest_outcome.claim_ids if harvest_outcome else None,
        gaps_remaining=gaps_remaining,
        gap_fill_exhausted=gap_fill_exhausted,
        referee_verdict=referee_verdict,
    )
