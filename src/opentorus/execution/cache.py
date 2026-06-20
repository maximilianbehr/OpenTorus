"""Content-addressed result cache (Milestone 66).

A run is identified by the content that determines its output: the ``run.py``
source (which embeds the seed), the pinned image reference, the command, and any
declared inputs. Identical content ⇒ identical key ⇒ the recorded result and
manifest are reused (and the manifest says ``cache_hit: true``). Changing the
seed/source/image/command changes the key and forces a fresh run.

The cache lives under ``.opentorus/cache/<key>/`` and stores the result files
plus the manifest, so a hit is fully reproducible from the workspace.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

_MANIFEST = "manifest.yaml"


def cache_key(
    *,
    run_source: str,
    image_ref: str | None,
    command: str,
    inputs: dict | None = None,
) -> str:
    """Compute the content-addressed key for a run."""
    h = hashlib.sha256()
    h.update(run_source.encode("utf-8"))
    h.update(b"\x00")
    h.update((image_ref or "").encode("utf-8"))
    h.update(b"\x00")
    h.update(command.encode("utf-8"))
    if inputs:
        h.update(b"\x00")
        h.update(json.dumps(inputs, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def cache_root(ot_dir: Path) -> Path:
    return ot_dir / "cache"


def entry_dir(ot_dir: Path, key: str) -> Path:
    return cache_root(ot_dir) / key


def lookup(ot_dir: Path, key: str) -> Path | None:
    """Return the cache entry directory for ``key`` if it holds a manifest."""
    entry = entry_dir(ot_dir, key)
    return entry if (entry / _MANIFEST).is_file() else None


def store(ot_dir: Path, key: str, results_dir: Path) -> Path:
    """Copy a completed run's result files into the cache, keyed by content."""
    dest = entry_dir(ot_dir, key)
    dest.mkdir(parents=True, exist_ok=True)
    for item in sorted(results_dir.iterdir()):
        if item.is_file():
            shutil.copy2(item, dest / item.name)
    return dest


def restore(ot_dir: Path, key: str, results_dir: Path) -> bool:
    """Copy cached result files into ``results_dir``. Returns True on a hit."""
    entry = lookup(ot_dir, key)
    if entry is None:
        return False
    results_dir.mkdir(parents=True, exist_ok=True)
    for item in sorted(entry.iterdir()):
        if item.is_file():
            shutil.copy2(item, results_dir / item.name)
    return True
