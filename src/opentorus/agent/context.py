"""Context builder for the agent loop.

For the MVP this is intentionally simple: it summarizes workspace state, git
status, recent actions, and the available tools. The structure is designed so a
smarter, dependency-aware context builder (AST/import graph) can replace the
heuristics later without touching the loop.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.session import SessionMessage, read_messages
from opentorus.config import Config
from opentorus.tools.git import git_status
from opentorus.workspace import gather_status


def latest_user_query(ot_dir: Path) -> str | None:
    """Return the most recent user message content, used as the retrieval query."""
    for message in reversed(read_messages(ot_dir)):
        if message.role == "user" and message.content.strip():
            return message.content
    return None


def select_relevant(ot_dir: Path, config: Config, query: str | None):
    """Return the top relevant (IndexDoc, score) artifacts for ``query``.

    Uses hybrid (BM25 + vector) retrieval when an embedder is available (provider
    API or optional local sentence-transformers), degrading transparently to
    BM25-only otherwise.
    """
    if not config.context.retrieval_enabled or not query:
        return []
    from opentorus.research.embeddings import load_embedder
    from opentorus.research.index import hybrid_search

    embedder = load_embedder(config)
    return hybrid_search(ot_dir, query, k=config.context.top_k, embedder=embedder)


def format_relevant(selected) -> str:
    """Render selected artifacts as a context block, recording why each was chosen."""
    lines = [
        "Relevant artifacts (selected by keyword relevance to your latest message; "
        "evidence, not verified truth):"
    ]
    for doc, score in selected:
        snippet = " ".join(doc.text.split())[:200]
        lines.append(
            f"- {doc.artifact_id} [{doc.artifact_type}] (relevance {score:.2f}): {snippet}"
        )
    return "\n".join(lines)


def build_context_summary(
    root: Path,
    ot_dir: Path,
    config: Config,
    tool_names: list[str],
) -> str:
    snap = gather_status(root)
    git = git_status(root)
    recent_actions = list_actions(ot_dir, limit=5)
    action_lines = (
        "; ".join(f"{a.tool_name}({'ok' if a.ok else 'failed'})" for a in recent_actions) or "none"
    )
    sensitive = "allowed" if config.privacy.allow_sensitive_context else "excluded (default)"
    lines = [
        "Workspace context:",
        f"- cwd: {snap.cwd}",
        f"- workspace root: {snap.workspace_root}",
        f"- git: {'repo' if git.is_repo else 'not a repo'}",
        f"- project mode: {config.project.mode}",
        f"- operating style: {config.agent.style}",
        f"- permission mode: {config.permissions.mode}",
        f"- sensitive context: {sensitive}",
        f"- available tools: {', '.join(tool_names) or 'none'}",
        f"- recent actions: {action_lines}",
    ]
    if snap.initialized:
        from opentorus.agent.inventory import format_artifact_inventory, gather_artifact_inventory

        inventory = gather_artifact_inventory(root, ot_dir)
        lines.append(format_artifact_inventory(inventory, for_agent=True))
    return "\n".join(lines)


def _sanitize_session_history(history: list[SessionMessage]) -> list[SessionMessage]:
    """Drop empty assistant turns and persisted chat-only recovery noise."""
    cleaned: list[SessionMessage] = []
    recovery_prefix = "This is a planned task that requires tool use"
    for message in history:
        if message.role == "assistant":
            if not (message.content or "").strip() and not message.metadata.get("tool_calls"):
                continue
        if message.role == "user" and message.content.strip().startswith(recovery_prefix):
            continue
        cleaned.append(message)
    return cleaned


def build_messages(
    root: Path,
    ot_dir: Path,
    config: Config,
    tool_names: list[str],
    *,
    include_history: int | None = None,
    planned_task=None,
    recovery_hint: str | None = None,
    provider=None,
) -> list[SessionMessage]:
    """Assemble the message list for a provider call.

    The caller is expected to have already persisted the latest user (or tool)
    message to the session, so the recent history ends with the message the
    provider should respond to. When retrieval is enabled, the most relevant
    artifacts for the latest user message are injected as a context block.
    """
    from opentorus.agent.prompts import build_system_prompt, build_task_execution_prompt

    system_prompt = build_system_prompt(config.project.mode, config.agent.style)
    messages: list[SessionMessage] = [
        SessionMessage(role="system", content=system_prompt),
        SessionMessage(
            role="system",
            content=build_context_summary(root, ot_dir, config, tool_names),
        ),
    ]
    from opentorus.agent.prompts import TOOL_ROUTING_GUIDE

    messages.append(SessionMessage(role="system", content=TOOL_ROUTING_GUIDE))
    if config.model.provider == "ollama":
        from opentorus.agent.prompts import LOCAL_TOOL_HINT

        messages.append(SessionMessage(role="system", content=LOCAL_TOOL_HINT))
    if planned_task is not None:
        messages.append(
            SessionMessage(
                role="system",
                content=build_task_execution_prompt(
                    category=planned_task.category,
                    goal=planned_task.goal,
                    result_contract=planned_task.result_contract,
                    verification_requirements=planned_task.verification_requirements,
                ),
            )
        )

    selected = select_relevant(ot_dir, config, latest_user_query(ot_dir))
    if selected:
        messages.append(SessionMessage(role="system", content=format_relevant(selected)))

    turns = include_history if include_history is not None else config.context.history_turns
    history = _sanitize_session_history(read_messages(ot_dir))
    if history:
        messages.extend(history[-turns:])
    if recovery_hint:
        messages.append(SessionMessage(role="user", content=recovery_hint))

    from opentorus.privacy import redact_for_provider

    messages = redact_for_provider(messages, config.privacy.allow_sensitive_context)

    from opentorus.agent.compaction import compact_messages, maybe_compact_session

    maybe_compact_session(ot_dir, config, provider=provider)
    return compact_messages(ot_dir, messages, config, provider=provider)
