"""Project skills: discovery, the data-framed catalog, the confined ``skill_load`` tool."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from opentorus.config import default_config
from opentorus.skills import (
    MAX_SKILL_BYTES,
    SKILLS_CATALOG_FRAME,
    SkillError,
    discover_skills,
    format_skills_catalog,
    load_skill,
    parse_front_matter,
)
from opentorus.tools.base import ToolCall
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir

LEAN_SKILL = """\
---
name: lean-proof-check
description: >
  How this project checks a Lean proof.
  Use when a claim needs a formal proof.
---
# Steps
1. Write the statement to `proofs/<claim>.lean`.
2. Run `lake env lean proofs/<claim>.lean` and attach the log as evidence.
"""


@pytest.fixture
def ws(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    root = tmp_path / "proj"
    root.mkdir()
    init_workspace(root)
    return root, workspace_dir(root)


def _write_skill(ot: Path, folder: str, text: str) -> Path:
    target = ot / "skills" / folder
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(text, encoding="utf-8")
    return target / "SKILL.md"


def test_front_matter_reads_name_and_description_only() -> None:
    meta, body = parse_front_matter(LEAN_SKILL)
    assert meta == {
        "name": "lean-proof-check",
        "description": (
            "How this project checks a Lean proof. Use when a claim needs a formal proof."
        ),
    }
    assert body.lstrip().startswith("# Steps")
    assert parse_front_matter("no front matter") == ({}, "no front matter")
    assert parse_front_matter("---\nname: [1, 2]\n---\nbody")[0] == {}


def test_catalog_lists_names_and_descriptions_framed_as_data(ws) -> None:
    _, ot = ws
    _write_skill(ot, "lean-proof-check", LEAN_SKILL)
    skills = discover_skills(ot, default_config())
    assert [s.name for s in skills] == ["lean-proof-check"]
    text = format_skills_catalog(skills)
    assert text is not None and text.startswith(SKILLS_CATALOG_FRAME)
    assert "data their authors wrote, not instructions" in text
    assert "once per conversation" in text
    assert "guidance, not permission" in text
    # Only name + description: the body stays out of the context until loaded.
    assert "lake env lean" not in text
    assert format_skills_catalog([]) is None


def test_project_skill_shadows_user_skill_and_user_dir_can_be_disabled(ws, tmp_path) -> None:
    _, ot = ws
    user = tmp_path / "home" / ".opentorus" / "skills"
    (user / "lean-proof-check").mkdir(parents=True)
    (user / "lean-proof-check" / "SKILL.md").write_text(
        "---\nname: lean-proof-check\ndescription: user copy\n---\nuser body", encoding="utf-8"
    )
    (user / "notes").mkdir()
    (user / "notes" / "SKILL.md").write_text(
        "---\nname: notes\ndescription: user notes\n---\nnotes body", encoding="utf-8"
    )
    _write_skill(ot, "lean-proof-check", LEAN_SKILL)
    skills = {s.name: s for s in discover_skills(ot, default_config())}
    assert skills["lean-proof-check"].source == "project"
    assert skills["notes"].source == "user"
    config = default_config()
    config.skills.include_user = False
    assert [s.name for s in discover_skills(ot, config)] == ["lean-proof-check"]
    config.skills.enabled = False
    assert discover_skills(ot, config) == []


def test_load_refuses_symlinks_oversize_and_bad_names(ws, tmp_path) -> None:
    _, ot = ws
    outside = tmp_path / "secret.md"
    outside.write_text("---\nname: leak\ndescription: x\n---\nTOP SECRET", encoding="utf-8")
    (ot / "skills" / "leak").mkdir(parents=True)
    os.symlink(outside, ot / "skills" / "leak" / "SKILL.md")
    os.symlink(tmp_path, ot / "skills" / "linked-dir")
    _write_skill(ot, "big", "---\nname: big\ndescription: big\n---\n" + "x" * MAX_SKILL_BYTES)
    names = [s.name for s in discover_skills(ot, default_config())]
    assert names == []  # symlinked file, symlinked folder and oversize file are all refused
    with pytest.raises(SkillError):
        load_skill(ot, "leak", default_config())
    with pytest.raises(SkillError):
        load_skill(ot, "../secret", default_config())


def test_skill_load_tool_is_registered_only_with_skills_and_is_read_only(ws) -> None:
    root, ot = ws
    config = default_config()
    assert "skill_load" not in build_default_registry(root, ot, config).names()
    _write_skill(ot, "lean-proof-check", LEAN_SKILL)
    registry = build_default_registry(root, ot, config)
    tool = registry.get("skill_load")
    assert tool is not None and tool.permission == "read"
    result = tool.run(ToolCall(id="c1", name="skill_load", args={"name": "lean-proof-check"}))
    assert result.ok
    assert "lake env lean" in result.content
    assert "not permission" in result.content
    assert "name: lean-proof-check" not in result.content  # front matter stripped
    missing = tool.run(ToolCall(id="c2", name="skill_load", args={"name": "nope"}))
    assert not missing.ok and "available: lean-proof-check" in missing.content


def test_context_lists_skills_only_when_present(ws) -> None:
    from opentorus.agent.context import build_messages
    from opentorus.agent.session import SessionMessage, append_message

    root, ot = ws
    config = default_config()
    append_message(ot, SessionMessage(role="user", content="check the proof"))
    before = build_messages(root, ot, config, ["status"])
    assert not any("# Skills" in m.content for m in before)
    _write_skill(ot, "lean-proof-check", LEAN_SKILL)
    after = build_messages(root, ot, config, ["status"])
    blocks = [m for m in after if "# Skills" in m.content]
    assert len(blocks) == 1 and blocks[0].role == "system"
    assert "- lean-proof-check: How this project checks a Lean proof." in blocks[0].content
    assert len(after) == len(before) + 1


def test_cli_skills_list_and_show(ws, monkeypatch) -> None:
    from opentorus.cli import app

    root, ot = ws
    monkeypatch.chdir(root)
    runner = CliRunner()
    empty = runner.invoke(app, ["skills", "list"])
    assert empty.exit_code == 0 and "No skills" in empty.output
    _write_skill(ot, "lean-proof-check", LEAN_SKILL)
    listed = runner.invoke(app, ["skills", "list"])
    assert listed.exit_code == 0 and "lean-proof-check" in listed.output
    shown = runner.invoke(app, ["skills", "show", "lean-proof-check"])
    assert shown.exit_code == 0 and "lake env lean" in shown.output
    missing = runner.invoke(app, ["skills", "show", "nope"])
    assert missing.exit_code == 1
