"""Local-first privacy helpers.

Two layers protect sensitive data:
1. The sensitive-file guard (``permissions.policy.is_sensitive_path``) blocks
   silent reads of files like ``.env`` or private keys in every mode.
2. The provider-context filter redacts any message flagged as sensitive before it
   is sent to an external model, unless ``privacy.allow_sensitive_context`` is on.
"""

from __future__ import annotations

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.permissions.policy import is_sensitive_path

REDACTION = "[redacted: sensitive content excluded from provider context]"

__all__ = ["is_sensitive_path", "redact_for_provider", "provider_context_notice", "REDACTION"]


def redact_for_provider(
    messages: list[SessionMessage], allow_sensitive: bool
) -> list[SessionMessage]:
    """Redact messages flagged ``sensitive`` unless sensitive context is allowed."""
    if allow_sensitive:
        return messages
    redacted: list[SessionMessage] = []
    for message in messages:
        if message.metadata.get("sensitive"):
            redacted.append(message.model_copy(update={"content": REDACTION}))
        else:
            redacted.append(message)
    return redacted


def provider_context_notice(
    config: Config,
    tool_names: list[str],
    selected: list | None = None,
) -> str:
    """Describe what would be sent to an external provider and the privacy posture."""
    posture = (
        "INCLUDED (privacy.allow_sensitive_context is on)"
        if config.privacy.allow_sensitive_context
        else "excluded by default"
    )
    lines = [
        "Provider-context notice:",
        "- Sent: system prompt, workspace status summary, recent session turns, tool results.",
        f"- Sensitive file contents: {posture}.",
        f"- Available tools the model may call: {', '.join(tool_names) or 'none'}.",
        "- Nothing leaves your machine unless a non-local provider is configured.",
    ]
    if selected is not None:
        if selected:
            picks = ", ".join(f"{doc.artifact_id} ({score:.2f})" for doc, score in selected)
            lines.append(f"- Selected artifacts (by relevance): {picks}.")
        else:
            lines.append("- Selected artifacts: none (no relevant matches or retrieval off).")
    return "\n".join(lines)
