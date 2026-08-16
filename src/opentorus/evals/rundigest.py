"""Turn a finished workspace into a structured account of what the run actually did.

Every behavioural fix in this project so far was found by reading a transcript by
hand — counting how often a tool failed the same way, noticing eleven consecutive
searches, spotting that a whole benchmark cell never called ``proof_submit``. That is
exactly the work a machine should do: the material is already on disk as typed
artifacts (``actions.jsonl``, ``proofs.jsonl``, the dossier stores, the usage ledger),
and reading it by eye does not scale past a handful of runs.

A digest is *description*, not judgement. It counts what happened and names the
patterns that have previously indicated a stuck run; it never decides whether the
mathematics was any good. Scoring against a stated expectation is a separate step
(:class:`ExpectedOutcome`), so the neutral record stays neutral.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from pydantic import BaseModel, Field

# A tool failing this often with the same error is the signature of a stuck run
# rather than of a hard problem.
_REPEAT_FAILURE_FLAG = 3
# Consecutive searches without a fetch/read in between (the loop warns from 4).
_SEARCH_SPAM_FLAG = 4
_SEARCH_TOOLS = frozenset({"lit_search", "web_search"})
_SEARCH_NEUTRAL = frozenset({"paper_list", "status"})


class ToolStat(BaseModel):
    name: str
    calls: int = 0
    failures: int = 0

    @property
    def failure_rate(self) -> float:
        return self.failures / self.calls if self.calls else 0.0


class DeadEnd(BaseModel):
    """A tool call that failed the same way more than once."""

    tool: str
    error: str
    count: int


class VerifierSummary(BaseModel):
    submissions: int = 0
    accepted: int = 0
    rejected: int = 0
    inconclusive: int = 0
    cached: int = 0
    backends: list[str] = Field(default_factory=list)


class ClaimSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_type: dict[str, int] = Field(default_factory=dict)


class CostSummary(BaseModel):
    model_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    wall_seconds: float = 0.0
    models: list[str] = Field(default_factory=list)

    @property
    def prompt_share(self) -> float:
        """Fraction of processed tokens that were re-sent prompt.

        A high share is the signature of a request whose prefix cannot be reused; it is
        what motivated putting volatile context at the end of the request.
        """
        total = self.prompt_tokens + self.completion_tokens
        return self.prompt_tokens / total if total else 0.0


class RunDigest(BaseModel):
    workspace: str
    initialized: bool = True
    tools: list[ToolStat] = Field(default_factory=list)
    total_calls: int = 0
    total_failures: int = 0
    dead_ends: list[DeadEnd] = Field(default_factory=list)
    longest_search_streak: int = 0
    verifier: VerifierSummary = Field(default_factory=VerifierSummary)
    claims: ClaimSummary = Field(default_factory=ClaimSummary)
    experiments_run: int = 0
    experiments_failed: int = 0
    proof_attempts: int = 0
    open_gaps: int = 0
    cost: CostSummary = Field(default_factory=CostSummary)
    # Patterns previously seen to indicate a stuck run. Observations, not verdicts.
    flags: list[str] = Field(default_factory=list)


def _normalize(text: str | None, limit: int = 160) -> str:
    return " ".join((text or "").split())[:limit]


def _tool_stats(actions) -> tuple[list[ToolStat], int, int]:  # noqa: ANN001
    stats: dict[str, ToolStat] = {}
    for entry in actions:
        stat = stats.setdefault(entry.tool_name, ToolStat(name=entry.tool_name))
        stat.calls += 1
        if not entry.ok:
            stat.failures += 1
    ordered = sorted(stats.values(), key=lambda s: (-s.calls, s.name))
    return ordered, sum(s.calls for s in ordered), sum(s.failures for s in ordered)


def _dead_ends(actions) -> list[DeadEnd]:  # noqa: ANN001
    counts: Counter[tuple[str, str]] = Counter()
    for entry in actions:
        if entry.ok:
            continue
        counts[(entry.tool_name, _normalize(entry.stderr_summary))] += 1
    return [
        DeadEnd(tool=tool, error=error, count=count)
        for (tool, error), count in counts.most_common()
        if count > 1
    ]


def _longest_search_streak(actions) -> int:  # noqa: ANN001
    longest = current = 0
    for entry in actions:
        if entry.tool_name in _SEARCH_TOOLS:
            current += 1
            longest = max(longest, current)
        elif entry.tool_name not in _SEARCH_NEUTRAL:
            current = 0
    return longest


def _verifier_summary(ot_dir: Path) -> VerifierSummary:
    from opentorus.research.verifiers.proofs import list_proofs

    summary = VerifierSummary()
    backends: set[str] = set()
    for proof in list_proofs(ot_dir):
        summary.submissions += 1
        backends.add(proof.backend)
        if getattr(proof, "cached", False):
            summary.cached += 1
        if proof.inconclusive:
            summary.inconclusive += 1
        elif proof.accepted:
            summary.accepted += 1
        else:
            summary.rejected += 1
    summary.backends = sorted(backends)
    return summary


def _claim_and_proof_summary(ot_dir: Path) -> tuple[ClaimSummary, int, int]:
    """Count claims from both stores, and proof attempts + open gaps from the dossier.

    The agent's ``claim_new`` writes to the *workspace* claim store while the report and
    referee read the *dossier* store. Counting only the dossier made a run that recorded
    plenty of claims look like it had recorded none.
    """
    from opentorus.research import claims as workspace_claims
    from opentorus.research.dossier import store

    claims = ClaimSummary()
    attempts = 0
    gaps = 0

    def _count(status: str, claim_type: str | None) -> None:
        claims.total += 1
        claims.by_status[status] = claims.by_status.get(status, 0) + 1
        if claim_type is not None:
            claims.by_type[claim_type] = claims.by_type.get(claim_type, 0) + 1

    # Workspace claims carry a status but no type; dossier claims carry both.
    for workspace_claim in workspace_claims.list_claims(ot_dir):
        _count(workspace_claim.status, None)
    for dossier in store.list_dossiers(ot_dir):
        for dossier_claim in store.list_claims(ot_dir, dossier.id):
            _count(dossier_claim.status, dossier_claim.type)
        for proof in store.list_proof_attempts(ot_dir, dossier.id):
            attempts += 1
            gaps += len(proof.gaps or [])
    return claims, attempts, gaps


def _cost_summary(ot_dir: Path) -> CostSummary:
    from opentorus.usage import read_usage

    cost = CostSummary()
    models: set[str] = set()
    for record in read_usage(ot_dir):
        cost.model_calls += 1
        cost.prompt_tokens += record.prompt_tokens
        cost.completion_tokens += record.completion_tokens
        cost.wall_seconds += (record.latency_ms or 0) / 1000
        models.add(record.model)
    cost.models = sorted(models)
    return cost


# The workspace and dossier experiment stores use different status vocabularies for
# the same two ideas. Spelling both out here keeps the digest honest rather than
# silently reporting zero because it checked for the wrong word.
_RAN_STATUSES = frozenset({"completed", "succeeded"})
_FAILED_STATUSES = frozenset({"failed"})


def _experiment_counts(ot_dir: Path) -> tuple[int, int]:
    """Count runs across both stores.

    The agent's ``exp_new``/``exp_run`` write to the workspace store while the dossier
    keeps its own; a digest that reads only one of them under-reports the work done.
    """
    from opentorus.research.dossier import store
    from opentorus.research.dossier.experiments import list_problem_experiments
    from opentorus.research.experiments import list_experiments

    statuses: list[str] = [str(e.status) for e in list_experiments(ot_dir)]
    for dossier in store.list_dossiers(ot_dir):
        statuses.extend(str(e.status) for e in list_problem_experiments(ot_dir, dossier.id))
    ran = sum(1 for s in statuses if s in _RAN_STATUSES)
    failed = sum(1 for s in statuses if s in _FAILED_STATUSES)
    return ran, failed


def _flags(digest: RunDigest) -> list[str]:
    """Patterns that have previously marked a stuck run. Observations, not verdicts."""
    flags: list[str] = []
    if digest.total_calls == 0:
        flags.append("no tool calls at all — the model produced only chat")
    for dead_end in digest.dead_ends:
        if dead_end.count >= _REPEAT_FAILURE_FLAG:
            flags.append(
                f"{dead_end.tool} failed {dead_end.count}x with the same error: {dead_end.error}"
            )
    if digest.longest_search_streak >= _SEARCH_SPAM_FLAG:
        flags.append(
            f"{digest.longest_search_streak} consecutive searches with no fetch or read between"
        )
    if digest.verifier.submissions == 0 and digest.proof_attempts > 0:
        flags.append("a proof was written but nothing was ever submitted to a verifier")
    if digest.verifier.inconclusive and not digest.verifier.accepted:
        flags.append(
            f"{digest.verifier.inconclusive} inconclusive verifier run(s) and no acceptance — "
            "the checker never concluded, which is not a mathematical result either way"
        )
    if digest.experiments_failed and not digest.experiments_run:
        flags.append("every recorded experiment failed to run")
    if digest.cost.model_calls and digest.cost.prompt_share > 0.9:
        flags.append(
            f"{digest.cost.prompt_share:.0%} of processed tokens were re-sent prompt "
            f"({digest.cost.prompt_tokens:,} vs {digest.cost.completion_tokens:,})"
        )
    return flags


def digest_workspace(ot_dir: Path) -> RunDigest:
    """Summarize one finished ``.opentorus/`` workspace."""
    from opentorus.actions import list_actions

    digest = RunDigest(workspace=str(ot_dir))
    if not ot_dir.is_dir():
        digest.initialized = False
        return digest

    actions = list_actions(ot_dir)
    digest.tools, digest.total_calls, digest.total_failures = _tool_stats(actions)
    digest.dead_ends = _dead_ends(actions)
    digest.longest_search_streak = _longest_search_streak(actions)
    digest.verifier = _verifier_summary(ot_dir)
    digest.claims, digest.proof_attempts, digest.open_gaps = _claim_and_proof_summary(ot_dir)
    digest.experiments_run, digest.experiments_failed = _experiment_counts(ot_dir)
    digest.cost = _cost_summary(ot_dir)
    digest.flags = _flags(digest)
    return digest


def format_digest(digest: RunDigest) -> str:
    """Render a digest as plain text (the CLI adds colour)."""
    if not digest.initialized:
        return f"{digest.workspace}: not an OpenTorus workspace."
    lines = [f"Run digest — {digest.workspace}", ""]
    lines.append(
        f"Tool calls: {digest.total_calls} ({digest.total_failures} failed)"
        if digest.total_calls
        else "Tool calls: none"
    )
    for stat in digest.tools[:12]:
        suffix = f", {stat.failures} failed" if stat.failures else ""
        lines.append(f"  {stat.name}: {stat.calls}{suffix}")

    v = digest.verifier
    if v.submissions:
        lines.append(
            f"Verifier: {v.submissions} submission(s) — {v.accepted} accepted, "
            f"{v.rejected} rejected, {v.inconclusive} inconclusive"
            + (f", {v.cached} answered from cache" if v.cached else "")
            + (f" [{', '.join(v.backends)}]" if v.backends else "")
        )
    else:
        lines.append("Verifier: no submissions")

    if digest.claims.total:
        by_status = ", ".join(f"{k}={v}" for k, v in sorted(digest.claims.by_status.items()))
        lines.append(f"Claims: {digest.claims.total} ({by_status})")
    lines.append(
        f"Experiments: {digest.experiments_run} ran, {digest.experiments_failed} failed; "
        f"proof attempts: {digest.proof_attempts}, open gaps: {digest.open_gaps}"
    )

    c = digest.cost
    if c.model_calls:
        lines.append(
            f"Model: {c.model_calls} calls, {c.prompt_tokens:,} prompt / "
            f"{c.completion_tokens:,} completion tokens ({c.prompt_share:.0%} prompt), "
            f"{c.wall_seconds / 60:.1f} min" + (f" [{', '.join(c.models)}]" if c.models else "")
        )

    if digest.dead_ends:
        lines.append("")
        lines.append("Repeated failures:")
        for dead_end in digest.dead_ends[:8]:
            lines.append(f"  {dead_end.count}x {dead_end.tool}: {dead_end.error}")

    if digest.flags:
        lines.append("")
        lines.append("Flags (patterns, not verdicts):")
        lines.extend(f"  - {flag}" for flag in digest.flags)
    return "\n".join(lines)
