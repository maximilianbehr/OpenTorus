"""Permission evaluation and enforcement for tool calls, lifted out of the loop.

The permission *policy* itself lives in ``opentorus.permissions.policy`` and is
unchanged; this module is the glue that picks the right evaluator for a tool's
``permission`` kind and turns a decision into the loop's block/confirm behaviour —
including the audit-log entries, in the same order as before.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from opentorus.actions import log_action
from opentorus.agent.control.models import PolicyAction, PolicyDecision, ReasonCode
from opentorus.approvals import EXTERNAL_SESSION_KEY
from opentorus.config import OperatingStyle, PermissionMode
from opentorus.permissions.policy import (
    PermissionDecision,
    evaluate_command,
    evaluate_external_tool,
    evaluate_write,
)
from opentorus.tools.base import Tool
from opentorus.tools.registry import ToolRegistry

# A confirmation callback receives the decision, a human-readable description
# of the pending action, and an optional session scope (e.g. "external" for all
# network tools). Returns True to allow it.
ConfirmCallback = Callable[[PermissionDecision, str, str | None], bool]


def evaluate_permission(
    tool: Tool, args: dict, *, mode: PermissionMode, style: OperatingStyle, review: bool
) -> PermissionDecision | None:
    """Return a permission decision for a write/command/external tool, or None for reads."""
    if tool.permission == "write":
        return evaluate_write(args.get("path", ""), mode, style=style, review=review)
    if tool.permission == "command":
        return evaluate_command(args.get("command", ""), mode, style=style, review=review)
    if tool.permission == "external":
        return evaluate_external_tool(tool.name, mode, style=style, review=review)
    return None


def permission_decision_to_policy(decision: PermissionDecision) -> PolicyDecision:
    """Translate a permission decision into control-plane vocabulary."""
    if not decision.allowed:
        return PolicyDecision(
            action=PolicyAction.BLOCK,
            reason_code=ReasonCode.PERMISSION_DENIED,
            message=f"Blocked: {decision.reason}",
            metadata={"risk_level": decision.risk_level, "reason": decision.reason},
        )
    if decision.requires_confirmation:
        return PolicyDecision(
            action=PolicyAction.WARN,
            reason_code=ReasonCode.PERMISSION_DENIED,
            message=f"Requires confirmation: {decision.reason}",
            metadata={"risk_level": decision.risk_level, "reason": decision.reason},
        )
    return PolicyDecision(action=PolicyAction.ALLOW, reason_code=ReasonCode.OK)


def enforce_permission(
    name: str,
    args: dict,
    decision: PermissionDecision,
    *,
    ot_dir: Path,
    registry: ToolRegistry,
    confirm: ConfirmCallback | None,
) -> str | None:
    """Apply a permission decision. Returns a message if the call must not run."""
    if not decision.allowed:
        log_action(
            ot_dir,
            name,
            ok=False,
            args=args,
            permission_decision=decision.model_dump(),
            stderr_summary=decision.reason,
        )
        return f"Blocked: {decision.reason}"
    if decision.requires_confirmation:
        description = args.get("command") or args.get("path") or name
        tool = registry.get(name)
        is_external = tool is not None and tool.permission == "external"
        scope = EXTERNAL_SESSION_KEY if is_external else None
        approved = confirm(decision, str(description), scope) if confirm else False
        if not approved:
            log_action(
                ot_dir,
                name,
                ok=False,
                args=args,
                permission_decision=decision.model_dump(),
                stderr_summary="not confirmed",
            )
            return f"Not run (requires confirmation): {decision.reason}"
    return None
