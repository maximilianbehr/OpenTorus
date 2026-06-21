"""OpenAI requires every assistant tool_call to be answered by a tool message.

A stopped/resumed run or a compaction split can leave a dangling tool_call (the
HTTP 400 the user hit) or an orphan tool result. to_openai_messages must repair the
sequence so the request is always well-formed.
"""

from __future__ import annotations

from opentorus.agent.session import SessionMessage
from opentorus.providers._convert import to_openai_messages


def _assistant_call(call_id: str, name: str = "read_file") -> SessionMessage:
    return SessionMessage(
        role="assistant",
        content="",
        metadata={"tool_calls": [{"id": call_id, "name": name, "args": {}}]},
    )


def _tool_result(call_id: str, content: str = "ok") -> SessionMessage:
    return SessionMessage(
        role="tool", content=content, metadata={"tool_call_id": call_id, "name": "x"}
    )


def _assert_valid_pairing(msgs: list[dict]) -> None:
    """Every assistant tool_calls is immediately followed by a tool msg per id; no orphans."""
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            ids = [tc["id"] for tc in m["tool_calls"]]
            for k, call_id in enumerate(ids):
                follower = msgs[i + 1 + k]
                assert follower["role"] == "tool"
                assert follower["tool_call_id"] == call_id
            i += 1 + len(ids)
        else:
            assert m.get("role") != "tool", "orphan tool message left in the stream"
            i += 1


def test_dangling_tool_call_gets_synthetic_result() -> None:
    # Assistant requested a call; the run stopped before the tool returned.
    msgs = to_openai_messages(
        [
            SessionMessage(role="user", content="do it"),
            _assistant_call("call_utwyqz4m"),
        ]
    )
    _assert_valid_pairing(msgs)
    tool_msgs = [m for m in msgs if m["role"] == "tool"]
    assert tool_msgs and tool_msgs[0]["tool_call_id"] == "call_utwyqz4m"
    assert "interrupted" in tool_msgs[0]["content"].lower()


def test_normal_pairing_preserved() -> None:
    msgs = to_openai_messages(
        [
            SessionMessage(role="user", content="do it"),
            _assistant_call("call_1"),
            _tool_result("call_1", "file contents"),
            SessionMessage(role="assistant", content="done"),
        ]
    )
    _assert_valid_pairing(msgs)
    assert [m["role"] for m in msgs] == ["user", "assistant", "tool", "assistant"]
    assert any(m["role"] == "tool" and m["content"] == "file contents" for m in msgs)


def test_orphan_tool_message_dropped() -> None:
    # A tool result with no preceding assistant tool_call must not be sent.
    msgs = to_openai_messages(
        [
            SessionMessage(role="user", content="hi"),
            _tool_result("call_orphan", "stray"),
            SessionMessage(role="assistant", content="ok"),
        ]
    )
    _assert_valid_pairing(msgs)
    assert not any(m["role"] == "tool" for m in msgs)


def test_invalid_tool_name_is_dropped() -> None:
    # A harmony-format marker leaked into a tool name (from a prior gpt-oss run)
    # violates OpenAI's ^[a-zA-Z0-9_-]+$ pattern and caused a 400. It must be dropped
    # so the request stays valid; its orphan tool result is dropped too.
    import re

    from opentorus.providers._convert import _OPENAI_TOOL_NAME_RE

    msgs = to_openai_messages(
        [
            SessionMessage(role="user", content="prove it"),
            SessionMessage(
                role="assistant",
                content="thinking",
                metadata={
                    "tool_calls": [
                        {"id": "c1", "name": "assistant<|channel|>commentary", "args": {}}
                    ]
                },
            ),
            _tool_result("c1", "leftover"),
            SessionMessage(role="user", content="continue"),
        ]
    )
    # No tool_calls with an OpenAI-invalid name survive the conversion.
    for m in msgs:
        for tc in m.get("tool_calls") or []:
            assert _OPENAI_TOOL_NAME_RE.match(tc["function"]["name"]) is not None
    # The garbage call left no orphan tool message either.
    assert not any(m["role"] == "tool" for m in msgs)
    # The assistant turn is preserved as plain content.
    assert any(m["role"] == "assistant" and not m.get("tool_calls") for m in msgs)
    assert re.search(r"thinking", str(msgs))


def test_mixed_valid_and_invalid_tool_calls() -> None:
    # An assistant turn with one valid and one garbage tool call keeps the valid one
    # (with its result) and drops the garbage one.
    msgs = to_openai_messages(
        [
            SessionMessage(
                role="assistant",
                content="",
                metadata={
                    "tool_calls": [
                        {"id": "good", "name": "read_file", "args": {}},
                        {"id": "bad", "name": "x<|y|>z", "args": {}},
                    ]
                },
            ),
            _tool_result("good", "contents"),
            _tool_result("bad", "garbage"),
            SessionMessage(role="user", content="ok"),
        ]
    )
    _assert_valid_pairing(msgs)
    ids = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert ids == ["good"]  # only the valid call's result remains


def test_partial_multicall_completed() -> None:
    # Two calls in one turn, only one answered → the other gets a synthetic result.
    msgs = to_openai_messages(
        [
            SessionMessage(
                role="assistant",
                content="",
                metadata={
                    "tool_calls": [
                        {"id": "a", "name": "read_file", "args": {}},
                        {"id": "b", "name": "status", "args": {}},
                    ]
                },
            ),
            _tool_result("a", "first"),
            SessionMessage(role="user", content="continue"),
        ]
    )
    _assert_valid_pairing(msgs)
    ids = [m["tool_call_id"] for m in msgs if m["role"] == "tool"]
    assert ids == ["a", "b"]
