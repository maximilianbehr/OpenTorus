"""Local usage and cost ledger (Milestone 31).

Every provider turn is recorded as one inspectable JSONL line under
``.opentorus/usage/ledger.jsonl``: provider, model, estimated prompt/completion
tokens, latency, and an estimated cost in USD. Token counts are estimated
locally (no network), so the ledger works fully offline; cost uses a small,
explicit price table and is clearly marked as an estimate. The ledger is for
transparency and budgeting, not billing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.jsonl import append_jsonl, read_jsonl

LEDGER_DIRNAME = "usage"
LEDGER_FILENAME = "ledger.jsonl"

# Approximate published prices in USD per 1M tokens: (input, output).
# Local models (e.g. via Ollama) are free. Unknown models fall back to (0, 0)
# and are reported as an unknown/estimated cost of $0.
_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "o3-mini": (1.10, 4.40),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-opus": (15.00, 75.00),
}


class UsageRecord(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    session_id: str | None = None
    provider: str = "unknown"
    model: str = "unknown"
    prompt_tokens: int = 0
    completion_tokens: int = 0
    # Reasoning/thinking tokens, a subset of completion_tokens (not added on top).
    thinking_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    cost_estimated: bool = True
    # False when prompt/completion tokens are the provider's exact counts rather
    # than a local character-count estimate.
    tokens_estimated: bool = True
    # Model-routing transparency (Phase 24, M75): which task class chose this model.
    task_class: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def _price_for(model: str) -> tuple[float, float] | None:
    name = model.lower()
    if name in _PRICE_PER_MTOK:
        return _PRICE_PER_MTOK[name]
    # Tolerate version suffixes like "claude-3-5-sonnet-20241022".
    for key, price in _PRICE_PER_MTOK.items():
        if name.startswith(key):
            return price
    return None


def is_local_provider(provider: str) -> bool:
    """A local provider (mock/ollama) genuinely costs nothing."""
    return provider.lower() in {"mock", "ollama"}


def cost_known(provider: str, model: str) -> bool:
    """Whether the cost can be priced: local (free) or a model with a known rate."""
    return is_local_provider(provider) or _price_for(model) is not None


def estimate_cost(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """Estimate cost in USD. Local providers cost $0; an unknown paid model returns 0.0.

    A 0.0 here is ambiguous (free local vs unknown-price paid); callers that render
    cost should consult :func:`cost_known` to distinguish the two honestly.
    """
    if is_local_provider(provider):
        return 0.0
    price = _price_for(model)
    if price is None:
        return 0.0
    input_rate, output_rate = price
    return (prompt_tokens * input_rate + completion_tokens * output_rate) / 1_000_000


def ledger_path(ot_dir: Path) -> Path:
    return ot_dir / LEDGER_DIRNAME / LEDGER_FILENAME


def record_usage(ot_dir: Path, record: UsageRecord) -> UsageRecord:
    append_jsonl(ledger_path(ot_dir), record)
    return record


def read_usage(ot_dir: Path, session_id: str | None = None) -> list[UsageRecord]:
    records = read_jsonl(ledger_path(ot_dir), UsageRecord)
    if session_id is not None:
        records = [r for r in records if r.session_id == session_id]
    return records


class UsageSummary(BaseModel):
    turns: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    thinking_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    avg_latency_ms: int = 0
    by_model: dict[str, int] = Field(default_factory=dict)
    # True when any turn's tokens are a local estimate (so the total is approximate).
    tokens_estimated: bool = False


def summarize_usage(ot_dir: Path, session_id: str | None = None) -> UsageSummary:
    records = read_usage(ot_dir, session_id)
    if not records:
        return UsageSummary()
    summary = UsageSummary(
        turns=len(records),
        prompt_tokens=sum(r.prompt_tokens for r in records),
        completion_tokens=sum(r.completion_tokens for r in records),
        thinking_tokens=sum(r.thinking_tokens for r in records),
        cost_usd=round(sum(r.cost_usd for r in records), 6),
        avg_latency_ms=round(sum(r.latency_ms for r in records) / len(records)),
    )
    summary.total_tokens = summary.prompt_tokens + summary.completion_tokens
    summary.tokens_estimated = any(r.tokens_estimated for r in records)
    for record in records:
        summary.by_model[record.model] = summary.by_model.get(record.model, 0) + record.total_tokens
    return summary


def _fmt_tokens(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def format_usage_line(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    *,
    thinking_tokens: int = 0,
    session_cost: float | None = None,
    tokens_estimated: bool = True,
) -> str:
    """A compact per-step token/cost line for the verbose trace.

    Cost is the same estimate written to the ledger; local providers read ``$0``.
    Tokens are tagged ``~`` when locally estimated and ``=`` when they are the
    provider's exact counts. Reasoning models also show how many output tokens
    were thinking (a subset of ``out``).
    """
    total = prompt_tokens + completion_tokens
    cost = estimate_cost(provider, model, prompt_tokens, completion_tokens)
    if is_local_provider(provider):
        cost_str = "$0 (local)"
    elif not cost_known(provider, model):
        # A paid cloud model with no known rate must not read as free.
        cost_str = "$? (price unknown)"
    else:
        cost_str = f"~${cost:.4f}"
    sigil = "~" if tokens_estimated else "="
    out = f"{_fmt_tokens(completion_tokens)} out"
    if thinking_tokens > 0:
        out += f", {_fmt_tokens(thinking_tokens)} think"
    line = (
        f"↳ {sigil}{_fmt_tokens(total)} tok ({_fmt_tokens(prompt_tokens)} in / {out}) · {cost_str}"
    )
    if session_cost is not None and session_cost > 0:
        line += f" · session ~${session_cost:.4f}"
    return line


def format_usage_total(summary: UsageSummary) -> str:
    """A run-end summary line: cumulative input/output tokens and estimated cost."""
    cost_str = "$0 (local)" if summary.cost_usd == 0 else f"~${summary.cost_usd:.4f}"
    sigil = "~" if summary.tokens_estimated else "="
    out = f"{_fmt_tokens(summary.completion_tokens)} out"
    if summary.thinking_tokens > 0:
        out += f", {_fmt_tokens(summary.thinking_tokens)} think"
    return (
        f"Σ {summary.turns} turn(s): {sigil}{_fmt_tokens(summary.total_tokens)} tok "
        f"({_fmt_tokens(summary.prompt_tokens)} in / {out}) · {cost_str}"
    )
