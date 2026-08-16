"""Context builder for the agent loop.

For the MVP this is intentionally simple: it summarizes workspace state, git
status, recent actions, and the available tools. The structure is designed so a
smarter, dependency-aware context builder (AST/import graph) can replace the
heuristics later without touching the loop.
"""

from __future__ import annotations

import logging
from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.session import SessionMessage, read_messages
from opentorus.config import Config
from opentorus.tools.git import git_status
from opentorus.workspace import gather_status

_logger = logging.getLogger(__name__)

# Circuit breaker for retrieval: a flaky embeddings endpoint must not abort the run,
# but a single transient hiccup must not permanently disable retrieval for every later
# phase either. So count *consecutive* failures, trip only at the limit, and let any
# success reset the counter; ``reset_retrieval_breaker`` clears it at a phase boundary.
_retrieval_failures = 0
_RETRIEVAL_FAILURE_LIMIT = 3


def reset_retrieval_breaker() -> None:
    """Reset the retrieval failure counter (call at the start of a run/phase)."""
    global _retrieval_failures
    _retrieval_failures = 0


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
    global _retrieval_failures
    if (
        not config.context.retrieval_enabled
        or not query
        or _retrieval_failures >= _RETRIEVAL_FAILURE_LIMIT
    ):
        return []
    from opentorus.research.embeddings import load_embedder
    from opentorus.research.index import hybrid_search

    # Retrieval is an optional enhancement: a flaky embeddings endpoint (e.g. an
    # Ollama timeout while a large chat model occupies the server) must never abort
    # the agent run. Degrade to no retrieval on failure; trip the breaker only after
    # several *consecutive* failures, and let a success reset it so one transient
    # hiccup does not silently disable retrieval for the rest of the process.
    try:
        embedder = load_embedder(config)
        result = hybrid_search(ot_dir, query, k=config.context.top_k, embedder=embedder)
        _retrieval_failures = 0
        return result
    except Exception as exc:  # noqa: BLE001 — retrieval is best-effort, never fatal
        _retrieval_failures += 1
        level = "warning" if _retrieval_failures >= _RETRIEVAL_FAILURE_LIMIT else "debug"
        getattr(_logger, level)(
            "Context retrieval failed (%s); failure %d/%d.",
            exc,
            _retrieval_failures,
            _RETRIEVAL_FAILURE_LIMIT,
        )
        return []


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
    goal: str | None = None,
    provider=None,
) -> list[SessionMessage]:
    """Assemble the message list for a provider call.

    The caller is expected to have already persisted the latest user (or tool)
    message to the session, so the recent history ends with the message the
    provider should respond to. When retrieval is enabled, the most relevant
    artifacts for the latest user message are injected as a context block.
    """
    from opentorus.agent.prompts import build_system_prompt, build_task_execution_prompt

    # Ordering matters for cost, not just for clarity. Everything below is re-sent on
    # every model step, and a local server can only reuse its KV cache for the prompt
    # prefix it has already seen. The workspace inventory used to sit at position 2 —
    # it changes almost every turn, so the shared prefix ended a few hundred tokens in
    # and the whole history behind it was re-evaluated each step. Measured on a real
    # run (examples/matrix-spencer): 1,263,204 prompt tokens against 51,534 completion
    # tokens, with prompt_eval_count climbing 8k -> 30k in lockstep with latency, i.e.
    # no reuse at all. So: stable blocks first, volatile state last.
    system_prompt = build_system_prompt(config.project.mode, config.agent.style)
    messages: list[SessionMessage] = [SessionMessage(role="system", content=system_prompt)]
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

    # Anchor the run's task as a persistent system instruction. The history below is
    # windowed to the last few turns, so on a long autonomous run the original task
    # (and the deliverable it asks for) would otherwise scroll out of context and the
    # agent would re-derive or forget it.
    if goal and goal.strip():
        messages.append(
            SessionMessage(
                role="system",
                content=(
                    "Current task — keep working toward it until its deliverable exists; "
                    "do not re-derive it or treat it as unasked:\n" + goal.strip()
                ),
            )
        )

    inventory = build_context_summary(root, ot_dir, config, tool_names)
    selected = select_relevant(ot_dir, config, latest_user_query(ot_dir))
    retrieval = format_relevant(selected) if selected else None

    if not config.context.stable_prefix:
        # Legacy ordering, kept verbatim so the change can be switched off if a model
        # behaves differently with the state at the end.
        messages.insert(1, SessionMessage(role="system", content=inventory))
        if retrieval:
            messages.append(SessionMessage(role="system", content=retrieval))
        _extend_with_history(messages, ot_dir, config, include_history)
        if recovery_hint:
            messages.append(SessionMessage(role="user", content=recovery_hint))
        return _finalize(ot_dir, config, messages, provider)

    _extend_with_history(messages, ot_dir, config, include_history)

    # Volatile state goes behind the history, but *not* dead last: the final turn is
    # what the model is answering, and burying it under a page of inventory both shifts
    # its salience and would split a tool_call/tool_result pair (which the OpenAI and
    # Anthropic APIs reject). Inserting it just before the final turn keeps the answer
    # target intact while still making everything ahead of it a stable, reusable prefix.
    # Merged into ONE message because a run of consecutive same-role messages is what
    # strict local chat templates choke on — and for the same reason it is a ``system``
    # message: inserted before a user turn, a ``user`` block would produce exactly that
    # forbidden pair. The trade-off is Anthropic, which hoists every system message into
    # the top-level system field and so puts this back in front; that costs nothing
    # today, because Anthropic prefix caching needs explicit cache_control breakpoints
    # rather than message order, and the measured problem is the local Ollama path.
    volatile = [part for part in (inventory, retrieval) if part]
    if volatile:
        messages.insert(
            _final_turn_start(messages),
            SessionMessage(role="system", content="\n\n".join(volatile)),
        )
    # The recovery hint stays last: it tells the model what to do *now*.
    if recovery_hint:
        messages.append(SessionMessage(role="user", content=recovery_hint))
    return _finalize(ot_dir, config, messages, provider)


def _final_turn_start(messages: list[SessionMessage]) -> int:
    """Index of the first message of the final turn — where volatile state is inserted.

    The final turn is either a lone user message or an assistant ``tool_calls`` message
    followed by its ``tool`` results. Those results must stay adjacent to the call that
    produced them, so the insertion point is *before* the whole group, never inside it.
    """
    idx = len(messages)
    while idx > 0 and messages[idx - 1].role == "tool":
        idx -= 1
    if (
        idx > 0
        and messages[idx - 1].role == "assistant"
        and messages[idx - 1].metadata.get("tool_calls")
    ):
        return idx - 1
    if idx == len(messages) and idx > 0 and messages[idx - 1].role == "user":
        return idx - 1
    return idx


def _extend_with_history(
    messages: list[SessionMessage],
    ot_dir: Path,
    config: Config,
    include_history: int | None,
) -> None:
    turns = include_history if include_history is not None else config.context.history_turns
    history = _sanitize_session_history(read_messages(ot_dir))
    if history:
        messages.extend(history[-turns:])


def _finalize(
    ot_dir: Path,
    config: Config,
    messages: list[SessionMessage],
    provider,  # noqa: ANN001 - BaseProvider (lazy import)
) -> list[SessionMessage]:
    from opentorus.privacy import redact_for_provider

    messages = redact_for_provider(messages, config.privacy.allow_sensitive_context)

    from opentorus.agent.compaction import compact_messages, maybe_compact_session

    maybe_compact_session(ot_dir, config, provider=provider)
    return compact_messages(ot_dir, messages, config, provider=provider)
