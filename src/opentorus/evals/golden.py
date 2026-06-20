"""Golden-transcript regression suite.

Records deterministic transcripts of ``dispatch``/loop runs against the mock
provider and compares them later to catch unintended behavior changes. Scenarios
are chosen so their output is fully deterministic (no timestamps, temp paths, or
other volatile data), keeping goldens stable across machines and CI.
"""

from __future__ import annotations

import difflib
import tempfile
from pathlib import Path

from pydantic import BaseModel


class GoldenScenario(BaseModel):
    name: str
    # Slash commands run through dispatch (deterministic output only).
    commands: list[str] = []
    # Natural-language goals run through the agent loop against the mock provider.
    goals: list[str] = []


GOLDEN_SCENARIOS: list[GoldenScenario] = [
    GoldenScenario(name="help", commands=["/help"]),
    GoldenScenario(
        name="mock-fallback",
        goals=["tell me a story about clouds"],
    ),
    GoldenScenario(
        name="unknown-command",
        commands=["/definitely-not-a-command"],
    ),
]


def _normalize(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"


def generate_transcript(scenario: GoldenScenario) -> str:
    """Run a scenario in an isolated temp workspace and return its transcript."""
    from opentorus.agent.loop import AgentLoop
    from opentorus.config import default_config
    from opentorus.providers.mock_provider import MockProvider
    from opentorus.repl import dispatch
    from opentorus.tools.builtin import build_default_registry
    from opentorus.workspace import init_workspace, workspace_dir

    parts: list[str] = []
    with tempfile.TemporaryDirectory(prefix="opentorus-golden-") as tmp:
        root = Path(tmp)
        init_workspace(root)
        ot = workspace_dir(root)
        for command in scenario.commands:
            result = dispatch(command, root)
            parts.append(f"$ {command}")
            parts.extend(result.messages)
        for goal in scenario.goals:
            registry = build_default_registry(root, ot)
            loop = AgentLoop(root, ot, MockProvider(), registry, default_config())
            answer = loop.run(goal)
            parts.append(f"> {goal}")
            parts.append(answer)
    return _normalize("\n".join(parts))


def golden_path(golden_dir: Path, name: str) -> Path:
    return golden_dir / f"{name}.txt"


def record_goldens(golden_dir: Path) -> list[str]:
    """(Re)generate and write all golden transcripts. Returns the scenario names."""
    golden_dir.mkdir(parents=True, exist_ok=True)
    names: list[str] = []
    for scenario in GOLDEN_SCENARIOS:
        golden_path(golden_dir, scenario.name).write_text(
            generate_transcript(scenario), encoding="utf-8"
        )
        names.append(scenario.name)
    return names


class GoldenResult(BaseModel):
    name: str
    matched: bool
    diff: str = ""


def verify_goldens(golden_dir: Path) -> list[GoldenResult]:
    """Compare freshly generated transcripts to the recorded goldens."""
    results: list[GoldenResult] = []
    for scenario in GOLDEN_SCENARIOS:
        path = golden_path(golden_dir, scenario.name)
        actual = generate_transcript(scenario)
        if not path.is_file():
            results.append(
                GoldenResult(name=scenario.name, matched=False, diff="(no golden recorded)")
            )
            continue
        expected = path.read_text(encoding="utf-8")
        if expected == actual:
            results.append(GoldenResult(name=scenario.name, matched=True))
        else:
            diff = "".join(
                difflib.unified_diff(
                    expected.splitlines(keepends=True),
                    actual.splitlines(keepends=True),
                    fromfile=f"{scenario.name} (golden)",
                    tofile=f"{scenario.name} (actual)",
                )
            )
            results.append(GoldenResult(name=scenario.name, matched=False, diff=diff))
    return results
