"""Tests for single-sourced versioning (Milestone 39)."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import opentorus

_ROOT = Path(__file__).resolve().parents[1]


def test_version_is_semverish() -> None:
    assert re.fullmatch(r"\d+\.\d+\.\d+([.-].+)?", opentorus.__version__)


def test_pyproject_version_is_dynamic() -> None:
    data = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    # Version must not be hard-coded; it is sourced from opentorus.__version__.
    assert "version" not in data["project"]
    assert "version" in data["project"]["dynamic"]
    attr = data["tool"]["setuptools"]["dynamic"]["version"]["attr"]
    assert attr == "opentorus.__version__"


def test_cli_reports_version() -> None:
    from typer.testing import CliRunner

    from opentorus.cli import app

    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0
    assert opentorus.__version__ in result.stdout
