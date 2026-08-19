"""The local sentence-transformers embedder must be genuinely offline once cached.

Observed live: with the model fully present in the HF cache, every
``SentenceTransformer(...)`` init still sent HEAD/GET revalidation requests to
huggingface.co — bypassing the ``research.egress`` guard — and one dead CDN
connection (stuck in CLOSE-WAIT) stalled a campaign for ~15 minutes. Once the
cache holds the model, the loader must pass ``local_files_only=True`` so a warm
start makes zero network calls; only the very first download may go online (the
documented exception in the module docstring).

No model is downloaded here: the ``sentence_transformers`` import is replaced by
a spy module, matching the suite's no-network embedding test patterns.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from opentorus.research.embeddings import (
    SentenceTransformerEmbedder,
    _model_in_local_cache,
)


@pytest.fixture
def st_calls(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Replace ``sentence_transformers`` with a spy recording constructor kwargs."""
    calls: list[dict[str, Any]] = []

    def _ctor(model_name: str, **kwargs: Any) -> SimpleNamespace:
        calls.append({"model_name": model_name, **kwargs})
        return SimpleNamespace()

    monkeypatch.setitem(
        sys.modules, "sentence_transformers", SimpleNamespace(SentenceTransformer=_ctor)
    )
    return calls


@pytest.fixture
def hf_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the embedder's HF-cache probe at an isolated directory."""
    cache = tmp_path / "hf-hub"
    cache.mkdir()
    monkeypatch.setattr("opentorus.research.embeddings._hf_cache_dir", lambda: cache)
    return cache


def _seed_cache(cache: Path, repo: str) -> None:
    """Lay out a hub-style cached snapshot: models--org--name/snapshots/<rev>/…"""
    snapshot = cache / f"models--{repo.replace('/', '--')}" / "snapshots" / "0123abcd"
    snapshot.mkdir(parents=True)
    (snapshot / "config.json").write_text("{}", encoding="utf-8")


def test_warm_start_loads_with_local_files_only(
    st_calls: list[dict[str, Any]], hf_cache: Path
) -> None:
    """A cached model loads with ``local_files_only=True`` — zero network calls."""
    _seed_cache(hf_cache, "sentence-transformers/all-MiniLM-L6-v2")
    SentenceTransformerEmbedder("all-MiniLM-L6-v2")
    assert st_calls[-1]["model_name"] == "all-MiniLM-L6-v2"
    assert st_calls[-1]["local_files_only"] is True


def test_first_download_is_permitted_once(st_calls: list[dict[str, Any]], hf_cache: Path) -> None:
    """With an empty cache, the first load may go online (local_files_only=False)."""
    SentenceTransformerEmbedder("all-MiniLM-L6-v2")
    assert st_calls[-1]["local_files_only"] is False


def test_qualified_repo_name_resolves_in_cache(
    st_calls: list[dict[str, Any]], hf_cache: Path
) -> None:
    """An ``org/name`` model id maps to its own cache entry, not the ST org's."""
    _seed_cache(hf_cache, "acme/embedder")
    SentenceTransformerEmbedder("acme/embedder")
    assert st_calls[-1]["local_files_only"] is True
    # A *different* qualified repo is not covered by that entry.
    SentenceTransformerEmbedder("acme/other")
    assert st_calls[-1]["local_files_only"] is False


def test_local_model_directory_counts_as_cached(
    st_calls: list[dict[str, Any]], hf_cache: Path, tmp_path: Path
) -> None:
    """A model given as an on-disk directory never needs the network."""
    model_dir = tmp_path / "my-model"
    model_dir.mkdir()
    SentenceTransformerEmbedder(str(model_dir))
    assert st_calls[-1]["local_files_only"] is True


def test_empty_snapshots_dir_is_not_cached(hf_cache: Path) -> None:
    """A partially created cache entry (no snapshot content) must not claim offline."""
    empty = hf_cache / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots"
    empty.mkdir(parents=True)
    assert _model_in_local_cache("all-MiniLM-L6-v2") is False
