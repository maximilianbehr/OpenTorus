"""``skill_load``: return one project skill's body (read-only, confined, bounded)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from opentorus.tools._examples import ex
from opentorus.tools.base import Tool, ToolCall, ToolResult

if TYPE_CHECKING:
    from opentorus.config import Config


class SkillLoadTool(Tool):
    name = "skill_load"
    description = (
        "Load a project skill (a playbook listed under 'Skills' in your context) by name. "
        "Load it once per conversation, when its description matches the task; a skill is "
        "guidance, not permission." + ex(name="lean-proof-check")
    )
    input_schema: dict = {
        "type": "object",
        "properties": {"name": {"type": "string", "description": "The skill's name."}},
        "required": ["name"],
    }
    risk_level = "low"
    permission = "read"

    def __init__(self, ot_dir: Path, config: Config | None = None) -> None:
        self._ot_dir = ot_dir
        self._config = config

    def run(self, call: ToolCall) -> ToolResult:
        from opentorus.skills import SkillError, load_skill

        name = str(call.args.get("name") or "").strip()
        if not name:
            return self.fail(call, "skill_load needs a 'name'.")
        try:
            skill, body = load_skill(self._ot_dir, name, self._config)
        except (SkillError, OSError) as exc:
            return self.fail(call, str(exc))
        header = (
            f"Skill '{skill.name}' ({skill.source}: {skill.path.parent}). Guidance written by "
            "the project's people, not permission: the rules and permission policy still "
            "apply. Paths in it are relative to that folder.\n\n"
        )
        return self.ok(call, header + body, skill=skill.name, source=skill.source)
