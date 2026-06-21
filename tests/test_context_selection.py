"""Tests for retrieval-driven context selection (Milestone 28)."""

from __future__ import annotations

from pathlib import Path

from opentorus.agent.context import build_messages, select_relevant
from opentorus.agent.session import SessionMessage, append_message
from opentorus.config import default_config
from opentorus.privacy import provider_context_notice
from opentorus.research.memory import add_memory
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _seed(ot: Path) -> None:
    add_memory(ot, "facts", "Caching reduces p95 latency in the API gateway")
    add_memory(ot, "facts", "The frontend is written in TypeScript and React")


def test_relevant_artifacts_injected_into_messages(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _seed(ot)
    append_message(ot, SessionMessage(role="user", content="how do we improve latency?"))

    messages = build_messages(tmp_path, ot, default_config(), ["status"])
    blocks = [m.content for m in messages if m.role == "system"]
    relevant = next((b for b in blocks if "Relevant artifacts" in b), "")
    assert "latency" in relevant.lower()
    assert "FACT-0001" in relevant  # the caching/latency fact


def test_retrieval_can_be_disabled(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _seed(ot)
    append_message(ot, SessionMessage(role="user", content="how do we improve latency?"))

    config = default_config()
    config.context.retrieval_enabled = False
    messages = build_messages(tmp_path, ot, config, ["status"])
    assert all("Relevant artifacts" not in m.content for m in messages)


def test_selection_reason_recorded_in_notice(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _seed(ot)
    config = default_config()
    selected = select_relevant(ot, config, "latency caching gateway")
    assert selected
    notice = provider_context_notice(config, ["status"], selected=selected)
    assert "Selected artifacts" in notice
    assert selected[0][0].artifact_id in notice


def test_no_query_means_no_selection(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    _seed(ot)
    assert select_relevant(ot, default_config(), None) == []


def test_select_relevant_survives_embedding_failure(tmp_path: Path, monkeypatch) -> None:
    # A flaky embeddings/index backend must never crash the agent: select_relevant
    # degrades to no retrieval and, after several consecutive failures, trips a
    # recoverable circuit breaker for the rest of the run.
    import opentorus.agent.context as context

    ot = _ws(tmp_path)
    _seed(ot)
    context.reset_retrieval_breaker()

    def _boom(*args, **kwargs):
        raise TimeoutError("timed out")

    monkeypatch.setattr("opentorus.research.index.hybrid_search", _boom)
    config = default_config()
    # Each failure returns [] instead of raising; the breaker trips at the limit.
    for _ in range(context._RETRIEVAL_FAILURE_LIMIT):
        assert select_relevant(ot, config, "latency") == []
    assert context._retrieval_failures >= context._RETRIEVAL_FAILURE_LIMIT
    # Once tripped, subsequent calls skip retrieval entirely (no repeated timeout).
    calls = {"n": 0}

    def _count(*args, **kwargs):
        calls["n"] += 1
        return []

    monkeypatch.setattr("opentorus.research.index.hybrid_search", _count)
    assert select_relevant(ot, config, "latency") == []
    assert calls["n"] == 0  # breaker prevents re-calling the backend


def test_retrieval_breaker_resets_on_success(tmp_path: Path, monkeypatch) -> None:
    # A single transient failure must not permanently disable retrieval: a later
    # success resets the counter.
    import opentorus.agent.context as context

    ot = _ws(tmp_path)
    _seed(ot)
    context.reset_retrieval_breaker()
    config = default_config()

    monkeypatch.setattr(
        "opentorus.research.index.hybrid_search",
        lambda *a, **k: (_ for _ in ()).throw(TimeoutError("blip")),
    )
    assert select_relevant(ot, config, "latency") == []
    assert context._retrieval_failures == 1

    monkeypatch.setattr("opentorus.research.index.hybrid_search", lambda *a, **k: [])
    assert select_relevant(ot, config, "latency") == []
    assert context._retrieval_failures == 0  # success reset the counter
