"""Hybrid retrieval embeddings: provider APIs + optional local fallback (Milestone 46).

By default OpenTorus uses the configured chat provider's embedding API (OpenAI or
Ollama) fused with BM25. ``sentence-transformers`` remains an optional offline
fallback when ``context.embeddings_backend`` is ``local`` or when no provider
embedder is available (e.g. Anthropic chat has no embeddings API — try local
ST or a local Ollama embed model).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.error
import urllib.request
from typing import Protocol, runtime_checkable

from opentorus.config import Config, EmbeddingsBackend

logger = logging.getLogger("opentorus")

_DEFAULT_LOCAL_MODEL = "all-MiniLM-L6-v2"
_DEFAULT_OPENAI_MODEL = "text-embedding-3-small"
_DEFAULT_OLLAMA_MODEL = "nomic-embed-text"
_OLLAMA_DEFAULT_HOST = "http://localhost:11434"
_ENCODE_BATCH = 32
_MAX_CHARS = 8000


@runtime_checkable
class Embedder(Protocol):
    """Anything that turns texts into fixed-length vectors."""

    model_name: str

    def encode(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0.0:
        return vec
    return [x / norm for x in vec]


def _truncate(texts: list[str]) -> list[str]:
    return [t[:_MAX_CHARS] if len(t) > _MAX_CHARS else t for t in texts]


class SentenceTransformerEmbedder:
    """Adapter over ``sentence-transformers`` (loaded lazily, offline)."""

    def __init__(self, model_name: str) -> None:
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(_truncate(texts), normalize_embeddings=True)
        return [list(map(float, v)) for v in vectors]


class OpenAIEmbedder:
    """OpenAI ``/v1/embeddings`` (uses ``OPENAI_API_KEY``)."""

    def __init__(self, config: Config, model_name: str) -> None:
        self.model_name = model_name
        self._config = config

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not os.environ.get("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is not set")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("openai package is not installed") from exc

        client = OpenAI()
        trimmed = _truncate(texts)
        out: list[list[float]] = []
        for start in range(0, len(trimmed), _ENCODE_BATCH):
            batch = trimmed[start : start + _ENCODE_BATCH]
            response = client.embeddings.create(model=self.model_name, input=batch)
            out.extend(_normalize(list(map(float, row.embedding))) for row in response.data)
        return out


class OllamaEmbedder:
    """Ollama ``/api/embed`` against a local or remote Ollama server."""

    def __init__(self, config: Config, model_name: str) -> None:
        self.model_name = model_name
        self._host = (config.model.base_url or _OLLAMA_DEFAULT_HOST).rstrip("/")

    def encode(self, texts: list[str]) -> list[list[float]]:
        trimmed = _truncate(texts)
        out: list[list[float]] = []
        for start in range(0, len(trimmed), _ENCODE_BATCH):
            batch = trimmed[start : start + _ENCODE_BATCH]
            payload = json.dumps({"model": self.model_name, "input": batch}).encode("utf-8")
            request = urllib.request.Request(
                f"{self._host}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except urllib.error.URLError as exc:
                raise RuntimeError(f"Could not reach Ollama at {self._host}: {exc}") from exc
            embeddings = body.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(batch):
                raise RuntimeError(f"Unexpected Ollama embed response: {body!r}")
            out.extend(_normalize(list(map(float, vec))) for vec in embeddings)
        return out


def _embedding_model_for(config: Config, backend: str) -> str:
    model = config.context.embeddings_model
    if model:
        return model
    if backend == "openai":
        return _DEFAULT_OPENAI_MODEL
    if backend == "ollama":
        return _DEFAULT_OLLAMA_MODEL
    return _DEFAULT_LOCAL_MODEL


def _try_local(config: Config) -> Embedder | None:
    model_name = _embedding_model_for(config, "local")
    try:
        return SentenceTransformerEmbedder(model_name)
    except Exception as exc:
        logger.debug("Local embeddings unavailable (%s).", exc)
        return None


def _try_openai(config: Config) -> Embedder | None:
    model_name = _embedding_model_for(config, "openai")
    try:
        return OpenAIEmbedder(config, model_name)
    except Exception as exc:
        logger.debug("OpenAI embeddings unavailable (%s).", exc)
        return None


def _try_ollama(config: Config) -> Embedder | None:
    model_name = _embedding_model_for(config, "ollama")
    try:
        return OllamaEmbedder(config, model_name)
    except Exception as exc:
        logger.debug("Ollama embeddings unavailable (%s).", exc)
        return None


def _resolve_backend(config: Config) -> EmbeddingsBackend:
    backend = config.context.embeddings_backend
    if backend != "auto":
        return backend
    override = config.context.embeddings_provider
    if override:
        if override not in ("openai", "ollama", "local"):
            logger.warning(
                "Unknown context.embeddings_provider '%s'; falling back to auto.",
                override,
            )
        else:
            return override
    provider = config.model.provider
    if provider == "openai":
        return "openai"
    if provider == "ollama":
        return "ollama"
    return "local"


def _attempt_order(config: Config, backend: EmbeddingsBackend) -> list[str]:
    if backend == "off":
        return []
    if backend in ("openai", "ollama", "local"):
        return [backend]
    # auto — already resolved to concrete provider when possible
    provider = config.model.provider
    if provider == "openai":
        return ["openai", "ollama", "local"]
    if provider == "ollama":
        return ["ollama", "local"]
    if provider == "anthropic":
        # Anthropic has no public embeddings API; local ST or Ollama sidecar.
        return ["local", "ollama"]
    # mock and others
    return ["ollama", "local"]


def load_embedder(config: Config) -> Embedder | None:
    """Return an embedder for hybrid BM25+vector retrieval, or ``None`` for BM25-only.

    Priority (``embeddings_backend: auto``): match the chat provider when it has
    an embedding API (OpenAI, Ollama), else optional local ``sentence-transformers``,
    else the other network/local fallback.
    """
    if not config.context.embeddings_enabled:
        return None

    backend = _resolve_backend(config)
    if backend == "off":
        return None

    loaders = {
        "openai": _try_openai,
        "ollama": _try_ollama,
        "local": _try_local,
    }
    for kind in _attempt_order(config, backend):
        embedder = loaders[kind](config)
        if embedder is not None:
            logger.info(
                "Hybrid retrieval: %s embeddings (%s) + BM25.",
                kind,
                embedder.model_name,
            )
            return embedder

    logger.info("No embedding backend available; using BM25-only retrieval.")
    return None
