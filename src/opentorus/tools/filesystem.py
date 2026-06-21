"""Path-safe filesystem helpers.

All paths are resolved through :func:`resolve_workspace_path`, so reads and writes
can never escape the workspace. Reads of sensitive files are refused unless the
caller explicitly opts in (the sensitive-file guard).
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path

from opentorus.errors import OpenTorusError, PermissionDeniedError
from opentorus.paths import WORKSPACE_DIRNAME, resolve_workspace_path
from opentorus.permissions.policy import is_sensitive_path

# Files that are never useful agent targets (OS / scaffold noise).
_IGNORE_FILE_NAMES = frozenset(
    {
        ".DS_Store",
        "Thumbs.db",
        "desktop.ini",
        ".gitkeep",
    }
)

# Directories hidden from listings and blocked for naive exploration.
_IGNORE_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".nox",
        ".hypothesis",
        WORKSPACE_DIRNAME,
    }
)

_GLOB_RESULT_LIMIT = 200

_TEXT_HINT_SUFFIXES = {
    ".pdf": " Use paper_fetch or `opentorus paper ingest` on the PAPER-* id instead.",
    ".png": " Image files are not readable as text.",
    ".jpg": " Image files are not readable as text.",
    ".jpeg": " Image files are not readable as text.",
    ".gif": " Image files are not readable as text.",
    ".zip": " Archive files are not readable as text.",
    ".gz": " Archive files are not readable as text.",
}


def _relative_parts(root: Path, target: Path) -> tuple[str, ...]:
    return target.resolve().relative_to(root.resolve()).parts


def _path_has_ignored_dir(parts: tuple[str, ...]) -> bool:
    return any(part in _IGNORE_DIR_NAMES for part in parts)


def _under_opentorus_problems(parts: tuple[str, ...]) -> bool:
    """True for `.opentorus/problems` and anything beneath a dossier."""
    return len(parts) >= 2 and parts[0] == WORKSPACE_DIRNAME and parts[1] == "problems"


def _under_opentorus_tasks(parts: tuple[str, ...]) -> bool:
    """True for `.opentorus/tasks` and task cards beneath it."""
    return len(parts) >= 2 and parts[0] == WORKSPACE_DIRNAME and parts[1] == "tasks"


def _under_opentorus_agent_readable(parts: tuple[str, ...]) -> bool:
    """OpenTorus subdirs the agent may read (dossiers, task cards)."""
    return _under_opentorus_problems(parts) or _under_opentorus_tasks(parts)


def _opentorus_dossier_path(parts: tuple[str, ...]) -> bool:
    return _under_opentorus_problems(parts) and len(parts) >= 3


def _path_skipped_for_glob(parts: tuple[str, ...]) -> bool:
    if _under_opentorus_agent_readable(parts):
        return False
    return _path_has_ignored_dir(parts)


def _read_allowed_under_opentorus(parts: tuple[str, ...]) -> bool:
    return _under_opentorus_agent_readable(parts)


def _listing_blocked_message(user_path: str, parts: tuple[str, ...]) -> str | None:
    if parts and parts[0] in _IGNORE_DIR_NAMES and parts[0] != WORKSPACE_DIRNAME:
        return (
            f"'{user_path}' is a cache or tooling directory, not project content. "
            "Use glob_files for source files or status for research artifacts."
        )
    if parts and parts[0] == WORKSPACE_DIRNAME and not _under_opentorus_agent_readable(parts):
        return (
            f"'{user_path}' is internal OpenTorus state. Use status, paper_list, "
            "memory_list, read_file on .opentorus/tasks/TASK-XXXX.md or "
            ".opentorus/problems/PROBLEM-XXXX/… instead."
        )
    return None


# Tool-managed dossier artifacts (the first path component under a PROBLEM-* dir).
# A raw write_file/apply_patch to any of these can clobber a proof/claim/experiment
# that the dossier tools own (observed: an agent overwriting its own PROOF-* file),
# so they are write-protected; free-form notes elsewhere in the dossier are allowed.
_DOSSIER_MANAGED_ARTIFACTS: frozenset[str] = frozenset(
    {
        "proof_attempts",
        "evidence",
        "experiments",
        "referee",
        "approaches",
        "counterexample_search",
        "algebra",
        "claims.jsonl",
        "report.md",
        "problem.yaml",
        "statement.md",
        "index.jsonl",
        "status_changelog.jsonl",
        "known_results.yaml",
        "assumptions.yaml",
        "definitions.yaml",
        "related_papers.jsonl",
        "theorem_refs.jsonl",
        "failed_attempts.jsonl",
        "citation_failures.txt",
    }
)


def _write_blocked_message(user_path: str, parts: tuple[str, ...]) -> str | None:
    """Refuse writes into internal OpenTorus state and tool-managed dossier artifacts.

    Non-agent-readable internal state (papers cache, memory, session logs) is always
    refused. Inside a dossier, the tool-managed artifacts (proof_attempts/,
    claims.jsonl, evidence/, experiment manifests, report.md, …) are also refused: a
    raw ``write_file``/``apply_patch`` would clobber a proof/claim the dossier tools
    own (observed: an agent overwriting its own PROOF-* file). Free-form notes in the
    dossier remain writable; project files belong outside ``.opentorus/``.
    """
    if parts and parts[0] == WORKSPACE_DIRNAME and not _under_opentorus_agent_readable(parts):
        return (
            f"Refusing to write '{user_path}' into internal OpenTorus state. Use the "
            "dedicated tools (claim_new, evidence_add, proof_write, exp_new, memory_add) "
            "for artifacts, or write project files outside .opentorus/."
        )
    if (
        _opentorus_dossier_path(parts)
        and len(parts) >= 4
        and parts[3] in _DOSSIER_MANAGED_ARTIFACTS
    ):
        return (
            f"Refusing to write '{user_path}': it is a tool-managed dossier artifact. "
            "Use proof_write / claim_new / evidence_add / exp_new / dossier_* tools — a "
            "raw write would corrupt the artifact index."
        )
    return None


def _read_blocked_message(user_path: str, parts: tuple[str, ...]) -> str | None:
    if parts and parts[-1] in _IGNORE_FILE_NAMES:
        return (
            f"'{user_path}' is workspace scaffolding, not project content "
            "(e.g. .gitkeep, .DS_Store). Use status, paper_list, or glob_files."
        )
    if _path_has_ignored_dir(parts):
        if parts[0] == WORKSPACE_DIRNAME and _read_allowed_under_opentorus(parts):
            return None
        hint = "Use status, paper_fetch, or a concrete project file path."
        if len(parts) >= 2 and parts[1] == "papers":
            # A cached paper PDF — read its parsed note, not the binary under .opentorus/.
            pid = parts[2] if len(parts) >= 3 and parts[2].startswith("PAPER-") else "PAPER-XXXX"
            hint = f'Use paper_read("{pid}") for the parsed reading note (not the PDF).'
        return f"Refusing to read '{user_path}' under a cache or internal directory. {hint}"
    return None


def _visible_entry(name: str, *, is_dir: bool) -> bool:
    if name in _IGNORE_FILE_NAMES:
        return False
    if is_dir and name in _IGNORE_DIR_NAMES:
        return False
    return True


def _read_utf8_text(target: Path, user_path: str) -> str:
    """Read a workspace file as UTF-8 text or raise a clear :class:`OpenTorusError`."""
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        suffix = target.suffix.lower()
        hint = _TEXT_HINT_SUFFIXES.get(suffix, "")
        if not hint and suffix:
            hint = " Use a format-specific tool if one exists for this file type."
        raise OpenTorusError(
            f"Cannot read '{user_path}' as UTF-8 text (binary or non-UTF-8 file).{hint}"
        ) from exc


def list_files(root: Path, user_path: str = ".") -> list[str]:
    """List entries directly under ``user_path``, hiding cache/scaffold noise."""
    target = resolve_workspace_path(root, user_path)
    if not target.exists():
        raise OpenTorusError(f"Path does not exist: {user_path}{_dossier_path_hint(root, target)}")
    parts = _relative_parts(root, target)
    blocked = _listing_blocked_message(user_path, parts)
    if blocked:
        raise OpenTorusError(blocked)
    if target.is_file():
        if not _visible_entry(target.name, is_dir=False):
            raise OpenTorusError(
                f"'{user_path}' is not project content. Use status or glob_files instead."
            )
        return [target.name]
    return sorted(
        child.name
        for child in target.iterdir()
        if _visible_entry(child.name, is_dir=child.is_dir())
    )


def glob_files(root: Path, pattern: str, user_path: str = ".") -> list[str]:
    """Glob project files under ``user_path``, skipping caches and internal dirs."""
    if not pattern.strip():
        raise OpenTorusError("glob_files requires a non-empty 'pattern'.")
    base = resolve_workspace_path(root, user_path)
    if not base.exists():
        raise OpenTorusError(f"Path does not exist: {user_path}{_dossier_path_hint(root, base)}")
    parts = _relative_parts(root, base)
    blocked = _listing_blocked_message(user_path, parts)
    if blocked:
        raise OpenTorusError(blocked)
    matches: list[str] = []
    for path in sorted(base.glob(pattern)):
        if not path.is_file():
            continue
        rel = path.resolve().relative_to(root.resolve())
        if _path_skipped_for_glob(rel.parts):
            continue
        if rel.name in _IGNORE_FILE_NAMES:
            continue
        matches.append(rel.as_posix())
        if len(matches) >= _GLOB_RESULT_LIMIT:
            break
    return matches


def _resolve_problem_path(root: Path, user_path: str, parts: tuple[str, ...]) -> str | None:
    """Recover from a wrong PROBLEM-* id under ``.opentorus/problems/``.

    Returns corrected file text (with a note) when the requested dossier id only
    differs by zero-padding, raises with the valid id list when it is unknown, or
    returns ``None`` to fall through to the normal "Not a file" error.
    """
    if not (_under_opentorus_problems(parts) and len(parts) >= 3):
        return None
    requested = parts[2]
    if not requested.upper().startswith("PROBLEM"):
        return None

    from opentorus.research.dossier import store

    ot_dir = root / WORKSPACE_DIRNAME
    existing = [d.id for d in store.list_dossiers(ot_dir)]
    if not existing:
        return None
    resolved = store.resolve_dossier_id(ot_dir, requested)
    if resolved is None:
        ids = ", ".join(existing)
        raise OpenTorusError(
            f"No dossier '{requested}'. Existing problem dossiers: {ids}. "
            f"Use an exact id, e.g. "
            f"read_file('.opentorus/problems/{existing[0]}/statement.md')."
        )
    if resolved == requested:
        return None  # dossier exists; the specific file is simply absent
    corrected = root / WORKSPACE_DIRNAME / "problems" / resolved / Path(*parts[3:])
    if not corrected.is_file():
        return None
    note = (
        f"(Note: '{requested}' is not a dossier id; resolved to {resolved}. "
        f"Use problem_id='{resolved}' in proof_write and future read_file calls.)\n\n"
    )
    return note + _read_utf8_text(corrected, user_path)


# Dossier-internal subdirectories an agent often references without the
# ``.opentorus/problems/PROBLEM-XXXX/`` prefix (e.g. ``proof_attempts/PROOF-0001.md``).
_DOSSIER_SUBDIRS: frozenset[str] = frozenset(
    {"proof_attempts", "evidence", "experiments", "approaches", "counterexample_search", "referee"}
)


def _active_or_single_dossier(root: Path) -> str | None:
    """The active problem, or the only dossier if there is exactly one; else None."""
    from opentorus.research.dossier import store

    ot_dir = root / WORKSPACE_DIRNAME
    active = store.get_active_problem(ot_dir)
    if active:
        return active
    dossiers = store.list_dossiers(ot_dir)
    return dossiers[0].id if len(dossiers) == 1 else None


def _bare_dossier_suggestion(root: Path, parts: tuple[str, ...]) -> str | None:
    """Corrected path when a dossier subdir is referenced without its prefix.

    ``proof_attempts/PROOF-0001.md`` → ``.opentorus/problems/PROBLEM-XXXX/proof_attempts/
    PROOF-0001.md`` for the active/only dossier — the agent dropped the prefix.
    """
    if not parts or parts[0] not in _DOSSIER_SUBDIRS:
        return None
    pid = _active_or_single_dossier(root)
    if pid is None:
        return None
    return "/".join((WORKSPACE_DIRNAME, "problems", pid, *parts))


def _dossier_path_hint(root: Path, target: Path) -> str:
    """A ' Did you mean …' suffix when a bare dossier path was used, else ''."""
    try:
        parts = target.resolve().relative_to(root.resolve()).parts
    except ValueError:
        return ""
    suggestion = _bare_dossier_suggestion(root, parts)
    if suggestion is None:
        return ""
    return (
        ". Dossier artifacts live under .opentorus/problems/PROBLEM-XXXX/ — "
        f"did you mean '{suggestion}'?"
    )


def read_file(
    root: Path,
    user_path: str,
    start: int | None = None,
    end: int | None = None,
    *,
    allow_sensitive: bool = False,
) -> str:
    """Read a file (optionally a 1-indexed inclusive line range)."""
    target = resolve_workspace_path(root, user_path)
    parts = _relative_parts(root, target)
    blocked = _read_blocked_message(user_path, parts)
    if blocked:
        raise OpenTorusError(blocked)
    if is_sensitive_path(target) and not allow_sensitive:
        raise PermissionDeniedError(
            f"Refusing to read potentially sensitive file '{user_path}' "
            "without explicit permission."
        )
    if not target.is_file():
        corrected = _resolve_problem_path(root, user_path, parts)
        if corrected is not None:
            return corrected
        # The agent referenced a dossier artifact without its prefix (e.g.
        # ``proof_attempts/PROOF-0001.md``). Resolve it under the active dossier.
        suggestion = _bare_dossier_suggestion(root, parts)
        if suggestion is not None:
            corrected_file = root / suggestion
            if corrected_file.is_file():
                note = (
                    f"(Note: '{user_path}' was missing its dossier prefix; resolved to "
                    f"{suggestion}. Use that full path next time.)\n\n"
                )
                return note + _read_utf8_text(corrected_file, user_path)
            raise OpenTorusError(
                f"Not a file: {user_path}. Dossier artifacts live under "
                f".opentorus/problems/PROBLEM-XXXX/ — did you mean '{suggestion}'?"
            )
        raise OpenTorusError(f"Not a file: {user_path}")
    text = _read_utf8_text(target, user_path)
    if start is None and end is None:
        return text
    lines = text.splitlines()
    lo = (start - 1) if start else 0
    hi = end if end else len(lines)
    return "\n".join(lines[lo:hi])


def write_file(root: Path, user_path: str, content: str) -> Path:
    """Write ``content`` to ``user_path`` (path-safety enforced)."""
    target = resolve_workspace_path(root, user_path)
    blocked = _write_blocked_message(user_path, _relative_parts(root, target))
    if blocked:
        raise OpenTorusError(blocked)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def grep(root: Path, pattern: str, user_path: str = ".") -> list[tuple[str, int, str]]:
    """Return (relative_path, line_number, line) matches for ``pattern``."""
    regex = re.compile(pattern)
    base = resolve_workspace_path(root, user_path)
    matches: list[tuple[str, int, str]] = []
    files = [base] if base.is_file() else _walk_files(base)
    for file in files:
        try:
            text = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                matches.append((str(file.relative_to(root)), lineno, line))
    return matches


def _walk_files(base: Path):
    for path in base.rglob("*"):
        if path.is_dir():
            continue
        if any(part in _IGNORE_DIR_NAMES for part in path.parts):
            continue
        if path.name in _IGNORE_FILE_NAMES:
            continue
        yield path


def patch_preview(old_content: str, new_content: str, path: str) -> str:
    """Return a unified diff between two file contents."""
    diff = difflib.unified_diff(
        old_content.splitlines(keepends=True),
        new_content.splitlines(keepends=True),
        fromfile=f"a/{path}",
        tofile=f"b/{path}",
    )
    return "".join(diff)


def apply_patch(root: Path, user_path: str, old: str, new: str) -> str:
    """Replace an exact ``old`` substring with ``new`` in a file.

    Returns the unified-diff preview of the change. Raises if ``old`` is absent or
    ambiguous (appears more than once).
    """
    target = resolve_workspace_path(root, user_path)
    blocked = _write_blocked_message(user_path, _relative_parts(root, target))
    if blocked:
        raise OpenTorusError(blocked)
    if not target.is_file():
        raise OpenTorusError(f"Not a file: {user_path}")
    original = _read_utf8_text(target, user_path)
    count = original.count(old)
    if count == 0:
        raise OpenTorusError(f"Patch target text not found in '{user_path}'.")
    if count > 1:
        raise OpenTorusError(
            f"Patch target text appears {count} times in '{user_path}'; refine it to be unique."
        )
    updated = original.replace(old, new, 1)
    preview = patch_preview(original, updated, user_path)
    target.write_text(updated, encoding="utf-8")
    return preview
