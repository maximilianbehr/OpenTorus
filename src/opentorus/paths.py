"""Workspace discovery and path-safety helpers.

Every file operation in OpenTorus must stay inside the workspace root. The
:func:`resolve_workspace_path` helper is the single choke point that enforces
this: it resolves a user-supplied path against the workspace root and refuses
anything that would escape it (``..`` traversal or absolute paths pointing
elsewhere).
"""

from __future__ import annotations

from pathlib import Path

from opentorus.errors import PathTraversalError

WORKSPACE_DIRNAME = ".opentorus"


def find_workspace_root(start: Path | None = None) -> Path | None:
    """Return the nearest ancestor directory containing ``.opentorus``.

    Walks upward from ``start`` (default: current working directory). Returns
    ``None`` if no initialized workspace is found.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        if (candidate / WORKSPACE_DIRNAME).is_dir():
            return candidate
    return None


def looks_like_uninitialized_project(path: Path) -> bool:
    """True when ``path`` has project folders but no ``.opentorus/`` yet."""
    if (path / WORKSPACE_DIRNAME).is_dir():
        return False
    return (path / "papers").is_dir()


def resolve_cli_workspace_root(start: Path | None = None) -> Path | None:
    """Resolve the workspace root for CLI commands run from ``start``.

    Unlike :func:`find_workspace_root`, this refuses to bind a subdirectory to a
    parent workspace when the current directory already looks like its own
    project (e.g. ``papers/`` without ``.opentorus/``), or when the only match
    would be the user's home directory while the command runs in a child folder.
    """
    cwd = (start or Path.cwd()).resolve()
    local = cwd / WORKSPACE_DIRNAME
    if local.is_dir():
        return cwd

    if looks_like_uninitialized_project(cwd):
        return None

    found = find_workspace_root(cwd)
    if found is None:
        return None

    home = Path.home().resolve()
    if found == home and cwd != home:
        return None

    return found if found != cwd else cwd


def _strip_component_whitespace(user_path: str) -> str:
    """Trim whitespace around each path component and drop the ones left empty.

    A path component that begins or ends with a space, or contains a newline, is not a
    filename anybody meant to write — it is the same output corruption that turns
    ``read_file`` into ``read_ file``. Left alone it succeeds silently and litters the
    project: a run wrote ``" \\nscripts/verify_6. py"`` and created a real directory
    named two-spaces-newline-scripts, outside ``.opentorus/`` so no re-run cleans it up,
    with the script unreachable from every sane path the model tried afterwards.

    Only the component boundaries are touched. A space *inside* a name is legitimate
    ("my notes.md") and is left exactly as written.
    """
    separator = "\\" if "\\" in user_path and "/" not in user_path else "/"
    parts = [part.strip() for part in user_path.split(separator)]
    # An empty first part is a leading separator (absolute path) and must survive.
    kept = [part for index, part in enumerate(parts) if part or index == 0]
    cleaned = separator.join(kept)
    return cleaned if cleaned.strip() else user_path


def resolve_workspace_path(workspace_root: Path | str, user_path: Path | str) -> Path:
    """Resolve ``user_path`` against ``workspace_root`` without allowing escape.

    Raises :class:`PathTraversalError` if the resolved path would fall outside
    the workspace root (via ``..`` traversal or an absolute path pointing
    elsewhere).
    """
    root = Path(workspace_root).resolve()
    candidate = Path(_strip_component_whitespace(str(user_path)))

    # Anchor relative paths to the workspace root; absolute paths are taken as-is
    # and validated below so that e.g. ``/etc/passwd`` is rejected.
    combined = candidate if candidate.is_absolute() else root / candidate
    resolved = combined.resolve()

    if resolved != root and root not in resolved.parents:
        raise PathTraversalError(
            f"Path '{user_path}' resolves outside the workspace root '{root}'."
        )
    return resolved
