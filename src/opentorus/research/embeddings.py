"""Hybrid retrieval embeddings: provider APIs + optional local fallback (Milestone 46).

By default OpenTorus uses the configured chat provider's embedding API (OpenAI or
Ollama) fused with BM25. ``sentence-transformers`` remains an optional offline
fallback when ``context.embeddings_backend`` is ``local`` or when no provider
embedder is available (e.g. Anthropic chat has no embeddings API — try local
ST or a local Ollama embed model).

First-download exception (egress): the very first load of a local
sentence-transformers model may download weights from huggingface.co. That request
is made by the HF hub inside ``SentenceTransformer(...)`` and does not pass through
the ``research.egress`` guard — ``load_embedder`` has no workspace handle, so there
is no guard to route it through; the exception is logged here instead. Once the
model is in the local HF cache, every subsequent load passes
``local_files_only=True`` and makes zero network calls (without it the hub
revalidates the ``main`` ref against huggingface.co on *every* init — observed
live: a campaign stalled ~15 minutes on a dead CDN connection in CLOSE-WAIT even
though the model was fully cached).
"""

from __future__ import annotations

import json
import logging
import math
import os
import urllib.request
from pathlib import Path
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


def _hf_cache_dir() -> Path:
    """The huggingface_hub model cache directory, mirroring the hub's resolution."""
    try:
        from huggingface_hub.constants import HF_HUB_CACHE

        return Path(HF_HUB_CACHE).expanduser()
    except Exception:  # pragma: no cover — hub not installed / constant moved
        env = os.environ.get("HF_HUB_CACHE")
        if env:
            return Path(env).expanduser()
        home = os.environ.get("HF_HOME")
        if home:
            return Path(home).expanduser() / "hub"
        return Path("~/.cache/huggingface/hub").expanduser()


def _model_in_local_cache(model_name: str) -> bool:
    """True when the sentence-transformers model can load with zero network calls.

    Either ``model_name`` is a local directory, or the HF hub cache already holds a
    snapshot of the repo (bare names resolve under the ``sentence-transformers/`` org,
    exactly as the library itself resolves them).
    """
    if Path(model_name).expanduser().is_dir():
        return True
    repo = model_name if "/" in model_name else f"sentence-transformers/{model_name}"
    snapshots = _hf_cache_dir() / f"models--{repo.replace('/', '--')}" / "snapshots"
    return snapshots.is_dir() and any(snapshots.iterdir())


def _silence_hf_progress_bars() -> None:
    """Ask the HF stack not to draw a load progress bar into OpenTorus's output.

    Loading the local embedding model draws a "Loading weights" tqdm bar on
    stderr, interleaved with OpenTorus's own diagnostics on every command that
    touches retrieval. Setting the documented switch is what turns it off;
    redirecting the stream instead would also swallow real diagnostics. Only a
    default is set, so an operator who wants the bar can still export it.
    """
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")


class SentenceTransformerEmbedder:
    """Adapter over ``sentence-transformers`` (loaded lazily, offline once cached)."""

    def __init__(self, model_name: str) -> None:
        _silence_hf_progress_bars()
        from sentence_transformers import SentenceTransformer

        self.model_name = model_name
        cached = _model_in_local_cache(model_name)
        if not cached:
            # The one permitted network call: see the module docstring for the
            # first-download egress exception.
            logger.info(
                "Embedding model '%s' is not in the local HF cache; the first load "
                "downloads it from huggingface.co (one-time network egress — all "
                "subsequent loads are fully offline).",
                model_name,
            )
        # A warm start must make zero network calls: local_files_only=True stops the
        # HF hub from revalidating the 'main' ref against huggingface.co on init.
        self._model = SentenceTransformer(model_name, local_files_only=cached)

    def encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            _truncate(texts), normalize_embeddings=True, show_progress_bar=False
        )
        return [list(map(float, v)) for v in vectors]


class OpenAIEmbedder:
    """``/v1/embeddings`` on the configured OpenAI-compatible endpoint (``OPENAI_API_KEY``).

    Honours ``model.base_url`` like the chat provider does: with a local vLLM/llama.cpp
    server configured, the embedder used to build the client with the SDK defaults and
    sent workspace text (artifact titles and bodies) to api.openai.com — off-machine,
    against the workspace's own locality — before failing on the bogus key.
    """

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
        from opentorus.providers.openai_provider import openai_client_kwargs

        client = OpenAI(**openai_client_kwargs(self._config))
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
        # ``model.base_url`` names an Ollama server only when the chat provider is Ollama;
        # for any other provider it is that provider's endpoint (a vLLM server has no
        # ``/api/embed``), so the embedder falls back to the default local Ollama host.
        host = config.model.base_url if config.model.provider == "ollama" else None
        self._host = (host or _OLLAMA_DEFAULT_HOST).rstrip("/")
        self._keep_alive = config.model.keep_alive

    def encode(self, texts: list[str]) -> list[list[float]]:
        trimmed = _truncate(texts)
        out: list[list[float]] = []
        for start in range(0, len(trimmed), _ENCODE_BATCH):
            batch = trimmed[start : start + _ENCODE_BATCH]
            body: dict[str, object] = {"model": self.model_name, "input": batch}
            if self._keep_alive is not None:
                body["keep_alive"] = self._keep_alive
            payload = json.dumps(body).encode("utf-8")
            request = urllib.request.Request(
                f"{self._host}/api/embed",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=120) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Timed out after 120s embedding a batch via Ollama at {self._host}. "
                    "A read timeout is a bare TimeoutError (an OSError, not a URLError), "
                    "so it must be handled here or it escapes as a traceback."
                ) from exc
            except OSError as exc:
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


# One loaded sentence-transformers model per process: ``load_embedder`` runs on every
# agent turn, and constructing the model each time re-reads the weights (seconds) —
# the mock-provider test suite tripled in wall time the day the package was installed.
_LOCAL_CACHE: dict[str, SentenceTransformerEmbedder] = {}


def _try_local(config: Config) -> Embedder | None:
    model_name = _embedding_model_for(config, "local")
    cached = _LOCAL_CACHE.get(model_name)
    if cached is not None:
        return cached
    try:
        embedder = SentenceTransformerEmbedder(model_name)
    except Exception as exc:
        logger.debug("Local embeddings unavailable (%s).", exc)
        return None
    _LOCAL_CACHE[model_name] = embedder
    return embedder


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
        # A *local* OpenAI-compatible endpoint (vLLM, llama.cpp, a proxy) is a chat
        # server, not OpenAI: it usually serves no embedding model, and it is not where
        # workspace text should go for one. Stay on "auto" so the local backend comes
        # first (see ``_attempt_order``); a real OpenAI base URL keeps the OpenAI embedder.
        from opentorus.usage import is_local_base_url

        if is_local_base_url(config.model.base_url):
            return "auto"
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
        # only reached for a local OpenAI-compatible endpoint: embed on this machine
        # (sentence-transformers) when installed; else ask that endpoint (it may serve an
        # embedding model); the workspace's Ollama default host last.
        return ["local", "openai", "ollama"]
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
