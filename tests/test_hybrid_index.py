"""Tests for the hybrid (BM25 + vector) index (Milestone 46).

A small deterministic fake embedder stands in for sentence-transformers, so the
fusion plumbing is tested offline. We verify that a semantically-related but
lexically-different query ranks correctly under fusion, and that retrieval
degrades to BM25-only when no embedder is available.
"""

from __future__ import annotations

from pathlib import Path

from opentorus.research.embeddings import cosine
from opentorus.research.index import build_index, hybrid_search, search
from opentorus.research.memory import add_memory
from opentorus.workspace import init_workspace, workspace_dir

# Concept groups: documents/queries map to a 2-d "meaning" vector.
_GROUPS = [
    {"car", "automobile", "vehicle", "transport", "engine", "driving"},
    {"cooking", "recipe", "food", "meal", "kitchen", "baking"},
]


class _FakeEmbedder:
    model_name = "fake-2d"

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for text in texts:
            words = set(text.lower().replace(".", " ").split())
            vectors.append([float(len(words & group)) for group in _GROUPS])
        return vectors


def _ot(tmp_path: Path) -> Path:
    init_workspace(tmp_path)
    return workspace_dir(tmp_path)


def _seed(ot: Path) -> None:
    add_memory(ot, "observations", "An automobile uses an engine for driving and transport.")
    add_memory(ot, "observations", "A recipe for baking bread in the kitchen, a tasty meal.")


def test_cosine_basic() -> None:
    assert cosine([1.0, 0.0], [2.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([], [1.0]) == 0.0


def test_hybrid_ranks_semantic_match_first(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed(ot)
    build_index(ot, embedder=_FakeEmbedder())

    # "car" is lexically absent from both docs; only the embedder relates it to
    # the automobile note.
    results = hybrid_search(ot, "car", k=2, embedder=_FakeEmbedder())
    assert results, "expected at least one hybrid result"
    top_doc, _ = results[0]
    assert "automobile" in top_doc.text.lower()


def test_bm25_only_finds_nothing_for_synonym(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed(ot)
    build_index(ot)
    # Plain BM25 cannot bridge car -> automobile.
    assert search(ot, "car", k=2) == []


def test_hybrid_degrades_to_bm25_without_embedder(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed(ot)
    build_index(ot)  # no embedder -> BM25-only index
    lexical = hybrid_search(ot, "kitchen recipe", k=2, embedder=None)
    assert lexical, "lexical query should still match via BM25"
    assert "recipe" in lexical[0][0].text.lower()


def test_build_index_records_embedding_status(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed(ot)
    status = build_index(ot, embedder=_FakeEmbedder())
    assert status.embeddings is True
    assert status.embeddings_model == "fake-2d"
    # Rebuilding without an embedder clears the vector cache.
    status2 = build_index(ot)
    assert status2.embeddings is False
    assert not (ot / "index" / "vectors.jsonl").exists()


def test_hybrid_uses_cached_vectors(tmp_path: Path) -> None:
    ot = _ot(tmp_path)
    _seed(ot)
    build_index(ot, embedder=_FakeEmbedder())
    assert (ot / "index" / "vectors.jsonl").is_file()
    # Even with cached doc vectors, the query still needs the embedder.
    results = hybrid_search(ot, "vehicle", k=2, embedder=_FakeEmbedder())
    assert "automobile" in results[0][0].text.lower()
