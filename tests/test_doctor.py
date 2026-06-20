"""Tests for ``opentorus doctor`` health checks."""

from __future__ import annotations

from pathlib import Path

from opentorus.config import default_config
from opentorus.doctor import run_doctor
from opentorus.workspace import init_workspace, workspace_dir


def test_doctor_ok_on_fresh_workspace(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.model.provider = "mock"
    checks = run_doctor(tmp_path, ot, config)
    names = {c.name for c in checks}
    assert "workspace" in names
    assert "config" in names
    assert "tools" in names
    assert all(c.ok for c in checks if c.name != "quality")
