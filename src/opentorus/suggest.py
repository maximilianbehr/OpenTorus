"""Beginner-friendly next-step command suggestions.

Inspects the workspace and config, then returns a short ordered list of concrete
CLI commands a new user can run next. Used by ``opentorus suggest``, ``/suggest``
in the REPL, and briefly after ``init`` / ``status``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from opentorus.config import Config, default_config, load_config
from opentorus.paths import resolve_cli_workspace_root


@dataclass(frozen=True)
class CommandSuggestion:
    command: str
    reason: str
    priority: int = 50


def suggest_next_commands(
    root: Path | None,
    ot_dir: Path | None,
    config: Config | None = None,
    *,
    limit: int = 6,
) -> list[CommandSuggestion]:
    """Return up to ``limit`` suggested next commands for the current workspace."""
    if root is None or ot_dir is None:
        return [
            CommandSuggestion(
                "opentorus init",
                "Create a .opentorus/ workspace in this directory.",
                priority=10,
            ),
            CommandSuggestion(
                "opentorus --help",
                "See all commands grouped by topic.",
                priority=90,
            ),
        ][:limit]

    config = config or _load_config(ot_dir)
    out: list[CommandSuggestion] = []

    if config.model.provider == "mock":
        out.append(
            CommandSuggestion(
                "opentorus config set model.provider ollama",
                "The mock provider cannot run real agent work — point at a local or cloud model.",
                priority=20,
            )
        )
        out.append(
            CommandSuggestion(
                "opentorus config set model.name llama3",
                "Set the model id your provider expects (replace llama3 with yours).",
                priority=21,
            )
        )

    inbox = root / "papers" / "inbox"
    if inbox.is_dir():
        pdfs = list(inbox.glob("*.pdf"))
        if pdfs:
            out.append(
                CommandSuggestion(
                    "opentorus paper ingest",
                    f"Register {len(pdfs)} PDF(s) waiting in papers/inbox/.",
                    priority=30,
                )
            )

    from opentorus.research.index import index_status
    from opentorus.research.papers import list_papers

    papers = list_papers(ot_dir)
    if papers and not index_status(ot_dir).built_at:
        out.append(
            CommandSuggestion(
                "opentorus index build",
                "Papers are registered but the search index is not built yet.",
                priority=35,
            )
        )

    if papers:
        first = papers[0].id
        from opentorus.research.papers import is_paper_parsed

        if not is_paper_parsed(ot_dir, papers[0]):
            out.append(
                CommandSuggestion(
                    "opentorus paper read-unread",
                    "Parse cached PDFs that are still [UNREAD].",
                    priority=45,
                )
            )
        out.append(
            CommandSuggestion(
                f"opentorus problem extract {first}",
                "Pull numbered open problems into PROBLEM-* dossiers.",
                priority=46,
            )
        )

    from opentorus.research.tasks import list_tasks, next_pending_task

    pending = next_pending_task(ot_dir)
    if pending is not None:
        out.append(
            CommandSuggestion(
                "opentorus run --plan --resume",
                f"Continue planned work — next up: {pending.id} ({pending.category}).",
                priority=40,
            )
        )
    elif any(t.status == "failed" for t in list_tasks(ot_dir)):
        out.append(
            CommandSuggestion(
                "opentorus task retry",
                "Reset failed tasks to proposed, then run --resume.",
                priority=41,
            )
        )

    from opentorus.agent.run_state import load_run_state

    if load_run_state(ot_dir) is not None and pending is None:
        out.append(
            CommandSuggestion(
                "opentorus run --resume",
                "Pick up the last agent session from run_state.json.",
                priority=42,
            )
        )

    if config.permissions.mode == "safe":
        out.append(
            CommandSuggestion(
                "opentorus config set permissions.mode ask",
                "Safe mode blocks writes and shell — use ask or trusted for agent runs.",
                priority=25,
            )
        )

    out.append(
        CommandSuggestion(
            "opentorus doctor",
            "Quick health check: config, provider, inbox, index, and tools.",
            priority=70,
        )
    )

    if not papers:
        out.append(
            CommandSuggestion(
                'opentorus run --plan --fresh "Survey papers/inbox; pick an open problem"',
                "Good first workflow once a model is configured "
                "(see examples/simons-eigenvalue-problems/).",
                priority=50,
            )
        )
    else:
        out.append(
            CommandSuggestion(
                "opentorus chat",
                "Interactive session — type tasks or use /help for slash commands.",
                priority=60,
            )
        )

    out.append(
        CommandSuggestion(
            "opentorus suggest",
            "Re-run this guide anytime your workspace changes.",
            priority=95,
        )
    )

    out.sort(key=lambda s: s.priority)
    seen: set[str] = set()
    unique: list[CommandSuggestion] = []
    for item in out:
        if item.command in seen:
            continue
        seen.add(item.command)
        unique.append(item)
    return unique[:limit]


def suggest_for_cwd(
    *,
    limit: int = 6,
) -> tuple[Path | None, Path | None, list[CommandSuggestion]]:
    cwd = Path.cwd().resolve()
    root = resolve_cli_workspace_root(cwd)
    if root is None:
        return None, None, suggest_next_commands(None, None, limit=limit)
    ot_dir = root / ".opentorus"
    config = _load_config(ot_dir)
    return root, ot_dir, suggest_next_commands(root, ot_dir, config, limit=limit)


def _load_config(ot_dir: Path) -> Config:
    from opentorus.config import CONFIG_FILENAME

    path = ot_dir / CONFIG_FILENAME
    return load_config(path) if path.is_file() else default_config()


def format_suggestions_plain(suggestions: list[CommandSuggestion]) -> str:
    if not suggestions:
        return "No suggestions right now."
    lines = ["Suggested next commands:", ""]
    for index, item in enumerate(suggestions, start=1):
        lines.append(f"{index}. {item.command}")
        lines.append(f"   {item.reason}")
    return "\n".join(lines)
