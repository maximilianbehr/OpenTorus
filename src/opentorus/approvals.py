"""Ergonomic, safe approval prompts for the agent loop.

When the permission policy says an action ``requires_confirmation``, the loop
calls a confirmation callback. This module turns that into a clear, ergonomic
prompt with three choices:

* allow once -- run this one action;
* allow for this session -- auto-approve identical actions for the rest of the
  session (in memory only, never persisted);
* deny.

Safety guarantee: high-risk actions (destructive commands, sensitive files) can
never be blanket-approved. Even if the user picks "session", such actions are
treated as allow-once, so they are confirmed every time. Dangerous commands are
blocked by policy before they ever reach an approval prompt.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from opentorus.permissions.policy import PermissionDecision

ApprovalChoice = Literal["once", "session", "deny"]
# Asks the user and returns their choice. ``blanket_allowed`` indicates whether
# "allow for session" is offered for this particular action.
AskFn = Callable[[PermissionDecision, str, bool], ApprovalChoice]


def can_blanket(decision: PermissionDecision) -> bool:
    """Whether an action is eligible for session-wide blanket approval.

    Only low/medium-risk, allowed actions qualify. High-risk (destructive
    commands, sensitive files) and blocked actions never do.
    """
    return decision.allowed and decision.risk_level in {"low", "medium"}


# Session-wide approval for any gated external/network tool (lit_search, web_search, …).
EXTERNAL_SESSION_KEY = "external"


class SessionApprovals:
    """In-memory set of actions approved for the current session only."""

    def __init__(self) -> None:
        self._keys: set[str] = set()

    def approved(self, key: str) -> bool:
        return key in self._keys

    def remember(self, key: str) -> None:
        self._keys.add(key)

    def __len__(self) -> int:
        return len(self._keys)


def confirm_with_approvals(
    decision: PermissionDecision,
    description: str,
    *,
    approvals: SessionApprovals,
    ask: AskFn,
    session_scope: str | None = None,
) -> bool:
    """Resolve a confirmation, honoring (and recording) session approvals.

    Returns True if the action may run this time. Session approval is only
    recorded for blanket-eligible actions. When ``session_scope`` is
    :data:`EXTERNAL_SESSION_KEY`, a single ``[s] this session`` covers all
    external tools (not just the one named in ``description``).
    """
    key = session_scope or description
    if approvals.approved(key) or (
        session_scope == EXTERNAL_SESSION_KEY and approvals.approved(EXTERNAL_SESSION_KEY)
    ):
        return True
    choice = ask(decision, description, can_blanket(decision))
    if choice == "deny":
        return False
    if choice == "session" and can_blanket(decision):
        approvals.remember(key)
        if session_scope == EXTERNAL_SESSION_KEY:
            approvals.remember(EXTERNAL_SESSION_KEY)
    return True


def make_console_confirm(console, approvals: SessionApprovals | None = None, config=None):
    """Build a loop confirmation callback backed by a Rich console and approvals."""
    approvals = approvals if approvals is not None else SessionApprovals()

    def _ask(
        decision: PermissionDecision, description: str, blanket_allowed: bool
    ) -> ApprovalChoice:
        if config is not None:
            from opentorus.notifications import notify_permission_required

            notify_permission_required(config.ui, description=description)
        console.print(f"\n[bold]OpenTorus wants to:[/bold] {description}")
        console.print(f"Reason: {decision.reason}  [dim](risk: {decision.risk_level})[/dim]")
        # Brackets must be escaped, otherwise Rich treats ``[y]``/``[s]``/``[n]``
        # as (invalid) markup tags and strips them, leaving the user unable to
        # see which keys to press.
        if blanket_allowed:
            prompt = r"Allow? \[y] once  \[s] this session  \[n] no: "
        else:
            console.print("[dim]High-risk action: cannot be approved for the whole session.[/dim]")
            prompt = r"Allow? \[y] once  \[n] no: "
        answer = console.input(prompt).strip().lower()
        # Accept both the short keys and the full words shown in the prompt.
        if answer in {"s", "session", "this session"} and blanket_allowed:
            return "session"
        if answer in {"y", "yes", "once", "s", "session", "this session"}:
            return "once"
        return "deny"

    def _confirm(
        decision: PermissionDecision, description: str, session_scope: str | None = None
    ) -> bool:
        return confirm_with_approvals(
            decision,
            description,
            approvals=approvals,
            ask=_ask,
            session_scope=session_scope,
        )

    return _confirm
