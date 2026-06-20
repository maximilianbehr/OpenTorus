"""Local, offline-first artifact index.

Builds a keyword/BM25 index over project artifacts (memory, claims, papers,
reports, experiments) so the agent can recall the *right* context instead of
dumping everything into the prompt. The index is plain JSONL under
``.opentorus/index/`` — inspectable and git-friendly. No network or embeddings
are required; an embeddings backend can be added later behind the same API.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from opentorus.research.embeddings import Embedder

ArtifactType = str
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_K1 = 1.5
_B = 0.75
_RRF_K = 60


class IndexDoc(BaseModel):
    artifact_id: str
    artifact_type: ArtifactType
    title: str
    text: str


class IndexStatus(BaseModel):
    built: bool
    count: int = 0
    by_type: dict[str, int] = Field(default_factory=dict)
    built_at: datetime | None = None
    embeddings: bool = False
    embeddings_model: str | None = None


def index_dir(ot_dir: Path) -> Path:
    return ot_dir / "index"


def _docs_path(ot_dir: Path) -> Path:
    return index_dir(ot_dir) / "docs.jsonl"


def _status_path(ot_dir: Path) -> Path:
    return index_dir(ot_dir) / "status.json"


def _vectors_path(ot_dir: Path) -> Path:
    return index_dir(ot_dir) / "vectors.jsonl"


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _read_text(path: Path, limit: int = 4000) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeDecodeError):
        return ""


def gather_documents(ot_dir: Path) -> list[IndexDoc]:
    """Collect indexable documents from all artifact stores (live, not cached)."""
    from opentorus.research.claims import list_claims
    from opentorus.research.experiments import list_experiments
    from opentorus.research.memory import VALID_KINDS, list_memory
    from opentorus.research.papers import list_papers

    docs: list[IndexDoc] = []

    for kind in VALID_KINDS:
        for entry in list_memory(ot_dir, kind):
            docs.append(
                IndexDoc(
                    artifact_id=entry.id,
                    artifact_type=f"memory:{kind}",
                    title=entry.text[:80],
                    text=entry.text,
                )
            )

    for claim in list_claims(ot_dir):
        text = f"{claim.statement} {claim.notes}".strip()
        docs.append(
            IndexDoc(
                artifact_id=claim.id,
                artifact_type="claim",
                title=claim.statement[:80],
                text=text,
            )
        )

    for paper in list_papers(ot_dir):
        title = paper.title or paper.source
        body = f"{title} {paper.source}"
        if paper.abstract:
            body += f"\n{paper.abstract}"
        if paper.note_path:
            body += f"\n{_read_text(ot_dir / paper.note_path)}"
        docs.append(
            IndexDoc(
                artifact_id=paper.id,
                artifact_type="paper",
                title=title[:80],
                text=body,
            )
        )

    for exp in list_experiments(ot_dir):
        summary = _read_text(ot_dir / exp.path / "summary.md")
        docs.append(
            IndexDoc(
                artifact_id=exp.id,
                artifact_type="experiment",
                title=exp.title[:80],
                text=f"{exp.title}\n{summary}",
            )
        )

    return docs


def build_index(ot_dir: Path, embedder: Embedder | None = None) -> IndexStatus:
    """Gather all artifacts and persist the index under ``.opentorus/index/``.

    When an ``embedder`` is supplied, document vectors are computed and cached so
    later queries only embed the query. Without one, a BM25-only index is built.
    """
    docs = gather_documents(ot_dir)
    index_dir(ot_dir).mkdir(parents=True, exist_ok=True)
    lines = [doc.model_dump_json() for doc in docs]
    _docs_path(ot_dir).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    embeddings_built = False
    model_name: str | None = None
    vectors_file = _vectors_path(ot_dir)
    if embedder is not None and docs:
        vectors = embedder.encode([f"{d.title} {d.text}" for d in docs])
        with vectors_file.open("w", encoding="utf-8") as fh:
            for doc, vec in zip(docs, vectors, strict=True):
                fh.write(json.dumps({"artifact_id": doc.artifact_id, "vector": vec}) + "\n")
        embeddings_built = True
        model_name = getattr(embedder, "model_name", embedder.__class__.__name__)
    elif vectors_file.exists():
        vectors_file.unlink()

    by_type: Counter[str] = Counter(doc.artifact_type for doc in docs)
    status = IndexStatus(
        built=True,
        count=len(docs),
        by_type=dict(sorted(by_type.items())),
        built_at=datetime.now(UTC),
        embeddings=embeddings_built,
        embeddings_model=model_name,
    )
    _status_path(ot_dir).write_text(status.model_dump_json(indent=2), encoding="utf-8")
    return status


def _load_vectors(ot_dir: Path) -> dict[str, list[float]]:
    path = _vectors_path(ot_dir)
    if not path.is_file():
        return {}
    vectors: dict[str, list[float]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            data = json.loads(line)
            vectors[data["artifact_id"]] = data["vector"]
    return vectors


def load_documents(ot_dir: Path) -> list[IndexDoc]:
    """Load the cached index, falling back to a live gather if not yet built."""
    path = _docs_path(ot_dir)
    if not path.is_file():
        return gather_documents(ot_dir)
    docs: list[IndexDoc] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            docs.append(IndexDoc.model_validate_json(line))
    return docs


def index_status(ot_dir: Path) -> IndexStatus:
    path = _status_path(ot_dir)
    if not path.is_file():
        return IndexStatus(built=False)
    return IndexStatus.model_validate_json(path.read_text(encoding="utf-8"))


def _bm25_scores(query_tokens: list[str], doc_tokens: list[list[str]]) -> list[float]:
    n = len(doc_tokens)
    if n == 0:
        return []
    avgdl = sum(len(d) for d in doc_tokens) / n
    df: Counter[str] = Counter()
    for tokens in doc_tokens:
        for term in set(tokens):
            df[term] += 1
    scores = [0.0] * n
    for i, tokens in enumerate(doc_tokens):
        dl = len(tokens) or 1
        tf = Counter(tokens)
        score = 0.0
        for term in query_tokens:
            freq = tf.get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (n - df[term] + 0.5) / (df[term] + 0.5))
            score += idf * (freq * (_K1 + 1)) / (freq + _K1 * (1 - _B + _B * dl / avgdl))
        scores[i] = score
    return scores


def search(ot_dir: Path, query: str, k: int = 5) -> list[tuple[IndexDoc, float]]:
    """Return the top-``k`` (document, score) matches for ``query`` (score > 0)."""
    docs = load_documents(ot_dir)
    if not docs:
        return []
    query_tokens = _tokenize(query)
    doc_tokens = [_tokenize(f"{d.title} {d.text}") for d in docs]
    scores = _bm25_scores(query_tokens, doc_tokens)
    ranked = sorted(zip(docs, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [(doc, score) for doc, score in ranked[:k] if score > 0]


def _rrf(orderings: list[list[int]], rrf_k: int = _RRF_K) -> dict[int, float]:
    """Reciprocal-rank fusion: combine ranked index lists into a fused score map."""
    fused: dict[int, float] = {}
    for ordering in orderings:
        for rank, idx in enumerate(ordering, start=1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (rrf_k + rank)
    return fused


def hybrid_search(
    ot_dir: Path,
    query: str,
    k: int = 5,
    *,
    embedder: Embedder | None = None,
) -> list[tuple[IndexDoc, float]]:
    """Retrieve by BM25 fused with vector similarity (reciprocal-rank fusion).

    Degrades gracefully: with no ``embedder`` (and no usable query vector) this is
    exactly BM25. Document vectors are read from the cache when present, otherwise
    computed on the fly from the supplied embedder.
    """
    docs = load_documents(ot_dir)
    if not docs:
        return []

    query_tokens = _tokenize(query)
    doc_tokens = [_tokenize(f"{d.title} {d.text}") for d in docs]
    bm25 = _bm25_scores(query_tokens, doc_tokens)

    if embedder is None:
        ranked = sorted(zip(docs, bm25, strict=True), key=lambda p: p[1], reverse=True)
        return [(doc, score) for doc, score in ranked[:k] if score > 0]

    from opentorus.research.embeddings import cosine

    cached = _load_vectors(ot_dir)
    doc_vecs: list[list[float]]
    if all(d.artifact_id in cached for d in docs) and cached:
        doc_vecs = [cached[d.artifact_id] for d in docs]
    else:
        doc_vecs = embedder.encode([f"{d.title} {d.text}" for d in docs])
    query_vec = embedder.encode([query])[0]
    sims = [cosine(query_vec, dv) for dv in doc_vecs]

    bm25_order = sorted(range(len(docs)), key=lambda i: bm25[i], reverse=True)
    vec_order = sorted(range(len(docs)), key=lambda i: sims[i], reverse=True)
    fused = _rrf([bm25_order, vec_order])

    ranked_idx = sorted(fused, key=lambda i: fused[i], reverse=True)
    # Keep documents that surface in either signal (positive BM25 or similarity).
    return [(docs[i], fused[i]) for i in ranked_idx[:k] if bm25[i] > 0 or sims[i] > 0]
