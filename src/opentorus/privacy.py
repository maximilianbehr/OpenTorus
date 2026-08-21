"""Local-first privacy helpers.

Three layers protect sensitive data:
1. The sensitive-file guard (``permissions.policy.is_sensitive_path``) blocks
   silent reads of files like ``.env`` or private keys in every mode, and
   ``command_exposes_environment`` extends that to commands that print credentials
   instead of reading them from a file.
2. The provider-context filter redacts any message flagged as sensitive before it
   is sent to an external model, unless ``privacy.allow_sensitive_context`` is on.
3. :func:`scrub_known_secrets` removes the *values* of credentials this process
   actually holds from anything bound for the provider. Layers 1 and 2 are keyed to
   a path or a flag, so neither catches a secret that arrives some other way —
   ``git config --list``, a grep that happens to match, a script that prints a
   token. Matching literal values means it can only ever redact a real secret, and
   it needs no heuristic about what a secret looks like.
"""

from __future__ import annotations

import os

from opentorus.agent.session import SessionMessage
from opentorus.config import Config
from opentorus.permissions.policy import is_sensitive_path

REDACTION = "[redacted: sensitive content excluded from provider context]"

# Environment variables whose *value* must never be forwarded. Names only — the
# values are read from the environment at redaction time and never stored.
CREDENTIAL_ENV_NAMES: tuple[str, ...] = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "MISTRAL_API_KEY",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
)
# A placeholder key ("x" in a local-vLLM setup, and this project's own examples do
# exactly that) would otherwise turn every letter x in the transcript into a
# redaction marker. Only values long enough to be real secrets are scrubbed.
_MIN_SECRET_LENGTH = 12

__all__ = [
    "is_sensitive_path",
    "redact_for_provider",
    "provider_context_notice",
    "scrub_known_secrets",
    "CREDENTIAL_ENV_NAMES",
    "REDACTION",
]


def scrub_known_secrets(text: str, environ: dict[str, str] | None = None) -> str:
    """Replace the values of known credential variables with a named marker."""
    env = os.environ if environ is None else environ
    for name in CREDENTIAL_ENV_NAMES:
        value = env.get(name)
        if value and len(value) >= _MIN_SECRET_LENGTH and value in text:
            text = text.replace(value, f"[redacted: {name}]")
    return text


def redact_for_provider(
    messages: list[SessionMessage], allow_sensitive: bool
) -> list[SessionMessage]:
    """Redact messages flagged ``sensitive`` unless sensitive context is allowed.

    Known credential values are scrubbed either way: ``allow_sensitive_context``
    opts into sending *workspace* content, never into forwarding this process's own
    API keys.
    """
    redacted: list[SessionMessage] = []
    for message in messages:
        if not allow_sensitive and message.metadata.get("sensitive"):
            redacted.append(message.model_copy(update={"content": REDACTION}))
            continue
        scrubbed = scrub_known_secrets(message.content) if message.content else message.content
        if scrubbed != message.content:
            redacted.append(message.model_copy(update={"content": scrubbed}))
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
