"""The request prefix must stay stable across steps.

A local inference server can only reuse its KV cache for the prompt prefix it has
already seen. The workspace inventory used to sit at message index 1 — it changes
almost every turn, so the shared prefix ended a few hundred tokens in and everything
behind it was re-evaluated on every single step.

Measured on a real run before this change (examples/matrix-spencer, gemma4:31b,
provider-reported counts): 1,263,204 prompt tokens against 51,534 completion tokens,
with prompt_eval_count climbing 8k -> 30k in lockstep with latency. 96% of all tokens
processed were re-sent prompt.

These tests pin the ordering property, plus the two constraints that make the naive
"just append it at the end" version wrong: the final turn must stay the answer target,
and a tool_call/tool_result pair must never be split.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.actions import log_action
from opentorus.agent.context import build_messages
from opentorus.agent.session import SessionMessage, append_message
from opentorus.config import default_config
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _contents(messages: list[SessionMessage]) -> list[str]:
    return [f"{m.role}:{m.content}" for m in messages]


def _common_prefix(a: list[str], b: list[str]) -> int:
    n = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        n += 1
    return n


def _advance_one_step(ot: Path, question: str) -> None:
    """What a real agent step does: run a tool, then add the next turn.

    The recorded tool call is the point — the inventory embeds the last five actions,
    so it changes on essentially every step of a real run. That is what made its
    position at the front of the request so expensive.
    """
    log_action(ot, "status", ok=True, args={})
    append_message(ot, SessionMessage(role="user", content=question))


def test_prefix_survives_a_new_turn(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    config = default_config()
    for i in range(6):
        append_message(ot, SessionMessage(role="user", content=f"question {i}"))
        append_message(ot, SessionMessage(role="assistant", content=f"answer {i}"))

    before = _contents(build_messages(tmp_path, ot, config, ["status"]))
    _advance_one_step(ot, "a brand new question")
    after = _contents(build_messages(tmp_path, ot, config, ["status"]))

    shared = _common_prefix(before, after)
    # Everything except the volatile block and the new turn is reused.
    assert shared >= len(before) - 2, f"only {shared}/{len(before)} messages were stable"


def test_legacy_ordering_is_what_we_moved_away_from(tmp_path: Path) -> None:
    """Guards the comparison: with stable_prefix off, the prefix collapses to nothing."""
    ot = _ws(tmp_path)
    config = default_config()
    config.context.stable_prefix = False
    for i in range(6):
        append_message(ot, SessionMessage(role="user", content=f"question {i}"))
        append_message(ot, SessionMessage(role="assistant", content=f"answer {i}"))

    before = _contents(build_messages(tmp_path, ot, config, ["status"]))
    _advance_one_step(ot, "a brand new question")
    after = _contents(build_messages(tmp_path, ot, config, ["status"]))

    # The inventory carries the recent-action list, and it sits at index 1.
    assert "Workspace context" in before[1]
    assert "recent actions" in before[1]
    # So a single tool call invalidates everything after the system prompt: one
    # message of reusable prefix, and the entire history re-evaluated behind it.
    assert _common_prefix(before, after) == 1


def test_final_turn_stays_the_answer_target(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, SessionMessage(role="user", content="the actual question"))
    messages = build_messages(tmp_path, ot, default_config(), ["status"])
    assert messages[-1].role == "user"
    assert messages[-1].content == "the actual question"


def test_tool_result_pairing_is_not_split(tmp_path: Path) -> None:
    """Inserting volatile state must never land between a tool call and its results."""
    ot = _ws(tmp_path)
    append_message(ot, SessionMessage(role="user", content="run the status tool"))
    append_message(
        ot,
        SessionMessage(
            role="assistant",
            content="",
            metadata={"tool_calls": [{"id": "c1", "name": "status", "arguments": {}}]},
        ),
    )
    append_message(
        ot,
        SessionMessage(role="tool", content="observed output", metadata={"tool_call_id": "c1"}),
    )

    messages = build_messages(tmp_path, ot, default_config(), ["status"])
    roles = [m.role for m in messages]
    tool_idx = len(roles) - 1 - roles[::-1].index("tool")
    assert messages[tool_idx - 1].role == "assistant"
    assert messages[tool_idx - 1].metadata.get("tool_calls")
    assert messages[-1].role == "tool", "the tool result stays the message being answered"


def test_recovery_hint_stays_last(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    append_message(ot, SessionMessage(role="user", content="the actual question"))
    messages = build_messages(
        tmp_path, ot, default_config(), ["status"], recovery_hint="Attempt 1: call exp_run now."
    )
    assert messages[-1].content == "Attempt 1: call exp_run now."


def test_volatile_state_is_a_single_message(tmp_path: Path) -> None:
    """Consecutive same-role messages are what strict local chat templates reject."""
    ot = _ws(tmp_path)
    append_message(ot, SessionMessage(role="user", content="the actual question"))
    messages = build_messages(tmp_path, ot, default_config(), ["status"])
    roles = [m.role for m in messages]
    assert not any(a == b == "user" for a, b in zip(roles, roles[1:], strict=False))
