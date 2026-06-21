"""Interactive OpenTorus session (the primary UX).

``run_repl`` renders a compact banner and reads ``ot>`` input in a loop. All
command interpretation lives in the pure :func:`dispatch` function so it can be
tested without a real TTY. Natural-language input returns a placeholder until the
agent loop lands in a later milestone.
"""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console

from opentorus.actions import list_actions
from opentorus.cli import BANNER, SLOGAN
from opentorus.paths import find_workspace_root
from opentorus.research.memory import VALID_KINDS, list_memory
from opentorus.workspace import gather_status, workspace_dir

PROMPT = "ot> "

_HELP_TEXT = """\
Available slash commands:
  /help     Show this help.
  /suggest  Suggest concrete next commands for this workspace.
  /status   Show workspace, git, and project state.
  /diff     Show the git diff of the working tree.
  /claims   Show research claims and their statuses.
  /experiments  Show registered experiments.
  /papers   Show registered papers.
  /tasks    Show planned research tasks.
  /graph    Show the artifact relation graph.
  /related <id>  Show relations touching an artifact.
  /evidence <claim-id>  Show evidence linked to a claim.
  /why <id>  Trace an artifact back to its evidence and relations.
  /report [problem-id]  Rebuild a dossier report (defaults to the active problem).
  /problem [id]  Show the active problem / dossiers, or set the active problem.
  /patches  Show patch artifacts.
  /patch <id>  Show a patch's metadata and diff.
  /memory   Show structured project memory counts.
  /actions  Show recent tool actions.
  /history [n]  Show recent input history (↑/↓ recall, Ctrl+R searches).
  /permissions  Show the current permission mode and policy.
  /style [name]  Show or set the operating style (cautious/normal/fast/autonomous).
  /mode [name]  Show or set the agent mode (normal/review).
  /execute [goal]  Plan a goal (or resume) and execute tasks one at a time.
  /replay [last|<id>]  Summarize a session for review.
  /usage    Show the local token usage and estimated cost ledger.
  /check    Run the configured quality gates (test/lint/typecheck).
  /checkpoint create <label>  Record a recoverable checkpoint.
  /context  Show the context summary sent to the model.
  /model    Show the model config, or `/model set <key> <value>`.
  /clear    Clear the screen.
  /exit     Leave the session.

Press TAB to complete commands; ↑/↓ recall history and Ctrl+R searches it.
Type a natural-language task to run it through the agent loop."""


@dataclass
class ReplResult:
    """Outcome of handling one line of input."""

    messages: list[str] = field(default_factory=list)
    should_exit: bool = False
    should_clear: bool = False


def build_banner(start: Path | None = None) -> str:
    snap = gather_status(start)
    workspace = snap.workspace_root or "(no workspace — run `opentorus init`)"
    return (
        f"[bold blue]{BANNER}[/bold blue]\n"
        f"{SLOGAN}\n\n"
        f"Workspace: {workspace}\n"
        f"Mode: {snap.permission_mode or 'ask'}\n"
        f"Project mode: {snap.project_mode or 'mixed'}\n"
        f"Style: {snap.operating_style or 'normal'}\n"
        "Type /help for commands, /suggest for next steps, /exit to quit."
    )


def dispatch(line: str, start: Path | None = None) -> ReplResult:
    """Interpret one input line. Pure and TTY-free for testability."""
    text = line.strip()
    if not text:
        return ReplResult()

    if text.startswith("/"):
        command, _, args = text[1:].partition(" ")
        command = command.lower()
        if command in {"exit", "quit"}:
            return ReplResult(messages=["Bye."], should_exit=True)
        if command == "clear":
            return ReplResult(should_clear=True)
        if command == "help":
            return ReplResult(messages=[_HELP_TEXT])
        if command == "suggest":
            return ReplResult(messages=[_format_suggest(start)])
        if command == "status":
            return ReplResult(messages=[_format_status(start)])
        if command == "diff":
            return ReplResult(messages=[_format_diff(start)])
        if command == "claims":
            return ReplResult(messages=[_format_claims(start)])
        if command == "experiments":
            return ReplResult(messages=[_format_experiments(start)])
        if command == "papers":
            return ReplResult(messages=[_format_papers(start)])
        if command == "tasks":
            return ReplResult(messages=[_format_tasks(start)])
        if command == "graph":
            return ReplResult(messages=[_format_graph(start)])
        if command == "related":
            return ReplResult(messages=[_format_related(args.strip(), start)])
        if command == "evidence":
            return ReplResult(messages=[_format_evidence(args.strip(), start)])
        if command == "why":
            return ReplResult(messages=[_format_why(args.strip(), start)])
        if command == "report":
            return ReplResult(messages=[_format_report(args.strip(), start)])
        if command == "problem":
            return ReplResult(messages=[_handle_problem(args.strip(), start)])
        if command == "patches":
            return ReplResult(messages=[_format_patches(start)])
        if command == "patch":
            return ReplResult(messages=[_format_patch(args.strip(), start)])
        if command == "memory":
            return ReplResult(messages=[_format_memory(start)])
        if command == "actions":
            return ReplResult(messages=[_format_actions(start)])
        if command == "history":
            return ReplResult(messages=[_format_history(args.strip())])
        if command == "permissions":
            return ReplResult(messages=[_format_permissions(start)])
        if command == "replay":
            return ReplResult(messages=[_format_replay(args.strip(), start)])
        if command == "usage":
            return ReplResult(messages=[_format_usage(start)])
        if command == "execute":
            return ReplResult(messages=[_handle_execute(args.strip(), start)])
        if command == "check":
            return ReplResult(messages=[_format_check(start)])
        if command == "checkpoint":
            return ReplResult(messages=[_handle_checkpoint(args.strip(), start)])
        if command == "context":
            return ReplResult(messages=[_format_context(start)])
        if command == "model":
            return ReplResult(messages=[_handle_model(args.strip(), start)])
        if command == "style":
            return ReplResult(messages=[_handle_style(args.strip(), start)])
        if command == "mode":
            return ReplResult(messages=[_handle_mode(args.strip(), start)])
        return ReplResult(messages=[f"Unknown command: /{command}. Type /help for the list."])

    # Natural-language input is handled by the agent loop in run_repl.
    return ReplResult(messages=[])


def _format_suggest(start: Path | None) -> str:
    from opentorus.suggest import format_suggestions_plain, suggest_for_cwd

    _root, _ot, items = suggest_for_cwd(limit=6)
    return format_suggestions_plain(items)


def _format_why(artifact_id: str, start: Path | None) -> str:
    """Trace an artifact back to its evidence and relations (wraps `explain`)."""
    artifact_id = artifact_id.strip().upper()
    if not artifact_id:
        return "Usage: /why <ARTIFACT-ID>  (e.g. /why CLAIM-0001)."
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    from opentorus.research.explain import explain
    from opentorus.workspace import workspace_dir

    try:
        res = explain(workspace_dir(root), artifact_id)
    except Exception as exc:  # noqa: BLE001 — surface a friendly message, not a traceback
        return f"Could not explain {artifact_id}: {exc}"
    lines = [f"{res.artifact_id} [{res.kind}] {res.title}".rstrip()]
    if res.status:
        lines.append(f"  status: {res.status}")
    if res.rigor:
        lines.append(f"  rigor: {res.rigor}")
    lines.append(
        f"  evidence: {len(res.supporting)} supporting, {len(res.contradicting)} contradicting"
    )
    if res.neighbors:
        lines.append(f"  related: {', '.join(res.neighbors)}")
    if res.open_findings:
        lines.append("  open findings:")
        lines.extend(f"    - {f}" for f in res.open_findings)
    return "\n".join(lines)


def _format_report(args: str, start: Path | None) -> str:
    """Rebuild the dossier report for a problem (defaults to the active problem)."""
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    from opentorus.research.dossier import store
    from opentorus.research.dossier.report import build_report
    from opentorus.workspace import workspace_dir

    ot = workspace_dir(root)
    pid = args.strip().upper() or store.get_active_problem(ot)
    if not pid:
        return "No problem given and no active problem. Try /report PROBLEM-0001 or /problem <id>."
    pid = store.canonical_problem_id(pid) or pid
    if store.get_dossier(ot, pid) is None:
        return f"No dossier {pid}."
    build_report(ot, pid, harvest_session=False)
    path = store.dossier_dir(ot, pid) / "report.md"
    return (
        f"Built report for {pid} → {path}\n"
        f"For the full LLM narrative/PDF run: opentorus problem report {pid}"
    )


def _handle_problem(args: str, start: Path | None) -> str:
    """Show the active problem and list dossiers, or set the active problem."""
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    from opentorus.research.dossier import store
    from opentorus.workspace import workspace_dir

    ot = workspace_dir(root)
    arg = args.strip().upper()
    if arg:
        pid = store.canonical_problem_id(arg) or arg
        if store.get_dossier(ot, pid) is None:
            return f"No dossier {pid}."
        store.set_active_problem(ot, pid)
        return f"Active problem set to {pid}."
    dossiers = store.list_dossiers(ot)
    if not dossiers:
        return 'No problems yet. Create one with: problem new "…"'
    active = store.get_active_problem(ot)
    return "\n".join(("→ " if d.id == active else "  ") + f"{d.id}: {d.title}" for d in dossiers)


def _format_status(start: Path | None) -> str:
    snap = gather_status(start)
    lines = [
        f"Workspace: {snap.workspace_root or 'none'}",
        f"Initialized: {'yes' if snap.initialized else 'no'}",
        f"Git branch: {snap.git_branch or 'n/a'}",
        f"Project mode: {snap.project_mode or 'n/a'}",
        f"Style: {snap.operating_style or 'n/a'}",
        f"Claims: {snap.num_claims}  Experiments: {snap.num_experiments}  "
        f"Actions: {snap.num_actions}  Evidence: {snap.num_evidence}",
    ]
    return "\n".join(lines)


def _format_memory(start: Path | None) -> str:
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    counts = {kind: len(list_memory(base, kind)) for kind in VALID_KINDS}
    body = "  ".join(f"{kind}: {count}" for kind, count in counts.items())
    return f"Memory entries by kind:\n  {body}"


def _format_actions(start: Path | None) -> str:
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    entries = list_actions(workspace_dir(root), limit=10)
    if not entries:
        return "No actions logged yet."
    lines = ["Recent actions:"]
    for i, entry in enumerate(entries, start=1):
        status = "ok" if entry.ok else "failed"
        lines.append(f"  {i}. {entry.tool_name} — {status}")
    return "\n".join(lines)


def _format_history(args: str) -> str:
    from opentorus.replhistory import readline_available, recent_history

    if not readline_available():
        return "History is unavailable (readline is not installed on this platform)."
    limit = 20
    if args:
        try:
            limit = max(1, int(args))
        except ValueError:
            return "Usage: /history [n]  (n = how many recent entries to show)"
    entries = recent_history(limit)
    if not entries:
        return "No history yet. Use ↑/↓ to recall inputs and Ctrl+R to search."
    lines = ["Recent input history (use ↑/↓ to recall, Ctrl+R to search):"]
    for i, entry in enumerate(entries, start=1):
        lines.append(f"  {i:>3}. {entry}")
    return "\n".join(lines)


def _format_diff(start: Path | None) -> str:
    from opentorus.tools.git import git_diff

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    result = git_diff(root)
    lines = result.output.splitlines()
    if len(lines) > 200:
        changed = [line[6:] for line in lines if line.startswith("+++ b/")]
        listing = "\n".join(f"  M {name}" for name in changed)
        return (
            f"Large diff ({len(lines)} lines). Changed files:\n{listing}\n"
            "Run `opentorus diff --full`."
        )
    return result.output


def _format_claims(start: Path | None) -> str:
    from opentorus.research.claims import list_claims

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    claims = list_claims(workspace_dir(root))
    if not claims:
        return "No claims yet."
    lines = ["Claims:"]
    for claim in claims:
        statement = claim.statement if len(claim.statement) <= 60 else claim.statement[:57] + "..."
        lines.append(f"  {claim.id} [{claim.status}] {statement}")
    return "\n".join(lines)


def _format_experiments(start: Path | None) -> str:
    from opentorus.research.experiments import list_experiments

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    experiments = list_experiments(workspace_dir(root))
    if not experiments:
        return "No experiments yet."
    lines = ["Experiments:"]
    for experiment in experiments:
        lines.append(f"  {experiment.id} [{experiment.status}] {experiment.title}")
    return "\n".join(lines)


def _format_papers(start: Path | None) -> str:
    from opentorus.research.papers import list_papers

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    papers = list_papers(workspace_dir(root))
    if not papers:
        return "No papers yet."
    lines = ["Papers:"]
    for paper in papers:
        pin = "pinned" if paper.pinned else "unpinned"
        lines.append(f"  {paper.id} [{paper.source_type}, {pin}] {paper.source}")
    return "\n".join(lines)


def _format_graph(start: Path | None) -> str:
    from opentorus.research.graph import list_edges

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    edges = list_edges(workspace_dir(root))
    if not edges:
        return "No graph edges yet."
    lines = ["Artifact graph:"]
    for edge in edges:
        lines.append(f"  {edge.id}: {edge.source_id} —{edge.relation}→ {edge.target_id}")
    return "\n".join(lines)


def _format_related(artifact_id: str, start: Path | None) -> str:
    from opentorus.research.graph import related

    if not artifact_id:
        return "Usage: /related <artifact-id>"
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    edges = related(workspace_dir(root), artifact_id)
    if not edges:
        return f"No relations for {artifact_id}."
    lines = [f"Relations for {artifact_id}:"]
    for edge in edges:
        direction = "→" if edge.source_id == artifact_id else "←"
        other = edge.target_id if edge.source_id == artifact_id else edge.source_id
        lines.append(f"  {edge.id}: {edge.relation} {direction} {other}")
    return "\n".join(lines)


def _format_patches(start: Path | None) -> str:
    from opentorus.research.patches import list_patches

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    patches = list_patches(workspace_dir(root))
    if not patches:
        return "No patches yet."
    lines = ["Patches:"]
    for patch in patches:
        lines.append(f"  {patch.id} [{patch.status}] {patch.reason}")
    return "\n".join(lines)


def _format_patch(patch_id: str, start: Path | None) -> str:
    from opentorus.research.patches import get_patch, read_diff

    if not patch_id:
        return "Usage: /patch <patch-id>"
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    patch = get_patch(base, patch_id)
    if patch is None:
        return f"No patch with id '{patch_id}'."
    diff = read_diff(base, patch)
    lines = diff.splitlines()
    if len(lines) > 100:
        diff = "\n".join(lines[:100]) + f"\n... ({len(lines)} lines total)"
    header = (
        f"{patch.id} [{patch.status}] {patch.reason}\nFiles: {', '.join(patch.files_changed)}\n"
    )
    return header + (diff or "(empty diff)")


def _format_evidence(claim_id: str, start: Path | None) -> str:
    from opentorus.research.evidence import list_evidence

    if not claim_id:
        return "Usage: /evidence <claim-id>"
    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    entries = list_evidence(workspace_dir(root), claim_id)
    if not entries:
        return f"No evidence for {claim_id}."
    lines = [f"Evidence for {claim_id}:"]
    for ev in entries:
        source = f"{ev.source_type}:{ev.source_id}" if ev.source_id else ev.source_type
        lines.append(f"  {ev.id} [{ev.direction}/{ev.strength}] ({source}) {ev.summary}")
    return "\n".join(lines)


def _format_tasks(start: Path | None) -> str:
    from opentorus.research.tasks import list_tasks

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    tasks = list_tasks(workspace_dir(root))
    if not tasks:
        return 'No tasks yet. Plan some with `opentorus task plan "<goal>"`.'
    lines = ["Tasks:"]
    for task in tasks:
        lines.append(f"  {task.id} [{task.category}/{task.status}] {task.goal}")
    return "\n".join(lines)


def _format_permissions(start: Path | None) -> str:
    snap = gather_status(start)
    mode = snap.permission_mode or "ask"
    descriptions = {
        "safe": "read-only; writes and non-trivial commands are blocked",
        "ask": "reads allowed; writes and commands require confirmation",
        "trusted": "normal development allowed; dangerous commands still blocked",
    }
    return (
        f"Permission mode: {mode}\n"
        f"  {descriptions.get(mode, 'unknown mode')}\n"
        "Dangerous commands are always blocked and sensitive files are guarded, "
        "regardless of mode."
    )


def _handle_execute(args: str, start: Path | None) -> str:
    from opentorus.agent.executor import execute_plan
    from opentorus.config import CONFIG_FILENAME, default_config, load_config
    from opentorus.errors import OpenTorusError, ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.tools.builtin import build_default_registry

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    config_path = base / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()
    try:
        provider = get_provider(config)
        registry = build_default_registry(root, base, config)
        outcome = execute_plan(
            root,
            base,
            provider,
            registry,
            config,
            goal=args or None,
        )
    except (ProviderError, OpenTorusError) as exc:
        return f"Execution error: {exc}"
    if not outcome.tasks:
        return "No pending tasks to execute."
    return "\n".join(f"{r.task_id} → {r.status}: {r.answer}" for r in outcome.tasks)


def _format_replay(args: str, start: Path | None) -> str:
    from opentorus.agent.replay import summarize_session

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    arg = args.strip()
    if not arg or arg == "last":
        return summarize_session(base)
    return summarize_session(base, arg)


def _format_usage(start: Path | None) -> str:
    from opentorus.usage import summarize_usage

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    summary = summarize_usage(workspace_dir(root))
    if summary.turns == 0:
        return "No usage recorded yet."
    lines = [
        "Usage (all sessions):",
        f"  turns: {summary.turns}",
        f"  total tokens: {summary.total_tokens} "
        f"(prompt {summary.prompt_tokens}, completion {summary.completion_tokens})",
        f"  est. cost: ${summary.cost_usd:.4f} (estimated)",
        f"  avg latency: {summary.avg_latency_ms} ms",
    ]
    return "\n".join(lines)


def _format_check(start: Path | None) -> str:
    from opentorus.config import CONFIG_FILENAME, default_config, load_config
    from opentorus.quality import run_checks

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    config_path = base / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()
    results = run_checks(root, base, config)
    lines = ["Quality gates:"]
    for result in results:
        if result.skipped:
            state = "skipped"
        elif result.ok:
            state = "passed"
        else:
            state = f"failed (exit {result.exit_code})"
        lines.append(f"  {result.name}: {state}")
    return "\n".join(lines)


def _handle_checkpoint(args: str, start: Path | None) -> str:
    from opentorus.errors import OpenTorusError
    from opentorus.research.checkpoints import create_checkpoint, list_checkpoints

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)

    parts = args.split(maxsplit=1)
    if not parts or parts[0] == "list":
        checkpoints = list_checkpoints(base)
        if not checkpoints:
            return "No checkpoints yet. Create one with `/checkpoint create <label>`."
        lines = ["Checkpoints:"]
        for cp in checkpoints:
            ref = (cp.git_commit or "")[:8] if cp.kind == "git" else f"{len(cp.manifest)} files"
            lines.append(f"  {cp.id} [{cp.kind}] {cp.label} ({ref})")
        return "\n".join(lines)
    if parts[0] == "create":
        label = parts[1].strip() if len(parts) > 1 else ""
        if not label:
            return "Usage: /checkpoint create <label>"
        try:
            cp = create_checkpoint(root, base, label)
        except OpenTorusError as exc:
            return str(exc)
        return f"{cp.id} checkpoint recorded ({cp.kind})."
    return "Usage: /checkpoint create <label>  |  /checkpoint list"


def _format_context(start: Path | None) -> str:
    from opentorus.agent.context import build_context_summary
    from opentorus.config import CONFIG_FILENAME, default_config, load_config
    from opentorus.tools.builtin import build_default_registry

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    config_path = base / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()
    registry = build_default_registry(root, base, config)
    from opentorus.agent.context import latest_user_query, select_relevant
    from opentorus.privacy import provider_context_notice

    summary = build_context_summary(root, base, config, registry.names())
    selected = select_relevant(base, config, latest_user_query(base))
    notice = provider_context_notice(config, registry.names(), selected=selected)
    return f"{summary}\n\n{notice}"


def _handle_model(args: str, start: Path | None) -> str:
    from opentorus.config import (
        CONFIG_FILENAME,
        default_config,
        load_config,
        set_dotted,
        write_config,
    )
    from opentorus.errors import ConfigError

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    config_path = base / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()

    if not args:
        m = config.model
        return (
            f"Model config:\n  provider: {m.provider}\n  name: {m.name}\n"
            f"  temperature: {m.temperature}\n  base_url: {m.base_url or 'none'}"
        )

    parts = args.split()
    if len(parts) != 3 or parts[0] != "set":
        return "Usage: /model set <key> <value> (keys: provider, name, temperature, base_url)"
    _, key, value = parts
    try:
        updated = set_dotted(config, f"model.{key}", value)
    except ConfigError as exc:
        return str(exc)
    write_config(config_path, updated)
    return f"Set model.{key} = {value}"


_VALID_STYLES = ("cautious", "normal", "fast", "autonomous")
_VALID_MODES = ("normal", "review")


def _set_config_value(start: Path | None, dotted: str, value: str) -> str | None:
    """Persist a single dotted config value. Returns an error string or None."""
    from opentorus.config import (
        CONFIG_FILENAME,
        default_config,
        load_config,
        set_dotted,
        write_config,
    )
    from opentorus.errors import ConfigError

    root = find_workspace_root(start)
    if root is None:
        return "No workspace found. Run `opentorus init` first."
    base = workspace_dir(root)
    config_path = base / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()
    try:
        updated = set_dotted(config, dotted, value)
    except ConfigError as exc:
        return str(exc)
    write_config(config_path, updated)
    return None


def _handle_style(args: str, start: Path | None) -> str:
    from opentorus.config import CONFIG_FILENAME, default_config, load_config

    if not args:
        root = find_workspace_root(start)
        if root is None:
            return "No workspace found. Run `opentorus init` first."
        config_path = workspace_dir(root) / CONFIG_FILENAME
        config = load_config(config_path) if config_path.is_file() else default_config()
        return f"Operating style: {config.agent.style} (choices: {', '.join(_VALID_STYLES)})"
    if args not in _VALID_STYLES:
        return f"Unknown style '{args}'. Choices: {', '.join(_VALID_STYLES)}."
    error = _set_config_value(start, "agent.style", args)
    return error or f"Operating style set to '{args}'."


def _handle_mode(args: str, start: Path | None) -> str:
    from opentorus.config import CONFIG_FILENAME, default_config, load_config

    if not args:
        root = find_workspace_root(start)
        if root is None:
            return "No workspace found. Run `opentorus init` first."
        config_path = workspace_dir(root) / CONFIG_FILENAME
        config = load_config(config_path) if config_path.is_file() else default_config()
        return f"Agent mode: {config.agent.mode} (choices: {', '.join(_VALID_MODES)})"
    if args not in _VALID_MODES:
        return f"Unknown mode '{args}'. Choices: {', '.join(_VALID_MODES)}."
    error = _set_config_value(start, "agent.mode", args)
    if error:
        return error
    if args == "review":
        return "Agent mode set to 'review' — read-only: inspect and critique, but no edits."
    return "Agent mode set to 'normal'."


_SLASH_COMMANDS = (
    "/help",
    "/suggest",
    "/status",
    "/diff",
    "/claims",
    "/experiments",
    "/papers",
    "/tasks",
    "/graph",
    "/related",
    "/evidence",
    "/why",
    "/report",
    "/problem",
    "/patches",
    "/patch",
    "/memory",
    "/actions",
    "/history",
    "/permissions",
    "/style",
    "/mode",
    "/execute",
    "/replay",
    "/usage",
    "/check",
    "/checkpoint",
    "/context",
    "/model",
    "/clear",
    "/exit",
)


def _arg_options(command: str, preceding: list[str]) -> list[str]:
    """Completion candidates for the argument after a slash command."""
    if command == "/style":
        return list(_VALID_STYLES) if not preceding else []
    if command == "/mode":
        return list(_VALID_MODES) if not preceding else []
    if command == "/checkpoint":
        return ["create", "list"] if not preceding else []
    if command == "/replay":
        return ["last"] if not preceding else []
    if command == "/model":
        if not preceding:
            return ["set"]
        if preceding == ["set"]:
            return ["provider", "name", "temperature", "base_url"]
        if preceding == ["set", "provider"]:
            return ["mock", "openai", "anthropic", "ollama"]
        return []
    return []


# Commands whose first argument is an artifact id, and the kind to offer.
_ID_COMMANDS = {
    "/evidence": "claim",
    "/patch": "patch",
    "/related": "any",
}


def _artifact_ids(start: Path | None, kind: str) -> list[str]:
    """List artifact ids for completion (best effort; never raises)."""
    from opentorus.errors import OpenTorusError

    root = find_workspace_root(start)
    if root is None:
        return []
    base = workspace_dir(root)
    ids: list[str] = []
    try:
        if kind in ("claim", "any"):
            from opentorus.research.claims import list_claims

            ids += [c.id for c in list_claims(base)]
        if kind in ("patch", "any"):
            from opentorus.research.patches import list_patches

            ids += [p.id for p in list_patches(base)]
        if kind == "any":
            from opentorus.research.experiments import list_experiments
            from opentorus.research.papers import list_papers

            ids += [e.id for e in list_experiments(base)]
            ids += [p.id for p in list_papers(base)]
    except OpenTorusError:
        return ids
    return ids


def complete_repl(line: str, text: str, start: Path | None = None) -> list[str]:
    """Return TAB-completion candidates for a REPL input line. Pure/testable.

    Only slash-command lines complete; natural-language input is left untouched.
    Artifact-id arguments (``/evidence``, ``/patch``, ``/related``) complete
    against the live workspace when ``start`` resolves to one.
    """
    if not line.lstrip().startswith("/"):
        return []
    stripped = line.lstrip()
    tokens = stripped.split()
    completing_first = " " not in stripped
    current = text

    if completing_first:
        return [c for c in _SLASH_COMMANDS if c.startswith(current)]

    command = tokens[0]
    preceding = tokens[1:] if line.endswith(" ") else tokens[1:-1]

    if command in _ID_COMMANDS and not preceding:
        ids = _artifact_ids(start, _ID_COMMANDS[command])
        return [i for i in ids if i.startswith(current)]

    options = _arg_options(command, preceding)
    return [o for o in options if o.startswith(current)]


_CLI_PREFIXES = ("python -m opentorus", "opentorus")


def _strip_cli_prefix(text: str) -> str | None:
    """Return the args after a leading ``opentorus`` invocation, else ``None``."""
    for prefix in _CLI_PREFIXES:
        if text == prefix:
            return ""
        if text.startswith(prefix + " "):
            return text[len(prefix) + 1 :].strip()
    return None


def _maybe_cli_hint(text: str, start: Path | None) -> str | None:
    """Catch users typing a full ``opentorus …`` command inside the session.

    Inside the REPL, commands are slash commands; a bare ``opentorus …`` line
    would otherwise be sent verbatim to the model (which is confusing — the model
    often just suggests the very command the user typed). We detect that, perform
    the obvious in-session equivalent for ``config set``, and otherwise explain
    how to drive the session. Returns ``None`` when the input is not a CLI
    invocation, so normal natural-language input is unaffected.
    """
    rest = _strip_cli_prefix(text.strip())
    if rest is None:
        return None

    if rest.startswith("config set "):
        args = rest[len("config set ") :].split(maxsplit=1)
        if len(args) == 2:
            key, value = args[0], args[1].strip().strip('"').strip("'")
            error = _set_config_value(start, key, value)
            if error:
                return error
            return (
                f"Set {key} = {value}.\n"
                "(Inside the session you don't need the `opentorus` prefix — use "
                "slash commands like /model, or `/model set <key> <value>`.)"
            )

    return (
        "It looks like you typed a full `opentorus` command inside the session.\n"
        "Here, commands are slash commands — type /help for the list "
        "(e.g. /status, /model, /claims, /history). Run full `opentorus …` "
        "commands in a separate terminal instead.\n"
        "This line was not sent to the model."
    )


def _math_transform(start: Path | None):
    """Return the LaTeX→Unicode line renderer unless disabled in config."""
    from opentorus.config import CONFIG_FILENAME, default_config, load_config

    root = find_workspace_root(start)
    if root is None:
        config = default_config()
    else:
        config_path = workspace_dir(root) / CONFIG_FILENAME
        config = load_config(config_path) if config_path.is_file() else default_config()
    if not config.ui.render_math:
        return None
    from opentorus.mathtext import render_math_line

    return render_math_line


def _read_line(console: Console) -> str:
    """Read one input line, using readline editing (arrows + Ctrl+R) when able.

    When readline is active and we are attached to a TTY we drive the built-in
    ``input()`` with an ANSI-colored prompt (escape codes wrapped in the
    ``\\001``/``\\002`` non-printing markers so the line width stays correct).
    Otherwise we fall back to Rich's ``console.input`` with markup.
    """
    from opentorus.replhistory import readline_available

    if readline_available() and sys.stdin.isatty():
        console.print()  # spacing, matching the previous leading newline
        prompt = f"\001\033[1;36m\002{PROMPT}\001\033[0m\002"
        return input(prompt)
    return console.input(f"\n[bold cyan]{PROMPT}[/bold cyan]")


def run_repl(console: Console | None = None, start: Path | None = None) -> None:
    """Run the interactive read-eval-print loop."""
    from opentorus.ux import make_console

    console = console or make_console()
    console.print(build_banner(start))

    root = find_workspace_root(start)
    base = workspace_dir(root) if root is not None else None
    session_id = uuid.uuid4().hex

    from opentorus.approvals import make_console_confirm
    from opentorus.config import CONFIG_FILENAME, default_config, load_config
    from opentorus.replhistory import enable_completion, save_history, setup_history

    config = default_config()
    if base is not None:
        config_path = base / CONFIG_FILENAME
        if config_path.is_file():
            config = load_config(config_path)

    setup_history()
    enable_completion(lambda line, text: complete_repl(line, text, start))
    _confirm = make_console_confirm(console, config=config)

    try:
        while True:
            try:
                line = _read_line(console)
            except (EOFError, KeyboardInterrupt):
                console.print("\nBye.")
                return

            stripped = line.strip()
            if stripped and not stripped.startswith("/"):
                cli_hint = _maybe_cli_hint(stripped, start)
                if cli_hint is not None:
                    console.print(cli_hint)
                    save_history()
                    continue

                try:
                    _run_agent_turn(
                        console,
                        root,
                        base,
                        stripped,
                        session_id=session_id,
                        confirm=_confirm,
                        start=start,
                    )
                except KeyboardInterrupt:
                    # Ctrl-C cancels the current turn, not the whole session.
                    from opentorus.ux import format_interrupt_message

                    console.print("\n" + format_interrupt_message("Turn"))
                save_history()
                continue

            result = dispatch(line, start)
            save_history()
            if result.should_clear:
                console.clear()
            for message in result.messages:
                console.print(message)
            if result.should_exit:
                return
    finally:
        save_history()


def _run_agent_turn(
    console: Console,
    root: Path | None,
    base: Path | None,
    task: str,
    session_id: str | None = None,
    confirm=None,
    start: Path | None = None,
) -> None:
    """Run one natural-language turn with a live activity spinner and streaming.

    Shows an animated indicator (label + clock + elapsed seconds) while the model
    thinks and while tools run, pausing it whenever the model streams text or a
    confirmation prompt is needed, then prints the final answer.
    """
    from opentorus.ux import ActivityIndicator, StreamPrinter, activity_label

    indicator = ActivityIndicator(console)
    printer = StreamPrinter(console, transform=_math_transform(start), indicator=indicator)

    def _on_status(phase: str, detail: str | None) -> None:
        indicator.update(activity_label(phase, detail))

    def _confirm_paused(decision, description, session_scope=None):
        # Drop the spinner before prompting so the question and its input prompt
        # render cleanly; the next model step restarts the indicator.
        indicator.pause()
        return confirm(decision, description, session_scope) if confirm else False

    try:
        answer = _run_agent(
            root,
            base,
            task,
            session_id=session_id,
            confirm=_confirm_paused if confirm else None,
            on_text=printer,
            on_status=_on_status,
        )
    finally:
        indicator.stop()
    printer.finish(answer)


def _run_agent(
    root: Path | None,
    base: Path | None,
    task: str,
    session_id: str | None = None,
    confirm=None,
    on_text=None,
    on_status=None,
) -> str:
    if root is None or base is None:
        return "No workspace found. Run `opentorus init` first."
    from opentorus.agent.loop import AgentLoop
    from opentorus.config import CONFIG_FILENAME, default_config, load_config
    from opentorus.errors import ProviderError
    from opentorus.providers.registry import get_provider
    from opentorus.tools.builtin import build_default_registry

    config_path = base / CONFIG_FILENAME
    config = load_config(config_path) if config_path.is_file() else default_config()
    try:
        provider = get_provider(config)
        registry = build_default_registry(root, base, config)
        loop = AgentLoop(
            root,
            base,
            provider,
            registry,
            config,
            max_steps=config.agent.max_steps,
            session_id=session_id,
            confirm=confirm,
            on_text=on_text,
            on_status=on_status,
        )
        return loop.run(task)
    except ProviderError as exc:
        return f"Provider error: {exc}"
