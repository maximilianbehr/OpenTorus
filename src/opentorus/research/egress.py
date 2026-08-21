"""Network-egress guard for literature access (Milestone 44).

Every outbound request the agent makes for literature flows through one guard so
network use is *safe* (policy-gated by mode/style/review), *consent-gated* (each
new host confirmed once in ask mode), *throttled* (per-host rate limit and a
daily request budget), and *honest about credentials* (keys and session material
are redacted from any log line — the guard never receives them and refuses
systematic bulk harvesting by design).
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from opentorus.config import OperatingStyle, PermissionMode
from opentorus.permissions.policy import evaluate_egress

ConfirmFn = Callable[[str], bool]


class EgressBlocked(RuntimeError):
    """Raised when a network request is denied by policy, budget, or rate limit."""


def host_of(url_or_host: str) -> str:
    """Return the bare hostname for a URL or host string (lowercased)."""
    candidate = url_or_host.strip()
    if "://" in candidate:
        netloc = urlparse(candidate).netloc
    else:
        netloc = candidate.split("/", 1)[0]
    return netloc.split("@")[-1].split(":")[0].lower()


# Token-like material that must never reach a log line.
_SECRET_QUERY_KEYS = ("api_key", "apikey", "key", "token", "access_token", "password")
_SECRET_RE = re.compile(r"([?&](?:" + "|".join(_SECRET_QUERY_KEYS) + r")=)[^&\s]+", re.IGNORECASE)


def redact(text: str) -> str:
    """Strip credential-bearing query parameters from a URL/string for logging."""
    return _SECRET_RE.sub(r"\1REDACTED", text)


class EgressGuard:
    """Stateful guard combining egress policy, host consent, and throttling."""

    def __init__(
        self,
        mode: PermissionMode,
        *,
        style: OperatingStyle = "normal",
        review: bool = False,
        rate_limit_per_minute: int = 20,
        daily_request_budget: int = 500,
        confirm: ConfirmFn | None = None,
        ledger_path: Path | None = None,
        clock: Callable[[], float] = time.monotonic,
        dlp: bool = True,
    ) -> None:
        self.mode = mode
        self.style = style
        self.review = review
        self.rate_limit_per_minute = rate_limit_per_minute
        self.daily_request_budget = daily_request_budget
        self._confirm = confirm
        self._ledger_path = ledger_path
        self._clock = clock
        self.dlp = dlp
        self._confirmed_hosts: set[str] = set()
        self._recent: dict[str, list[float]] = {}
        self._day, self._day_count = self._load_budget()

    def _today(self) -> str:
        return datetime.now(UTC).strftime("%Y-%m-%d")

    def _read_ledger(self) -> dict:
        if self._ledger_path and self._ledger_path.is_file():
            try:
                data = json.loads(self._ledger_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                return {}
            return data if isinstance(data, dict) else {}
        return {}

    def _load_budget(self) -> tuple[str, int]:
        today = self._today()
        data = self._read_ledger()
        if data.get("day") == today:
            return today, int(data.get("count", 0))
        return today, 0

    def _recent_on_disk(self, host: str, wall_now: float) -> list[float]:
        """Wall-clock timestamps of this host's requests inside the last minute.

        The in-memory window cannot throttle anything in production: the tools build
        a **fresh guard for every call**, so its window is always empty. Measured with
        a 2/min limit — one guard blocks the third request, a fresh guard per request
        allows six in a row, which is exactly the bulk-harvesting the daily budget
        alone was never meant to be the only defence against. Wall clock, not the
        injected ``clock``: ``time.monotonic`` is process-local and meaningless to the
        next process reading this file.
        """
        hosts = self._read_ledger().get("hosts")
        if not isinstance(hosts, dict):
            return []
        stamps = hosts.get(host)
        if not isinstance(stamps, list):
            return []
        return [float(t) for t in stamps if isinstance(t, (int, float)) and wall_now - t < 60.0]

    def _persist_budget(self, host: str | None = None, wall_now: float | None = None) -> None:
        if not self._ledger_path:
            return
        from opentorus.atomicio import atomic_write_text, file_lock

        # Read-modify-write on a file other runs share: hold the lock across both.
        with file_lock(self._ledger_path):
            data = self._read_ledger()
            hosts = data.get("hosts")
            hosts = dict(hosts) if isinstance(hosts, dict) else {}
            if host is not None and wall_now is not None:
                kept = [
                    float(t)
                    for t in hosts.get(host, [])
                    if isinstance(t, (int, float)) and wall_now - t < 60.0
                ]
                kept.append(wall_now)
                hosts[host] = kept
            # Drop hosts whose window has fully elapsed so the ledger stays small.
            if wall_now is not None:
                hosts = {
                    h: ts for h, ts in hosts.items() if any(wall_now - float(t) < 60.0 for t in ts)
                }
            atomic_write_text(
                self._ledger_path,
                json.dumps({"day": self._day, "count": self._day_count, "hosts": hosts}),
            )

    def authorize(self, url_or_host: str) -> str:
        """Authorize one request; returns the host or raises :class:`EgressBlocked`.

        On success the request is counted against the per-host rate limit and the
        daily budget. Credentials are never part of the host and never logged.
        """
        host = host_of(url_or_host)
        decision = evaluate_egress(host, self.mode, style=self.style, review=self.review)
        if not decision.allowed:
            raise EgressBlocked(decision.reason)

        if decision.requires_confirmation and host not in self._confirmed_hosts:
            if self._confirm is None or not self._confirm(host):
                raise EgressBlocked(f"Network egress to '{host}' was not confirmed.")
            self._confirmed_hosts.add(host)

        now = self._clock()
        self._enforce_rate_limit(host, now)
        self._enforce_budget()
        self._record(host, now)
        return host

    def screen_payload(self, text: str) -> None:
        """Pre-egress DLP on a request *body* before it leaves the machine (M75).

        Fails closed: a detected secret/PII raises :class:`DlpBlocked`. Authorized
        URLs are *not* screened here (credentials in keyed query params are
        legitimate and already redacted from logs) — only payload bodies are.
        """
        if not self.dlp:
            return
        from opentorus.governance import assert_egress_safe

        assert_egress_safe(text)

    def _enforce_rate_limit(self, host: str, now: float) -> None:
        window = [t for t in self._recent.get(host, []) if now - t < 60.0]
        self._recent[host] = window
        # With a ledger the on-disk window is authoritative — it is the only one that
        # survives the per-call guard the tools construct. Without one (unit tests,
        # a bare guard) the in-memory window keeps its old, clock-injectable meaning.
        count = len(self._recent_on_disk(host, time.time())) if self._ledger_path else len(window)
        if count >= self.rate_limit_per_minute:
            raise EgressBlocked(
                f"Rate limit reached for '{host}' "
                f"({self.rate_limit_per_minute}/min); throttling to respect the source."
            )

    def _enforce_budget(self) -> None:
        if self._today() != self._day:
            self._day, self._day_count = self._today(), 0
        # Reconcile with the on-disk ledger so a concurrent or earlier run's requests
        # are counted: the in-memory count alone would undercount and overrun the cap.
        disk_day, disk_count = self._load_budget()
        if disk_day == self._day:
            self._day_count = max(self._day_count, disk_count)
        if self._day_count >= self.daily_request_budget:
            raise EgressBlocked(
                f"Daily request budget of {self.daily_request_budget} reached; "
                "stopping to avoid bulk harvesting."
            )

    def _record(self, host: str, now: float) -> None:
        self._recent.setdefault(host, []).append(now)
        # Re-read before incrementing so concurrent runs do not clobber each other's
        # totals (read-modify-write on the shared ledger); the count stays monotone.
        disk_day, disk_count = self._load_budget()
        if disk_day == self._day:
            self._day_count = max(self._day_count, disk_count)
        self._day_count += 1
        self._persist_budget(host=host, wall_now=time.time())
