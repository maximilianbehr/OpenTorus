"""Minimal ``.env`` loader for provider credentials.

Providers read their API keys from ``os.environ`` (the OpenAI/Anthropic SDKs do),
so a ``.env`` file sitting in the project is invisible unless its values are
exported. This loads ``KEY=VALUE`` pairs from a project ``.env`` into the
environment at CLI startup — the convenience users expect — without adding a
dependency.

It follows the usual ``.env`` conventions: ``#`` comments and blank lines are
skipped, an optional ``export`` prefix is accepted, surrounding quotes are
stripped, and — importantly — an already-set environment variable is never
overridden (an explicit ``export`` on the shell still wins). Parsing only ever
reads ``KEY=VALUE`` text; nothing is executed.

This does not weaken the sensitive-file guard: the *agent* still cannot read
``.env`` through the file tools, and the egress/DLP guards still screen anything
sent to a provider. This only lets the local process authenticate.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.match(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        elif " #" in value:
            # Strip an inline comment for unquoted values (API keys contain no spaces).
            value = value.split(" #", 1)[0].rstrip()
        out[key] = value
    return out


def load_dotenv_file(path: Path, *, override: bool = False) -> list[str]:
    """Load one ``.env`` file into ``os.environ``; return the variable names set."""
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    loaded: list[str] = []
    for key, value in _parse_env(text).items():
        if override or key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded


def load_project_dotenv(cwd: Path | None = None) -> list[str]:
    """Load ``.env`` from the working directory and the workspace root (deduplicated)."""
    from opentorus.paths import find_workspace_root

    cwd = (cwd or Path.cwd()).resolve()
    candidates: list[Path] = [cwd / ".env"]
    root = find_workspace_root(cwd)
    if root is not None:
        env_at_root = root.resolve() / ".env"
        if env_at_root not in candidates:
            candidates.append(env_at_root)
    loaded: list[str] = []
    for path in candidates:
        loaded.extend(load_dotenv_file(path))
    return loaded
