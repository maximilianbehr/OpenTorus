"""Workspace scaffolding and status gathering.

``init_workspace`` creates the ``.opentorus/`` project-memory tree idempotently:
existing files are never overwritten, so re-running ``opentorus init`` is safe.
``gather_status`` collects a read-only snapshot used by ``opentorus status`` and
the interactive ``/status`` command.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from pydantic import BaseModel

from opentorus.config import (
    CONFIG_FILENAME,
    Config,
    default_config,
    load_config,
    write_default_config,
)
from opentorus.paths import WORKSPACE_DIRNAME, find_workspace_root

PERMISSIONS_FILENAME = "permissions.yaml"

# Top-level JSONL ledgers created empty.
_ROOT_JSONL_FILES = ["session.jsonl", "actions.jsonl", "graph.jsonl", "evidence.jsonl"]
# Structured memory ledgers.
_MEMORY_JSONL_FILES = [
    "facts.jsonl",
    "claims.jsonl",
    "hypotheses.jsonl",
    "observations.jsonl",
    "failed_attempts.jsonl",
    "decisions.jsonl",
]
# Artifact directories (kept with .gitkeep while empty).
_ARTIFACT_DIRS = [
    "experiments",
    "papers",
    "problems",
    "summaries",
    "tasks",
    "patches",
    "checkpoints",
    "replay",
]

_DEFAULT_PERMISSIONS_YAML = """\
# OpenTorus permission policy.
# mode: safe | ask | trusted
mode: ask

# Commands the agent may run without asking in this session (filled at runtime).
always_allow: []

# Commands that are always blocked regardless of mode (see permissions/policy.py).
blocked_patterns_note: "Dangerous commands are blocked in code by default."
"""


class WorkspaceStatus(BaseModel):
    cwd: str
    workspace_root: str | None
    initialized: bool
    git_branch: str | None
    git_dirty: bool | None
    project_mode: str | None
    operating_style: str | None
    permission_mode: str | None
    num_claims: int
    num_experiments: int
    num_actions: int
    num_evidence: int


def workspace_dir(root: Path) -> Path:
    return root / WORKSPACE_DIRNAME


def _touch_empty(path: Path) -> bool:
    """Create an empty file if missing. Returns True if created."""
    if path.exists():
        return False
    path.touch()
    return True


def init_workspace(root: Path) -> list[Path]:
    """Create the ``.opentorus/`` tree under ``root`` idempotently.

    Returns the list of paths that were newly created (empty on a no-op rerun).
    """
    root = root.resolve()
    base = workspace_dir(root)
    created: list[Path] = []

    if not base.exists():
        base.mkdir(parents=True)
        created.append(base)

    # config.yaml with defaults (never clobber an existing config).
    config_path = base / CONFIG_FILENAME
    if not config_path.exists():
        write_default_config(config_path)
        created.append(config_path)

    # permissions.yaml
    perms_path = base / PERMISSIONS_FILENAME
    if not perms_path.exists():
        perms_path.write_text(_DEFAULT_PERMISSIONS_YAML, encoding="utf-8")
        created.append(perms_path)

    for name in _ROOT_JSONL_FILES:
        if _touch_empty(base / name):
            created.append(base / name)

    memory_dir = base / "memory"
    if not memory_dir.exists():
        memory_dir.mkdir()
        created.append(memory_dir)
    for name in _MEMORY_JSONL_FILES:
        if _touch_empty(memory_dir / name):
            created.append(memory_dir / name)

    for dirname in _ARTIFACT_DIRS:
        d = base / dirname
        if not d.exists():
            d.mkdir()
            created.append(d)
        keep = d / ".gitkeep"
        if _touch_empty(keep):
            created.append(keep)

    # User-visible paper drop folder (PDFs land in papers/inbox/, ingested into
    # .opentorus/papers/PAPER-* via ``opentorus paper ingest`` or paper_ingest_inbox).
    for rel in ("papers/inbox", "papers/inbox/processed"):
        visible = root / rel
        if not visible.exists():
            visible.mkdir(parents=True)
            created.append(visible)
        if _touch_empty(visible / ".gitkeep"):
            created.append(visible / ".gitkeep")

    return created


def _count_lines(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open("r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _count_subdirs(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(1 for child in path.iterdir() if child.is_dir())


def _git_info(root: Path) -> tuple[str | None, bool | None]:
    """Return (branch, dirty) best-effort; (None, None) if not a git repo."""
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if branch.returncode != 0:
            return None, None
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=5,
        )
        dirty = bool(status.stdout.strip()) if status.returncode == 0 else None
        return branch.stdout.strip() or None, dirty
    except (OSError, subprocess.SubprocessError):
        return None, None


def gather_status(start: Path | None = None) -> WorkspaceStatus:
    """Collect a read-only snapshot of the workspace state."""
    cwd = (start or Path.cwd()).resolve()
    root = find_workspace_root(cwd)
    git_branch, git_dirty = _git_info(root or cwd)

    if root is None:
        return WorkspaceStatus(
            cwd=str(cwd),
            workspace_root=None,
            initialized=False,
            git_branch=git_branch,
            git_dirty=git_dirty,
            project_mode=None,
            operating_style=None,
            permission_mode=None,
            num_claims=0,
            num_experiments=0,
            num_actions=0,
            num_evidence=0,
        )

    base = workspace_dir(root)
    config_path = base / CONFIG_FILENAME
    config: Config = load_config(config_path) if config_path.is_file() else default_config()

    return WorkspaceStatus(
        cwd=str(cwd),
        workspace_root=str(root),
        initialized=True,
        git_branch=git_branch,
        git_dirty=git_dirty,
        project_mode=config.project.mode,
        operating_style=config.agent.style,
        permission_mode=config.permissions.mode,
        num_claims=_count_lines(base / "memory" / "claims.jsonl"),
        num_experiments=_count_subdirs(base / "experiments"),
        num_actions=_count_lines(base / "actions.jsonl"),
        num_evidence=_count_lines(base / "evidence.jsonl"),
    )
