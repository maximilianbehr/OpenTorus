"""Built-in tools wired into a default registry.

These wrap existing workspace/filesystem/git helpers as :class:`Tool` instances
bound to a workspace so the agent loop can route calls through the registry.
Read tools enforce their own sensitive-file guard; write and command tools
declare a ``permission`` kind so the agent loop gates them through the permission
policy (mode, operating style, and review mode) before they run.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.tools._examples import ex
from opentorus.tools.base import Tool, ToolCall, ToolResult
from opentorus.tools.registry import ToolRegistry


class StatusTool(Tool):
    name = "status"
    description = (
        "Workspace git/project status and research artifact summary (papers, dossiers, tasks). "
        "Prefer over list_files on .opentorus/." + ex()
    )
    input_schema: dict = {"type": "object", "properties": {}}
    risk_level = "low"

    def __init__(self, root: Path, ot_dir: Path) -> None:
        self._root = root
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.agent.inventory import format_artifact_inventory, gather_artifact_inventory
        from opentorus.workspace import gather_status

        snap = gather_status(self._root)
        parts = [
            f"workspace_root={snap.workspace_root} initialized={snap.initialized}",
            f"git_branch={snap.git_branch} project_mode={snap.project_mode}",
            f"style={snap.operating_style} permission={snap.permission_mode}",
            f"actions={snap.num_actions} evidence={snap.num_evidence}",
        ]
        if snap.initialized:
            inventory = gather_artifact_inventory(self._root, self._ot_dir)
            parts.append(format_artifact_inventory(inventory, for_agent=False))
        return self.ok(call, "\n".join(parts))


class GitDiffTool(Tool):
    name = "git_diff"
    description = "Show the git diff of the working tree."
    input_schema: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional workspace-relative path to diff."}
        },
    }
    risk_level = "low"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.tools.git import git_diff

        result = git_diff(self._root, call.args.get("path"))
        return self.ok(call, result.output, is_repo=result.is_repo)


class MemoryListTool(Tool):
    name = "memory_list"
    description = "List project memory entries of one kind." + ex(kind="observations")
    input_schema: dict = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "description": "Memory kind, e.g. facts, decisions, hypotheses.",
            }
        },
    }
    risk_level = "low"

    def __init__(self, ot_dir: Path) -> None:
        self._ot_dir = ot_dir

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.memory import VALID_KINDS, list_memory

        kind = call.args.get("kind", "facts")
        if kind not in VALID_KINDS:
            return self.fail(call, f"Unknown memory kind '{kind}'.")
        entries = list_memory(self._ot_dir, kind)
        if not entries:
            return self.ok(call, f"No memory entries of kind '{kind}'.")
        return self.ok(call, "\n".join(f"{e.id}: {e.text}" for e in entries))


class ListFilesTool(Tool):
    name = "list_files"
    description = (
        "List immediate children of a workspace directory. Hides cache dirs "
        "(.mypy_cache, …), .opentorus/, and scaffold files (.gitkeep, .DS_Store). "
        "Use glob_files to find source files or status for research artifacts."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative directory (default '.')."}
        },
    }
    risk_level = "low"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.tools.filesystem import list_files

        try:
            names = list_files(self._root, call.args.get("path", "."))
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(call, "\n".join(names))


class ReadFileTool(Tool):
    name = "read_file"
    description = (
        "Read a workspace text file. For dossier problems use "
        ".opentorus/problems/PROBLEM-0001/statement.md; for papers use paper_read."
        + ex(path=".opentorus/problems/PROBLEM-0001/statement.md")
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Workspace-relative file path.",
            },
            "start": {"type": "integer", "description": "Optional 1-based start line."},
            "end": {"type": "integer", "description": "Optional 1-based end line."},
        },
        "required": ["path"],
    }
    risk_level = "low"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.tools.filesystem import read_file

        path = call.args.get("path")
        if not path:
            return self.fail(call, "read_file requires a 'path' argument.")
        try:
            content = read_file(self._root, path, call.args.get("start"), call.args.get("end"))
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(call, content)


class GlobFilesTool(Tool):
    name = "glob_files"
    description = "Find project files by glob (skips .opentorus/ and caches)." + ex(
        pattern="**/*.py"
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Glob pattern relative to path, e.g. '**/*.py'.",
            },
            "path": {
                "type": "string",
                "description": "Directory to search from (default '.').",
            },
        },
        "required": ["pattern"],
    }
    risk_level = "low"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.tools.filesystem import glob_files

        pattern = str(call.args.get("pattern", "")).strip()
        if not pattern:
            return self.fail(call, "glob_files requires a 'pattern' argument.")
        try:
            matches = glob_files(self._root, pattern, call.args.get("path", "."))
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        if not matches:
            return self.ok(call, f"No files matched pattern '{pattern}'.")
        return self.ok(call, "\n".join(matches), count=len(matches))


class WriteFileTool(Tool):
    name = "write_file"
    description = (
        "Create or overwrite a workspace file with new content. "
        "Prefer this over embedding code in run_shell."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "The full new file content."},
        },
        "required": ["path", "content"],
    }
    risk_level = "medium"
    permission = "write"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.tools.filesystem import patch_preview, write_file

        path = call.args.get("path")
        content = call.args.get("content")
        if not path or content is None:
            return self.fail(call, "write_file requires 'path' and 'content' arguments.")
        try:
            target = self._root / path
            old = target.read_text(encoding="utf-8") if target.is_file() else ""
            write_file(self._root, path, content)
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        except OSError as exc:
            return self.fail(call, f"Could not write '{path}': {exc}")
        preview = patch_preview(old, content, path) or f"(wrote {len(content)} chars to {path})"
        return self.ok(call, preview)


class ApplyPatchTool(Tool):
    name = "apply_patch"
    description = "Replace an exact, unique snippet of text in a workspace file."
    input_schema: dict = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "old": {"type": "string", "description": "Exact text to replace (must be unique)."},
            "new": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old", "new"],
    }
    risk_level = "medium"
    permission = "write"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.errors import OpenTorusError
        from opentorus.tools.filesystem import apply_patch

        path = call.args.get("path")
        old = call.args.get("old")
        new = call.args.get("new")
        if not path or old is None or new is None:
            return self.fail(call, "apply_patch requires 'path', 'old', and 'new' arguments.")
        try:
            preview = apply_patch(self._root, path, old, new)
        except OpenTorusError as exc:
            return self.fail(call, str(exc))
        return self.ok(call, preview)


class RunShellTool(Tool):
    name = "run_shell"
    description = (
        "Run a short command in the workspace and return its output. "
        "No real shell: pipes (|), redirects (>), and && are not supported. "
        "Never install packages here (pip/conda/apt install is blocked). "
        "For numpy/scipy use exp_new(environment='python-sci') + exp_run "
        "(run 'opentorus env prepare python-sci --file docker/Dockerfile' first). "
        "Use write_file for scripts, then run_shell with one simple argv "
        "(e.g. bash path/run.sh)."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": (
                    "Single-line shell command (e.g. python experiments/run.py). "
                    "Do not embed multi-line scripts."
                ),
            },
        },
        "required": ["command"],
    }
    risk_level = "high"
    permission = "command"

    def __init__(self, root: Path) -> None:
        self._root = root

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.tools.shell import run_shell

        command = call.args.get("command")
        if not command:
            return self.fail(call, "run_shell requires a 'command' argument.")
        result = run_shell(command, cwd=self._root)
        body = f"exit_code={result.exit_code}\n"
        if result.stdout.strip():
            body += f"stdout:\n{result.stdout.rstrip()}\n"
        if result.stderr.strip():
            body += f"stderr:\n{result.stderr.rstrip()}\n"
        body = body.rstrip()
        if result.exit_code == 0:
            return self.ok(call, body, exit_code=result.exit_code)
        return self.fail(call, body, exit_code=result.exit_code)


class LiteratureSearchTool(Tool):
    name = "lit_search"
    description = (
        "Search scholarly databases (OpenAlex, arXiv, …). Then paper_fetch using the "
        "exact DOI or arXiv id from a hit — copy it verbatim, do not alter digits."
        + ex(query="matrix sign function polynomial approximation", limit=10)
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keywords from the problem statement or hypothesis.",
            },
            "limit": {"type": "integer", "description": "Max results per source (default 5)."},
            "field": {
                "type": "string",
                "description": (
                    "Field hint to pick relevant sources (math, cs, physics, bio, …); "
                    "defaults to math. Avoids querying off-domain databases."
                ),
            },
        },
        "required": ["query"],
    }
    risk_level = "medium"
    permission = "external"

    def __init__(self, config, ot_dir=None) -> None:  # noqa: ANN001
        self._config = config
        self._ot_dir = ot_dir

    def _egress_guard(self):  # noqa: ANN202
        # Mirror PaperFetchTool: host authorization + per-host rate limit + the daily
        # request-budget ledger. Without ot_dir (e.g. a bare unit test) skip the guard.
        if self._ot_dir is None:
            return None
        from opentorus.research.egress import EgressGuard

        lit = self._config.tools.literature
        return EgressGuard(
            self._config.permissions.mode,
            style=self._config.agent.style,
            review=self._config.agent.mode == "review",
            rate_limit_per_minute=lit.rate_limit_per_minute,
            daily_request_budget=lit.daily_request_budget,
            ledger_path=self._ot_dir / "egress.json",
            dlp=self._config.governance.dlp,
        )

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.egress import EgressBlocked
        from opentorus.research.sources import search_all, sources_for_field

        query = str(call.args.get("query", "")).strip()
        if not query:
            return self.fail(call, "lit_search requires a non-empty 'query'.")
        limit = int(call.args.get("limit", 5))
        # Default to the math field so a math problem does not query bio/CS/astro DBs.
        field = str(call.args.get("field", "") or "math").strip()
        source_names = [s.name for s in sources_for_field(self._config, field)]
        try:
            records = search_all(
                self._config,
                query,
                limit=limit,
                sources=source_names or None,
                egress=self._egress_guard(),
            )
        except EgressBlocked as exc:
            return self.fail(call, f"Network egress denied: {exc}")
        if not records:
            return self.ok(call, "No results (or no literature sources enabled).")
        lines = []
        for r in records:
            fetch_id = r.doi or r.arxiv_id
            oa = "OA" if r.is_open_access else "closed"
            year = r.year or "n.d."
            if fetch_id:
                lines.append(
                    f"[{r.source}] {r.title} ({year}) — {oa} — "
                    f'fetch="{fetch_id}" (paper_fetch identifier, copy exactly)'
                )
            else:
                ident = r.url or "(no fetch id)"
                lines.append(f"[{r.source}] {r.title} ({year}) — {oa} — {ident}")
        return self.ok(call, "\n".join(lines), count=len(records))


class FetchUrlTool(Tool):
    name = "fetch_url"
    description = (
        "Fetch an http(s) URL (e.g. a Wikipedia page) and return its readable text. "
        "Use this to read a page the user links to."
    )
    input_schema: dict = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The http(s) URL to fetch."},
        },
        "required": ["url"],
    }
    risk_level = "medium"
    permission = "external"

    def __init__(self, max_chars: int = 8000) -> None:
        self._max_chars = max_chars

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.sources.base import SourceError
        from opentorus.tools.web import fetch_url

        url = str(call.args.get("url", "")).strip()
        if not url:
            return self.fail(call, "fetch_url requires a 'url' argument.")
        try:
            title, text, truncated = fetch_url(url, max_chars=self._max_chars)
        except SourceError as exc:
            return self.fail(call, str(exc))
        header = f"# {title}\n({url})\n\n" if title else f"({url})\n\n"
        return self.ok(call, header + text, truncated=truncated, url=url)


class WebSearchTool(Tool):
    name = "web_search"
    description = "Search the web by keyword." + ex(query="Crouzeix conjecture status", limit=5)
    input_schema: dict = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query (keywords)."},
            "limit": {"type": "integer", "description": "Max results (default 5)."},
        },
        "required": ["query"],
    }
    risk_level = "medium"
    permission = "external"

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.research.sources.base import SourceError
        from opentorus.tools.web import web_search

        query = str(call.args.get("query", "")).strip()
        if not query:
            return self.fail(call, "web_search requires a non-empty 'query'.")
        limit = int(call.args.get("limit", 5))
        try:
            results = web_search(query, limit=limit)
        except SourceError as exc:
            return self.fail(call, str(exc))
        if not results:
            return self.ok(call, "No web results found.")
        lines = [f"{i}. {title}\n   {url}" for i, (title, url) in enumerate(results, start=1)]
        return self.ok(call, "\n".join(lines), count=len(results))


def build_default_registry(root: Path, ot_dir: Path, config=None) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(StatusTool(root, ot_dir))
    registry.register(GitDiffTool(root))
    registry.register(MemoryListTool(ot_dir))
    registry.register(ListFilesTool(root))
    registry.register(GlobFilesTool(root))
    registry.register(ReadFileTool(root))
    registry.register(WriteFileTool(root))
    registry.register(ApplyPatchTool(root))
    registry.register(RunShellTool(root))
    if config is not None and config.tools.literature.enabled:
        registry.register(LiteratureSearchTool(config, ot_dir))
    if config is not None and config.tools.web.enabled:
        web = config.tools.web
        if web.fetch:
            registry.register(FetchUrlTool(max_chars=web.max_chars))
        if web.search:
            registry.register(WebSearchTool())
    if config is not None and config.tools.mcp:
        from opentorus.tools.mcp import register_mcp_tools

        register_mcp_tools(registry, config)
    if config is not None:
        from opentorus.tools.research import register_research_tools

        register_research_tools(registry, root, ot_dir, config)
    return registry
