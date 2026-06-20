"""Tests for the local artifact index (Milestone 27)."""

from __future__ import annotations

from pathlib import Path

from opentorus.research.claims import new_claim
from opentorus.research.index import build_index, index_status, search
from opentorus.research.memory import add_memory
from opentorus.workspace import init_workspace, workspace_dir


def _ws(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def test_build_index_counts_documents(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_memory(ot, "facts", "Caching reduces p95 latency in the gateway")
    add_memory(ot, "decisions", "We will use an in-memory LRU cache")
    new_claim(ot, "Throughput improves with batching")

    status = build_index(ot)
    assert status.built is True
    assert status.count == 3
    assert status.by_type["claim"] == 1
    assert status.by_type["memory:facts"] == 1


def test_status_reflects_build(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    assert index_status(ot).built is False
    add_memory(ot, "facts", "alpha beta gamma")
    build_index(ot)
    assert index_status(ot).built is True


def test_search_ranks_relevant_artifact_first(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_memory(ot, "facts", "Caching reduces latency dramatically")
    add_memory(ot, "facts", "The deployment runs on Kubernetes clusters")
    new_claim(ot, "Batching increases throughput")
    build_index(ot)

    results = search(ot, "latency caching", k=3)
    assert results
    top_doc, top_score = results[0]
    assert top_score > 0
    assert "caching" in top_doc.text.lower()


def test_search_works_without_explicit_build(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    add_memory(ot, "observations", "GPU memory is the bottleneck during training")
    # No build_index call: search falls back to a live gather.
    results = search(ot, "gpu memory bottleneck")
    assert results
    assert "gpu" in results[0][0].text.lower()


def test_search_empty_returns_nothing(tmp_path: Path) -> None:
    ot = _ws(tmp_path)
    assert search(ot, "anything") == []
