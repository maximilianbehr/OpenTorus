"""Shareable, privacy-clean session bundles.

``export_session`` packages a session's messages plus the workspace's structured
artifacts and manifests into a single inspectable ``.zip``. Two privacy layers
apply so nothing secret leaves the machine:

* messages flagged ``sensitive`` are redacted (the M20 provider filter);
* any artifact file or patch whose path is sensitive (``is_sensitive_path``) is
  excluded from the bundle.

``import_bundle`` extracts a bundle into a read-only review directory; it never
merges into the live ledgers, so importing is always safe.
"""

from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, Field

import opentorus
from opentorus.agent.session import SessionMessage, read_messages
from opentorus.errors import OpenTorusError
from opentorus.permissions.policy import is_sensitive_path
from opentorus.privacy import redact_for_provider

# Top-level artifact ledgers safe to include verbatim.
_ARTIFACT_FILES = (
    "graph.jsonl",
    "evidence.jsonl",
    "proofs.jsonl",
    "usage/ledger.jsonl",
)
# Directories whose files are copied (skipping any sensitively-named file).
# ``memory`` holds claims.jsonl and structured memory ledgers; ``journal`` and
# ``research`` carry the autonomous-research journal and resumable state (M53/M54).
_ARTIFACT_DIRS = (
    "memory",
    "tasks",
    "experiments",
    "papers",
    "evals",
    "journal",
    "research",
    "proofs",
    "checkpoints",
    "reviews",
    "figures",
    "drafts",
    "datasets",
)


class BundleManifest(BaseModel):
    session_id: str
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    opentorus_version: str = opentorus.__version__
    message_count: int = 0
    redacted_messages: int = 0
    files: list[str] = Field(default_factory=list)


def _session_messages(ot_dir: Path, session_id: str) -> list[SessionMessage]:
    return [m for m in read_messages(ot_dir) if m.metadata.get("session_id") == session_id]


def _patches_privacy_clean(ot_dir: Path) -> bytes | None:
    """Return patches.jsonl with sensitive-path patches removed, or None if absent."""
    path = ot_dir / "patches.jsonl"
    if not path.is_file():
        return None
    kept: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        changes = record.get("changes", [])
        if any(is_sensitive_path(c.get("path", "")) for c in changes):
            continue
        kept.append(line)
    return ("\n".join(kept) + "\n").encode("utf-8") if kept else b""


def export_session(ot_dir: Path, session_id: str, out_path: Path | None = None) -> Path:
    """Bundle a session into a privacy-clean zip archive and return its path."""
    messages = _session_messages(ot_dir, session_id)
    if not messages:
        raise OpenTorusError(f"No messages found for session '{session_id}'.")

    redacted = redact_for_provider(messages, allow_sensitive=False)
    redacted_count = sum(
        1 for a, b in zip(messages, redacted, strict=False) if a.content != b.content
    )

    manifest = BundleManifest(
        session_id=session_id,
        message_count=len(messages),
        redacted_messages=redacted_count,
    )

    entries: list[tuple[str, bytes]] = []
    messages_blob = "\n".join(m.model_dump_json() for m in redacted).encode("utf-8") + b"\n"
    entries.append(("messages.jsonl", messages_blob))

    for rel in _ARTIFACT_FILES:
        path = ot_dir / rel
        if path.is_file() and not is_sensitive_path(path):
            entries.append((f"artifacts/{rel}", path.read_bytes()))

    for dirname in _ARTIFACT_DIRS:
        directory = ot_dir / dirname
        if not directory.is_dir():
            continue
        for file in sorted(directory.rglob("*")):
            if file.is_file() and not is_sensitive_path(file):
                arc = f"artifacts/{file.relative_to(ot_dir).as_posix()}"
                entries.append((arc, file.read_bytes()))

    # Code-evidence repos (M72): bundle only the REPO-* metadata, never the
    # cloned working tree — it may carry credentials or other fetched secrets.
    repos = ot_dir / "repos"
    if repos.is_dir():
        for meta in sorted(repos.glob("*/metadata.yaml")):
            if not is_sensitive_path(meta):
                arc = f"artifacts/{meta.relative_to(ot_dir).as_posix()}"
                entries.append((arc, meta.read_bytes()))

    patches = _patches_privacy_clean(ot_dir)
    if patches is not None:
        entries.append(("artifacts/patches.jsonl", patches))

    manifest.files = sorted(name for name, _ in entries)

    out_path = out_path or ot_dir / "bundles" / f"{session_id}.zip"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("bundle.json", manifest.model_dump_json(indent=2))
        for name, data in entries:
            zf.writestr(name, data)
    return out_path


def read_bundle_manifest(bundle_path: Path) -> BundleManifest:
    with zipfile.ZipFile(bundle_path) as zf:
        return BundleManifest.model_validate_json(zf.read("bundle.json"))


def import_bundle(ot_dir: Path, bundle_path: Path, dest: Path | None = None) -> Path:
    """Extract a bundle into a read-only review directory. Never merges live data."""
    if not bundle_path.is_file():
        raise OpenTorusError(f"Bundle not found: {bundle_path}")
    manifest = read_bundle_manifest(bundle_path)
    dest = dest or ot_dir / "imports" / manifest.session_id
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(bundle_path) as zf:
        # Guard against zip-slip: refuse entries that escape the destination.
        # Compare on path components, not string prefixes — a sibling directory
        # whose name merely starts with ``dest`` (e.g. ``imports/S`` vs the
        # crafted ``imports/S_evil``) would pass a naive ``startswith`` check.
        dest_resolved = dest.resolve()
        for name in zf.namelist():
            target = (dest / name).resolve()
            if target != dest_resolved and dest_resolved not in target.parents:
                raise OpenTorusError(f"Refusing unsafe bundle entry path: {name}")
        zf.extractall(dest)
    return dest
