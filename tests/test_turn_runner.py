"""The turn runner: provider turns and tool execution with their side effects.

Covers what the loop delegates: the usage ledger and event sink on a provider turn,
the action log on a blocked call (exactly one entry), permission blocks, and the
external ``should_stop`` signal that ends a run before any tool runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.control import ListSink, ReasonCode, RunStopped, ToolExecuted, TurnCompleted
from opentorus.agent.control.legacy import LegacyCallbackPolicySet
from opentorus.agent.control.turn_runner import TurnRunner
from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import SessionMessage, read_messages
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


def _configured(provider: ScriptedProvider, *, kind: str, base_url: str | None) -> ScriptedProvider:
    """Give a scripted double the ``config`` a pool-built provider carries.

    Real providers keep the profile-derived ``Config`` they were built from, so the
    runner can read the endpoint the lease actually talks to.
    """
    cfg = default_config()
    cfg.model.provider = kind  # type: ignore[assignment]
    cfg.model.name = provider.model_name or cfg.model.name
    cfg.model.base_url = base_url
    provider.config = cfg  # type: ignore[attr-defined]
    return provider


_SECRET_MESSAGE = "key sk-abcdefghijklmnopqrstuvwxyz0123456789"


def test_dlp_follows_the_leased_provider_not_the_default_profile(tmp_path: Path) -> None:
    """A cloud lease is screened even when the workspace default profile is local.

    The default ``model:`` block points at a local server (exempt from DLP), but the
    provider in use is an OpenAI lease built from another profile: the secret must
    not leave the machine.
    """
    from opentorus.agent.session import SessionMessage

    ot, config, registry = _workspace(tmp_path)
    config.governance.dlp = True
    config.model.base_url = "http://localhost:8000/v1"
    provider = _configured(
        ScriptedProvider([message("never")], name="openai", model_name="gpt-4o"),
        kind="openai",
        base_url="https://api.openai.com/v1",
    )
    runner = TurnRunner(tmp_path, ot, provider, registry, config, session_id="s-lease")
    turn = runner.request([SessionMessage(role="user", content=_SECRET_MESSAGE)])
    assert turn.response is None and turn.stop is not None
    assert turn.stop.reason_code is ReasonCode.EGRESS_BLOCKED
    assert provider.calls == [] and read_usage(ot, "s-lease") == []


def test_dlp_exempts_a_local_lease_even_when_the_default_profile_is_cloud(
    tmp_path: Path,
) -> None:
    """The mirror case: workspace default is a cloud endpoint, the lease is local."""
    from opentorus.agent.session import SessionMessage

    ot, config, registry = _workspace(tmp_path)
    config.governance.dlp = True
    config.model.provider = "openai"  # type: ignore[assignment]
    config.model.base_url = "https://api.openai.com/v1"
    provider = _configured(
        ScriptedProvider([message("ok")], name="openai", model_name="local-llm"),
        kind="openai",
        base_url="http://localhost:8000/v1",
    )
    runner = TurnRunner(tmp_path, ot, provider, registry, config, session_id="s-local")
    turn = runner.request([SessionMessage(role="user", content=_SECRET_MESSAGE)])
    assert turn.stop is None and turn.response is not None and turn.response.content == "ok"
    assert len(provider.calls) == 1


def test_dlp_falls_back_to_the_workspace_profile_without_a_provider_config(
    tmp_path: Path,
) -> None:
    """A provider without ``config`` (test doubles, the mock) is judged by ``model:``."""
    from opentorus.agent.session import SessionMessage

    ot, config, registry = _workspace(tmp_path)
    config.governance.dlp = True
    config.model.base_url = "http://localhost:8000/v1"
    provider = ScriptedProvider([message("ok")], name="openai")
    runner = TurnRunner(tmp_path, ot, provider, registry, config, session_id="s-fb")
    turn = runner.request([SessionMessage(role="user", content=_SECRET_MESSAGE)])
    assert turn.stop is None and turn.response is not None


def test_cost_estimate_uses_the_leased_providers_endpoint(tmp_path: Path) -> None:
    """Pricing follows the provider in use: a cloud lease costs money even when the
    default profile is local, and a local lease is free even when the default is cloud."""
    from opentorus.providers.base import ProviderResponse, TokenUsage

    ot, config, registry = _workspace(tmp_path)
    config.model.base_url = "http://localhost:8000/v1"  # default profile: local
    priced = ProviderResponse(
        kind="message",
        content="hi",
        usage=TokenUsage(prompt_tokens=1_000_000, completion_tokens=0),
    )
    cloud = _configured(
        ScriptedProvider([priced], name="openai", model_name="gpt-4o"),
        kind="openai",
        base_url="https://api.openai.com/v1",
    )
    TurnRunner(tmp_path, ot, cloud, registry, config, session_id="cloud").request([])
    (record,) = read_usage(ot, "cloud")
    assert record.cost_usd == 2.50  # gpt-4o input price per 1M tokens, not $0 (local)

    config.model.base_url = "https://api.openai.com/v1"  # default profile: cloud
    local = _configured(
        ScriptedProvider([priced], name="openai", model_name="gpt-4o"),
        kind="openai",
        base_url="http://localhost:8000/v1",
    )
    TurnRunner(tmp_path, ot, local, registry, config, session_id="local").request([])
    (record,) = read_usage(ot, "local")
    assert record.cost_usd == 0.0


# --- event sink robustness ------------------------------------------------------------------


class _RaisingSink:
    """A sink that violates the contract; the loop must survive it."""

    def __init__(self) -> None:
        self.seen = 0

    def emit(self, event: object) -> None:
        self.seen += 1
        raise RuntimeError("sink exploded")


def test_a_raising_sink_never_aborts_the_run(tmp_path: Path) -> None:
    ot, config, registry = _workspace(tmp_path)
    sink = _RaisingSink()
    provider = ScriptedProvider([tool_call("status"), message("done")])
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=5, event_sink=sink)
    assert loop.run("do it") == "done"
    assert sink.seen >= 4  # turn started, turn completed, tool executed, run stopped
    assert loop.tools_used_this_run == ["status"]
    assert len(read_usage(ot)) == 2  # usage is still recorded after the sink raised


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


# --- pre-egress DLP: secrets block, PII is redacted ------------------------------------------


def _cloud_runner(tmp_path: Path, **gov):
    """A runner whose provider looks like a cloud endpoint, so DLP actually runs."""
    ot, config, registry = _workspace(tmp_path)
    for key, value in gov.items():
        setattr(config.governance, key, value)
    config.model.base_url = "https://api.example.com/v1"
    provider = ScriptedProvider([message("ok")], model_name="gpt-x")
    provider.name = "openai"
    provider.config = config
    return TurnRunner(tmp_path, ot, provider, registry, config, session_id="dlp")


def test_a_secret_still_blocks_the_send(tmp_path: Path) -> None:
    """The control exists for this case and must keep failing closed."""
    runner = _cloud_runner(tmp_path)
    msgs = [SessionMessage(role="user", content="key is sk-abcdefghijklmnopqrstuvwxyz012345")]
    decision = runner.screen_outbound(msgs)
    assert decision is not None
    assert "openai_key" in decision.message
    assert "must not be sent" in decision.message


def test_an_author_email_is_redacted_not_blocked(tmp_path: Path) -> None:
    """Every academic PDF carries author emails; blocking on them closed the whole
    literature workflow for cloud providers."""
    runner = _cloud_runner(tmp_path)
    msgs = [SessionMessage(role="user", content="Correspondence: ada@uni-example.ac.uk here.")]
    assert runner.screen_outbound(msgs) is None
    assert "ada@uni-example.ac.uk" not in msgs[0].content
    assert "[redacted: email]" in msgs[0].content


def test_pii_in_tool_call_arguments_is_redacted_too(tmp_path: Path) -> None:
    """to_openai_messages serialises metadata['tool_calls'][i]['args'] into what it
    sends, and the DLP scan reads the whole message — so redacting only `content`
    would report the PII as removed while still putting it on the wire."""
    runner = _cloud_runner(tmp_path)
    msgs = [
        SessionMessage(
            role="assistant",
            content="recording it",
            metadata={
                "tool_calls": [
                    {
                        "id": "call-1",
                        "name": "memory_add",
                        "args": {"text": "contact grace@example.edu for the dataset"},
                    }
                ]
            },
        )
    ]
    assert runner.screen_outbound(msgs) is None
    sent = json.dumps(msgs[0].metadata)
    assert "grace@example.edu" not in sent
    assert "[redacted: email]" in sent


def test_block_mode_restores_the_old_behaviour(tmp_path: Path) -> None:
    runner = _cloud_runner(tmp_path, dlp_pii="block")
    msgs = [SessionMessage(role="user", content="write to ada@uni-example.ac.uk")]
    decision = runner.screen_outbound(msgs)
    assert decision is not None
    assert "email" in decision.message
    assert msgs[0].content.endswith("ada@uni-example.ac.uk"), "block must not also rewrite"


def test_off_mode_neither_blocks_nor_redacts(tmp_path: Path) -> None:
    runner = _cloud_runner(tmp_path, dlp_pii="off")
    msgs = [SessionMessage(role="user", content="write to ada@uni-example.ac.uk")]
    assert runner.screen_outbound(msgs) is None
    assert "ada@uni-example.ac.uk" in msgs[0].content


def test_a_secret_blocks_even_when_pii_would_be_redacted(tmp_path: Path) -> None:
    """A payload with both must not be waved through by the redaction path."""
    runner = _cloud_runner(tmp_path)
    msgs = [
        SessionMessage(
            role="user",
            content="mail ada@uni-example.ac.uk, key sk-abcdefghijklmnopqrstuvwxyz012345",
        )
    ]
    decision = runner.screen_outbound(msgs)
    assert decision is not None
    assert "openai_key" in decision.message


def test_a_local_provider_is_still_exempt(tmp_path: Path) -> None:
    """Nothing leaves the machine, so neither the block nor the rewrite should happen."""
    ot, config, registry = _workspace(tmp_path)
    config.model.base_url = "http://localhost:8000/v1"
    provider = ScriptedProvider([message("ok")], model_name="local-x")
    provider.name = "openai"
    provider.config = config
    runner = TurnRunner(tmp_path, ot, provider, registry, config, session_id="local")
    msgs = [SessionMessage(role="user", content="mail ada@uni-example.ac.uk")]
    assert runner.screen_outbound(msgs) is None
    assert "ada@uni-example.ac.uk" in msgs[0].content
