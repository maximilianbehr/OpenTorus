"""Secret scan before logs and exports (item 22): must-match / must-not-match tables."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from opentorus.governance import (
    SecretsInExport,
    redact_secrets,
    scan_path,
    scan_secrets,
    screen_export_entries,
)

# Assembled at runtime so this file itself does not trip a repository scan.
_PEM = "-----BEGIN " + "RSA PRIVATE KEY-----\nMIIEow...\n-----END RSA PRIVATE KEY-----"
_JWT = (
    "eyJhbGciOiJIUzI1NiJ9"
    + ".eyJzdWIiOiIxMjM0NTY3ODkwIn0"
    + ".dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"
)
_HF = "hf_" + "abcdEFGHijklMNOPqrstUVWXyz0123456789"

MUST_MATCH = [
    ("private_key_block", _PEM),
    ("private_key_block", "-----BEGIN " + "OPENSSH PRIVATE KEY-----"),
    ("private_key_block", "-----BEGIN " + "ENCRYPTED PRIVATE KEY-----"),
    ("jwt", f"cookie: session={_JWT}"),
    ("authorization_header", "Authorization: Bearer abc123def456ghi789jkl"),
    ("authorization_header", 'headers = {"Authorization": "token 9f8e7d6c5b4a39281706"}'),
    ("authorization_header", "authorization: Basic dXNlcjpwYXNzd29yZDEyMw=="),
    ("url_credentials", "postgres://admin:S3cr3tPw@db.internal:5432/prod"),
    ("url_credentials", "https://user:ghp4real9pass@github.com/org/repo.git"),
    ("env_assignment", "HF_TOKEN=" + "q8Zr2LmX9vB4nT7c"),
    ("env_assignment", "DB_PASSWORD: Tr0ub4dor&3xx".replace("&", "")),
    ("env_assignment", "export OPENTORUS_SECRET_KEY='a1b2c3d4e5f6g7h8'"),
    ("assigned_secret", "token=supersecretvalue123"),
    ("assigned_secret", "password = hunter2trustno1"),
    ("huggingface_token", _HF),
    ("openai_key", "sk-" + "proj-abcdefghijklmnopqrstuvwxyz0123"),
    ("aws_access_key", "AKIA" + "ABCDEFGHIJKLMNOP"),
]

MUST_NOT_MATCH = [
    "OPENAI_API_KEY=xxx",
    "OPENAI_API_KEY=xxxxxxxxxxxxxxxx",
    "api_key: <your-key>",
    "API_KEY=<YOUR_API_KEY>",
    "HF_TOKEN=${HF_TOKEN}",
    "DB_PASSWORD=$DB_PASSWORD",
    "password: changeme",
    "SECRET_KEY=replace-me-please",
    "token: your_token_here",
    "api_key = os.environ.get(self.api_key_env)",
    "token = match.group(0)",
    "self.api_key = api_key",
    "num_tokens = len(tokens)",
    "max_tokens=4096",
    "Authorization: Bearer <token>",
    "https://user:password@example.com/  (documentation placeholder)",
    "postgres://user:<password>@localhost/db",
    "The secret of the proof is the bound on the eigenvalues.",
    "a JWT has the form header.payload.signature",
    "-----BEGIN PUBLIC KEY-----",
]


@pytest.mark.parametrize(("kind", "text"), MUST_MATCH)
def test_must_match(kind: str, text: str) -> None:
    kinds = {f.kind for f in scan_secrets(text, scan_pii=False)}
    assert kind in kinds, f"{kind} not detected in {text!r} (got {kinds})"


@pytest.mark.parametrize("text", MUST_NOT_MATCH)
def test_must_not_match(text: str) -> None:
    assert scan_secrets(text, scan_pii=False) == [], text


def test_redaction_keeps_a_masked_preview_and_drops_the_value() -> None:
    secret = "q8Zr2LmX9vB4nT7cW1pK"
    text = f"HF_TOKEN={secret} and more"
    redacted, findings = redact_secrets(text)
    assert secret not in redacted
    assert "HF_TOKEN=" in redacted and "and more" in redacted
    assert "[redacted:env_assignment]" in redacted
    assert redacted.count("q8Zr") == 1  # a 4-char preview, never the whole value
    assert findings and findings[0].kind == "env_assignment"


def test_action_log_never_stores_a_secret(tmp_path: Path) -> None:
    from opentorus.actions import actions_path, log_action

    secret = "sk-" + "live-abcdefghijklmnopqrstuvwxyz012345"
    log_action(
        tmp_path,
        "run_shell",
        ok=True,
        args={"command": f"curl -H 'Authorization: Bearer {secret}' x"},
        stdout_summary=f"key={secret}",
    )
    raw = actions_path(tmp_path).read_text(encoding="utf-8")
    assert secret not in raw
    assert "redacted" in raw


def test_session_log_never_stores_a_secret(tmp_path: Path) -> None:
    from opentorus.agent.session import SessionMessage, append_message, session_path

    secret = "ghp_" + "A" * 36
    append_message(
        tmp_path,
        SessionMessage(
            role="tool", content=f"GITHUB_TOKEN={secret}", metadata={"args": {"t": secret}}
        ),
    )
    raw = session_path(tmp_path).read_text(encoding="utf-8")
    assert secret not in raw


def test_export_entries_are_redacted_or_refused() -> None:
    secret = "AKIA" + "QRSTUVWXYZ012345"
    entries = [("notes.md", f"aws key {secret}\n".encode()), ("img.png", b"\x89PNG\0\0data")]
    cleaned, findings = screen_export_entries(entries)
    assert secret.encode() not in cleaned[0][1]
    assert cleaned[1] == entries[1]  # binary passes through
    assert findings[0].path == "notes.md" and findings[0].line == 1
    with pytest.raises(SecretsInExport, match="notes.md:1"):
        screen_export_entries(entries, on_secret="refuse")


def test_pack_export_redacts_and_reports(tmp_path: Path) -> None:
    from opentorus.research.pack import export_pack
    from opentorus.workspace import init_workspace

    init_workspace(tmp_path)
    ot = tmp_path / ".opentorus"
    secret = "sk-" + "ant-abcdefghijklmnopqrstuvwxyz0123"
    (ot / "journal").mkdir(exist_ok=True)
    (ot / "journal" / "notes.md").write_text(f"used {secret} today\n", encoding="utf-8")
    path = export_pack(ot)
    with zipfile.ZipFile(path) as zf:
        body = zf.read("pack/journal/notes.md").decode()
        manifest = json.loads(zf.read("pack.json"))
    assert secret not in body
    assert manifest["secret_findings"][0]["path"] == "pack/journal/notes.md"
    with pytest.raises(SecretsInExport):
        export_pack(ot, tmp_path / "x.zip", on_secret="refuse")


def test_scan_path_walks_a_directory(tmp_path: Path) -> None:
    (tmp_path / "ok.md").write_text("nothing here\n", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / ".env.example").write_text("OPENAI_API_KEY=xxx\n", encoding="utf-8")
    (tmp_path / "sub" / "leak.py").write_text(
        "x = 1\nTOKEN = 'ab12cd34ef56gh78'\n", encoding="utf-8"
    )
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("password=abc123secret9\n", encoding="utf-8")
    findings = scan_path(tmp_path)
    assert [(f.path, f.line) for f in findings] == [("sub/leak.py", 2)]


def test_gov_scan_cli_on_a_directory(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    (tmp_path / "leak.txt").write_text("key " + "AKIA" + "ABCDEFGHIJKLMNOP\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["gov", "scan", str(tmp_path)])
    assert result.exit_code == 1
    assert "leak.txt:1" in result.output
    (tmp_path / "leak.txt").write_text("clean\n", encoding="utf-8")
    assert CliRunner().invoke(app, ["governance", "scan", str(tmp_path)]).exit_code == 0
