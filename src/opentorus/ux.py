"""Shared UX helpers: logging setup and actionable error formatting.

These keep CLI output consistent and human-friendly: failures explain what ran,
how it failed, the likely cause, and a concrete next action instead of dumping a
raw traceback or a wall of output.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

logger = logging.getLogger("opentorus")


def make_console(**kwargs: Any):
    """Create a Rich ``Console`` with deterministic, user-respecting color.

    Honors the ``NO_COLOR`` convention (https://no-color.org): when ``NO_COLOR``
    is set, color is disabled regardless of terminal detection. Otherwise Rich's
    own tty detection applies. Centralizing construction here keeps color behavior
    consistent across the CLI/REPL/TUI and testable. Extra ``kwargs`` are passed
    through to :class:`rich.console.Console` (e.g. ``width``, ``record``, ``file``).
    """
    import os

    from rich.console import Console

    if os.environ.get("NO_COLOR") is not None:
        kwargs.setdefault("no_color", True)
    return Console(**kwargs)


# Friendly, human-readable labels for the activity spinner, keyed by tool name.
# Unknown tools fall back to their raw name so new tools still show *something*.
_TOOL_LABELS = {
    "web_search": "Searching the web",
    "lit_search": "Searching the literature",
    "fetch_url": "Fetching a page",
    "paper_fetch": "Fetching a paper",
    "paper_list": "Listing papers",
    "paper_read": "Reading a paper note",
    "paper_add": "Adding a paper",
    "paper_ingest_inbox": "Ingesting inbox PDFs",
    "paper_extract_problems": "Extracting open problems",
    "proof_write": "Writing proof artifact",
    "counterexample_search": "Searching for counterexamples",
    "memory_add": "Recording memory",
    "claim_new": "Creating a claim",
    "evidence_add": "Linking evidence",
    "exp_run": "Running an experiment",
    "read_file": "Reading a file",
    "list_files": "Listing files",
    "glob_files": "Finding files",
    "write_file": "Writing a file",
    "apply_patch": "Editing a file",
    "run_shell": "Running a command",
    "git_diff": "Inspecting changes",
    "status": "Checking status",
    "memory_list": "Reading memory",
}


def activity_label(phase: str, detail: str | None = None) -> str:
    """Map an agent-loop status event to a short, human-readable label.

    ``phase`` is ``"model"`` (the model is deciding what to do) or ``"tool"``
    (a tool is running); ``detail`` carries the tool name for the latter.
    """
    if phase == "tool" and detail:
        return _TOOL_LABELS.get(detail, f"Running {detail}")
    return "Thinking"


def compose_progress_label(message: str) -> str:
    """Map report/PDF export progress text to a short spinner label."""
    lower = message.lower()
    if any(
        phrase in lower
        for phrase in (
            "finding open problems",
            "writing report narrative",
            "converting",
            "composing narrative",
            "composing",
        )
    ):
        return "Thinking"
    if "rendering pdf" in lower or "compiling pdf" in lower:
        return "Compiling PDF"
    if "gathering" in lower or "harvest" in lower:
        return "Gathering artifacts"
    if "assembling" in lower:
        return "Assembling report"
    trimmed = message.rstrip(".…").strip()
    return trimmed[:48] if trimmed else "Working"


class ActivityIndicator:
    """A live spinner that shows the agent is working, plus a clock and timer.

    Modeled on the "the assistant is working" affordance in tools like Claude
    Code: an animated spinner, a short label of *what* is happening (thinking vs.
    a specific tool), the current wall-clock time, and the seconds elapsed in the
    current phase. The label and timer update live because the spinner re-renders
    this object (via :meth:`__rich__`) on every refresh tick.

    It is a no-op when output is not an interactive terminal so piped or captured
    output stays clean.
    """

    def __init__(
        self,
        console: Any,
        *,
        enabled: bool | None = None,
        spinner: str = "dots",
    ) -> None:
        self._console = console
        if enabled is None:
            import sys

            enabled = sys.stdout.isatty()
        self._enabled = enabled
        self._spinner = spinner
        self._status: Any = None
        self._label = ""
        self._phase_started = time.monotonic()

    def __rich__(self) -> Any:
        from rich.text import Text

        elapsed = time.monotonic() - self._phase_started
        clock = datetime.now().strftime("%H:%M:%S")
        return Text.assemble(
            (f"{self._label or 'Working'}…", "bold cyan"),
            (f"  · {clock} · {elapsed:.0f}s", "dim"),
        )

    def update(self, label: str) -> None:
        """Show ``label`` and (re)start the spinner, resetting the phase timer."""
        if not self._enabled:
            return
        self._label = label
        self._phase_started = time.monotonic()
        if self._status is None:
            self._status = self._console.status(self, spinner=self._spinner)
            self._status.start()

    def pause(self) -> None:
        """Temporarily hide the spinner so streamed output prints cleanly.

        A later :meth:`update` resumes it. Safe to call when not running.
        """
        if self._status is not None:
            self._status.stop()
            self._status = None

    def stop(self) -> None:
        """Stop and clear the spinner entirely."""
        self.pause()


class StreamPrinter:
    """Prints streamed text and remembers whether anything streamed.

    Used as the agent loop's ``on_text`` callback so the CLI/REPL can render a
    response, then avoid printing the final message twice. Output is buffered and
    emitted line by line so an optional ``transform`` (e.g. LaTeX→Unicode math
    rendering) can be applied to whole lines, while fenced code blocks are left
    verbatim.

    When an :class:`ActivityIndicator` is supplied it is paused as soon as text
    starts streaming, so the spinner does not fight with the model's output.
    """

    def __init__(
        self,
        console: Any,
        transform: Callable[[str], str] | None = None,
        indicator: ActivityIndicator | None = None,
    ) -> None:
        self._console = console
        self.streamed = False
        self._transform = transform
        self._indicator = indicator
        self._buffer = ""
        self._in_fence = False

    def _emit(self, line: str) -> None:
        if line.lstrip().startswith("```"):
            self._in_fence = not self._in_fence
            self._console.print(line, markup=False, highlight=False)
            return
        if not self._in_fence:
            line = normalize_terminal_text(line)
        if self._transform is not None and not self._in_fence:
            line = self._transform(line)
        self._console.print(line, markup=False, highlight=False)

    def __call__(self, chunk: str) -> None:
        if self._indicator is not None:
            self._indicator.pause()
        self.streamed = True
        self._buffer += chunk
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            self._emit(line)

    def finish(self, answer: str) -> None:
        """Flush remaining streamed text, or print the full answer if none streamed."""
        if self.streamed:
            if self._buffer:
                self._emit(self._buffer)
                self._buffer = ""
        else:
            for line in answer.split("\n"):
                self._emit(line)


_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TABLE_ROW_RE = re.compile(r"^\|.+\|$")
_TRACE_ROLE_LIMITS: dict[str, int] = {
    "tool": 320,
    "assistant": 800,
    "user": 800,
    "system": 600,
}


def normalize_terminal_text(text: str) -> str:
    """Make model markdown/HTML easier to read in a plain terminal."""
    if not text:
        return ""
    text = _BR_RE.sub("\n", text)
    lines: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            if lines and lines[-1]:
                lines.append("")
            continue
        if _TABLE_ROW_RE.match(line):
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            line = " · ".join(cell for cell in cells if cell)
        else:
            line = re.sub(r"[ \t]{2,}", " ", line)
        lines.append(line)
    return "\n".join(lines).strip()


def _summarize_tool_trace(content: str, tool_name: str | None) -> str:
    """Keep verbose traces short for bulky tool results."""
    first_line = content.split("\n", 1)[0].strip()
    if tool_name == "proof_write" and first_line.startswith("created PROOF-"):
        summary_lines = [first_line]
        for line in content.splitlines()[1:4]:
            stripped = line.strip()
            if stripped.startswith("Gaps recorded:"):
                summary_lines.append(stripped)
                break
        return "\n".join(summary_lines)
    if tool_name in {
        "read_file",
        "glob_files",
        "list_files",
        "paper_list",
        "status",
        "paper_fetch",
    }:
        return first_line if len(content) <= 240 else first_line + "\n… (truncated)"
    if tool_name in {"lit_search", "web_search"}:
        return first_line if len(content) <= 320 else first_line + "\n… (truncated)"
    if tool_name == "paper_fetch":
        for line in content.splitlines()[:3]:
            if line.strip().startswith("PAPER-"):
                return line.strip()
        return first_line
    return content


def format_trace_message(
    role: str,
    content: str,
    *,
    debug: bool = False,
    tool_name: str | None = None,
    preview_limit: int | None = None,
) -> str:
    """Normalize and truncate session text for ``--verbose`` LLM traces."""
    normalized = normalize_terminal_text(content)
    if debug:
        return normalized
    if role == "tool":
        normalized = _summarize_tool_trace(normalized, tool_name)
    limit = preview_limit if preview_limit is not None else _TRACE_ROLE_LIMITS.get(role, 800)
    if len(normalized) > limit:
        return normalized[:limit] + "…"
    return normalized


def setup_logging(verbose: bool = False, debug: bool = False) -> None:
    """Configure the OpenTorus logger. ``--debug`` wins over ``--verbose``."""
    level = logging.WARNING
    if debug:
        level = logging.DEBUG
    elif verbose:
        level = logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(name)s: %(message)s",
    )
    logger.setLevel(level)


def _format_tool_args(args: dict, *, debug: bool) -> str:
    """Pretty-print tool arguments for verbose traces."""
    import json

    if debug:
        return json.dumps(args, ensure_ascii=False, indent=2, default=str)
    compact = json.dumps(args, ensure_ascii=False, default=str)
    if len(compact) <= 400:
        return compact
    return compact[:400] + "…"


class LlmTraceSession:
    """Incremental, step-oriented LLM trace for ``--verbose`` / ``--debug``.

    Prints only *new* session messages each step (not the full growing context),
    labels tool I/O clearly, and separates streamed model output from context
    dumps — so long agent runs (e.g. ``opentorus prove --verbose``) stay readable.
    """

    _ROLE_STYLE = {
        "user": "yellow",
        "assistant": "cyan",
        "tool": "green",
        "system": "dim",
    }

    def __init__(
        self,
        console: Any,
        *,
        debug: bool = False,
        user_on_text: Callable[[str], None] | None = None,
        indicator: ActivityIndicator | None = None,
    ) -> None:
        self._console = console
        self._debug = debug
        self._user_on_text = user_on_text
        self._indicator = indicator
        self._step = 0
        # Content signatures of messages already shown. The provider message list
        # is rebuilt (and windowed) each turn rather than appended to, so a simple
        # index slice would misreport genuinely-new tool/user turns as "no new
        # context"; track by content instead.
        self._seen_sigs: set[str] = set()
        self._banner: str | None = None
        self._tools_shown = False
        self._stream_prefix_printed = False
        self._thinking_prefix_printed = False
        self._streamed_chars = 0

    def set_banner(self, label: str | None) -> None:
        """Mark a high-level phase (e.g. literature vs proof) in the trace."""
        if not label or label == self._banner:
            return
        self._banner = label
        self._console.print()
        self._console.rule(f"[bold cyan]{label}[/bold cyan]")

    def on_request(self, messages: list[Any], tools: list[dict] | None) -> None:
        from opentorus.agent.session import SessionMessage

        self._step += 1
        self._stream_prefix_printed = False
        self._thinking_prefix_printed = False
        self._streamed_chars = 0

        def _sig(message: Any) -> str:
            role = getattr(message, "role", "?")
            content = getattr(message, "content", "") or ""
            tool_calls = ""
            meta = getattr(message, "metadata", None)
            if isinstance(meta, dict):
                tool_calls = str(meta.get("tool_calls", ""))
            return f"{role}\x00{content}\x00{tool_calls}"

        new_messages = [m for m in messages if _sig(m) not in self._seen_sigs]
        self._seen_sigs.update(_sig(m) for m in messages)

        header_parts = [f"Step {self._step}", f"context {len(messages)} msgs"]
        if self._banner:
            header_parts.insert(1, self._banner)
        self._console.print()
        self._console.print(f"[bold]{' · '.join(header_parts)}[/bold]")

        if self._step == 1:
            for message in messages:
                if isinstance(message, SessionMessage) and message.role == "system":
                    self._print_system_summary(message)
                    break

        if not new_messages:
            if self._step > 1:
                self._console.print("  [dim](recovery turn — no new context)[/dim]")
        else:
            for message in new_messages:
                if (
                    isinstance(message, SessionMessage)
                    and message.role == "system"
                    and self._step == 1
                ):
                    continue
                self._print_message(message)

        if tools and (self._debug or not self._tools_shown):
            names = ", ".join(tool.get("name", "?") for tool in tools)
            self._console.print(f"  [dim]available tools ({len(tools)}): {names}[/dim]")
            self._tools_shown = True

    def _print_system_summary(self, message: Any) -> None:
        content = message.content or ""
        if self._debug:
            self._print_message(message)
            return
        self._console.print(
            f"  [dim]system[/dim] ({len(content)} chars — use --debug for full prompt)"
        )

    def _print_message(self, message: Any) -> None:
        role = message.role
        tool_name = message.metadata.get("name") if role == "tool" else None
        label = f"tool:{tool_name}" if tool_name else role
        style = self._ROLE_STYLE.get(role, "white")

        content = message.content or ""
        if message.images:
            content = f"{content}\n({len(message.images)} image(s))".strip()
        formatted = format_trace_message(
            role,
            content,
            debug=self._debug,
            tool_name=str(tool_name) if tool_name else None,
        )
        if not formatted:
            self._console.print(f"  [{style}]{label}[/{style}] [dim](empty)[/dim]")
            return

        lines = formatted.splitlines()
        if len(lines) == 1:
            self._console.print(f"  [{style}]{label}[/{style}] {lines[0]}")
            return
        self._console.print(f"  [{style}]{label}[/{style}]")
        for line in lines:
            self._console.print(f"    {line}")

    def on_response(self, response: Any) -> None:
        from opentorus.providers.base import ProviderResponse

        if not isinstance(response, ProviderResponse):
            return
        if response.kind == "tool_call":
            args_text = _format_tool_args(response.tool_args or {}, debug=self._debug)
            self._console.print(f"  [green]→ call[/green] [bold]{response.tool_name}[/bold]")
            if "\n" in args_text:
                for line in args_text.splitlines():
                    self._console.print(f"    [dim]{line}[/dim]")
            else:
                self._console.print(f"    [dim]{args_text}[/dim]")
        elif response.content:
            if self._streamed_chars:
                self._console.print(
                    f"  [dim]→ reply ({self._streamed_chars} chars streamed above)[/dim]"
                )
            else:
                preview = format_trace_message("assistant", response.content, debug=self._debug)
                if self._debug:
                    self._console.print("  [cyan]→ reply[/cyan]")
                    for line in preview.splitlines():
                        self._console.print(f"    {line}")
                else:
                    one_line = preview.replace("\n", " ")
                    if len(one_line) > 240:
                        one_line = one_line[:240] + "…"
                    self._console.print(f"  [cyan]→ reply[/cyan] {one_line}")
        if self._stream_prefix_printed or self._thinking_prefix_printed:
            self._console.print()
        self._stream_prefix_printed = False
        self._thinking_prefix_printed = False

    def on_text(self, chunk: str) -> None:
        if not chunk:
            return
        if self._indicator is not None:
            self._indicator.pause()
        if not self._stream_prefix_printed:
            self._console.print("  [cyan]assistant[/cyan] ", end="")
            self._stream_prefix_printed = True
        self._streamed_chars += len(chunk)
        self._console.print(chunk, end="", markup=False, highlight=False)
        if self._user_on_text is not None:
            if isinstance(self._user_on_text, StreamPrinter):
                self._user_on_text.streamed = True
            else:
                self._user_on_text(chunk)

    def on_thinking(self, chunk: str) -> None:
        if not chunk.strip():
            return
        if self._indicator is not None:
            self._indicator.pause()
        if not self._thinking_prefix_printed:
            self._console.print("  [dim italic]thinking[/dim italic] ", end="")
            self._thinking_prefix_printed = True
        self._console.print(chunk, end="", markup=False, highlight=False, style="dim italic")


def make_llm_trace(
    console: Any,
    *,
    verbose: bool = False,
    debug: bool = False,
    user_on_text: Callable[[str], None] | None = None,
    indicator: ActivityIndicator | None = None,
) -> tuple[
    Callable[[list[Any], list[dict] | None], None] | None,
    Callable[[Any], None] | None,
    Callable[[str], None] | None,
    bool,
    Callable[[str], None] | None,
    LlmTraceSession | None,
]:
    """Build optional LLM request/response trace hooks for ``--verbose`` / ``--debug``.

    Returns ``(on_request, on_response, on_text, stream_llm, on_thinking, trace)``.
    """
    if not verbose and not debug:
        return None, None, user_on_text, False, None, None

    trace = LlmTraceSession(
        console,
        debug=debug,
        user_on_text=user_on_text,
        indicator=indicator,
    )
    return trace.on_request, trace.on_response, trace.on_text, True, trace.on_thinking, trace


def make_llm_stream_callbacks(
    console: Any,
    *,
    indicator: ActivityIndicator | None = None,
) -> tuple[Callable[[str], None], Callable[[str], None]]:
    """Stream model reply (bold) and reasoning (dim italic), matching ``opentorus run``."""
    state = {"emitted": False}

    def on_text(chunk: str) -> None:
        if not chunk:
            return
        if indicator is not None:
            indicator.pause()
        state["emitted"] = True
        console.print(chunk, end="", markup=False, highlight=False, style="bold")

    def on_thinking(chunk: str) -> None:
        if not chunk.strip():
            return
        if indicator is not None:
            indicator.pause()
        state["emitted"] = True
        console.print(chunk, end="", markup=False, highlight=False, style="dim italic")

    return on_text, on_thinking


@dataclass(frozen=True)
class LlmCliHooks:
    """LLM feedback hooks for CLI commands (spinner vs ``--verbose`` trace)."""

    indicator: ActivityIndicator | None
    on_llm_request: Callable[[list[Any], list[dict] | None], None] | None
    on_llm_response: Callable[[Any], None] | None
    on_llm_text: Callable[[str], None] | None
    on_thinking: Callable[[str], None] | None
    stream_llm: bool
    trace: LlmTraceSession | None = None


def configure_llm_cli_hooks(
    console: Any,
    *,
    verbose: bool,
    debug: bool,
    spinner: bool = True,
    user_on_text: Callable[[str], None] | None = None,
    indicator: ActivityIndicator | None = None,
) -> LlmCliHooks:
    """Standard LLM CLI feedback across OpenTorus commands.

    Default (interactive terminal): activity spinner only — no streamed model text
    or chain-of-thought. Pass ``--verbose`` or ``--debug`` for the incremental LLM
    trace and live streaming (same behavior as ``opentorus run --verbose``).
    """
    import sys

    if indicator is None and spinner and sys.stdout.isatty():
        indicator = ActivityIndicator(console)

    if verbose or debug:
        on_request, on_response, on_text, stream_flag, on_thinking, trace = make_llm_trace(
            console,
            verbose=verbose,
            debug=debug,
            user_on_text=user_on_text,
            indicator=indicator,
        )
        return LlmCliHooks(
            indicator=indicator,
            on_llm_request=on_request,
            on_llm_response=on_response,
            on_llm_text=on_text,
            on_thinking=on_thinking,
            stream_llm=stream_flag,
            trace=trace,
        )

    return LlmCliHooks(
        indicator=indicator,
        on_llm_request=None,
        on_llm_response=None,
        on_llm_text=None,
        on_thinking=None,
        stream_llm=False,
        trace=None,
    )


def _short(text: str, limit: int = 400) -> str:
    text = (text or "").strip()
    if not text:
        return "(no stderr output)"
    return text if len(text) <= limit else text[:limit] + "\n... (truncated)"


def likely_cause(exit_code: int, stderr: str, timed_out: bool) -> tuple[str, str]:
    """Return (likely_cause, suggested_next_action) for a failed command."""
    if timed_out or exit_code == 124:
        return (
            "The command did not finish in time.",
            "Increase the timeout (--timeout) or check whether it is waiting on input.",
        )
    if exit_code == 127:
        return (
            "The program was not found on PATH.",
            "Check the spelling, install the tool, or activate the right environment.",
        )
    if exit_code == 126:
        return (
            "The target is not executable or permission was denied.",
            "Check file permissions (chmod +x) or run it with the correct interpreter.",
        )
    lowered = (stderr or "").lower()
    if "no such file or directory" in lowered:
        return (
            "A referenced file or directory does not exist.",
            "Verify the path; use `opentorus status` or `ls` to confirm it exists.",
        )
    if "permission denied" in lowered:
        return (
            "The process lacks permission for a file or resource.",
            "Check ownership/permissions, or whether the path is protected.",
        )
    return (
        "The command exited with a non-zero status.",
        "Read the stderr above; fix the underlying issue and re-run.",
    )


def format_command_error(
    command: str,
    exit_code: int,
    stderr: str,
    timed_out: bool = False,
) -> str:
    """Build a structured, actionable error message for a failed command."""
    cause, action = likely_cause(exit_code, stderr, timed_out)
    return (
        f"Command failed: {command}\n"
        f"  Exit code: {exit_code}{' (timed out)' if timed_out else ''}\n"
        f"  Stderr: {_short(stderr)}\n"
        f"  Likely cause: {cause}\n"
        f"  Next action: {action}"
    )


def provider_error_cause(message: str) -> tuple[str, str]:
    """Map a provider/LLM error message to (likely_cause, suggested_next_action)."""
    lowered = message.lower()
    if "api_key" in lowered or "api key" in lowered or "openai_api_key" in lowered:
        return (
            "The provider API key is not set or was rejected.",
            "Export the key (e.g. OPENAI_API_KEY / ANTHROPIC_API_KEY), or switch to a "
            "local model: `opentorus config set model.provider ollama` (or `mock`).",
        )
    if "could not reach" in lowered or "connection" in lowered or "refused" in lowered:
        return (
            "The model server is unreachable.",
            "Start it (e.g. `ollama serve`) or fix model.base_url with "
            "`opentorus config set model.base_url http://localhost:11434`.",
        )
    if "rate limit" in lowered or "429" in lowered or "quota" in lowered:
        return (
            "The provider is rate-limiting or out of quota.",
            "Wait and retry, lower request volume, or switch providers/models.",
        )
    if "does not support tools" in lowered or "tool" in lowered and "support" in lowered:
        return (
            "The selected model cannot use tools.",
            "Choose a tool-capable model with `opentorus config set model.name <model>`.",
        )
    if "not found" in lowered or "no such model" in lowered or "404" in lowered:
        return (
            "The requested model was not found.",
            "Check model.name, or pull/install the model for your provider.",
        )
    return (
        "The model provider returned an error.",
        "Read the message above; check provider, model.name, and credentials.",
    )


def format_provider_error(message: str) -> str:
    """Build a structured, actionable message for a provider/LLM failure."""
    cause, action = provider_error_cause(message)
    return f"Provider error: {message}\n  Likely cause: {cause}\n  Next action: {action}"


def format_interrupt_message(what: str, resume_cmd: str | None = None) -> str:
    """A calm, structured message for a user Ctrl-C, instead of a traceback.

    Reassures that artifacts written so far are persisted and, when applicable,
    tells the user exactly how to resume.
    """
    msg = f"Interrupted: {what}. Work recorded so far is saved under .opentorus/."
    if resume_cmd:
        msg += f"\n  Resume with: {resume_cmd}"
    return msg
