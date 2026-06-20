"""Attack strategy templates (Milestone M1, Phase 5).

Each strategy turns a problem into a structured ``Approach`` artifact: an
objective, assumptions, a method, expected outputs, failure modes, and the tools
it would need. The templates do not pretend to *solve* anything — they scaffold
honest, reproducible work and record what would count as a result and what would
count as a failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from opentorus.research.dossier import store
from opentorus.research.dossier.models import Approach, AttackStrategy, utcnow


@dataclass(frozen=True)
class StrategyTemplate:
    strategy: AttackStrategy
    objective: str
    assumptions: list[str] = field(default_factory=list)
    method: str = ""
    expected_outputs: list[str] = field(default_factory=list)
    failure_modes: list[str] = field(default_factory=list)
    required_tools: list[str] = field(default_factory=list)


STRATEGY_TEMPLATES: dict[AttackStrategy, StrategyTemplate] = {
    "literature_map": StrategyTemplate(
        strategy="literature_map",
        objective=(
            "Find relevant papers, known results, equivalent formulations, and prior "
            "failed approaches; attach each to the dossier with a local citation."
        ),
        method=(
            "Search the literature, register PAPER-* artifacts, record theorem "
            "references with page/section, and add RELP-* related-paper entries. "
            "Mark equivalent forms in problem.yaml:known_equivalent_forms."
        ),
        expected_outputs=[
            "related_papers.jsonl entries",
            "theorem references with page/section",
            "REFERENCE_FACT claims (each citing a source)",
        ],
        failure_modes=[
            "No local artifact backing a citation (hallucinated reference)",
            "Stating a result as 'known' without a paper/theorem reference",
        ],
        required_tools=["lit_search", "paper_fetch"],
    ),
    "special_cases": StrategyTemplate(
        strategy="special_cases",
        objective=(
            "Restrict the problem to simpler regimes (finite, low-dimensional, "
            "symmetric, smooth, bounded, toy) to build intuition or find structure."
        ),
        method=(
            "Define the restricted regime as an Assumption, state the specialized "
            "claim, and gather evidence (computation/experiment). Keep the "
            "specialization explicit so conclusions are not over-generalized."
        ),
        expected_outputs=[
            "Assumptions describing each restricted regime",
            "Claims scoped to the special case",
            "Evidence supporting/contradicting the special case",
        ],
        failure_modes=[
            "Generalizing a special-case result to the full problem",
            "Hidden assumptions that make the special case trivial",
        ],
        required_tools=["run_shell", "write_file"],
    ),
    "counterexample_search": StrategyTemplate(
        strategy="counterexample_search",
        objective=(
            "Search small, finite, numerical, symbolic, or pathological examples that "
            "could refute the conjecture."
        ),
        method=(
            "Enumerate or sample candidate objects under recorded bounds; log each "
            "candidate under counterexample_search/. A candidate is a "
            "COUNTEREXAMPLE_CANDIDATE claim until an explicit verification artifact "
            "exists — only then COUNTEREXAMPLE_VERIFIED."
        ),
        expected_outputs=[
            "Reproducible search experiment manifest (EXP-*)",
            "COUNTEREXAMPLE_CANDIDATE claims (if any)",
            "Recorded search bounds (what was and was not checked)",
        ],
        failure_modes=[
            "Calling a candidate 'verified' without a verification artifact",
            "Numerical noise mistaken for a true counterexample",
            "Search space too large; absence of counterexample is not a proof",
        ],
        required_tools=["run_shell", "exp_run", "write_file"],
    ),
    "symbolic_simplification": StrategyTemplate(
        strategy="symbolic_simplification",
        objective=(
            "Rewrite the problem into an equivalent algebraic, analytic, "
            "combinatorial, or variational form that may be easier to attack."
        ),
        method=(
            "Derive an equivalent formulation, record it in "
            "problem.yaml:known_equivalent_forms, and justify the equivalence as a "
            "LEMMA_ATTEMPT with explicit gaps where the equivalence is unproven."
        ),
        expected_outputs=[
            "Equivalent formulation recorded",
            "LEMMA_ATTEMPT claims for each rewriting step",
        ],
        failure_modes=[
            "Equivalence that silently changes the hypotheses",
            "Asserting equivalence without proof",
        ],
        required_tools=["run_shell", "write_file"],
    ),
    "numerical_experiment": StrategyTemplate(
        strategy="numerical_experiment",
        objective="Generate reproducible computational evidence about the conjecture.",
        method=(
            "Write a script with a fixed random seed, capture stdout/stderr and an "
            "EXP-* manifest (command, deps hash, git commit), and link the result to "
            "a claim as supporting/contradicting evidence — never as proof."
        ),
        expected_outputs=[
            "experiments/EXP-* with manifest.yaml, run.sh, logs, result.md",
            "EXPERIMENT evidence linked to a claim (support only)",
        ],
        failure_modes=[
            "Treating numerical evidence as a proof",
            "Unseeded randomness (non-reproducible)",
            "Floating-point error mistaken for signal",
        ],
        required_tools=["run_shell", "exp_run", "write_file"],
    ),
    "formalization_attempt": StrategyTemplate(
        strategy="formalization_attempt",
        objective=(
            "Translate definitions and the statement into a proof-assistant-friendly "
            "form (e.g. Lean-style), even if not fully checked."
        ),
        method=(
            "Formalize the definitions and statement; set "
            "problem.yaml:formalization_status to lean_ready/coq_ready. Only a "
            "successful verifier run may set lean_checked/coq_checked."
        ),
        expected_outputs=[
            "Formal statement/definitions skeleton",
            "formalization_status updated (ready, not checked)",
        ],
        failure_modes=[
            "Marking as checked without running a verifier",
            "Formal statement drifting from the informal one",
        ],
        required_tools=["write_file", "verifier"],
    ),
    "proof_sketch": StrategyTemplate(
        strategy="proof_sketch",
        objective="Create a clearly labelled informal proof attempt with gaps marked.",
        method=(
            "Call proof_write with theorem/definitions/lemmas/main_proof sections; enumerate "
            "every gap and unjustified step. The sketch is a PROOF attempt at status 'sketch' — it "
            "is never a verified proof and never sets a claim to formally_verified."
        ),
        expected_outputs=[
            "proof_attempts/PROOF-* sketch with explicit gaps",
            "LEMMA_ATTEMPT claims for sub-steps",
        ],
        failure_modes=[
            "Hidden gaps presented as complete steps",
            "Calling the sketch a proof",
        ],
        required_tools=["proof_write"],
    ),
    "obstruction_search": StrategyTemplate(
        strategy="obstruction_search",
        objective=(
            "Identify why standard methods fail and record reusable obstructions so "
            "the same dead end is not retried."
        ),
        method=(
            "For each standard method tried, record a FailedAttempt with the precise "
            "reason it fails and mark reusable_obstruction=true. Summarize recurring "
            "obstructions in problem.yaml:known_obstructions."
        ),
        expected_outputs=[
            "failed_attempts.jsonl entries with reasons",
            "known_obstructions updated",
        ],
        failure_modes=[
            "Vague 'it didn't work' with no reusable reason",
            "Retrying a known obstruction without new assumptions",
        ],
        required_tools=["write_file"],
    ),
}


def create_approach(ot_dir: Path, problem_id: str, strategy: AttackStrategy) -> Approach:
    """Instantiate a strategy template as an Approach artifact in the dossier."""
    store.require_dossier(ot_dir, problem_id)
    template = STRATEGY_TEMPLATES[strategy]
    existing = store.list_approaches(ot_dir, problem_id)
    from opentorus.jsonl import next_sequential_id

    approach = Approach(
        id=next_sequential_id("APPR", len(existing)),
        problem_id=problem_id,
        strategy=strategy,
        objective=template.objective,
        assumptions=list(template.assumptions),
        method=template.method,
        expected_outputs=list(template.expected_outputs),
        failure_modes=list(template.failure_modes),
        required_tools=list(template.required_tools),
        created_at=utcnow(),
    )
    # Write a human-readable approach card too.
    card = store.dossier_dir(ot_dir, problem_id) / "approaches"
    card.mkdir(exist_ok=True)
    (card / f"{approach.id}.md").write_text(_render_approach(approach), encoding="utf-8")
    return store.add_approach(ot_dir, approach)


def _render_approach(a: Approach) -> str:
    def _bullets(items: list[str]) -> str:
        return "\n".join(f"- {x}" for x in items) if items else "- (none)"

    return (
        f"# {a.id} — {a.strategy}\n\n"
        f"## Objective\n\n{a.objective}\n\n"
        f"## Assumptions\n\n{_bullets(a.assumptions)}\n\n"
        f"## Method\n\n{a.method}\n\n"
        f"## Expected outputs\n\n{_bullets(a.expected_outputs)}\n\n"
        f"## Failure modes\n\n{_bullets(a.failure_modes)}\n\n"
        f"## Required tools\n\n{_bullets(a.required_tools)}\n"
    )
