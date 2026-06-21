"""Governance: pre-egress DLP, budgets, and model routing (Milestone 75).

Three controls harden cost, secrets, and model use without loosening safety:

* **Pre-egress DLP** — a final secret/PII scan on any payload before it leaves
  the machine (to a provider or a network host), extending the M20/M44 redaction.
  It *fails closed*: a detected secret blocks the send and reports why.
* **Budget governance** — per-provider and per-investigation cost/token budgets
  with alerts, on top of the usage ledger (M31). A breach stops cleanly.
* **Model routing** — a policy picking a cheaper model for planning/narration and
  a stronger one for proofs/critique, recorded per turn for transparency.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from opentorus.config import Config
from opentorus.errors import OpenTorusError

# ---------------------------------------------------------------------------
# Pre-egress DLP
# ---------------------------------------------------------------------------

# High-signal secret/PII patterns. Kept deliberately conservative to fail closed
# without flagging ordinary prose. Each entry is (name, compiled regex).
_SECRET_SPECS: list[tuple[str, str]] = [
    ("openai_key", r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9_-]{20,}\b"),
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("github_token", r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    ("private_key_block", r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    ("bearer_token", r"\b[Bb]earer\s+[A-Za-z0-9._-]{20,}\b"),
    ("assigned_secret", r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*\S{6,}"),
]
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pat)) for name, pat in _SECRET_SPECS
]
_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


class SecretFinding(BaseModel):
    kind: str
    excerpt: str


class DlpResult(BaseModel):
    allowed: bool
    findings: list[SecretFinding] = Field(default_factory=list)

    @property
    def reason(self) -> str:
        if self.allowed:
            return "No secrets detected."
        kinds = ", ".join(sorted({f.kind for f in self.findings}))
        return f"Blocked pre-egress: detected {kinds}."


class DlpBlocked(OpenTorusError):
    """Raised when a payload contains secret/PII material and must not be sent."""


def _excerpt(match: re.Match[str]) -> str:
    text = match.group(0)
    head = text[:6]
    return f"{head}…(redacted)" if len(text) > 6 else "…(redacted)"


def scan_secrets(text: str, *, scan_pii: bool = True) -> list[SecretFinding]:
    """Return secret/PII findings in ``text`` (excerpts are redacted, never raw).

    The text is normalized first (zero-width removal, homoglyph folding) so a secret
    split by a zero-width character or disguised with look-alike letters is still
    detected — the scanner fails closed against trivial evasion.
    """
    from opentorus.textnorm import normalize_for_scan

    text = normalize_for_scan(text)
    findings: list[SecretFinding] = []
    for kind, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            findings.append(SecretFinding(kind=kind, excerpt=_excerpt(match)))
    if scan_pii:
        for match in _EMAIL_RE.finditer(text):
            findings.append(SecretFinding(kind="email", excerpt=_excerpt(match)))
    return findings


def dlp_check(text: str, *, scan_pii: bool = True) -> DlpResult:
    findings = scan_secrets(text, scan_pii=scan_pii)
    return DlpResult(allowed=not findings, findings=findings)


def assert_egress_safe(text: str, config: Config | None = None, *, scan_pii: bool = True) -> None:
    """Fail closed if ``text`` contains secrets/PII and DLP is enabled.

    With ``config`` and ``governance.dlp`` disabled this is a no-op; otherwise a
    detected secret raises :class:`DlpBlocked` with a redacted reason.
    """
    if config is not None and not config.governance.dlp:
        return
    result = dlp_check(text, scan_pii=scan_pii)
    if not result.allowed:
        raise DlpBlocked(result.reason)


# ---------------------------------------------------------------------------
# Budget governance
# ---------------------------------------------------------------------------


class BudgetAlert(BaseModel):
    scope: str  # "total" | "tokens" | provider name
    metric: str  # "cost_usd" | "tokens"
    spent: float
    cap: float
    breached: bool

    @property
    def message(self) -> str:
        state = "BREACHED" if self.breached else "ok"
        unit = "$" if self.metric == "cost_usd" else ""
        return f"[{state}] {self.scope} {self.metric}: {unit}{self.spent:g} / {unit}{self.cap:g}"


def budget_alerts(
    ot_dir: Path, config: Config, *, session_id: str | None = None
) -> list[BudgetAlert]:
    """Compare recorded usage against configured caps; return all alerts.

    ``breached`` flags caps that are met or exceeded. Per-provider caps are
    evaluated against that provider's spend; total cost/token caps against the
    investigation (optionally a single session).
    """
    from opentorus.usage import read_usage

    records = read_usage(ot_dir, session_id)
    budgets = config.governance.budgets
    alerts: list[BudgetAlert] = []

    total_cost = sum(r.cost_usd for r in records)
    total_tokens = sum(r.total_tokens for r in records)

    if budgets.cost_budget_usd is not None:
        alerts.append(
            BudgetAlert(
                scope="total",
                metric="cost_usd",
                spent=round(total_cost, 6),
                cap=budgets.cost_budget_usd,
                breached=total_cost >= budgets.cost_budget_usd,
            )
        )
    if budgets.token_budget is not None:
        alerts.append(
            BudgetAlert(
                scope="tokens",
                metric="tokens",
                spent=total_tokens,
                cap=budgets.token_budget,
                breached=total_tokens >= budgets.token_budget,
            )
        )
    for provider, cap in sorted(budgets.per_provider_usd.items()):
        spent = sum(r.cost_usd for r in records if r.provider == provider)
        alerts.append(
            BudgetAlert(
                scope=provider,
                metric="cost_usd",
                spent=round(spent, 6),
                cap=cap,
                breached=spent >= cap,
            )
        )
    return alerts


def breached_budgets(
    ot_dir: Path, config: Config, *, session_id: str | None = None
) -> list[BudgetAlert]:
    return [a for a in budget_alerts(ot_dir, config, session_id=session_id) if a.breached]


class BudgetExceeded(OpenTorusError):
    """Raised when a hard budget cap is reached and work must stop cleanly."""


def assert_within_budget(ot_dir: Path, config: Config, *, session_id: str | None = None) -> None:
    """Raise :class:`BudgetExceeded` if any configured budget is breached."""
    breached = breached_budgets(ot_dir, config, session_id=session_id)
    if breached:
        reasons = "; ".join(a.message for a in breached)
        raise BudgetExceeded(f"Budget reached, stopping cleanly: {reasons}")


# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------

TaskClass = str  # "planning" | "narration" | "proof" | "critique" | "default" | ...
VALID_TASK_CLASSES: tuple[str, ...] = (
    "planning",
    "narration",
    "proof",
    "critique",
    "default",
)


class RoutingDecision(BaseModel):
    task_class: str
    model: str
    rationale: str


def route_model(config: Config, task_class: str) -> RoutingDecision:
    """Pick the model for a task class per policy, falling back to ``model.name``.

    With routing disabled (the default), every task uses the configured model.
    The decision is returned so callers can record it per turn for transparency.
    """
    routing = config.governance.routing
    default_model = config.model.name
    if not routing.enabled:
        return RoutingDecision(
            task_class=task_class,
            model=default_model,
            rationale="routing disabled; using model.name",
        )
    mapped = routing.task_models.get(task_class) or routing.task_models.get("default")
    if mapped:
        return RoutingDecision(
            task_class=task_class,
            model=mapped,
            rationale=f"routed '{task_class}' to configured model",
        )
    return RoutingDecision(
        task_class=task_class,
        model=default_model,
        rationale=f"no route for '{task_class}'; using model.name",
    )
