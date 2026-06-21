"""Atomic file writes for the artifact store.

A crash, full disk, or Ctrl-C during a plain ``write_text`` (or a truncate-then-
write ``rewrite``) can leave a half-written, corrupt file — and the JSONL reader
silently drops the corrupted tail, discarding records with no error. Routing the
store's whole-file writes through :func:`atomic_write_text` makes them durable:
write to a temp file in the same directory, fsync, then ``os.replace`` — an atomic
rename that either fully succeeds or leaves the prior file intact.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: Path, data: str, *, encoding: str = "utf-8") -> None:
    """Write ``data`` to ``path`` atomically (temp file + fsync + rename)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding=encoding) as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        # Never leave the temp file behind on failure; the original is untouched.
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
