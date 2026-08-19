"""Tests for the agent loop with the mock provider (Milestone 10)."""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.providers.mock_provider import MockProvider
from opentorus.tools.builtin import build_default_registry
from opentorus.workspace import init_workspace, workspace_dir


def _loop(tmp_path: Path) -> AgentLoop:
    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    return AgentLoop(tmp_path, ot_dir, MockProvider(), registry, default_config())


def test_finite_max_steps_is_a_hard_cap(tmp_path: Path) -> None:
    # A finite max_steps caps a provider that never returns a final message.
    # (max_steps=inf is intentionally unbounded — the no-progress stall guard and
    # Ctrl-C are the stops there; see tests/test_task_cycle_guard.py.)
    from opentorus.providers.base import BaseProvider, ProviderResponse

    class _NeverFinishes(BaseProvider):
        name = "never"

        def generate(self, messages, tools=None):  # type: ignore[override]
            return ProviderResponse(kind="tool_call", tool_name="status", tool_args={})

    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    loop = AgentLoop(tmp_path, ot_dir, _NeverFinishes(), registry, default_config(), max_steps=5)
    loop.run("loop until cap")
    assert loop.hit_max_steps is True
    assert loop.steps_run == 5


def test_status_task_runs_tool_and_persists(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    answer = loop.run("show me the status")
    assert "workspace_root" in answer
    assert "Validation not run" in answer

    ot_dir = workspace_dir(tmp_path)
    roles = [m.role for m in read_messages(ot_dir)]
    assert "user" in roles and "tool" in roles and "assistant" in roles
    assert list_actions(ot_dir)[-1].tool_name == "status"


def test_memory_task_uses_memory_tool(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    answer = loop.run("what is in memory?")
    assert "memory" in answer.lower()
    assert list_actions(workspace_dir(tmp_path))[-1].tool_name == "memory_list"


def test_plain_task_returns_direct_message(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    answer = loop.run("hello there")
    assert "mock provider" in answer.lower()
    # A direct answer should not have invoked any tool.
    assert list_actions(workspace_dir(tmp_path)) == []


def test_diff_task_uses_git_diff_tool(tmp_path: Path) -> None:
    loop = _loop(tmp_path)
    loop.run("show the diff")
    assert list_actions(workspace_dir(tmp_path))[-1].tool_name == "git_diff"


def test_stall_check_ends_the_run_honestly(tmp_path: Path) -> None:
    # The stall_check seam: a caller-supplied no-progress probe ends the run with
    # its message, even though the model keeps making (exempt) tool calls.
    from opentorus.providers.base import BaseProvider, ProviderResponse

    class _StatusForever(BaseProvider):
        name = "status"

        def generate(self, messages, tools=None):  # type: ignore[override]
            return ProviderResponse(kind="tool_call", tool_name="status", tool_args={})

    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = build_default_registry(tmp_path, ot_dir)
    holder: list[AgentLoop] = []
    loop = AgentLoop(
        tmp_path,
        ot_dir,
        _StatusForever(),
        registry,
        default_config(),
        max_steps=50,
        stall_check=lambda: "[stopped] stalled" if holder[0].steps_run > 3 else None,
    )
    holder.append(loop)
    answer = loop.run("poll status forever")
    assert answer == "[stopped] stalled"
    assert loop.steps_run == 4
    assert loop.hit_max_steps is False


def test_search_streak_nudge_after_consecutive_searches(tmp_path: Path) -> None:
    # Three real runs died in consecutive-search loops (11 lit_search in one run).
    # From the 4th consecutive search on, the result carries a stop-searching nudge;
    # a substantive tool (paper_fetch-like) resets the streak.
    from opentorus.providers.base import BaseProvider, ProviderResponse
    from opentorus.tools.base import Tool, ToolCall, ToolResult
    from opentorus.tools.registry import ToolRegistry

    class _StubSearch(Tool):
        name = "lit_search"
        description = "stub"
        input_schema: dict = {"type": "object", "properties": {}}

        def run(self, call: ToolCall) -> ToolResult:
            return self.ok(call, "1. some hit")

    class _StubFetch(Tool):
        name = "paper_fetch"
        description = "stub"
        input_schema: dict = {"type": "object", "properties": {}}

        def run(self, call: ToolCall) -> ToolResult:
            return self.ok(call, "fetched")

    class _Script(BaseProvider):
        name = "mock"

        def __init__(self, calls: list[str]) -> None:
            self._calls = calls
            self._i = 0

        def generate(self, messages, tools=None):  # type: ignore[override]
            if self._i >= len(self._calls):
                return ProviderResponse(kind="message", content="done")
            name = self._calls[self._i]
            self._i += 1
            return ProviderResponse(kind="tool_call", tool_name=name, tool_args={})

    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    registry = ToolRegistry()
    registry.register(_StubSearch())
    registry.register(_StubFetch())

    loop = AgentLoop(
        tmp_path,
        ot_dir,
        _Script(["lit_search"] * 5),
        registry,
        default_config(),
        max_steps=10,
    )
    loop.run("search a lot")
    tool_msgs = [m.content for m in read_messages(ot_dir) if m.role == "tool"]
    assert "[loop guard]" not in tool_msgs[2]  # 3rd search: below threshold
    assert "consecutive search #4" in tool_msgs[3]
    assert "consecutive search #5" in tool_msgs[4]

    # A fetch between searches resets the streak: no nudge on 3+1 pattern.
    init_workspace(tmp_path / "b")
    ot2 = workspace_dir(tmp_path / "b")
    loop2 = AgentLoop(
        tmp_path / "b",
        ot2,
        _Script(["lit_search", "lit_search", "lit_search", "paper_fetch", "lit_search"]),
        registry,
        default_config(),
        max_steps=10,
    )
    loop2.run("search then fetch")
    msgs2 = [m.content for m in read_messages(ot2) if m.role == "tool"]
    assert all("[loop guard]" not in m for m in msgs2)


# --- ``tool_choice="required"`` follows the provider actually in use -----------------------


class _ToolChoiceRecorder:
    """Wraps a scripted provider and records the ``tool_choice`` of every request.

    ``kind`` gives the wrapper the ``config`` a pool-built provider carries (its
    profile's ``model.provider``); ``None`` leaves it a bare provider with a name only.
    """

    def __init__(self, provider, *, name: str, kind: str | None) -> None:  # noqa: ANN001
        self._provider = provider
        self.name = name
        self.choices: list[str | dict | None] = []
        if kind is not None:
            cfg = default_config()
            cfg.model.provider = kind  # type: ignore[assignment]
            self.config = cfg

    @property
    def model_name(self):  # noqa: ANN201
        return self._provider.model_name

    def respond(self, messages, tools=None, on_text=None, **kwargs):  # noqa: ANN001, ANN003
        self.choices.append(kwargs.get("tool_choice"))
        return self._provider.respond(messages, tools, on_text, **kwargs)


def _deliverable_run(
    tmp_path: Path, *, provider_name: str, provider_kind: str | None, workspace_kind: str
) -> tuple[AgentLoop, list[str | dict | None]]:
    """Run a loop that needs a deliverable it never gets, so the retry nudge fires."""
    from support.providers import ScriptedProvider, message, tool_call

    init_workspace(tmp_path)
    ot_dir = workspace_dir(tmp_path)
    config = default_config()
    config.model.provider = workspace_kind  # type: ignore[assignment]
    config.permissions.mode = "trusted"  # type: ignore[assignment]
    registry = build_default_registry(tmp_path, ot_dir, config)
    scripted = ScriptedProvider(
        [message("chat"), message("chat"), tool_call("status"), message("d")]
    )
    recorder = _ToolChoiceRecorder(scripted, name=provider_name, kind=provider_kind)
    loop = AgentLoop(
        tmp_path,
        ot_dir,
        recorder,  # type: ignore[arg-type]
        registry,
        config,
        max_steps=6,
        session_gate=lambda: False,
    )
    loop.run("produce something")
    return loop, recorder.choices


def test_tool_choice_required_is_decided_from_the_leased_providers_kind(tmp_path: Path) -> None:
    """The workspace default profile is *not* Ollama, but the provider in use is a
    routed Ollama lease (its own config says so): the deliverable retry forces a tool
    call, exactly as it would for an Ollama default profile."""
    loop, choices = _deliverable_run(
        tmp_path, provider_name="ollama", provider_kind="ollama", workspace_kind="mock"
    )
    assert loop._provider_kind() == "ollama"
    assert choices[0] is None  # first ask: no nudge
    assert "required" in choices[1:]


def test_tool_choice_required_is_not_forced_on_a_non_ollama_lease(tmp_path: Path) -> None:
    """The mirror: the workspace default profile *is* Ollama, but the leased provider is
    OpenAI — its kind wins, so ``tool_choice`` stays unforced."""
    loop, choices = _deliverable_run(
        tmp_path, provider_name="openai", provider_kind="openai", workspace_kind="ollama"
    )
    assert loop._provider_kind() == "openai"
    assert len(choices) >= 2 and all(c is None for c in choices)


def test_tool_choice_falls_back_to_the_provider_name_then_the_workspace_profile(
    tmp_path: Path,
) -> None:
    """Without a provider ``config``, the provider ``name`` decides; without either,
    the workspace ``model.provider`` (the pre-routing behaviour) still applies."""
    loop, choices = _deliverable_run(
        tmp_path, provider_name="ollama", provider_kind=None, workspace_kind="mock"
    )
    assert loop._provider_kind() == "ollama" and "required" in choices[1:]

    loop, choices = _deliverable_run(
        tmp_path / "w2", provider_name="", provider_kind=None, workspace_kind="ollama"
    )
    assert loop._provider_kind() == "ollama" and "required" in choices[1:]
