"""Tests for anti-cycle guards during planned task execution."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.loop import AgentLoop
from opentorus.config import default_config
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.research.tasks import create_task
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


class RepeatGlobProvider(BaseProvider):
    """Always requests the same glob_files call (simulates Ollama cycling)."""

    def generate(self, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(
            kind="tool_call",
            content="",
            tool_name="glob_files",
            tool_args={"pattern": "**/*.py"},
        )


class RepeatMissingReadProvider(BaseProvider):
    """Keeps trying to read a non-existent algorithms module."""

    def generate(self, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(
            kind="tool_call",
            content="",
            tool_name="read_file",
            tool_args={"path": "src/algorithms.py"},
        )


class AlwaysChatProvider(BaseProvider):
    """Never calls a tool — always returns the same prose reply (like a reasoning
    model that answers in chat instead of acting)."""

    def generate(self, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(kind="message", content="Here is a structured approach: …")


def test_chat_only_gap_fill_does_not_cycle(tmp_path: Path) -> None:
    # Regression: during gap-fill (deliverable produced but gaps remain) the
    # bootstrap does not re-fire, so a model that keeps replying in chat would loop
    # to the step ceiling — especially with max_steps/prove_gap_fill set to inf.
    # The stall backstop must stop it quickly instead.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot, default_config())
    config = default_config()
    config.permissions.mode = "trusted"
    config.agent.max_steps = float("inf")  # no step cap — the backstop must still stop it
    loop = AgentLoop(tmp_path, ot, AlwaysChatProvider(), registry, config)
    # Simulate the gap-fill state: a deliverable exists but its gaps never close.
    loop.deliverable_bootstrap = ("status", {})
    loop._deliverable_satisfied = True
    loop._deliverable_complete = lambda: False
    answer = loop.run("fill the gaps")
    assert loop.steps_run < 12  # stopped fast, not at the 1000-step ceiling
    # This provider never calls a tool at all, so the stall message flags tool-calling
    # support (a model that calls tools then chats gets the "without calling tools" form).
    assert "tool calling" in answer.lower()


def test_repeat_glob_files_is_blocked(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot, default_config())
    task = create_task(ot, "report", "write_file final investigation report.")
    config = default_config()
    config.permissions.mode = "trusted"
    loop = AgentLoop(tmp_path, ot, RepeatGlobProvider(), registry, config, max_steps=6)
    loop._task_id = task.id
    loop.run(task.goal)
    from opentorus.agent.session import read_messages

    tool_text = "\n".join(m.content for m in read_messages(ot) if m.role == "tool")
    assert "Blocked repeat glob_files" in tool_text or "write_file" in loop.tools_used_this_run


class RepeatExistingReadProvider(BaseProvider):
    """Reads the same existing file twice, then stops (simulates re-reading a file
    whose content was compacted out of context)."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None) -> ProviderResponse:
        self.calls += 1
        if self.calls <= 2:
            return ProviderResponse(
                kind="tool_call", content="", tool_name="read_file", tool_args={"path": "notes.md"}
            )
        return ProviderResponse(kind="message", content="done")


def test_repeat_existing_read_file_reserves_content(tmp_path: Path) -> None:
    # A repeated successful read_file must re-serve the cached content (the file
    # may have been compacted away), not hard-block with "Blocked repeat", which
    # would strand the agent unable to recover a file it already read.
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    (tmp_path / "notes.md").write_text("UNIQUE_SENTINEL_CONTENT for the proof.", encoding="utf-8")
    registry = build_default_registry(tmp_path, ot, default_config())
    config = default_config()
    config.permissions.mode = "trusted"
    loop = AgentLoop(tmp_path, ot, RepeatExistingReadProvider(), registry, config, max_steps=5)
    loop.run("read notes then report")

    from opentorus.agent.session import read_messages

    tool_msgs = [m.content for m in read_messages(ot) if m.role == "tool"]
    # Both reads return the file content; the second is the re-served (nudged) copy.
    assert sum("UNIQUE_SENTINEL_CONTENT" in c for c in tool_msgs) >= 2
    assert any("re-showing the cached content" in c for c in tool_msgs)
    assert not any("Blocked repeat read_file with the same arguments" in c for c in tool_msgs)


def test_repeat_missing_read_file_is_blocked(tmp_path: Path) -> None:
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot, default_config())
    task = create_task(ot, "report", "write_file final investigation report.")
    config = default_config()
    config.permissions.mode = "trusted"
    loop = AgentLoop(tmp_path, ot, RepeatMissingReadProvider(), registry, config, max_steps=4)
    loop._task_id = task.id
    loop.run(task.goal)
    from opentorus.agent.session import read_messages

    messages = read_messages(ot)
    tool_text = "\n".join(m.content for m in messages if m.role == "tool")
    assert "Not a file" in tool_text or "Blocked repeat read_file" in tool_text
    assert tool_text.count("src/algorithms.py") >= 1


class AlwaysRereadProvider(BaseProvider):
    """A model that reads the same file forever instead of writing anything."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools=None) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse(
            kind="tool_call", content="", tool_name="read_file", tool_args={"path": "notes.md"}
        )


def test_endless_rereading_stops_being_free(tmp_path: Path) -> None:
    """A cache re-serve is logged ok=True, so no other guard can see the loop.

    Two recorded runs re-read one and the same statement.md 24 and 25 times, each
    costing a full model round-trip while nothing changed. The first few re-serves stay
    (a compacted-away file must be recoverable); past that the call has to fail so the
    identical-failure tracker takes over.
    """
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    (tmp_path / "notes.md").write_text("SENTINEL", encoding="utf-8")
    registry = build_default_registry(tmp_path, ot, default_config())
    config = default_config()
    config.permissions.mode = "trusted"
    loop = AgentLoop(tmp_path, ot, AlwaysRereadProvider(), registry, config, max_steps=20)
    loop.run("read notes forever")

    from opentorus.agent.session import read_messages

    tool_msgs = [m.content for m in read_messages(ot) if m.role == "tool"]
    served = [c for c in tool_msgs if "re-showing the cached content" in c]
    refused = [c for c in tool_msgs if "the content has not changed" in c]

    assert len(served) == 4, f"expected 4 cached re-serves, got {len(served)}"
    assert refused, "the loop must eventually stop re-serving"
    assert "produce the deliverable" in refused[0]
    # The run ends on its own rather than grinding to the step ceiling.
    assert len(tool_msgs) < 20
