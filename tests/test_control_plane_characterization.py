"""Characterization of the agent-loop control plane, pinned BEFORE the M1 extraction.

Every guard in ``AgentLoop`` speaks to the model in prose, and that prose is the
contract: it is what a recorded run shows, what the digest greps for, and what the
tests below fix byte for byte. The campaign-engine refactor moves the guards into
``opentorus.agent.control`` as pure policy objects; these tests are the proof that the
move changed nothing observable — thresholds, reason messages, step counts, and the
constructor signature ``AgentLoop`` exposes to its callers.

Written against the pre-refactor loop and kept unchanged afterwards.
"""

from __future__ import annotations

import inspect
import time
from pathlib import Path

from opentorus.actions import list_actions
from opentorus.agent.loop import AgentLoop
from opentorus.agent.session import read_messages
from opentorus.config import default_config
from opentorus.governance import route_model
from opentorus.providers.base import BaseProvider, ProviderResponse
from opentorus.tools.base import Tool, ToolCall, ToolResult
from opentorus.tools.builtin import build_default_registry
from opentorus.tools.registry import ToolRegistry
from opentorus.workspace import init_workspace, workspace_dir
from support.providers import ScriptedProvider, message, tool_call

# --- the constructor contract ---------------------------------------------------------

# ``inspect.signature(AgentLoop.__init__)`` before the control-plane extraction:
# (name, repr(default) or "<empty>"). M1 may only APPEND keyword-only parameters after
# these; every entry here keeps its name, position and default.
M0_SIGNATURE: list[tuple[str, str]] = [
    ("self", "<empty>"),
    ("root", "<empty>"),
    ("ot_dir", "<empty>"),
    ("provider", "<empty>"),
    ("registry", "<empty>"),
    ("config", "<empty>"),
    ("max_steps", "6"),
    ("session_id", "None"),
    ("confirm", "None"),
    ("on_text", "None"),
    ("on_status", "None"),
    ("on_llm_request", "None"),
    ("on_llm_response", "None"),
    ("stream_llm", "False"),
    ("on_thinking", "None"),
    ("deliverable_bootstrap", "None"),
    ("session_gate", "None"),
    ("session_recovery_hint", "None"),
    ("pre_deliverable_gate", "None"),
    ("pre_deliverable_gate_detail", "None"),
    ("deliverable_complete", "None"),
    ("tool_gate", "None"),
    ("stall_check", "None"),
]


def _signature_snapshot() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for param in inspect.signature(AgentLoop.__init__).parameters.values():
        default = "<empty>" if param.default is inspect.Parameter.empty else repr(param.default)
        out.append((param.name, default))
    return out


def test_agent_loop_init_signature_snapshot() -> None:
    snapshot = _signature_snapshot()
    assert snapshot[: len(M0_SIGNATURE)] == M0_SIGNATURE
    # Anything appended later must be keyword-only, so positional callers never shift.
    params = list(inspect.signature(AgentLoop.__init__).parameters.values())
    for param in params[len(M0_SIGNATURE) :]:
        assert param.kind is inspect.Parameter.KEYWORD_ONLY, param.name


# --- helpers ---------------------------------------------------------------------------


class _FakeTool(Tool):
    """A registry entry with a chosen name that always answers the same way."""

    input_schema: dict = {"type": "object", "properties": {}}
    permission = "read"

    def __init__(self, name: str, content: str = "ok", *, ok: bool = True) -> None:
        self.name = name
        self.description = f"fake {name}"
        self._content = content
        self._ok = ok

    def run(self, call: ToolCall) -> ToolResult:
        if self._ok:
            return self.ok(call, self._content)
        return self.fail(call, self._content)


class _RepeatCall(BaseProvider):
    """Cycle through a fixed list of tool calls forever."""

    name = "repeat"

    def __init__(self, calls: list[tuple[str, dict]]) -> None:
        self._calls = calls
        self._i = 0

    def generate(self, messages, tools=None):  # type: ignore[override]
        name, args = self._calls[self._i % len(self._calls)]
        self._i += 1
        return ProviderResponse(kind="tool_call", tool_name=name, tool_args=args)


def _workspace(tmp_path: Path):
    init_workspace(tmp_path)
    ot = workspace_dir(tmp_path)
    config = default_config()
    config.permissions.mode = "trusted"
    return ot, config


def _tool_messages(ot: Path) -> list[str]:
    return [m.content for m in read_messages(ot) if m.role == "tool"]


# --- identical-failure ladder ---------------------------------------------------------


def test_identical_failure_stop_after_six_repeats(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    registry = build_default_registry(tmp_path, ot, config)
    provider = _RepeatCall([("exp_run", {"exp_id": "EXP-9999"})])
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=50)
    answer = loop.run("run the experiment")
    assert answer == (
        "Stopped: exp_run failed 6 times with identical arguments and an identical error "
        "— no progress is possible without changing the call. The failing call and its "
        "error are preserved in the session log; the dossier holds the current state."
    )
    assert loop.steps_run == 6
    assert loop.hit_max_steps is False
    tool_msgs = _tool_messages(ot)
    assert len(tool_msgs) == 6
    # Warned from the third identical failure, with the countdown spelled out.
    assert "[loop guard]" not in tool_msgs[0] and "[loop guard]" not in tool_msgs[1]
    assert tool_msgs[2].endswith(
        "\n\n[loop guard] This exact exp_run call has now failed 3 times with the identical "
        "error. Do NOT repeat it unchanged — change the arguments to address the error "
        "above, take a different approach, or record the blocker with "
        "memory_add(kind=decisions). The run stops after 3 more identical failure(s)."
    )
    assert tool_msgs[5].endswith(
        "[loop guard] This exact exp_run call has now failed 6 times with the identical "
        "error. Do NOT repeat it unchanged — change the arguments to address the error "
        "above, take a different approach, or record the blocker with "
        "memory_add(kind=decisions)."
    )
    assert "The run stops after" not in tool_msgs[5]


def test_unchanged_error_warns_on_fourth_and_stops_on_eighth(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    registry = build_default_registry(tmp_path, ot, config)
    blocked_text = "Blocked: run_shell is not available during prove. Use exp_new then exp_run."

    class _Rewriter(BaseProvider):
        name = "rewriter"

        def __init__(self) -> None:
            self.n = 0

        def generate(self, messages, tools=None):  # type: ignore[override]
            self.n += 1
            return ProviderResponse(
                kind="tool_call", tool_name="run_shell", tool_args={"command": f"ls -{self.n}"}
            )

    loop = AgentLoop(
        tmp_path,
        ot,
        _Rewriter(),
        registry,
        config,
        max_steps=50,
        tool_gate=lambda name, args: blocked_text if name == "run_shell" else None,
    )
    answer = loop.run("list things")
    assert answer == (
        "Stopped: run_shell failed 8 times with different arguments and the identical "
        "error every time — the arguments were never what was wrong, and rewriting them "
        "again cannot help. The failing calls and their error are preserved in the session "
        "log; the dossier holds the current state."
    )
    assert loop.steps_run == 8
    tool_msgs = _tool_messages(ot)
    assert len(tool_msgs) == 8
    assert tool_msgs[:3] == [blocked_text] * 3
    assert tool_msgs[3] == (
        f"{blocked_text}\n\nYou have now called run_shell 4 times with different arguments "
        "and gotten this identical error every time. The arguments are not the problem — "
        "the error is telling you something you have not addressed yet. Read it literally "
        "and fix what it names, or record the obstruction with memory_add(kind=decisions) "
        "and take another route."
    )
    assert tool_msgs[7].startswith(f"{blocked_text}\n\nYou have now called run_shell 8 times")
    # Every gate block is in the audit trail, none of them ok.
    acts = list_actions(ot)
    assert len(acts) == 8 and all(not a.ok for a in acts)


# --- acquisition guards -----------------------------------------------------------------


def test_search_streak_nudge_from_the_fourth_consecutive_search(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    registry = ToolRegistry()
    registry.register(_FakeTool("lit_search", "hit"))
    provider = ScriptedProvider(
        [tool_call("lit_search", {"query": f"q{i}"}) for i in range(5)] + [message("done")]
    )
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=10)
    assert loop.run("search") == "done"
    tool_msgs = _tool_messages(ot)
    assert tool_msgs[:3] == ["hit"] * 3
    assert tool_msgs[3] == (
        "hit\n\n[loop guard] This is consecutive search #4 with nothing fetched or read in "
        "between. STOP searching: paper_fetch the most relevant hit NOW and paper_read it, "
        "or proceed to the deliverable — more searching adds no papers."
    )
    assert tool_msgs[4].endswith(
        "[loop guard] This is consecutive search #5 with nothing fetched or read in "
        "between. STOP searching: paper_fetch the most relevant hit NOW and paper_read it, "
        "or proceed to the deliverable — more searching adds no papers."
    )


def test_acquisition_ratio_nudge_at_fifteen_fetches_and_nothing_read(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    registry = ToolRegistry()
    registry.register(_FakeTool("paper_fetch", "fetched"))
    provider = ScriptedProvider(
        [tool_call("paper_fetch", {"identifier": f"2401.{i:05d}"}) for i in range(15)]
        + [message("done")]
    )
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=20)
    assert loop.run("collect") == "done"
    tool_msgs = _tool_messages(ot)
    assert len(tool_msgs) == 15
    assert tool_msgs[:14] == ["fetched"] * 14
    assert tool_msgs[14] == (
        "fetched\n\n[loop guard] 15 searches/fetches so far against 0 calls that did anything "
        "with the results. Collecting is not progress: paper_read what you already have, then "
        "record what it gives you (memory_add, claim_new) or write the deliverable. Fetching "
        "more will not move the run forward."
    )
    assert loop._acquisition_calls == 15 and loop._processing_calls == 0


# --- cached re-serve ---------------------------------------------------------------------


def test_cached_reread_is_served_four_times_then_refused(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    (tmp_path / "notes.md").write_text("SENTINEL", encoding="utf-8")
    registry = build_default_registry(tmp_path, ot, config)
    provider = _RepeatCall([("read_file", {"path": "notes.md"})])
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=30)
    answer = loop.run("read notes forever")

    tool_msgs = _tool_messages(ot)
    assert tool_msgs[0] == "SENTINEL"
    served_text = (
        "(Already read this earlier in the run; re-showing the cached content — then produce "
        "the deliverable: write_file (e.g. analysis.md).)\n\nSENTINEL"
    )
    assert tool_msgs[1:5] == [served_text] * 4
    refused_text = (
        "read_file with these arguments has already been re-served from cache several times "
        "and the content has not changed. Re-reading it cannot move this run forward: produce "
        "the deliverable (write_file (e.g. analysis.md)), or if something is missing, get it "
        "with a different call."
    )
    assert tool_msgs[5] == refused_text
    assert tool_msgs[6] == refused_text
    assert tool_msgs[7] == (
        f"{refused_text}\n\n[loop guard] This exact read_file call has now failed 3 times with "
        "the identical error. Do NOT repeat it unchanged — change the arguments to address "
        "the error above, take a different approach, or record the blocker with "
        "memory_add(kind=decisions). The run stops after 3 more identical failure(s)."
    )
    # 1 real read + 4 re-serves + 6 refusals, then the identical-failure cap ends the run.
    assert len(tool_msgs) == 11
    assert answer.startswith("Stopped: read_file failed 6 times with identical arguments")
    served_actions = [
        a for a in list_actions(ot) if a.stdout_summary == "(re-served from read cache)"
    ]
    assert len(served_actions) == 4 and all(a.ok for a in served_actions)


# --- chat-only stall -----------------------------------------------------------------------


_NO_TOOL_CALLS_STOP = (
    "Stopped: the model produced no tool calls at all despite tools being available — it "
    "likely does not support tool calling, which OpenTorus requires. Configure a "
    "tool-calling model (e.g. a recent OpenAI/Claude chat model, or `ollama pull qwen3`)."
)
_KEPT_CHATTING_STOP = (
    "Stopped: the model kept replying in chat without calling tools (no further progress). "
    "The dossier holds the current state."
)


def _gap_fill_loop(tmp_path: Path, provider: BaseProvider) -> AgentLoop:
    ot, config = _workspace(tmp_path)
    config.agent.max_steps = float("inf")
    registry = build_default_registry(tmp_path, ot, config)
    loop = AgentLoop(tmp_path, ot, provider, registry, config, max_steps=float("inf"))
    # Gap-fill state: a deliverable exists but never completes, so the bootstrap does not
    # re-fire and only the stall backstops can end the run.
    loop.deliverable_bootstrap = ("status", {})
    loop._deliverable_satisfied = True
    loop._deliverable_complete = lambda: False
    return loop


def test_chat_only_stall_after_eight_distinct_replies_without_any_tool(tmp_path: Path) -> None:
    provider = ScriptedProvider([message(f"thinking about it, take {i}") for i in range(1, 10)])
    loop = _gap_fill_loop(tmp_path, provider)
    answer = loop.run("fill the gaps")
    assert answer == _NO_TOOL_CALLS_STOP
    assert loop.steps_run == 8
    assert loop.tool_calls_this_run == 0


def test_chat_only_stall_after_eight_replies_following_a_tool_call(tmp_path: Path) -> None:
    provider = ScriptedProvider(
        [tool_call("status")] + [message(f"still thinking, take {i}") for i in range(1, 10)]
    )
    loop = _gap_fill_loop(tmp_path, provider)
    answer = loop.run("fill the gaps")
    assert answer == _KEPT_CHATTING_STOP
    assert loop.steps_run == 9
    assert loop.tool_calls_this_run == 1


def test_repeated_identical_reply_in_gap_fill_stops_immediately(tmp_path: Path) -> None:
    provider = ScriptedProvider([message("Here is a structured approach: …")])
    loop = _gap_fill_loop(tmp_path, provider)
    answer = loop.run("fill the gaps")
    assert answer == _NO_TOOL_CALLS_STOP
    assert loop.steps_run == 2


# --- budgets -------------------------------------------------------------------------------


def test_wall_clock_stop_text(tmp_path: Path, monkeypatch) -> None:
    ot, config = _workspace(tmp_path)
    registry = build_default_registry(tmp_path, ot, config)
    loop = AgentLoop(tmp_path, ot, ScriptedProvider([message("x")]), registry, config)
    assert loop._wall_clock_stop(run_started=0.0) is None  # off by default
    config.agent.max_wall_seconds = 90.0
    monkeypatch.setattr(time, "monotonic", lambda: 1000.0)
    assert loop._wall_clock_stop(run_started=950.0) is None
    loop.steps_run = 7
    assert loop._wall_clock_stop(run_started=850.0) == (
        "Stopped: this run reached its wall-clock budget of 90s (elapsed 150s) after 7 model "
        "steps. Everything recorded so far is preserved; re-run to continue from the "
        "artifacts, or raise agent.max_wall_seconds."
    )


def test_governance_token_budget_stops_before_the_next_turn(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    config.governance.budgets.token_budget = 0
    registry = build_default_registry(tmp_path, ot, config)
    provider = ScriptedProvider([message("never sent")])
    loop = AgentLoop(tmp_path, ot, provider, registry, config)
    answer = loop.run("anything")
    assert answer == "[stopped] Budget reached, stopping cleanly: [BREACHED] tokens tokens: 0 / 0"
    assert provider.calls == []  # stopped before spending
    assert loop.steps_run == 1
    assert [m.content for m in read_messages(ot) if m.role == "assistant"] == [answer]


def test_pre_egress_dlp_blocks_a_cloud_send(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    assert config.governance.dlp is True
    registry = build_default_registry(tmp_path, ot, config)
    provider = ScriptedProvider([message("never sent")], name="openai")
    loop = AgentLoop(tmp_path, ot, provider, registry, config)
    answer = loop.run("Use the key AKIAABCDEFGHIJKLMNOP to fetch the data.")
    # A secret still fails closed — that is unchanged and must stay so. The wording is
    # new: it no longer says "Blocked pre-egress" twice, and it no longer offers
    # "disable governance.dlp" as a way past a *secret*, which was advice to turn the
    # control off rather than remove the credential.
    assert answer == (
        "[stopped] Pre-egress DLP blocked the request: detected aws_access_key. "
        "Remove the secret from the conversation; it must not be sent."
    )
    assert provider.calls == []


def test_local_provider_is_exempt_from_dlp(tmp_path: Path) -> None:
    ot, config = _workspace(tmp_path)
    registry = build_default_registry(tmp_path, ot, config)
    provider = ScriptedProvider([message("sent")], name="mock")
    loop = AgentLoop(tmp_path, ot, provider, registry, config)
    assert loop.run("Use the key AKIAABCDEFGHIJKLMNOP to fetch the data.") == "sent"
    assert len(provider.calls) == 1


# --- prove: literature gate on the deliverable ---------------------------------------


def test_pre_deliverable_gate_block_message_shape(tmp_path: Path) -> None:
    from opentorus.agent.prove_loop import run_prove
    from opentorus.research.dossier import store

    ot, config = _workspace(tmp_path)
    store.create_dossier(ot, "For all n, S(n)=n².", title="Gauss sum")
    config.agent.max_steps = 12
    config.agent.prove_until_gaps_closed = False
    provider = ScriptedProvider(
        [
            tool_call(
                "proof_write",
                {
                    "problem_id": "PROBLEM-0001",
                    "title": "Induction proof",
                    "theorem": "S(n)=n² for all n≥1.",
                    "main_proof": "By induction on n. [GAP-1] algebra detail.",
                    "gaps_markdown": "[GAP-1] expand inductive algebra.",
                    "gaps": ["Inductive step algebra"],
                },
            ),
            message("Proof draft recorded."),
        ]
    )
    run_prove(tmp_path, ot, provider, config, "PROBLEM-0001", literature_first=False, min_papers=1)
    tool_msgs = _tool_messages(ot)
    assert tool_msgs[0] == (
        "Blocked proof_write: literature requirements not met (Need ≥1 [parsed] papers in "
        "paper_list (have 0).). Complete lit_search, paper_fetch, and memory_add (one "
        "observation per parsed paper) before drafting a proof."
    )
    blocked = [a for a in list_actions(ot) if a.tool_name == "proof_write" and not a.ok]
    assert blocked and blocked[0].stderr_summary == tool_msgs[0][:500]


# --- routing rationale strings (compat surface for the routing milestone) -----------


def test_route_model_rationale_strings_and_legacy_default_fallback() -> None:
    config = default_config()
    config.model.name = "base-model"
    disabled = route_model(config, "proof")
    assert (disabled.model, disabled.rationale) == (
        "base-model",
        "routing disabled; using model.name",
    )

    config.governance.routing.enabled = True
    config.governance.routing.task_models = {"proof": "strong-model", "default": "mid-model"}
    routed = route_model(config, "proof")
    assert (routed.model, routed.rationale) == (
        "strong-model",
        "routed 'proof' to configured model",
    )
    fallback = route_model(config, "planning")
    assert (fallback.model, fallback.rationale) == (
        "mid-model",
        "routed 'planning' to configured model",
    )

    config.governance.routing.task_models = {"proof": "strong-model"}
    unrouted = route_model(config, "planning")
    assert (unrouted.model, unrouted.rationale) == (
        "base-model",
        "no route for 'planning'; using model.name",
    )
