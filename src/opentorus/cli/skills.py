"""OpenTorus CLI — project skills (``.opentorus/skills/<name>/SKILL.md``)."""

from __future__ import annotations

import typer
from rich.markup import escape
from rich.table import Table

from opentorus.cli._base import (
    SortedGroup,
    _load_workspace_config,
    _require_workspace_dir,
    app,
    console,
)

skills_app = typer.Typer(cls=SortedGroup, help="List and show project skills (SKILL.md).")
app.add_typer(skills_app, name="skills")


@skills_app.command("list")
def skills_list() -> None:
    """List the skills the agent can load (project skills shadow user skills)."""
    from opentorus.skills import discover_skills, project_skills_dir

    base = _require_workspace_dir()
    skills = discover_skills(base, _load_workspace_config(base))
    if not skills:
        console.print(
            f"[dim]No skills. Add one as {project_skills_dir(base)}/<name>/SKILL.md "
            "with 'name' and 'description' front matter.[/dim]"
        )
        return
    table = Table(title="Skills")
    table.add_column("Name", style="bold")
    table.add_column("Source")
    table.add_column("Description")
    for skill in skills:
        table.add_row(skill.name, skill.source, escape(skill.description or "—"))
    console.print(table)


@skills_app.command("show")
def skills_show(name: str = typer.Argument(..., help="Skill name.")) -> None:
    """Print one skill's body (what ``skill_load`` returns to the agent)."""
    from opentorus.skills import SkillError, load_skill

    base = _require_workspace_dir()
    try:
        skill, body = load_skill(base, name, _load_workspace_config(base))
    except SkillError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[bold]{skill.name}[/bold] ({skill.source}: {skill.path})")
    if skill.description:
        console.print(f"[dim]{escape(skill.description)}[/dim]")
    console.print()
    console.print(body, markup=False, highlight=False)
