"""Deterministic task planner.

Decomposes a goal into a small set of typed sub-tasks. For substantial research
goals it proposes the standard pipeline (literature -> code -> experiment ->
analysis -> review -> report); for trivial one-step requests it proposes a single
task so task cards are not overused.

A provider is accepted for interface compatibility and future LLM-backed
planning, but the current decomposition is deterministic so behavior is testable
without any model.
"""

from __future__ import annotations

import logging
import re

from opentorus.providers.base import BaseProvider

logger = logging.getLogger(__name__)

TaskSpec = tuple[str, str]

RESEARCH_PIPELINE = ["literature", "code", "experiment", "analysis", "review", "report"]

_PIPELINE_PREFIX = {
    "literature": "Survey relevant prior work",
    "code": "Implement the needed code",
    "experiment": "Design and run a reproducible experiment",
    "analysis": "Analyze results and observed behavior",
    "review": "Review evidence and limitations",
    "report": "Assemble a structured report",
}

_CODE_HINTS = ("fix", "refactor", "implement", "rename", "add", "remove", "bug", "patch")
_LIT_HINTS = ("read", "paper", "literature", "survey", "cite", "reference")


def _infer_category(goal: str) -> str:
    low = goal.lower()
    if any(word in low for word in _LIT_HINTS):
        return "literature"
    if any(word in low for word in _CODE_HINTS):
        return "code"
    return "analysis"


_RESEARCH_KEYWORDS = (
    "prove",
    "conjecture",
    "theorem",
    "hypothesis",
    "counterexample",
    "state of the art",
    "open problem",
    "survey the literature",
)
_SIMPLE_DELIVERABLE_HINTS = (
    "write ",
    "read ",
    "summarize",
    "summary",
    "analysis.md",
    "draft ",
    "explain ",
)


_RESEARCH_SUBGOALS = {
    "literature": (
        "Survey and read relevant sources (paper_list, paper_fetch, lit_search). "
        "Extract open problems and record facts with memory_add / claim_new, citing PAPER-* ids."
    ),
    "code": (
        "Implement minimal, testable code for one concrete open problem from the goal. "
        "Use read_file/write_file/run_shell/check; keep diffs small."
    ),
    "experiment": (
        "Design and run a reproducible experiment (exp_run or experiment tools) that probes "
        "one conjecture; store results under EXP-* with captured stdout."
    ),
    "analysis": (
        "Analyze evidence and observations from papers/experiments; write analysis distinguishing "
        "evidence from conclusions; use memory_add and evidence_add."
    ),
    "review": (
        "Review claims and evidence for gaps or overclaiming; note limitations and whether "
        "status upgrades are justified."
    ),
    "report": (
        "Write analysis.md or update the dossier with claims, evidence, and papers; "
        "cite artifact IDs."
    ),
}


def _is_research_goal(low: str) -> bool:
    """True when ``goal`` looks like formal research, not incidental substrings."""
    for keyword in _RESEARCH_KEYWORDS:
        if " " in keyword:
            if keyword in low:
                return True
        elif re.search(rf"\b{re.escape(keyword)}\b", low):
            return True
    return False


def plan(goal: str, provider: BaseProvider | None = None) -> list[TaskSpec]:
    """Return a list of (category, sub-goal) specs for ``goal``."""
    goal = goal.strip()
    low = goal.lower()
    words = len(goal.split())

    if words <= 4:
        return [(_infer_category(goal), goal)]

    is_research = _is_research_goal(low)
    simple_deliverable = any(h in low for h in _SIMPLE_DELIVERABLE_HINTS)

    if simple_deliverable and not is_research and words <= 14:
        return [
            ("literature", f"Gather context for: {goal}"),
            ("analysis", goal),
        ]

    if not is_research:
        return [
            ("literature", f"Gather context for: {goal}"),
            ("code", f"Implement the needed code for: {goal}"),
            ("analysis", f"Analyze results for: {goal}"),
        ]

    return [
        (cat, f"{_RESEARCH_SUBGOALS[cat]} Overall investigation: {goal}")
        for cat in RESEARCH_PIPELINE
    ]


def _parse_llm_plan(text: str, goal: str) -> list[TaskSpec] | None:
    """Best-effort JSON plan from an LLM response."""
    import json

    text = text.strip()
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end <= start:
        return None
    try:
        raw = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    if not isinstance(raw, list):
        return None
    specs: list[TaskSpec] = []
    valid = {"literature", "code", "experiment", "analysis", "review", "report"}
    for item in raw[:6]:
        if not isinstance(item, dict):
            continue
        cat = str(item.get("category", "")).strip().lower()
        sub = str(item.get("goal", item.get("subgoal", ""))).strip()
        if cat in valid and sub:
            specs.append((cat, sub))
    return specs or None


def plan_with_provider(
    goal: str,
    provider: BaseProvider | None,
    *,
    use_llm: bool = True,
) -> list[TaskSpec]:
    """Plan with an optional LLM decomposition, falling back to deterministic rules."""
    if not use_llm or provider is None:
        return plan(goal, provider)
    name = getattr(provider, "name", "")
    if name == "mock":
        return plan(goal, provider)

    from opentorus.agent.session import SessionMessage

    prompt = (
        "Decompose this research/engineering goal into 2–6 ordered tasks.\n"
        "Return ONLY a JSON array of objects with keys category and goal.\n"
        "category must be one of: literature, code, experiment, analysis, review, report.\n"
        "Each goal must be a concrete deliverable (mention tools like paper_fetch, "
        "write_file, exp_run, claim_new where appropriate).\n\n"
        f"Goal: {goal.strip()}"
    )
    try:
        response = provider.respond([SessionMessage(role="user", content=prompt)])
        if response.kind == "message" and response.content:
            specs = _parse_llm_plan(response.content, goal)
            if specs:
                return specs
    except Exception as exc:  # noqa: BLE001 — fall back to the deterministic pipeline plan
        logger.debug("LLM plan decomposition failed (%s); using deterministic plan.", exc)
    return plan(goal, provider)
