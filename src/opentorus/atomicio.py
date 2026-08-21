"""Atomic file writes for the artifact store.

A crash, full disk, or Ctrl-C during a plain ``write_text`` (or a truncate-then-
write ``rewrite``) can leave a half-written, corrupt file — and the JSONL reader
silently drops the corrupted tail, discarding records with no error. Routing the
store's whole-file writes through :func:`atomic_write_text` makes them durable:
write to a temp file in the same directory, fsync, then ``os.replace`` — an atomic
rename that either fully succeeds or leaves the prior file intact.

Atomicity of a single write is not enough for a *mutable* ledger, though. Those are
updated read-modify-write — read every record, add or change one, replace the file
— and two processes doing that concurrently both succeed while one of them silently
loses its record, because the second rename overwrites the first writer's file.
Worse, each derives the next artifact id from what it just read, so both mint the
same id. Measured: four processes appending fifteen claims each to one workspace
reported sixty successes and left sixteen records behind, with ids handed out four
times over. :func:`file_lock` closes that window — hold it across the read *and*
the write, not just the write.
"""

from __future__ import annotations

import errno
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from opentorus.errors import OpenTorusError

_LOCK_POLL_SECONDS = 0.02
_LOCK_TIMEOUT_SECONDS = 15.0
# A holder that died leaves its lock file behind. Reclaim one that is older than any
# plausible read-modify-write rather than blocking every later run forever.
_LOCK_STALE_SECONDS = 120.0


@contextmanager
def file_lock(
    path: Path,
    *,
    timeout: float = _LOCK_TIMEOUT_SECONDS,
    stale_after: float = _LOCK_STALE_SECONDS,
) -> Iterator[None]:
    """Serialize a read-modify-write of ``path`` across processes.

    Uses an ``O_EXCL`` sibling lock file rather than ``fcntl``: the same code then
    works on Windows, and the lock is visible in a directory listing when something
    goes wrong. A lock file older than ``stale_after`` is assumed to belong to a
    process that died and is reclaimed, so a crash cannot wedge the workspace.

    Raises :class:`OpenTorusError` on timeout — a caller that cannot take the lock
    must not fall through and write anyway, which is the very behaviour this exists
    to prevent.
    """
    lock = path.with_name(path.name + ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + timeout
    while True:
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        except FileExistsError:
            try:
                age = time.time() - lock.stat().st_mtime
            except OSError:
                continue  # released between the failed open and the stat
            if age > stale_after:
                try:
                    lock.unlink()
                except OSError:
                    pass
                continue
            if time.monotonic() >= deadline:
                raise OpenTorusError(
                    f"Timed out after {timeout:g}s waiting for the lock on {path.name}. "
                    f"Another OpenTorus process is writing this workspace; if none is, "
                    f"remove {lock}."
                ) from None
            time.sleep(_LOCK_POLL_SECONDS)
            continue
        except OSError as exc:  # pragma: no cover - filesystem without O_EXCL support
            if exc.errno in (errno.EACCES, errno.EPERM):
                raise OpenTorusError(f"Cannot create a lock file next to {path}: {exc}") from exc
            raise
        try:
            os.write(fd, f"{os.getpid()}\n".encode())
        finally:
            os.close(fd)
        break
    try:
        yield
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


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
