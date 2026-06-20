"""Tests for session bundles (Milestone 40)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from opentorus.agent.session import SessionMessage, append_message
from opentorus.bundle import (
    export_session,
    import_bundle,
    read_bundle_manifest,
)
from opentorus.errors import OpenTorusError
from opentorus.privacy import REDACTION
from opentorus.research.claims import new_claim
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _msg(content: str, session_id: str, *, sensitive: bool = False) -> SessionMessage:
    meta = {"session_id": session_id}
    if sensitive:
        meta["sensitive"] = True
    return SessionMessage(role="user", content=content, metadata=meta)


def test_export_creates_bundle(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, _msg("hello", "S1"))
    append_message(ot, _msg("world", "S1"))
    path = export_session(ot, "S1")
    assert path.is_file()
    manifest = read_bundle_manifest(path)
    assert manifest.session_id == "S1"
    assert manifest.message_count == 2


def test_export_unknown_session_raises(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        export_session(ot, "nope")


def test_only_target_session_is_exported(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, _msg("keep me", "S1"))
    append_message(ot, _msg("other session", "S2"))
    path = export_session(ot, "S1")
    with zipfile.ZipFile(path) as zf:
        messages = zf.read("messages.jsonl").decode("utf-8")
    assert "keep me" in messages
    assert "other session" not in messages


def test_sensitive_messages_are_redacted(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, _msg("normal text", "S1"))
    append_message(ot, _msg("AWS_SECRET=abc123", "S1", sensitive=True))
    path = export_session(ot, "S1")
    manifest = read_bundle_manifest(path)
    assert manifest.redacted_messages == 1
    with zipfile.ZipFile(path) as zf:
        messages = zf.read("messages.jsonl").decode("utf-8")
    assert "abc123" not in messages
    assert REDACTION in messages


def test_artifacts_included(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, _msg("hi", "S1"))
    new_claim(ot, "Gradient descent converges here.")
    path = export_session(ot, "S1")
    with zipfile.ZipFile(path) as zf:
        names = zf.namelist()
    assert "artifacts/memory/claims.jsonl" in names


def test_sensitive_patch_excluded(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, _msg("hi", "S1"))
    # Hand-write a patches.jsonl with one sensitive and one safe patch.
    (ot / "patches.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "PATCH-0001", "changes": [{"path": ".env"}]}),
                json.dumps({"id": "PATCH-0002", "changes": [{"path": "src/main.py"}]}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    path = export_session(ot, "S1")
    with zipfile.ZipFile(path) as zf:
        patches = zf.read("artifacts/patches.jsonl").decode("utf-8")
    assert "PATCH-0002" in patches
    assert "PATCH-0001" not in patches


def test_import_roundtrip(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, _msg("hello", "S1"))
    new_claim(ot, "A claim worth sharing.")
    path = export_session(ot, "S1")

    other = tmp_path / "reviewer"
    init_workspace(other)
    other_ot = workspace_dir(other)
    dest = import_bundle(other_ot, path)
    assert (dest / "messages.jsonl").is_file()
    assert (dest / "bundle.json").is_file()
    # Importing is read-only: the reviewer's live claims ledger is not merged into.
    live_claims = other_ot / "memory" / "claims.jsonl"
    live_text = live_claims.read_text(encoding="utf-8") if live_claims.exists() else ""
    assert "A claim worth sharing." not in live_text
    # The shared claim is present in the read-only review copy instead.
    assert "A claim worth sharing." in (dest / "artifacts" / "memory" / "claims.jsonl").read_text(
        encoding="utf-8"
    )


def test_import_missing_bundle_raises(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    with pytest.raises(OpenTorusError):
        import_bundle(ot, tmp_path / "nope.zip")


def test_import_rejects_sibling_prefix_zip_slip(tmp_path: Path) -> None:
    # The destination is .../imports/<session_id>; a crafted entry pointing at a
    # *sibling* directory whose name merely starts with the destination name
    # (``imports/S1_evil`` vs ``imports/S1``) must be rejected — a naive
    # string-prefix guard would let it escape.
    ot = _ws(tmp_path)
    malicious = tmp_path / "evil.zip"
    with zipfile.ZipFile(malicious, "w") as zf:
        zf.writestr("bundle.json", json.dumps({"session_id": "S1"}))
        zf.writestr("../S1_evil/payload.txt", "escaped")
    with pytest.raises(OpenTorusError):
        import_bundle(ot, malicious)
    assert not (ot / "imports" / "S1_evil" / "payload.txt").exists()
