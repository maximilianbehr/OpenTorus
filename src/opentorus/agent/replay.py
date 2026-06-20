"""Session replay for auditability (not exact deterministic replay).

A session is the set of ``session.jsonl`` messages sharing a ``session_id``
(assigned by the agent loop). ``summarize_session`` distills it into a concise,
structured review: the user's goals, the tool actions taken, files read, commands
run, failures, the final answer, and suggested next steps.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.session import SessionMessage, read_messages

_READ_TOOLS = {"read_file", "list_files", "grep"}
_COMMAND_TOOLS = {"run_shell", "shell"}
_WRITE_TOOLS = {"write_file", "apply_patch"}


def list_session_ids(ot_dir: Path) -> list[str]:
    """Return session ids in order of first appearance."""
    seen: list[str] = []
    for message in read_messages(ot_dir):
        sid = message.metadata.get("session_id")
        if sid and sid not in seen:
            seen.append(sid)
    return seen


def last_session_id(ot_dir: Path) -> str | None:
    ids = list_session_ids(ot_dir)
    return ids[-1] if ids else None


def _session_messages(ot_dir: Path, session_id: str) -> list[SessionMessage]:
    return [m for m in read_messages(ot_dir) if m.metadata.get("session_id") == session_id]


def _tool_calls(messages: list[SessionMessage]) -> list[tuple[str, dict]]:
    calls: list[tuple[str, dict]] = []
    for message in messages:
        for tc in message.metadata.get("tool_calls", []):
            calls.append((tc.get("name", "?"), tc.get("args", {})))
    return calls


def summarize_session(ot_dir: Path, session_id: str | None = None) -> str:
    """Summarize a session into a concise, structured review."""
    session_id = session_id or last_session_id(ot_dir)
    if session_id is None:
        return "No sessions recorded yet."

    messages = _session_messages(ot_dir, session_id)
    if not messages:
        return f"No messages found for session '{session_id}'."

    goals = [m.content for m in messages if m.role == "user"]
    calls = _tool_calls(messages)
    tool_actions = [f"{name}({_fmt_args(args)})" for name, args in calls]
    files_read = _paths(calls, _READ_TOOLS)
    files_changed = _paths(calls, _WRITE_TOOLS)
    commands = [args.get("command", "") for name, args in calls if name in _COMMAND_TOOLS]

    failures = [
        m.content.strip()
        for m in messages
        if m.role == "tool" and ("Unknown tool" in m.content or "failed" in m.content.lower())
    ]
    final = next(
        (
            m.content
            for m in reversed(messages)
            if m.role == "assistant" and not m.metadata.get("tool_calls")
        ),
        "",
    )

    lines = [
        f"Session {session_id} — {len(messages)} message(s)",
        "",
        "Goals:",
        *([f"  - {g}" for g in goals] or ["  (none)"]),
        "",
        "Tool actions:",
        *([f"  - {a}" for a in tool_actions] or ["  (none)"]),
    ]
    if files_read:
        lines += ["", "Files read:", *(f"  - {p}" for p in files_read)]
    if files_changed:
        lines += ["", "Files changed:", *(f"  - {p}" for p in files_changed)]
    if commands:
        lines += ["", "Commands run:", *(f"  - {c}" for c in commands)]
    if failures:
        lines += ["", "Failures:", *(f"  - {f[:120]}" for f in failures)]
    lines += [
        "",
        "Final answer:",
        f"  {final[:300] if final else '(none)'}",
        "",
        "Suggested next steps:",
        "  - Review the tool actions and any failures above.",
        "  - Run `opentorus check` if code changed; record claims/evidence as needed.",
    ]
    return "\n".join(lines)


def _fmt_args(args: dict) -> str:
    if not args:
        return ""
    return ", ".join(f"{k}={v}" for k, v in args.items())


def _paths(calls: list[tuple[str, dict]], tool_names: set[str]) -> list[str]:
    paths: list[str] = []
    for name, args in calls:
        if name in tool_names and args.get("path"):
            path = args["path"]
            if path not in paths:
                paths.append(path)
    return paths
