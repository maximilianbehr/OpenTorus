"""Tests for the project .env loader (provider credentials)."""

from __future__ import annotations

from pathlib import Path

from opentorus.dotenv import _parse_env, load_dotenv_file, load_project_dotenv


def test_parse_env_handles_quotes_export_comments() -> None:
    parsed = _parse_env(
        "\n".join(
            [
                "# a comment",
                "",
                "OPENAI_API_KEY=sk-plain",
                'ANTHROPIC_API_KEY="sk-ant-quoted"',
                "export FOO='bar'",
                "WITH_COMMENT=value123 # trailing note",
                "not a valid line",
                "1BAD=skip",  # key must start with a letter/underscore
            ]
        )
    )
    assert parsed["OPENAI_API_KEY"] == "sk-plain"
    assert parsed["ANTHROPIC_API_KEY"] == "sk-ant-quoted"
    assert parsed["FOO"] == "bar"
    assert parsed["WITH_COMMENT"] == "value123"
    assert "1BAD" not in parsed


def test_load_dotenv_file_sets_unset_and_preserves_existing(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    env = tmp_path / ".env"
    env.write_text("OPENAI_API_KEY=sk-from-dotenv\nALREADY=from-dotenv\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("ALREADY", "from-shell")

    loaded = load_dotenv_file(env)
    assert "OPENAI_API_KEY" in loaded
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-from-dotenv"
    # An already-set variable (explicit shell export) is never overridden.
    assert os.environ["ALREADY"] == "from-shell"
    assert "ALREADY" not in loaded


def test_load_project_dotenv_reads_cwd(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-cwd\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    loaded = load_project_dotenv(tmp_path)
    import os

    assert "OPENAI_API_KEY" in loaded
    assert os.environ["OPENAI_API_KEY"] == "sk-cwd"


def test_cli_invocation_loads_dotenv_into_environ(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    # End to end: running any opentorus command loads the project .env so the provider
    # SDK (which reads os.environ) sees the key — no manual export needed.
    import os

    from typer.testing import CliRunner

    from opentorus.cli import app

    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert CliRunner().invoke(app, ["init"]).exit_code == 0
    (tmp_path / ".env").write_text("OPENAI_API_KEY=sk-cli-loaded\n", encoding="utf-8")
    CliRunner().invoke(app, ["status"])
    assert os.environ.get("OPENAI_API_KEY") == "sk-cli-loaded"
