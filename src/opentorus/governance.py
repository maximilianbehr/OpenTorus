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
    ("github_pat", r"\bgithub_pat_[A-Za-z0-9_]{40,}\b"),
    ("huggingface_token", r"\bhf_[A-Za-z0-9]{30,}\b"),
    ("slack_token", r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    ("google_api_key", r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    (
        "private_key_block",
        r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP |ENCRYPTED )?PRIVATE KEY(?: BLOCK)?-----",
    ),
    ("jwt", r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    (
        "authorization_header",
        r"(?i)\bauthorization\b[\"']?\s*[:=]\s*[\"']?(?:bearer|basic|token|bot)\s+"
        r"(?P<value>[A-Za-z0-9._~+/=-]{8,})",
    ),
    ("bearer_token", r"\b[Bb]earer\s+(?P<value>[A-Za-z0-9._-]{20,})\b"),
    (
        "url_credentials",
        r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/:@'\"<>]+:(?P<value>[^\s/@'\"<>]{3,})@[^\s/'\"<>]+",
    ),
    (
        "assigned_secret",
        r"(?i)\b(?:api[_-]?key|secret|password|passwd|token)\b\s*[:=]\s*(?P<value>\S{6,})",
    ),
    # KEY=VALUE / KEY: VALUE for credential-named variables (HF_TOKEN=..., DB_PASSWORD:
    # ...). The value must look like a secret -- no code expression -- so
    # ``num_tokens = len(tokens)`` stays prose.
    (
        "env_assignment",
        r"(?<![A-Za-z0-9])[A-Za-z0-9_]*(?:API_?KEY|ACCESS_?KEY|SECRET|TOKEN|PASSWORD|PASSWD)"
        r"[A-Za-z0-9_]*[\"']?\s*[:=]\s*[\"']?(?P<value>[A-Za-z0-9_\-+/=.~]{8,})",
    ),
]
_SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (name, re.compile(pat)) for name, pat in _SECRET_SPECS
]

# Values that are obviously not real credentials: documentation placeholders,
# template variables and masks. Matched against the value part of assignment-style
# rules only -- a literal key format (sk-..., AKIA...) is never "a placeholder".
_PLACEHOLDER_RE = re.compile(
    r"""(?ix)^(?:
        x{3,}.*|.*x{6,}.*|\*{3,}.*|\.{3,}|_+|-+|
        <[^>]*>|\{\{.*\}\}|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|%\([^)]*\)s|%s|
        .*(?:changeme|change[_-]?me|replace[_-]?me|your[_-]?(?:api[_-]?)?(?:key|token|secret|password)
           |placeholder|example|dummy|redacted|sample|fake|test[_-]?(?:key|token)|not[_-]?a[_-]?secret
           |insert[_-]?here|todo|none|null|undefined).*
    )$"""
)
# Rules whose match carries a free-form value that may be a placeholder.
_VALUE_RULES = frozenset(
    {"assigned_secret", "env_assignment", "url_credentials", "authorization_header", "bearer_token"}
)


_EXACT_PLACEHOLDERS = frozenset(
    {"password", "pass", "passwd", "pwd", "pw", "secret", "token", "key", "apikey", "api_key"}
)


def _is_placeholder(value: str) -> bool:
    v = value.strip("\"'`,;)")
    return v.lower() in _EXACT_PLACEHOLDERS or bool(_PLACEHOLDER_RE.match(v))


_CODE_VALUE_RE = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+")
_CODE_WORDS = frozenset(
    {"api_key", "apikey", "token", "tokens", "secret", "password", "passwd", "true", "false"}
)


def _looks_like_code(value: str) -> bool:
    """``token = match.group(0)``, ``api_key = self.api_key`` -- an expression, not a value."""
    v = value.strip("\"'`,;")
    return (
        any(c in v for c in "()[]{}") or bool(_CODE_VALUE_RE.match(v)) or v.lower() in _CODE_WORDS
    )


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")


# PII is not a secret. A credential in a payload is a compromise; an author's email
# address inside a paper the user deliberately fetched is public bibliographic data,
# and every academic PDF has several. Blocking on it made the flagship workflow —
# fetch papers, read them, reason — impossible with any cloud provider, and the advice
# it printed ("disable governance.dlp") traded away all secret protection to get past
# an email. They are separated here so PII can be redacted while secrets still block.
PII_KINDS: frozenset[str] = frozenset({"email"})
PII_REDACTION = "[redacted: email]"


def redact_pii(text: str) -> str:
    """Replace PII with a marker. Secrets are never redacted — those block the send."""
    return _EMAIL_RE.sub(PII_REDACTION, text)


def split_findings(
    findings: list[SecretFinding],
) -> tuple[list[SecretFinding], list[SecretFinding]]:
    """``(secrets, pii)`` — the two halves get different treatment."""
    return (
        [f for f in findings if f.kind not in PII_KINDS],
        [f for f in findings if f.kind in PII_KINDS],
    )


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


def _secret_matches(text: str) -> list[tuple[str, re.Match[str]]]:
    """Secret matches in ``text`` (placeholders suppressed), earliest first."""
    out: list[tuple[str, re.Match[str]]] = []
    for kind, pattern in _SECRET_PATTERNS:
        for match in pattern.finditer(text):
            if kind in _VALUE_RULES:
                value = match.groupdict().get("value") or ""
                if _is_placeholder(value):
                    continue
                if kind in ("assigned_secret", "env_assignment") and _looks_like_code(value):
                    continue
                if kind == "env_assignment" and not (
                    any(c.isdigit() for c in value) or len(value) >= 20
                ):
                    continue
            out.append((kind, match))
    out.sort(key=lambda item: item[1].start())
    return out


def _mask(secret: str) -> str:
    """A masked preview: enough to recognise which value it was, never enough to use it."""
    head = secret[:4] if len(secret) >= 12 else ""
    return f"{head}…" if head else "…"


def redact_secrets(text: str) -> tuple[str, list[SecretFinding]]:
    """Replace every detected secret in ``text`` with a masked marker.

    Used before anything is written to a log or put into an export. Works on the
    text as given (no normalization) so offsets stay valid; the DLP send path still
    scans the normalized form.
    """
    matches = _secret_matches(text)
    if not matches:
        return text, []
    findings: list[SecretFinding] = []
    pieces: list[str] = []
    cursor = 0
    for kind, match in matches:
        start, end = match.span()
        if "value" in match.re.groupindex and match.group("value"):
            start, end = match.span("value")
        if start < cursor:
            continue  # overlaps a span already redacted
        secret = text[start:end]
        pieces.append(text[cursor:start])
        pieces.append(f"{_mask(secret)}[redacted:{kind}]")
        findings.append(SecretFinding(kind=kind, excerpt=_mask(secret) + "(redacted)"))
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), findings


def redact_secrets_in(value: object) -> object:
    """:func:`redact_secrets` applied to every string inside a JSON-like value."""
    if isinstance(value, str):
        return redact_secrets(value)[0]
    if isinstance(value, dict):
        return {k: redact_secrets_in(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_secrets_in(v) for v in value]
    if isinstance(value, tuple):
        return tuple(redact_secrets_in(v) for v in value)
    return value


class FileFinding(BaseModel):
    path: str
    kind: str
    line: int
    excerpt: str


# Never scanned: version control, caches, virtualenvs, and the scan's own outputs.
_SCAN_SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
    }
)
_SCAN_MAX_BYTES = 5 * 1024 * 1024


def scan_path(path: Path) -> list[FileFinding]:
    """Scan a file, or every text file under a directory, for secrets (not PII)."""
    root = Path(path)
    files = (
        [root]
        if root.is_file()
        else sorted(
            p
            for p in root.rglob("*")
            if p.is_file()
            and not p.is_symlink()
            and not any(part in _SCAN_SKIP_DIRS for part in p.relative_to(root).parts)
        )
    )
    findings: list[FileFinding] = []
    for file in files:
        try:
            if file.stat().st_size > _SCAN_MAX_BYTES:
                continue
            data = file.read_bytes()
        except OSError:
            continue
        if b"\0" in data[:8192]:
            continue  # binary
        text = data.decode("utf-8", errors="replace")
        rel = file.name if file == root else file.relative_to(root).as_posix()
        for line_no, line in enumerate(text.splitlines(), start=1):
            end = -1
            for kind, match in _secret_matches(line):
                if match.start() < end:
                    continue  # one finding per secret, not one per rule that sees it
                end = match.end()
                findings.append(
                    FileFinding(path=rel, kind=kind, line=line_no, excerpt=_excerpt(match))
                )
    return findings


class SecretsInExport(OpenTorusError):
    """An export would contain secrets and was refused (``on_secret="refuse"``)."""


def screen_export_entries(
    entries: list[tuple[str, bytes]], *, on_secret: str = "redact"
) -> tuple[list[tuple[str, bytes]], list[FileFinding]]:
    """Scan export entries for secrets; redact them (default) or refuse the export.

    Binary entries are passed through unscanned. Returns the (possibly redacted)
    entries and every finding, with the archive name as the path.
    """
    if on_secret not in ("redact", "refuse"):
        raise ValueError("on_secret must be 'redact' or 'refuse'")
    out: list[tuple[str, bytes]] = []
    findings: list[FileFinding] = []
    for name, data in entries:
        if b"\0" in data[:8192]:
            out.append((name, data))
            continue
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines(keepends=True)
        changed = False
        for i, line in enumerate(lines):
            redacted, found = redact_secrets(line)
            if found:
                changed = True
                lines[i] = redacted
                findings.extend(
                    FileFinding(path=name, kind=f.kind, line=i + 1, excerpt=f.excerpt)
                    for f in found
                )
        out.append((name, "".join(lines).encode("utf-8") if changed else data))
    if findings and on_secret == "refuse":
        where = ", ".join(sorted({f"{f.path}:{f.line} ({f.kind})" for f in findings})[:10])
        raise SecretsInExport(f"Export refused: {len(findings)} secret(s) found -- {where}.")
    return out, findings


def scan_secrets(text: str, *, scan_pii: bool = True) -> list[SecretFinding]:
    """Return secret/PII findings in ``text`` (excerpts are redacted, never raw).

    The text is normalized first (zero-width removal, homoglyph folding) so a secret
    split by a zero-width character or disguised with look-alike letters is still
    detected — the scanner fails closed against trivial evasion.
    """
    from opentorus.textnorm import normalize_for_scan

    text = normalize_for_scan(text)
    findings: list[SecretFinding] = []
    for kind, match in _secret_matches(text):
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
    # Set when the figure above cannot be trusted — e.g. calls that could not be priced.
    note: str | None = None

    @property
    def message(self) -> str:
        state = "BREACHED" if self.breached else "ok"
        unit = "$" if self.metric == "cost_usd" else ""
        line = f"[{state}] {self.scope} {self.metric}: {unit}{self.spent:g} / {unit}{self.cap:g}"
        return f"{line} — {self.note}" if self.note else line


def budget_alerts(
    ot_dir: Path,
    config: Config,
    *,
    session_id: str | None = None,
    campaign_id: str | None = None,
) -> list[BudgetAlert]:
    """Compare recorded usage against configured caps; return all alerts.

    ``breached`` flags caps that are met or exceeded. Per-provider caps are
    evaluated against that provider's spend; total cost/token caps against the
    investigation (optionally a single session and/or a single campaign — a
    campaign's workers run under many session ids, so the campaign id is the
    axis that makes its budget non-vacuous).
    """
    from opentorus.usage import read_usage

    records = read_usage(ot_dir, session_id, campaign_id=campaign_id)
    budgets = config.governance.budgets
    alerts: list[BudgetAlert] = []

    total_cost = sum(r.cost_usd for r in records)
    # Calls that could not be priced contribute 0.0 to total_cost. Reporting
    # "$0.00 / $50.00" while those calls are billing real money is the worst kind of
    # wrong: the user asked for a cap and got a number that cannot move.
    unpriced = sum(1 for r in records if not getattr(r, "cost_known", True))
    total_tokens = sum(r.total_tokens for r in records)

    if budgets.cost_budget_usd is not None and unpriced:
        models = sorted({r.model for r in records if not getattr(r, "cost_known", True)})
        alerts.append(
            BudgetAlert(
                scope="total",
                metric="cost_usd",
                spent=total_cost,
                cap=budgets.cost_budget_usd,
                breached=False,
                note=(
                    f"cost_budget_usd cannot bind: {unpriced} call(s) to "
                    f"{', '.join(models)} have no known price, so they count as $0. "
                    "Use governance.budgets.token_budget for a cap that holds."
                ),
            )
        )
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
    ot_dir: Path,
    config: Config,
    *,
    session_id: str | None = None,
    campaign_id: str | None = None,
) -> list[BudgetAlert]:
    return [
        a
        for a in budget_alerts(ot_dir, config, session_id=session_id, campaign_id=campaign_id)
        if a.breached
    ]


class BudgetExceeded(OpenTorusError):
    """Raised when a hard budget cap is reached and work must stop cleanly."""


def assert_within_budget(
    ot_dir: Path,
    config: Config,
    *,
    session_id: str | None = None,
    campaign_id: str | None = None,
) -> None:
    """Raise :class:`BudgetExceeded` if any configured budget is breached."""
    breached = breached_budgets(ot_dir, config, session_id=session_id, campaign_id=campaign_id)
    if breached:
        reasons = "; ".join(a.message for a in breached)
        raise BudgetExceeded(f"Budget reached, stopping cleanly: {reasons}")


# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------

TaskClass = str  # any value of ``providers.pool.TaskClass``, or a legacy alias


def _valid_task_classes() -> tuple[str, ...]:
    from opentorus.providers.pool import LEGACY_TASK_ALIASES
    from opentorus.providers.pool import TaskClass as _TaskClass

    names = list(LEGACY_TASK_ALIASES)
    names.extend(tc.value for tc in _TaskClass if tc.value not in names)
    return tuple(names)


VALID_TASK_CLASSES: tuple[str, ...] = _valid_task_classes()


class RoutingDecision(BaseModel):
    task_class: str
    model: str
    rationale: str


def route_model(config: Config, task_class: str) -> RoutingDecision:
    """Pick the model for a task class per policy, falling back to ``model.name``.

    A compatibility view over :class:`opentorus.providers.pool.ProviderPool`: the
    pool decides (``task_routes`` first, then legacy ``task_models``, then the
    default profile) and this reports the *model name* of its first candidate with
    the historical rationale strings. Callers that need the provider itself — and
    the ledger record — should acquire from the pool directly.
    """
    from opentorus.providers.pool import ProviderPool

    routing = config.governance.routing
    default_model = config.model.name
    if not routing.enabled:
        return RoutingDecision(
            task_class=task_class,
            model=default_model,
            rationale="routing disabled; using model.name",
        )
    pool = ProviderPool(config)
    candidates = pool.candidates(task_class)
    if candidates and pool.route_source(task_class) != "default":
        profile = pool.profiles().get(candidates[0])
        return RoutingDecision(
            task_class=task_class,
            model=profile.name if profile is not None else candidates[0],
            rationale=f"routed '{task_class}' to configured model",
        )
    return RoutingDecision(
        task_class=task_class,
        model=default_model,
        rationale=f"no route for '{task_class}'; using model.name",
    )
