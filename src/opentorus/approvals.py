"""Ergonomic, safe approval prompts for the agent loop.

When the permission policy says an action ``requires_confirmation``, the loop
calls a confirmation callback. This module turns that into a clear, ergonomic
prompt with three choices:

* allow once -- run this one action;
* allow for this session -- auto-approve the *same* action for the rest of the
  session (in memory only, never persisted);
* deny.

What "the same action" means is explicit: an approval key is the tool name plus
the canonical JSON of the arguments that decide what the call touches -- the
``path`` of a write, the ``command`` of a shell call, the host of a
``fetch_url``. Approving ``write_file x.py`` therefore never covers
``apply_patch x.py``, and approving one external tool never covers another (an
MCP tool's name carries its server).

Safety guarantees: high-risk actions (destructive commands, sensitive files) and
**irreversible** effects (see :mod:`opentorus.tools.effects`) are never
blanket-approved -- even if the user picks "session", they are confirmed every
time. Dangerous commands are blocked by policy before they ever reach a prompt.

Without a terminal (a ``setsid`` background campaign) approvals go through an
on-disk queue instead (:class:`ApprovalQueue`): the request is written under
``.opentorus/approvals/pending/``, bound to the tool, a digest of the exact
arguments and the policy version, and decided with ``opentorus approvals
approve|deny <id>``. An approval is single-use and applies only to a call whose
arguments hash to the same digest under the same policy version.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from opentorus.permissions.policy import POLICY_VERSION, PermissionDecision

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


# Kept for compatibility: a scope string, no longer a wildcard. Session approval
# of external tools is per tool (+server, +host), never global.
EXTERNAL_SESSION_KEY = "external"


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def args_digest(tool_name: str, args: dict) -> str:
    """Digest of the *exact* call: tool name + canonical JSON of every argument."""
    return hashlib.sha256(f"{tool_name}\0{canonical_json(args)}".encode()).hexdigest()


class ApprovalScope(str):
    """The session-approval key for one call, carrying the call it was made for.

    It *is* a string (the key), so confirmation callbacks that only pass it along
    keep working; the queue reads the attributes to bind an approval to the exact
    arguments.
    """

    tool: str
    args: dict
    effect: str
    per_call: bool

    def __new__(
        cls, key: str, *, tool: str, args: dict, effect: str, per_call: bool
    ) -> ApprovalScope:
        obj = super().__new__(cls, key)
        obj.tool = tool
        obj.args = dict(args)
        obj.effect = effect
        obj.per_call = per_call
        return obj


def _relevant_args(tool: Any, args: dict) -> dict:
    permission = getattr(tool, "permission", "read")
    name = getattr(tool, "name", "")
    if permission == "write":
        return {"path": args.get("path", "")}
    if permission == "command":
        return {"command": args.get("command", "")}
    if name == "fetch_url":
        host = urllib.parse.urlparse(str(args.get("url", ""))).hostname or ""
        return {"host": host.lower()}
    server = getattr(tool, "server", None)
    return {"server": server} if server else {}


def approval_scope(tool: Any, args: dict) -> ApprovalScope:
    """Key = tool name + canonical JSON of the relevant arguments."""
    from opentorus.tools.effects import effect_of

    name = str(getattr(tool, "name", ""))
    effect = effect_of(tool)
    key = f"{name}:{canonical_json(_relevant_args(tool, args))}"
    return ApprovalScope(
        key, tool=name, args=args, effect=effect, per_call=effect == "irreversible"
    )


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def describe_action(tool: Any, args: dict, root: Path | None = None) -> str:
    """What the approval prompt shows: the URL, the command, or a write's size/diff."""
    name = str(getattr(tool, "name", ""))
    permission = getattr(tool, "permission", "read")
    if name == "fetch_url":
        return f"fetch_url {args.get('url', '')}"
    if permission == "command":
        return str(args.get("command", name))
    if permission == "write":
        path = str(args.get("path", ""))
        return f"{name} {path}\n{_write_summary(name, path, args, root)}"
    if permission == "external":
        shown = {k: v for k, v in args.items() if k not in ("content",)}
        return f"{name} {_short(canonical_json(shown))}" if shown else name
    return name


def _write_summary(name: str, path: str, args: dict, root: Path | None) -> str:
    import difflib

    old = ""
    exists = False
    if root is not None and path:
        try:
            from opentorus.paths import resolve_workspace_path

            target = resolve_workspace_path(root, path)
            if target.is_file():
                exists = True
                old = target.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 — a summary must never block the prompt
            pass
    if name == "apply_patch":
        before, after = str(args.get("old", "")), str(args.get("new", ""))
        head = f"  replaces {len(before)} chars with {len(after)} chars"
    else:
        before, after = old, str(args.get("content", ""))
        head = (
            f"  overwrites {len(old)} chars with {len(after)} chars"
            if exists
            else f"  new file, {len(after)} chars"
        )
    diff = list(
        difflib.unified_diff(
            before.splitlines(), after.splitlines(), "before", "after", lineterm="", n=1
        )
    )[2:]
    shown = diff[:20]
    more = f"\n  … {len(diff) - 20} more diff lines" if len(diff) > 20 else ""
    body = "\n".join(f"  {line}" for line in shown)
    return head + ("\n" + body if body else "") + more


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

    Returns True if the action may run this time. ``session_scope`` is the approval
    key (see :func:`approval_scope`); without one the description is the key. A
    session approval is only recorded for blanket-eligible actions, and never for
    a per-call (irreversible) scope.
    """
    key = str(session_scope) if session_scope else description
    per_call = bool(getattr(session_scope, "per_call", False))
    blanket = can_blanket(decision) and not per_call
    if blanket and approvals.approved(key):
        return True
    choice = ask(decision, description, blanket)
    if choice == "deny":
        return False
    if choice == "session" and blanket:
        approvals.remember(key)
    return True


def make_console_confirm(console, approvals: SessionApprovals | None = None, config=None):
    """Build a loop confirmation callback backed by a Rich console and approvals."""
    approvals = approvals if approvals is not None else SessionApprovals()

    def _ask(
        decision: PermissionDecision, description: str, blanket_allowed: bool
    ) -> ApprovalChoice:
        if config is not None:
            from opentorus.notifications import notify_permission_required

            notify_permission_required(
                config.ui,
                description=description,
                reason=decision.reason,
                risk_level=str(decision.risk_level),
            )
        from rich.markup import escape

        console.print(f"\n[bold]OpenTorus wants to:[/bold] {escape(description)}")
        console.print(f"Reason: {decision.reason}  [dim](risk: {decision.risk_level})[/dim]")
        # Brackets must be escaped, otherwise Rich treats ``[y]``/``[s]``/``[n]``
        # as (invalid) markup tags and strips them, leaving the user unable to
        # see which keys to press.
        if blanket_allowed:
            prompt = r"Allow? \[y] once  \[s] this session  \[n] no: "
        else:
            console.print(
                "[dim]High-risk or irreversible action: approved one call at a time.[/dim]"
            )
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


# --- the on-disk approval queue (no terminal) -------------------------------------

QueueState = Literal["pending", "approved", "denied", "used"]
_STATES: tuple[QueueState, ...] = ("pending", "approved", "denied", "used")


def _now() -> str:
    return datetime.now(UTC).isoformat()


class ApprovalQueue:
    """``.opentorus/approvals/<state>/<id>.json``; a state change is an atomic rename."""

    def __init__(self, ot_dir: Path) -> None:
        self.base = Path(ot_dir) / "approvals"

    def _dir(self, state: QueueState) -> Path:
        return self.base / state

    def _path(self, state: QueueState, approval_id: str) -> Path:
        if not approval_id.replace("-", "").isalnum():
            raise ValueError(f"Invalid approval id {approval_id!r}.")
        return self._dir(state) / f"{approval_id}.json"

    def _write(self, state: QueueState, record: dict) -> Path:
        from opentorus.atomicio import atomic_write_text

        path = self._path(state, record["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(path, json.dumps(record, indent=2, sort_keys=True))
        return path

    def _read(self, path: Path) -> dict | None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return data if isinstance(data, dict) else None

    def list(self, state: QueueState | None = None) -> list[dict]:
        states = (state,) if state else _STATES
        out: list[dict] = []
        for st in states:
            d = self._dir(st)
            if not d.is_dir():
                continue
            for path in sorted(d.glob("*.json")):
                rec = self._read(path)
                if rec is not None:
                    out.append({**rec, "state": st})
        return sorted(out, key=lambda r: str(r.get("created_at", "")))

    def get(self, approval_id: str) -> tuple[QueueState, dict] | None:
        for st in _STATES:
            path = self._path(st, approval_id)
            if path.is_file():
                rec = self._read(path)
                if rec is not None:
                    return st, rec
        return None

    def request(
        self,
        *,
        tool: str,
        args: dict,
        description: str,
        decision: PermissionDecision,
        session: str | None = None,
    ) -> dict:
        """Queue (or find the already-pending) request for this exact call."""
        digest = args_digest(tool, args)
        for rec in self.list("pending"):
            if rec.get("args_digest") == digest and rec.get("policy_version") == POLICY_VERSION:
                return rec
        record = {
            "id": f"APPROVAL-{secrets.token_hex(6)}",
            "tool": tool,
            "args_digest": digest,
            "policy_version": POLICY_VERSION,
            "description": description[:2000],
            "reason": decision.reason,
            "risk_level": decision.risk_level,
            "session": session,
            "created_at": _now(),
        }
        self._write("pending", record)
        return record

    def decide(self, approval_id: str, approve: bool, *, by: str = "cli") -> dict:
        """Move a pending request to ``approved`` or ``denied``."""
        src = self._path("pending", approval_id)
        rec = self._read(src) if src.is_file() else None
        if rec is None:
            found = self.get(approval_id)
            current = found[0] if found else "missing"
            raise ValueError(f"{approval_id} is not pending (state: {current}).")
        target: QueueState = "approved" if approve else "denied"
        rec.update({"decided_at": _now(), "decided_by": by, "decision": target})
        self._write(target, rec)
        src.unlink(missing_ok=True)
        return rec

    def consume(self, tool: str, args: dict) -> dict | None:
        """Use an approval for this exact call once; ``None`` if there is none."""
        digest = args_digest(tool, args)
        for rec in self.list("approved"):
            if (
                rec.get("tool") != tool
                or rec.get("args_digest") != digest
                or rec.get("policy_version") != POLICY_VERSION
            ):
                continue
            src = self._path("approved", rec["id"])
            dst = self._path("used", rec["id"])
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.rename(src, dst)  # atomic: exactly one consumer wins
            except FileNotFoundError:
                continue
            used = {k: v for k, v in rec.items() if k != "state"}
            used["used_at"] = _now()
            self._write("used", used)
            return used
        return None

    def denied(self, approval_id: str) -> bool:
        return self._path("denied", approval_id).is_file()

    def approved(self, approval_id: str) -> bool:
        return self._path("approved", approval_id).is_file()


def make_queue_confirm(
    ot_dir: Path,
    *,
    wait_seconds: float = 0.0,
    poll_seconds: float = 1.0,
    session: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
):
    """A confirmation callback for runs without a terminal.

    A call that already has a matching approval runs (consuming it). Otherwise a
    request is queued and the run waits up to ``wait_seconds`` for a decision; on
    timeout or denial the call is not run (the loop records the denial).
    """
    queue = ApprovalQueue(ot_dir)

    def _confirm(
        decision: PermissionDecision, description: str, session_scope: str | None = None
    ) -> bool:
        tool = getattr(session_scope, "tool", None) or description
        args = getattr(session_scope, "args", None) or {"description": description}
        if queue.consume(tool, args) is not None:
            return True
        record = queue.request(
            tool=tool, args=args, description=description, decision=decision, session=session
        )
        deadline = time.monotonic() + max(0.0, wait_seconds)
        while time.monotonic() < deadline:
            if queue.denied(record["id"]):
                return False
            if queue.approved(record["id"]) and queue.consume(tool, args) is not None:
                return True
            sleep(min(poll_seconds, max(0.0, deadline - time.monotonic())))
        return False

    return _confirm
