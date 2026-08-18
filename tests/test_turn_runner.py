"""The turn runner: provider turns and tool execution with their side effects.

Covers what the loop delegates: the usage ledger and event sink on a provider turn,
the action log on a blocked call (exactly one entry), permission blocks, and the
external ``should_stop`` signal that ends a run before any tool runs.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.control import ListSink, ReasonCode, RunStopped, ToolExecuted, TurnCompleted
from opentorus.agent.control.legacy import LegacyCallbackPolicySet
from opentorus.agent.control.turn_runner import TurnRunner
from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.tools.builtin import build_default_registry
from opentorus.usage import UsageRecord, read_usage
from opentorus.workspace import init_workspace, workspace_dir
from support.providers import ScriptedProvider, message, tool_call


def _workspace(tmp_path: Path, *, mode: str = "trusted"):
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = mode  # type: ignore[assignment]
    registry = build_default_registry(tmp_path, ot, config)
    return ot, config, registry


class _Routing:
    """A stand-in for ``providers.pool.RoutingDecisionRecord`` (structural)."""

    decision_id = "RTD-0001"
    task_class = "proof"
    requested_profile = "strong"
    selected_profile = "strong"
    configured_model = "model-x"
    fallback_reason = None


# --- provider turn ---------------------------------------------------------------------------


def test_request_records_usage_and_emits_turn_completed(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    sink = ListSink()
    provider = ScriptedProvider([message("hello")], model_name="model-x")
    runner = TurnRunner(
        tmp_path,
        ot,
        provider,
        registry,
        config,
        session_id="sess",
        event_sink=sink,
        routing=_Routing(),
        usage_tags={"campaign_id": "CAMPAIGN-0001", "worker_role": "prover"},
    )
    runner.step = 3
    turn = runner.request([])
    assert turn.stop is None and turn.response is not None and turn.response.content == "hello"

    records = read_usage(ot, "sess")
    assert len(records) == 1
    record = records[0]
    assert record.provider == "scripted"
    assert record.model == "model-x"  # the provider's model, not config.model.name
    assert record.tokens_estimated is True
    # Provenance columns are stamped only once the ledger schema has them.
    for field, value in (
        ("routing_decision_id", "RTD-0001"),
        ("selected_profile", "strong"),
        ("actual_model", "model-x"),
        ("campaign_id", "CAMPAIGN-0001"),
        ("worker_role", "prover"),
    ):
        if field in UsageRecord.model_fields:
            assert getattr(record, field) == value
    if "task_class" in UsageRecord.model_fields:
        assert record.task_class == "proof"

    completed = [e for e in sink.events if isinstance(e, TurnCompleted)]
    assert len(completed) == 1
    event = completed[0]
    assert event.step == 3 and event.session_id == "sess"
    assert event.response_kind == "message" and event.tool_names == []
    assert event.model == "model-x" and event.provider == "scripted"
    assert event.routing_decision_id == "RTD-0001"


def test_request_falls_back_to_config_model_name(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    provider = ScriptedProvider([tool_call("status", call_id="c1")])
    runner = TurnRunner(tmp_path, ot, provider, registry, config, session_id="s2")
    turn = runner.request([])
    assert turn.response is not None and turn.response.kind == "tool_call"
    record = read_usage(ot, "s2")[0]
    assert record.model == config.model.name == "mock-default"
    assert record.completion_tokens > 0  # the tool name + args are counted as output


def test_request_screens_outbound_for_cloud_providers(tmp_path: Path) -> None:
    from opentorus.agent.session import SessionMessage

    ot, config, registry = _workspace(tmp_path)
    provider = ScriptedProvider([message("never")], name="openai")
    runner = TurnRunner(tmp_path, ot, provider, registry, config, session_id="s3")
    turn = runner.request([SessionMessage(role="user", content="key AKIAABCDEFGHIJKLMNOP")])
    assert turn.response is None and turn.stop is not None
    assert turn.stop.reason_code is ReasonCode.EGRESS_BLOCKED
    assert turn.stop.message.startswith("[stopped] Pre-egress DLP blocked the request:")
    assert provider.calls == [] and read_usage(ot, "s3") == []


# --- tool execution -----------------------------------------------------------------------


def test_execute_tool_emits_tool_executed_and_counts(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    sink = ListSink()
    runner = TurnRunner(
        tmp_path,
        ot,
        ScriptedProvider([message("x")]),
        registry,
        config,
        session_id="s",
        event_sink=sink,
    )
    outcome = runner.execute_tool("status", {}, "c1")
    assert outcome.ok and outcome.ran and outcome.call_id == "c1"
    assert runner.tool_calls_this_run == 1 and runner.tools_used_this_run == ["status"]
    events = [e for e in sink.events if isinstance(e, ToolExecuted)]
    assert len(events) == 1 and events[0].outcome.name == "status" and events[0].outcome.ok
    acts = list_actions(ot)
    assert len(acts) == 1 and acts[0].ok and acts[0].tool_name == "status"


def test_blocked_gate_call_is_logged_exactly_once(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    sink = ListSink()
    policies = LegacyCallbackPolicySet(
        tool_gate=lambda name, args: (
            "Blocked: not in this phase." if name == "memory_list" else None
        )
    )
    runner = TurnRunner(
        tmp_path,
        ot,
        ScriptedProvider([message("x")]),
        registry,
        config,
        session_id="s",
        policies=policies,
        event_sink=sink,
    )
    outcome = runner.execute_tool("memory_list", {}, "c1")
    assert outcome.ok is False and outcome.ran is False
    assert outcome.blocked_by is ReasonCode.TOOL_GATE_BLOCKED
    assert outcome.content == "Blocked: not in this phase."
    assert runner.last_tool_ok is False
    assert runner.tool_calls_this_run == 0  # a blocked call never ran
    acts = list_actions(ot)
    assert len(acts) == 1
    assert acts[0].ok is False and acts[0].stderr_summary == "Blocked: not in this phase."
    events = [e for e in sink.events if isinstance(e, ToolExecuted)]
    assert len(events) == 1 and events[0].outcome.blocked_by is ReasonCode.TOOL_GATE_BLOCKED


def test_permission_block_returns_blocked_text(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path, mode="safe")
    runner = TurnRunner(
        tmp_path, ot, ScriptedProvider([message("x")]), registry, config, session_id="s"
    )
    outcome = runner.execute_tool("write_file", {"path": "out.md", "content": "hi"}, "c1")
    assert outcome.ok is False and outcome.blocked_by is ReasonCode.PERMISSION_DENIED
    assert outcome.content == "Blocked: Safe mode is read-only; file writes are not permitted."
    assert not (tmp_path / "out.md").exists()
    acts = list_actions(ot)
    assert len(acts) == 1 and acts[0].ok is False
    assert acts[0].permission_decision["allowed"] is False


def test_unknown_tool_is_a_failure_that_names_the_available_tools(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    runner = TurnRunner(
        tmp_path, ot, ScriptedProvider([message("x")]), registry, config, session_id="s"
    )
    outcome = runner.execute_tool("frobnicate", {}, "c1")
    assert outcome.ok is False and outcome.ran is False
    assert outcome.content.startswith("Unknown tool: 'frobnicate'. It does not exist")
    assert "status" in outcome.content
    assert list_actions(ot)[0].stderr_summary == "unknown tool"


def test_file_edit_is_tracked_as_pending_edit(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    runner = TurnRunner(
        tmp_path, ot, ScriptedProvider([message("x")]), registry, config, session_id="s"
    )
    outcome = runner.execute_tool("write_file", {"path": "out.md", "content": "hi\n"}, "c1")
    assert outcome.ok and outcome.edited and runner.edited
    assert outcome.file_edit == ("out.md", "", "hi\n")
    assert runner.pending_edits == [("out.md", "", "hi\n")]
    runner.reset_run()
    assert runner.pending_edits == [] and runner.edited  # ``edited`` survives on purpose


# --- cancellation through the loop --------------------------------------------------------


def test_should_stop_prevents_tool_execution_and_stops_the_run(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    sink = ListSink()
    provider = ScriptedProvider([tool_call("status"), message("done")])
    loop = AgentLoop(
        tmp_path,
        ot,
        provider,
        registry,
        config,
        max_steps=5,
        event_sink=sink,
        should_stop=lambda: True,
    )
    answer = loop.run("do it")
    assert answer == "[stopped] cancelled by caller"
    assert provider.calls == []  # never asked the model
    assert loop.tool_calls_this_run == 0 and list_actions(ot) == []
    assert loop.steps_run == 1 and loop.hit_max_steps is False
    assistant = [m.content for m in read_messages(ot) if m.role == "assistant"]
    assert assistant == ["[stopped] cancelled by caller"]
    stopped = [e for e in sink.events if isinstance(e, RunStopped)]
    assert len(stopped) == 1 and stopped[0].decision.reason_code is ReasonCode.CANCELLED


def test_should_stop_flipped_mid_turn_stops_before_the_next_tool(tmp_path: Path) -> None:
    from opentorus.providers.base import ProviderResponse, ToolCallRequest

    ot, config, registry = _workspace(tmp_path)
    flag = {"stop": False}
    two_calls = ProviderResponse(
        kind="tool_call",
        tool_calls=[
            ToolCallRequest(tool_name="status", tool_args={}, tool_call_id="c1"),
            ToolCallRequest(tool_name="memory_list", tool_args={}, tool_call_id="c2"),
        ],
    )
    provider = ScriptedProvider([two_calls, message("done")])
    loop = AgentLoop(
        tmp_path,
        ot,
        provider,
        registry,
        config,
        max_steps=5,
        should_stop=lambda: flag["stop"],
    )
    # Flip the flag as a side effect of the first tool running, so the check that
    # precedes the second tool of the same turn sees it.
    original = loop._runner.execute_tool

    def _execute(name, args, call_id):  # noqa: ANN001
        outcome = original(name, args, call_id)
        flag["stop"] = True
        return outcome

    loop._runner.execute_tool = _execute  # type: ignore[method-assign]
    answer = loop.run("do it")
    assert answer == "[stopped] cancelled by caller"
    assert loop.tools_used_this_run == ["status"]  # the second call never ran


def test_run_stopped_is_emitted_for_a_clean_finish_and_the_step_cap(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    sink = ListSink()
    loop = AgentLoop(
        tmp_path, ot, ScriptedProvider([message("done")]), registry, config, event_sink=sink
    )
    assert loop.run("hi") == "done"
    stopped = [e for e in sink.events if isinstance(e, RunStopped)]
    assert len(stopped) == 1 and stopped[0].decision.reason_code is ReasonCode.OK
    assert stopped[0].decision.message == "done"

    sink2 = ListSink()
    loop2 = AgentLoop(
        tmp_path,
        ot,
        ScriptedProvider([tool_call("status")]),
        registry,
        config,
        max_steps=2,
        event_sink=sink2,
    )
    loop2.run("poll forever")
    assert loop2.hit_max_steps is True
    stopped2 = [e for e in sink2.events if isinstance(e, RunStopped)]
    assert stopped2[-1].decision.reason_code is ReasonCode.STEP_CAP_REACHED
    assert len([e for e in sink2.events if isinstance(e, TurnCompleted)]) == 2
