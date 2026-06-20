"""Tests for privacy and the sensitive-file guard (Milestone 20)."""

from __future__ import annotations

from pathlib import Path

import pytest

from opentorus.agent.context import build_messages
from opentorus.agent.session import SessionMessage, append_message
from opentorus.config import default_config
from opentorus.errors import PermissionDeniedError
from opentorus.permissions.policy import evaluate_read, is_sensitive_path
from opentorus.privacy import REDACTION, provider_context_notice, redact_for_provider
from opentorus.tools.filesystem import read_file
from opentorus.workspace import init_workspace, workspace_dir


@pytest.mark.parametrize(
    "name",
    [
        ".env",
        ".env.production",
        "prod.env",
        "server.pem",
        "private.key",
        "id_rsa",
        "id_ed25519",
        "secrets.yaml",
        "credentials.json",
        "kubeconfig",
        ".netrc",
        ".npmrc",
        ".git-credentials",
        "vault.kdbx",
        "passwords.txt",
        "access_token",
        "session.token",
    ],
)
def test_sensitive_files_detected(name: str) -> None:
    assert is_sensitive_path(name) is True


@pytest.mark.parametrize(
    "name",
    [
        "main.py",
        "README.md",
        "data.csv",
        "config.toml",
        # Precise patterns must not flag common ML/source files.
        "tokenizer.json",
        "tokenizer_config.json",
        "password_reset.py",
        "secret_santa.py",
    ],
)
def test_non_sensitive_files_not_flagged(name: str) -> None:
    assert is_sensitive_path(name) is False


def test_sensitive_in_dotdir_detected() -> None:
    assert is_sensitive_path(Path(".aws/credentials")) is True
    assert is_sensitive_path(Path("home/.ssh/config")) is True


def test_read_file_blocks_sensitive_without_permission(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SECRET=1\n", encoding="utf-8")
    with pytest.raises(PermissionDeniedError):
        read_file(tmp_path, ".env")
    # Explicit opt-in is required to read it.
    assert "SECRET" in read_file(tmp_path, ".env", allow_sensitive=True)


def test_sensitive_read_requires_confirmation_in_every_mode() -> None:
    for mode in ("safe", "ask", "trusted"):
        decision = evaluate_read(".env", mode)  # type: ignore[arg-type]
        assert decision.requires_confirmation is True


def test_redact_for_provider_default_excludes_sensitive() -> None:
    messages = [
        SessionMessage(role="user", content="hello"),
        SessionMessage(role="tool", content="API_KEY=xyz", metadata={"sensitive": True}),
    ]
    redacted = redact_for_provider(messages, allow_sensitive=False)
    assert redacted[0].content == "hello"
    assert redacted[1].content == REDACTION

    kept = redact_for_provider(messages, allow_sensitive=True)
    assert kept[1].content == "API_KEY=xyz"


def test_build_messages_redacts_sensitive_history(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    append_message(ot, SessionMessage(role="user", content="please read .env"))
    append_message(
        ot, SessionMessage(role="tool", content="SECRET=1", metadata={"sensitive": True})
    )
    messages = build_messages(tmp_path, ot, default_config(), ["status"])
    assert any(m.content == REDACTION for m in messages)
    assert all("SECRET=1" not in m.content for m in messages)


def test_provider_context_notice_states_posture() -> None:
    notice = provider_context_notice(default_config(), ["status", "git_diff"])
    assert "excluded by default" in notice
    assert "status" in notice
