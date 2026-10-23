"""Confinement for proof checkers: run Lean/Coq under ``bwrap`` without network.

Model-written proof source is code. The textual gate (``lean_rules`` / ``coq_rules``)
refuses every construct known to run code while the file elaborates, but a checker
bug or a construct the gate does not know about would still run on the host with the
user's privileges. When `bubblewrap <https://github.com/containers/bubblewrap>`_ is
installed the checker therefore runs in a fresh network/PID/IPC namespace with the
whole filesystem bound read-only, only the per-check temporary directory writable,
and credential directories (``~/.ssh``, ``~/.gnupg``, ``~/.aws``) hidden.

``tools.verifiers.confine``:

* ``auto`` (default) — confine when a working ``bwrap`` exists, else run unconfined
  (the result records ``confined=False``);
* ``require`` — refuse to run the checker when ``bwrap`` is missing or broken
  (fail closed);
* ``off`` — never confine (e.g. a checker that is itself a container invocation).
"""

from __future__ import annotations

import functools
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Literal

ConfineMode = Literal["auto", "require", "off"]

_HIDDEN_HOME_DIRS = (".ssh", ".gnupg", ".aws", ".config/gcloud", ".netrc.d")


class ConfinementUnavailable(RuntimeError):
    """``confine: require`` but no working ``bwrap`` is available."""


@functools.lru_cache(maxsize=4)
def _probe(bwrap: str) -> bool:
    """Whether ``bwrap`` actually works here (user namespaces may be disabled)."""
    try:
        done = subprocess.run(
            [bwrap, "--ro-bind", "/", "/", "--unshare-net", "--die-with-parent", "true"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def bwrap_binary() -> str | None:
    """Path of a *working* ``bwrap``, or ``None``."""
    path = shutil.which("bwrap")
    if path is None:
        return None
    return path if _probe(path) else None


def bwrap_argv(bwrap: str, writable: list[Path]) -> list[str]:
    """The ``bwrap`` prefix: read-only root, writable ``writable``, no network."""
    argv = [bwrap, "--ro-bind", "/", "/", "--dev", "/dev", "--proc", "/proc"]
    home = Path(os.path.expanduser("~"))
    for rel in _HIDDEN_HOME_DIRS:
        hidden = home / rel
        if hidden.is_dir():
            argv += ["--tmpfs", str(hidden)]
    for path in writable:
        argv += ["--bind", str(path), str(path)]
    argv += [
        "--unshare-net",
        "--unshare-pid",
        "--unshare-ipc",
        "--die-with-parent",
        "--new-session",
        "--",
    ]
    return argv


def confine_command(
    command: str, *, writable: list[Path], mode: ConfineMode = "auto"
) -> tuple[str, bool]:
    """``(command to run, confined?)`` for ``command`` under ``mode``.

    Raises :class:`ConfinementUnavailable` when ``mode`` is ``require`` and no
    working ``bwrap`` exists — the caller must refuse to run the checker.
    """
    if mode == "off" or os.name == "nt":
        if mode == "require":
            raise ConfinementUnavailable("bwrap confinement is not supported on this platform")
        return command, False
    bwrap = bwrap_binary()
    if bwrap is None:
        if mode == "require":
            raise ConfinementUnavailable(
                "tools.verifiers.confine is 'require' but no working bwrap (bubblewrap) "
                "is installed; the proof checker was NOT run. Install bubblewrap or set "
                "confine to 'auto'/'off'."
            )
        return command, False
    prefix = bwrap_argv(bwrap, writable)
    return shlex.join(prefix) + " " + command, True


__all__ = [
    "ConfineMode",
    "ConfinementUnavailable",
    "bwrap_argv",
    "bwrap_binary",
    "confine_command",
]
