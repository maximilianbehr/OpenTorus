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
